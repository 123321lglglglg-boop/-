"""PWA 支持:让手机"添加到主屏幕"后像原生 App 打开。

在 Streamlit 里通过注入 meta 标签 + data-URI manifest 实现:
  - iOS: apple-mobile-web-app-capable → 全屏无浏览器栏
  - Android: manifest.json → 独立窗口 + 图标
  - 主题色、启动画面色
"""
import base64
import json
from pathlib import Path

import streamlit as st

BASE = Path(__file__).resolve().parent.parent


def _icon_data_uri(name: str) -> str:
    p = BASE / "static" / name
    if not p.exists():
        return ""
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:image/png;base64,{b64}"


def inject_pwa(app_name="乌兰察布知识图谱"):
    """注入 PWA 所需的 meta 标签与 manifest。"""
    icon_192 = _icon_data_uri("icon-192.png")
    icon_512 = _icon_data_uri("icon-512.png")
    apple_icon = _icon_data_uri("apple-touch-icon.png")

    manifest = {
        "name": "乌兰察布本地生活知识图谱",
        "short_name": "乌兰察布KG",
        "description": "知识图谱作品集:6949 个商家、53666 条关系、LLM 问答",
        "start_url": ".",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#070b14",
        "theme_color": "#070b14",
        "icons": [
            {"src": icon_192, "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": icon_512, "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    manifest_uri = "data:application/manifest+json;base64," + base64.b64encode(
        json.dumps(manifest, ensure_ascii=False).encode()
    ).decode()

    st.markdown(
        f"""
<link rel="manifest" href="{manifest_uri}">
<link rel="apple-touch-icon" href="{apple_icon}">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="{app_name}">
<meta name="mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#070b14">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
""",
        unsafe_allow_html=True,
    )

    # Streamlit Cloud 把 app 放在 iframe 里,而 iOS "添加到主屏幕"只读顶层页面的 head。
    # 这段脚本把关键标签从 iframe 提升到顶层文档(同源,可直接操作 parent)。
    # 用定时器重试:Streamlit 页面动态渲染,head 可能尚未就绪。
    st.markdown(
        f"""
<script>
(function() {{
  var tries = 0;
  var MAX = 40;              // 最多尝试 40 次(约 20 秒)
  var INT = 500;             // 每 500ms 一次

  function topDoc() {{
    var w = window;
    try {{
      while (w.parent && w.parent !== w) {{ w = w.parent; }}
      return w.document;
    }} catch (e) {{
      return window.parent.document;   // 跨域时退回上一层
    }}
  }}

  function apply() {{
    var doc;
    try {{ doc = topDoc(); }} catch (e) {{ return false; }}
    if (!doc || !doc.head) return false;

    var head = doc.head;
    function upsert(sel, make) {{
      if (!head.querySelector(sel)) head.appendChild(make());
    }}
    function mk(tag, attrs) {{
      var el = doc.createElement(tag);
      Object.keys(attrs).forEach(function(k) {{ el.setAttribute(k, attrs[k]); }});
      return el;
    }}

    upsert('link[rel="manifest"]', function() {{ return mk('link', {{rel: 'manifest', href: '{manifest_uri}'}}); }});
    upsert('link[rel="apple-touch-icon"]', function() {{ return mk('link', {{rel: 'apple-touch-icon', href: '{apple_icon}'}}); }});
    upsert('meta[name="apple-mobile-web-app-capable"]', function() {{ return mk('meta', {{name: 'apple-mobile-web-app-capable', content: 'yes'}}); }});
    upsert('meta[name="apple-mobile-web-app-title"]', function() {{ return mk('meta', {{name: 'apple-mobile-web-app-title', content: '{app_name}'}}); }});
    upsert('meta[name="apple-mobile-web-app-status-bar-style"]', function() {{ return mk('meta', {{name: 'apple-mobile-web-app-status-bar-style', content: 'black-translucent'}}); }});
    upsert('meta[name="mobile-web-app-capable"]', function() {{ return mk('meta', {{name: 'mobile-web-app-capable', content: 'yes'}}); }});
    // theme-color 可能已存在(Streamlit 自带白色),需要覆盖而非跳过
    var tc = head.querySelector('meta[name="theme-color"]');
    if (tc) {{ tc.setAttribute('content', '#070b14'); }}
    else {{ head.appendChild(mk('meta', {{name: 'theme-color', content: '#070b14'}})); }}

    return true;
  }}

  if (!apply()) {{
    var t = setInterval(function() {{
      tries++;
      if (apply() || tries >= MAX) clearInterval(t);
    }}, INT);
  }}
}})();
</script>
""",
        unsafe_allow_html=True,
    )


# iOS 全屏模式的补充样式(状态栏留白、增大触控目标)
MOBILE_CSS = """
<style>
/* iOS 全屏(从主屏打开)时给顶部留出状态栏空间 */
@media (display-mode: standalone) {
  .main .block-container { padding-top: 3.2rem !important; }
}
/* 触控目标增大(移动端) */
@media (max-width: 820px) {
  .main .block-container { padding-left: 0.7rem !important; padding-right: 0.7rem !important; }
  h1 { font-size: 1.75rem !important; }
  .stTabs [role="tab"] {
    padding: 0 10px !important;
    font-size: 0.8rem !important;
    height: 40px !important;
  }
  [data-testid="stMetricValue"] { font-size: 1.55rem !important; }
  [data-testid="stMetricLabel"] p { font-size: 0.72rem !important; }
  .stButton > button { padding: 0.5rem 0.8rem !important; font-size: 0.86rem !important; }
  /* 输入控件放大,避免 iOS 聚焦时自动缩放 */
  .stTextInput input, .stNumberInput input, .stTextArea textarea,
  [data-baseweb="select"] > div { font-size: 16px !important; }
  /* 图表容器在窄屏下减padding */
  [data-testid="stArrowVegaLiteChart"], [data-testid="stVegaLiteChart"] { padding: 8px; }
  [data-testid="stIFrame"] { border-radius: 14px; }
}
/* 极窄屏:指标卡两列 */
@media (max-width: 480px) {
  .stTabs [role="tab"] { padding: 0 7px !important; font-size: 0.74rem !important; }
}
</style>
"""


def inject_mobile_css():
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)
