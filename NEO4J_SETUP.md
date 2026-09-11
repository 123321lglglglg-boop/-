# 启动 Neo4j(Docker 方式,已适配国内镜像源)

## 首次启动

```bash
docker run -d --name neo4j-wlcb ^
  -p 7474:7474 -p 7687:7687 ^
  -e NEO4J_AUTH=neo4j/wlcb123456 ^
  -e NEO4J_PLUGINS='["apoc"]' ^
  -v wlcb_neo4j_data:/data ^
  neo4j:5.26-community
```

说明:
- `7474` = Neo4j Browser(网页界面,http://localhost:7474)
- `7687` = Bolt 协议端口(我们的 Python 脚本连这个)
- 用户名 `neo4j`,密码 `wlcb123456`(仅本地学习用,可改)
- 数据存在 Docker volume `wlcb_neo4j_data`,容器删了数据还在

## 日常使用

```bash
docker start neo4j-wlcb     # 启动
docker stop neo4j-wlcb      # 停止
docker logs -f neo4j-wlcb   # 看日志(启动后等 ~20 秒才就绪)
```

## 连接信息(给 load_neo4j.py 用)

```bash
set NEO4J_URI=bolt://localhost:7687
set NEO4J_USER=neo4j
set NEO4J_PASSWORD=wlcb123456
python src/load_neo4j.py
```

## 验证

浏览器打开 http://localhost:7474,用上面的账号密码登录,在顶部输入框执行:

```
MATCH (n) RETURN count(n);
```

看到节点数即成功。数据导入后可以跑 `cypher/queries.cypher` 里的查询。
