"""意图分流 + 图谱/向量双路检索 + RRF 融合(方案 4.1 / 5.1)。

分工原则(方案核心):
  结构化问题(人均50以下、有几家、评分最高)→ 走图谱,精确可控
  模糊语义问题(适合带小孩、氛围好)→ 走向量,图谱做不到
  混合问题(集宁区适合聚会的餐厅人均100内)→ 双路并行 + RRF 融合
"""
import re
import warnings

warnings.filterwarnings("ignore")

from src.vector_search import semantic_search

# ---- 分流规则 ----

# 结构化信号:数值/计数/精确条件 → 图谱强项
STRUCT_SIGNALS = [
    "多少家", "几家", "几个", "数量", "人均", "多少钱", "价格", "评分",
    "最高", "最低", "最贵", "最便宜", "排名", "top", "前几名",
    "以下", "以上", "以内", "超过", "低于", "高于",
    "几区", "分布", "哪个区", "哪些区",
]
# 语义信号:主观/模糊/体验类 → 向量强项
SEMANTIC_SIGNALS = [
    "适合", "氛围", "环境", "推荐", "好吃", "特色", "有名", "口碑",
    "带小孩", "带孩子", "约会", "聚会", "安静", "热闹", "放松",
    "好玩", "有意思", "值得", "怎么样", "好不好", "体验",
]

# 明确的实体/关系查询 → 图谱
KG_EXPLICIT = ["附近", "最近", "邻近", "属于", "连锁", "品牌"]
# 明确的品类词(用于混合判定)
CATEGORY_WORDS = [
    "火锅", "烧烤", "蒙餐", "莜面", "烧麦", "咖啡", "酒店", "宾馆",
    "景点", "KTV", "酒吧", "网吧", "电影", "商场", "超市", "民宿",
    "快餐", "甜品", "奶茶", "面馆", "餐厅", "餐馆",
]
# 菜品词:图谱有 Dish 实体,走图谱比向量精确
DISH_WORDS = [
    "羊杂", "羊杂碎", "冰煮羊", "铁锅焖面", "焖面", "烧麦", "稍麦", "熏鸡",
    "刀削面", "麻辣烫", "肉夹馍", "串串香", "汉堡", "果茶", "生日蛋糕",
    "莜面", "羊蝎子", "海鲜烧烤", "私房菜", "农家菜", "土豆粉",
    "炸鸡", "披萨", "米线", "烤肉", "涮羊肉", "手把肉", "烩菜",
]
# 询问"哪里有/卖/吃"这类动词 + 菜品词 → 明确是找店,走图谱
DISH_QUERY_VERBS = ["哪里有", "哪里卖", "哪卖", "哪家", "哪有", "吃", "卖", "推荐"]


def classify(query: str) -> str:
    """分流:返回 'structured' | 'semantic' | 'hybrid'。"""
    q = (query or "").strip()
    if not q:
        return "structured"

    # 菜品查询优先:图谱有 Dish 实体,精确匹配优于语义近似
    has_dish = any(d in q for d in DISH_WORDS)
    if has_dish:
        # "想吃冰煮羊" / "哪里有卖羊杂的" / "铁锅焖面哪家好" → 图谱
        if any(v in q for v in ["吃", "卖", "哪", "推荐", "找"]):
            return "structured"
        # 单纯提菜品名,也是精确查询
        return "structured"

    has_struct = any(k in q for k in STRUCT_SIGNALS)
    has_semantic = any(k in q for k in SEMANTIC_SIGNALS)
    has_kg = any(k in q for k in KG_EXPLICIT)

    # 关系类查询(附近/最近)必须走图谱
    if has_kg and not has_semantic:
        return "structured"

    # 纯结构化 → 图谱
    if has_struct and not has_semantic:
        return "structured"

    # 纯语义 → 向量
    if has_semantic and not has_struct:
        return "semantic"

    # 两者都有 → 混合
    if has_struct and has_semantic:
        return "hybrid"

    # 没有明显信号:含品类词走图谱,否则走向量
    if any(w in q for w in CATEGORY_WORDS):
        return "structured"

    return "semantic"


# 追问的指代信号:出现这些词说明依赖上文
FOLLOWUP_PATTERNS = [
    "那", "呢", "还有", "再", "换", "别的", "其他", "另外",
    "上面", "刚才", "刚说", "之前", "这个", "这些", "那些",
    "它的", "他的", "他们", "其中", "里面",
]


def is_followup(query: str) -> bool:
    """判断是否是追问(依赖上文的短问题)。"""
    q = (query or "").strip()
    if not q:
        return False
    # 短问题 + 指代词 → 追问
    if len(q) <= 15 and any(p in q for p in FOLLOWUP_PATTERNS):
        return True
    # 很短的问句(<=8字)通常也是追问
    if len(q) <= 8:
        return True
    return False


