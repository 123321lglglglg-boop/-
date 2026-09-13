"""GraphRAG 检索路径展示:让用户看到问题走了哪条检索通道。

注意:这里展示的必须是真实执行的流程。之前这个文件写的是
"RRF 倒数排名融合 → LLM 精排取 Top-5",但线上 hybrid 路由走的是
图谱优先+向量补位的去重合并(src/hybrid_retrieval.py 的 _merge_kg_vec),
既没有 RRF 也没有 LLM 精排——展示和执行不一致,面试一问就穿。
现在改成按真实合并逻辑描述。
"""
import textwrap


def render_route_html(route_info: dict) -> str:
    """渲染双引擎检索路径。

    route_info: {"route": "semantic|hybrid|structured",
                 "kg_count": n, "vec_count": m, "merged_count": k}
    """
    route = route_info.get("route", "")
    kg_n = route_info.get("kg_count", 0)
    vec_n = route_info.get("vec_count", 0)
    merged_n = route_info.get("merged_count") or (kg_n + vec_n)

    if route == "semantic":
        title = "语义检索通道"
        desc = ("你的问题偏主观/体验类,知识图谱的结构化查询难以覆盖,"
                "已启用语义向量检索(BGE-M3 编码 + 余弦相似度)")
        active = "vector"
    elif route == "hybrid":
        title = "双引擎并行"
        desc = ("你的问题既有结构化条件也有主观偏好,图谱查询与语义检索已并行执行,"
                "图谱结果优先、向量结果补位,按店名去重")
        active = "both"
    else:
        return ""

    def node(name, kind, count, on):
        cls = "rt-node rt-on" if on else "rt-node"
        cnt = f'<span class="rt-count">{count} 条</span>' if count else ""
        return f'<div class="{cls}"><span class="rt-dot rt-dot-{kind}"></span><span class="rt-name">{name}</span>{cnt}</div>'

    kg_on = active in ("both", "kg")
    vec_on = active in ("both", "vector")

    return textwrap.dedent(f"""
<style>
.rt-wrap {{
  margin: 10px 0 4px;
  padding: 14px 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(56,189,248,0.07), rgba(255,255,255,0.02));
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  border: 1px solid rgba(125,211,252,0.20);
  box-shadow: 0 8px 28px rgba(2,6,23,0.42), inset 0 1px 0 rgba(255,255,255,0.13);
}}
.rt-title {{
  font-size: 12px; letter-spacing: 1.2px; text-transform: uppercase;
  color: #7dd3fc; margin-bottom: 5px; font-weight: 700;
}}
.rt-desc {{ font-size: 11.5px; color: #94a3b8; margin-bottom: 12px; line-height: 1.55; }}
.rt-node {{
  display: flex; align-items: center; gap: 9px;
  padding: 9px 12px; margin-bottom: 6px; border-radius: 12px;
  background: rgba(255,255,255,0.035);
  border: 1px solid rgba(255,255,255,0.07);
  opacity: 0.42;
}}
.rt-on {{
  opacity: 1;
  background: rgba(125,211,252,0.09);
  border-color: rgba(125,211,252,0.26);
}}
.rt-dot {{
  width: 8px; height: 8px; border-radius: 50%; flex: 0 0 8px;
}}
.rt-dot-kg {{ background: #34d399; box-shadow: 0 0 9px rgba(52,211,153,0.7); }}
.rt-dot-vector {{ background: #f0abfc; box-shadow: 0 0 9px rgba(240,171,252,0.7); }}
.rt-name {{ font-size: 13px; color: #e8eef7; font-weight: 600; }}
.rt-count {{
  margin-left: auto; font-size: 11px; color: #7dd3fc;
  background: rgba(56,189,248,0.16); padding: 1px 8px; border-radius: 7px;
}}
.rt-merge {{
  margin-top: 8px; padding-top: 8px; border-top: 1px dashed rgba(255,255,255,0.10);
  font-size: 11.5px; color: #c4b5fd;
}}
</style>
<div class="rt-wrap">
  <div class="rt-title">🧭 检索路径 · {title}</div>
  <div class="rt-desc">{desc}</div>
  {node("知识图谱(结构化精确查询)", "kg", kg_n, kg_on)}
  {node("语义向量检索(BGE-M3 + 余弦相似度)", "vector", vec_n, vec_on)}
  {f'<div class="rt-merge">↓ 图谱取前 8 条优先 + 向量取前 5 条补位,按店名去重 → 最终 {merged_n} 条</div>' if active == "both" else ''}
</div>
""").strip()
