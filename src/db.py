"""Neo4j 驱动单例:全进程复用一个连接池。

为什么需要这个模块:
线上库是 Neo4j Aura(neo4j+s://),每次 GraphDatabase.driver() 都要重新做
DNS + TCP + TLS 握手,单次握手在公网上是几十到上百毫秒。而一次问答里
run_cypher 会被调用很多次(text2cypher 执行、失败重试、推理路径回溯、
品类清单、相关性重排……),每个调用点各建一个 driver 的话,这些握手开销
会直接叠进用户等待时间里。

neo4j 官方 driver 本身就是线程安全 + 自带连接池的,所以正确做法是
进程内只建一次、所有线程共享。

用法:
    from src.db import run_cypher
    rows = run_cypher("MATCH (p:POI) RETURN p.name AS 名称 LIMIT 10")
"""
import atexit
import threading
import warnings

warnings.filterwarnings("ignore")

from neo4j import GraphDatabase

from src.config import neo4j_config

MAX_POOL_SIZE = 50

_driver = None
_lock = threading.Lock()


def get_driver():
    """返回进程内唯一的 Neo4j driver(首次调用时创建)。"""
    global _driver
    if _driver is None:
        with _lock:
            # 双检锁:并发首调时只建一个,后面进来的直接拿现成的
            if _driver is None:
                uri, auth = neo4j_config()
                _driver = GraphDatabase.driver(
                    uri,
                    auth=auth,
                    max_connection_pool_size=MAX_POOL_SIZE,
                    connection_acquisition_timeout=30,
                )
    return _driver


def run_cypher(cypher: str, **params) -> list:
    """执行只读查询,返回 [dict, …]。"""
    with get_driver().session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


def reset_driver():
    """丢弃当前 driver(连接串变了或需要强制重连时用)。"""
    global _driver
    with _lock:
        if _driver is not None:
            try:
                _driver.close()
            except Exception:
                pass
            _driver = None


def close_driver():
    """进程退出时释放连接池。"""
    reset_driver()


atexit.register(close_driver)
