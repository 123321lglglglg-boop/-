"""指标看板页(文档《KG项目优化文档》第二部分 1.3)。

这个页面回答三个问题:
  1. 双引擎到底哪个强? —— 评测集上的命中率对比
  2. 谁补谁的盲区?     —— 分 A/B/C 三类的命中率
  3. 线上跑得怎么样?   —— 缓存命中率 + 用户反馈好评率

数据来源:
  data/eval_report.json   由 scripts/eval_rag.py 生成
  data/eval_set.json      由 scripts/build_eval_set.py 生成
  Neo4j :Feedback         用户在对话页的赞/踩
"""
import json
import statistics
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parent.parent
EVAL_SET = BASE / "data" / "eval_set.json"
REPORT = BASE / "data" / "eval_report.json"

GRADIENT = ["#38bdf8", "#818cf8", "#a855f7", "#f472b6"]
CONFIG_COLORS = {"纯图谱": "#38bdf8", "纯向量": "#a855f7", "GraphRAG": "#f472b6"}


def _load_json(p: Path):
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _card(label: str, value: str, help_text: str = ""):
    st.markdown(
        f"<div style='background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);"
        f"border-radius:14px;padding:12px 14px'>"
        f"<div style='color:#8fa3bf;font-size:12px'>{label}</div>"
        f"<div style='color:#e8eef7;font-size:22px;font-weight:700;margin-top:4px'>{value}</div>"
        f"<div style='color:#64748b;font-size:11px;margin-top:2px'>{help_text}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _summary(rows: list, config: str) -> dict:
    sub = [r for r in rows if r["config"] == config]
    if not sub:
        return {}
    lat = sorted(r["ms"] for r in sub)
    s = {
        "方案": config,
        "题目数": len(sub),
        "命中率": sum(1 for r in sub if r["hit"]) / len(sub) * 100,
        "P@5": sum(r.get("p5", 0) for r in sub) / len(sub) * 100,
        "R@5": sum(r.get("r5", 0) for r in sub) / len(sub) * 100,
        "P50(ms)": statistics.median(lat),
        "P95(ms)": lat[min(len(lat) - 1, int(len(lat) * 0.95))],
        "报错": sum(1 for r in sub if r.get("error")),
    }
    for t in ("A", "B", "C"):
        ts = [r for r in sub if r["type"] == t]
        s[f"{t}类"] = (sum(r.get("p5", 0) for r in ts) / len(ts) * 100) if ts else None
    return s


def render_metrics_page():
    st.markdown(
        "<div style='text-align:center;color:#8fa3bf;font-size:13px;margin-bottom:10px'>"
        "三方案检索效果对比 · 数据来自真实评测集,可复现</div>",
        unsafe_allow_html=True,
    )

    report = _load_json(REPORT)
    evalset = _load_json(EVAL_SET)

    if not report or not report.get("results"):
        st.info(
            "还没有评测结果。先跑一次评测:\n\n"
            "```bash\n"
            "python scripts/build_eval_set.py   # 生成评测集\n"
            "python scripts/eval_rag.py         # 跑三方案对比\n"
            "```"
        )
    else:
        rows = report["results"]
        meta = report.get("meta", {})
        configs = [c for c in ("纯图谱", "纯向量", "GraphRAG")
                   if any(r["config"] == c for r in rows)]
        summ = [_summary(rows, c) for c in configs]

        # ---- 概览卡 ----
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            _card("评测题数", str(len({r["id"] for r in rows})),
                  "由真实图谱反推生成,非手写")
        with c2:
            best = max(summ, key=lambda s: s["P@5"]) if summ else None
            _card("最佳方案", best["方案"] if best else "—",
                  f"P@5 {best['P@5']:.1f}%" if best else "")
        with c3:
            gap = ""
            if len(summ) >= 2:
                ss = sorted(summ, key=lambda s: s["P@5"])
                gap = f"比最差高 {ss[-1]['P@5'] - ss[0]['P@5']:.1f} 个百分点"
            _card("方案差距", f"{len(configs)} 套方案", gap)
        with c4:
            fast = min(summ, key=lambda s: s["P50(ms)"]) if summ else None
            _card("最快方案", fast["方案"] if fast else "—",
                  f"P50 {fast['P50(ms)']:.0f}ms" if fast else "")

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # ---- 总分对比 ----
        st.subheader("① 三方案总对比")
        st.caption(
            "P@5 = 返回的前 5 条里满足该题条件的比例(衡量是否理解意图,与排序无关)。"
            "「严格命中」另外要求顺序与标注的评分序一致,对按语义相似度排序的向量不公平,仅供参考。"
        )
        df = pd.DataFrame([{
            "方案": s["方案"],
            "题目数": s["题目数"],
            "P@5": round(s["P@5"], 1),
            "R@5": round(s["R@5"], 1),
            "严格命中": round(s["命中率"], 1),
            "P50(ms)": round(s["P50(ms)"]),
            "P95(ms)": round(s["P95(ms)"]),
            "报错": s["报错"],
        } for s in summ])
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("")
        st.bar_chart(df.set_index("方案")[["P@5"]], height=260, color="#38bdf8")

        # ---- 分类型对比 ----
        st.subheader("② 分类型 P@5(A 结构化 / B 语义化 / C 混合)")
        st.caption(
            "这一节是用来验证「双引擎互补」的:如果图谱只在 A 强、向量只在 B 强,"
            "而 GraphRAG 在 C 上领先,那融合设计才是有依据的。"
        )
        tf = pd.DataFrame([{
            "方案": s["方案"],
            "A 结构化": s.get("A类"),
            "B 语义化": s.get("B类"),
            "C 混合": s.get("C类"),
        } for s in summ]).set_index("方案").dropna(axis=1, how="all")
        if not tf.empty:
            st.bar_chart(tf, height=300, color=GRADIENT[:tf.shape[1]])
            st.dataframe(
                tf.round(1).astype(str).replace("nan", "—"),
                use_container_width=True,
            )
        else:
            st.info("评测集里还没有分类数据。")

        # ---- 逐题明细 ----
        st.subheader("③ 逐题结果")
        detail = pd.DataFrame([{
            "题号": r["id"], "类型": r["type"], "方案": r["config"],
            "问题": r["question"],
            "命中": "✅" if r["hit"] else "❌",
            "耗时(ms)": r["ms"],
            "返回Top5": " / ".join(str(x)[:14] for x in r.get("got_top5", [])[:3]),
            "报错": (r.get("error") or "")[:60],
        } for r in rows])
        tsel = st.multiselect("按类型筛选", ["A", "B", "C"], default=[])
        if tsel:
            detail = detail[detail["类型"].isin(tsel)]
        only_miss = st.checkbox("只看未命中", value=False)
        if only_miss:
            detail = detail[detail["命中"] == "❌"]
        st.dataframe(detail, use_container_width=True, hide_index=True)

        st.caption(
            f"评测集 {Path(meta.get('eval_set', '')).name or ''} · "
            f"生成于 {meta.get('generated_at', '')} · "
            "主指标 P@5(返回前 5 条满足题目条件的比例)"
        )

    # ---- 线上运行指标 ----
    st.divider()
    st.subheader("④ 线上运行指标")

    from src.feedback import feedback_stats, load_dislikes
    stats = feedback_stats()
    try:
        from src.qa_cache import cache_stats
        cache = cache_stats()
    except Exception:
        cache = {}

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        total = stats.get("total", 0)
        likes = stats.get("likes", 0)
        _card("好评率", f"{likes / total * 100:.0f}%" if total else "—",
              f"{likes} 赞 / {total} 条反馈")
    with k2:
        _card("反馈总数", str(total), "对话页每条回答下的赞/踩")
    with k3:
        _card("缓存命中率", cache.get("命中率", "—"),
              f"精确 {cache.get('L1命中', 0)} / 语义 {cache.get('L3命中', 0)} / 总请求 {cache.get('总请求', 0)}")
    with k4:
        _card("缓存条目", str(cache.get("L3条目数", 0)), "语义缓存库大小")

    if stats.get("dislikes"):
        st.markdown("**需要优化的问答(点踩)**")
        for item in load_dislikes(limit=10):
            q = str(item.get("问题", ""))[:44]
            with st.expander(f"👎 {q}"):
                st.write("**用户意见**:", item.get("用户意见") or "(未填写)")
                st.write("**时间**:", item.get("时间"))
