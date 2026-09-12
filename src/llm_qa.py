"""LLM 增强问答:Text2Cypher + 答案生成(DeepSeek API)。

功能:
  1. Text2Cypher:自然语言问题 → LLM 生成 Cypher → 只读校验 → 执行
  2. 答案生成:图谱查询结果 → LLM 总结成自然语言回答
  3. 失败自动重试:把错误信息回传给 LLM 让它修正

用法:
    python src/llm_qa.py "集宁区人均50以下的餐厅推荐几家"
"""
import json
import os
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import requests
from neo4j import GraphDatabase

BASE = Path(__file__).resolve().parent.parent
KEY_FILE = BASE / "deepseek_key.txt"

from src.config import neo4j_config

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

# 图谱本体描述,喂给 LLM 帮助它写对 Cypher
SCHEMA_DESC = """
节点类型与属性:
- POI(商家): poi_id, name, address, rating(评分0~5), cost(人均元), tel, open_hours, is_chain, lng, lat
- District(区县): name (乌兰察布下辖:集宁区、丰镇市、卓资县、化德县、商都县、兴和县、凉城县、察右前旗、察右中旗、察右后旗、四子王旗)
- BusinessArea(商圈): name, district, size(商家数)
- CategoryL1(粗类): name (餐饮服务、住宿服务、风景名胜、购物服务等)
- CategoryL3(细类): name (中餐厅、宾馆酒店、快餐厅、火锅店、风景名胜、特色/地方风味餐厅、咖啡厅、清真菜馆、综合酒楼、普通商场、寺庙道观、甜品店、经济型连锁酒店、四川菜(川菜)等)
- Chain(连锁品牌): chain_id, name
- PriceLevel(价格带): name (经济<=30, 大众31-60, 中档61-120, 高端>120)
- RatingTier(评分档): name (高分>=4.5, 良好4.0-4.4, 一般3.5-3.9, 较低<3.5)

关系(有方向):
- (POI)-[:位于]->(District)
- (POI)-[:位于商圈]->(BusinessArea)
- (POI)-[:属于品类]->(CategoryL1)
- (POI)-[:属于细类]->(CategoryL3)
- (CategoryL3)-[:子类]->(CategoryL1)
- (POI)-[:连锁品牌]->(Chain)
- (POI)-[:价位]->(PriceLevel)
- (POI)-[:评分档]->(RatingTier)
- (POI)-[:邻近 {距离}]->(POI)   同商圈内距离<300米的商家
- (Chain)-[:主营]->(CategoryL2)
- (BusinessArea)-[:属于区县]->(District)

常用查询模式:
- 按区县找商家: MATCH (p:POI)-[:位于]->(d:District {name:'集宁区'})
- 按细类: MATCH (p:POI)-[:属于细类]->(c:CategoryL3 {name:'火锅店'})
- 按店名: WHERE p.name CONTAINS '蒙餐'
- 价格条件: WHERE p.cost <= 50 AND p.cost > 0
- 评分条件: WHERE p.rating >= 4.5
- 找邻近: MATCH (p:POI {name:'X'})-[:邻近]->(q:POI)
- 品牌门店: MATCH (p:POI)-[:连锁品牌]->(c:Chain) WHERE c.name CONTAINS '肯德基'
"""

TEXT2CYPHER_PROMPT = f"""你是 Neo4j Cypher 专家。根据下面的图数据库结构,把用户的自然语言问题转成一条 Cypher 查询。

{SCHEMA_DESC}

要求:
1. 只返回 Cypher 语句本身,不要任何解释、不要 markdown 代码块标记
2. 只允许 MATCH / OPTIONAL MATCH / WHERE / RETURN / ORDER BY / LIMIT / WITH / COUNT / collect / DISTINCT
3. 禁止任何写操作(CREATE/DELETE/SET/MERGE/REMOVE/DROP/CALL)
4. 返回的列名用中文别名,如 RETURN p.name AS 名称, p.rating AS 评分
5. 结果默认 LIMIT 20,除非用户明确要更多
6. **店名必须用 CONTAINS 模糊匹配,禁止用精确等值匹配**。
   数据库里的店名通常带后缀,例如用户说「乌兰图雅蒙餐」,
   实际存的是「乌兰图雅·蒙餐(乌兰察布怡海佳苑店)」。
   正确写法:MATCH (p:POI) WHERE p.name CONTAINS '乌兰图雅'
   错误写法:MATCH (p:POI {{name:'乌兰图雅蒙餐'}})
7. 用 CONTAINS 时只取店名的核心词(2-6 字),不要带后缀或括号内容
"""

