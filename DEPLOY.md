# 公网部署(已完成大部分,剩余最后一步)

## 当前状态

| 项目 | 状态 |
|---|---|
| Neo4j Aura 云数据库 | 已完成 — `neo4j+s://fd355fed.databases.neo4j.io` |
| 数据迁移 | 已完成 — 7,507 节点 / 53,700 关系,与本地完全一致 |
| GitHub 仓库 | 已完成 — `https://github.com/123321lglglglg-boop/-` |
| 代码推送 | 已完成 |
| **Streamlit Cloud 部署** | **待完成(见下)** |

---

## 最后一步:Streamlit Cloud 部署

1. 打开 https://share.streamlit.io,用 **GitHub 账号**登录(可能需要代理)

2. 点 **Create app** / **New app**,表单这样填:

| 字段 | 填写内容 |
|---|---|
| Repository | `123321lglglglg-boop/-` |
| Branch | `main` |
| Main file path | `app.py` |
| App URL | 自定义,如 `ulanqab-kg` |

3. 展开 **Advanced settings**,在 **Secrets** 框里粘贴以下内容(把三个值换成真实的):

```toml
DEEPSEEK_API_KEY = "sk-你的DeepSeek密钥"

NEO4J_URI = "neo4j+s://fd355fed.databases.neo4j.io"
NEO4J_USER = "fd355fed"
NEO4J_PASSWORD = "你的Aura密码"
```

> 真实值在本地 `aura_creds.txt` 和 `deepseek_key.txt` 里(这两个文件已加入 .gitignore,不会上传 GitHub)。
> ⚠️ 不要把真实密钥写进任何会被提交的文件——GitHub 的推送保护会自动拦截。

4. 点 **Deploy**,等 2-3 分钟

5. 得到公网链接,形如 `https://你的名字.streamlit.app`

---

## 手机装成 App

**iPhone(Safari 打开链接):**
分享按钮 → 添加到主屏幕 → 主屏图标点开即全屏 App

**Android(Chrome):**
右上角菜单 → 添加到主屏幕 / 安装应用

---

## 注意事项

- **Aura 免费实例会自动休眠**:长时间无访问后首次打开需等约 10 秒唤醒。面试演示前先打开一次预热
- **LLM 限流**:已内置(每会话每分钟 8 次、每天 120 次),防止 API key 被刷
- **修改代码后**:`git add -A && git commit -m "..." && git push`,Streamlit Cloud 会自动重新部署
- **数据更新后**:本地跑完 `load_neo4j.py` + `enrich_graph.py`,再执行
  ```
  python scripts/migrate_to_aura.py "neo4j+s://fd355fed.databases.neo4j.io" "fd355fed" "密码"
  ```
  注意第三个参数是**用户名**(Aura 免费实例的用户名是实例 ID,不是默认的 neo4j)

## 本地开发

不受影响:不配置 secrets 时自动连本地 `bolt://localhost:7687`。
