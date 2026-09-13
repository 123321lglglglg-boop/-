"""给高频查询字段建索引(文档《KG项目优化文档》第一部分 5.1)。

幂等:全部用 IF NOT EXISTS,可反复执行。

用法:
    python scripts/apply_indexes.py            # 建索引 + 打印索引现状
    python scripts/apply_indexes.py --bench    # 附:对比建索引前后执行计划的 dbHits

线上库是 Neo4j Aura,执行前先配好 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
(本地会读 aura_creds.txt 里那套就自己 export,或直接设环境变量)。
"""
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from src.db import get_driver, run_cypher  # noqa: E402

INDEX_FILE = BASE / "cypher" / "indexes.cypher"

# 用来验证索引是否真的生效的三个查询形态(和线上高频问法一致)
BENCH_QUERIES = {
    "店名 CONTAINS(蒙餐)": (
        "MATCH (p:POI) WHERE p.name CONTAINS '蒙餐' "
        "RETURN p.name AS 名称, p.rating AS 评分 ORDER BY 评分 DESC LIMIT 20"
    ),
    "按评分排序": (
        "MATCH (p:POI) WHERE p.rating IS NOT NULL "
        "RETURN p.name AS 名称, p.rating AS 评分 ORDER BY p.rating DESC LIMIT 20"
    ),
    "按人均过滤": (
        "MATCH (p:POI) WHERE p.cost <= 50 AND p.cost > 0 "
        "RETURN p.name AS 名称, p.cost AS 人均 ORDER BY p.cost LIMIT 20"
    ),
}


def statements() -> list:
    """从 cypher 文件里读出可执行语句(去掉注释和空行)。"""
    out = []
    for chunk in INDEX_FILE.read_text(encoding="utf-8").split(";"):
        lines = [l for l in chunk.splitlines() if not l.strip().startswith("//")]
        stmt = "\n".join(lines).strip()
        if stmt:
            out.append(stmt)
    return out


def profile(query: str) -> dict:
    """跑一次 PROFILE,返回顶层 dbHits / rows 和第一个扫表算子的信息。"""
    with get_driver().session() as s:
        rec = s.run("PROFILE " + query).consume()
    prof = rec.profile
    root_hits = prof["dbHits"]
    scan = {"op": "?", "hits": 0, "rows": 0}

    def walk(node):
        nonlocal scan
        op = str(node.get("operatorType", ""))
        if "Scan" in op or "Seek" in op:
            scan = {"op": op, "hits": node.get("dbHits") or 0, "rows": node.get("rows") or 0}
            return True
        for ch in (node.get("children") or []):
            if walk(ch):
                return True
        return False

    walk(prof)
    return {"dbHits": root_hits, "scan": scan}


def apply_indexes():
    print("=" * 68)
    print("建索引(幂等)")
    print("=" * 68)
    for stmt in statements():
        one_line = " ".join(stmt.split())
        try:
            run_cypher(stmt)
            print(f"  [OK]   {one_line[:90]}")
        except Exception as e:
            print(f"  [FAIL] {one_line[:90]}\n         {str(e)[:200]}")

    print()
    print("当前索引:")
    rows = run_cypher(
        """
        SHOW INDEXES YIELD name, labelsOrTypes, properties, type, state
        RETURN name, labelsOrTypes, properties, type, state
        ORDER BY type, name
        """
    )
    for r in rows:
        labels = ",".join(r["labelsOrTypes"] or [])
        props = ",".join(r["properties"] or [])
        print(f"  {r['type']:<9} {r['name']:<24} {labels}({props})  {r['state']}")


def bench():
    print()
    print("=" * 68)
    print("执行计划对比(看第一个扫表算子:全表扫 6949 行 vs 走索引)")
    print("=" * 68)
    for name, q in BENCH_QUERIES.items():
        r = profile(q)
        s = r["scan"]
        print(f"  {name:<22} {s['op']:<24} 扫描行数={s['rows']:<6} dbHits={s['hits']}")


def main():
    apply_indexes()
    if "--bench" in sys.argv:
        bench()
    print()
    print("完成。FULLTEXT 索引建好后要真正生效,查询需要用")
    print('  CALL db.index.fulltext.queryNodes("poi_name_fulltext", $kw)')


if __name__ == "__main__":
    main()
