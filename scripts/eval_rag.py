"""三方案检索效果评测(文档《KG项目优化文档》第二部分 1.2)。

跑 data/eval_set.json 里的每道题,分别用三套检索方案各跑一遍,统计:
  - 命中率(标准答案是否出现在 Top-5)
  - 分类型命中率(A 结构化 / B 语义化 / C 混合)—— 用来验证"双引擎互补"的说法
  - 延迟 P50 / P95

三套方案直接调用线上真实代码路径,不另写一份实现:
  纯图谱   → src/llm_qa.py:text2cypher
  纯向量   → src/vector_search.py:semantic_search
  GraphRAG → src/hybrid_retrieval.py:retrieve  (和生产环境完全同一条路径)

用法:
    python scripts/eval_rag.py                     # 全量
    python scripts/eval_rag.py --limit 20          # 先跑 20 题冒烟
    python scripts/eval_rag.py --only A            # 只跑 A 类
    python scripts/eval_rag.py --config 纯图谱      # 只跑某一个方案
    python scripts/eval_rag.py --resume            # 跳过已有结果的题(断点续跑)

结果写到 data/eval_report.json,每跑完一题就落盘一次,中断不丢。
"""
import argparse
import json
import statistics
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from src.hybrid_retrieval import retrieve        # noqa: E402
from src.llm_qa import text2cypher               # noqa: E402
from src.vector_search import semantic_search    # noqa: E402

EVAL_SET = BASE / "data" / "eval_set.json"
REPORT = BASE / "data" / "eval_report.json"
TOP_K_HIT = 5          # 标准答案落在前 5 条即算命中

CONFIG_NAMES = ["纯图谱", "纯向量", "GraphRAG"]


def _names_from_kg_records(records: list) -> list:
    out = []
    for r in records or []:
        nm = r.get("名称") or r.get("name")
        if nm:
            out.append(str(nm))
    return out


def _extract_count(records: list):
    """计数题("乌兰察布有多少家中餐厅")的答案是一个数字,不是店名列表。

    从结果里找出唯一的数值列。要求整个结果集里只有一个不同的数值,
    避免把评分/人均这类列误当成数量。
    """
    if not records or len(records) > 2:
        return None
    vals = []
    for r in records:
        for v in (r or {}).values():
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                vals.append(v)
            elif isinstance(v, float) and float(v).is_integer():
                vals.append(int(v))
    distinct = set(vals)
    return vals[0] if len(distinct) == 1 and vals else None


def kg_search(q: str) -> dict:
    _, records, _err = text2cypher(q)
    return {"names": _names_from_kg_records(records),
            "count": _extract_count(records)}


def vec_search(q: str) -> dict:
    return {"names": [v.get("name", "") for v in (semantic_search(q, top_k=10) or [])],
            "count": None}


def graphrag_search(q: str) -> dict:
    def _kg(query, history):
        return text2cypher(query, history=history)
    res = retrieve(q, _kg)
    recs = res.get("records") or []
    return {"names": _names_from_kg_records(recs),
            "count": _extract_count(recs)}


RUNNERS = {
    "纯图谱": kg_search,
    "纯向量": vec_search,
    "GraphRAG": graphrag_search,
}


def hit(expected: list, got: list) -> bool:
    """严格命中:标准答案(按评分的前 10 家)出现在 Top-5 里。

    注意这个指标对向量检索是不公平的——它实际在考"返回顺序是否和评分序一致",
    而向量是按语义相似度排序的。它适合衡量图谱那一路(查询本身就带 ORDER BY),
    衡量语义检索要看下面的 P@5 / R@5。
    """
    return bool(set(expected) & set(got[:TOP_K_HIT]))


def precision_at_5(gt_set: list, got: list) -> float:
    """P@5:返回的前 5 条里,有多少条真的满足这道题的条件。

    这是衡量"有没有理解意图"的指标:问"想涮点肉吃",返回 5 家火锅店 → 1.0,
    返回 5 家不相关 → 0.0,与排序无关。
    """
    top = got[:TOP_K_HIT]
    if not top:
        return 0.0
    s = set(gt_set)
    return sum(1 for g in top if g in s) / len(top)


