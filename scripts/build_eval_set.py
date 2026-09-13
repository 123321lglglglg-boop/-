"""从真实图谱反推生成评测集 data/eval_set.json。

设计原则(重要,决定了结果可不可信):
  1. 题目和标准答案全部来自真实图数据,不手写、不编造。
  2. 每道题的 ground_truth 都附一条等价的 Cypher(结构化题)或一个显式谓词
     (语义题),任何人可以重跑验证。评测脚本不用这些 GT,GT 只用于判定命中。
  3. 固定随机种子,保证同一次构建结果稳定可复现。

三类题(对齐文档《KG项目优化文档》第二部分 1.1):
  A 结构化 40 题 —— 问题里有明确的数值/枚举条件,图谱的强项。
      标准答案 = 等价 Cypher 的真实返回(按评分取前 10 家真实店名)。
  B 语义化 30 题 —— 用口语化说法提问,刻意不出现图谱里的品类词,
      考察的是"能不能理解意图"而不是"能不能匹配关键词"。
      标准答案 = 满足文档化谓词的 POI 集合(按评分取前 10)。
      ⚠️ 局限:谓词是定义在真实字段(细类/店名)上的,属于"词法层面"的
      标准答案,是真实语义质量的下界,不是人工精标。README 里有说明。
  C 混合   30 题 —— 区县/人均这类硬条件 + B 类那种口语化意图,两者都要满足。

用法:
    python scripts/build_eval_set.py            # 写 data/eval_set.json
    python scripts/build_eval_set.py --stats    # 只打印统计
"""
import json
import random
import sys
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from src.db import run_cypher  # noqa: E402

OUT = BASE / "data" / "eval_set.json"
SEED = 20260913
TOP_N = 10          # expected_entities 保留的店数(按评分取前 N)
SET_CAP = 3000      # ground_truth_set 的上限。必须大于最大的答案集合
                    # (中餐厅 1623 家),否则集合被截断会把合法结果误判成
                    # "不满足条件",P@5 被系统性低估。

# ── A 类参数字典:全部从真实图谱取 ──
PRICE_LEVELS = [30, 50, 80, 100]

# ── B/C 类意图 → 显式谓词 ──
# 每条 = (三种口语化问法, 匹配谓词说明, 用于精确过滤的 Cypher 条件片段)
# 关键:问法里刻意不出现 category 的原词,否则就退化成关键词匹配了;
# 同一个意图的三种问法用词各不相同,用来考察对表述变化的鲁棒性。
INTENTS = [
    (
        ["想涮点肉吃", "想吃个热乎的锅子", "哪家锅子好吃"],
        "火锅店",
        "EXISTS { MATCH (p)-[:属于细类]->(c:CategoryL3) WHERE c.name = '火锅店' }",
    ),
    (
        ["晚上想撸串喝点啤酒", "哪儿能吃烤串", "找地方整点烧烤"],
        "烧烤/酒吧",
        "EXISTS { MATCH (p)-[:属于细类]->(c:CategoryL3) WHERE c.name IN ['酒吧'] OR p.name CONTAINS '烧烤' }",
    ),
    (
        ["想吃点有内蒙特色的", "尝尝本地口味", "有什么地道的地方菜"],
        "蒙餐/莜面/烧麦等地方风味",
        "p.name CONTAINS '蒙餐' OR EXISTS { MATCH (p)-[:属于细类]->(c:CategoryL3) WHERE c.name IN ['特色/地方风味餐厅','清真菜馆'] }",
    ),
    (
        ["带孩子出门吃饭去哪好", "适合全家人一起吃的", "小孩能吃的地方"],
        "快餐厅/冷饮店/糕饼店",
        "EXISTS { MATCH (p)-[:属于细类]->(c:CategoryL3) WHERE c.name IN ['快餐厅','冷饮店','糕饼店'] }",
    ),
    (
        ["想找个安静地方坐下来喝点咖啡", "哪儿能喝到手冲", "找个能坐一下午的咖啡馆"],
        "咖啡厅",
        "EXISTS { MATCH (p)-[:属于细类]->(c:CategoryL3) WHERE c.name = '咖啡厅' }",
    ),
    (
        ["想跟朋友吼两嗓子", "哪儿能唱歌", "晚上想找个地方唱会儿"],
        "KTV",
        "EXISTS { MATCH (p)-[:属于细类]->(c:CategoryL3) WHERE c.name = 'KTV' }",
    ),
    (
        ["出差要找个地方过夜", "晚上住哪方便", "有什么能落脚的地方"],
        "宾馆酒店",
        "EXISTS { MATCH (p)-[:属于细类]->(c:CategoryL3) WHERE c.name = '宾馆酒店' }",
    ),
    (
        ["想找地方坐着聊聊天喝点茶", "哪儿能安静喝茶", "找个能泡一下午茶馆"],
        "茶艺馆/休闲场所",
        "EXISTS { MATCH (p)-[:属于细类]->(c:CategoryL3) WHERE c.name IN ['茶艺馆','休闲场所'] }",
    ),
    (
        ["想吃点乡下的土菜", "有没有农家味道的馆子", "想吃柴火灶做的那种"],
        "农家菜/采摘园",
        "p.name CONTAINS '农家' OR EXISTS { MATCH (p)-[:属于细类]->(c:CategoryL3) WHERE c.name = '采摘园' }",
    ),
    (
        ["想找地方喝杯冰的", "天热想喝点凉的", "有什么解暑的饮品店"],
        "冷饮店",
        "EXISTS { MATCH (p)-[:属于细类]->(c:CategoryL3) WHERE c.name = '冷饮店' }",
    ),
]

