"""批量向量化:调用硅基流动 API(BGE-M3),结果存本地文件。

为什么要提前算好:
  Streamlit Cloud 免费版只有 1GB 内存,装不下 BGE-M3 模型(2GB+),
  所以向量在本地算好、存成文件,云端只做查询不算向量。

产物:
  data/vectors/embeddings.npy   向量矩阵 (N, 1024) float32
  data/vectors/meta.jsonl       与向量一一对应的元数据
  data/vectors/index.json       索引信息(模型/维度/条数/生成时间)
"""
import json
import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import requests

BASE = Path(__file__).resolve().parent.parent
INPUT = BASE / "data" / "processed" / "poi_searchable.jsonl"
OUT_DIR = BASE / "data" / "vectors"
KEY_FILE = BASE / "siliconflow_key.txt"

API = "https://api.siliconflow.cn/v1/embeddings"
MODEL = "BAAI/bge-m3"
BATCH = 16          # 每批条数(API 限制)
SLEEP = 0.3         # 批间隔,避免限流


def get_key() -> str:
    key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    return key


def embed_batch(key: str, texts: list, retries: int = 3) -> list:
    """批量向量化一批文本,带重试。"""
    for attempt in range(retries):
        try:
            r = requests.post(
                API,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": MODEL, "input": texts, "encoding_format": "float"},
                timeout=60,
            )
            if r.status_code == 200:
                data = r.json()["data"]
                # 按 index 排序,保证顺序对应
                data.sort(key=lambda x: x["index"])
                return [d["embedding"] for d in data]
            if r.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"    限流,等待 {wait}s 后重试")
                time.sleep(wait)
                continue
            print(f"    API 错误 {r.status_code}: {r.text[:120]}")
        except Exception as e:
            print(f"    请求异常: {str(e)[:80]}")
        time.sleep(2 * (attempt + 1))
    return []


def main():
    if not INPUT.exists():
        print(f"缺少输入文件:{INPUT}")
        print("请先运行:python scripts/build_searchable.py")
        sys.exit(1)

    key = get_key()
    if not key:
        print("未配置 API key(siliconflow_key.txt 或 SILICONFLOW_API_KEY)")
        sys.exit(1)

    items = []
    with INPUT.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line))
    print(f"待向量化:{len(items)} 条")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 增量模式:已有向量 + 文本未变的直接复用(只重算文本变化的部分)
    existing = {}
    meta_file = OUT_DIR / "meta.jsonl"
    vec_file = OUT_DIR / "embeddings.npy"
    if meta_file.exists() and vec_file.exists():
        import numpy as _np
        _old = _np.load(vec_file)
        with meta_file.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if line.strip() and i < len(_old):
                    r = json.loads(line)
                    existing[r["poi_id"]] = {"text": r.get("text", ""), "vec": _old[i]}
        print(f"已加载现有向量:{len(existing)} 条")

    reuse = {}
    todo = []
    for it in items:
        e = existing.get(it["poi_id"])
        if e and e["text"] == it["text"]:
            reuse[it["poi_id"]] = e["vec"]
        else:
            todo.append(it)
    print(f"可复用:{len(reuse)} 条 | 需重算:{len(todo)} 条")

    ckpt = OUT_DIR / "embeddings_partial.jsonl"   # 断点续传(只针对本次重算的)

    done = {}
    if ckpt.exists():
        with ckpt.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    done[r["poi_id"]] = r["vec"]
        print(f"检测到断点,已完成 {len(done)} 条")

    todo = [it for it in items if it["poi_id"] not in done]
    if todo:
        with ckpt.open("a", encoding="utf-8") as f:
            t0 = time.time()
            for i in range(0, len(todo), BATCH):
                chunk = todo[i:i + BATCH]
                vecs = embed_batch(key, [c["text"] for c in chunk])
                if not vecs:
                    print(f"  第 {i // BATCH + 1} 批失败,跳过")
                    continue
                for c, v in zip(chunk, vecs):
                    done[c["poi_id"]] = v
                    f.write(json.dumps({"poi_id": c["poi_id"], "vec": v}, ensure_ascii=False) + "\n")
                f.flush()
                n_done = len(done)
                if (i // BATCH) % 10 == 0 or n_done == len(items):
                    elapsed = time.time() - t0
                    rate = (i + BATCH) / elapsed if elapsed > 0 else 0
                    eta = (len(todo) - i - BATCH) / rate if rate > 0 else 0
                    print(f"  进度 {n_done}/{len(items)} | {rate:.1f} 条/秒 | 预计剩余 {eta / 60:.1f} 分钟")
                time.sleep(SLEEP)

    # ---- 落盘为 numpy ----
    import numpy as np

    # 合并:复用的 + 本次计算的
    all_vecs = dict(reuse)
    all_vecs.update(done)

    valid = [it for it in items if it["poi_id"] in all_vecs]
    if not valid:
        print("没有成功的向量,退出")
        sys.exit(1)

    mat = np.array([all_vecs[it["poi_id"]] for it in valid], dtype="float32")
    # L2 归一化:之后用点积即余弦相似度
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1
    mat = mat / norms

    np.save(OUT_DIR / "embeddings.npy", mat)
    with (OUT_DIR / "meta.jsonl").open("w", encoding="utf-8") as f:
        for it in valid:
            f.write(json.dumps({
                "poi_id": it["poi_id"], "name": it["name"],
                "text": it["text"], "meta": it.get("meta", {}),
            }, ensure_ascii=False) + "\n")

    from datetime import datetime
    (OUT_DIR / "index.json").write_text(json.dumps({
        "model": MODEL, "dim": mat.shape[1], "count": int(mat.shape[0]),
        "normalized": True, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    size_mb = mat.nbytes / 1048576
    print()
    print(f"完成:{mat.shape[0]} 条 × {mat.shape[1]} 维")
    print(f"  向量文件:{OUT_DIR / 'embeddings.npy'} ({size_mb:.1f} MB)")
    print(f"  元数据:{OUT_DIR / 'meta.jsonl'}")
    if len(valid) < len(items):
        print(f"  注意:{len(items) - len(valid)} 条未成功向量化")


if __name__ == "__main__":
    main()
