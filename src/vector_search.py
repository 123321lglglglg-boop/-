"""语义检索:用预计算的向量做相似度检索(方案 4.2)。

设计:
  - 向量在本地算好存成 npy,云端只加载+查询(Streamlit Cloud 内存只有 1GB)
  - 向量已 L2 归一化,点积即余弦相似度
  - 7000 条 × 1024 维的矩阵乘法在 CPU 上只需几毫秒
"""
import json
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import requests

BASE = Path(__file__).resolve().parent.parent
VEC_DIR = BASE / "data" / "vectors"
KEY_FILE = BASE / "siliconflow_key.txt"

EMBED_API = "https://api.siliconflow.cn/v1/embeddings"
EMBED_MODEL = "BAAI/bge-m3"

_cache = {"mat": None, "meta": None}


def get_key() -> str:
    key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        try:
            import streamlit as st
            key = str(st.secrets.get("SILICONFLOW_API_KEY", "")).strip()
        except Exception:
            pass
    return key


def load_index():
    """加载向量索引(进程内缓存)。"""
    if _cache["mat"] is not None:
        return _cache["mat"], _cache["meta"]

    npy = VEC_DIR / "embeddings.npy"
    meta_file = VEC_DIR / "meta.jsonl"
    if not npy.exists() or not meta_file.exists():
        return None, None

    mat = np.load(npy)
    meta = []
    with meta_file.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                meta.append(json.loads(line))

    _cache["mat"], _cache["meta"] = mat, meta
    return mat, meta


def embed_query(text: str, timeout: int = 20) -> list:
    """把查询文本转向量(单条,在线)。"""
    key = get_key()
    if not key:
        return []
    try:
        r = requests.post(
            EMBED_API,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": EMBED_MODEL, "input": text, "encoding_format": "float"},
            timeout=timeout,
        )
        if r.status_code != 200:
            return []
        return r.json()["data"][0]["embedding"]
    except Exception:
        return []


def semantic_search(query: str, top_k: int = 10) -> list:
    """语义检索:返回 [{poi_id, name, text, score, source}, …]。

    score 是余弦相似度(0~1,越高越相似)。
    """
    mat, meta = load_index()
    if mat is None or not meta:
        return []

    qv = embed_query(query)
    if not qv:
        return []

    q = np.asarray(qv, dtype="float32")
    n = np.linalg.norm(q)
    if n > 0:
        q = q / n

    # 归一化后的点积 = 余弦相似度
    scores = mat @ q
    k = min(top_k, len(scores))
    idx = np.argpartition(-scores, k - 1)[:k]
    idx = idx[np.argsort(-scores[idx])]

    out = []
    for i in idx:
        m = meta[int(i)]
        out.append({
            "poi_id": m.get("poi_id"),
            "name": m.get("name"),
            "text": m.get("text", ""),
            "score": float(scores[int(i)]),
            "source": "vector",
        })
    return out


def index_ready() -> bool:
    """检查向量索引是否就绪。"""
    return (VEC_DIR / "embeddings.npy").exists() and (VEC_DIR / "meta.jsonl").exists()


def index_info() -> dict:
    f = VEC_DIR / "index.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}
