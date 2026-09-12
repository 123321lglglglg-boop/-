"""Multi-Query 模糊检索:把模糊问题扩展成多个具体查询,分别检索后合并。

适用场景(用户没提具体品类,但隐含了可查询的条件):
  - 场景:约会去哪 / 带娃去哪 / 朋友聚会
  - 时间:晚上玩什么 / 早餐 / 宵夜
  - 目的:想放松 / 想逛街 / 想运动
  - 人群:适合老人 / 适合小孩 / 情侣
  - 预算:便宜点 / 高档 / 性价比
  - 偏好:清淡 / 素食 / 不喝酒
  - 场合:生日 / 商务宴请 / 纪念日
  - 情绪:无聊 / 想发呆 / 心情不好

流程:模糊问题 → LLM 扩展成 N 个子查询(Cypher)→ 各自执行 → 合并去重 → 综合回答
"""
import json
import re
import warnings

warnings.filterwarnings("ignore")

from src.llm_qa import SCHEMA_DESC, call_llm, clean_cypher, is_readonly, run_cypher

MAX_SUB_QUERIES = 4


def _category_catalog() -> str:
    """从数据库动态生成品类清单(保证提示词里的名称永远真实存在)。"""
    try:
        rows = _run(
            """
            MATCH (p:POI)-[:属于细类]->(c:CategoryL3)
            RETURN c.name AS name, count(p) AS cnt
            ORDER BY cnt DESC
            """
        )
    except Exception:
        return ""
    if not rows:
        return ""
    # 只保留有一定规模的品类(>=3 家),避免噪音
    names = [r["name"] for r in rows if (r["cnt"] or 0) >= 3 and r["name"]]
    return "、".join(names)


def _run(cypher: str, **params):
    """简单查询封装(供品类清单使用)。"""
    from src.llm_qa import run_cypher
    return run_cypher(cypher, **params)


def build_expand_prompt() -> str:
    """构造扩展提示词(含动态品类清单)。"""
    catalog = _category_catalog()
    catalog_section = (
        f"\n5. **只能使用以下真实存在的细类名**(等值匹配,一字不差):\n   {catalog}\n"
        if catalog else ""
    )
    return f"""你是本地生活检索专家。用户的问题比较模糊,没有指明具体品类。
你需要把它拆解成 **{MAX_SUB_QUERIES} 个具体可执行的检索意图**,每个意图对应一条 Cypher 查询。

{SCHEMA_DESC}

常见模糊问题的拆解参考:
- "晚上有什么玩的" → KTV、酒吧、电影院、网吧、夜景/景点
- "情侣约会去哪" → 咖啡厅、西餐厅、电影院、景点
- "带小孩去哪" → 游乐场、公园/风景名胜、快餐厅、甜品店
- "想放松一下" → 咖啡厅、茶艺馆、洗浴推拿场所、公园
- "想运动" → 健身中心、综合体育馆、运动场所、台球厅
- "早餐吃什么" → 快餐厅、中餐厅(包子面馆)、糕饼店
- "商务宴请" → 综合酒楼、高档餐厅(人均>100)、特色/地方风味餐厅
- "便宜又好吃" → 人均<=40 的中餐厅/快餐厅,评分>=4.0
- "想逛街" → 普通商场、购物中心、商场

要求:
1. 只返回 JSON 数组,不要 markdown 代码块标记,不要解释
2. 每个元素包含两个字段:
   - "intent": 该子查询的中文意图描述(如"KTV 唱歌")
   - "cypher": 对应的 Cypher 查询语句
3. Cypher 要求:
   - 只读查询(MATCH/OPTIONAL MATCH/WHERE/RETURN/ORDER BY/LIMIT/WITH)
   - **RETURN 必须使用中文别名**,严格按此格式:
     RETURN p.name AS 名称, p.rating AS 评分, p.cost AS 人均, p.address AS 地址
   - 每个 LIMIT 8
   - 优先返回评分高的:ORDER BY p.rating DESC
4. **品类匹配必须用精确等值,禁止模糊匹配**:
   - ✅ 正确:`MATCH (p:POI)-[:属于细类]->(c:CategoryL3) WHERE c.name = 'KTV'`
   - ❌ 错误:`WHERE c.name CONTAINS 'KTV' OR c.name CONTAINS '歌厅'`
   - ❌ 错误:`WHERE c.name CONTAINS '娱乐'`
   - 一个查询里最多用 `OR` 连接 **2 个同义细类名**,且都必须在下面清单里
{catalog_section}   如果清单里没有合适的品类,改用店名匹配:`p.name CONTAINS '关键词'`
   (如日料 → p.name CONTAINS '料理')
6. 子查询要覆盖不同角度,不要重复
"""


# 列名容错:LLM 有时用原始名(p.name)、有时用中文别名(名称)
FIELD_ALIASES = {
    "名称": ["名称", "name", "p.name", "店名", "门店", "商家", "店铺"],
    "评分": ["评分", "rating", "p.rating", "分数", "打分"],
    "人均": ["人均", "cost", "p.cost", "人均消费", "价格", "消费"],
    "地址": ["地址", "address", "p.address", "位置", "详细地址"],
}


SYNTH_PROMPT = """用户问了一个比较模糊的问题,你通过多个角度的检索找到了以下结果。

【用户的原始问题】
{question}

【各角度的检索结果】(这是你能拿到的全部真实数据)
{results}

要求:
1. 按**不同场景/需求**分类推荐,让用户一眼看到选择(如"想唱歌"、"想安静聊天"、"想看电影")
2. 每个推荐只写数据里有的字段:名称、评分、人均、地址
3. **严禁编造**:不要添加数据里没有的描述(如"包厢新"、"驻唱不错"、"环境优雅"、
   "适合学生党"等)。你只能基于名称/评分/人均/地址做客观推荐。
4. 可以基于数据做合理推断并说明依据,例如"评分4.7,值得优先考虑"、
   "人均30元,比较实惠"——这类推断必须来自数据
5. 优先推荐评分高的
6. 最后给一句基于数据的建议(如"评分最高的是XX")
7. 控制在 350 字以内,分类清晰,用 markdown 列表
8. 不要提"根据检索结果"这类话,直接给建议"""


