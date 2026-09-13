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
import logging
import threading
import warnings

warnings.filterwarnings("ignore")

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from src.config import neo4j_config

# Aura 会对"查询里引用了当前库里还不存在的属性"发大量告警
# (比如会话表还没数据时查 s.title)。这些是无害的,但每次查询都刷屏,
# 会把真正的错误淹掉,所以把通知日志压到 ERROR。
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

MAX_POOL_SIZE = 50

# Aura 会主动断开闲置连接,池子里会留下已经失效的连接。
# 让连接最多活 5 分钟就退役,不让它老到被服务端掐掉。
CONN_LIFETIME = 300

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
                    max_connection_lifetime=CONN_LIFETIME,
                )
    return _driver


def run_cypher(cypher: str, **params) -> list:
    """执行只读查询,返回 [dict, …]。

    为什么不用 session.execute_read(托管事务):
    托管事务虽然能让 driver 自动重试连接失效,但要多发 BEGIN / COMMIT
    两个往返。到 Aura 单程约 250ms,一次查询就从 250ms 涨到 730ms,
    而这个应用一次页面加载要跑好几次查询,代价太大。
    改成:普通 session.run(单往返) + 自己捕获取消重试。

    重试覆盖两个场景:
      SessionExpired    —— 复用到了一条已被服务端断开的连接
      ServiceUnavailable—— 连接池整体失效(典型:Aura 免费实例休眠后唤醒)
    两者都通过丢掉旧 driver、重建一条连接来恢复,避免整页 500。
    """
    def _once():
        with get_driver().session() as s:
            return [dict(r) for r in s.run(cypher, **params)]

    try:
        return _once()
    except (SessionExpired, ServiceUnavailable):
        reset_driver()
        return _once()


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
