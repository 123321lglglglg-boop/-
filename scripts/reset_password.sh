#!/usr/bin/env bash
# 停止 Neo4j 并重置密码
JAVA_DIR=$(ls -d "$HOME"/tools/jdk-17* 2>/dev/null | head -1)
export JAVA_HOME="$JAVA_DIR"
export NEO4J_HOME="$HOME/tools/neo4j-community-5.26.30"
export PATH="$JAVA_HOME/bin:$PATH"

"$NEO4J_HOME/bin/neo4j" stop 2>/dev/null || pkill -f "Neo4jBoot" || true
pkill -f "CommunityEntryPoint" 2>/dev/null || true
sleep 4

echo "=== 重置密码 ==="
"$NEO4J_HOME/bin/neo4j-admin" dbms set-initial-password wlcb123456 2>&1
echo "=== 密码文件 ==="
ls -la "$NEO4J_HOME/data/dbms/" 2>/dev/null
