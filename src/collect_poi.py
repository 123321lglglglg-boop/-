"""高德 Web 服务 API POI 采集:按区县 × 品类拉取乌兰察布本地 POI。

用法:
    set AMAP_KEY=你的key   (Windows cmd; bash 用 export AMAP_KEY=...)
    python src/collect_poi.py
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://restapi.amap.com/v3/place/text"
OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "poi.json"

DISTRICTS = {
    "集宁区": "150902",
    "卓资县": "150921",
    "化德县": "150922",
    "商都县": "150923",
    "兴和县": "150924",
    "凉城县": "150925",
    "察右前旗": "150926",
    "察右中旗": "150927",
    "察右后旗": "150928",
    "四子王旗": "150929",
    "丰镇市": "150981",
}

CATEGORIES = {
    "中餐": "050100",
    "外国餐厅": "050200",
    "快餐": "050300",
    "火锅": "050116",
    "烧烤": "050117",
    "咖啡厅": "050500",
    "甜品店": "050900",
    "冷饮店": "050600",
    "休闲餐饮": "050800",
    "酒店": "100100",
    "景点": "110200",
    "购物中心": "060100",
    # 奶茶/饮品(冷饮店 050600 已覆盖部分,再补休闲餐饮细类)
    "茶艺馆": "080307",
    # 休闲娱乐
    "休闲娱乐": "080000",
    "影剧院": "080601",
    "KTV": "080302",
    "酒吧": "080304",
    "网吧": "080305",
    "洗浴": "080104",
    "足疗按摩": "080106",
    "健身": "080102",
}

PAGE_SIZE = 25
MAX_PAGE = 40

# 常见连锁品牌:按关键词搜索(编码搜索对部分品牌覆盖不全)
BRAND_KEYWORDS = [
    "蜜雪冰城", "茶百道", "沪上阿姨", "古茗", "喜茶", "奈雪的茶", "益禾堂",
    "甜啦啦", "书亦烧仙草", "瑞幸咖啡", "星巴克", "库迪咖啡",
    "肯德基", "麦当劳", "华莱士", "德克士",
]


def fetch_page(session, key, adcode, types, page, keywords=None):
    params = {
        "key": key,
        "city": adcode,
        "citylimit": "true",
        "offset": PAGE_SIZE,
        "page": page,
        "extensions": "all",
        "output": "JSON",
    }
    if keywords:
        params["keywords"] = keywords
    else:
        params["types"] = types
    for attempt in range(3):
        try:
            r = session.get(API, params=params, timeout=10)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            print(f"    请求异常({e}),{attempt + 1}/3 重试")
            time.sleep(2 * (attempt + 1))
            continue
        if data.get("status") == "1":
            return data
        info = data.get("info", "")
        if info == "DAILY_QUERY_OVER_LIMIT":
            print("    日调用量已用尽,停止本次采集")
            sys.exit(1)
        print(f"    API 错误 {info},{attempt + 1}/3 重试")
        time.sleep(2 * (attempt + 1))
    return None


def main():
    key = os.environ.get("AMAP_KEY", "").strip()
    if not key:
        key_file = Path(__file__).resolve().parent.parent / "amap_key.txt"
        if key_file.exists():
            key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        print("请先设置环境变量 AMAP_KEY,或把 key 写入项目根目录的 amap_key.txt")
        sys.exit(1)

    pois = {}
    if OUT.exists():
        pois = {p["id"]: p for p in json.loads(OUT.read_text(encoding="utf-8"))}
        print(f"载入已有数据 {len(pois)} 条(断点续传)")

    session = requests.Session()
    total_calls = 0
    for dname, adcode in DISTRICTS.items():
        for cname, types in CATEGORIES.items():
            fetched = 0
            for page in range(1, MAX_PAGE + 1):
                data = fetch_page(session, key, adcode, types, page)
                total_calls += 1
                if not data:
                    break
                items = data.get("pois") or []
                for p in items:
                    pid = p.get("id")
                    if pid and pid not in pois:
                        p["district"] = dname
                        p["category_query"] = cname
                        pois[pid] = p
                fetched += len(items)
                if len(items) < PAGE_SIZE:
                    break
                time.sleep(0.35)
            print(f"{dname} × {cname}: 新增 {fetched} 条(累计 {len(pois)})")
            OUT.write_text(json.dumps(list(pois.values()), ensure_ascii=False, indent=1), encoding="utf-8")
            time.sleep(0.35)

    # 连锁品牌关键词补充搜索(编码搜索对奶茶等品牌覆盖不全)
    for dname, adcode in DISTRICTS.items():
        for brand in BRAND_KEYWORDS:
            fetched = 0
            for page in range(1, MAX_PAGE + 1):
                data = fetch_page(session, key, adcode, None, page, keywords=brand)
                total_calls += 1
                if not data:
                    break
                items = data.get("pois") or []
                for p in items:
                    pid = p.get("id")
                    if pid and pid not in pois:
                        p["district"] = dname
                        p["category_query"] = f"品牌:{brand}"
                        pois[pid] = p
                fetched += len(items)
                if len(items) < PAGE_SIZE:
                    break
                time.sleep(0.35)
            if fetched:
                print(f"{dname} × 品牌[{brand}]: 新增 {fetched} 条(累计 {len(pois)})")
                OUT.write_text(json.dumps(list(pois.values()), ensure_ascii=False, indent=1), encoding="utf-8")
            time.sleep(0.2)

    print(f"完成:共 {len(pois)} 条 POI,API 调用 {total_calls} 次,已写入 {OUT}")


if __name__ == "__main__":
    main()