ANSWER_PROMPT = """你是本地生活助手。根据知识图谱查询结果,用自然、简洁的中文回答用户问题。

要求:
1. 直接回答问题,不要提"根据查询结果"这类话
2. 如果结果里有评分、人均、地址等,挑重点信息说
3. 结果为空时,如实说没找到,并给出可能的原因(如换个区县/关键词)
4. 不要编造结果里没有的信息
5. 控制在 200 字以内"""

FORBIDDEN = re.compile(
    r"\b(CREATE|DELETE|SET|MERGE|REMOVE|DROP|CALL|LOAD\s+CSV|FOREACH|APOC)\b",
    re.IGNORECASE,
)
CYPHER_BLOCK = re.compile(r"```(?:cypher)?\s*(.*?)```", re.S | re.IGNORECASE)

# 多轮对话:把历史转成上下文,让"那评分高的呢"这类追问能被理解
CONTEXT_PROMPT = """下面是用户之前的对话。如果当前问题是追问(比如"那XX呢"、"还有吗"、
"换成XX"),请结合上下文补全意图再生成 Cypher;如果是全新问题,忽略历史即可。

历史对话(用户问 → 你生成的查询要点):
{history}

当前问题:{question}"""


def format_history(history: list, max_turns: int = 4) -> str:
    """把对话历史整理成 LLM 可读的上下文。

    history: [{"q": 用户问题, "cypher": 上次生成的查询, "answer": 上次回答}, ...]
    """
    if not history:
        return "(无)"
    lines = []
    for h in history[-max_turns:]:
        lines.append(f"- 用户:{h['q']}")
        if h.get("cypher"):
            lines.append(f"  上次查询:{h['cypher']}")
        if h.get("answer"):
            ans = h["answer"].replace("\n", " ")[:120]
            lines.append(f"  上次回答:{ans}")
    return "\n".join(lines)


def make_messages(question: str, history: list = None) -> list:
    """构造发送给 LLM 的消息(含多轮上下文)。"""
    msgs = [{"role": "system", "content": TEXT2CYPHER_PROMPT}]
    if history:
        ctx = CONTEXT_PROMPT.format(history=format_history(history), question=question)
        msgs.append({"role": "user", "content": ctx})
    else:
        msgs.append({"role": "user", "content": question})
    return msgs

# ---- 公网部署限流:防止 API key 被刷 ----
_RATE = {"window_start": 0.0, "count": 0}
RATE_LIMIT_PER_MIN = 8      # 每 IP 每分钟
RATE_LIMIT_DAILY = 120      # 每 IP 每天
_daily = {"day": "", "per_ip": {}}


class RateLimited(Exception):
    pass


def check_rate_limit(client_id: str = "anon"):
    """简单的内存限流(单进程足够;多副本部署需换 Redis)。"""
    import time as _t
    now = _t.time()

    # 每分钟
    if now - _RATE["window_start"] > 60:
        _RATE["window_start"] = now
        _RATE["count"] = 0
    if _RATE["count"] >= RATE_LIMIT_PER_MIN:
        raise RateLimited("请求太频繁,请稍后再试(每分钟限 8 次)")
    _RATE["count"] += 1

    # 每天
    today = _t.strftime("%Y-%m-%d")
    if _daily["day"] != today:
        _daily["day"] = today
        _daily["per_ip"] = {}
    used = _daily["per_ip"].get(client_id, 0)
    if used >= RATE_LIMIT_DAILY:
        raise RateLimited("今日额度已用完,明天再来试试")
    _daily["per_ip"][client_id] = used + 1


def get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        # 云端部署:从 Streamlit secrets 读取
        try:
            import streamlit as st
            key = str(st.secrets.get("DEEPSEEK_API_KEY", "")).strip()
        except Exception:
            pass
    return key


