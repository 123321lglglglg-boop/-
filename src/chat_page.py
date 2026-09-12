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

EXAMPLES = [
    "集宁区人均50以下的餐厅有哪些",
    "评分最高的蒙餐馆在哪",
    "乌兰察布有多少家火锅店",
    "四子王旗有什么景点",
    "离乌兰图雅蒙餐最近的商家",
]

WELCOME = """你好 👋 我可以查询乌兰察布的 **6,949 个商家**和 **53,700 条关系**。

试试问我:

- 集宁区人均 50 以下的餐厅有哪些?
- 评分最高的蒙餐馆在哪?
- 离乌兰图雅蒙餐最近的商家有哪些?

**可以追问**,比如接着问"那评分 4.5 以上的呢?"——我会记得上文。"""


def init_state():
    if "chat" not in st.session_state:
        st.session_state.chat = []          # [{role, content, cypher, records}]
    if "pending" not in st.session_state:
        st.session_state.pending = None     # 待处理的问题(由示例按钮设置)


def _example_clicked(q: str):
    st.session_state.pending = q


def render_examples():
    """示例问题按钮(仅在还没对话时展示,避免占地方)。"""
    if st.session_state.chat:
        return
    cols = st.columns(len(EXAMPLES))
    for i, (col, q) in enumerate(zip(cols, EXAMPLES)):
        short = q if len(q) <= 14 else q[:13] + "…"
        if col.button(short, key=f"ex_{i}", use_container_width=True, help=q):
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
    """生成回答并流式展示。返回 (答案全文, cypher, records)。"""
    cypher, records, err = text2cypher(question, history=history)
    if err:
        msg = f"查询失败:{err}"
        st.markdown(msg)
        return msg, cypher, []

    placeholder = st.empty()
    collected = []
    try:
        from src.llm_qa import ANSWER_PROMPT, call_llm_stream
        import json as _json

        data_txt = _json.dumps(records[:20], ensure_ascii=False, default=str, indent=1) \
            if records else "(查询结果为空)"
        user_content = f"用户问题:{question}\n\n查询结果({len(records)} 条):\n{data_txt}"

        msgs = [
            {"role": "system", "content": ANSWER_PROMPT},
            {"role": "user", "content": user_content},
        ]
        for chunk in call_llm_stream(msgs):
            collected.append(chunk)
            placeholder.markdown("".join(collected) + "▌")
        placeholder.markdown("".join(collected))
    except Exception:
        # 流式失败时退回普通调用
        text = generate_answer(question, records, history=history)
        placeholder.markdown(text)
        collected = [text]

    return "".join(collected), cypher, records


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
    with st.chat_message("assistant"):
        try:
            check_rate_limit(st.session_state.get("client_id", "anon"))
        except RateLimited as e:
            st.warning(str(e))
            answer_txt, cypher, records = str(e), "", []
        else:
            with st.spinner("正在查询知识图谱…"):
                answer_txt, cypher, records = _answer_with_stream(question, history)

        if cypher or records:
            with st.expander(f"查看查询细节({len(records)} 条结果)"):
                st.markdown("**生成的 Cypher**")
                st.code(cypher or "(未生成)", language="cypher")
                if records:
                    import pandas as pd
                    st.dataframe(pd.DataFrame(records).head(10),
                                 use_container_width=True, hide_index=True)

    st.session_state.chat.append({
        "role": "assistant", "content": answer_txt,
        "cypher": cypher, "records": records,
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
                if m["role"] == "assistant" and m.get("cypher"):
                    with st.expander(f"查看查询细节({len(m.get('records') or [])} 条结果)"):
                        st.markdown("**生成的 Cypher**")
                        st.code(m["cypher"], language="cypher")
                        if m.get("records"):
                            import pandas as pd
                            st.dataframe(pd.DataFrame(m["records"]).head(10),
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
