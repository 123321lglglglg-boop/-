"""导入 Neo4j。

前置:
  1. 安装 Neo4j(推荐 Neo4j Desktop / Community 5.x,本地起库)
  2. 设置环境变量: NEO4J_URI(默认 bolt://localhost:7687)、NEO4J_USER(默认 neo4j)、NEO4J_PASSWORD

用法: python src/load_neo4j.py
"""
import json
import os
from pathlib import Path

from neo4j import GraphDatabase

BASE = Path(__file__).resolve().parent.parent
CLEAN = BASE / "data" / "processed" / "pois_clean.json"

CONSTRAINTS = [
    "CREATE CONSTRAINT poi_id IF NOT EXISTS FOR (p:POI) REQUIRE p.poi_id IS UNIQUE",
    "CREATE CONSTRAINT district_name IF NOT EXISTS FOR (d:District) REQUIRE d.name IS UNIQUE",
    "CREATE CONSTRAINT cat_l1_name IF NOT EXISTS FOR (c:CategoryL1) REQUIRE c.name IS UNIQUE",
    "CREATE CONSTRAINT cat_l3_name IF NOT EXISTS FOR (c:CategoryL3) REQUIRE c.name IS UNIQUE",
    "CREATE CONSTRAINT chain_id IF NOT EXISTS FOR (c:Chain) REQUIRE c.chain_id IS UNIQUE",
]


def main():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not password:
        print("请设置环境变量 NEO4J_PASSWORD")
        return

    data = json.loads(CLEAN.read_text(encoding="utf-8"))
    pois = data["pois"]

    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as s:
        for c in CONSTRAINTS:
            s.run(c)

        # 分批写入,避免单事务过大
        batch = 500
        for i in range(0, len(pois), batch):
            s.run(
                """
                UNWIND $rows AS row
                MERGE (p:POI {poi_id: row.poi_id})
                SET p.name = row.name, p.address = row.address,
                    p.lng = row.lng, p.lat = row.lat,
                    p.rating = row.rating, p.cost = row.cost,
                    p.tel = row.tel, p.open_hours = row.open_hours,
                    p.is_chain = row.is_chain
                WITH row, p
                MERGE (d:District {name: row.district})
                MERGE (p)-[:位于]->(d)
                WITH row, p
                MERGE (c1:CategoryL1 {name: row.category_l1})
                MERGE (p)-[:属于品类]->(c1)
                WITH row, p
                MERGE (c3:CategoryL3 {name: row.category_l3})
                MERGE (p)-[:属于细类]->(c3)
                MERGE (c3)-[:子类]->(c1)
                WITH row, p
                FOREACH (_ IN CASE WHEN row.chain_id IS NULL THEN [] ELSE [1] END |
                    MERGE (ch:Chain {chain_id: row.chain_id})
                    SET ch.name = row.chain_key
                    MERGE (p)-[:连锁品牌]->(ch)
                )
                """,
                rows=pois[i:i + batch],
            )
            print(f"已导入 {min(i + batch, len(pois))}/{len(pois)}")

        counts = s.run(
            """
            MATCH (p:POI) WITH count(p) AS poi
            MATCH (d:District) WITH poi, count(d) AS district
            MATCH (c:CategoryL3) WITH poi, district, count(c) AS cat3
            MATCH (ch:Chain) WITH poi, district, cat3, count(ch) AS chain
            MATCH ()-[r]->() WITH poi, district, cat3, chain, count(r) AS rel
            RETURN poi, district, cat3, chain, rel
            """
        ).single()
        print(f"库内统计: POI={counts['poi']}, 区县={counts['district']}, "
              f"细类={counts['cat3']}, 连锁品牌={counts['chain']}, 关系={counts['rel']}")

    driver.close()


if __name__ == "__main__":
    main()
