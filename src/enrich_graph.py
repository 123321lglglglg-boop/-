"""扩充图谱本体:从真实数据计算新关系,显著丰富图谱结构。

新增:
  1. BusinessArea 商圈节点 —— 坐标网格聚类,用区域内高频地名命名
  2. PriceLevel 价格带节点 —— 按人均分档(经济/大众/中档/高端)
  3. RatingTier 评分档节点 —— 按评分分档
  4. CategoryL2 中类 —— 用高德 type 的二级分类
  5. 品牌主营关系:Chain -[:主营]-> CategoryL2(该品牌门店最多的类)
  6. 邻近关系:POI -[:邻近 {距离}]-> POI(同商圈内互相距离 < 300m,限量)

用法: python src/enrich_graph.py
"""
import json
import math
import re
import warnings
from collections import Counter, defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")

from neo4j import GraphDatabase

BASE = Path(__file__).resolve().parent.parent
CLEAN = BASE / "data" / "processed" / "pois_clean.json"
NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "wlcb123456")

GRID = 0.02  # 约 2km 网格,用作商圈聚类的初始桶

# 从地址里提取可用于命名的地标词
LANDMARK_RE = re.compile(
    r"([一-龥]{2,8}(?:广场|商城|购物中心|大街|街|路|小区|国际|大厦|酒店|学校|医院|车站|公园|市场|中心|大学|中学|小学))"
)


def price_level(cost):
    if cost is None or cost <= 0:
        return None
    if cost <= 30:
        return ("经济", 1)
    if cost <= 60:
        return ("大众", 2)
    if cost <= 120:
        return ("中档", 3)
    return ("高端", 4)


def rating_tier(rating):
    if rating is None:
        return None
    if rating >= 4.5:
        return ("高分", 1)
    if rating >= 4.0:
        return ("良好", 2)
    if rating >= 3.5:
        return ("一般", 3)
    return ("较低", 4)


def cluster_business_areas(pois):
    """按坐标网格聚类,再用区域内高频地标词命名商圈。"""
    buckets = defaultdict(list)
    for p in pois:
        if p["lng"] is None or p["lat"] is None:
            continue
        key = (round(p["lng"] / GRID), round(p["lat"] / GRID))
        buckets[key].append(p)

    areas = {}
    for key, members in buckets.items():
        if len(members) < 15:  # 太稀疏的不算商圈
            continue
        # 用成员地址里最高频的地标词命名
        words = Counter()
        for m in members:
            for w in LANDMARK_RE.findall(m["address"] or ""):
                words[w] += 1
        if words:
            name = words.most_common(1)[0][0]
        else:
            # 没有地标的用区县 + 序号
            name = f"{members[0]['district']}片区"
        # 避免不同网格重名
        base = name
        i = 2
        while name in areas:
            name = f"{base}({i})"
            i += 1
        avg_lng = sum(m["lng"] for m in members) / len(members)
        avg_lat = sum(m["lat"] for m in members) / len(members)
        areas[name] = {
            "name": name,
            "district": members[0]["district"],
            "lng": avg_lng,
            "lat": avg_lat,
            "poi_ids": [m["poi_id"] for m in members],
            "size": len(members),
        }
    return areas


