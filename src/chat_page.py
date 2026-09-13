"""对话式搜索首页:多轮对话 + 流式回答。

产品思路:用户打开 app 第一眼就是搜索框,直接提问即可;
不用先找到"某个 tab"才能用核心功能。
"""
import warnings

warnings.filterwarnings("ignore")

import streamlit as st

from src.llm_qa import (
    RateLimited,
    ask,
    check_rate_limit,
    generate_answer,
    run_cypher,
    text2cypher,
)
from src.reasoning_path import extract_paths
from src.path_viz import render_paths_graph_html, render_paths_html
from src.hybrid_qa import (
    fetch_weather,
    fetch_web_context,
    needs_weather,
    needs_web,
)
from src.hybrid_retrieval import (
    plan,
    retrieve,
)
from src.qa_cache import (
    cache_key,
    cacheable,
    cached_embed,
    l1_get,
    l1_put,
    note_miss,
    semantic_lookup,
    semantic_store,
)
from src.source_viz import render_sources_html
from src.multi_query import is_vague, multi_query_answer
from src.multi_viz import render_multi_html
from src.feedback import save_feedback
from src.session_store import list_sessions, load_session, save_session
from src.compare import compare_stats, parse_compare, render_compare_html
from src.route_viz import render_route_html

EXAMPLES = [
    "集宁区人均50以下的餐厅有哪些",
    "评分最高的蒙餐馆在哪",
    "乌兰察布有多少家火锅店",
    "四子王旗有什么景点",
    "离乌兰图雅蒙餐最近的商家",
]

WELCOME = """你好 👋 我能查乌兰察布的 **6,949 个商家**。

直接问就行,也可以连续追问。"""


def _rehydrate(msgs: list) -> list:
    """把从库里读回的会话补齐渲染用的片段。

    path_html / route_html / mq_html / src_html 这些没落库(体积大且可重算),
    读回来时用 question + cypher + records 重新生成一遍,历史消息的展开面板
    才能和刚生成时一样。
    """
    for m in msgs:
        if m.get("role") != "assistant":
            continue
        try:
            _enrich(m, m.get("question") or "", [])
        except Exception:
            for k in ("path_html", "route_html", "mq_html", "src_html"):
                m.setdefault(k, "")
    return msgs


def init_state():
    if "chat" not in st.session_state:
        st.session_state.chat = []          # [{role, content, cypher, records}]
    if "pending" not in st.session_state:
        st.session_state.pending = None     # 待处理的问题(由示例按钮设置)

    if "sid" not in st.session_state:
        # 会话 ID 放 URL query param,刷新页面后仍是同一个会话。
        # 不能用 st.session_state 里的随机 client_id 当会话标识——那个刷新就变。
        sid = ""
        try:
            sid = st.query_params.get("s") or ""
        except Exception:
            sid = ""
        if not sid:
            import uuid
            sid = uuid.uuid4().hex[:12]
            try:
                st.query_params["s"] = sid
            except Exception:
                pass
        st.session_state["sid"] = sid
        # 首次进入时,如果这个 sid 在库里已经有历史(比如刷新页面),直接读回来
        if not st.session_state.chat:
            try:
                msgs = load_session(sid)
                if msgs:
                    st.session_state.chat = _rehydrate(msgs)
            except Exception:
                pass


def _save_session():
    """把当前会话写库(失败不影响对话)。"""
    try:
        save_session(
            st.session_state.get("sid", ""),
            st.session_state.get("client_id", "anon"),
            st.session_state.chat,
        )
    except Exception:
        pass


def _switch_session(sid: str, reset: bool = False):
    st.session_state["sid"] = sid
    st.session_state.chat = [] if reset else _rehydrate(load_session(sid))
    st.session_state["fb_state"] = {}
    try:
        st.query_params["s"] = sid
    except Exception:
        pass
    st.rerun()


