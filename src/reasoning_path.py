"""推理路径提取:从图谱中还原查询的遍历过程。

思路:不依赖 LLM 编造,而是根据执行的 Cypher + 结果集,
用规则从真实图数据里回溯出「节点 → 关系 → 节点」的路径链。
"""
import re
import warnings

warnings.filterwarnings("ignore")

from neo4j import GraphDatabase

from src.config import neo4j_config

MAX_PATHS = 3          # 最多展示几条示例路径
MAX_STEPS = 5          # 单条路径最多几跳


def _run(cypher: str, **params):
    uri, auth = neo4j_config()
    d = GraphDatabase.driver(uri, auth=auth)
    try:
        with d.session() as s:
            return [dict(r) for r in s.run(cypher, **params)]
    finally:
        d.close()


def _key(rec: dict, kind: str):
    """从记录里取用于回溯的键。"""
    for k in ("poi_id", "名称", "name", "chain_id", "chain_name", "品牌"):
        if k in rec and rec[k]:
            return str(rec[k])
    return None


def extract_paths(question: str, cypher: str, records: list) -> list:
    """提取推理路径。返回 [{"start":…, "steps":[…]}, …]。"""
    if not records:
        return []

    c = cypher or ""
    paths = []

    try:
        if "邻近" in c:
            paths = _paths_proximity(records, question)
        elif "连锁品牌" in c:
            paths = _paths_chain(records)
        elif "位于商圈" in c and ("属于细类" in c or "属于品类" in c):
            paths = _paths_same_area(records)
        elif "位于商圈" in c or "商圈" in question:
            paths = _paths_same_area(records)
        else:
            paths = _paths_category(records)
    except Exception:
        paths = []

    return paths


def _paths_proximity(records: list, question: str = "") -> list:
    """邻近类查询:从起点店名回溯 邻近 关系与距离。

    起点是问题里提到的店(如「离乌兰图雅蒙餐最近的商家」→ 乌兰图雅蒙餐),
    不是结果里的店,所以先尝试从问题中提取。
    """
    # 从问题里找起点(去掉疑问词)
    anchor = None
    if question:
        q = question
        for kw in ["离", "附近的", "最近的", "最近的商家", "有哪些", "什么", "?", "?"]:
            q = q.replace(kw, " ")
        # 剩下的中文片段作为候选
        import re as _re
        cands = [w for w in _re.split(r"[ ,,。.、]+", q) if len(w) >= 2]
        if cands:
            anchor = max(cands, key=len)[:12]

    out = []
    queries = [anchor] if anchor else []
    if not queries:
        # 兜底:用结果里第一条店的商圈反查一个锚点
        queries = [r.get("名称") or r.get("name") for r in records[:1] if r.get("名称") or r.get("name")]

    for name in queries:
        if not name:
            continue
        rows = _run(
            """
            MATCH (a:POI)-[r:邻近]->(b:POI)
            WHERE a.name CONTAINS $name
            OPTIONAL MATCH (a)-[:位于商圈]->(area:BusinessArea)
            WITH a, b, r, area
            ORDER BY r.距离
            WITH a, area, collect({目标: b.name, 距离: r.距离})[..3] AS targets
            RETURN a.name AS 起点, area.name AS 商圈, targets
            LIMIT 1
            """,
            name=str(name),
        )
        if not rows:
            continue
        row = rows[0]
        start, area = row.get("起点") or name, row.get("商圈")
        chain = []
        if area:
            chain.append({"from": start, "rel": "位于商圈", "to": area, "note": "同商圈"})
        seen = set()
        for t in (row.get("targets") or []):
            tgt, dist = t.get("目标"), t.get("距离")
            if not tgt or tgt in seen:
                continue
            seen.add(tgt)
            chain.append({"from": area or start, "rel": f"邻近 {dist}m",
                          "to": tgt, "note": None})
        if chain:
            out.append({"start": start, "steps": chain})
            break   # 只渲染一个锚点的路径,避免重复
    return out


