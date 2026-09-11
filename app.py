"""乌兰察布本地生活知识图谱 - Streamlit 网页 Demo

启动:
    python run_demo.py
"""
import os
import warnings

warnings.filterwarnings("ignore")

from pathlib import Path

import pandas as pd
import streamlit as st
from neo4j import GraphDatabase

from src.qa import answer, parse
from src.llm_qa import ask
from src.graph_data import overview_subgraph, poi_neighborhood
from src.viz import graph_html
from src.theme import inject_liquid_theme
from src.pwa import inject_pwa, inject_mobile_css
from src.hero import hero_html
from src.map_viz import drilldown_map_html
import altair as alt

def _cfg(key: str, default: str = "") -> str:
    """读取配置:环境变量 > Streamlit secrets > 默认值(本地开发)。"""
    v = os.environ.get(key, "").strip()
    if not v:
        try:
            v = str(st.secrets.get(key, "")).strip()
        except Exception:
            pass
    return v or default


NEO4J_URI = _cfg("NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = (
    _cfg("NEO4J_USER", "neo4j"),
    _cfg("NEO4J_PASSWORD", "wlcb123456"),
)
BASE = Path(__file__).resolve().parent

st.set_page_config(page_title="乌兰察布知识图谱", page_icon="🗺️", layout="wide")
inject_liquid_theme()
inject_pwa()
inject_mobile_css()

GRADIENT = ["#38bdf8", "#818cf8", "#a855f7", "#f472b6"]


def _gradient_bar(rows, cat_field, val_field, title, horizontal=False):
    """渐变配色的柱状图(替代 Streamlit 默认绿色)。"""
    df = pd.DataFrame(rows)
    df[val_field] = pd.to_numeric(df[val_field])
    df = df.sort_values(val_field, ascending=horizontal)
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=6, size=22)
        .encode(
            x=alt.X(f"{val_field}:Q", title=None,
                    axis=alt.Axis(labelColor="#8fa3bf", gridColor="rgba(255,255,255,0.06)")),
            y=alt.Y(f"{cat_field}:N", title=None, sort="-x" if not horizontal else None,
                    axis=alt.Axis(labelColor="#cbd5e1", labelFontSize=12)),
            color=alt.Color(f"{val_field}:Q", legend=None,
                            scale=alt.Scale(range=GRADIENT)),
            tooltip=[cat_field, val_field],
        )
        .properties(title=alt.TitleParams(title, color="#e2e8f0", fontSize=14,
                                          anchor="start"),
                    background="transparent")
        .configure_view(strokeOpacity=0)
    )
    return chart


@st.cache_resource
def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)


def run_cypher(query: str, **params):
    with get_driver().session() as s:
        return [dict(r) for r in s.run(query, **params)]


def poi_search(districts, cats, rating_min, cost_max, keyword, limit):
    where = ["1=1"]
    params = {"limit": limit}
    if districts:
        where.append("d.name IN $districts")
        params["districts"] = districts
    if cats:
        where.append("c.name IN $cats")
        params["cats"] = cats
    if rating_min > 0:
        where.append("p.rating IS NOT NULL AND p.rating >= $rating_min")
        params["rating_min"] = rating_min
    if cost_max is not None:
        where.append("p.cost IS NOT NULL AND p.cost > 0 AND p.cost <= $cost_max")
        params["cost_max"] = cost_max
    if keyword:
        where.append("p.name CONTAINS $kw")
        params["kw"] = keyword

    q = f"""
    MATCH (p:POI)-[:位于]->(d:District)
    OPTIONAL MATCH (p)-[:属于细类]->(c:CategoryL3)
    OPTIONAL MATCH (p)-[:位于商圈]->(a:BusinessArea)
    WITH p, d, c, a
    WHERE {' AND '.join(where)}
    RETURN p.name AS 名称, d.name AS 区县, a.name AS 商圈, c.name AS 品类,
           p.rating AS 评分, p.cost AS 人均, p.address AS 地址
    ORDER BY 评分 DESC LIMIT $limit
    """
    return pd.DataFrame(run_cypher(q, **params))


def session_client_id() -> str:
    """为每个浏览器会话生成稳定 ID,用于 LLM 限流。"""
    if "client_id" not in st.session_state:
        import uuid
        st.session_state["client_id"] = uuid.uuid4().hex[:16]
    return st.session_state["client_id"]