def _render_history_menu():
    """历史会话入口(右上角)。放在 popover 里,不占首屏空间。"""
    try:
        sessions = list_sessions(st.session_state.get("client_id", "anon"), limit=15)
    except Exception:
        sessions = []

    with st.popover("🕘 历史"):
        st.caption("最近会话(存在 Neo4j,刷新不丢)")
        if not sessions:
            st.caption("还没有历史会话")
        cur = st.session_state.get("sid")
        for s in sessions:
            sid = s.get("sid") or ""
            title = (s.get("title") or "新会话")[:18]
            ts = (s.get("updated_at") or "")[:16]
            label = f"{'▶ ' if sid == cur else ''}{title} · {ts}"
            if st.button(label, key=f"hs_{sid}", use_container_width=True):
                _switch_session(sid)
        if st.button("➕ 新会话", key="hs_new", use_container_width=True):
            import uuid
            _switch_session(uuid.uuid4().hex[:12], reset=True)


def _example_clicked(q: str):
    st.session_state.pending = q


def render_examples():
    """示例问题按钮(仅在还没对话时展示)。

    手机上单列会撑高页面触发自动滚动,所以用两列网格布局。
    """
    if st.session_state.chat:
        return

    # 两列网格:手机上每行两个,高度减半
    rows = [EXAMPLES[i:i + 2] for i in range(0, len(EXAMPLES), 2)]
    for row in rows:
        cols = st.columns(2)
        for col, q in zip(cols, row):
            short = q if len(q) <= 11 else q[:10] + "…"
            if col.button(short, key=f"ex_{q}", use_container_width=True, help=q):
                _example_clicked(q)


def history_for_llm(max_turns: int = 4) -> list:
    """把对话历史转成 LLM 可用的上下文(只取问答对)。

    带上 route 字段:追问分流时需要继承上一轮的检索意图。
    """
    hist = []
    for m in st.session_state.chat:
        if m["role"] == "user":
            hist.append({"q": m["content"], "cypher": "", "answer": "", "route": ""})
        elif m["role"] == "assistant" and hist:
            hist[-1]["cypher"] = m.get("cypher", "")
            hist[-1]["answer"] = m.get("content", "")
            # route 存在 assistant 消息里,回溯给对应的问句
            ri = m.get("route_info") or {}
            hist[-1]["route"] = ri.get("route", "")
    return hist[-max_turns:]


def _kg_fn(question: str, history: list):
    """图谱检索入口,注入给 hybrid_retrieval.retrieve。

    返回 (cypher, records, err),records 的列名由 LLM 生成的 Cypher 决定
    (通常是 名称/评分/人均/区县 这类中文别名)。
    """
    cypher, records, err = text2cypher(question, history=history)
    return cypher, (records or []), err


def _cache_badge(result: dict) -> str:
    """缓存命中提示文案(空字符串表示未命中)。"""
    level = result.get("cache_level")
    if level == "exact":
        return "⚡ 命中精确缓存"
    if level == "semantic":
        sim = result.get("similarity")
        src_q = result.get("matched_question") or ""
        tip = "⚡ 命中语义缓存"
        if sim is not None:
            tip += f"(相似度 {sim:.3f}"
            if src_q:
                tip += f" · 原问题「{src_q}」"
            tip += ")"
        return tip
    return ""


def _render_answer(result: dict, mode: str):
    """渲染答案。

    mode:
      "streamed" —— 流式生成时已经边生成边写进 placeholder,这里不再重复渲染
      "exact"    —— 命中精确缓存,直接给出整段答案
      "semantic" —— 命中语义缓存,额外提示相似度
      "plain"    —— 一次性生成的答案(Multi-Query 分支)
    """
    if mode == "streamed":
        return
    badge = _cache_badge(result)
    if badge and mode != "plain":
        st.caption(badge)
    st.markdown(result.get("answer", ""))