def classify_with_context(query: str, history: list = None) -> str:
    """带上下文的分流。

    追问场景("那评分高的呢")字面没有结构化信号,
    但它继承的是上一轮的检索意图,所以必须参考历史路由。
    """
    base = classify(query)
    if not history:
        return base

    if not is_followup(query):
        return base

    # 追问:继承上一轮的意图(从最近一条有 cypher/来源的记录推断)
    last_route = None
    for h in reversed(history):
        if h.get("route"):
            last_route = h["route"]
            break
        # 旧记录没有 route 字段时,从 cypher 有无推断
        if h.get("cypher"):
            last_route = "structured"
            break

    if last_route in ("structured", "hybrid"):
        # 上一轮走图谱/混合 → 追问很可能还是结构化加深
        # 但如果追问本身有语义信号,则升级为混合
        if classify(query) == "semantic":
            return "hybrid"
        return "structured"

    if last_route == "semantic":
        # 上一轮是语义检索 → 追问通常继续在语义空间
        if classify(query) == "structured":
            return "hybrid"
        return "semantic"

    return base


# ---- RRF 融合(方案 5.1 解法 A)----

def rrf_fuse(kg_results: list, vec_results: list, k: int = 60) -> list:
    """倒数排名融合:不看分数,只看排名,规避量纲不一致。

    图谱 score=1.0(布尔命中)与向量 score=0.73(余弦)量纲不同,
    直接加权会让图谱永远赢。
    """
    scores = {}
    for rank, item in enumerate(kg_results):
        key = item.get("poi_id") or item.get("name")
        if key:
            scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
    for rank, item in enumerate(vec_results):
        key = item.get("poi_id") or item.get("name")
        if key:
            scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)

    all_items = {}
    for item in kg_results + vec_results:
        key = item.get("poi_id") or item.get("name")
        if key and key not in all_items:
            all_items[key] = item

    ranked = sorted(all_items.values(),
                    key=lambda x: scores.get(x.get("poi_id") or x.get("name"), 0),
                    reverse=True)
    for item in ranked:
        item["rrf_score"] = scores.get(item.get("poi_id") or item.get("name"), 0)
    return ranked


def rerank_with_llm(query: str, candidates: list, top_n: int = 5) -> list:
    """用 LLM 做精排(替代 BGE-Reranker,省一个模型)。

    方案推荐 RRF 粗排 → Reranker 精排;这里用 LLM 充当 Reranker,
    因为云端装不下 2GB 的 reranker 模型,而 LLM 我们已经有了。
    """
    if not candidates:
        return []
    if len(candidates) <= top_n:
        return candidates

    from src.llm_qa import call_llm
    import json as _json

    items = []
    for i, c in enumerate(candidates[:12]):
        txt = (c.get("text") or c.get("name") or "")[:120].replace("\n", " ")
        items.append(f"[{i}] {txt}")

    prompt = f"""用户问题:{query}

候选结果:
{chr(10).join(items)}

请按与用户需求的相关性排序,只返回最相关的前 {top_n} 个的编号(JSON 数组,如 [2,0,5])。
只返回数组,不要解释。"""

    try:
        raw = call_llm([{"role": "user", "content": prompt}], temperature=0, max_tokens=100)
        m = re.search(r"\[[\d,\s]*\]", raw)
        if m:
            order = _json.loads(m.group(0))
            picked = []
            for i in order:
                if isinstance(i, int) and 0 <= i < len(candidates):
                    picked.append(candidates[i])
            if picked:
                return picked[:top_n]
    except Exception:
        pass
    return candidates[:top_n]


# ---- 完整检索流程(方案 5.2)----

def hybrid_retrieve(query: str, kg_search_fn, top_k: int = 10) -> dict:
    """按分流结果执行检索。

    kg_search_fn: 调用方传入的图谱检索函数 (query) -> list[dict]
    返回 {"route", "candidates", "kg_count", "vec_count"}
    """
    route = classify(query)

    kg_results, vec_results = [], []

    if route in ("structured", "hybrid"):
        try:
            kg_results = kg_search_fn(query) or []
        except Exception:
            kg_results = []

    if route in ("semantic", "hybrid"):
        try:
            vec_results = semantic_search(query, top_k=top_k) or []
        except Exception:
            vec_results = []

    if route == "structured":
        candidates = kg_results
    elif route == "semantic":
        candidates = rerank_with_llm(query, vec_results, top_n=5)
    else:
        merged = rrf_fuse(kg_results, vec_results)
        candidates = rerank_with_llm(query, merged, top_n=5)

    return {
        "route": route,
        "candidates": candidates,
        "kg_count": len(kg_results),
        "vec_count": len(vec_results),
    }