def main():
    # ---- 首屏 Hero ----
    stats_raw = {
        "poi": run_cypher("MATCH (p:POI) RETURN count(p) AS n")[0]["n"],
        "relations": run_cypher("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"],
        "brands": run_cypher("MATCH (c:Chain) RETURN count(c) AS n")[0]["n"],
        "districts": run_cypher("MATCH (d:District) RETURN count(d) AS n")[0]["n"],
    }
    st.iframe(hero_html(stats_raw, height=350), height=360)

    st.markdown(
        "<div style='text-align:center;color:#8fa3bf;font-size:13.5px;"
        "letter-spacing:0.5px;margin:6px 0 18px'>"
        "数据来源:高德开放平台 Web API · 存储:Neo4j 图数据库 · 问答:规则解析 + DeepSeek LLM"
        "</div>",
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["📊 图谱总览", "🗺️ 地图分布", "🕸️ 图谱探索",
         "🔍 商家查询", "💬 规则问答", "🤖 LLM 问答"]
    )

    # ---- Tab 1: 总览 ----
    with tab1:
        cols = st.columns(5)
        stats = [
            ("POI 节点", stats_raw["poi"]),
            ("关系总数", stats_raw["relations"]),
            ("商圈", run_cypher("MATCH (a:BusinessArea) RETURN count(a) AS n")[0]["n"]),
            ("连锁品牌", stats_raw["brands"]),
            ("关系类型", run_cypher("CALL db.relationshipTypes() YIELD relationshipType RETURN count(*) AS n")[0]["n"]),
        ]
        for col, (label, value) in zip(cols, stats):
            col.metric(label, f"{value:,}")

        st.caption("提示:想看数据长在地图上的样子?切到「🗺️ 地图分布」;想看实体怎么连成网?切到「🕸️ 图谱探索」")

        col_l, col_r = st.columns(2)
        with col_l:
            st.subheader("区县分布")
            dist_rows = run_cypher(
                "MATCH (p:POI)-[:位于]->(d:District) "
                "RETURN d.name AS 区县, count(p) AS 数量 ORDER BY 数量 DESC"
            )
            st.altair_chart(_gradient_bar(dist_rows, "区县", "数量", "区县商家分布"),
                            use_container_width=True)
        with col_r:
            st.subheader("商圈 TOP10")
            area_rows = run_cypher(
                "MATCH (a:BusinessArea) RETURN a.name AS 商圈, a.size AS 商家数 "
                "ORDER BY a.size DESC LIMIT 10"
            )
            st.altair_chart(_gradient_bar(area_rows, "商圈", "商家数", "商圈商家数 TOP10", horizontal=True),
                            use_container_width=True)

        st.subheader("关系类型分布")
        rel_df = pd.DataFrame(run_cypher(
            "MATCH ()-[r]->() RETURN type(r) AS 关系, count(r) AS 数量 ORDER BY 数量 DESC"
        )).set_index("关系")
        st.dataframe(rel_df.T, use_container_width=True)

    # ---- Tab 2: 地图 ----
    with tab2:
        st.markdown(
            "**把知识图谱画到地图上** — 6,900+ 个商家带真实经纬度。"
            "**点击任意区县下钻**查看该区县统计与商家分布,支持按评分/人均/品类切换着色"
        )

        counts = {r["区县"]: r["数量"] for r in run_cypher(
            "MATCH (p:POI)-[:位于]->(d:District) RETURN d.name AS 区县, count(p) AS 数量"
        )}
        all_pts = run_cypher(
            """
            MATCH (p:POI)-[:位于]->(d:District)
            OPTIONAL MATCH (p)-[:属于细类]->(c:CategoryL3)
            WHERE p.lng IS NOT NULL
            RETURN p.name AS name, p.lng AS lng, p.lat AS lat,
                   p.rating AS rating, p.cost AS cost,
                   d.name AS district, c.name AS category
            """
        )
        st.iframe(drilldown_map_html(all_pts, counts, height=640), height=660)
        st.caption(
            f"共载入 {len(all_pts):,} 个商家坐标 · 地图边界来自 DataV.GeoAtlas · "
            "点击区县下钻、滚轮缩放、悬停查看详情、左侧面板可返回全区"
        )

    # ---- Tab 3: 图谱探索 ----
    with tab3:
        st.markdown("**交互式知识图谱** — 可拖拽节点、滚轮缩放、悬停查看详情、点击图例可隐藏某类节点")
        c1, c2, c3 = st.columns([2, 2, 3])
        with c1:
            district = st.selectbox("聚焦区县", ["全部"] + [r["n"] for r in run_cypher(
                "MATCH (d:District) RETURN d.name AS n ORDER BY n")])
        with c2:
            mode = st.radio("模式", ["区域总览", "商家邻域"], horizontal=True)
        with c3:
            if mode == "商家邻域":
                kw = st.text_input("商家名关键词", "肯德基", help="输入店名的一部分,看它和周边商家的关系")
            else:
                per_district = st.slider("每区县抽样商家数", 5, 60, 20)

        if mode == "区域总览":
            with st.spinner("构建子图…"):
                nodes, edges = overview_subgraph(
                    district=None if district == "全部" else district,
                    limit_pois=per_district,
                )
            title = f"{district} · 图谱结构"
        else:
            with st.spinner("构建邻域子图…"):
                nodes, edges = poi_neighborhood(kw, limit=1)
            title = f"「{kw}」及其周边"

        if not nodes:
            st.warning("没有匹配的数据,换个关键词或区县试试")
        else:
            st.caption(f"节点 {len(nodes)} 个 · 关系 {len(edges)} 条")
            st.iframe(graph_html(nodes, edges, height=680, title=title), height=700)

    # ---- Tab 3: 查询 ----
    with tab4:
        col1, col2, col3 = st.columns(3)
        with col1:
            district = st.multiselect("区县", sorted(r["n"] for r in run_cypher(
                "MATCH (d:District) RETURN d.name AS n ORDER BY n")))
            keyword = st.text_input("店名关键词", "")
        with col2:
            cats = st.multiselect("品类", sorted(r["n"] for r in run_cypher(
                "MATCH (c:CategoryL3) RETURN c.name AS n ORDER BY n")))
            rating_min = st.slider("最低评分", 0.0, 5.0, 0.0, 0.1)
        with col3:
            use_cost = st.checkbox("限制人均")
            cost_max = st.number_input("人均上限(元)", 0, 1000, 50, 10) if use_cost else None
            limit = st.number_input("返回条数", 10, 200, 30, 10)

        if st.button("查询", type="primary"):
            df = poi_search(district, cats, rating_min, cost_max, keyword, limit)
            if df.empty:
                st.warning("没有符合条件的商家")
            else:
                st.success(f"找到 {len(df)} 家")
                st.dataframe(df, use_container_width=True, hide_index=True)

    # ---- Tab 4: 问答 ----
    with tab5:
        st.markdown("**试试这些问题:**")
        examples = [
            "集宁区人均50以下的餐厅有哪些",
            "评分最高的蒙餐馆在哪",
            "四子王旗有什么景点",
            "肯德基在乌兰察布有几家店",
            "哪个区县餐厅最多",
        ]
        cols = st.columns(len(examples))
        for i, (col, ex) in enumerate(zip(cols, examples)):
            if col.button(ex, key=f"ex{i}", use_container_width=True):
                st.session_state["question"] = ex

        question = st.text_input("输入你的问题", value=st.session_state.get("question", ""),
                                 placeholder="例如:集宁区人均50以下的餐厅有哪些")
        if st.button("提问", type="primary") and question.strip():
            with st.spinner("查询知识图谱…"):
                plan = parse(question)
                result = answer(question)
            st.markdown("### 回答")
            st.text(result)
            with st.expander("查看解析逻辑(面试加分项)"):
                st.markdown("**1. 自然语言 → 结构化条件**")
                st.json({k: v for k, v in plan.items() if v not in (None, False)})
                st.caption(
                    "规则解析器把口语映射到图谱本体:区县别名、品类口语词、"
                    "价格/评分条件、计数/分布/排序意图;再由 build_query 组装 Cypher。"
                )

    # ---- Tab 5: LLM 问答 ----
    with tab6:
        st.markdown(
            "**LLM 增强问答** — 大模型把自然语言转成 Cypher 查询图谱,"
            "再把结果总结成自然语言回答。相比规则版,能理解更灵活的问法。"
        )
        st.caption("底层模型:DeepSeek · 只读查询校验 · 出错自动重试")

        llm_examples = [
            "离乌兰图雅蒙餐最近的商家有哪些",
            "推荐几家集宁区评分高的火锅店,说说理由",
            "肯德基在乌兰察布的门店都分布在哪些区",
            "四子王旗有什么值得去的景点",
        ]
        cols = st.columns(len(llm_examples))
        for i, (col, ex) in enumerate(zip(cols, llm_examples)):
            if col.button(ex, key=f"lex{i}", use_container_width=True):
                st.session_state["llm_question"] = ex

        llm_q = st.text_input("输入你的问题", value=st.session_state.get("llm_question", ""),
                              placeholder="例如:离最近的火锅店有哪些好吃的",
                              key="llm_input")
        if st.button("LLM 提问", type="primary") and llm_q.strip():
            with st.spinner("大模型正在生成查询并分析结果…"):
                try:
                    llm_result = ask(llm_q, client_id=session_client_id())
                except Exception as e:
                    llm_result = {"ok": False, "cypher": "", "records": [],
                                  "answer": f"调用失败:{e}"}

            st.markdown("### 回答")
            if llm_result["ok"]:
                st.success(llm_result["answer"])
            else:
                st.error(llm_result["answer"])

            with st.expander("查看技术细节(面试加分项)"):
                st.markdown("**1. 大模型生成的 Cypher**")
                st.code(llm_result["cypher"] or "(未生成)", language="cypher")
                st.markdown(f"**2. 图谱返回 {len(llm_result['records'])} 条结果**")
                if llm_result["records"]:
                    st.dataframe(pd.DataFrame(llm_result["records"]).head(10),
                                 use_container_width=True, hide_index=True)
                st.caption(
                    "流程:自然语言 → LLM 生成 Cypher(带本体 schema 提示)→ "
                    "只读语句校验 → Neo4j 执行(报错自动回传重试)→ "
                    "LLM 根据查询结果生成自然语言回答"
                )

    st.divider()
    st.caption("知识图谱作品集 | 采集 → 清洗 → 实体对齐 → 图谱增强 → Neo4j → 可视化问答")


if __name__ == "__main__":
    main()
