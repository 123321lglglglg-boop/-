"""知识图谱问答:把自然语言问题解析为 Cypher 查询并返回答案。

支持的问法示例:
    集宁区人均 50 以下的餐厅有哪些?
    评分最高的蒙餐馆在哪?
    四子王旗有什么景点?
    蜜雪冰城在乌兰察布有几家店?
    乌兰察布有多少家火锅店?

用法:
    python src/qa.py                    # 交互模式
    python src/qa.py "集宁区评分最高的餐厅"
"""
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "wlcb123456")

# ---- 词典:把口语映射到图谱里的真实名称 ----

DISTRICTS = ["集宁区", "丰镇市", "卓资县", "化德县", "商都县", "兴和县",
             "凉城县", "察右前旗", "察右中旗", "察右后旗", "四子王旗"]
DISTRICT_ALIAS = {d: d for d in DISTRICTS}
DISTRICT_ALIAS.update({"集宁": "集宁区", "丰镇": "丰镇市", "卓资": "卓资县",
                       "化德": "化德县", "商都": "商都县", "兴和": "兴和县",
                       "凉城": "凉城县", "察右前": "察右前旗", "察右中": "察右中旗",
                       "察右后": "察右后旗", "四子王": "四子王旗", "中旗": "察右中旗",
                       "后旗": "察右后旗", "前旗": "察右前旗"})

# 口语 → 图谱细类名(或店名关键词,用 name_kw 标记)
CATEGORY_MAP = {
    "火锅": {"l3": "火锅店"},
    "蒙餐": {"name_kw": "蒙餐"},
    "内蒙菜": {"name_kw": "蒙餐"},
    "蒙餐馆": {"name_kw": "蒙餐"},
    "莜面": {"name_kw": "莜面"},
    "烧麦": {"name_kw": "烧麦"},
    "烧烤": {"name_kw": "烧烤"},
    "咖啡": {"l3": "咖啡厅"},
    "咖啡厅": {"l3": "咖啡厅"},
    "甜品": {"l3": "甜品店"},
    "蛋糕": {"l3": "甜品店"},
    "快餐": {"l3": "快餐厅"},
    "酒店": {"l1": "住宿服务"},
    "宾馆": {"l1": "住宿服务"},
    "旅馆": {"l1": "住宿服务"},
    "住宿": {"l1": "住宿服务"},
    "景点": {"l1": "风景名胜"},
    "景区": {"l1": "风景名胜"},
    "寺庙": {"l3": "寺庙道观"},
    "教堂": {"l3": "教堂"},
    "商场": {"l3": "普通商场"},
    "购物": {"l1": "购物服务"},
    "清真": {"l3": "清真菜馆"},
    "川菜": {"l3": "四川菜(川菜)"},
    "东北菜": {"l3": "东北菜"},
    "西餐": {"l3": "西餐厅(综合风味)"},
    "日料": {"l3": "日本料理"},
    "日本料理": {"l3": "日本料理"},
    "韩国料理": {"l3": "韩国料理"},
    "餐厅": {"l1": "餐饮服务"},
    "饭店": {"l1": "餐饮服务"},
    "吃的": {"l1": "餐饮服务"},
}

DEFAULT_LIMIT = 20


def parse(question: str) -> dict:
    """把问题解析成结构化查询条件。"""
    q = question.strip()
    plan = {"district": None, "category": None, "cost_max": None, "cost_min": None,
            "rating_min": None, "limit": DEFAULT_LIMIT, "sort": None,
            "count": False, "by_district": False, "brand_hint": None}

    # 分布意图优先级最高(问的是"哪个区县最多/分布",不是具体某区的某类商家)
    if any(k in q for k in ["分布", "哪个区县", "哪个区", "各区县", "哪些区县", "哪些区", "区县对比"]):
        plan["by_district"] = True
        return plan

    # 区县
    for alias, full in sorted(DISTRICT_ALIAS.items(), key=lambda x: -len(x[0])):
        if alias in q:
            plan["district"] = full
            break

    # 品类(行长优先,避免"蒙餐馆"被"餐馆"截胡)
    for kw, cat in sorted(CATEGORY_MAP.items(), key=lambda x: -len(x[0])):
        if kw in q:
            plan["category"] = cat
            break

    # 人均/价格
    m = re.search(r"人均\s*(\d+)\s*(?:元)?\s*(以下|以内|不到|低于)", q) or \
        re.search(r"(\d+)\s*(?:元|块)?\s*(?:以下|以内|之内)", q) or \
        re.search(r"人均\s*(?:不超过|低于|少于)\s*(\d+)", q)
    if m:
        plan["cost_max"] = float(m.group(1))
    m2 = re.search(r"人均\s*(\d+)\s*(?:元)?\s*(以上|往上)", q)
    if m2:
        plan["cost_min"] = float(m2.group(1))

    # 评分
    m = re.search(r"评分\s*(\d+(?:\.\d+)?)\s*(以上|往上的?|不低于)", q) or \
        re.search(r"(\d+(?:\.\d+)?)\s*分\s*(?:以上|之上)", q)
    if m:
        plan["rating_min"] = float(m.group(1))

    # 排序意图
    if any(k in q for k in ["评分最高", "最好的", "最高分", "评价最好", "口碑最好", "好吃"]):
        plan["sort"] = "rating"
    elif any(k in q for k in ["最便宜", "人均最低", "性价比"]):
        plan["sort"] = "cost_asc"

    # 计数意图
    if any(k in q for k in ["多少家", "几家", "有多少", "数量"]):
        plan["count"] = True

    # 连锁品牌查询:问题里直接出现品牌名(去数据库里反查)
    plan["brand_hint"] = None
    if any(k in q for k in ["多少家", "几家", "门店", "连锁"]):
        brand_m = re.match(r"^(.+?)(?:在[^有]*?)?(?:有|开了)?(?:多少家|几家)", q)
        if brand_m and not plan["category"]:
            brand = brand_m.group(1)
            for w in ["乌兰察布", "全市"] + DISTRICTS:
                brand = brand.replace(w, "")
            brand = brand.strip("在的有多少家几门店包含 ")
            if 2 <= len(brand) <= 10:
                plan["brand_hint"] = brand

    return plan