def is_vague(question: str, cypher: str = "") -> bool:
    """判断问题是否模糊(需要 multi-query 扩展)。

    判断依据:问题里没有明确的品类词,且原始查询返回结果很少或为空。
    """
    q = question or ""
    # 明确品类词 → 不算模糊
    explicit = [
        "火锅", "烧烤", "蒙餐", "莜面", "烧麦", "咖啡", "酒店", "宾馆",
        "景点", "KTV", "酒吧", "网吧", "电影", "商场", "超市", "医院",
    ]
    if any(k in q for k in explicit):
        return False
    # 明确店名(含"店/馆/楼/城/家"等) → 大概率不模糊
    if re.search(r"[一-龥]{2,10}(店|馆|楼|城|公司|银行)", q):
        return False
    # 模糊信号词
    vague_signals = [
        "有什么", "哪些地方", "去哪", "去哪里", "玩玩", "好玩", "逛",
        "放松", "约会", "聚会", "带娃", "带小孩", "适合", "推荐",
        "晚上", "晚上有", "早餐", "宵夜", "夜宵", "周末",
        "无聊", "想找", "有什么好", "怎么办",
    ]
    if any(k in q for k in vague_signals):
        return True
    return False


def expand_queries(question: str) -> list:
    """把模糊问题扩展成多个子查询。返回 [{"intent":…, "cypher":…}, …]。"""
    try:
        raw = call_llm([
            {"role": "system", "content": build_expand_prompt()},
            {"role": "user", "content": f"用户问题:{question}"},
        ], temperature=0.3, max_tokens=1100)
    except Exception:
        return []

    # 解析 JSON(容错:去掉可能的代码块标记)
    txt = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m:
        txt = m.group(1).strip()
    if not txt.startswith("["):
        i, j = txt.find("["), txt.rfind("]")
        if i >= 0 and j > i:
            txt = txt[i:j + 1]

    try:
        items = json.loads(txt)
    except Exception:
        return []

    out = []
    for it in items[:MAX_SUB_QUERIES]:
        if not isinstance(it, dict):
            continue
        cypher = clean_cypher(str(it.get("cypher", "")))
        intent = str(it.get("intent", "")).strip()
        if cypher and intent and is_readonly(cypher):
            out.append({"intent": intent, "cypher": cypher})
    return out


def execute_multi(sub_queries: list) -> list:
    """执行多个子查询,返回 [{intent, cypher, records, error}, …]。"""
    results = []
    for sq in sub_queries:
        try:
            recs = run_cypher(sq["cypher"])
            results.append({"intent": sq["intent"], "cypher": sq["cypher"],
                            "records": recs, "error": None})
        except Exception as e:
            results.append({"intent": sq["intent"], "cypher": sq["cypher"],
                            "records": [], "error": str(e)[:120]})
    return results


def merge_records(sub_results: list) -> list:
    """合并所有子查询结果并按店名去重,保留最高分。"""
    seen = {}
    for r in sub_results:
        for rec in r.get("records", []):
            key = rec.get("名称") or rec.get("name") or json.dumps(rec, default=str)[:40]
            if key not in seen:
                rec = dict(rec)
                rec["_intent"] = r["intent"]
                seen[key] = rec
    merged = list(seen.values())
    merged.sort(key=lambda x: (x.get("评分") or 0), reverse=True)
    return merged


def pick(rec: dict, field: str, default=None):
    """容错取值:按中文别名逐个别名尝试。"""
    for k in FIELD_ALIASES.get(field, [field]):
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return default


def synthesize_multi(question: str, sub_results: list) -> str:
    """综合多个角度的检索结果,生成分类推荐。"""
    blocks = []
    for r in sub_results:
        recs = r.get("records") or []
        if not recs:
            continue
        lines = []
        for x in recs[:6]:
            name = pick(x, "名称")
            if not name:
                continue
            rating = pick(x, "评分")
            cost = pick(x, "人均")
            addr = pick(x, "地址")
            parts = [str(name)]
            if rating:
                parts.append(f"{rating}分")
            if cost:
                parts.append(f"人均{cost}元")
            if addr:
                parts.append(str(addr)[:30])
            lines.append("  - " + " | ".join(parts))
        if lines:
            blocks.append(f"【{r['intent']}】\n" + "\n".join(lines))

    if not blocks:
        return "抱歉,没有找到合适的推荐。可以告诉我更具体一点的需求,比如想吃什么类型、预算多少。"

    msgs = [
        {"role": "system", "content": "你是熟悉乌兰察布本地的向导。"},
        {"role": "user", "content": SYNTH_PROMPT.format(
            question=question, results="\n\n".join(blocks))},
    ]
    return call_llm(msgs, temperature=0.3, max_tokens=800)


def multi_query_answer(question: str) -> dict:
    """完整流程:扩展 → 检索 → 合并 → 综合。"""
    sub_queries = expand_queries(question)
    if not sub_queries:
        return {"ok": False, "queries": [], "results": [], "records": [], "answer": ""}

    sub_results = execute_multi(sub_queries)
    merged = merge_records(sub_results)
    answer = synthesize_multi(question, sub_results)
    return {
        "ok": True,
        "queries": sub_queries,
        "results": sub_results,
        "records": merged,
        "answer": answer,
    }