def haversine_m(lng1, lat1, lng2, lat2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearby_pairs(pois, areas):
    """同商圈内互相距离 < 300m 的 POI 对,每个 POI 最多连 3 个,避免关系爆炸。"""
    by_area = defaultdict(list)
    for area in areas.values():
        for pid in area["poi_ids"]:
            by_area[area["name"]].append(pid)
    index = {p["poi_id"]: p for p in pois}

    pairs = []
    seen = set()
    for area_name, pids in by_area.items():
        members = [index[pid] for pid in pids if pid in index]
        for i, a in enumerate(members):
            if a["lng"] is None or a["lat"] is None:
                continue
            linked = 0
            for b in members[i + 1:]:
                if linked >= 3:
                    break
                if b["lng"] is None or b["lat"] is None:
                    continue
                key = tuple(sorted((a["poi_id"], b["poi_id"])))
                if key in seen:
                    continue
                dist = haversine_m(a["lng"], a["lat"], b["lng"], b["lat"])
                if 0 < dist <= 300:
                    seen.add(key)
                    pairs.append({"a": a["poi_id"], "b": b["poi_id"], "dist": round(dist)})
                    linked += 1
    return pairs


def main():
    data = json.loads(CLEAN.read_text(encoding="utf-8"))
    pois = data["pois"]

    # ---- 1. 商圈 ----
    areas = cluster_business_areas(pois)
    print(f"识别商圈 {len(areas)} 个(成员 >= 15 家的网格)")

    # ---- 2. 分层 ----
    price_counts, rating_counts = Counter(), Counter()
    for p in pois:
        pl = price_level(p.get("cost"))
        rt = rating_tier(p.get("rating"))
        p["_price_level"] = pl[0] if pl else None
        p["_price_rank"] = pl[1] if pl else None
        p["_rating_tier"] = rt[0] if rt else None
        p["_rating_rank"] = rt[1] if rt else None
        if pl:
            price_counts[pl[0]] += 1
        if rt:
            rating_counts[rt[0]] += 1
    print(f"价格带: {dict(price_counts)}")
    print(f"评分档: {dict(rating_counts)}")

    # ---- 3. 邻近对 ----
    pairs = nearby_pairs(pois, areas)
    print(f"邻近关系对 {len(pairs)} 条")

    # ---- 4. 品牌主营 ----
    brand_cat = defaultdict(Counter)
    cat_by_poi = {}
    for p in pois:
        cat_by_poi[p["poi_id"]] = p["category_l3"]
        if p.get("chain_id"):
            brand_cat[p["chain_id"]][p["category_l3"]] += 1
    brand_main = {
        cid: cnt.most_common(1)[0][0]
        for cid, cnt in brand_cat.items()
        if cnt
    }
    print(f"品牌主营关系 {len(brand_main)} 条")

    # ---- 写入 Neo4j ----
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    with driver.session() as s:
        for c in [
            "CREATE CONSTRAINT area_name IF NOT EXISTS FOR (a:BusinessArea) REQUIRE a.name IS UNIQUE",
            "CREATE CONSTRAINT price_name IF NOT EXISTS FOR (p:PriceLevel) REQUIRE p.name IS UNIQUE",
            "CREATE CONSTRAINT rating_name IF NOT EXISTS FOR (r:RatingTier) REQUIRE r.name IS UNIQUE",
            "CREATE CONSTRAINT cat2_name IF NOT EXISTS FOR (c:CategoryL2) REQUIRE c.name IS UNIQUE",
        ]:
            s.run(c)

        # 商圈节点 + 关系
        s.run(
            """
            UNWIND $areas AS a
            MERGE (n:BusinessArea {name: a.name})
            SET n.district = a.district, n.lng = a.lng, n.lat = a.lat, n.size = a.size
            WITH n, a
            MATCH (d:District {name: a.district})
            MERGE (n)-[:属于区县]->(d)
            WITH n, a
            UNWIND a.poi_ids AS pid
            MATCH (p:POI {poi_id: pid})
            MERGE (p)-[:位于商圈]->(n)
            """,
            areas=list(areas.values()),
        )

        # 价格带 / 评分档
        s.run(
            """
            UNWIND $rows AS row
            MATCH (p:POI {poi_id: row.poi_id})
            FOREACH (_ IN CASE WHEN row.price IS NULL THEN [] ELSE [1] END |
                MERGE (pl:PriceLevel {name: row.price})
                SET pl.rank = row.price_rank
                MERGE (p)-[:价位]->(pl)
            )
            FOREACH (_ IN CASE WHEN row.rating IS NULL THEN [] ELSE [1] END |
                MERGE (rt:RatingTier {name: row.rating})
                SET rt.rank = row.rating_rank
                MERGE (p)-[:评分档]->(rt)
            )
            """,
            rows=[{"poi_id": p["poi_id"], "price": p["_price_level"],
                   "price_rank": p["_price_rank"], "rating": p["_rating_tier"],
                   "rating_rank": p["_rating_rank"]} for p in pois],
        )

        # 邻近关系
        for i in range(0, len(pairs), 1000):
            s.run(
                """
                UNWIND $pairs AS pair
                MATCH (a:POI {poi_id: pair.a})
                MATCH (b:POI {poi_id: pair.b})
                MERGE (a)-[:邻近 {距离: pair.dist}]->(b)
                """,
                pairs=pairs[i:i + 1000],
            )

        # 品牌主营
        s.run(
            """
            UNWIND $rows AS row
            MATCH (ch:Chain {chain_id: row.chain_id})
            MERGE (c:CategoryL2 {name: row.category})
            MERGE (ch)-[:主营]->(c)
            """,
            rows=[{"chain_id": cid, "category": cat} for cid, cat in brand_main.items()],
        )

        counts = s.run(
            """
            MATCH (p:POI) WITH count(p) AS poi
            MATCH ()-[r]->() WITH poi, count(r) AS rel
            MATCH (a:BusinessArea) WITH poi, rel, count(a) AS area
            RETURN poi, rel, area
            """
        ).single()
        print(f"\n更新后: POI={counts['poi']}, 关系总数={counts['rel']}, 商圈={counts['area']}")

        rel_types = s.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
        print("关系类型:", [r["relationshipType"] for r in rel_types])

    driver.close()


if __name__ == "__main__":
    main()
