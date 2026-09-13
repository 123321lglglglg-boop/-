"""ECharts 知识图谱可视化组件(深色炫酷主题)。

用法:
    from src.viz import graph_html
    st.iframe(graph_html(...), height=650)
"""
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent.parent
ECHARTS_JS = BASE / "static" / "echarts.min.js"

# 节点类型 → (颜色, 大小, 形状)
TYPE_STYLE = {
    "POI":        ("#38bdf8", 8,  "circle"),
    "BusinessArea": ("#fbbf24", 26, "roundRect"),
    "District":   ("#f472b6", 40, "diamond"),
    "Chain":      ("#a78bfa", 18, "circle"),
    "CategoryL3": ("#34d399", 16, "circle"),
    "CategoryL1": ("#059669", 28, "roundRect"),
    "PriceLevel": ("#f97316", 22, "roundRect"),
    "RatingTier": ("#eab308", 20, "roundRect"),
    "Dish":       ("#fb7185", 18, "circle"),
}

EDGE_LABEL = {
    "位于": "位于",
    "属于细类": "属于细类",
    "属于品类": "属于品类",
    "连锁品牌": "连锁品牌",
    "位于商圈": "位于商圈",
    "价位": "价位",
    "评分档": "评分档",
    "邻近": "邻近",
    "主营": "主营",
    "子类": "子类",
    "属于区县": "属于区县",
}


def _load_echarts() -> str:
    return ECHARTS_JS.read_text(encoding="utf-8")


def graph_html(nodes, edges, height=680, title="知识图谱", categories=None):
    """生成 ECharts 力导向图的完整 HTML。

    nodes: [{"id", "name", "type", "value", "info"}]  value=节点大小权重
    edges: [{"source", "target", "type", "label"}]   type 对应 EDGE_LABEL
    """
    cats = categories or [t for t in TYPE_STYLE]
    cat_index = {t: i for i, t in enumerate(cats)}

    echarts_nodes = []
    for n in nodes:
        t = n.get("type", "POI")
        color, size, symbol = TYPE_STYLE.get(t, ("#94a3b8", 8, "circle"))
        echarts_nodes.append({
            "id": str(n["id"]),
            "name": str(n["name"]),
            "symbolSize": n.get("value") or size,
            "symbol": symbol,
            "category": cat_index.get(t, 0),
            "itemStyle": {
                "color": color,
                "shadowBlur": 12 if t != "POI" else 4,
                "shadowColor": color,
            },
            "label": {"show": t != "POI", "fontSize": 12, "color": "#e5e7eb"},
            "value": n.get("info", t),
        })

    echarts_edges = []
    for e in edges:
        t = e.get("type", "")
        echarts_edges.append({
            "source": str(e["source"]),
            "target": str(e["target"]),
            "value": EDGE_LABEL.get(t, t),
            "lineStyle": {"curveness": 0.12},
            "label": {"show": False},
        })

    cats_data = [{"name": c, "itemStyle": {"color": TYPE_STYLE.get(c, ("#94a3b8",))[0]}} for c in cats]

    option = {
        "backgroundColor": "transparent",
        "title": {
            "text": title,
            "textStyle": {"color": "#f1f5f9", "fontSize": 16, "fontWeight": 600},
            "left": "center", "top": 8,
        },
        "tooltip": {
            "backgroundColor": "rgba(15,23,42,0.92)",
            "borderColor": "rgba(125,211,252,0.35)",
            "borderWidth": 1,
            "textStyle": {"color": "#e2e8f0", "fontSize": 12},
            "formatter": "{b}<br/>{c}",
            "extraCssText": "backdrop-filter: blur(14px); border-radius: 12px; box-shadow: 0 8px 26px rgba(2,6,23,0.5);",
        },
        "legend": {
            "data": [c["name"] for c in cats_data],
            "textStyle": {"color": "#cbd5e1"},
            "top": 36, "left": "center",
            "itemWidth": 14, "itemHeight": 10,
            "backgroundColor": "rgba(255,255,255,0.05)",
            "borderColor": "rgba(255,255,255,0.12)",
            "borderWidth": 1,
            "borderRadius": 12,
            "padding": [8, 14],
        },
        "series": [{
            "type": "graph",
            "layout": "force",
            "roam": True,
            "draggable": True,
            "data": echarts_nodes,
            "links": echarts_edges,
            "categories": cats_data,
            "force": {
                "repulsion": 320,
                "edgeLength": [60, 160],
                "gravity": 0.08,
                "friction": 0.15,
                "layoutAnimation": True,
            },
            "emphasis": {
                "focus": "adjacency",
                "lineStyle": {"width": 3, "color": "#f8fafc"},
                "label": {"show": True},
            },
            "lineStyle": {"color": "#334155", "width": 1, "opacity": 0.6},
            "label": {"position": "right", "formatter": "{b}"},
            "labelLayout": {"hideOverlap": True},
            "scaleLimit": {"min": 0.3, "max": 8},
        }],
        "animationDuration": 1200,
        "animationEasingUpdate": "quinticInOut",
    }

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{
    margin: 0; padding: 0;
    background:
      radial-gradient(ellipse at 22% 26%, rgba(56,189,248,0.16), transparent 52%),
      radial-gradient(ellipse at 76% 22%, rgba(168,85,247,0.15), transparent 54%),
      radial-gradient(ellipse at 58% 84%, rgba(244,114,182,0.11), transparent 56%),
      #070b14;
  }}
  #main {{ width: 100%; height: {height}px; }}
</style>
<script>{_load_echarts()}</script>
</head>
<body>
<div id="main"></div>
<script>
  var chart = echarts.init(document.getElementById('main'), null, {{renderer: 'canvas'}});
  var option = {json.dumps(option, ensure_ascii=False)};
  chart.setOption(option);
  window.addEventListener('resize', function() {{ chart.resize(); }});
</script>
</body>
</html>"""
