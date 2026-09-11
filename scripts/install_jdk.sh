#!/usr/bin/env bash
# 下载并解压 JDK 17 到 ~/tools(免 sudo)
set -e
mkdir -p ~/tools
cd ~/tools

JDK_URL="https://mirrors.tuna.tsinghua.edu.cn/Adoptium/17/jdk/x64/linux/OpenJDK17U-jdk_x64_linux_hotspot_17.0.20.1_1.tar.gz"
JDK_TAR="jdk17.tar.gz"

if [ -d ~/tools/jdk-17* ]; then
  echo "JDK 已存在"
else
  for i in $(seq 1 30); do
    size=$(stat -c%s "$JDK_TAR" 2>/dev/null || echo 0)
    if [ "$size" -ge 190000000 ]; then break; fi
    echo "第 $i 轮,已有 $((size/1048576)) MB"
    curl -sL -C - --max-time 120 -o "$JDK_TAR" "$JDK_URL" 2>/dev/null || true
  done
  tar xzf "$JDK_TAR"
  echo "JDK 解压完成:"
  ls -d ~/tools/jdk-17*
fi
~/tools/jdk-17*/bin/java -version 2>&1 | head -2
