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
from src.path_viz import render_paths_html
from src.hybrid_qa import (
    fetch_weather,
    fetch_web_context,
    needs_weather,
    needs_web,
)
from src.source_viz import render_sources_html
from src.multi_query import is_vague, multi_query_answer
from src.multi_viz import render_multi_html
from src.feedback import save_feedback
from src.hybrid_retrieval import classify, classify_with_context, is_followup
from src.vector_search import index_ready, semantic_search
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


def init_state():
    if "chat" not in st.session_state:
        st.session_state.chat = []          # [{role, content, cypher, records}]
    if "pending" not in st.session_state:
        st.session_state.pending = None     # 待处理的问题(由示例按钮设置)


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


def _kg_search(question: str, history: list):
    """图谱检索:图数据库里的精确查询。返回 [{poi_id, name, text, source}, …]。"""
    cypher, records, err = text2cypher(question, history=history)
    if err or not records:
        return [], cypher, records
    import json as _json
    out = []
    for r in records:
        out.append({
            "poi_id": r.get("poi_id") or r.get("名称"),
            "name": r.get("名称") or r.get("name") or "",
            "text": _json.dumps(r, ensure_ascii=False, default=str)[:300],
            "score": 1.0,
            "source": "kg",
            "raw": r,
        })
    return out, cypher, records


def _answer_with_stream(question: str, history: list):
    """生成回答并流式展示。返回 (答案, cypher, records, web_results, weather_text, multi_info, route_info)。

    检索优先级(GraphRAG 架构):
      1. 走向量:问题含主观/体验类语义信号 → 语义检索最准
      2. 走图谱:结构化条件(人均/数量/评分/关系)
      3. 走 Multi-Query:图谱和向量都难以覆盖的宽泛场景问题
    """
    multi_info = None
    # 带上下文分流:追问("那评分高的呢")要继承上一轮的检索意图
    route = classify_with_context(question, history)

    # 追问时把上下文拼进检索语句,让向量检索也能理解"那些店"指什么
    search_query = question
    if is_followup(question) and history:
        last_q = ""
        for h in reversed(history):
            if h.get("q"):
                last_q = h["q"]
                break
        if last_q:
            search_query = f"{last_q} {question}"

    # ---- 先做 GraphRAG 双引擎检索 ----
    route_info = {"route": route, "kg_count": 0, "vec_count": 0}
    vector_mode = route in ("semantic", "hybrid")
    vec_results = []

    if vector_mode and index_ready():
        with st.spinner("正在做语义检索…"):
            try:
                vec_results = semantic_search(search_query, top_k=10)
            except Exception:
                vec_results = []
        route_info["vec_count"] = len(vec_results)

    # ---- 宽泛场景问题:两路都覆盖不了时,才用 Multi-Query 多角度召回 ----
    # 追问不走 Multi-Query(追问是收窄范围,不是发散)
    if is_vague(question) and not is_followup(question) and route == "structured" and not vec_results:
        with st.spinner("正在从多个角度检索…"):
            mq = multi_query_answer(question)
        if mq.get("ok") and mq.get("records"):
            flat = []
            for sr in mq["results"]:
                for rec in sr["records"]:
                    flat.append(rec)
            answer_txt = mq["answer"]
            st.markdown(answer_txt)
            return answer_txt, "", flat, [], "", {
                "queries": mq["queries"],
                "results": mq["results"],
                "merged": mq["records"],
            }, None

    cypher, records, err = text2cypher(question, history=history)
    if err and not vec_results:
        msg = f"查询失败:{err}"
        st.markdown(msg)
        return msg, cypher, [], [], "", None, None
    route_info["kg_count"] = len(records or [])

    # 语义路由:主要用向量结果,图谱结果作为补充
    if route == "semantic" and vec_results:
        records = [{"名称": v["name"], "说明": v["text"].replace("\n", " · ")[:160],
                    "_source": "语义检索"} for v in vec_results[:8]]
    elif route == "hybrid" and vec_results and records:
        # 混合:两路合并去重(图谱优先,向量补位)
        seen = set()
        merged = []
        for r in records[:8]:
            name = r.get("名称") or r.get("name")
            if name and name not in seen:
                seen.add(name)
                merged.append(r)
        for v in vec_results[:5]:
            if v["name"] not in seen:
                seen.add(v["name"])
                merged.append({"名称": v["name"],
                               "说明": v["text"].replace("\n", " · ")[:160],
                               "_source": "语义检索"})
        records = merged

    # 判断是否需要联网 / 天气补充
    need_web = needs_web(question)
    web_results, weather_text = [], ""
    if need_web:
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
        if is_followup(question) and history:
            last_q = ""
            for h in reversed(history):
                if h.get("q"):
                    last_q = h["q"]
                    break
            if last_q:
                ctx = f"(这是对上一个问题「{last_q}」的追问)\n\n"

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

        for chunk in call_llm_stream(msgs):
            collected.append(chunk)
            placeholder.markdown("".join(collected) + "▌")
        placeholder.markdown("".join(collected))
    except Exception:
        text = generate_answer(question, records, history=history)
        placeholder.markdown(text)
        collected = [text]

    return "".join(collected), cypher, records, web_results, weather_text, multi_info, route_info


