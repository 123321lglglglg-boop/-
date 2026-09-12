"""Multi-Query 检索过程展示:让用户看到问题被拆成了哪些角度。"""
import textwrap

from src.multi_query import pick


def render_multi_html(queries: list, results: list) -> str:
    """渲染多角度检索过程。

    queries: [{"intent":…, "cypher":…}, …]
    results: [{"intent":…, "records":[…], "error":…}, …]
    """
    if not queries:
        return ""

    by_intent = {r["intent"]: r for r in results}
    items = []
    for q in queries:
        intent = _esc(q.get("intent", ""))
        r = by_intent.get(q.get("intent"), {})
        recs = r.get("records") or []
        cnt = len(recs)
        samples = []
        for x in recs[:3]:
            name = pick(x, "名称")
            rating = pick(x, "评分")
            if name:
                samples.append(f"{_esc(name)}" + (f"({rating}分)" if rating else ""))
        sample_txt = "、".join(samples) if samples else "无结果"
        items.append(f"""<div class="mq-item"><div class="mq-head"><span class="mq-dot"></span><span class="mq-intent">{intent}</span><span class="mq-count">{cnt} 家</span></div><div class="mq-sample">{sample_txt}</div></div>""")

    return textwrap.dedent(f"""
<style>
.mq-wrap {{
  margin: 10px 0 4px;
  padding: 14px 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(168,85,247,0.07), rgba(255,255,255,0.02));
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  border: 1px solid rgba(168,85,247,0.20);
  box-shadow: 0 8px 28px rgba(2,6,23,0.42), inset 0 1px 0 rgba(255,255,255,0.13);
}}
.mq-title {{
  font-size: 12px; letter-spacing: 1.2px; text-transform: uppercase;
  color: #c4b5fd; margin-bottom: 6px; font-weight: 700;
}}
.mq-hint {{ font-size: 11.5px; color: #94a3b8; margin-bottom: 12px; line-height: 1.5; }}
.mq-item {{
  padding: 9px 12px; margin-bottom: 8px; border-radius: 12px;
  background: rgba(255,255,255,0.045);
  border: 1px solid rgba(255,255,255,0.08);
  transition: all .3s ease;
}}
.mq-item:last-child {{ margin-bottom: 0; }}
.mq-item:hover {{
  background: rgba(168,85,247,0.12);
  border-color: rgba(196,181,253,0.32);
  transform: translateX(3px);
}}
.mq-head {{ display: flex; align-items: center; gap: 8px; }}
.mq-dot {{
  width: 7px; height: 7px; border-radius: 50%; flex: 0 0 7px;
  background: linear-gradient(135deg, #c4b5fd, #f0abfc);
  box-shadow: 0 0 9px rgba(196,181,253,0.7);
}}
.mq-intent {{ font-size: 13px; color: #e8eef7; font-weight: 600; }}
.mq-count {{
  margin-left: auto; font-size: 11px; color: #c4b5fd;
  background: rgba(168,85,247,0.18); padding: 1px 8px; border-radius: 7px;
  border: 1px solid rgba(196,181,253,0.25);
}}
.mq-sample {{ font-size: 11.5px; color: #94a3b8; margin-top: 4px; line-height: 1.5; }}
</style>
<div class="mq-wrap"><div class="mq-title">🔎 多角度检索</div><div class="mq-hint">你的问题比较宽泛,我拆成了 {len(queries)} 个角度分别检索:</div>{"".join(items)}</div>
""").strip()


def _esc(s) -> str:
    return (str(s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
