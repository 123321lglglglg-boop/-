"""联网信息源展示:让用户知道每条外部信息来自哪里。"""
import textwrap


def render_sources_html(web_results: list, weather_text: str = "") -> str:
    """渲染来源面板(玻璃风格卡片列表)。"""
    if not web_results and not weather_text:
        return ""

    rows = []

    # 天气来源(API 优先展示)
    if weather_text:
        first_line = weather_text.split("\n")[0][:80]
        rows.append(f"""<div class="src-item src-api"><div class="src-head"><span class="src-badge src-badge-api">API</span><span class="src-name">高德地图天气</span></div><div class="src-snippet">{_esc(first_line)}</div></div>""")

    # 联网搜索结果
    for r in web_results:
        rows.append(f"""<div class="src-item"><div class="src-head"><span class="src-badge">网页</span><span class="src-name">{_esc(r.get('source', '未知来源'))}</span></div><a class="src-title" href="{_esc(r.get('url', '#'))}" target="_blank" rel="noopener">{_esc(r.get('title', ''))}</a><div class="src-snippet">{_esc(r.get('snippet', '')[:140])}</div></div>""")

    html = f"""
<style>
.src-wrap {{
  margin: 10px 0 4px;
  padding: 14px 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(52,211,153,0.06), rgba(255,255,255,0.02));
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  border: 1px solid rgba(52,211,153,0.18);
  box-shadow: 0 8px 28px rgba(2,6,23,0.42), inset 0 1px 0 rgba(255,255,255,0.13);
}}
.src-head-title {{
  font-size: 12px; letter-spacing: 1.2px; text-transform: uppercase;
  color: #6ee7b7; margin-bottom: 12px; font-weight: 700;
}}
.src-item {{
  padding: 10px 12px;
  margin-bottom: 8px;
  border-radius: 12px;
  background: rgba(255,255,255,0.045);
  border: 1px solid rgba(255,255,255,0.08);
  transition: all .3s ease;
}}
.src-item:last-child {{ margin-bottom: 0; }}
.src-item:hover {{
  background: rgba(52,211,153,0.10);
  border-color: rgba(52,211,153,0.30);
  transform: translateX(3px);
}}
.src-api {{ border-color: rgba(125,211,252,0.25); }}
.src-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }}
.src-badge {{
  font-size: 10px; padding: 1px 7px; border-radius: 6px;
  background: rgba(148,163,184,0.20); color: #cbd5e1;
  border: 1px solid rgba(148,163,184,0.28); font-weight: 600;
}}
.src-badge-api {{
  background: rgba(56,189,248,0.20); color: #7dd3fc;
  border-color: rgba(125,211,252,0.35);
}}
.src-name {{ font-size: 12.5px; color: #6ee7b7; font-weight: 700; }}
.src-title {{
  display: block; font-size: 13px; color: #e2e8f0; text-decoration: none;
  font-weight: 600; margin-bottom: 3px; line-height: 1.45;
}}
.src-title:hover {{ color: #7dd3fc; text-decoration: underline; }}
.src-snippet {{ font-size: 11.5px; color: #94a3b8; line-height: 1.5; }}
</style>
<div class="src-wrap"><div class="src-head-title">📡 信息来源</div>{"".join(rows)}</div>
"""
    # 去掉缩进:Markdown 会把 4 空格缩进当成代码块,导致 HTML 被显示成纯文本
    return textwrap.dedent(html).strip()


def _esc(s) -> str:
    return (str(s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
