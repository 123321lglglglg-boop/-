"""PWA 支持:让手机"添加到主屏幕"后像原生 App 打开。

要点:
  - iOS 的 apple-touch-icon 必须是可访问的 URL(不用 data URI),
    因此图标放在 static/,靠 Streamlit 的 enableStaticServing 提供 /app/static/。
  - Streamlit Cloud 把 app 放在 iframe 里,而 iOS 只读顶层文档的 head,
    所以用 st.components(能执行 JS)把标签提升到父文档。
  - manifest 用 static/manifest.json 静态文件,不再用 blob:。
    原因:blob URL 没有有效的基址,manifest 里的相对路径(start_url、图标 src)
    会被浏览器判定为 "not a valid URL" 并整个丢弃 —— 实测 iOS WebKit
    报 "Parsing application manifest ... is not a valid URL",
    "添加到主屏幕"直接失效。静态文件有真实 URL,相对路径按规范
    以 manifest 自身地址为基准解析,不会有这个问题。
"""
import json
from pathlib import Path

import streamlit as st

BASE = Path(__file__).resolve().parent.parent

# .streamlit/config.toml 里 enableStaticServing=true 后,
# 项目根的 static/ 映射到 /app/static/
STATIC_PREFIX = "./app/static/"


def inject_pwa(app_name="乌兰察布知识图谱"):
    """注入 PWA 元数据与图标。"""
    apple_icon = STATIC_PREFIX + "apple-touch-icon.png"

    # 用 components 才能确保 <script> 真正执行(st.markdown 的脚本会被过滤)
    st.components.v1.html(
        f"""
<div style="display:none"></div>
<script>
(function() {{
  var APPLE_ICON = "{apple_icon}";
  var APP_NAME = {json.dumps(app_name, ensure_ascii=False)};
  var MANIFEST_PATH = "app/static/manifest.json";

  function topDoc() {{
    var w = window;
    try {{
      while (w.parent && w.parent !== w) {{ w = w.parent; }}
      return w.document;
    }} catch (e) {{
      try {{ return window.parent.document; }} catch (e2) {{ return null; }}
    }}
  }}

  function topWin() {{
    var w = window;
    try {{
      while (w.parent && w.parent !== w) {{ w = w.parent; }}
      return w;
    }} catch (e) {{ return window; }}
  }}

  // 应用可能部署在子路径下(Streamlit Cloud),所以基址要从当前地址算,
  // 不能写死 "/app/static/"。
  // 注意:必须用【顶层窗口】的 location —— 这段脚本跑在 Streamlit 的组件
  // iframe 里,iframe 自己的 location 是 about:srcdoc,origin 是字符串 "null",
  // 拿它算基址会拼出 ".../nullapp/static/..." 这种坏地址。
  function appBase() {{
    try {{
      var w = topWin();
      return w.location.origin + w.location.pathname.replace(/[^/]*$/, "");
    }} catch (e) {{ return "/"; }}
  }}

  function apply() {{
    var doc = topDoc();
    if (!doc || !doc.head) return false;
    var head = doc.head;
    var ORIGIN = appBase();

    function mk(tag, attrs) {{
      var el = doc.createElement(tag);
      Object.keys(attrs).forEach(function(k) {{ el.setAttribute(k, attrs[k]); }});
      return el;
    }}
    function upsert(sel, make) {{
      var el = head.querySelector(sel);
      if (el) el.parentNode.removeChild(el);
      head.appendChild(make());
    }}

    // manifest 用静态文件(绝对地址),不用 blob —— 见模块开头说明
    upsert('link[rel="manifest"]', function() {{
      return mk('link', {{rel: 'manifest', href: ORIGIN + MANIFEST_PATH}});
    }});

    upsert('link[rel="apple-touch-icon"]', function() {{ return mk('link', {{rel: 'apple-touch-icon', href: ORIGIN + "app/static/apple-touch-icon.png"}}); }});
    upsert('link[rel="apple-touch-icon-precomposed"]', function() {{ return mk('link', {{rel: 'apple-touch-icon-precomposed', href: ORIGIN + "app/static/apple-touch-icon.png"}}); }});
    upsert('meta[name="apple-mobile-web-app-capable"]', function() {{ return mk('meta', {{name: 'apple-mobile-web-app-capable', content: 'yes'}}); }});
    upsert('meta[name="apple-mobile-web-app-title"]', function() {{ return mk('meta', {{name: 'apple-mobile-web-app-title', content: APP_NAME}}); }});
    upsert('meta[name="apple-mobile-web-app-status-bar-style"]', function() {{ return mk('meta', {{name: 'apple-mobile-web-app-status-bar-style', content: 'black-translucent'}}); }});
    upsert('meta[name="mobile-web-app-capable"]', function() {{ return mk('meta', {{name: 'mobile-web-app-capable', content: 'yes'}}); }});

    upsert('meta[name="theme-color"]', function() {{ return mk('meta', {{name: 'theme-color', content: '#070b14'}}); }});

    return true;
  }}

  if (!apply()) {{
    var n = 0;
    var timer = setInterval(function() {{
      n++;
      if (apply() || n >= 40) clearInterval(timer);
    }}, 500);
  }}
}})();
</script>
""",
        height=0,
    )


# iOS 全屏模式的补充样式(状态栏留白、增大触控目标)
MOBILE_CSS = """
<style>
/* iOS 全屏(从主屏打开)时给顶部留出状态栏空间 */
@media (display-mode: standalone) {
  [data-testid="stMainBlockContainer"] { padding-top: 2.6rem !important; }
}
/* 触控目标增大(移动端) */
@media (max-width: 820px) {
  /* 顶部留出呼吸空间,同时让 header 不占位 */
  [data-testid="stMainBlockContainer"] { padding-top: 1.8rem !important; }
  [data-testid="stMainBlockContainer"] { padding-left: 0.7rem !important; padding-right: 0.7rem !important; }
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
