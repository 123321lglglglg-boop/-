"""首屏 Hero 区:大标题 + 动态数字 + 图谱动画背景。

用 Streamlit 组件嵌入一段自包含的 HTML/CSS/JS:
  - 玻璃质感英雄卡片
  - 数字从 0 滚动到目标值
  - 背景是 canvas 绘制的漂浮节点网络动画
"""
import json
import warnings

warnings.filterwarnings("ignore")


def hero_html(stats: dict, height=340):
    """stats: {"poi": 6949, "relations": 53666, "brands": 303, "districts": 11}"""
    stats_json = json.dumps(stats, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  html, body {{
    margin: 0; padding: 0;
    font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    background: transparent;
    overflow: hidden;
  }}
  #hero {{
    position: relative;
    width: 100%;
    height: {height}px;
    border-radius: 24px;
    overflow: hidden;
    background: linear-gradient(135deg, rgba(255,255,255,0.09), rgba(255,255,255,0.03));
    border: 1px solid rgba(255,255,255,0.15);
    box-shadow: 0 18px 60px rgba(2,6,23,0.5), inset 0 1px 0 rgba(255,255,255,0.2);
  }}
  #net {{
    position: absolute; inset: 0;
    width: 100%; height: 100%;
    opacity: 0.85;
  }}
  .content {{
    position: relative;
    z-index: 2;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    padding: 0 30px;
    text-align: center;
  }}
  .badge {{
    display: inline-block;
    padding: 6px 16px;
    border-radius: 999px;
    font-size: 12.5px;
    letter-spacing: 1.2px;
    color: #a5f3fc;
    background: rgba(56,189,248,0.13);
    border: 1px solid rgba(125,211,252,0.35);
    backdrop-filter: blur(10px);
    margin-bottom: 18px;
    text-transform: uppercase;
  }}
  .title {{
    font-size: 42px;
    font-weight: 800;
    letter-spacing: -1px;
    line-height: 1.18;
    background: linear-gradient(100deg, #7dd3fc 0%, #c4b5fd 38%, #f0abfc 72%, #7dd3fc 100%);
    background-size: 250% auto;
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: shine 9s linear infinite;
    filter: drop-shadow(0 0 30px rgba(125,211,252,0.35));
    margin: 0;
  }}
  @keyframes shine {{ to {{ background-position: 250% center; }} }}

  .subtitle {{
    margin-top: 14px;
    font-size: 15.5px;
    color: #a8bcd4;
    max-width: 720px;
    line-height: 1.6;
  }}
  .subtitle b {{ color: #7dd3fc; font-weight: 600; }}

  .stats {{
    display: flex;
    gap: 42px;
    margin-top: 30px;
    flex-wrap: wrap;
    justify-content: center;
  }}
  .stat {{ text-align: center; min-width: 92px; }}
  .stat .num {{
    font-size: 31px;
    font-weight: 800;
    color: #f8fafc;
    text-shadow: 0 0 26px rgba(125,211,252,0.45);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.5px;
  }}
  .stat .lbl {{
    font-size: 12px;
    color: #8fa3bf;
    letter-spacing: 1.4px;
    margin-top: 5px;
    text-transform: uppercase;
  }}
  .stat .bar {{
    height: 3px;
    width: 100%;
    margin-top: 9px;
    border-radius: 3px;
    background: linear-gradient(90deg, transparent, #38bdf8, #a855f7, transparent);
    opacity: 0.75;
    animation: pulse 2.6s ease-in-out infinite;
  }}
  @keyframes pulse {{
    0%, 100% {{ opacity: 0.4; transform: scaleX(0.75); }}
    50%      {{ opacity: 1;   transform: scaleX(1); }}
  }}
</style>
</head>
<body>
<div id="hero">
  <canvas id="net"></canvas>
  <div class="content">
    <div class="badge">Knowledge Graph · 知识图谱作品集</div>
    <h1 class="title">乌兰察布本地生活知识图谱</h1>
    <div class="subtitle">
      从高德开放平台采集 <b>真实商家数据</b>,构建涵盖商圈、品类、价格带、
      地理邻近关系的知识图谱,支持 <b>自然语言问答</b> 与 <b>LLM 图查询</b>
    </div>
    <div class="stats">
      <div class="stat"><div class="num" data-target="{stats['poi']}">0</div>
        <div class="lbl">商家 POI</div><div class="bar"></div></div>
      <div class="stat"><div class="num" data-target="{stats['relations']}">0</div>
        <div class="lbl">关系总数</div><div class="bar"></div></div>
      <div class="stat"><div class="num" data-target="{stats['brands']}">0</div>
        <div class="lbl">连锁品牌</div><div class="bar"></div></div>
      <div class="stat"><div class="num" data-target="{stats['districts']}">0</div>
        <div class="lbl">覆盖区县</div><div class="bar"></div></div>
    </div>
  </div>
</div>

<script>
(function() {{
  /* ---- 数字滚动 ---- */
  var els = document.querySelectorAll('.num');
  els.forEach(function(el) {{
    var target = parseInt(el.getAttribute('data-target'), 10);
    var dur = 1600, t0 = null;
    function step(ts) {{
      if (!t0) t0 = ts;
      var prog = Math.min((ts - t0) / dur, 1);
      // easeOutCubic
      var eased = 1 - Math.pow(1 - prog, 3);
      el.textContent = Math.round(target * eased).toLocaleString();
      if (prog < 1) requestAnimationFrame(step);
    }}
    requestAnimationFrame(step);
  }});

  /* ---- 节点网络动画 ---- */
  var canvas = document.getElementById('net');
  var ctx = canvas.getContext('2d');
  var dpr = window.devicePixelRatio || 1;
  var W, H, nodes = [];

  function resize() {{
    var r = canvas.parentElement.getBoundingClientRect();
    W = canvas.width = r.width * dpr;
    H = canvas.height = r.height * dpr;
    canvas.style.width = r.width + 'px';
    canvas.style.height = r.height + 'px';
  }}
  resize();
  window.addEventListener('resize', function() {{ resize(); }});

  var COLORS = ['125,211,252', '196,181,253', '240,171,252', '52,211,153'];
  for (var i = 0; i < 34; i++) {{
    nodes.push({{
      x: Math.random(), y: Math.random(),
      vx: (Math.random() - 0.5) * 0.00045,
      vy: (Math.random() - 0.5) * 0.00045,
      r: (Math.random() * 2.1 + 1.3) * dpr,
      c: COLORS[Math.floor(Math.random() * COLORS.length)]
    }});
  }}

  function draw() {{
    ctx.clearRect(0, 0, W, H);
    // 连线
    for (var i = 0; i < nodes.length; i++) {{
      for (var j = i + 1; j < nodes.length; j++) {{
        var dx = (nodes[i].x - nodes[j].x) * W;
        var dy = (nodes[i].y - nodes[j].y) * H;
        var d = Math.sqrt(dx * dx + dy * dy);
        if (d < 175 * dpr) {{
          ctx.strokeStyle = 'rgba(125,211,252,' + (0.16 * (1 - d / (175 * dpr))) + ')';
          ctx.lineWidth = 0.85 * dpr;
          ctx.beginPath();
          ctx.moveTo(nodes[i].x * W, nodes[i].y * H);
          ctx.lineTo(nodes[j].x * W, nodes[j].y * H);
          ctx.stroke();
        }}
      }}
    }}
    // 节点
    for (var k = 0; k < nodes.length; k++) {{
      var n = nodes[k];
      n.x += n.vx; n.y += n.vy;
      if (n.x < 0 || n.x > 1) n.vx *= -1;
      if (n.y < 0 || n.y > 1) n.vy *= -1;
      var x = n.x * W, y = n.y * H;
      var g = ctx.createRadialGradient(x, y, 0, x, y, n.r * 4.5);
      g.addColorStop(0, 'rgba(' + n.c + ',0.9)');
      g.addColorStop(1, 'rgba(' + n.c + ',0)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, n.r * 4.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = 'rgba(' + n.c + ',0.95)';
      ctx.beginPath();
      ctx.arc(x, y, n.r, 0, Math.PI * 2);
      ctx.fill();
    }}
    requestAnimationFrame(draw);
  }}
  draw();
}})();
</script>
</body></html>"""