PRICE_WORD = {30: "30", 50: "50", 80: "80", 100: "100"}


def _names(rows, n=TOP_N):
    """从查询结果取前 n 个店名(去重)。"""
    seen, out = set(), []
    for r in rows:
        nm = r.get("名称")
        if nm and nm not in seen:
            seen.add(nm)
            out.append(nm)
        if len(out) >= n:
            break
    return out


def static_cypher(where_sql: str, extra_order: str = "p.rating DESC", limit: int = TOP_N) -> str:
    return (
        "MATCH (p:POI) WHERE " + where_sql + " AND p.name IS NOT NULL "
        "RETURN p.name AS 名称 ORDER BY " + extra_order + " LIMIT " + str(limit)
    )


# ══════════════════════════════════════════════════════════════
# A 类:结构化
# ══════════════════════════════════════════════════════════════

def build_A(rng) -> list:
    out = []

    districts = [r["n"] for r in run_cypher(
        "MATCH (p:POI)-[:位于]->(d:District) RETURN d.name AS n, count(p) AS c "
        "ORDER BY c DESC LIMIT 6")]
    cats = [r["c"] for r in run_cypher(
        "MATCH (p:POI)-[:属于细类]->(c:CategoryL3) RETURN c.name AS c, count(p) AS n "
        "ORDER BY n DESC LIMIT 12")]
    chains = [r["c"] for r in run_cypher(
        "MATCH (p:POI)-[:连锁品牌]->(c:Chain) RETURN c.name AS c, count(p) AS n "
        "ORDER BY n DESC LIMIT 8")]
    dishes = [r["d"] for r in run_cypher(
        "MATCH (p:POI)-[:招牌菜]->(d:Dish) RETURN d.name AS d, count(p) AS n "
        "ORDER BY n DESC LIMIT 15")]
    areas = [r["a"] for r in run_cypher(
        "MATCH (p:POI)-[:位于商圈]->(a:BusinessArea) RETURN a.name AS a, count(p) AS n "
        "ORDER BY n DESC LIMIT 8")]

    n = 0

    # A1 区县 + 人均 + 品类(10 题)
    picks = [(d, c, pr) for d in districts[:4] for c in cats[:5] for pr in PRICE_LEVELS]
    rng.shuffle(picks)
    for d, c, pr in picks[:10]:
        where = (f"p.cost IS NOT NULL AND p.cost > 0 AND p.cost <= {pr} "
                 f"AND EXISTS {{ MATCH (p)-[:位于]->(dd:District) WHERE dd.name = '{d}' }} "
                 f"AND EXISTS {{ MATCH (p)-[:属于细类]->(cc:CategoryL3) WHERE cc.name = '{c}' }}")
        rows = run_cypher(static_cypher(where))
        gts = _names(rows)
        if len(gts) < 3:
            continue
        n += 1
        out.append({
            "id": f"A{n:03d}", "type": "A",
            "question": f"{d}人均{PRICE_WORD[pr]}元以下的{c}有哪些",
            "expected_entities": gts,
            "answerable": True,
            "notes": "区县+人均阈值+品类的三条件过滤,图谱的典型强项",
            "ground_truth_cypher": static_cypher(where),
        })

    # A2 评分排序(8 题)
    picks = [(d, c) for d in districts for c in rng.sample(cats, 4)]
    rng.shuffle(picks)
    for d, c in picks[:8]:
        where = (f"p.rating IS NOT NULL "
                 f"AND EXISTS {{ MATCH (p)-[:位于]->(dd:District) WHERE dd.name = '{d}' }} "
                 f"AND EXISTS {{ MATCH (p)-[:属于细类]->(cc:CategoryL3) WHERE cc.name = '{c}' }}")
        rows = run_cypher(static_cypher(where))
        gts = _names(rows)
        if len(gts) < 3:
            continue
        n += 1
        out.append({
            "id": f"A{n:03d}", "type": "A",
            "question": f"{d}评分最高的{c}是哪几家",
            "expected_entities": gts,
            "answerable": True,
            "notes": "按评分排序取头部,考察 ORDER BY + LIMIT 是否正确下推",
            "ground_truth_cypher": static_cypher(where),
        })

    # A3 计数题(6 题)
    picks = [("乌兰察布", c) for c in cats[:6]]
    for d, c in picks:
        if d == "乌兰察布":
            where = f"EXISTS {{ MATCH (p)-[:属于细类]->(cc:CategoryL3) WHERE cc.name = '{c}' }}"
            q = f"乌兰察布有多少家{c}"
        else:
            where = (f"EXISTS {{ MATCH (p)-[:位于]->(dd:District) WHERE dd.name = '{d}' }} "
                     f"AND EXISTS {{ MATCH (p)-[:属于细类]->(cc:CategoryL3) WHERE cc.name = '{c}' }}")
            q = f"{d}有多少家{c}"
        rows = run_cypher(static_cypher(where))
        gts = _names(rows)
        if len(gts) < 3:
            continue
        n += 1
        out.append({
            "id": f"A{n:03d}", "type": "A",
            "question": q,
            "expected_entities": gts,
            "answerable": True,
            # 计数题返回的是 {数量: N} 而不是店名列,不能按"标准答案是否在 Top-5"判定,
            # 要按"数字对不对"判定——否则会被系统性误判为未命中
            "answer_kind": "count",
            "notes": "计数题;按返回的数量是否等于真实商家数判定,不比对店名",
            "ground_truth_cypher": static_cypher(where),
        })

    # A4 连锁品牌(6 题)
    picks = [(ch, None) for ch in chains[:6]]
    for ch, _ in picks:
        where = f"EXISTS {{ MATCH (p)-[:连锁品牌]->(cc:Chain) WHERE cc.name = '{ch}' }}"
        rows = run_cypher(static_cypher(where))
        gts = _names(rows)
        if len(gts) < 3:
            continue
        n += 1
        out.append({
            "id": f"A{n:03d}", "type": "A",
            "question": f"{ch}在乌兰察布有几家店",
            "expected_entities": gts,
            "answerable": True,
            "notes": "品牌门店枚举,考察 Chain 关系是否正确使用",
            "ground_truth_cypher": static_cypher(where),
        })

    # A5 菜品(6 题)
    for dw in dishes[:8]:
        if n >= 34:
            break
        where = f"EXISTS {{ MATCH (p)-[:招牌菜]->(dd:Dish) WHERE dd.name = '{dw}' }}"
        rows = run_cypher(static_cypher(where))
        gts = _names(rows)
        if len(gts) < 3:
            continue
        n += 1
        out.append({
            "id": f"A{n:03d}", "type": "A",
            "question": f"哪里有卖{dw}的",
            "expected_entities": gts,
            "answerable": True,
            "notes": "菜品找店,考察 Dish 实体与 招牌菜 关系",
            "ground_truth_cypher": static_cypher(where),
        })

    # A6 商圈(补足到 40)
    for a in areas:
        if n >= 40:
            break
        where = f"EXISTS {{ MATCH (p)-[:位于商圈]->(aa:BusinessArea) WHERE aa.name = '{a}' }}"
        rows = run_cypher(static_cypher(where))
        gts = _names(rows)
        if len(gts) < 3:
            continue
        n += 1
        out.append({
            "id": f"A{n:03d}", "type": "A",
            "question": f"{a}商圈有哪些评分高的商家",
            "expected_entities": gts,
            "answerable": True,
            "notes": "商圈维度,考察 BusinessArea 关系",
            "ground_truth_cypher": static_cypher(where),
        })

    return out


