"""从 Neo4j 抽取用于可视化的子图数据。"""
import warnings

warnings.filterwarnings("ignore")

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "wlcb123456")


def _driver():
    return GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)


def _run(query, **params):
    d = _driver()
    try:
        with d.session() as s:
            return [dict(r) for r in s.run(query, **params)]
    finally:
        d.close()


def overview_subgraph(district=None, limit_pois=40):
    """总览子图:商圈/区县/品类/品牌/POI 多层结构。

    以每个区县高分 POI 为种子,连接它们的全部关系,呈现真实网络感。
    """
    where = "WHERE d.name = $district" if district else ""
    rows = _run(
        f"""
        MATCH (p:POI)-[:位于]->(d:District)
        {where}
        WITH d, p ORDER BY p.rating DESC
        WITH d, collect(p)[..$per_district] AS pois
        UNWIND pois AS p
        OPTIONAL MATCH (p)-[:位于商圈]->(a:BusinessArea)
        OPTIONAL MATCH (p)-[:属于细类]->(c3:CategoryL3)
        OPTIONAL MATCH (p)-[:连锁品牌]->(ch:Chain)
        OPTIONAL MATCH (p)-[:价位]->(pl:PriceLevel)
        RETURN p.poi_id AS pid, p.name AS pname, p.rating AS rating, p.cost AS cost,
               d.name AS district, a.name AS area, c3.name AS cat3,
               ch.chain_id AS chain_id, ch.name AS chain_name, pl.name AS price_level
        """,
        district=district, per_district=limit_pois,
    )

    nodes, edges = {}, {}
    cat_l1_present = {}

    def add_node(nid, name, ntype, value=None, info=None):
        if nid in nodes:
            return
        nodes[nid] = {"id": nid, "name": name, "type": ntype,
                      "value": value, "info": info}

    def add_edge(src, tgt, etype):
        key = (src, tgt, etype)
        if key not in edges:
            edges[key] = {"source": src, "target": tgt, "type": etype}

    # 细类 → 粗类的映射(用于加一层分类结构)
    cat_map = {r["l3"]: r["l1"] for r in _run(
        "MATCH (c3:CategoryL3)-[:子类]->(c1:CategoryL1) RETURN c3.name AS l3, c1.name AS l1"
    )}

    for r in rows:
        pid = r["pid"]
        rating_txt = f"{r['rating']}分" if r["rating"] else "无评分"
        cost_txt = f"人均{r['cost']:.0f}元" if r["cost"] else "人均未知"
        add_node(pid, r["pname"], "POI",
                 value=10 + (r["rating"] or 3) * 1.5,
                 info=f"{rating_txt} / {cost_txt}")

        if r["district"]:
            add_node(f"d:{r['district']}", r["district"], "District", value=40)
            add_edge(pid, f"d:{r['district']}", "位于")
        if r["area"]:
            add_node(f"a:{r['area']}", r["area"], "BusinessArea", value=26,
                     info="商圈")
            add_edge(pid, f"a:{r['area']}", "位于商圈")
        if r["cat3"]:
            add_node(f"c3:{r['cat3']}", r["cat3"], "CategoryL3", value=16, info="品类")
            add_edge(pid, f"c3:{r['cat3']}", "属于细类")
            l1 = cat_map.get(r["cat3"])
            if l1:
                add_node(f"c1:{l1}", l1, "CategoryL1", value=28, info="粗类")
                add_edge(f"c3:{r['cat3']}", f"c1:{l1}", "子类")
        if r["chain_id"]:
            add_node(r["chain_id"], r["chain_name"], "Chain", value=18, info="连锁品牌")
            add_edge(pid, r["chain_id"], "连锁品牌")
        if r["price_level"]:
            add_node(f"pl:{r['price_level']}", r["price_level"], "PriceLevel", value=22, info="价格带")
            add_edge(pid, f"pl:{r['price_level']}", "价位")

    return list(nodes.values()), list(edges.values())


def poi_neighborhood(poi_name_kw, limit=1):
    """以某个商家为中心的子图:它的全部关系 + 邻近商家。"""
    anchors = _run(
        """
        MATCH (p:POI) WHERE p.name CONTAINS $kw
        RETURN p.poi_id AS pid ORDER BY coalesce(p.rating, 0) DESC LIMIT $limit
        """,
        kw=poi_name_kw, limit=limit,
    )
    if not anchors:
        return [], []

    nodes, edges = {}, {}

    def add_node(nid, name, ntype, value=None, info=None):
        nodes.setdefault(nid, {"id": nid, "name": name, "type": ntype,
                               "value": value, "info": info})

    def add_edge(src, tgt, etype):
        edges.setdefault((src, tgt, etype),
                         {"source": src, "target": tgt, "type": etype})

    for a in anchors:
        pid = a["pid"]
        center = _run(
            """
            MATCH (p:POI {poi_id: $pid})
            OPTIONAL MATCH (p)-[:位于]->(d:District)
            OPTIONAL MATCH (p)-[:位于商圈]->(a:BusinessArea)
            OPTIONAL MATCH (p)-[:属于细类]->(c3:CategoryL3)
            OPTIONAL MATCH (p)-[:连锁品牌]->(ch:Chain)
            OPTIONAL MATCH (p)-[:价位]->(pl:PriceLevel)
            OPTIONAL MATCH (p)-[:评分档]->(rt:RatingTier)
            RETURN p.name AS pname, p.rating AS rating, p.cost AS cost,
                   d.name AS district, a.name AS area, c3.name AS cat3,
                   ch.chain_id AS chain_id, ch.name AS chain_name,
                   pl.name AS price_level, rt.name AS rating_tier
            """,
            pid=pid,
        )[0]

        rating_txt = f"{center['rating']}分" if center["rating"] else "无评分"
        cost_txt = f"人均{center['cost']:.0f}元" if center["cost"] else "人均未知"
        add_node(pid, center["pname"], "POI", value=30,
                 info=f"{rating_txt} / {cost_txt}")
        if center["district"]:
            add_node(f"d:{center['district']}", center["district"], "District", 40)
            add_edge(pid, f"d:{center['district']}", "位于")
        if center["area"]:
            add_node(f"a:{center['area']}", center["area"], "BusinessArea", 26)
            add_edge(pid, f"a:{center['area']}", "位于商圈")
        if center["cat3"]:
            add_node(f"c3:{center['cat3']}", center["cat3"], "CategoryL3", 16)
            add_edge(pid, f"c3:{center['cat3']}", "属于细类")
        if center["chain_id"]:
            add_node(center["chain_id"], center["chain_name"], "Chain", 18)
            add_edge(pid, center["chain_id"], "连锁品牌")
        if center["price_level"]:
            add_node(f"pl:{center['price_level']}", center["price_level"], "PriceLevel", 22)
            add_edge(pid, f"pl:{center['price_level']}", "价位")
        if center["rating_tier"]:
            add_node(f"rt:{center['rating_tier']}", center["rating_tier"], "RatingTier", 20)
            add_edge(pid, f"rt:{center['rating_tier']}", "评分档")

        # 邻近商家
        for nb in _run(
            """
            MATCH (p:POI {poi_id: $pid})-[r:邻近]->(q:POI)
            RETURN q.poi_id AS qid, q.name AS qname, r.距离 AS dist
            LIMIT 8
            """,
            pid=pid,
        ):
            add_node(nb["qid"], nb["qname"], "POI", 12, info=f"距中心 {nb['dist']} 米")
            add_edge(pid, nb["qid"], "邻近")

    return list(nodes.values()), list(edges.values())
