"""更新日志卡片:页面打开时告诉用户本次更新了什么。

实现方式说明(踩过坑):
  最初想做成浮层模态——用 st.components.v1.html 注入 JS,在顶层文档里
  createElement 画卡片,再挂点击监听。结果不可靠:Streamlit 把注入脚本跑在
  组件 iframe 里,而卡片元素在顶层文档,跨 realm 注册的监听器收不到顶层派发的
  点击事件;改成行内 onclick 调用挂到顶层 window 上的函数后能触发,
  但 setTimeout 移除元素那步行为不稳定,出现过"淡出了但没移除"的状态。
  这类依赖 DOM 时序的注入很难测也难维护。

  所以改成完全 Streamlit 原生:卡片用 st.container(border=True),按钮用
  st.button。"我已知晓"写进 st.query_params,刷新后 URL 里还带着,
  卡片就不再出现——不需要 localStorage,也不需要任何注入脚本。

为什么不用 st.session_state 记已读:
  Streamlit 每次刷新页面都会新建 session_state,存那里的话用户每刷一次
  就被弹一次。query_params 跟着 URL 走,刷新/切页都还在。

改文案只需动 CHANGELOG;改了内容记得同时改 CURRENT_VERSION,
否则已读用户的 URL 里存的还是旧版本号,新内容不会再弹出来。
"""
import streamlit as st

# 改内容时同步改版本号,否则老用户看不到新版本
CURRENT_VERSION = "2026.09.13"

# URL 参数名(出现 ?cl=2026.09.13 就表示已读过这一版)
PARAM = "cl"

CHANGELOG = [
    {
        "group": "⚡ 性能",
        "items": [
            "数据库连接池复用:单次查询从约 2.6 秒降到 0.25 秒",
            "新增索引:按评分/人均筛选的扫描行数从 6,949 降到 21",
            "双引擎并行检索:混合类问题耗时降到较慢那一路,不再相加",
            "三级缓存上线:同一个问题秒回,换个说法也能命中已有答案",
        ],
    },
    {
        "group": "✨ 新功能",
        "items": [
            "对话历史持久化:刷新页面不再丢失,右上角「🕘 历史」可切换会话",
            "对比分析:试试「集宁区和四子王旗的餐饮对比」",
            "推理路径升级为节点-关系图,可拖拽缩放",
            "结果表支持分页与 CSV 导出",
            "新增指标看板:三方案评测对比、缓存命中率、反馈统计",
        ],
    },
    {
        "group": "🔧 修复",
        "items": [
            "修复菜品查询(如「哪里有卖羊杂的」)返回空结果的问题",
            "修复连续追问同一问题时页面报错的问题",
        ],
    },
]


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _acknowledged() -> bool:
    """这一版是否已被用户点过"我已知晓"。"""
    try:
        if st.query_params.get(PARAM) == CURRENT_VERSION:
            return True
    except Exception:
        pass
    return st.session_state.get("changelog_ack") == CURRENT_VERSION


def _acknowledge():
    try:
        st.query_params[PARAM] = CURRENT_VERSION
    except Exception:
        pass
    # 同时写 session_state:query_params 万一不可用(某些嵌入场景),还能生效
    st.session_state["changelog_ack"] = CURRENT_VERSION


def render_changelog():
    """在页面顶部展示更新日志卡片。已读用户什么都不会看到。"""
    if _acknowledged():
        return

    with st.container(border=True):
        st.markdown(
            "<div style='display:flex;align-items:baseline;gap:10px;flex-wrap:wrap'>"
            "<span style='font-size:11px;letter-spacing:1.4px;color:#7dd3fc;"
            "background:rgba(56,189,248,.14);border:1px solid rgba(125,211,252,.3);"
            "padding:3px 10px;border-radius:8px;font-weight:700'>"
            f"更新日志 · {_esc(CURRENT_VERSION)}</span>"
            "<span style='font-size:16px;font-weight:800;"
            "background:linear-gradient(100deg,#7dd3fc,#c4b5fd,#f0abfc);"
            "-webkit-background-clip:text;background-clip:text;"
            "-webkit-text-fill-color:transparent'>这次更新了什么</span>"
            "<span style='font-size:12px;color:#8fa3bf'>"
            "更快、更稳,也多了几个新功能</span>"
            "</div>",
            unsafe_allow_html=True,
        )

        cols = st.columns(len(CHANGELOG))
        for col, g in zip(cols, CHANGELOG):
            with col:
                items = "".join(
                    f"<li style='margin-bottom:3px'>{_esc(t)}</li>"
                    for t in g["items"]
                )
                st.markdown(
                    f"<div style='font-size:12.5px;font-weight:700;color:#7dd3fc;"
                    f"margin:6px 0 6px'>{_esc(g['group'])}</div>"
                    f"<ul style='margin:0;padding-left:17px;font-size:12.5px;"
                    f"line-height:1.7;color:#cbd5e1'>{items}</ul>",
                    unsafe_allow_html=True,
                )

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        _, mid, _ = st.columns([3, 1, 3])
        with mid:
            if st.button("我已知晓", key="changelog_ack_btn",
                         use_container_width=True, type="primary"):
                _acknowledge()
                st.rerun()
