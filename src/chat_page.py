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
    """把对话历史转成 LLM 可用的上下文(只取问答对)。"""
    hist = []
    for m in st.session_state.chat:
        if m["role"] == "user":
            hist.append({"q": m["content"], "cypher": "", "answer": ""})
        elif m["role"] == "assistant" and hist:
            hist[-1]["cypher"] = m.get("cypher", "")
            hist[-1]["answer"] = m.get("content", "")
    return hist[-max_turns:]


def _answer_with_stream(question: str, history: list):
    """生成回答并流式展示。返回 (答案全文, cypher, records, web_results, weather_text)。"""
    cypher, records, err = text2cypher(question, history=history)
    if err:
        msg = f"查询失败:{err}"
        st.markdown(msg)
        return msg, cypher, [], [], ""

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
                {"role": "user", "content": f"用户问题:{question}"},
            ]
        else:
            # 纯图谱回答
            msgs = [
                {"role": "system", "content": ANSWER_PROMPT},
                {"role": "user", "content": f"用户问题:{question}\n\n查询结果({len(records)} 条):\n{data_txt}"},
            ]

        for chunk in call_llm_stream(msgs):
            collected.append(chunk)
            placeholder.markdown("".join(collected) + "▌")
        placeholder.markdown("".join(collected))
    except Exception:
        text = generate_answer(question, records, history=history)
        placeholder.markdown(text)
        collected = [text]

    return "".join(collected), cypher, records, web_results, weather_text


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
    web_results, weather_text = [], ""
    with st.chat_message("assistant"):
        try:
            check_rate_limit(st.session_state.get("client_id", "anon"))
        except RateLimited as e:
            st.warning(str(e))
            answer_txt, cypher, records = str(e), "", []
        else:
            with st.spinner("正在查询知识图谱…"):
                answer_txt, cypher, records, web_results, weather_text = \
                    _answer_with_stream(question, history)

            # 推理路径:算好后存进消息,rerun 后由历史渲染分支展示
            if records:
                try:
                    paths = extract_paths(question, cypher, records)
                    if paths:
                        path_html = render_paths_html(paths)
                except Exception:
                    path_html = ""

            # 来源面板(联网/天气)
            if web_results or weather_text:
                src_html = render_sources_html(web_results, weather_text)

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
        "src_html": src_html,
    })


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
        for m in st.session_state.chat:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
                if m["role"] == "assistant":
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
