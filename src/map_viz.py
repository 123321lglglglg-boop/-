"""ECharts 地图可视化:乌兰察布区县分布 + 区县下钻联动。

总览视图:区县热力地图(点击区县下钻)
下钻视图:缩放到该区县 + 商家散点 + 统计面板(点"返回"回总览)
全部在浏览器端完成,点击零延迟。
"""
import json
import math
import warnings
from collections import defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent.parent
ECHARTS_JS = BASE / "static" / "echarts.min.js"
GEOJSON = BASE / "data" / "ulanqab_geo.json"

# 品类 → 颜色
CAT_COLORS = {
    "中餐厅": "#f97316", "快餐厅": "#fbbf24", "火锅店": "#ef4444",
    "宾馆酒店": "#3b82f6", "风景名胜": "#22c55e", "咖啡厅": "#a16207",
    "冷饮店": "#ec4899", "商场": "#a855f7", "KTV": "#8b5cf6",
    "酒吧": "#d946ef", "网吧": "#06b6d4", "电影院": "#facc15",
    "旅馆招待所": "#60a5fa", "综合酒楼": "#fb923c", "清真菜馆": "#10b981",
    "甜品店": "#f0abfc", "经济型连锁酒店": "#818cf8",
}


def _load_echarts() -> str:
    return ECHARTS_JS.read_text(encoding="utf-8")


def _load_geojson() -> dict:
    return json.loads(GEOJSON.read_text(encoding="utf-8"))


def _district_center(boundary: dict):
    """粗略计算区县中心点(用边界坐标平均值)。"""
    coords = []
    geom = boundary.get("geometry", {})
    def walk(c):
        if isinstance(c[0], (int, float)):
            coords.append(c)
        else:
            for x in c:
                walk(x)
    walk(geom.get("coordinates", []))
    if not coords:
        return None
    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return [sum(lngs) / len(lngs), sum(lats) / len(lats)]


