// 高频查询字段索引(文档《KG项目优化文档》第一部分 5.1)
//
// 背景:建索引前用 PROFILE 看过执行计划,三种高频查询形态里
//   - "某区县的商家"   → 已在用 NodeUniqueIndexSeek(District.name),不用再加
//   - "评分最高的 N 家" → NodeByLabelScan,全表扫 6949 行再排序
//   - "店名包含 XX"     → NodeByLabelScan + Filter CONTAINS,全表扫 6949 行
// 后两种就是下面这几个索引要解决的。
//
// 实测(scripts/apply_indexes.py --bench,第一个扫表算子的行数):
//   按评分排序   6949 行 → 21 行(NodeIndexScan)
//   按人均过滤   6949 行 → 21 行(NodeIndexSeekByRange)
//
// 全部幂等(IF NOT EXISTS),可以反复执行。
// 执行:python scripts/apply_indexes.py

// ── 评分:支持"评分最高的 N 家"这类排序查询走有序索引扫描 ──
CREATE INDEX poi_rating_idx IF NOT EXISTS
FOR (p:POI) ON (p.rating);

// ── 人均:支持"人均 50 以下"这类范围过滤 ──
CREATE INDEX poi_cost_idx IF NOT EXISTS
FOR (p:POI) ON (p.cost);

// ── 店名:全文索引 ──
// 为什么必须是 FULLTEXT 而不是普通 RANGE 索引:
// TEXT2CYPHER_PROMPT 强制 LLM 用 CONTAINS 匹配店名(库里店名带后缀,例如
// 「乌兰图雅·蒙餐(乌兰察布怡海佳苑店)」),而 CONTAINS 是子串匹配,
// RANGE 索引只加速 = 和 STARTS WITH,对 CONTAINS 完全无效。
//
// 为什么必须指定 cjk 分析器:
// Neo4j 默认的 standard 分析器按空白/标点切词。中文店名没有空格,
// 整串会变成一个 token,导致索引里存的是「荣茂蒙餐(幸福路店)」这个整体,
// 搜「蒙餐」匹配不到——召回结果和 CONTAINS 完全对不上。
// 换成 cjk 分析器后按中文切词,子串检索才能命中。
CREATE FULLTEXT INDEX poi_name_fulltext IF NOT EXISTS
FOR (p:POI) ON EACH [p.name]
OPTIONS { indexConfig: { `fulltext.analyzer`: 'cjk' } };
