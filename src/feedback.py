"""用户反馈采集:把赞/踩与文字建议存入 Neo4j。

用图数据库存反馈有两个好处:
  1. 反馈可以和图谱里的实体(商家)建立关系,后续做"哪些商家的问答质量差"分析
  2. 演示了 Neo4j 作为通用数据存储的能力,不只是知识图谱
"""
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

from neo4j import GraphDatabase

from src.config import neo4j_config

SCHEMA = [
    "CREATE CONSTRAINT feedback_id IF NOT EXISTS FOR (f:Feedback) REQUIRE f.fid IS UNIQUE",
]


def _driver():
    uri, auth = neo4j_config()
    return GraphDatabase.driver(uri, auth=auth)


def save_feedback(fid: str, question: str, answer: str,
                  rating: int, comment: str = "", client_id: str = "") -> bool:
    """保存一条反馈。

    rating: 1 = 赞, -1 = 踩
    comment: 用户填写的具体意见(点踩时收集)
    返回是否保存成功。
    """
    uri, auth = neo4j_config()
    d = GraphDatabase.driver(uri, auth=auth)
    try:
        with d.session() as s:
            for c in SCHEMA:
                try:
                    s.run(c)
                except Exception:
                    pass
            s.run(
                """
                MERGE (f:Feedback {fid: $fid})
                SET f.rating = $rating,
                    f.question = $question,
                    f.answer = $answer,
                    f.comment = $comment,
                    f.client_id = $client_id,
                    f.created_at = $ts
                """,
                fid=fid,
                rating=int(rating),
                question=(question or "")[:500],
                answer=(answer or "")[:1500],
                comment=(comment or "")[:800],
                client_id=client_id or "anon",
                ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        return True
    except Exception:
        return False
    finally:
        d.close()


def feedback_stats() -> dict:
    """统计反馈情况(可在管理页展示)。"""
    uri, auth = neo4j_config()
    d = GraphDatabase.driver(uri, auth=auth)
    try:
        with d.session() as s:
            row = s.run(
                """
                MATCH (f:Feedback)
                RETURN count(f) AS total,
                       sum(CASE WHEN f.rating = 1 THEN 1 ELSE 0 END) AS likes,
                       sum(CASE WHEN f.rating = -1 THEN 1 ELSE 0 END) AS dislikes
                """
            ).single()
            if not row:
                return {"total": 0, "likes": 0, "dislikes": 0}
            return {
                "total": row["total"] or 0,
                "likes": row["likes"] or 0,
                "dislikes": row["dislikes"] or 0,
            }
    except Exception:
        return {"total": 0, "likes": 0, "dislikes": 0}
    finally:
        d.close()


def load_dislikes(limit: int = 20) -> list:
    """读取最近的负面反馈(改进依据)。"""
    uri, auth = neo4j_config()
    d = GraphDatabase.driver(uri, auth=auth)
    try:
        with d.session() as s:
            return [dict(r) for r in s.run(
                """
                MATCH (f:Feedback {rating: -1})
                RETURN f.question AS 问题, f.comment AS 用户意见,
                       f.created_at AS 时间
                ORDER BY f.created_at DESC LIMIT $limit
                """,
                limit=limit,
            )]
    except Exception:
        return []
    finally:
        d.close()