def drilldown_map_html(pois, district_counts, height=640):
    """带下钻的地图。

    pois: [{"name","lng","lat","rating","cost","district","category"}]
    district_counts: {"集宁区": 875, ...}
    """
    geojson = _load_geojson()

    # 按区县分组商家
    by_district = defaultdict(list)
    for p in pois:
        if p["lng"] is None or p["lat"] is None:
            continue
        by_district[p["district"]].append({
            "name": p["name"],
            "value": [p["lng"], p["lat"], p.get("rating") or 0],
            "rating": p.get("rating"),
            "cost": p.get("cost"),
            "category": p.get("category"),
        })

    # 计算每个区县的统计与中心点
    geo_features = {f["properties"]["name"]: f for f in geojson["features"]}
    district_meta = {}
    for dname, items in by_district.items():
        ratings = [i["rating"] for i in items if i["rating"]]
        costs = [i["cost"] for i in items if i["cost"] and i["cost"] > 0]
        cats = defaultdict(int)
        for i in items:
            if i["category"]:
                cats[i["category"]] += 1
        top_cats = sorted(cats.items(), key=lambda x: -x[1])[:5]
        center = _district_center(geo_features[dname]) if dname in geo_features else None
        district_meta[dname] = {
            "count": len(items),
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "avg_cost": round(sum(costs) / len(costs)) if costs else None,
            "top_cats": top_cats,
            "center": center,
            "points": items,
        }

    data = [{"name": k, "value": v} for k, v in district_counts.items()]
    vmax = max(district_counts.values()) if district_counts else 1

    cat_color_js = json.dumps(CAT_COLORS, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin:0; padding:0; font-family:'Segoe UI','PingFang SC',sans-serif;
    background: radial-gradient(ellipse at 30% 30%, rgba(56,189,248,0.13), transparent 55%),
                radial-gradient(ellipse at 72% 70%, rgba(168,85,247,0.12), transparent 55%),
                #070b14; overflow:hidden; }}
  #wrap {{ position:relative; width:100%; height:{height}px; }}
  #main {{ width:100%; height:100%; }}

  /* 左侧统计面板 */
  #panel {{
    position:absolute; top:16px; left:16px; width:250px;
    padding:16px 18px; border-radius:18px;
    background: rgba(15,23,42,0.72);
    backdrop-filter: blur(20px) saturate(160%);
    -webkit-backdrop-filter: blur(20px) saturate(160%);
    border:1px solid rgba(125,211,252,0.30);
    box-shadow: 0 14px 44px rgba(2,6,23,0.55), inset 0 1px 0 rgba(255,255,255,0.14);
    color:#e2e8f0; z-index:10;
    opacity:0; transform: translateX(-16px); pointer-events:none;
    transition: all .45s cubic-bezier(.22,1,.36,1);
  }}
  #panel.show {{ opacity:1; transform: translateX(0); pointer-events:auto; }}
  #panel .dname {{
    font-size:19px; font-weight:800; margin-bottom:2px;
    background: linear-gradient(100deg,#7dd3fc,#c4b5fd,#f0abfc);
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
  }}
  #panel .sub {{ font-size:11px; color:#8fa3bf; letter-spacing:1px; margin-bottom:12px; }}
  #panel .row {{ display:flex; justify-content:space-between; align-items:baseline;
    padding:7px 0; border-bottom:1px solid rgba(255,255,255,0.07); font-size:13px; }}
  #panel .row:last-of-type {{ border-bottom:none; }}
  #panel .row .v {{ font-weight:700; color:#7dd3fc; font-variant-numeric:tabular-nums; }}
  #panel .cats {{ margin-top:10px; }}
  #panel .cats .t {{ font-size:11px; color:#8fa3bf; letter-spacing:1px; margin-bottom:6px; }}
  #panel .cat {{ display:flex; align-items:center; gap:7px; font-size:12px; padding:3px 0; color:#cbd5e1; }}
  #panel .cat .dot {{ width:8px; height:8px; border-radius:50%; flex:0 0 8px; }}
  #panel .cat .n {{ margin-left:auto; color:#94a3b8; font-variant-numeric:tabular-nums; }}

  #back {{
    display:none; margin-top:13px; width:100%; padding:9px 0;
    border-radius:11px; border:1px solid rgba(125,211,252,0.40);
    background: linear-gradient(120deg, rgba(56,189,248,0.30), rgba(168,85,247,0.30));
    color:#f1f5f9; font-weight:700; font-size:13px; cursor:pointer;
    transition: all .3s ease;
  }}
  #back:hover {{ transform:translateY(-1.5px);
    box-shadow:0 8px 24px rgba(56,189,248,0.35); border-color:rgba(125,211,252,0.7); }}
  #panel.show #back {{ display:block; }}

  /* 下钻后的着色切换 */
  #colorbar {{
    position:absolute; top:16px; right:16px; z-index:10;
    display:none; gap:7px;
  }}
  #colorbar.show {{ display:flex; }}
  #colorbar button {{
    padding:7px 13px; border-radius:11px; font-size:12px; cursor:pointer;
    background: rgba(15,23,42,0.72); backdrop-filter: blur(16px);
    border:1px solid rgba(255,255,255,0.16); color:#cbd5e1;
    transition: all .3s ease;
  }}
  #colorbar button:hover {{ border-color:rgba(125,211,252,0.5); color:#f1f5f9; }}
  #colorbar button.on {{
    background: linear-gradient(120deg, rgba(56,189,248,0.34), rgba(168,85,247,0.34));
    border-color:rgba(125,211,252,0.6); color:#fff; font-weight:700;
  }}

  #hint {{
    position:absolute; bottom:14px; left:50%; transform:translateX(-50%);
    font-size:12px; color:#8fa3bf; letter-spacing:.6px;
    background: rgba(15,23,42,0.6); padding:6px 16px; border-radius:999px;
    border:1px solid rgba(255,255,255,0.09); backdrop-filter: blur(12px);
    transition: opacity .4s ease; z-index:10;
  }}