def _enrich(result: dict, question: str, history: list) -> dict:
    """把渲染用的 HTML 片段补齐,让缓存命中的那次也能原样展示。"""
    route_info = result.get("route_info") or {}
    result["route_html"] = (
        render_route_html(route_info)
        if route_info.get("route") in ("semantic", "hybrid") else ""
    )

    mi = result.get("multi_info")
    result["mq_html"] = (
        render_multi_html(mi["queries"], mi["results"]) if mi else ""
    )

    result["path_html"] = ""
    result["paths"] = []
    if (result.get("records") and not mi
            and route_info.get("route") != "semantic"):
        try:
            paths = extract_paths(question, result.get("cypher") or "",
                                  result["records"])
            if paths:
                # 原始路径数据也留着:渲染图要用它,而且它很小,
                # 存缓存/存库都不会撑爆(渲染好的 HTML 内联了 echarts,有 1MB 不能存)
                result["paths"] = paths
                result["path_html"] = render_paths_html(paths)
        except Exception:
            result["path_html"] = ""

    result["src_html"] = (
        render_sources_html(result.get("web_results") or [],
                            result.get("weather_text") or "")
        if (result.get("web_results") or result.get("weather_text")) else ""
    )

    result["compare_html"] = render_compare_html(result.get("compare_info") or {})
    return result


def _cache_put(key: str, question: str, search_query: str,
               is_fq: bool, result: dict, route: str, qvec):
    """写入 L1 + L3。"""
    l1_put(key, result)
    if is_fq:
        # 追问不写语义缓存:它的含义依赖上文,换个上下文就完全不是一回事
        return
    vec = qvec
    if not vec:
        vec = cached_embed(search_query)
    if vec:
        semantic_store(question, vec, result, route)