def handle_question(question: str):
    question = question.strip()
    if not question:
        return

    # 记入用户消息并展示
    st.session_state.chat.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # 生成回答
    history = history_for_llm()
    path_html = ""
    src_html = ""
    mq_html = ""
    route_html = ""
    web_results, weather_text = [], ""
    with st.chat_message("assistant"):
        try:
            check_rate_limit(st.session_state.get("client_id", "anon"))
        except RateLimited as e:
            st.warning(str(e))
            answer_txt, cypher, records = str(e), "", []
            multi_info = None
            route_info = None
        else:
            with st.spinner("正在检索…"):
                answer_txt, cypher, records, web_results, weather_text, multi_info, route_info = \
                    _answer_with_stream(question, history)

            # GraphRAG 双引擎:展示走了哪条路
            if route_info and route_info.get("route") in ("semantic", "hybrid"):
                route_html = render_route_html(route_info)

            # Multi-Query 扩展过程展示
            if multi_info:
                mq_html = render_multi_html(multi_info["queries"], multi_info["results"])

            # 推理路径:算好后存进消息,rerun 后由历史渲染分支展示
            if records and not multi_info and route_info.get("route") != "semantic":
                try:
                    paths = extract_paths(question, cypher, records)
                    if paths:
                        path_html = render_paths_html(paths)
                except Exception:
                    path_html = ""

            # 来源面板(联网/天气)
            if web_results or weather_text:
                src_html = render_sources_html(web_results, weather_text)

    # GraphRAG 检索路径展示
    if route_html:
        with st.expander("🧭 查看检索路径(双引擎)", expanded=True):
            st.markdown(route_html, unsafe_allow_html=True)

    # 多角度检索过程展示
    if mq_html:
        with st.expander("🔎 查看检索过程(多角度召回)", expanded=True):
            st.markdown(mq_html, unsafe_allow_html=True)

    # 推理路径展示(放在聊天消息外,确保 expander 正常渲染)
    if path_html:
        with st.expander("🔍 查看推理路径", expanded=True):
            st.markdown(path_html, unsafe_allow_html=True)

    # 信息来源展示
    if src_html:
        with st.expander("📡 查看信息来源", expanded=True):
            st.markdown(src_html, unsafe_allow_html=True)

    if records:
        import pandas as pd
        with st.expander(f"查看全部 {len(records)} 条结果"):
            st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)

    st.session_state.chat.append({
        "role": "assistant", "content": answer_txt,
        "cypher": cypher, "records": records, "path_html": path_html,
        "mq_html": mq_html,
        "route_html": route_html,
        "route_info": route_info,
        "src_html": src_html,
        "question": question,
    })


def _msg_id(m: dict) -> str:
    """给每条消息生成稳定 ID(用于反馈关联)。"""
    if "_fid" not in m:
        import hashlib
        raw = f"{m.get('content','')[:80]}|{m.get('question','')}"
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
                    if m.get("path_html"):
                        with st.expander("🔍 查看推理路径", expanded=True):
                            st.markdown(m["path_html"], unsafe_allow_html=True)
                    # 信息来源
                    if m.get("src_html"):
                        with st.expander("📡 查看信息来源", expanded=True):
                            st.markdown(m["src_html"], unsafe_allow_html=True)
                    if m.get("records"):
                        import pandas as pd
                        with st.expander(f"查看全部 {len(m['records'])} 条结果"):
                            st.dataframe(pd.DataFrame(m["records"]),
                                         use_container_width=True, hide_index=True)
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
