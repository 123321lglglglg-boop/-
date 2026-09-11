"""把本地 Neo4j 的全部数据导出成 Cypher 脚本,供导入 Neo4j Aura。

用法:
    python scripts/export_cypher.py

产出:
    data/export/graph_export.cypher  —— 可在 Aura Browser 里直接粘贴执行
"""
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from neo4j import GraphDatabase

BASE = Path(__file__).resolve().parent.parent
OUT_DIR = BASE / "data" / "export"
OUT = OUT_DIR / "graph_export.cypher"

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "wlcb123456")

# 节点标签 → 唯一键
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


def esc(v):
    """转义 Cypher 字符串。"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    lines = ["// 乌兰察布知识图谱导出 — 在 Neo4j Browser 里分段执行", ""]

    with driver.session() as s:
        # ---- 约束 ----
        lines.append("// === 约束 ===")
        for label, key in LABEL_KEY.items():
            lines.append(
                f"CREATE CONSTRAINT {label.lower()}_key IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE;"
            )
        lines.append("")

        # ---- 节点 ----
        total_nodes = 0
        for label, key in LABEL_KEY.items():
            rows = list(s.run(f"MATCH (n:{label}) RETURN properties(n) AS p"))
            if not rows:
                continue
            lines.append(f"// === 节点 {label}({len(rows)} 个)===")
            batch = []
            for i, r in enumerate(rows):
                props = r["p"]
                kv = ", ".join(f"{k}: {esc(v)}" for k, v in props.items())
                batch.append(f"CREATE (:{label} {{{kv}}})")
                if len(batch) >= 200:
                    lines.append(";\n".join(batch) + ";")
                    batch = []
                total_nodes += 1
            if batch:
                lines.append(";\n".join(batch) + ";")
            lines.append("")

        # ---- 关系 ----
        total_rels = 0
        for label, key in LABEL_KEY.items():
            rels = list(s.run(
                f"MATCH (a:{label})-[r]->(b) "
                f"RETURN a.{key} AS ak, b.{key} AS bk, type(r) AS t, "
                f"labels(b)[0] AS bl, properties(r) AS rp"
            ))
            if not rels:
                continue
            lines.append(f"// === 关系 from {label}({len(rels)} 条)===")
            batch = []
            for r in rels:
                bkey = LABEL_KEY.get(r["bl"], "name")
                props = r["rp"] or {}
                prop_str = (" {" + ", ".join(f"{k}: {esc(v)}" for k, v in props.items()) + "}") if props else ""
                batch.append(
                    f"MATCH (a:{label} {{{key}: {esc(r['ak'])}}}), "
                    f"(b:{r['bl']} {{{bkey}: {esc(r['bk'])}}}) "
                    f"CREATE (a)-[:{r['t']}{prop_str}]->(b)"
                )
                if len(batch) >= 200:
                    lines.append(";\n".join(batch) + ";")
                    batch = []
                total_rels += 1
            if batch:
                lines.append(";\n".join(batch) + ";")
            lines.append("")

    driver.close()

    header = [
        "// 乌兰察布本地生活知识图谱 — 完整导出",
        f"// 节点 {total_nodes} 个 · 关系 {total_rels} 条",
        "// 用法:Neo4j Aura Browser 里分段粘贴执行(建议按 节点/关系 分块)",
        "",
    ]
    OUT.write_text("\n".join(header + lines), encoding="utf-8")

    size_mb = OUT.stat().st_size / 1048576
    print(f"导出完成: {OUT}")
    print(f"  节点 {total_nodes} 个 · 关系 {total_rels} 条 · 文件 {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
