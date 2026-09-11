"""统一配置读取:环境变量 > Streamlit secrets > 本地默认值。

本地开发不配置任何东西 → 连本地 Neo4j;
云端部署(Streamlit Cloud Secrets)→ 连 Neo4j Aura。
"""
import os


def get_config(key: str, default: str = "") -> str:
    v = os.environ.get(key, "").strip()
    if not v:
        try:
            import streamlit as st
            v = str(st.secrets.get(key, "")).strip()
        except Exception:
            pass
    return v or default


def neo4j_config() -> tuple:
    """返回 (uri, auth)。"""
    uri = get_config("NEO4J_URI", "bolt://localhost:7687")
    user = get_config("NEO4J_USER", "neo4j")
    password = get_config("NEO4J_PASSWORD", "wlcb123456")
    return uri, (user, password)