def recall_at_5(gt_set: list, got: list) -> float:
    """R@5:该条件对应的全部商家,Top-5 覆盖了多少。"""
    if not gt_set:
        return 0.0
    top = set(got[:TOP_K_HIT])
    return len(top & set(gt_set)) / min(TOP_K_HIT, len(gt_set))


def pct(n, d):
    return f"{n / d * 100:.1f}%" if d else "—"


def summarize(rows: list, config: str) -> dict:
    """按方案汇总:严格命中率 + 谓词 P@5/R@5 + 分类型 + 延迟分位。"""
    sub = [r for r in rows if r["config"] == config]
    if not sub:
        return {}
    lat = sorted(r["ms"] for r in sub)
    out = {
        "题目数": len(sub),
        "命中率": pct(sum(1 for r in sub if r["hit"]), len(sub)),
        "P@5": f"{sum(r.get('p5', 0) for r in sub) / len(sub) * 100:.1f}%",
        "R@5": f"{sum(r.get('r5', 0) for r in sub) / len(sub) * 100:.1f}%",
        "P50(ms)": round(statistics.median(lat)),
        "P95(ms)": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))]),
        "平均(ms)": round(sum(lat) / len(lat)),
        "报错数": sum(1 for r in sub if r.get("error")),
    }
    for t in ("A", "B", "C"):
        ts = [r for r in sub if r["type"] == t]
        if ts:
            out[f"{t}类命中率"] = pct(sum(1 for r in ts if r["hit"]), len(ts))
            out[f"{t}类P@5"] = f"{sum(r.get('p5', 0) for r in ts) / len(ts) * 100:.1f}%"
            out[f"{t}类题数"] = len(ts)
    return out


def rescore(rows: list, gt_sets: dict, count_ids: set = None) -> list:
    """用已存的结果重算指标(不重跑检索)。

    计数题跳过:它们的判定依据是返回的数字,老结果里没存,重算会算错。
    """
    count_ids = count_ids or set()
    for r in rows:
        if r["id"] in count_ids:
            continue
        gt = gt_sets.get(r["id"]) or []
        got = r.get("got_top5") or []
        r["p5"] = round(precision_at_5(gt, got), 4)
        r["r5"] = round(recall_at_5(gt, got), 4)
    return rows