</style>
<script>{_load_echarts()}</script>
</head><body>
<div id="wrap">
  <div id="main"></div>
  <div id="panel">
    <div class="dname" id="p-name"></div>
    <div class="sub">DISTRICT DETAIL</div>
    <div class="row"><span>商家总数</span><span class="v" id="p-count"></span></div>
    <div class="row"><span>平均评分</span><span class="v" id="p-rating"></span></div>
    <div class="row"><span>平均人均</span><span class="v" id="p-cost"></span></div>
    <div class="cats">
      <div class="t">品类 TOP5</div>
      <div id="p-cats"></div>
    </div>
    <button id="back">← 返回全区</button>
  </div>
  <div id="colorbar">
    <button data-mode="rating" class="on">按评分</button>
    <button data-mode="cost">按人均</button>
    <button data-mode="category">按品类</button>
  </div>
  <div id="hint">点击区县查看详情 · 滚轮缩放</div>
</div>
<script>
(function() {{
  var geo = {json.dumps(geojson, ensure_ascii=False)};
  var META = {json.dumps(district_meta, ensure_ascii=False)};
  var CAT_COLORS = {cat_color_js};
  echarts.registerMap('ulanqab', geo);

  var chart = echarts.init(document.getElementById('main'));
  var panel = document.getElementById('panel');
  var colorbar = document.getElementById('colorbar');
  var hint = document.getElementById('hint');
  var currentDistrict = null;
  var colorMode = 'rating';

  /* ---------- 纬度换算:用热度色带 ---------- */
  function heatColor(v, min, max, stops) {{
    if (v == null) return 'rgba(148,163,184,0.5)';
    var t = Math.max(0, Math.min(1, (v - min) / (max - min)));
    var seg = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)));
    return stops[seg + 1];
  }}

  function scatterPoints(mode) {{
    var pts = META[currentDistrict].points;
    return pts.map(function(p) {{
      var color;
      if (mode === 'category') {{
        color = CAT_COLORS[p.category] || '#94a3b8';
      }} else if (mode === 'cost') {{
        var c = p.cost || 0;
        color = c <= 30 ? '#67e8f9' : c <= 60 ? '#38bdf8' : c <= 120 ? '#a855f7' : '#f472b6';
      }} else {{
        var r = p.rating || 0;
        color = r >= 4.5 ? '#34d399' : r >= 4.0 ? '#fbbf24' : r > 0 ? '#f87171' : '#64748b';
      }}
      return {{
        name: p.name,
        value: p.value,
        itemStyle: {{ color: color, borderColor: 'rgba(255,255,255,0.55)', borderWidth: 0.6,
                     shadowBlur: 9, shadowColor: color }}
      }};
    }});
  }}

  var overviewOption = {{
    backgroundColor: 'transparent',
    title: {{
      text: '乌兰察布商家分布热力', subtext: '点击任意区县下钻查看 · 颜色越亮商家越多',
      left: 'center', top: 12,
      textStyle: {{ color: '#f1f5f9', fontSize: 17, fontWeight: 600 }},
      subtextStyle: {{ color: '#8fa3bf', fontSize: 12 }}
    }},
    tooltip: {{
      trigger: 'item', backgroundColor: 'rgba(15,23,42,0.92)',
      borderColor: 'rgba(125,211,252,0.35)', textStyle: {{ color: '#e2e8f0' }},
      extraCssText: 'backdrop-filter: blur(14px); border-radius: 12px;',
      formatter: function(p) {{ return p.name + '<br/>商家数:' + (p.value || 0) + ' 家<br/><span style="color:#7dd3fc">点击查看详情 →</span>'; }}
    }},
    visualMap: {{
      min: 0, max: {vmax}, left: 20, bottom: 24, text: ['多', '少'],
      textStyle: {{ color: '#cbd5e1' }},
      inRange: {{ color: ['#0c2a4d', '#0e7490', '#22d3ee', '#a5f3fc'] }},
      calculable: true, itemWidth: 14, itemHeight: 90,
      precision: 0, formatter: function(v) {{ return Math.round(v); }}
    }},
    series: [{{
      type: 'map', map: 'ulanqab', roam: true, data: {json.dumps(data, ensure_ascii=False)},
      label: {{ show: true, color: '#e2e8f0', fontSize: 11 }},
      itemStyle: {{
        borderColor: 'rgba(125,211,252,0.45)', borderWidth: 1.2,
        shadowColor: 'rgba(56,189,248,0.4)', shadowBlur: 14
      }},
      emphasis: {{
        label: {{ color: '#ffffff', fontSize: 13, fontWeight: 700 }},
        itemStyle: {{ areaColor: '#38bdf8', shadowBlur: 26, shadowColor: 'rgba(56,189,248,0.85)' }}
      }}
    }}]
  }};

  function drillOption(dname) {{
    var meta = META[dname];
    var pts = scatterPoints(colorMode);
    var center = meta.center || [112.6, 41.5];
    return {{
      backgroundColor: 'transparent',
      title: {{
        text: dname + ' · 商家详情', subtext: meta.count + ' 个商家 · 滚轮缩放查看',
        left: 'center', top: 12,
        textStyle: {{ color: '#f1f5f9', fontSize: 17, fontWeight: 600 }},
        subtextStyle: {{ color: '#8fa3bf', fontSize: 12 }}
      }},
      tooltip: {{
        trigger: 'item', backgroundColor: 'rgba(15,23,42,0.92)',
        borderColor: 'rgba(125,211,252,0.35)', textStyle: {{ color: '#e2e8f0', fontSize: 12 }},
        extraCssText: 'backdrop-filter: blur(14px); border-radius: 12px;',
        formatter: function(p) {{
          var d = p.data;
          if (!d || !d.name) return p.name;
          return '<b>' + d.name + '</b><br/>评分:' + (d.rating || '无')
            + ' · 人均:' + (d.cost ? d.cost + '元' : '未知')
            + (d.category ? '<br/>' + d.category : '');
        }}
      }},
      geo: [{{
        map: 'ulanqab', roam: true, center: center, zoom: 6.5,
        itemStyle: {{
          areaColor: 'rgba(10,32,56,0.5)',
          borderColor: 'rgba(125,211,252,0.35)', borderWidth: 1
        }},
        emphasis: {{ disabled: true }}, silent: true
      }}],
      series: [{{
        type: 'scatter', coordinateSystem: 'geo', data: pts, symbolSize: 7,
        progressive: 2000, animationDuration: 700,
        emphasis: {{ scale: 1.8, itemStyle: {{ shadowBlur: 18 }} }}
      }}]
    }};
  }}

  chart.setOption(overviewOption);

  /* ---------- 交互:点击区县下钻 ---------- */
  chart.on('click', function(params) {{
    if (params.componentType !== 'series' || currentDistrict) return;
    var dname = params.name;
    if (!META[dname]) return;
    enterDistrict(dname);
  }});

  function enterDistrict(dname) {{
    currentDistrict = dname;
    var meta = META[dname];
    chart.clear();
    chart.setOption(drillOption(dname));
    hint.style.opacity = '0';

    /* 填充面板 */
    document.getElementById('p-name').textContent = dname;
    document.getElementById('p-count').textContent = meta.count + ' 家';
    document.getElementById('p-rating').textContent = meta.avg_rating != null ? meta.avg_rating + ' 分' : '—';
    document.getElementById('p-cost').textContent = meta.avg_cost != null ? '¥' + meta.avg_cost : '—';
    var catsHtml = '';
    meta.top_cats.forEach(function(c) {{
      var col = CAT_COLORS[c[0]] || '#94a3b8';
      catsHtml += '<div class="cat"><span class="dot" style="background:' + col + '"></span>'
        + '<span>' + c[0] + '</span><span class="n">' + c[1] + '</span></div>';
    }});
    document.getElementById('p-cats').innerHTML = catsHtml;
    panel.classList.add('show');
    colorbar.classList.add('show');
  }}

  function backToOverview() {{
    currentDistrict = null;
    panel.classList.remove('show');
    colorbar.classList.remove('show');
    chart.clear();
    chart.setOption(overviewOption);
    hint.style.opacity = '1';
  }}

  document.getElementById('back').addEventListener('click', backToOverview);

  /* 着色切换(仅下钻后可用) */
  colorbar.querySelectorAll('button').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      if (!currentDistrict) return;
      colorMode = btn.getAttribute('data-mode');
      colorbar.querySelectorAll('button').forEach(function(b) {{ b.classList.remove('on'); }});
      btn.classList.add('on');
      chart.setOption({{ series: [{{ data: scatterPoints(colorMode) }}] }});
    }});
  }});

  window.addEventListener('resize', function() {{ chart.resize(); }});
}})();
</script>
</body></html>"""
    return html


# ---- 保留旧的独立函数(向后兼容) ----

def density_map_html(district_counts: dict, height=620):
    """纯密度地图(无下钻)。"""
    geojson = _load_geojson()
    data = [{"name": k, "value": v} for k, v in district_counts.items()]
    values = list(district_counts.values())
    vmax = max(values) if values else 1

    option = {
        "backgroundColor": "transparent",
        "title": {
            "text": "乌兰察布商家分布热力",
            "subtext": f"共 {sum(values):,} 家 · 颜色越亮商家越多",
            "left": "center", "top": 10,
            "textStyle": {"color": "#f1f5f9", "fontSize": 16, "fontWeight": 600},
            "subtextStyle": {"color": "#8fa3bf", "fontSize": 12},
        },
        "tooltip": {
            "trigger": "item",
            "backgroundColor": "rgba(15,23,42,0.92)",
            "borderColor": "rgba(125,211,252,0.35)",
            "textStyle": {"color": "#e2e8f0"},
            "extraCssText": "backdrop-filter: blur(14px); border-radius: 12px;",
            "formatter": "{b}<br/>商家数:{c}",
        },
        "visualMap": {
            "min": 0, "max": vmax,
            "left": 20, "bottom": 20,
            "text": ["多", "少"],
            "textStyle": {"color": "#cbd5e1"},
            "inRange": {"color": ["#0c2a4d", "#0e7490", "#22d3ee", "#a5f3fc"]},
            "calculable": True,
            "itemWidth": 14, "itemHeight": 90,
        },
        "series": [{
            "type": "map",
            "map": "ulanqab",
            "roam": True,
            "data": data,
            "label": {"show": True, "color": "#e2e8f0", "fontSize": 11},
            "itemStyle": {
                "borderColor": "rgba(125,211,252,0.45)",
                "borderWidth": 1.2,
                "shadowColor": "rgba(56,189,248,0.4)",
                "shadowBlur": 14,
            },
            "emphasis": {
                "label": {"color": "#ffffff", "fontSize": 13, "fontWeight": 700},
                "itemStyle": {
                    "areaColor": "#38bdf8",
                    "shadowBlur": 24,
                    "shadowColor": "rgba(56,189,248,0.8)",
                },
            },
        }],
    }

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin:0; padding:0;
    background: radial-gradient(ellipse at 30% 30%, rgba(56,189,248,0.13), transparent 55%),
                radial-gradient(ellipse at 72% 70%, rgba(168,85,247,0.12), transparent 55%),
                #070b14; }}
  #main {{ width:100%; height:{height}px; }}
</style>
<script>{_load_echarts()}</script>
</head><body>
<div id="main"></div>
<script>
  var geo = {json.dumps(geojson, ensure_ascii=False)};
  echarts.registerMap('ulanqab', geo);
  var chart = echarts.init(document.getElementById('main'));
  chart.setOption({json.dumps(option, ensure_ascii=False)});
  window.addEventListener('resize', function() {{ chart.resize(); }});
</script>
</body></html>"""


