// 典型查询:在 Neo4j Browser 里逐条运行,截图可放简历/面试演示

// 1. 集宁区评分最高的 10 家餐厅
MATCH (p:POI)-[:位于]->(:District {name:'集宁区'})
WHERE p.rating IS NOT NULL
RETURN p.name, p.rating, p.address
ORDER BY p.rating DESC LIMIT 10;

// 2. 各区县 POI 数量分布
MATCH (p:POI)-[:位于]->(d:District)
RETURN d.name, count(p) AS cnt ORDER BY cnt DESC;

// 3. 品类 TOP15
MATCH (p:POI)-[:属于细类]->(c:CategoryL3)
RETURN c.name, count(p) AS cnt ORDER BY cnt DESC LIMIT 15;

// 4. 连锁品牌门店数排行
MATCH (p:POI)-[:连锁品牌]->(ch:Chain)
RETURN ch.name, count(p) AS stores ORDER BY stores DESC LIMIT 10;

// 5. 某品牌全部门店(示例:蜜雪冰城)
MATCH (p:POI)-[:连锁品牌]->(ch:Chain)
WHERE ch.name CONTAINS '蜜雪冰城'
RETURN p.name, p.address, p.rating;

// 6. 集宁区人均 50 以下、评分 4.0 以上的馆子(图文谱问答要实现的查询)
MATCH (p:POI)-[:位于]->(:District {name:'集宁区'})
WHERE p.cost <= 50 AND p.rating >= 4.0
RETURN p.name, p.cost, p.rating ORDER BY p.rating DESC LIMIT 20;

// 7. 图谱总览(可视化:节点+关系)
MATCH (p:POI)-[r]->(x) RETURN p, r, x LIMIT 200;
