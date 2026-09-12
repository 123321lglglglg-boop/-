"""推理路径的可视化渲染:液态玻璃风格的竖向路径链。"""


def render_paths_html(paths: list) -> str:
    """把路径数据渲染成 HTML(自包含样式,可嵌入 st.markdown)。

    paths: [{"start": 起点名, "steps": [{"from","rel","to","note"}, ...]}, ...]
    """
    if not paths:
        return ""

    blocks = []
    for pi, path in enumerate(paths):
        rows = []
        # 起点
        rows.append(f"""
        <div class="rp-node rp-start">
          <span class="rp-dot"></span>
          <span class="rp-name">{_esc(path['start'])}</span>
        </div>""")

        # 每一步:关系 + 目标节点
        for st in path["steps"]:
            note = f'<span class="rp-note">{_esc(st["note"])}</span>' if st.get("note") else ""
            rows.append(f"""
        <div class="rp-edge">
          <span class="rp-line"></span>
          <span class="rp-rel">{_esc(st['rel'])}</span>{note}
        </div>
        <div class="rp-node">
          <span class="rp-dot rp-dot-target"></span>
          <span class="rp-name">{_esc(st['to'])}</span>
        </div>""")

        label = f'<div class="rp-label">路径 {pi + 1}</div>' if len(paths) > 1 else ""
        blocks.append(f'<div class="rp-path">{label}{"".join(rows)}</div>')

    return f"""
<style>
.rp-wrap {{
  margin: 10px 0 4px;
  padding: 14px 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(255,255,255,0.07), rgba(255,255,255,0.025));
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  border: 1px solid rgba(255,255,255,0.12);
  box-shadow: 0 8px 28px rgba(2,6,23,0.42), inset 0 1px 0 rgba(255,255,255,0.15);
}}
.rp-title {{
  font-size: 12px; letter-spacing: 1.2px; text-transform: uppercase;
  color: #7dd3fc; margin-bottom: 12px; font-weight: 700;
}}
.rp-path {{
  display: flex; flex-direction: column;
  padding-left: 4px;
  margin-bottom: 14px;
}}
.rp-path:last-child {{ margin-bottom: 0; }}
.rp-label {{
  font-size: 11px; color: #8fa3bf; margin-bottom: 8px; letter-spacing: .6px;
}}
.rp-node {{
  display: flex; align-items: center; gap: 10px;
  padding: 7px 12px;
  border-radius: 12px;
  background: rgba(255,255,255,0.055);
  border: 1px solid rgba(255,255,255,0.09);
  transition: all .3s ease;
}}
.rp-node:hover {{
  background: rgba(125,211,252,0.12);
  border-color: rgba(125,211,252,0.35);
  transform: translateX(3px);
}}
.rp-start {{
  background: linear-gradient(120deg, rgba(56,189,248,0.20), rgba(168,85,247,0.20));
  border-color: rgba(125,211,252,0.38);
  box-shadow: 0 4px 18px rgba(56,189,248,0.18);
}}
.rp-dot {{
  width: 9px; height: 9px; border-radius: 50%; flex: 0 0 9px;
  background: linear-gradient(135deg, #7dd3fc, #c4b5fd);
  box-shadow: 0 0 10px rgba(125,211,252,0.75);
}}
.rp-dot-target {{
  background: rgba(148,163,184,0.85);
  box-shadow: 0 0 8px rgba(148,163,184,0.5);
  width: 7px; height: 7px; flex: 0 0 7px;
}}
.rp-name {{ font-size: 13.5px; color: #e8eef7; font-weight: 600; }}

.rp-edge {{
  display: flex; align-items: center; gap: 8px;
  padding: 5px 0 5px 14px;
}}
.rp-line {{
  width: 2px; height: 22px; flex: 0 0 2px;
  background: linear-gradient(to bottom, rgba(125,211,252,0.65), rgba(168,85,247,0.45));
  border-radius: 2px;
  position: relative;
}}
.rp-line::after {{
  content: '';
  position: absolute; bottom: -1px; left: 50%;
  transform: translateX(-50%);
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid rgba(168,85,247,0.55);
}}
.rp-rel {{
  font-size: 11.5px; color: #a5b4fc;
  background: rgba(99,102,241,0.16);
  border: 1px solid rgba(129,140,248,0.28);
  padding: 2px 9px; border-radius: 8px;
  font-weight: 600; letter-spacing: .3px;
}}
.rp-note {{
  font-size: 11px; color: #94a3b8;
}}
</style>
<div class="rp-wrap">
  <div class="rp-title">🔍 推理路径</div>
  {"".join(blocks)}
</div>
"""


def _esc(s) -> str:
    """HTML 转义,避免商家名里的特殊字符破坏结构。"""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
