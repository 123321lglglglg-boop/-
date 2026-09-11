#!/usr/bin/env bash
# 解压 neo4j deb 到 ~/tools 并做免 sudo 运行配置
set -e

DEB="$HOME/tools/neo4j_5.26.30_all.deb"
DEST="$HOME/tools/neo4j-community-5.26.30"
EXTRACT="$HOME/tools/neo4j_extract"

size=$(stat -c%s "$DEB" 2>/dev/null || echo 0)
if [ "$size" -lt 150000000 ]; then
  echo "deb 未下载完整 ($((size/1048576)) MB),请先完成 download_neo4j.sh"
  exit 1
fi

# 备份已有的 data(如果之前启动过)
if [ -d "$DEST/data" ]; then
  mv "$DEST/data" "$DEST/data.bak.$(date +%s)"
fi

rm -rf "$EXTRACT"
mkdir -p "$EXTRACT"
dpkg-deb -x "$DEB" "$EXTRACT"

mkdir -p "$DEST"
if [ -d "$EXTRACT/usr/share/neo4j" ]; then
  cp -r "$EXTRACT/usr/share/neo4j/." "$DEST/"
else
  echo "deb 内部结构异常:"
  find "$EXTRACT" -maxdepth 3 -type d | head -20
  exit 1
fi

# deb 里的配置文件在 /etc/neo4j,补到安装目录的 conf/ 下
mkdir -p "$DEST/conf"
cp -n "$EXTRACT/etc/neo4j/neo4j.conf" "$DEST/conf/neo4j.conf"
cp -n "$EXTRACT/etc/neo4j/neo4j-admin.conf" "$DEST/conf/neo4j-admin.conf"
cp -n "$EXTRACT/etc/neo4j/server-logs.xml" "$DEST/conf/server-logs.xml"
cp -n "$EXTRACT/etc/neo4j/user-logs.xml" "$DEST/conf/user-logs.xml"
rm -rf "$EXTRACT"

# 免 sudo 运行所需调整
CONF="$DEST/conf/neo4j.conf"
# 服务器监听所有地址(Windows 通过 localhost 转发访问)
sed -i 's/^#\?server\.default_listen_address=.*/server.default_listen_address=0.0.0.0/' "$CONF"
sed -i 's/^#\?server\.bolt\.listen_address=.*/server.bolt.listen_address=:7687/' "$CONF"
sed -i 's/^#\?server\.http\.listen_address=.*/server.http.listen_address=:7474/' "$CONF"
# 关掉 usage 统计上报
sed -i 's/^#\?dbms\.usage_reporting\.enabled=.*/dbms.usage_reporting.enabled=false/' "$CONF"
# 数据/日志目录改为安装目录下(用户可写)
sed -i "s|^#\?server\.directories\.data=.*|server.directories.data=$DEST/data|" "$CONF"
sed -i "s|^#\?server\.directories\.logs=.*|server.directories.logs=$DEST/logs|" "$CONF"
sed -i "s|^#\?server\.directories\.run=.*|server.directories.run=$DEST/run|" "$CONF"
sed -i "s|^#\?server\.directories\.import=.*|server.directories.import=$DEST/import|" "$CONF"

mkdir -p "$DEST/data" "$DEST/logs" "$DEST/run" "$DEST/import"

# 设置初始密码(仅首次生效)
if [ ! -f "$DEST/data/dbms/auth" ]; then
  "$DEST/bin/neo4j-admin" dbms set-initial-password wlcb123456 2>/dev/null || true
fi

echo "解压完成: $DEST"
grep -E "^server\.(default_listen|bolt\.listen|http\.listen|directories)" "$CONF" 2>/dev/null | head -8
echo "下一步: bash start_neo4j.sh start"