def write_report(rows: list, data: dict):
    REPORT.write_text(json.dumps({
        "meta": {
            "eval_set": str(EVAL_SET),
            "graph": data["meta"]["graph"],
            "top_k_hit": TOP_K_HIT,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "metric_note": (
                "严格命中 = 标注的标准答案(满足条件且按评分排序的前 10 家)出现在 Top-5。"
                "它实际在比对排序依据,对按语义相似度排序的向量检索不公平,仅供参考。"
                "P@5 = 返回的前 5 条里满足该题条件的比例,衡量是否理解意图,与排序无关。"
                "R@5 = 该条件对应的全部商家中 Top-5 覆盖到的比例。"
                "两个指标都只衡量「返回的商家对不对」,不评判回答文字质量。"
            ),
        },
        "results": rows,
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def print_summary(rows: list, configs: list):
    print()
    print("=" * 106)
    print(f"{'方案':<10}{'题目数':>7}{'严格命中':>10}{'P@5':>9}{'R@5':>9}"
          f"{'A类P@5':>9}{'B类P@5':>9}{'C类P@5':>9}{'P50':>8}{'P95':>8}{'报错':>6}")
    print("-" * 106)
    for cfg in configs:
        s = summarize(rows, cfg)
        if not s:
            continue
        print(f"{cfg:<10}{s['题目数']:>7}{s['命中率']:>10}{s['P@5']:>9}{s['R@5']:>9}"
              f"{s.get('A类P@5', '—'):>9}{s.get('B类P@5', '—'):>9}{s.get('C类P@5', '—'):>9}"
              f"{s['P50(ms)']:>8}{s['P95(ms)']:>8}{s['报错数']:>6}")
    print("=" * 106)
    print(f"明细已写入 {REPORT}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题")
    ap.add_argument("--only", default="", help="只跑某类题:A / B / C")
    ap.add_argument("--config", default="", help="只跑某个方案")
    ap.add_argument("--resume", action="store_true", help="跳过已有结果的 (题, 方案) 组合")
    ap.add_argument("--rescore", action="store_true",
                    help="不重跑检索,只用已存结果 + 评测集里的 ground_truth_set 重算指标")
    args = ap.parse_args()

    data = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    questions = data["questions"]
    gt_sets = {q["id"]: (q.get("ground_truth_set") or q.get("expected_entities") or [])
               for q in questions}
    if args.only:
        questions = [q for q in questions if q["type"] == args.only.upper()]
    if args.limit:
        questions = questions[:args.limit]

    configs = [args.config] if args.config else CONFIG_NAMES
    print(f"评测集 {EVAL_SET.name}: {len(questions)} 题 × {len(configs)} 方案")
    print(f"命中判定:标准答案出现在 Top-{TOP_K_HIT}")
    print()

    rows = []
    if args.resume and REPORT.exists():
        try:
            rows = json.loads(REPORT.read_text(encoding="utf-8")).get("results", [])
        except Exception:
            rows = []
    if args.rescore:
        if not rows and REPORT.exists():
            rows = json.loads(REPORT.read_text(encoding="utf-8")).get("results", [])
        count_ids = {q["id"] for q in data["questions"]
                     if q.get("answer_kind") == "count"}
        rows = rescore(rows, gt_sets, count_ids)
        print(f"已用评测集里的 ground_truth_set 重算 {len(rows)} 条结果(未重跑检索)")
        write_report(rows, data)
        print_summary(rows, configs)
        return
    done = {(r["id"], r["config"]) for r in rows}

    for qi, q in enumerate(questions, 1):
        line = []
        for cfg in configs:
            if args.resume and (q["id"], cfg) in done:
                line.append(f"{cfg}:(cached)")
                continue
            t0 = time.perf_counter()
            err = None
            res = {"names": [], "count": None}
            try:
                res = RUNNERS[cfg](q["question"])
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:160]}"
            ms = (time.perf_counter() - t0) * 1000
            got = res.get("names") or []
            gt = gt_sets.get(q["id"]) or []
            if q.get("answer_kind") == "count":
                # 计数题:看返回的数字对不对,不看店名
                truth = len(gt) or len(q["expected_entities"])
                gc = res.get("count")
                ok = gc is not None and abs(gc - truth) <= max(2, round(truth * 0.02))
                h = bool(ok)
                p5 = r5 = (1.0 if ok else 0.0)
            else:
                h = hit(q["expected_entities"], got)
                p5 = precision_at_5(gt, got)
                r5 = recall_at_5(gt, got)
            rows.append({
                "id": q["id"], "type": q["type"], "config": cfg,
                "question": q["question"], "ms": round(ms),
                "answer_kind": q.get("answer_kind", "names"),
                "hit": h, "p5": round(p5, 4), "r5": round(r5, 4),
                "got_count": res.get("count"),
                "got_top5": got[:TOP_K_HIT],
                "expected_top5": q["expected_entities"][:TOP_K_HIT],
                "error": err,
            })
            line.append(f"{cfg}:{'命中' if h else '未中'}/P{ p5*100:.0f}({ms/1000:.1f}s)")

        print(f"[{qi}/{len(questions)}] {q['id']} {q['question'][:32]:<34} " + "  ".join(line))
        write_report(rows, data)

    print_summary(rows, configs)


if __name__ == "__main__":
    main()
