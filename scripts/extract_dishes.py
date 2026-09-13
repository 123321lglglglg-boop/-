"""从 tag 字段提取菜品实体,建立 (POI)-[:招牌菜]->(Dish) 关系。

为什么值得做:
  现在图谱只有粗品类(火锅店/中餐厅),用户问"哪里有羊杂"匹配不到。
  提取菜品后可以精确检索,这是"想吃什么"这类高频真实需求。

数据来源:高德 POI 的 tag 字段(1776 家有,逗号分隔的菜品列表),
         即 data/raw/poi.json —— 不依赖任何已有图数据库。

用法:
    python scripts/extract_dishes.py --dry-run      # 只统计,不写库
    python scripts/extract_dishes.py                # 写入(目标库由 NEO4J_URI 决定)

目标库跟随 src.config.neo4j_config():不设环境变量就是本地 WSL 库,
设了 NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD 就是线上 Aura。
写入是幂等的(MERGE),可以反复执行。
"""
import json
import sys
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
RAW = BASE / "data" / "raw" / "poi.json"

from src.db import get_driver  # noqa: E402

# 过滤规则:这些不是菜品,是其他标签
NOT_DISH = {
    "中餐", "西餐", "快餐", "小吃", "特色", "推荐", "其他", "暂无",
    "免费", "wifi", "WiFi", "包间", "停车",
}
MAX_LEN = 12
MIN_LEN = 2


def parse_tags(tag_str: str) -> list:
    """解析 tag 字符串,返回菜品列表。"""
    if not tag_str:
        return []
    # 统一分隔符
    t = tag_str.replace(";", ",").replace("、", ",").replace("/", ",")
    parts = []
    for x in t.split(","):
        x = x.strip()
        if not x:
            continue
        if x in NOT_DISH:
            continue
        if not (MIN_LEN <= len(x) <= MAX_LEN):
            continue
        # 排除纯数字/英文
        if not any("一" <= ch <= "鿿" for ch in x):
            continue
        parts.append(x)
    return parts


def main():
    raw = json.loads(RAW.read_text(encoding="utf-8"))

    poi_dishes = {}       # poi_id → [菜品]
    dish_counter = Counter()

    for p in raw:
        pid = p.get("id")
        if not pid:
            continue
        dishes = parse_tags(p.get("tag") or "")
        if dishes:
            poi_dishes[pid] = dishes
            for d in set(dishes):
                dish_counter[d] += 1

    print(f"有菜品的商家: {len(poi_dishes)} / {len(raw)}")
    print(f"不同菜品数: {len(dish_counter)}")

    # 只保留至少有 2 家店卖的菜品(过滤噪音,如某家店的独有菜名拼写错误)
    valid_dishes = {d for d, c in dish_counter.items() if c >= 2}
    print(f"其中 >=2 家店的菜品: {len(valid_dishes)}")

    # 重新过滤 poi_dishes
    filtered = {}
    for pid, ds in poi_dishes.items():
        keep = [d for d in ds if d in valid_dishes]
        if keep:
            filtered[pid] = sorted(set(keep))
    print(f"过滤后有效商家: {len(filtered)}")
    print()
    print("=== 高频菜品 TOP20 ===")
    for d, c in dish_counter.most_common(20):
        if d in valid_dishes:
            print(f"  {d}: {c} 家")

    # ---- 写入图数据库 ----
    rows = [{"poi_id": pid, "dishes": ds} for pid, ds in filtered.items()]
    print()
    print(f"待写入: {len(rows)} 家商家 / {sum(len(r['dishes']) for r in rows)} 条关系")

    if "--dry-run" in sys.argv:
        print("(--dry-run:未写库)")
        return

    driver = get_driver()
    with driver.session() as s:
        s.run("CREATE CONSTRAINT dish_name IF NOT EXISTS FOR (d:Dish) REQUIRE d.name IS UNIQUE")

        # 批量建立关系
        batch = 200
        total_rel = 0
        for i in range(0, len(rows), batch):
            res = s.run(
                """
                UNWIND $rows AS row
                MATCH (p:POI {poi_id: row.poi_id})
                UNWIND row.dishes AS dname
                MERGE (d:Dish {name: dname})
                MERGE (p)-[:招牌菜]->(d)
                RETURN count(*) AS c
                """,
                rows=rows[i:i + batch],
            ).single()
            total_rel += res["c"] if res else 0
        print(f"已建立 招牌菜 关系: {total_rel}")

        # 统计
        stats = s.run("""
            MATCH (d:Dish) WITH count(d) AS dishes
            MATCH ()-[r:招牌菜]->() WITH dishes, count(r) AS rels
            RETURN dishes, rels
        """).single()
        print(f"图谱中 Dish 实体: {stats['dishes']}")
        print(f"图谱中 招牌菜 关系: {stats['rels']}")

        # 验证:羊杂
        rows2 = s.run("""
            MATCH (p:POI)-[:招牌菜]->(d:Dish {name:'羊杂'})
            OPTIONAL MATCH (p)-[:位于]->(dist:District)
            RETURN p.name AS 店名, dist.name AS 区县, p.rating AS 评分
            ORDER BY p.rating DESC LIMIT 5
        """).data()
        print()
        print("=== 验证:卖羊杂的店 ===")
        for r in rows2:
            print(f"  {r['店名'][:26]:28s} {r['区县']} {r['评分']}分")


if __name__ == "__main__":
    main()
