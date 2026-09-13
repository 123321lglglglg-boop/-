"""对话历史持久化(文档《KG项目优化文档》第二部分 3)。

为什么要做:现在多轮对话只存在 st.session_state.chat 里,刷新页面就没了。

存储介质说明:文档给的是 MongoDB(db.sessions.update_one),但线上是
Streamlit Community Cloud,唯一可用的持久化存储就是 Neo4j Aura
(项目已经在用它存反馈)。所以这里改用图模型:

    (:Session {sid, client_id, title, created_at, updated_at, msg_count})
        -[:包含 {seq}]->
    (:Msg {mid, seq, role, content, question, cypher, route, records_json, created_at})

为什么用子图而不是把整个对话塞进一个 JSON 属性:
  1. 追加是幂等的——每条消息有稳定的 mid,MERGE 一下就行,不用读-改-写整个列表
  2. 消息本身是可以被查询的对象(比如"哪些问题触发了语义路由"),
     这和用图数据库存反馈是同一个思路

用户身份:用的是 st.query_params 里的会话 ID(刷新后还在),
而不是 st.session_state 里的随机 client_id(刷新就变)。

体量控制:path_html / route_html 这些是渲染好的 HTML 片段,很大且可重算,
不落库;只存 question / cypher / records,读回来时重新算一遍展示片段。
"""
import json
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

from src.db import get_driver

MAX_RECORDS = 50        # 每条消息最多存多少行结果(表格是展示用,不必全存)
MAX_MESSAGES = 60       # 单个会话最多保留多少条消息
MAX_CONTENT = 4000      # 单条答案最多存多少字符

SCHEMA = [
    "CREATE CONSTRAINT session_id IF NOT EXISTS FOR (s:Session) REQUIRE s.sid IS UNIQUE",
    "CREATE CONSTRAINT msg_mid IF NOT EXISTS FOR (m:Msg) REQUIRE m.mid IS UNIQUE",
]

_ready = {"done": False}


def _ensure_schema():
    if _ready["done"]:
        return
    with get_driver().session() as s:
        for c in SCHEMA:
            try:
                s.run(c)
            except Exception:
                pass
    _ready["done"] = True


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_session(sid: str, client_id: str, messages: list) -> bool:
    """把一个会话的最新状态写库(按 mid 幂等,MERGE 即可,重复调用安全)。"""
    if not sid or not messages:
        return False
    msgs = messages[-MAX_MESSAGES:]
    title = ""
    for m in msgs:
        if m.get("role") == "user":
            title = (m.get("content") or "")[:30]
            break

    rows = []
    for i, m in enumerate(msgs):
        recs = m.get("records") or []
        ri = m.get("route_info") or {}
        rows.append({
            "mid": f"{sid}:{i}",
            "seq": i,
            "role": m.get("role", ""),
            "content": (m.get("content") or "")[:MAX_CONTENT],
            "question": (m.get("question") or "")[:500],
            "cypher": (m.get("cypher") or "")[:2000],
            "route": ri.get("route", "") if isinstance(ri, dict) else "",
            "records_json": json.dumps(recs[:MAX_RECORDS], ensure_ascii=False,
                                       default=str)[:60000],
            "route_info_json": json.dumps(ri, ensure_ascii=False, default=str)[:2000],
            "compare_info_json": json.dumps(m.get("compare_info"), ensure_ascii=False,
                                            default=str)[:4000]
            if m.get("compare_info") else "",
            "cache_badge": (m.get("cache_badge") or "")[:200],
            "created_at": _now(),
        })

    try:
        with get_driver().session() as s:
            _ensure_schema()
            s.run(
                """
                MERGE (s:Session {sid: $sid})
                SET s.client_id = $cid,
                    s.updated_at = $ts,
                    s.msg_count = $n,
                    s.title = CASE WHEN s.title IS NULL OR s.title = ''
                                   THEN $title ELSE s.title END,
                    s.created_at = coalesce(s.created_at, $ts)
                """,
                sid=sid, cid=client_id or "anon", ts=_now(),
                n=len(rows), title=title or "新会话",
            )
            s.run(
                """
                UNWIND $rows AS row
                MERGE (m:Msg {mid: row.mid})
                SET m.seq = row.seq,
                    m.role = row.role,
                    m.content = row.content,
                    m.question = row.question,
                    m.cypher = row.cypher,
                    m.route = row.route,
                    m.records_json = row.records_json,
                    m.route_info_json = row.route_info_json,
                    m.compare_info_json = row.compare_info_json,
                    m.cache_badge = row.cache_badge,
                    m.created_at = row.created_at
                WITH m, row
                MATCH (s:Session {sid: $sid})
                MERGE (s)-[r:包含]->(m)
                SET r.seq = row.seq
                """,
                rows=rows, sid=sid,
            )
        return True
    except Exception:
        return False


def list_sessions(client_id: str, limit: int = 20) -> list:
    """列出该用户的最近会话(用于侧栏历史列表)。"""
    try:
        with get_driver().session() as s:
            _ensure_schema()
            return [dict(r) for r in s.run(
                """
                MATCH (s:Session {client_id: $cid})
                RETURN s.sid AS sid, s.title AS title,
                       s.updated_at AS updated_at, s.msg_count AS msg_count
                ORDER BY s.updated_at DESC LIMIT $limit
                """,
                cid=client_id or "anon", limit=limit,
            )]
    except Exception:
        return []


def load_session(sid: str) -> list:
    """读回一个会话的全部消息(按 seq 排序),还原成 st.session_state.chat 的结构。"""
    try:
        with get_driver().session() as s:
            rows = [dict(r) for r in s.run(
                """
                MATCH (s:Session {sid: $sid})-[:包含]->(m:Msg)
                RETURN m.seq AS seq, m.role AS role, m.content AS content,
                       m.question AS question, m.cypher AS cypher,
                       m.records_json AS records_json,
                       m.route_info_json AS route_info_json,
                       m.compare_info_json AS compare_info_json,
                       m.cache_badge AS cache_badge
                ORDER BY m.seq
                """,
                sid=sid,
            )]
    except Exception:
        return []

    out = []
    for r in rows:
        try:
            records = json.loads(r.get("records_json") or "[]")
        except Exception:
            records = []
        try:
            route_info = json.loads(r.get("route_info_json") or "null")
        except Exception:
            route_info = None
        try:
            compare_info = json.loads(r.get("compare_info_json") or "null")
        except Exception:
            compare_info = None
        out.append({
            "role": r.get("role", ""),
            "content": r.get("content", ""),
            "question": r.get("question", ""),
            "cypher": r.get("cypher", ""),
            "records": records,
            "route_info": route_info,
            "compare_info": compare_info,
            "cache_badge": r.get("cache_badge", ""),
        })
    return out


def delete_session(sid: str) -> bool:
    try:
        with get_driver().session() as s:
            s.run("MATCH (s:Session {sid: $sid}) DETACH DELETE s", sid=sid)
        return True
    except Exception:
        return False
