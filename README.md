# 乌兰察布本地生活知识图谱

数据源:高德开放平台 Web 服务 API(POI 搜索),个人学习用途。

## 已完成

- 采集 **6,949 条**乌兰察布 POI(11 区县,22 个品类 + 16 个连锁品牌关键词搜索)
- 覆盖:餐饮(含奶茶/冷饮)、住宿、景点、购物、**休闲娱乐(KTV/酒吧/网吧/电影院/洗浴/足疗/健身)**
- 清洗:303 个连锁品牌识别、91 组重名消歧、10 粗类/105 细类归一
- **图谱增强**:64+ 商圈(坐标聚类 + 地标命名)、4 价格带、4 评分档、
  14,650 条商家邻近关系(真实地理距离计算)、303 条品牌主营关系
- 图谱入库:**6,949 节点、53,666 条关系、11 种关系类型**(Neo4j 5.26,WSL 部署)
- 问答模块:规则解析版(自然语言 → 图谱查询 → 回答)
- **LLM 增强问答**:DeepSeek Text2Cypher + 答案生成(只读校验、出错自动重试)
- **网页 Demo:Streamlit + ECharts 交互式图谱,液态玻璃(Liquid Glass)UI 主题**
  (动态渐变光斑背景、毛玻璃卡片、液态流光标签页与按钮)

## 网页 Demo

**方式一(推荐,PyCharm 里直接右键运行):**
右键 `run_demo.py` → Run,然后浏览器打开 http://localhost:8510

**方式二(命令行):**
```bash
streamlit run app.py
```

**不要**直接运行 `app.py`(那是普通 Python 脚本的跑法,Streamlit 应用必须用 `streamlit run`)。

包含六个标签页:

- **🦸 首屏 Hero**:渐变标题、数字滚动动画、漂浮节点网络背景(canvas 实时绘制)
- **图谱总览**:指标卡、渐变配色柱状图(区县分布、商圈 TOP10)、关系类型分布
- **地图分布**:乌兰察布区县热力地图,**点击区县下钻** — 缩放到该区县并展示商家散点 +
  统计面板(商家数/平均评分/平均人均/品类 TOP5),支持下钻后按评分/人均/品类切换着色,
  有"返回全区"按钮;全在浏览器端完成,点击零延迟
- **图谱探索**:交互式知识图谱(拖拽/缩放/悬停详情/点图例筛选),
  两种模式:「区域总览」看某区县的完整网络结构,「商家邻域」看某商家与
  周边商家的邻近关系
- **商家查询**:按区县/品类/评分/人均/关键词多条件筛选
- **规则问答**:模板/规则解析查询,附"解析逻辑"展示
- **LLM 问答**:DeepSeek 把自然语言转 Cypher 查询图谱,再总结成自然语言回答;
  可展开查看生成的 Cypher 和执行流程

截图见 `docs/screenshots/`。

## 图谱规模

| 指标 | 数值 |
|---|---|
| POI 节点 | 6,949 |
| 关系总数 | **53,666** |
| 节点类型 | POI / 商圈 / 区县 / 粗类 / 细类 / 连锁品牌 / 价格带 / 评分档(8 类) |
| 关系类型 | 位于 / 位于商圈 / 属于品类 / 属于细类 / 子类 / 连锁品牌 / 价位 / 评分档 / 邻近 / 主营 / 属于区县(11 种) |
| 商圈(坐标聚类) | 78 |
| 商家邻近关系 | 14,650(真实地理距离 < 300m) |
| 连锁品牌 | 303 |

## 流程

```
高德API采集 → 清洗/实体对齐 → 图谱增强(商圈聚类/分层/邻近) → Neo4j 入库 → 可视化/问答
```

## 目录

- `src/collect_poi.py` — 按区县 × 品类采集 POI
- `src/clean_normalize.py` — 清洗、品类归一、实体对齐
- `src/enrich_graph.py` — 图谱增强(商圈聚类、价格/评分分层、邻近关系)
- `src/load_neo4j.py` — 导入 Neo4j
- `src/qa.py` — 知识图谱问答(规则解析版)
- `src/llm_qa.py` — LLM 增强问答(DeepSeek Text2Cypher + 答案生成)
- `src/theme.py` — 液态玻璃 UI 主题(CSS 注入)
- `src/hero.py` — 首屏 Hero(数字滚动 + 节点网络动画)
- `src/map_viz.py` — ECharts 地图可视化(区县密度/商家散点)
- `src/graph_data.py` — 可视化用子图抽取
- `src/viz.py` — ECharts 可视化组件
- `cypher/queries.cypher` — 典型查询
- `scripts/` — WSL 下 Neo4j 部署与运维脚本
- `static/` — 前端库(ECharts,本地化避免 CDN 依赖)

## 使用

```bash
pip install -r requirements.txt
python src/collect_poi.py       # 采集(key 放 amap_key.txt)
python src/clean_normalize.py   # 清洗
NEO4J_PASSWORD=wlcb123456 python src/load_neo4j.py   # 入库
python src/enrich_graph.py      # 图谱增强(需 Neo4j 运行)
python src/qa.py                # 规则问答(交互模式)
python src/llm_qa.py "推荐几家高分蒙餐馆"   # LLM 问答(需 deepseek_key.txt)
python run_demo.py              # 网页 Demo
```

## Neo4j 启动(WSL)

```bash
wsl -d Ubuntu -- bash "/mnt/d/Ai_model project/WLCB/scripts/start_neo4j.sh" start
```

浏览器打开 http://localhost:7474(neo4j / wlcb123456),Python 连 `bolt://localhost:7687`。

## 本体

节点:POI、商圈、行政区、粗类、细类、连锁品牌、价格带、评分档
关系:`位于`(POI→区县)、`位于商圈`、`属于品类`、`属于细类`、`子类`、
`连锁品牌`、`价位`、`评分档`、`邻近`(带真实距离属性)、`主营`、`属于区县`
属性:名称/地址/经纬度/评分/人均/营业时间/连锁标记

## 问答支持的问法

- 集宁区人均 50 以下的餐厅有哪些?
- 评分最高的蒙餐馆在哪?
- 四子王旗有什么景点?
- 肯德基在乌兰察布有几家店?
- 乌兰察布有多少家火锅店?
- 哪个区县餐厅最多?