def _answer_with_stream(question: str, history: list) -> dict:
    """检索 + 生成回答,带三级缓存(见 src/qa_cache.py)。

    检索优先级(GraphRAG 架构):
      1. 走向量:问题含主观/体验类语义信号 → 语义检索最准
      2. 走图谱:结构化条件(人均/数量/评分/关系)
      3. 走 Multi-Query:图谱和向量都难以覆盖的宽泛场景问题

    返回 dict(而非元组),这样整块结果能直接进缓存:
      {answer, cypher, records, web_results, weather_text, multi_info,
       route_info, path_html, src_html, route_html, mq_html, cache_level}
    """
    route, search_query, fq = plan(question, history)

    # 追问但找不到上下文锚点时绕过缓存(原因见 qa_cache.cacheable 的说明)
    use_cache = cacheable(question, history)

    # ---- ① 精确缓存 ----
    key = cache_key(question, route, history)
    if use_cache:
        hit = l1_get(key)
        if hit:
            # 缓存里存的 payload 其 cache_level 是写入时的 "miss",
            # 必须覆盖成 "exact",否则命中提示和消息里的徽标都不会显示
            hit = dict(hit)
            hit["cache_level"] = "exact"
            _render_answer(hit, "exact")
            return hit

    # ---- ③ 语义缓存(在跑任何 LLM 之前判定)----
    # 追问不走语义缓存:追问的意思依赖上文,语义上不可跨会话复用
    qvec = ()
    if use_cache and not fq:
        qvec = cached_embed(search_query)
        if qvec:
            sem = semantic_lookup(qvec, route)
            if sem:
                result = {
                    "answer": sem.get("answer", ""),
                    "cypher": sem.get("cypher", ""),
                    "records": sem.get("records", []),
                    "web_results": sem.get("web_results", []),
                    "weather_text": sem.get("weather_text", ""),
                    "multi_info": None,
                    "route_info": sem.get("route_info"),
                    "compare_info": sem.get("compare_info"),
                    "cache_level": "semantic",
                    "similarity": sem.get("similarity"),
                    "matched_question": sem.get("matched_question"),
                }
                _enrich(result, question, history)
                _render_answer(result, "semantic")
                l1_put(key, result)
                return result

    # ---- ② 对比分析(文档第二部分 5)----
    # 识别到"X 和 Y 的对比"就直接走对比统计,不再走检索
    compare_info = None
    res = None
    if not fq:
        try:
            comp = parse_compare(question)
        except Exception:
            comp = None
        if comp:
            try:
                info = compare_stats(comp["a"], comp["b"], comp.get("label", ""))
            except Exception:
                info = {}
            if info:
                compare_info = info
                res = {
                    "route": "compare", "cypher": "",
                    "records": info["rows"], "err": None,
                    "kg_count": len(info["rows"]), "vec_count": 0,
                    "search_query": search_query, "is_followup": fq,
                    "vector_used": False,
                }

    # ---- ③ 未命中且不是对比题:宽泛场景走 Multi-Query ----
    if res is None and is_vague(question) and not fq and route == "structured":
        with st.spinner("正在从多个角度检索…"):
            mq = multi_query_answer(question)
        if mq.get("ok") and mq.get("records"):
            flat = [rec for sr in mq["results"] for rec in sr["records"]]
            result = {
                "answer": mq["answer"], "cypher": "", "records": flat,
                "web_results": [], "weather_text": "",
                "multi_info": {"queries": mq["queries"], "results": mq["results"],
                               "merged": mq["records"]},
                "route_info": None,
                "cache_level": "miss",
            }
            _enrich(result, question, history)
            _render_answer(result, "plain")
            if use_cache:
                _cache_put(key, question, search_query, fq, result, route, qvec)
            return result

    # ---- ④ 完整链路 ----
    if res is None:
        with st.spinner("正在检索…"):
            res = retrieve(question, _kg_fn, history=history)

    route_info = {
        "route": res["route"],
        "kg_count": res["kg_count"],
        "vec_count": res["vec_count"],
        "merged_count": len(res["records"] or []),
        "vector_used": res["vector_used"],
    }
    records, cypher, err = res["records"], res["cypher"], res["err"]

    if err and not res["vector_used"]:
        result = {
            "answer": f"查询失败:{err}", "cypher": cypher, "records": [],
            "web_results": [], "weather_text": "", "multi_info": None,
            "route_info": route_info, "cache_level": "miss",
        }
        _enrich(result, question, history)
        _render_answer(result, "plain")
        return result   # 失败不写缓存,避免把一次故障固化下来

    # 判断是否需要联网 / 天气补充
    web_results, weather_text = [], ""
    if needs_web(question):
        with st.spinner("正在联网补充信息…"):
            web_results = fetch_web_context(question, records)
            if needs_weather(question):
                weather_text = fetch_weather()

    placeholder = st.empty()
    collected = []
    try:
        from src.llm_qa import ANSWER_PROMPT, call_llm_stream
        import json as _json
        from src.hybrid_qa import SYNTH_PROMPT

        data_txt = _json.dumps(records[:20], ensure_ascii=False, default=str, indent=1) \
            if records else "(查询结果为空)"

        # 追问时把上文也提供给 LLM,让答案能呼应("这些店里XX最好")
        ctx = ""
        if fq and history:
            for h in reversed(history):
                if h.get("q"):
                    ctx = f"(这是对上一个问题「{h['q']}」的追问)\n\n"
                    break

        if web_results or weather_text:
            # 有外部信息:用融合提示词
            web_txt = "\n\n".join(
                f"[{i+1}] {r['title']}\n    内容:{r['snippet']}\n    来源:{r['source']}({r['url']})"
                for i, r in enumerate(web_results)
            ) or "(无)"
            msgs = [
                {"role": "system", "content": "你在回答用户关于乌兰察布本地生活的问题。"},
                {"role": "user", "content": SYNTH_PROMPT.format(
                    graph_data=data_txt,
                    weather_data=weather_text or "(本次未查询天气)",
                    web_data=web_txt,
                )},
                {"role": "user", "content": f"{ctx}用户问题:{question}"},
            ]
        else:
            # 纯图谱回答
            msgs = [
                {"role": "system", "content": ANSWER_PROMPT},
                {"role": "user", "content": f"{ctx}用户问题:{question}\n\n查询结果({len(records)} 条):\n{data_txt}"},
            ]

        # 答案生成用 0.3 温度、400 token 上限(文档第一部分 4.3):
        # ANSWER_PROMPT 要求答案控制在 200 字以内,400 token 足够且不会截断;
        # 温度比 Text2Cypher 那步高一点(0.1 → 0.3),让文字更自然。
        for chunk in call_llm_stream(msgs, temperature=0.3, max_tokens=400):
            collected.append(chunk)
            placeholder.markdown("".join(collected) + "▌")
        placeholder.markdown("".join(collected))
    except Exception:
        text = generate_answer(question, records, history=history)
        placeholder.markdown(text)
        collected = [text]
    result = {
        "answer": "".join(collected),
        "cypher": cypher,
        "records": records,
        "web_results": web_results,
        "weather_text": weather_text,
        "multi_info": None,
        "route_info": route_info,
        "compare_info": compare_info,
        "cache_level": "miss",
    }
    _enrich(result, question, history)
    if use_cache:
        _cache_put(key, question, search_query, fq, result, route, qvec)
    return result


