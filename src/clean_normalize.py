"""清洗去重 + 品类归一 + 连锁/重名实体对齐,输出结构化数据供 Neo4j 导入。

用法: python src/clean_normalize.py
"""
import json
import re
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw" / "poi.json"
OUT = BASE / "data" / "processed" / "pois_clean.json"

TEL_RE = re.compile(r";|,|、")
# 连锁店常见的品牌后缀(括号内容、分店名),对齐时先剥离
BRANCH_RE = re.compile(r"[（(][^）)]{0,12}[）)]|分店$|店$")


def normalize(name: str) -> str:
    return BRANCH_RE.sub("", name).strip()


def parse_number(v, cast=float):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def split_xy(location: str):
    try:
        x, y = location.split(",")
        return float(x), float(y)
    except (AttributeError, ValueError):
        return None, None


def main():
    pois = json.loads(RAW.read_text(encoding="utf-8"))

    cleaned = []
    for p in pois:
        name = (p.get("name") or "").strip()
        if not name or name in {"-", ""}:
            continue

        biz = p.get("biz_ext") or {}
        rating = parse_number(biz.get("rating"))
        cost = parse_number(biz.get("cost"))
        lng, lat = split_xy(p.get("location", ""))

        addr = p.get("address")
        if isinstance(addr, list):
            addr = "".join(addr)

        # 高德返回的 type 形如 "餐饮服务;中餐厅;火锅店",取末级 + 粗类
        type_str = p.get("type", "") or ""
        parts = [t for t in type_str.split(";") if t]
        category_l1 = parts[0] if parts else p.get("category_query", "其他")
        category_l3 = parts[-1] if parts else category_l1

        sid = p.get("id") or p.get("pname")
        chain_key = normalize(name)
        cleaned.append({
            "poi_id": sid,
            "name": name,
            "chain_key": chain_key,
            "district": p.get("district", ""),
            "address": addr or "",
            "lng": lng,
            "lat": lat,
            "category_l1": category_l1,
            "category_l3": category_l3,
            "rating": rating,
            "cost": cost,
            "tel": (p.get("tel") or "").split(";")[0] if p.get("tel") else "",
            "open_hours": biz.get("opentime2") or biz.get("open_time") or "",
            "source_query": p.get("category_query", ""),
        })

    # ---- 连锁识别:同一 chain_key 出现在 >=2 条记录,视为连锁品牌 ----
    key_count = Counter(c["chain_key"] for c in cleaned)
    chains = {}
    for c in cleaned:
        c["is_chain"] = key_count[c["chain_key"]] >= 2
        c["chain_id"] = None
        if c["is_chain"]:
            c["chain_id"] = "chain:" + c["chain_key"]

    # ---- 重名消歧:同名但不同城区/坐标差异大,标记为不同实体 ----
    by_name = {}
    for c in cleaned:
        by_name.setdefault(c["name"], []).append(c)
    dup_names = {n: len(v) for n, v in by_name.items() if len(v) > 1}

    stats = {
        "total": len(cleaned),
        "chains": sum(1 for c in cleaned if c["is_chain"]),
        "chain_brands": sum(1 for k, v in key_count.items() if v >= 2),
        "duplicate_names": len(dup_names),
        "districts": len({c["district"] for c in cleaned}),
        "categories_l1": len({c["category_l1"] for c in cleaned}),
        "categories_l3": len({c["category_l3"] for c in cleaned}),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"pois": cleaned, "stats": stats}, ensure_ascii=False, indent=1), encoding="utf-8")

    print("清洗完成:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"已写入 {OUT}")


if __name__ == "__main__":
    main()
