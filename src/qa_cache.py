"""三级缓存(文档《KG项目优化文档》第一部分 1)。

设计取舍(为什么不是照抄文档里的代码):

  文档给的 cached_pipeline(question) 只 hash 问题,这在多轮追问场景下会串答案:
  用户 A 问「集宁区火锅」后追问「那评分高的呢」,用户 B 也追问「那评分高的呢」——
  两句话字面完全相同,但指的是不同的上一轮。所以缓存 key 必须带上:
      归一化问题 + 路由 + 上下文锚点(上一轮真正的问题)
  追问取不到锚点时直接绕过缓存,宁可慢也不能答错。

  L1 用自维护的字典(挂在 st.cache_resource 上)而不是 @st.cache_data,
  因为需要"先查、未命中再走流式生成、生成完再回填"这个流程,
  而 @st.cache_data 只能包住一个纯函数,给不出"命中/未命中"的分支。
  L2(查询向量)是标准的纯函数,就用 @st.cache_data,和文档一致。

  三级各管什么:
    L1 精确缓存  完全相同的问法 → 直接返回上次的完整结果(含渲染好的 HTML)
    L2 向量缓存  同一个查询文本不再重复调 embedding API
    L3 语义缓存  换了说法但意思一样 → 用向量相似度命中历史答案

  失效:L1 的 key 里带了 DATA_VERSION / PROMPT_VERSION,
  数据重灌或改提示词时把版本号 +1,旧缓存自然全部失效。
"""
import hashlib
import json
import threading
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import streamlit as st

BASE = Path(__file__).resolve().parent.parent

# ── 版本盐:数据重灌 / 改提示词时手动 +1,旧缓存立即失效 ──
DATA_VERSION = "2026-09-13"
PROMPT_VERSION = "v1"

# ── TTL / 容量 ──
TTL_L1 = 3600            # 精确缓存 1 小时
TTL_L2 = 86400           # 向量缓存 24 小时(向量不会变)
TTL_L3 = 72 * 3600       # 语义缓存 72 小时
MAX_L1 = 500             # L1 最多存多少条(超出按最后命中时间淘汰)
MAX_L3 = 2000            # L3 最多存多少条
SEMANTIC_THRESHOLD = 0.96   # bge-m3 上 0.95 偏松,容易把条件不同的问法混为一谈

_EMBED_DIM = 1024


# ══════════════════════════════════════════════════════════════
# key 构造
# ══════════════════════════════════════════════════════════════

_PUNCT = " \t\r\n?？!！。.,,;；:：、"


def norm(text: str) -> str:
    """归一化问题文本:压空白、去首尾标点。

    只做这一层归一化——同义词改写交给 L3 语义缓存,不在这里做。
    """
    t = " ".join((text or "").split())
    return t.strip(_PUNCT)


def ctx_anchor(history: list) -> str:
    """上下文锚点:最近一个"非追问"问题的归一化文本。

    追问("那评分高的呢")换到另一个话题下意思完全不同,
    所以缓存 key 要把锚点带上,不同话题下的同一句追问不会互相命中。
    """
    if not history:
        return ""
    from src.hybrid_retrieval import is_followup
    for h in reversed(history):
        q = h.get("q") or ""
        if q and not is_followup(q):
            return norm(q)
    return ""


def cache_key(question: str, route: str, history: list) -> str:
    raw = "|".join([
        norm(question), route or "", ctx_anchor(history),
        DATA_VERSION, PROMPT_VERSION,
    ])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:20]


def cacheable(question: str, history: list) -> bool:
    """这次问答能不能进缓存。

    有一种情况必须绕过缓存:句子本身是追问(短、带指代词),
    但历史里找不到任何可作为锚点的非追问问题。
    这时"那评分高的呢"到底指什么完全无法确定,
    缓存 key 里的锚点是空串,不同话题下的同一句话会互相命中——
    宁可每次都重新算,也不能把 A 话题的答案返给 B 话题。
    """
    from src.hybrid_retrieval import is_followup
    if is_followup(question) and not ctx_anchor(history):
        return False
    return True


