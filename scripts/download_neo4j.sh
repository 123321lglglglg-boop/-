#!/usr/bin/env bash
# 断点续传下载 neo4j deb 到 ~/tools(/tmp 会因 WSL 重启丢失)
DEB="$HOME/tools/neo4j_5.26.30_all.deb"
TARGET=158200000
URL="https://debian.neo4j.com/pool/5/n/neo4j/neo4j_5.26.30_all.deb"

mkdir -p "$HOME/tools"

for i in $(seq 1 100); do
  size=$(stat -c%s "$DEB" 2>/dev/null || echo 0)
  if [ "$size" -ge "$TARGET" ]; then
    echo "下载完成: $((size/1048576)) MB"
    exit 0
  fi
  echo "第 $i 轮,已有 $((size/1048576)) MB"
  curl -sL -C - --max-time 120 -o "$DEB" "$URL" 2>/dev/null || true
  sleep 1
done
echo "重试次数用尽,当前 $(( $(stat -c%s "$DEB" 2>/dev/null || echo 0) /1048576 )) MB"
exit 1