def call_llm(messages: list, temperature: float = 0.1, max_tokens: int = 800) -> str:
    key = get_api_key()
    if not key:
        raise RuntimeError("未配置 DeepSeek key(deepseek_key.txt 或 DEEPSEEK_API_KEY)")
    r = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": messages,
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def call_llm_stream(messages: list, temperature: float = 0.1, max_tokens: int = 800):
    """流式调用,逐块 yield 文本(用于打字机效果)。"""
    key = get_api_key()
    if not key:
        raise RuntimeError("未配置 DeepSeek key(deepseek_key.txt 或 DEEPSEEK_API_KEY)")
    r = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": messages, "stream": True,
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=90,
        stream=True,
    )
    r.raise_for_status()
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload.strip() == "[DONE]":
            break
        try:
            delta = json.loads(payload)["choices"][0].get("delta", {})
            chunk = delta.get("content")
            if chunk:
                yield chunk
        except (ValueError, KeyError, IndexError):
            continue


def clean_cypher(text: str) -> str:
    m = CYPHER_BLOCK.search(text)
    if m:
        text = m.group(1)
    text = text.strip().strip("`").strip()
    # 去掉可能的前缀说明行
    lines = [l for l in text.split("\n") if l.strip()]
    while lines and not re.match(r"^\s*(MATCH|OPTIONAL|WITH|RETURN|UNWIND)", lines[0], re.I):
        lines.pop(0)
    return "\n".join(lines).strip().rstrip(";")


def is_readonly(cypher: str) -> bool:
    return not FORBIDDEN.search(cypher)


def run_cypher(cypher: str):
    uri, auth = neo4j_config()
    d = GraphDatabase.driver(uri, auth=auth)
    try:
        with d.session() as s:
            return [dict(r) for r in s.run(cypher)]
    finally:
        d.close()


def text2cypher(question: str, max_retry: int = 2, history: list = None) -> tuple:
    """自然语言 → Cypher,失败时带错误信息重试。返回 (cypher, records, error)。

    history: 多轮对话历史,用于理解追问。
    """
    messages = make_messages(question, history)
    last_err = None
    for attempt in range(max_retry + 1):
        cypher = clean_cypher(call_llm(messages))
        if not is_readonly(cypher):
            last_err = "生成的语句包含写操作,已拒绝"
            messages += [
                {"role": "assistant", "content": cypher},
                {"role": "user", "content": "你生成的语句包含写操作(如 CREATE/SET/MERGE),请只生成只读查询。"},
            ]
            continue
        try:
            records = run_cypher(cypher)
            return cypher, records, None
        except Exception as e:
            last_err = str(e)[:300]
            messages += [
                {"role": "assistant", "content": cypher},
                {"role": "user", "content": f"执行报错: {last_err}\n请修正后重新生成 Cypher。"},
            ]
    return "", [], last_err


def generate_answer(question: str, records: list, history: list = None) -> str:
    if not records:
        data_txt = "(查询结果为空)"
    else:
        sample = records[:20]
        data_txt = json.dumps(sample, ensure_ascii=False, default=str, indent=1)

    user_content = f"用户问题:{question}\n\n查询结果({len(records)} 条,最多展示 20 条):\n{data_txt}"
    if history:
        # 让回答也能呼应上一轮(如"那这些里评分最高的是?")
        user_content = (
            f"上一轮对话(供参考):{format_history(history, 2)}\n\n{user_content}"
        )
    return call_llm([
        {"role": "system", "content": ANSWER_PROMPT},
        {"role": "user", "content": user_content},
    ])


def ask(question: str, client_id: str = "anon", history: list = None) -> dict:
    """完整流程:问题 → Cypher → 查询 → 自然语言答案。

    history: 多轮对话历史 [{q, cypher, answer}, ...],用于理解追问。
    """
    try:
        check_rate_limit(client_id)
    except RateLimited as e:
        return {"ok": False, "cypher": "", "records": [], "answer": str(e)}

    cypher, records, err = text2cypher(question, history=history)
    if err:
        return {"ok": False, "cypher": cypher, "records": [], "answer": f"查询失败:{err}"}
    answer_txt = generate_answer(question, records, history=history)
    return {"ok": True, "cypher": cypher, "records": records, "answer": answer_txt}


def main():
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
    else:
        q = input("问> ").strip()
    if not q:
        return
    result = ask(q)
    print(f"\nCypher:\n{result['cypher']}\n")
    print(f"结果 {len(result['records'])} 条")
    print(f"\n回答:{result['answer']}")


if __name__ == "__main__":
    main()