# ══════════════════════════════════════════════════════════════
# L1 精确缓存
# ══════════════════════════════════════════════════════════════

@st.cache_resource
def _l1_store():
    """进程内全局存储(Streamlit 里所有会话共享)。"""
    return {"data": {}, "lock": threading.Lock()}


@st.cache_resource
def _hit_counter():
    return {"L1": 0, "L3": 0, "miss": 0, "lock": threading.Lock()}


def _bump(field: str, n: int = 1):
    c = _hit_counter()
    with c["lock"]:
        c[field] = c.get(field, 0) + n


def l1_get(key: str):
    store = _l1_store()
    with store["lock"]:
        item = store["data"].get(key)
        if not item:
            return None
        ts, payload = item
        if time.time() - ts > TTL_L1:
            store["data"].pop(key, None)
            return None
        store["data"][key] = (time.time(), payload)   # 更新最后命中时间(LRU 用)
    _bump("L1")
    return payload


def l1_put(key: str, payload: dict):
    store = _l1_store()
    with store["lock"]:
        d = store["data"]
        d[key] = (time.time(), payload)
        if len(d) > MAX_L1:
            # 按最后命中时间淘汰最旧的一批
            for k, _ in sorted(d.items(), key=lambda kv: kv[1][0])[:len(d) - MAX_L1]:
                d.pop(k, None)


# ══════════════════════════════════════════════════════════════
# L2 查询向量缓存
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=TTL_L2, show_spinner=False)
def cached_embed(text: str) -> tuple:
    """查询文本 → 向量(同一个文本不再重复调 embedding API)。

    返回 tuple 而不是 list:更省内存,也保证缓存对象不可变。
    """
    from src.vector_search import embed_query
    v = embed_query(text)
    return tuple(v) if v else ()


# ══════════════════════════════════════════════════════════════
# L3 语义缓存(Neo4j 持久化 + 进程内 numpy 镜像)
# ══════════════════════════════════════════════════════════════

def _cache_label() -> str:
    return "QACache"


@st.cache_resource
def _l3_matrix():
    """进程内镜像:{"mat": np.ndarray(n,1024), "rows": [...]}。

    线上是 Streamlit Community Cloud,容器文件系统是临时的,
    所以持久化只能落 Neo4j(项目已经在用它存反馈)。
    查询时用 numpy 矩阵乘算相似度,几百上千条 <1ms,和 vector_search 同款做法。
    """
    return {"mat": None, "rows": [], "loaded_at": 0.0, "lock": threading.Lock()}


def _load_l3(force: bool = False):
    mirror = _l3_matrix()
    with mirror["lock"]:
        if not force and mirror["mat"] is not None and time.time() - mirror["loaded_at"] < 300:
            return mirror["mat"], mirror["rows"]
        try:
            from src.db import run_cypher
            rows = run_cypher(
                "MATCH (c:QACache) WHERE c.created_at_ts IS NOT NULL "
                "RETURN c.q AS q, c.answer AS answer, c.route AS route, "
                "       c.payload AS payload, c.embedding AS embedding, "
                "       c.created_at_ts AS ts, c.hits AS hits "
                "ORDER BY c.last_hit_ts DESC LIMIT $n",
                n=MAX_L3,
            )
        except Exception:
            rows = []

        now = time.time()
        keep, vecs = [], []
        for r in rows:
            emb = r.get("embedding")
            if not emb or len(emb) != _EMBED_DIM:
                continue
            if now - float(r.get("ts") or 0) > TTL_L3:
                continue
            keep.append(r)
            vecs.append(emb)
        mirror["rows"] = keep
        mirror["mat"] = (np.asarray(vecs, dtype="float32") if vecs else None)
        mirror["loaded_at"] = now
        return mirror["mat"], mirror["rows"]