def poi_scatter_html(points, color_by="rating", height=620, title="商家分布"):
    """散点地图:每个商家按经纬度撒点(全区,不下钻)。"""
    geojson = _load_geojson()

    if color_by == "category":
        from collections import defaultdict
        groups = defaultdict(list)
        for p in points:
            if p["lng"] is None:
                continue
            groups[p.get("category") or "其他"].append({
                "name": p["name"], "value": [p["lng"], p["lat"]],
                "rating": p.get("rating"), "cost": p.get("cost"),
                "district": p.get("district"), "category": p.get("category"),
            })
        series = []
        for cat, items in sorted(groups.items(), key=lambda x: -len(x[1]))[:12]:
            series.append({
                "name": cat, "type": "scatter", "coordinateSystem": "geo",
                "data": items, "symbolSize": 7,
                "itemStyle": {"color": CAT_COLORS.get(cat, "#94a3b8"),
                              "borderColor": "rgba(255,255,255,0.6)", "borderWidth": 0.6},
            })
        visual_map = None
    else:
        scatter_data = [{
            "name": p["name"], "value": [p["lng"], p["lat"], p.get(color_by) or 0],
            "rating": p.get("rating"), "cost": p.get("cost"),
            "district": p.get("district"), "category": p.get("category"),
        } for p in points if p["lng"] is not None and p["lat"] is not None]
        series = [{
            "type": "scatter", "coordinateSystem": "geo", "data": scatter_data,
            "symbolSize": 7,
            "itemStyle": {"borderColor": "rgba(255,255,255,0.5)", "borderWidth": 0.6},
        }]
        visual_map = {
            "min": 0, "max": 150 if color_by == "cost" else 5,
            "left": 20, "bottom": 20, "dimension": 2,
            "text": ["高", "低"], "textStyle": {"color": "#cbd5e1"},
            "inRange": {"color": ["#67e8f9", "#38bdf8", "#a855f7", "#f472b6"]},
            "calculable": True, "itemWidth": 14, "itemHeight": 90,
        }

    option = {
        "backgroundColor": "transparent",
        "title": {"text": title, "subtext": f"共 {len(points):,} 个商家",
                  "left": "center", "top": 10,
                  "textStyle": {"color": "#f1f5f9", "fontSize": 16, "fontWeight": 600},
                  "subtextStyle": {"color": "#8fa3bf", "fontSize": 12}},
        "tooltip": {"trigger": "item", "backgroundColor": "rgba(15,23,42,0.92)",
                    "borderColor": "rgba(125,211,252,0.35)", "textStyle": {"color": "#e2e8f0", "fontSize": 12}},
        "legend": {"show": color_by == "category", "bottom": 6, "left": "center",
                   "textStyle": {"color": "#cbd5e1", "fontSize": 11}},
        "geo": {"map": "ulanqab", "roam": True, "zoom": 1.1,
                "itemStyle": {"areaColor": "rgba(15,42,71,0.55)",
                              "borderColor": "rgba(125,211,252,0.5)", "borderWidth": 1.2}},
        "series": series,
    }
    if visual_map:
        option["visualMap"] = visual_map

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin:0; padding:0;
    background: radial-gradient(ellipse at 30% 30%, rgba(56,189,248,0.13), transparent 55%),
                radial-gradient(ellipse at 72% 70%, rgba(168,85,247,0.12), transparent 55%),
                #070b14; }}
  #main {{ width:100%; height:{height}px; }}
</style>
<script>{_load_echarts()}</script>
</head><body>
<div id="main"></div>
<script>
  var geo = {json.dumps(geojson, ensure_ascii=False)};
  echarts.registerMap('ulanqab', geo);
  var chart = echarts.init(document.getElementById('main'));
  chart.setOption({json.dumps(option, ensure_ascii=False)});
  window.addEventListener('resize', function() {{ chart.resize(); }});
</script>
</body></html>"""
