"""构造可检索的语义文本(方案 2.2)。

关键:分字段拼接而非混成一坨——用户问"适合带小孩的地方"时,
向量要能匹配到"特色:适合家庭聚餐"这类结构化语义标签。

输出:data/processed/poi_searchable.jsonl
每行:{"poi_id", "name", "text", "meta": {...}}
"""
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw" / "poi.json"
CLEAN = BASE / "data" / "processed" / "pois_clean.json"
OUT = BASE / "data" / "processed" / "poi_searchable.jsonl"


def build_text(poi: dict) -> str:
    """把商户信息拼成可被语义检索的文本(方案 2.2 的格式)。"""
    parts = []

    name = (poi.get("name") or "").strip()
    if name:
        parts.append(f"店名:{name}")

    # 品类:取高德 type 的末级 + keytag
    typ = poi.get("type") or ""
    levels = [t for t in typ.split(";") if t]
    if levels:
        parts.append(f"品类:{levels[-1]}")
    keytag = (poi.get("keytag") or "").strip()
    if keytag and keytag not in typ:
        parts.append(f"核心特色:{keytag}")

    # 特色标签(有则拼,是语义检索的关键)
    tag = (poi.get("tag") or "").strip()
    if tag:
        parts.append(f"特色标签:{tag}")

    # 位置
    loc = []
    if poi.get("district"):
        loc.append(str(poi["district"]))
    if poi.get("business_area"):
        loc.append(str(poi["business_area"]))
    if loc:
        parts.append("位置:" + " · ".join(loc))
    addr = (poi.get("address") or "").strip()
    if addr and addr not in loc:
        parts.append(f"地址:{addr}")

    # 经营信息(有助于"便宜/高档/评分高"这类语义)
    biz = poi.get("biz_ext") or {}
    cost = biz.get("cost")
    if cost and str(cost) not in ("[]", ""):
        try:
            c = float(cost)
            if c > 0:
                level = "经济实惠" if c <= 30 else ("大众消费" if c <= 60 else ("中档消费" if c <= 120 else "高端消费"))
                parts.append(f"人均:{c:.0f}元({level})")
        except (TypeError, ValueError):
            pass
    rating = biz.get("rating")
    if rating and str(rating) not in ("[]", ""):
        try:
            r = float(rating)
            level = "口碑很好" if r >= 4.5 else ("评价不错" if r >= 4.0 else "")
            if level:
                parts.append(f"评分:{r}({level})")
        except (TypeError, ValueError):
            pass

    hours = biz.get("opentime2") or biz.get("open_time")
    if hours:
        parts.append(f"营业时间:{hours}")

    if poi.get("is_chain") or (poi.get("chain_key") and poi.get("is_chain")):
        pass  # 连锁信息不进入文本(结构化查询更合适)

    return "\n".join(parts)


def main():
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    # 用清洗后的数据补充连锁/商圈字段
    clean_map = {}
    if CLEAN.exists():
        cd = json.loads(CLEAN.read_text(encoding="utf-8"))
        clean_map = {p["poi_id"]: p for p in cd.get("pois", [])}

    rows = []
    for p in raw:
        pid = p.get("id")
        if not pid:
            continue
        c = clean_map.get(pid, {})
        merged = {
            "name": p.get("name"),
            "type": p.get("type"),
            "keytag": p.get("keytag"),
            "tag": p.get("tag"),
            "district": p.get("district") or c.get("district"),
            "business_area": p.get("business_area"),
            "address": p.get("address") or c.get("address"),
            "biz_ext": {
                "cost": c.get("cost") if c.get("cost") else (p.get("biz_ext") or {}).get("cost"),
                "rating": c.get("rating") if c.get("rating") else (p.get("biz_ext") or {}).get("rating"),
                "opentime2": c.get("open_hours") or (p.get("biz_ext") or {}).get("opentime2"),
            },
        }
        text = build_text(merged)
        if not text.strip():
            continue
        rows.append({
            "poi_id": pid,
            "name": merged["name"],
            "text": text,
            "meta": {
                "district": merged["district"],
                "category": (merged["type"] or "").split(";")[-1],
                "rating": merged["biz_ext"]["rating"],
                "cost": merged["biz_ext"]["cost"],
                "business_area": merged["business_area"],
            },
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total_chars = sum(len(r["text"]) for r in rows)
    print(f"生成完成:{OUT}")
    print(f"  条目:{len(rows)}")
    print(f"  总字数:{total_chars:,}(平均 {total_chars // max(len(rows),1)} 字/条)")
    print()
    print("=== 样本 ===")
    for r in rows[:2]:
        print(r["text"])
        print("-" * 50)


if __name__ == "__main__":
    main()
