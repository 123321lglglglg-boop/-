"""把本地 Neo4j 数据迁移到 Neo4j Aura(云端)。

比粘贴 Cypher 文件更可靠:直接驱动对驱动,批量复制。

用法:
    1. 注册 https://neo4j.com/cloud/aura-free/ 创建免费实例
    2. 拿到连接串(形如 neo4j+s://xxxx.databases.neo4j.io)和密码
    3. 运行:
       python scripts/migrate_to_aura.py "neo4j+s://xxxx.databases.neo4j.io" "密码"
"""
import sys
import time
import warnings

warnings.filterwarnings("ignore")

from neo4j import GraphDatabase

LOCAL_URI = "bolt://localhost:7687"
LOCAL_AUTH = ("neo4j", "wlcb123456")

LABEL_KEY = {
    "POI": "poi_id",
    "District": "name",
    "BusinessArea": "name",
    "CategoryL1": "name",
    "CategoryL3": "name",
    "Chain": "chain_id",
    "PriceLevel": "name",
    "RatingTier": "name",
    "CategoryL2": "name",
}
BATCH = 500


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    aura_uri, aura_password = sys.argv[1], sys.argv[2]

    print(f"源: {LOCAL_URI}")
    print(f"目标: {aura_uri}")
    src = GraphDatabase.driver(LOCAL_URI, auth=LOCAL_AUTH)
    dst = GraphDatabase.driver(aura_uri, auth=("neo4j", aura_password))

    # 先验证云连接
    dst.verify_connectivity()
    print("云连接成功\n")

    t0 = time.time()

    # ---- 约束 ----
    with dst.session() as s:
        for label, key in LABEL_KEY.items():
            s.run(f"CREATE CONSTRAINT {label.lower()}_key IF NOT EXISTS "
                  f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")
    print("约束创建完成")

    # ---- 节点 ----
    total_nodes = 0
    with src.session() as ss, dst.session() as ds:
        for label, key in LABEL_KEY.items():
            rows = [dict(r["p"]) for r in ss.run(f"MATCH (n:{label}) RETURN properties(n) AS p")]
            if not rows:
                continue
            for i in range(0, len(rows), BATCH):
                ds.run(
                    f"UNWIND $rows AS row MERGE (n:{label}) SET n = row",
                    rows=rows[i:i + BATCH],
                )
            total_nodes += len(rows)
            print(f"  {label}: {len(rows)} 个节点")
    print(f"节点总计 {total_nodes}\n")

    # ---- 关系 ----
    total_rels = 0
    from collections import defaultdict
    with src.session() as ss, dst.session() as ds:
        for label, key in LABEL_KEY.items():
            rels = [dict(r) for r in ss.run(
                f"MATCH (a:{label})-[r]->(b) "
                f"RETURN a.{key} AS ak, b.{key} AS bk, type(r) AS t, "
                f"labels(b)[0] AS bl, properties(r) AS rp"
            )]
            if not rels:
                continue
            # 按 (关系类型, 目标标签) 分组,每组一条写语句
            groups = defaultdict(list)
            for r in rels:
                groups[(r["t"], r["bl"])].append(r)
            for (rtype, blabel), items in groups.items():
                bkey = LABEL_KEY.get(blabel, "name")
                q = (
                    f"UNWIND $rows AS row "
                    f"MATCH (a:{label} {{{key}: row.ak}}) "
                    f"MATCH (b:{blabel} {{{bkey}: row.bk}}) "
                    f"MERGE (a)-[r:{rtype}]->(b) SET r = row.rp"
                )
                for i in range(0, len(items), BATCH):
                    ds.run(q, rows=items[i:i + BATCH])
            total_rels += len(rels)
            print(f"  {label}: {len(rels)} 条关系")

    print(f"关系总计 {total_rels}")
    print(f"\n迁移完成,用时 {time.time() - t0:.0f} 秒")

    # ---- 校验 ----
    with dst.session() as s:
        n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        r = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    print(f"云端校验:节点 {n} · 关系 {r}")

    src.close()
    dst.close()


if __name__ == "__main__":
    main()