# ══════════════════════════════════════════════════════════════
# B 类:语义化(口语化问法,不含品类原词)
# ══════════════════════════════════════════════════════════════

def build_B(rng) -> list:
    out, n = [], 0
    for phrasings, predicate_desc, cond in INTENTS:
        where = f"p.rating IS NOT NULL AND ({cond})"
        rows = run_cypher(static_cypher(where))
        gts = _names(rows)
        if len(gts) < 3:
            continue
        for v in phrasings:
            if n >= 30:
                break
            n += 1
            out.append({
                "id": f"B{n:03d}", "type": "B",
                "question": v,
                "expected_entities": gts,
                "answerable": True,
                "notes": f"口语化意图,未出现品类原词;标准答案定义为「{predicate_desc}」",
                "ground_truth_cypher": static_cypher(where),
                "ground_truth_is_proxy": True,
            })
    return out


# ══════════════════════════════════════════════════════════════
# C 类:混合(硬条件 + 口语化意图)
# ══════════════════════════════════════════════════════════════

def build_C(rng) -> list:
    out, n = [], 0
    districts = [r["n"] for r in run_cypher(
        "MATCH (p:POI)-[:位于]->(d:District) RETURN d.name AS n, count(p) AS c "
        "ORDER BY c DESC LIMIT 6")]
    for phrasings, predicate_desc, cond in INTENTS:
        for d in districts:
            if n >= 30:
                break
            # 人均阈值从小到大试,取第一个能凑够 3 家结果的档位,
            # 避免"该区县这个价位根本没有这类店"导致样本凑不齐
            for pr in PRICE_LEVELS:
                where = (f"p.cost IS NOT NULL AND p.cost > 0 AND p.cost <= {pr} "
                         f"AND EXISTS {{ MATCH (p)-[:位于]->(dd:District) WHERE dd.name = '{d}' }} "
                         f"AND ({cond})")
                rows = run_cypher(static_cypher(where))
                gts = _names(rows)
                if len(gts) < 3:
                    continue
                n += 1
                out.append({
                    "id": f"C{n:03d}", "type": "C",
                    "question": f"{d}这边{phrasings[0]}、人均{PRICE_WORD[pr]}以内的有哪些",
                    "expected_entities": gts,
                    "answerable": True,
                    "notes": f"区县+人均硬条件 与「{predicate_desc}」语义意图的组合,两路都要用上",
                    "ground_truth_cypher": static_cypher(where),
                    "ground_truth_is_proxy": True,
                })
                break
    return out