def semantic_lookup(qvec, route: str, threshold: float = SEMANTIC_THRESHOLD):
    """用查询向量在语义缓存里找相似问题。命中返回 payload,否则 None。"""
    if not qvec:
        return None
    mat, rows = _load_l3()
    if mat is None or not len(rows):
        return None

    q = np.asarray(qvec, dtype="float32")
    n = np.linalg.norm(q)
    if n > 0:
        q = q / n
    scores = mat @ q
    best = int(np.argmax(scores))
    score = float(scores[best])
    if score < threshold:
        return None
    row = rows[best]
    # 路由必须一致:结构化问题和语义问题即使字面相近,答案也不可互换
    if (row.get("route") or "") != (route or ""):
        return None

    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return None
    if not isinstance(payload, dict):
        return None
    payload = dict(payload)
    payload["similarity"] = round(score, 4)
    payload["matched_question"] = row.get("q")
    _bump("L3")
    _touch_l3(row.get("q"))
    return payload


def _touch_l3(q: str):
    """记录一次命中(用于 LRU 淘汰和统计)。失败不影响主流程。"""
    try:
        from src.db import run_cypher
        run_cypher(
            "MATCH (c:QACache {q: $q}) "
            "SET c.hits = coalesce(c.hits, 0) + 1, c.last_hit_ts = $ts",
            q=q, ts=time.time(),
        )
    except Exception:
        pass


def semantic_store(question: str, qvec, payload: dict, route: str):
    """把一次成功问答写进语义缓存。

    只存有内容的回答:报错和空结果不缓存,否则会把一次失败固化下来。
    """
    if not qvec or not payload:
        return False
    if payload.get("err"):
        return False
    if not (payload.get("answer") or "").strip():
        return False

    try:
        from src.db import run_cypher
        run_cypher(
            "CREATE CONSTRAINT qacache_q IF NOT EXISTS "
            "FOR (c:QACache) REQUIRE c.q IS UNIQUE",
        )
    except Exception:
        pass

    try:
        from src.db import run_cypher
        run_cypher(
            """
            MERGE (c:QACache {q: $q})
            SET c.answer = $answer,
                c.route = $route,
                c.payload = $payload,
                c.embedding = $embedding,
                c.created_at_ts = coalesce(c.created_at_ts, $ts),
                c.last_hit_ts = $ts,
                c.hits = coalesce(c.hits, 0)
            """,
            q=question,
            answer=(payload.get("answer") or "")[:2000],
            route=route or "",
            payload=json.dumps(payload, ensure_ascii=False, default=str)[:20000],
            embedding=[float(x) for x in qvec],
            ts=time.time(),
        )
        _load_l3(force=True)
        return True
    except Exception:
        return False


def semantic_prune():
    """超出上限时按最后命中时间淘汰(在写入后调用,失败不影响主流程)。"""
    try:
        _load_l3(force=True)
        from src.db import run_cypher
        n = run_cypher("MATCH (c:QACache) RETURN count(c) AS n")[0]["n"]
        if n <= MAX_L3:
            return 0
        res = run_cypher(
            """
            MATCH (c:QACache)
            WITH c ORDER BY coalesce(c.last_hit_ts, c.created_at_ts) ASC
            LIMIT $k
            DETACH DELETE c
            RETURN count(*) AS n
            """,
            k=n - MAX_L3,
        )
        return res[0]["n"] if res else 0
    except Exception:
        return 0


def cache_stats() -> dict:
    """给指标看板用的缓存统计。"""
    l1 = _l1_store()["data"]
    counter = _hit_counter()
    mat, rows = _load_l3()
    l1_hits, l3_hits, miss = counter.get("L1", 0), counter.get("L3", 0), counter.get("miss", 0)
    total = l1_hits + l3_hits + miss
    return {
        "L1条目数": len(l1),
        "L3条目数": len(rows),
        "L1命中": l1_hits,
        "L3命中": l3_hits,
        "未命中": miss,
        "总请求": total,
        "命中率": f"{(l1_hits + l3_hits) / total * 100:.0f}%" if total else "—",
    }


def note_miss():
    _bump("miss")


def clear_all():
    """清空缓存(调试/数据更新后手动调用)。"""
    store = _l1_store()
    with store["lock"]:
        store["data"].clear()
    _load_l3(force=True)
    try:
        from src.db import run_cypher
        run_cypher("MATCH (c:QACache) DETACH DELETE c")
    except Exception:
        pass
    try:
        cached_embed.clear()
    except Exception:
        pass
