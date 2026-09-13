"""对比 CONTAINS 与 FULLTEXT(cjk) 在店名检索上的召回与代价。

结论用途:验证 cypher/indexes.cypher 里的 poi_name_fulltext 索引
能不能真正替代 TEXT2CYPHER_PROMPT 现在强制 LLM 使用的 CONTAINS 写法。

用法:
    python scripts/bench_name_search.py
"""
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from src.db import get_driver  # noqa: E402

KEYWORDS = ["蒙餐", "火锅", "乌兰图雅", "蜜雪冰城", "莜面", "烧麦", "羊杂", "烧烤"]

CONTAINS_Q = (
    "MATCH (p:POI) WHERE p.name CONTAINS $kw "
    "RETURN p.name AS 名称"
)
FULLTEXT_Q = (
    "CALL db.index.fulltext.queryNodes('poi_name_fulltext', $kw) "
    "YIELD node, score RETURN node.name AS 名称, score "
    "ORDER BY score DESC LIMIT 200"
)


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t) * 1000


def main():
    d = get_driver()
    print(f"{'关键词':<10}{'CONTAINS':>10}{'FULLTEXT':>10}{'召回率':>9}"
          f"{'CONTAINS耗时':>14}{'FULLTEXT耗时':>14}")
    print("-" * 74)

    total_c = total_f = total_hit = 0
    with d.session() as s:
        for kw in KEYWORDS:
            cont, tc = timed(lambda: {r["名称"] for r in s.run(CONTAINS_Q, kw=kw)})
            full, tf = timed(lambda: {r["名称"] for r in s.run(FULLTEXT_Q, kw=kw)})
            # 召回率:CONTAINS 找到的,有多少也被 FULLTEXT 找到
            hit = len(cont & full)
            rate = hit / len(cont) * 100 if cont else 0.0
            total_c += len(cont)
            total_f += len(full)
            total_hit += hit
            print(f"{kw:<10}{len(cont):>10}{len(full):>10}{rate:>8.0f}%"
                  f"{tc:>13.0f}ms{tf:>13.0f}ms")

    print("-" * 74)
    overall = total_hit / total_c * 100 if total_c else 0.0
    print(f"总体召回率(FULLTEXT 覆盖 CONTAINS 的比例): {overall:.1f}%"
          f"  ({total_hit}/{total_c})")
    print()
    print("注:FULLTEXT 的 LIMIT 200 会截断超热门关键词,上面的召回率是下界。")


if __name__ == "__main__":
    main()
