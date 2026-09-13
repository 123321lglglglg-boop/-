"""对比分析(文档《KG项目优化文档》第二部分 5)。

用户问「集宁区和四子王旗的餐饮对比」→ 自动生成对比表 + 柱状图。

支持对比的维度(都在图谱里有真实数据):
  - 区县 vs 区县(District)
  - 细类 vs 细类(CategoryL3)
  - 商圈 vs 商圈(BusinessArea)

识别方式说明:
  一开始用正则 `(.+?)和(.+?)的(.+?)对比` 切分,结果把「四子王旗」切成了
  「四」+「子王旗的餐饮」——中文实体名没有词边界,非贪婪量词在这里完全不靠谱。
  改成拿图谱里真实的区县/细类/商圈名单去做子串匹配:
  一句话里出现了同一类的两个真实实体,才算对比意图。既准确又不用调正则。
"""
import re
import time
import warnings

warnings.filterwarnings("ignore")

from src.db import run_cypher

# 对比意图的触发词
TRIGGERS = ("对比", "相比", "比较", "vs", "VS", "Vs")

# 实体类型:(标签, 中文名, 指回 POI 的关系)
ENTITY_TYPES = [
    ("District", "区县", "位于"),
    ("CategoryL3", "细类", "属于细类"),
    ("BusinessArea", "商圈", "位于商圈"),
]

_NAME_CACHE = {"ts": 0.0, "data": {}}
_NAME_TTL = 600


def _all_names() -> dict:
    """取三类实体的全部名称(进程内缓存 10 分钟,避免每次问都查三遍库)。"""
    if _NAME_CACHE["data"] and time.time() - _NAME_CACHE["ts"] < _NAME_TTL:
        return _NAME_CACHE["data"]
    data = {}
    for label, kind, rel in ENTITY_TYPES:
        try:
            rows = run_cypher(f"MATCH (n:{label}) RETURN n.name AS name")
            data[label] = sorted({r["name"] for r in rows if r.get("name")},
                                 key=len, reverse=True)
        except Exception:
            data[label] = []
    _NAME_CACHE["data"] = data
    _NAME_CACHE["ts"] = time.time()
    return data


def parse_compare(query: str) -> dict:
    """识别对比意图。返回 {"a","b","label","kind"} 或 None。

    判定标准:问题里出现对比触发词,且同一类实体里出现了两个不同的真实名称。
    只在问题里出现一个实体(比如"集宁区怎么样")不算对比。
    """
    q = (query or "").strip()
    if not q or not any(t in q for t in TRIGGERS):
        return None

    names = _all_names()
    for label, kind, _rel in ENTITY_TYPES:
        hit = [n for n in names.get(label, []) if n in q]
        if len(hit) >= 2:
            return {"a": hit[0], "b": hit[1], "label": label, "kind": kind}
    return None


def compare_stats(a: str, b: str, label: str = "") -> dict:
    """统计两个实体在商家数/平均评分/平均人均上的差异。

    label 由 parse_compare 给出(两边必是同一类实体,否则对比没有意义)。
    返回 {"kind","a","b","rows":[{名称,商家数,平均评分,平均人均}]} 或 {}
    """
    rel = {lbl: r for lbl, _k, r in ENTITY_TYPES}
    kind = {lbl: k for lbl, k, _r in ENTITY_TYPES}.get(label, "")
    if not label or label not in rel:
        return {}

    cypher = f"""
    UNWIND $names AS nm
    MATCH (n:{label} {{name: nm}})<-[:{rel[label]}]-(p:POI)
    RETURN nm AS 名称,
           count(p) AS 商家数,
           round(avg(p.rating) * 100) / 100 AS 平均评分,
           round(avg(CASE WHEN p.cost > 0 THEN p.cost END)) AS 平均人均
    """
    try:
        rows = run_cypher(cypher, names=[a, b])
    except Exception:
        return {}
    if len(rows) < 2:
        return {}
    return {"kind": kind, "a": a, "b": b, "rows": rows}


