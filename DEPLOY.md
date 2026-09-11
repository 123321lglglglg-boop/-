# 公网部署指南(手机可访问)

目标:得到一个**永久公网链接**,任何设备(手机/电脑)都能打开,可"添加到主屏幕"当 App 用。

## 架构

```
GitHub 仓库 → Streamlit Community Cloud(免费托管网页)
                    ↓ 连接
              Neo4j Aura Free(免费云图数据库,存 7507 节点/53666 关系)
                    ↓ 调用
              DeepSeek API(LLM 问答)
```

全部免费。你只需要注册三个账号。

---

## 第一步:Neo4j Aura Free(云图数据库,5 分钟)

1. 打开 https://neo4j.com/cloud/aura-free/ → Sign up(可用 Google/GitHub 登录)
2. 创建一个 **AuraDB Free** 实例(免费档:200,000 节点 / 400,000 关系,你的数据远低于此)
3. 创建时会**弹出一次密码**,立刻复制保存(关掉就再也看不到了)
4. 记下连接串,形如:`neo4j+s://xxxxxxxx.databases.neo4j.io`

**迁移数据**(本地 Neo4j 需在运行):

```bash
cd "D:/Ai_model project/WLCB"
python scripts/migrate_to_aura.py "neo4j+s://xxxx.databases.neo4j.io" "你的Aura密码"
```

跑完会打印云端校验的节点/关系数,和本地的 7507 / 53666 对上就成功。

---

## 第二步:GitHub 仓库(5 分钟)

1. 注册 https://github.com(如已有跳过)
2. 新建仓库,名字随意(如 `ulanqab-kg`),**设为 Public**(Streamlit Cloud 免费版要求公开仓库)
3. 在本地项目目录执行(把地址换成你的):

```bash
cd "D:/Ai_model project/WLCB"
git init
git add -A
git commit -m "乌兰察布知识图谱作品集"
git branch -M main
git remote add origin https://github.com/你的用户名/ulanqab-kg.git
git push -u origin main
```

---

## 第三步:Streamlit Cloud 部署(5 分钟)

1. 打开 https://share.streamlit.io → 用 GitHub 登录
2. New app → 选你的仓库 → Main file path 填 `app.py`
3. 点 **Advanced settings → Secrets**,粘贴(换成你的真实值):

```toml
DEEPSEEK_API_KEY = "sk-你的deepseek-key"
NEO4J_URI = "neo4j+s://xxxx.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "你的Aura密码"
```

4. 点 Deploy,等 2-3 分钟

完成后得到形如 `https://<你起的名字>.streamlit.app` 的**公网链接**。

---

## 第四步:手机装成 App

**iPhone(Safari):**
1. 用 Safari 打开上面那个链接
2. 点底部「分享」按钮 → 「添加到主屏幕」
3. 主屏出现图标,点开就是全屏 App(无浏览器地址栏)

**Android(Chrome):**
1. 打开链接 → 右上角菜单 → 「添加到主屏幕」/「安装应用」

---

## 注意事项

- **LLM key 保护**:代码已内置限流(每会话每分钟 8 次、每天 120 次),防止 key 被刷
- **Aura 免费实例会自动暂停**:长时间无访问会休眠,首次打开可能要等 10 秒唤醒(面试演示前先打开一次预热)
- **数据更新**:如重新采集了数据,在本地跑完 `load_neo4j.py` + `enrich_graph.py` 后,再跑一次 `migrate_to_aura.py` 覆盖云端即可
- **本地开发不受影响**:不配置 secrets 时,程序自动连本地 `bolt://localhost:7687`
