"""综合问答:知识图谱(结构化) + 实时数据源(天气 API / 联网搜索)融合。

分工:
  - 图谱负责:商家名称、评分、人均、地址、商圈、营业时间、电话、关系
  - 天气 API 负责:实况与预报(结构化、准确)
  - 联网搜索负责:活动、临时变动、新闻等图谱外信息
  - 最后统一由 LLM 综合成答复,并**标注每条外部信息的来源**
"""
import os
import re
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import requests

from src.llm_qa import call_llm
from src.web_search import dedupe, web_search

BASE = Path(__file__).resolve().parent.parent
AMAP_KEY_FILE = BASE / "amap_key.txt"

# 触发联网的关键词
WEB_TRIGGERS = [
    "天气", "气温", "下雨", "下雪", "刮风", "温度", "冷", "热",
    "活动", "展览", "演出", "演唱会", "集市", "庙会", "赛事",
    "最近", "近期", "现在", "今天", "明天", "这周", "本周", "周末",
    "新闻", "消息", "怎么样", "火不火", "评价如何", "口碑",
    "有什么新", "推荐去", "值得去", "好玩",
]

WEATHER_TRIGGERS = ["天气", "气温", "温度", "下雨", "下雪", "刮风", "冷不冷", "热不热", "多少度"]

SYNTH_PROMPT = """你是本地生活助手,要综合三类信息回答用户问题。

【知识图谱数据】(结构化,商家信息以此为准)
{graph_data}

【实时天气】(来自高德地图天气 API,准确可靠)
{weather_data}

【联网搜索结果】(实时外部信息,引用时必须标注来源)
{web_data}

要求:
1. 商家相关问题优先用知识图谱数据(名称/评分/人均/营业时间/地址最准)
2. 天气问题直接用「实时天气」的数据回答,标注来源:高德天气
3. 活动/近期动态用联网结果,标注来源:xxx
4. 可以结合判断(例如"今天下雨,建议去室内景点"、"气温低,适合吃火锅")
5. 两类信息都不足时如实说明,不要编造
6. 控制在 300 字以内,语言自然亲切"""


def _amap_key() -> str:
    key = os.environ.get("AMAP_KEY", "").strip()
    if not key and AMAP_KEY_FILE.exists():
        key = AMAP_KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        try:
            import streamlit as st
            key = str(st.secrets.get("AMAP_KEY", "")).strip()
        except Exception:
            pass
    return key


def fetch_weather(city_adcode: str = "150900") -> str:
    """获取乌兰察布实况+预报天气(高德 API)。返回可读文本。"""
    key = _amap_key()
    if not key:
        return ""
    out = []
    try:
        r = requests.get(
            "https://restapi.amap.com/v3/weather/weatherInfo",
            params={"key": key, "city": city_adcode, "extensions": "base", "output": "JSON"},
            timeout=10,
        )
        for l in r.json().get("lives", []) or []:
            out.append(
                f"实况:{l.get('city')} {l.get('weather')} {l.get('temperature')}℃ "
                f"{l.get('winddirection')}风{l.get('windpower')}级 湿度{l.get('humidity')}%"
            )
        r = requests.get(
            "https://restapi.amap.com/v3/weather/weatherInfo",
            params={"key": key, "city": city_adcode, "extensions": "all", "output": "JSON"},
            timeout=10,
        )
        for c in r.json().get("forecasts", []) or []:
            for cast in (c.get("casts") or [])[:3]:
                out.append(
                    f"预报 {cast.get('date')}({cast.get('week')}):"
                    f"{cast.get('dayweather')} {cast.get('daytemp')}~{cast.get('nighttemp')}℃"
                )
    except Exception:
        pass
    return "\n".join(out)


def needs_web(question: str) -> bool:
    """判断问题是否需要联网补充。"""
    return any(k in (question or "") for k in WEB_TRIGGERS)


def needs_weather(question: str) -> bool:
    return any(k in (question or "") for k in WEATHER_TRIGGERS)


def build_search_query(question: str, graph_records: list) -> str:
    """构造搜索词:带上问题里的关键实体,提高相关性。"""
    q = question
    if "乌兰察布" not in q and len(q) < 20:
        q = f"乌兰察布 {q}"
    for w in ["有哪些", "是什么", "怎么样", "吗?", "吗", "?", "?"]:
        q = q.replace(w, " ")
    return re.sub(r"\s+", " ", q).strip()[:60]


def fetch_web_context(question: str, graph_records: list = None) -> list:
    """按需联网,返回结果列表(带来源)。"""
    if not needs_web(question):
        return []
    query = build_search_query(question, graph_records)
    try:
        return dedupe(web_search(query, max_results=6))[:4]
    except Exception:
        return []


def synthesize_with_sources(question: str, graph_data: str,
                            web_results: list, weather_text: str = "") -> str:
    """融合三类信息,生成带来源标注的回答。"""
    if web_results:
        web_txt = "\n\n".join(
            f"[{i + 1}] {r['title']}\n"
            f"    内容:{r['snippet']}\n"
            f"    来源:{r['source']}({r['url']})"
            for i, r in enumerate(web_results)
        )
    else:
        web_txt = "(本次未获取到联网信息)"

    msgs = [
        {"role": "system", "content": "你在回答用户关于乌兰察布本地生活的问题。"},
        {"role": "user", "content": SYNTH_PROMPT.format(
            graph_data=graph_data or "(无)",
            weather_data=weather_text or "(本次未查询天气)",
            web_data=web_txt,
        )},
        {"role": "user", "content": f"用户问题:{question}"},
    ]
    return call_llm(msgs, temperature=0.2, max_tokens=700)


def hybrid_answer(question: str, graph_data: str, graph_records: list = None) -> dict:
    """完整流程:判断需求 → 取天气/联网 → 融合回答。"""
    weather_text = fetch_weather() if needs_weather(question) else ""
    web_results = fetch_web_context(question, graph_records)
    answer = synthesize_with_sources(question, graph_data, web_results, weather_text)
    return {
        "answer": answer,
        "weather": weather_text,
        "web_results": web_results,
        "used_web": bool(web_results),
        "used_weather": bool(weather_text),
    }