def build_query(plan: dict):
    """把解析结果组装成 Cypher 语句和参数。"""
    where, params = [], {}

    # 品类和区县是两条独立的关系链,必须分开 MATCH,不能串成一条路径
    matches = ["MATCH (p:POI)"]
    if plan["category"]:
        cat = plan["category"]
        if "l1" in cat:
            matches.append("MATCH (p)-[:属于品类]->(c:CategoryL1 {name: $cat})")
            params["cat"] = cat["l1"]
        elif "l3" in cat:
            matches.append("MATCH (p)-[:属于细类]->(c:CategoryL3 {name: $cat})")
            params["cat"] = cat["l3"]
        elif "name_kw" in cat:
            where.append("p.name CONTAINS $name_kw")
            params["name_kw"] = cat["name_kw"]

    if plan["district"]:
        matches.append("MATCH (p)-[:位于]->(d:District {name: $district})")
        params["district"] = plan["district"]

    if plan["cost_max"] is not None:
        where.append("p.cost IS NOT NULL AND p.cost > 0 AND p.cost <= $cost_max")
        params["cost_max"] = plan["cost_max"]
    if plan.get("cost_min") is not None:
        where.append("p.cost >= $cost_min")
        params["cost_min"] = plan["cost_min"]
    if plan["rating_min"] is not None:
        where.append("p.rating IS NOT NULL AND p.rating >= $rating_min")
        params["rating_min"] = plan["rating_min"]

    match = " ".join(matches)

    if plan["by_district"]:
        q = ("MATCH (p:POI)-[:位于]->(d:District) "
             "RETURN d.name AS 区县, count(p) AS 数量 ORDER BY 数量 DESC")
        return q, {}

    where_clause = (" WHERE " + " AND ".join(where)) if where else ""

    if plan["count"]:
        q = f"{match}{where_clause} RETURN count(p) AS 数量"
        return q, params

    if plan["sort"] == "rating":
        order = "p.rating DESC"
        where_clause += (" AND " if where else " WHERE ") + "p.rating IS NOT NULL"
    elif plan["sort"] == "cost_asc":
        order = "p.cost ASC"
        where_clause += (" AND " if where else " WHERE ") + "p.cost IS NOT NULL AND p.cost > 0"
    else:
        order = "p.rating DESC"

    q = (f"{match}{where_clause} "
         f"RETURN p.name AS 名称, p.rating AS 评分, p.cost AS 人均, p.address AS 地址 "
         f"ORDER BY {order} LIMIT $limit")
    params["limit"] = plan["limit"]
    return q, params


def query_brand(brand_hint: str):
    """连锁品牌查询:模糊匹配品牌名。"""
    q = ("MATCH (p:POI)-[:连锁品牌]->(c:Chain) "
         "WHERE c.name CONTAINS $kw "
         "RETURN c.name AS 品牌, count(p) AS 门店数, collect(p.name)[..5] AS 部分门店")
    return q, {"kw": brand_hint}


def render(plan: dict, records: list) -> str:
    if not records:
        return "没有找到符合条件的商家。可以换个区县或品类试试。"

    if plan.get("by_district"):
        lines = ["各区县 POI 分布:"]
        for r in records:
            lines.append(f"  {r['区县']}: {r['数量']} 家")
        return "\n".join(lines)

    if plan.get("brand_hint") and "品牌" in records[0]:
        lines = []
        for r in records:
            lines.append(f"{r['品牌']}:{r['门店数']} 家门店")
            for n in r["部分门店"]:
                lines.append(f"    - {n}")
        return "\n".join(lines)

    if plan.get("count") and "数量" in records[0]:
        return f"共找到 {records[0]['数量']} 家。"

    lines = [f"找到 {len(records)} 家:"]
    for i, r in enumerate(records, 1):
        rating = f"{r['评分']}分" if r.get("评分") else "无评分"
        cost = f"人均{r['人均']:.0f}元" if r.get("人均") else "人均未知"
        lines.append(f"  {i}. {r['名称']}  [{rating} / {cost}]  {r.get('地址','')}")
    return "\n".join(lines)


def answer(question: str) -> str:
    plan = parse(question)

    if plan["brand_hint"]:
        q, params = query_brand(plan["brand_hint"])
    else:
        q, params = build_query(plan)

    d = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    with d.session() as s:
        records = [dict(r) for r in s.run(q, **params)]
    d.close()
    return render(plan, records)


def main():
    if len(sys.argv) > 1:
        print(answer(" ".join(sys.argv[1:])))
        return

    print("乌兰察布本地生活知识图谱问答(输入 q 退出)")
    print("试试:集宁区人均50以下的餐厅 / 评分最高的蒙餐馆 / 四子王旗有什么景点 / 蜜雪冰城有几家店")
    print()
    while True:
        try:
            q = input("问> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q or q.lower() in {"q", "quit", "exit", "退出"}:
            break
        try:
            print(answer(q))
        except Exception as e:
            print(f"查询出错: {e}")
        print()


if __name__ == "__main__":
    main()
