"""向量检索方案对比实验: numpy 暴力检索 vs Chroma 向量库。

产出选型依据(面试素材)。
"""
import json
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np

BASE = Path(__file__).resolve().parent.parent
VEC_DIR = BASE / "data" / "vectors"
N_QUERIES = 20
TOP_K = 10


def load_data():
    mat = np.load(VEC_DIR / "embeddings.npy")
    meta = []
    with (VEC_DIR / "meta.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                meta.append(json.loads(line))
    return mat, meta


def bench_numpy(mat, queries):
    """numpy 暴力检索。"""
    times = []
    for q in queries:
        t0 = time.time()
        scores = mat @ q
        idx = np.argpartition(-scores, TOP_K - 1)[:TOP_K]
        idx = idx[np.argsort(-scores[idx])]
        times.append((time.time() - t0) * 1000)
    return times


def bench_chroma(mat, meta, queries, persist_dir):
    """Chroma 向量库检索。"""
    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=str(persist_dir),
        settings=Settings(anonymized_telemetry=False),
    )
    name = "poi_bench"

    # 建库耗时
    t0 = time.time()
    try:
        client.delete_collection(name)
    except Exception:
        pass
    col = client.create_collection(name, metadata={"hnsw:space": "cosine"})
    batch = 1000
    for i in range(0, len(mat), batch):
        col.add(
            ids=[meta[j]["poi_id"] for j in range(i, min(i + batch, len(mat)))],
            embeddings=[mat[j].tolist() for j in range(i, min(i + batch, len(mat)))],
        )
    build_s = time.time() - t0

    # 查询耗时
    times = []
    for q in queries:
        t0 = time.time()
        col.query(query_embeddings=[q.tolist()], n_results=TOP_K)
        times.append((time.time() - t0) * 1000)

    return times, build_s


def main():
    print("=" * 56)
    print("向量检索方案对比:numpy vs Chroma")
    print("=" * 56)

    mat, meta = load_data()
    print(f"\n数据:{mat.shape[0]} 条 × {mat.shape[1]} 维")

    # 准备查询向量(用真实向量的扰动,更接近真实分布)
    rng = np.random.default_rng(7)
    idxs = rng.choice(len(mat), N_QUERIES, replace=False)
    queries = []
    for i in idxs:
        q = mat[i] + rng.standard_normal(mat.shape[1]).astype("float32") * 0.15
        q = q / np.linalg.norm(q)
        queries.append(q)

    # ---- numpy ----
    print(f"\n【方案 A:numpy 暴力检索】")
    t_load = time.time()
    _ = mat @ queries[0]
    load_ms = (time.time() - t_load) * 1000
    np_times = bench_numpy(mat, queries)
    print(f"  加载/预热: {load_ms:.1f} ms")
    print(f"  内存占用:  {mat.nbytes / 1048576:.1f} MB")
    print(f"  平均检索:  {np.mean(np_times):.2f} ms  (P95: {np.percentile(np_times, 95):.2f} ms)")
    print(f"  依赖数量:  0(标准科学计算栈)")

    # ---- Chroma ----
    print(f"\n【方案 B:Chroma 向量库】")
    try:
        import shutil
        persist = BASE / "data" / "vectors" / ".chroma_bench"
        if persist.exists():
            shutil.rmtree(persist)
        t0 = time.time()
        ch_times, build_s = bench_chroma(mat, meta, queries, persist)
        setup_s = time.time() - t0 - build_s
        size_mb = sum(f.stat().st_size for f in persist.rglob("*") if f.is_file()) / 1048576
        print(f"  建库耗时:  {build_s:.1f} s")
        print(f"  磁盘占用:  {size_mb:.1f} MB")
        print(f"  平均检索:  {np.mean(ch_times):.2f} ms  (P95: {np.percentile(ch_times, 95):.2f} ms)")
        print(f"  依赖数量:  chromadb + 约 20 个传递依赖")
        shutil.rmtree(persist, ignore_errors=True)
    except Exception as e:
        ch_times = None
        print(f"  实验失败: {str(e)[:120]}")

    # ---- 结论 ----
    print("\n" + "=" * 56)
    print("结论")
    print("=" * 56)
    if ch_times:
        np_avg, ch_avg = np.mean(np_times), np.mean(ch_times)
        if np_avg < ch_avg:
            print(f"  检索速度: numpy 快 {ch_avg / np_avg:.1f} 倍({np_avg:.2f}ms vs {ch_avg:.2f}ms)")
        else:
            print(f"  检索速度: Chroma 快 {np_avg / ch_avg:.1f} 倍({ch_avg:.2f}ms vs {np_avg:.2f}ms)")
    print(f"  numpy: 零额外依赖、无需建库、启动即用")
    print(f"  Chroma: 需建库 {build_s if ch_times else 0:.1f}s + 约 20 个传递依赖")
    print(f"  当前规模(7000 条)下两者都能满足体验要求")
    print(f"  → 选型结论:用 numpy(更简单、更可控、面试可解释)")
    print(f"     若数据涨到百万级,再换向量库(ANN 索引的复杂度优势才显现)")


if __name__ == "__main__":
    main()