def _paths_same_area(records: list) -> list:
    """同商圈的推荐:起点 → 商圈 → 同商圈的商家。"""
    out = []
    for rec in records[:MAX_PATHS]:
        name = rec.get("名称") or rec.get("name")
        pid = _key(rec, "poi")
        if not name:
            continue
        row = _run(
            """
            MATCH (p:POI)
            WHERE p.poi_id = $pid OR p.name = $name
            OPTIONAL MATCH (p)-[:位于商圈]->(a:BusinessArea)
            OPTIONAL MATCH (p)-[:位于]->(dist:District)
            OPTIONAL MATCH (p)-[:属于细类]->(c3:CategoryL3)
            RETURN a.name AS 商圈, dist.name AS 区县, c3.name AS 品类,
                   p.rating AS 评分, p.cost AS 人均
            LIMIT 1
            """,
            pid=pid, name=name,
        )
        if not row:
            continue
        r = row[0]
        steps = []
        if r.get("区县"):
            steps.append({"from": name, "rel": "位于", "to": r["区县"], "note": None})
        if r.get("商圈"):
            steps.append({"from": name, "rel": "位于商圈", "to": r["商圈"], "note": "定位"})
            # 同商圈的其他商家
            peers = _run(
                """
                MATCH (a:BusinessArea {name: $area})<-[:位于商圈]-(q:POI)
                WHERE q.name <> $name AND q.rating IS NOT NULL
                RETURN q.name AS 名称, q.rating AS 评分, q.cost AS 人均
                ORDER BY q.rating DESC LIMIT 2
                """,
                area=r["商圈"], name=name,
            )
            for p in peers:
                steps.append({"from": r["商圈"], "rel": "包含", "to": p["名称"],
                              "note": f"{p['评分']}分"})
        if r.get("品类"):
            steps.append({"from": name, "rel": "属于品类", "to": r["品类"], "note": None})
        if steps:
            out.append({"start": name, "steps": steps})
    return out


def _paths_chain(records: list) -> list:
    """连锁品牌:品牌 → 各家门店。"""
    out = []
    rec = records[0]
    brand = rec.get("品牌") or rec.get("品牌名") or rec.get("chain_name")
    if not brand:
        return []
    shops = _run(
        """
        MATCH (p:POI)-[:连锁品牌]->(c:Chain)
        WHERE c.name CONTAINS $brand OR c.chain_id = $brand
        OPTIONAL MATCH (p)-[:位于]->(d:District)
        OPTIONAL MATCH (p)-[:位于商圈]->(a:BusinessArea)
        RETURN p.name AS 门店, d.name AS 区县, a.name AS 商圈, p.rating AS 评分
        LIMIT 6
        """,
        brand=str(brand),
    )
    steps = []
    for s_ in shops:
        note = " · ".join(x for x in [s_.get("区县"), s_.get("商圈")] if x)
        steps.append({"from": brand, "rel": "拥有门店", "to": s_["门店"], "note": note or None})
    if steps:
        out.append({"start": brand, "steps": steps})
    return out


def _paths_category(records: list) -> list:
    """品类/筛选类:商家 → 区县/商圈/品类/价位/评分档。"""
    out = []
    for rec in records[:MAX_PATHS]:
        name = rec.get("名称") or rec.get("name")
        pid = _key(rec, "poi")
        if not name:
            continue
        row = _run(
            """
            MATCH (p:POI)
            WHERE p.poi_id = $pid OR p.name = $name
            OPTIONAL MATCH (p)-[:位于]->(d:District)
            OPTIONAL MATCH (p)-[:位于商圈]->(a:BusinessArea)
            OPTIONAL MATCH (p)-[:属于细类]->(c3:CategoryL3)
            OPTIONAL MATCH (p)-[:价位]->(pl:PriceLevel)
            OPTIONAL MATCH (p)-[:评分档]->(rt:RatingTier)
            RETURN d.name AS 区县, a.name AS 商圈, c3.name AS 品类,
                   pl.name AS 价位, rt.name AS 评分档,
                   p.rating AS 评分, p.cost AS 人均, p.name AS 店名
            LIMIT 1
            """,
            pid=pid, name=name,
        )
        if not row:
            continue
        r = row[0]
        steps = []
        for rel, key, note in [
            ("位于", "区县", None),
            ("位于商圈", "商圈", None),
            ("属于品类", "品类", None),
            ("价位", "价位", f"人均{r['人均']:.0f}元" if r.get("人均") else None),
            ("评分档", "评分档", f"{r['评分']}分" if r.get("评分") else None),
        ]:
            if r.get(key):
                steps.append({"from": name, "rel": rel, "to": r[key], "note": note})
        if steps:
            out.append({"start": name, "steps": steps})
    return out


def _paths_generic(records: list) -> list:
    """兜底:展示首条结果的直接关系。"""
    return _paths_category(records)