def render_compare_html(info: dict) -> str:
    """把对比结果渲染成一张卡片(表 + 横向条形图),与其余可视化同一套风格。"""
    if not info or len(info.get("rows") or []) < 2:
        return ""
    rows = info["rows"]
    colors = ["#38bdf8", "#f0abfc"]
    metrics = [("商家数", "#7dd3fc"), ("平均评分", "#c4b5fd"), ("平均人均", "#f9a8d4")]

    cells = []
    for i, r in enumerate(rows):
        cells.append(
            f"<div class='cp-col' style='--c:{colors[i % 2]}'>"
            f"<div class='cp-name'>{_esc(r.get('名称'))}</div>"
            f"<div class='cp-num'>{r.get('商家数', 0)}<span>家</span></div>"
            f"<div class='cp-sub'>平均评分 {r.get('平均评分') or '—'} · "
            f"平均人均 {r.get('平均人均') or '—'} 元</div>"
            "</div>"
        )

    # 横向条形图:每个指标下,两个实体按占比画条
    bars = []
    for label, color in metrics:
        vals = []
        for r in rows:
            v = r.get(label)
            try:
                vals.append(float(v) if v is not None else 0.0)
            except (TypeError, ValueError):
                vals.append(0.0)
        mx = max(vals) or 1.0
        segs = []
        for i, r in enumerate(rows):
            w = max(2.0, vals[i] / mx * 100)
            segs.append(
                f"<div class='cp-bar-row'>"
                f"<span class='cp-bar-label'>{_esc(r.get('名称'))}</span>"
                f"<span class='cp-bar-track'>"
                f"<span class='cp-bar-fill' style='width:{w:.1f}%;"
                f"background:linear-gradient(90deg,{colors[i % 2]},{colors[i % 2]}88)'></span>"
                f"</span>"
                f"<span class='cp-bar-val'>{vals[i]:.2f}</span>"
                f"</div>"
            )
        bars.append(
            f"<div class='cp-metric'><div class='cp-metric-name' style='color:{color}'>"
            f"{label}</div>{''.join(segs)}</div>"
        )

    kind = info.get("kind", "")
    return f"""
<style>
.cp-wrap {{
  margin: 10px 0 4px; padding: 14px 16px; border-radius: 18px;
  background: linear-gradient(135deg, rgba(56,189,248,0.07), rgba(255,255,255,0.02));
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  border: 1px solid rgba(125,211,252,0.20);
  box-shadow: 0 8px 28px rgba(2,6,23,0.42), inset 0 1px 0 rgba(255,255,255,0.13);
}}
.cp-title {{
  font-size: 12px; letter-spacing: 1.2px; text-transform: uppercase;
  color: #7dd3fc; margin-bottom: 12px; font-weight: 700;
}}
.cp-grid {{ display: flex; gap: 10px; margin-bottom: 14px; }}
.cp-col {{
  flex: 1; padding: 11px 13px; border-radius: 13px;
  background: rgba(255,255,255,0.045);
  border: 1px solid color-mix(in srgb, var(--c) 35%, transparent);
}}
.cp-name {{ font-size: 13.5px; color: #e8eef7; font-weight: 700; }}
.cp-num {{ font-size: 24px; color: var(--c); font-weight: 800; margin: 4px 0 2px; }}
.cp-num span {{ font-size: 12px; color: #8fa3bf; font-weight: 500; margin-left: 3px; }}
.cp-sub {{ font-size: 11.5px; color: #94a3b8; }}
.cp-metric {{ margin-bottom: 12px; }}
.cp-metric-name {{ font-size: 11.5px; font-weight: 700; margin-bottom: 6px; }}
.cp-bar-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }}
.cp-bar-label {{
  width: 96px; flex: 0 0 96px; font-size: 11.5px; color: #cbd5e1;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.cp-bar-track {{
  flex: 1; height: 9px; border-radius: 5px; background: rgba(255,255,255,0.07);
  overflow: hidden;
}}
.cp-bar-fill {{ display: block; height: 100%; border-radius: 5px; }}
.cp-bar-val {{ width: 52px; text-align: right; font-size: 11.5px; color: #7dd3fc; }}
</style>
<div class="cp-wrap">
  <div class="cp-title">📊 {_esc(kind)}对比 · {_esc(info.get('a'))} vs {_esc(info.get('b'))}</div>
  <div class="cp-grid">{''.join(cells)}</div>
  {''.join(bars)}
</div>
"""


def _esc(s) -> str:
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
