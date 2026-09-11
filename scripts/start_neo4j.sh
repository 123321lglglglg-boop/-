#!/usr/bin/env bash
# 在 WSL 里以普通用户身份运行 Neo4j(免 sudo,免系统服务)
# 用法: bash start_neo4j.sh [start|stop|status]
set -e

NEO4J_HOME="$HOME/tools/neo4j-community-5.26.30"
NEO4J_BIN="$NEO4J_HOME/bin/neo4j"
JAVA_HOME_DIR=$(ls -d "$HOME"/tools/jdk-17* 2>/dev/null | head -1)
PIDFILE="$NEO4J_HOME/run/neo4j.pid"

if [ ! -x "$NEO4J_BIN" ]; then
  echo "未找到 Neo4j: $NEO4J_BIN"
  echo "请先运行 unpack_neo4j.sh"
  exit 1
fi

export JAVA_HOME="$JAVA_HOME_DIR"
export NEO4J_HOME
export PATH="$JAVA_HOME/bin:$PATH"

# 配置文件里关闭 sysctl 类系统调用,普通用户才能启动
CONF="$NEO4J_HOME/conf/neo4j.conf"

case "${1:-start}" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Neo4j 已在运行 (pid $(cat "$PIDFILE"))"
      exit 0
    fi
    # setsid + nohup:让 Neo4j 脱离 WSL 会话,会话结束后不被杀掉
    setsid nohup "$NEO4J_BIN" console >/dev/null 2>&1 &
    echo "Neo4j 正在后台启动..."
    echo "等待就绪..."
    for i in $(seq 1 60); do
      if curl -s --max-time 2 http://localhost:7474 >/dev/null 2>&1; then
        echo "Neo4j 已就绪: http://localhost:7474"
        echo "Bolt 地址(Windows Python 用): bolt://localhost:7687"
        exit 0
      fi
      sleep 2
    done
    echo "超时未就绪,查看日志: $NEO4J_HOME/logs/neo4j.log"
    exit 1
    ;;
  stop)
    "$NEO4J_BIN" stop
    ;;
  status)
    "$NEO4J_BIN" status || true
    ;;
  *)
    echo "用法: $0 [start|stop|status]"
    exit 1
    ;;
esac