def _render_records(records: list, key: str):
    """结果表:补来源标注 + 分页 + CSV 导出(文档阶段一 1/3、第一部分 6.2、第二部分 8)。"""
    if not records:
        return
    import pandas as pd
    from datetime import datetime

    df = pd.DataFrame(records)
    # 来源标注:图谱那一路的记录里没有"来源"列,统一补成"图谱"
    if "来源" not in df.columns:
        df["来源"] = "图谱"

    with st.expander(f"查看全部 {len(df)} 条结果"):
        page_size = 20
        n_pages = max(1, (len(df) - 1) // page_size + 1)
        if n_pages > 1:
            page = st.number_input(f"页码(共 {n_pages} 页)", 1, n_pages, 1,
                                   key=f"pg_{key}")
        else:
            page = 1
        start = (page - 1) * page_size
        st.dataframe(df.iloc[start:start + page_size],
                     use_container_width=True, hide_index=True)

        c1, _ = st.columns([1, 3])
        with c1:
            # utf-8-sig 带 BOM,Excel 打开中文才不乱码
            st.download_button(
                "⬇️ 导出 CSV",
                data=df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"查询结果_{datetime.now():%Y%m%d_%H%M}.csv",
                mime="text/csv",
                key=f"dl_{key}",
                use_container_width=True,
            )


def handle_question(question: str):
    question = question.strip()
    if not question:
        return

    # 记入用户消息并展示
    st.session_state.chat.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # 生成回答(缓存命中与否由 _answer_with_stream 内部处理)
    history = history_for_llm()
    with st.chat_message("assistant"):
        try:
            check_rate_limit(st.session_state.get("client_id", "anon"))
        except RateLimited as e:
            st.warning(str(e))
            result = {
                "answer": str(e), "cypher": "", "records": [],
                "web_results": [], "weather_text": "", "multi_info": None,
                "route_info": None, "path_html": "", "src_html": "",
                "route_html": "", "mq_html": "", "cache_level": "miss",
            }
        else:
            result = _answer_with_stream(question, history)
            if result.get("cache_level") == "miss":
                note_miss()

    # 下面的面板放在聊天消息外,确保 expander 正常渲染
    if result.get("route_html"):
        with st.expander("🧭 查看检索路径(双引擎)", expanded=True):
            st.markdown(result["route_html"], unsafe_allow_html=True)

    if result.get("mq_html"):
        with st.expander("🔎 查看检索过程(多角度召回)", expanded=True):
            st.markdown(result["mq_html"], unsafe_allow_html=True)

    if result.get("path_html") or result.get("paths"):
        with st.expander("🔍 查看推理路径", expanded=True):
            if result.get("paths"):
                st.caption("节点-关系图(可拖拽/缩放)")
                st.iframe(render_paths_graph_html(result["paths"]), height=400)
            if result.get("path_html"):
                st.markdown(result["path_html"], unsafe_allow_html=True)

    if result.get("compare_html"):
        with st.expander("📊 查看对比分析", expanded=True):
            st.markdown(result["compare_html"], unsafe_allow_html=True)

    if result.get("src_html"):
        with st.expander("📡 查看信息来源", expanded=True):
            st.markdown(result["src_html"], unsafe_allow_html=True)

    # 这条消息的唯一 ID:同时给结果表的控件 key 和反馈关联用,
    # 保证同一会话里问同一个问题两次也不会撞 key
    import uuid
    mid = uuid.uuid4().hex[:16]
    _render_records(result.get("records") or [], key=mid)

    st.session_state.chat.append({
        "role": "assistant",
        "content": result.get("answer", ""),
        "cypher": result.get("cypher", ""),
        "records": result.get("records", []),
        "path_html": result.get("path_html", ""),
        "paths": result.get("paths") or [],
        "mq_html": result.get("mq_html", ""),
        "route_html": result.get("route_html", ""),
        "route_info": result.get("route_info"),
        "src_html": result.get("src_html", ""),
        "compare_info": result.get("compare_info"),
        "compare_html": result.get("compare_html", ""),
        # 缓存命中信息要存下来:handle_question 渲染完会 st.rerun(),
        # 之后由历史分支重新渲染,不存的话徽标会被冲掉
        "cache_badge": _cache_badge(result),
        "_fid": mid,
        "question": question,
    })
    _save_session()


def _msg_id(m: dict) -> str:
    """每条消息的稳定 ID(用于反馈关联和控件 key)。

    以前是用 md5(答案前 80 字 + 问题) 算的。这个做法有两个问题:
      1. 同一问题命中缓存后会返回完全相同的答案,两条消息的 md5 就一样了,
         反馈按钮的 key 冲突,Streamlit 直接抛 StreamlitDuplicateElementKey 崩掉;
      2. 反馈落库时用这个 ID 做 MERGE 键,不同用户在同一问题上的赞/踩
         会互相覆盖,好评率统计因此失真。
    改成在消息创建时分配一个唯一 ID,并存进消息里,重跑后仍指向同一条消息。
    """
    if "_fid" not in m:
        import hashlib
        import time
        raw = f"{m.get('question','')}|{m.get('content','')[:40]}|{time.time_ns()}"
        m["_fid"] = hashlib.md5(raw.encode()).hexdigest()[:16]
    return m["_fid"]


def _feedback_ui(msg_index: int, m: dict):
    """每条回答下方的赞/踩。

    产品考虑:点赞显示可自定义文案;点踩必须收集具体意见,
    这样反馈才有改进价值(只统计"踩"的数量没有意义)。
    """
    fid = _msg_id(m)
    key = f"fb_{fid}"
    st.session_state.setdefault("fb_state", {})
    state = st.session_state["fb_state"].get(fid)

    # 已提交 → 显示结果
    if state == "liked":
        st.caption("👍 感谢反馈!我们会继续保持。")
        return
    if state == "disliked_done":
        st.caption("👎 您的意见我们会及时改进,感谢您的反馈!")
        return

    # 点踩后 → 展开输入框
    if state == "disliked":
        st.markdown(
            "<div style='color:#fca5a5;font-size:13px;margin:6px 0 2px'>"
            "👎 哪里不满意?告诉我们,我们会改进:</div>",
            unsafe_allow_html=True,
        )
        comment = st.text_area(
            "不满意的地方", key=f"cmt_{fid}", label_visibility="collapsed",
            placeholder="例如:推荐的不符合我的需求 / 信息不准确 / 结果太少…",
            height=80,
        )
        c1, c2 = st.columns([1, 4])
        if c1.button("提交", key=f"sub_{fid}", type="primary"):
            ok = save_feedback(
                fid,
                question=m.get("question", ""),
                answer=m.get("content", ""),
                rating=-1,
                comment=comment,
                client_id=st.session_state.get("client_id", "anon"),
            )
            st.session_state["fb_state"][fid] = "disliked_done" if ok else "disliked"
            if not ok:
                st.warning("提交失败,请稍后重试")
            st.rerun()
        return

    # 默认 → 两个图标
    c1, c2, _ = st.columns([1, 1, 10])
    if c1.button("👍", key=f"up_{fid}", help="回答有帮助"):
        save_feedback(
            fid, question=m.get("question", ""), answer=m.get("content", ""),
            rating=1, client_id=st.session_state.get("client_id", "anon"),
        )
        st.session_state["fb_state"][fid] = "liked"
        st.rerun()
    if c2.button("👎", key=f"down_{fid}", help="回答需要改进"):
        st.session_state["fb_state"][fid] = "disliked"
        st.rerun()


def render_chat_page():
    """首屏对话页。"""
    init_state()

    _hc, _hh = st.columns([6, 1])
    with _hh:
        _render_history_menu()

    st.markdown(
        "<div style='text-align:center;margin:2px 0 6px'>"
        "<span style='font-size:26px;font-weight:800;"
        "background:linear-gradient(100deg,#7dd3fc,#c4b5fd,#f0abfc);"
        "-webkit-background-clip:text;background-clip:text;"
        "-webkit-text-fill-color:transparent'>乌兰察布本地生活知识图谱</span><br/>"
        "<span style='color:#8fa3bf;font-size:13px'>"
        "6,949 个商家 · 53,700 条关系 · 问问看,支持连续追问</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    # 历史消息
    if not st.session_state.chat:
        with st.chat_message("assistant"):
            st.markdown(WELCOME)
    else:
        for idx, m in enumerate(st.session_state.chat):
            with st.chat_message(m["role"]):
                if m.get("cache_badge"):
                    st.caption(m["cache_badge"])
                st.markdown(m["content"])
                if m["role"] == "assistant":
                    # GraphRAG 检索路径
                    if m.get("route_html"):
                        with st.expander("🧭 查看检索路径(双引擎)", expanded=True):
                            st.markdown(m["route_html"], unsafe_allow_html=True)
                    # 多角度检索过程
                    if m.get("mq_html"):
                        with st.expander("🔎 查看检索过程(多角度召回)", expanded=True):
                            st.markdown(m["mq_html"], unsafe_allow_html=True)
                    # 推理路径(存在消息里,rerun 后仍能渲染)
                    if m.get("path_html") or m.get("paths"):
                        with st.expander("🔍 查看推理路径", expanded=True):
                            if m.get("paths"):
                                st.caption("节点-关系图(可拖拽/缩放)")
                                st.iframe(render_paths_graph_html(m["paths"]), height=400)
                            if m.get("path_html"):
                                st.markdown(m["path_html"], unsafe_allow_html=True)
                    # 信息来源
                    if m.get("src_html"):
                        with st.expander("📡 查看信息来源", expanded=True):
                            st.markdown(m["src_html"], unsafe_allow_html=True)
                    # 对比分析
                    if m.get("compare_html"):
                        with st.expander("📊 查看对比分析", expanded=True):
                            st.markdown(m["compare_html"], unsafe_allow_html=True)
                    if m.get("records"):
                        _render_records(m["records"], key=f"h{idx}")
                    # 每条回答的评价入口
                    _feedback_ui(idx, m)

    render_examples()

    # 底部固定输入框(Streamlit 原生,自动吸底)
    typed = st.chat_input("问我任何关于乌兰察布商家的问题…(可连续追问)")

    # 处理示例按钮点击
    pending = st.session_state.pending
    if pending:
        st.session_state.pending = None
        handle_question(pending)
        st.rerun()

    if typed:
        handle_question(typed)
        st.rerun()
