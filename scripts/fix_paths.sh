#!/usr/bin/env bash
# 修正日志配置文件路径(/etc/neo4j → 本地 conf 目录)
DEST="$HOME/tools/neo4j-community-5.26.30"

for f in "$DEST/conf"/*.xml; do
  sed -i "s|/etc/neo4j/|$DEST/conf/|g" "$f"
done
# neo4j.conf 里可能也引用了 xml 路径或 /var 路径
sed -i "s|/etc/neo4j/|$DEST/conf/|g" "$DEST/conf/neo4j.conf"
sed -i "s|/var/log/neo4j|$DEST/logs|g; s|/var/lib/neo4j|$DEST/data|g" "$DEST/conf/neo4j.conf"

echo "=== 检查残留的系统路径 ==="
grep -E "/etc/neo4j|/var/log/neo4j|/var/lib/neo4j" "$DEST/conf/neo4j.conf" "$DEST/conf"/*.xml || echo "无残留"