def augment_truth_sets(questions: list) -> list:
    """给每道题补一个完整的标准答案集合 ground_truth_set(不截断)。

    为什么要补这一步:
      原来的 expected_entities 是"满足条件且按评分排序的前 10 家"。
      用它判定命中,实际考的是"返回顺序是否和评分序一致"——
      而向量检索按语义相似度排序,排序依据本来就不同。
      结果是:即使返回的全是正确品类的店,只要顺序不同就被判成未命中,
      把检索质量低估成"完全没找到"。
      补一个完整集合后,评测脚本可以额外算
      「谓词精确率 P@5」= 返回的前 5 条里有多少条真的满足这道题的条件,
      这才是衡量"有没有理解意图"的正确指标。
    """
    for q in questions:
        cyp = q.get("ground_truth_cypher") or ""
        if not cyp:
            q["ground_truth_set"] = list(q.get("expected_entities") or [])
            continue
        full = cyp.replace(f"LIMIT {TOP_N}", f"LIMIT {SET_CAP}")
        try:
            names = [r["名称"] for r in run_cypher(full) if r.get("名称")]
        except Exception:
            names = []
        q["ground_truth_set"] = names or list(q.get("expected_entities") or [])
    return questions


def main():
    rng = random.Random(SEED)
    a = build_A(rng)
    b = build_B(rng)
    c = build_C(rng)
    qs = augment_truth_sets(a + b + c)

    data = {
        "meta": {
            "version": "1.0",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "seed": SEED,
            "graph": {
                "poi": run_cypher("MATCH (p:POI) RETURN count(p) AS n")[0]["n"],
                "dish": run_cypher("MATCH (d:Dish) RETURN count(d) AS n")[0]["n"],
            },
            "counts": {"A": len(a), "B": len(b), "C": len(c), "total": len(qs)},
            "method": (
                "题目与标准答案均由 scripts/build_eval_set.py 从真实图谱反推生成,"
                "每题的 ground_truth_cypher 可独立重跑验证。"
                "A 类标准答案 = 等价 Cypher 的真实返回;B/C 类标准答案 = 文档化谓词"
                "(定义在 细类/店名 等真实字段上)命中的 POI,属于词法层面的代理标注,"
                "是语义质量的下界,不是人工精标。"
            ),
        },
        "questions": qs,
    }

    if "--stats" in sys.argv:
        print(json.dumps(data["meta"], ensure_ascii=False, indent=2))
        return
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写入 {OUT}")
    print(json.dumps(data["meta"]["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
