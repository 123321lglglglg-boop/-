"""乌兰察布本地生活知识图谱 - Streamlit 网页 Demo

启动:
    python run_demo.py
"""
import warnings

warnings.filterwarnings("ignore")

from pathlib import Path

import pandas as pd
import streamlit as st
from neo4j import GraphDatabase

from src.qa import answer, parse
from src.llm_qa import ask
from src.chat_page import render_chat_page
from src.graph_data import overview_subgraph, poi_neighborhood
from src.viz import graph_html
from src.theme import inject_liquid_theme
from src.pwa import inject_pwa, inject_mobile_css
from src.hero import hero_html
from src.map_viz import drilldown_map_html
from src.config import neo4j_config
import altair as alt

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
    uri, auth = neo4j_config()
    return GraphDatabase.driver(uri, auth=auth)


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
    stats_raw = {
        "poi": run_cypher("MATCH (p:POI) RETURN count(p) AS n")[0]["n"],
        "relations": run_cypher("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"],
        "brands": run_cypher("MATCH (c:Chain) RETURN count(c) AS n")[0]["n"],
        "districts": run_cypher("MATCH (d:District) RETURN count(d) AS n")[0]["n"],
    }

    # ---- 左上角汉堡菜单(替代顶部 tab 栏)----
    nav_col, _ = st.columns([1, 11])
    with nav_col:
        with st.popover("☰", use_container_width=True):
            options = ["💬 对话", "🗺️ 地图分布", "🕸️ 图谱探索", "🔍 商家查询"]
            choice = st.radio("功能", options, key="nav",
                              label_visibility="collapsed", index=None)

    # ---- 页面路由 ----
    page = choice or "💬 对话"

    if page == "💬 对话":
        render_chat_page()

    elif page == "🗺️ 地图分布":
        st.markdown(
            "<div style='text-align:center;color:#8fa3bf;font-size:13px;margin-bottom:10px'>"
            "点击任意区县下钻查看统计与商家分布 · 可滚轮缩放</div>",
            unsafe_allow_html=True,
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

    elif page == "🕸️ 图谱探索":
        _render_graph_explore()

    elif page == "🔍 商家查询":
        _render_merchant_search()

    if page != "💬 对话":
        st.divider()
        st.caption("知识图谱作品集 | 采集 → 清洗 → 实体对齐 → 图谱增强 → Neo4j → 对话式问答")


def _render_graph_explore():
    """图谱探索页。"""
    st.markdown(
        "<div style='text-align:center;color:#8fa3bf;font-size:13px;margin-bottom:8px'>"
        "可拖拽节点、滚轮缩放、悬停查看详情</div>",
        unsafe_allow_html=True,
    )
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


def _render_merchant_search():
    """商家查询页。"""
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


if __name__ == "__main__":
    main()
