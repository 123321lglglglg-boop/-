"""液态玻璃(Liquid Glass)主题 —— 为 Streamlit 注入自定义样式。

设计要点:
  - 动态渐变光斑背景(缓慢流动,营造"液态"感)
  - 毛玻璃卡片(backdrop-filter 模糊 + 半透明 + 高光边框)
  - 液态标签页(选中态有流动的高光,切换有弹性动效)
  - 渐变文字标题 + 光晕
  - 按钮按下有涟漪/回弹效果
  - 统一色板:深蓝紫基底 + 青/紫/粉三色光斑
"""
import streamlit as st

LIQUID_CSS = """
<style>
/* ========== 全局:深空基底 ========== */
.stApp {
  background: #070b14;
  font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

/* ========== 动态渐变光斑背景 ========== */
.stApp::before {
  content: '';
  position: fixed;
  inset: -20%;
  z-index: 0;
  background:
    radial-gradient(circle at 20% 25%, rgba(56,189,248,0.28), transparent 42%),
    radial-gradient(circle at 78% 18%, rgba(168,85,247,0.26), transparent 45%),
    radial-gradient(circle at 60% 82%, rgba(244,114,182,0.20), transparent 48%),
    radial-gradient(circle at 12% 78%, rgba(52,211,153,0.16), transparent 45%);
  filter: blur(40px) saturate(140%);
  animation: liquidFloat 24s ease-in-out infinite alternate;
  pointer-events: none;
}

@keyframes liquidFloat {
  0%   { transform: translate3d(0,0,0) scale(1); }
  33%  { transform: translate3d(3%, -2.5%, 0) scale(1.06); }
  66%  { transform: translate3d(-2.5%, 2%, 0) scale(0.98); }
  100% { transform: translate3d(2%, 3%, 0) scale(1.04); }
}

/* 细颗粒噪点,增加玻璃质感 */
.stApp::after {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  opacity: 0.5;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.035'/%3E%3C/svg%3E");
  pointer-events: none;
}

/* 内容层浮在光斑之上 */
.stApp > header, .stApp .main, .stApp .block-container { position: relative; z-index: 1; }

[data-testid="stMainBlockContainer"],
.stApp .block-container {
  padding-top: 0.5rem !important;
  max-width: 1500px;
}

/* ========== 标题:渐变液态文字 ========== */
h1 {
  font-size: 2.9rem !important;
  font-weight: 800 !important;
  letter-spacing: -0.5px;
  background: linear-gradient(100deg, #7dd3fc 0%, #c4b5fd 35%, #f0abfc 70%, #7dd3fc 100%);
  background-size: 260% auto;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: liquidShine 8s linear infinite;
  filter: drop-shadow(0 0 24px rgba(125,211,252,0.30));
}
@keyframes liquidShine {
  to { background-position: 260% center; }
}

h2, h3 { color: #e2e8f0 !important; font-weight: 700 !important; letter-spacing: -0.2px; }

/* 副标题说明文字 */
.stApp p, .stApp label, .stApp .stMarkdown { color: #cbd5e1; }
[data-testid="stCaptionContainer"] p { color: #8fa3bf !important; font-size: 0.9rem; }

/* ========== 毛玻璃卡片:通用容器 ========== */
[data-testid="stMetric"],
[data-testid="stDataFrame"],
[data-testid="stTable"],
div[data-testid="stExpander"],
[data-testid="stForm"] {
  background: linear-gradient(135deg, rgba(255,255,255,0.10) 0%, rgba(255,255,255,0.035) 100%) !important;
  backdrop-filter: blur(22px) saturate(170%);
  -webkit-backdrop-filter: blur(22px) saturate(170%);
  border: 1px solid rgba(255,255,255,0.14) !important;
  border-radius: 20px !important;
  box-shadow:
    0 8px 32px rgba(2,6,23,0.46),
    inset 0 1px 0 rgba(255,255,255,0.20),
    inset 0 -1px 0 rgba(255,255,255,0.04);
  transition: transform .35s cubic-bezier(.22,1,.36,1), box-shadow .35s ease, border-color .35s ease;
}

[data-testid="stMetric"]:hover {
  transform: translateY(-4px) scale(1.015);
  border-color: rgba(125,211,252,0.42) !important;
  box-shadow:
    0 16px 44px rgba(56,189,248,0.22),
    inset 0 1px 0 rgba(255,255,255,0.28);
}

/* 指标卡内文字 */
[data-testid="stMetricLabel"] p {
  color: #93c5fd !important;
  font-size: 0.86rem !important;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  opacity: 0.9;
}
[data-testid="stMetricValue"] {
  color: #f8fafc !important;
  font-weight: 800 !important;
  text-shadow: 0 0 22px rgba(125,211,252,0.35);
}

/* ========== 液态标签页 ========== */
/* 兼容新版(role=tablist/tab)与旧版(data-baseweb)Streamlit */
.stTabs [role="tablist"],
.stTabs [data-baseweb="tab-list"] {
  gap: 8px;
  background: rgba(255,255,255,0.055);
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  padding: 7px;
  border-radius: 20px;
  border: 1px solid rgba(255,255,255,0.13);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.16), 0 8px 26px rgba(2,6,23,0.4);
}

.stTabs [role="tab"],
.stTabs [data-baseweb="tab"] {
  height: 46px;
  padding: 0 22px;
  border-radius: 15px;
  background: transparent;
  color: #9fb3cc !important;
  font-weight: 600;
  font-size: 0.96rem;
  border: 1px solid transparent;
  transition: all .38s cubic-bezier(.22,1,.36,1);
  overflow: hidden;
  position: relative;
}

/* 液态高光:选中标签的流光扫过 */
.stTabs [role="tab"]::after,
.stTabs [data-baseweb="tab"]::after {
  content: '';
  position: absolute;
  top: 0; left: -120%;
  width: 120%; height: 100%;
  background: linear-gradient(100deg, transparent, rgba(255,255,255,0.34), transparent);
  transition: left .65s ease;
}
.stTabs [role="tab"]:hover::after,
.stTabs [data-baseweb="tab"]:hover::after { left: 120%; }

.stTabs [role="tab"]:hover,
.stTabs [data-baseweb="tab"]:hover {
  color: #e2e8f0 !important;
  background: rgba(255,255,255,0.085);
  border-color: rgba(255,255,255,0.16);
  transform: translateY(-1px);
}

.stTabs [role="tab"][aria-selected="true"],
.stTabs [aria-selected="true"] {
  background: linear-gradient(135deg, rgba(56,189,248,0.32), rgba(168,85,247,0.32)) !important;
  color: #f8fafc !important;
  border: 1px solid rgba(125,211,252,0.5) !important;
  box-shadow:
    0 6px 22px rgba(56,189,248,0.30),
    inset 0 1px 0 rgba(255,255,255,0.30);
}

/* 去掉 Streamlit 默认的下划线指示条(新旧版本) */
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"],
.stTabs [role="tablist"] > div[aria-hidden="true"] { display: none !important; }

/* ========== 按钮:液态回弹 ========== */
.stButton > button, .stDownloadButton > button {
  border-radius: 15px !important;
  border: 1px solid rgba(255,255,255,0.17) !important;
  background: linear-gradient(135deg, rgba(255,255,255,0.11), rgba(255,255,255,0.045)) !important;
  backdrop-filter: blur(16px) saturate(160%);
  -webkit-backdrop-filter: blur(16px) saturate(160%);
  color: #e2e8f0 !important;
  font-weight: 600 !important;
  padding: 0.55rem 1.1rem !important;
  box-shadow: 0 5px 18px rgba(2,6,23,0.34), inset 0 1px 0 rgba(255,255,255,0.19);
  transition: all .3s cubic-bezier(.22,1,.36,1);
  position: relative;
  overflow: hidden;
}

.stButton > button::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(115deg, transparent 35%, rgba(255,255,255,0.30) 50%, transparent 65%);
  transform: translateX(-130%);
  transition: transform .7s ease;
}
.stButton > button:hover::before { transform: translateX(130%); }

.stButton > button:hover {
  transform: translateY(-2.5px);
  border-color: rgba(125,211,252,0.5) !important;
  box-shadow: 0 12px 32px rgba(56,189,248,0.26), inset 0 1px 0 rgba(255,255,255,0.26);
  color: #f8fafc !important;
}

.stButton > button:active { transform: translateY(0) scale(0.975); }

/* 主按钮(查询/提问):实心液态渐变 */
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {
  background: linear-gradient(120deg, #0ea5e9, #6366f1 48%, #a855f7) !important;
  background-size: 200% auto !important;
  border: 1px solid rgba(255,255,255,0.26) !important;
  color: #ffffff !important;
  box-shadow: 0 8px 28px rgba(99,102,241,0.42), inset 0 1px 0 rgba(255,255,255,0.30);
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="baseButton-primary"]:hover {
  background-position: right center !important;
  box-shadow: 0 14px 38px rgba(168,85,247,0.50), inset 0 1px 0 rgba(255,255,255,0.34);
  transform: translateY(-2.5px) scale(1.012);
}

/* ========== 输入控件:玻璃质感 ========== */
.stTextInput input, .stNumberInput input, .stTextArea textarea {
  background: rgba(255,255,255,0.075) !important;
  border: 1px solid rgba(255,255,255,0.15) !important;
  border-radius: 13px !important;
  color: #f1f5f9 !important;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  transition: all .3s ease;
}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {
  border-color: rgba(125,211,252,0.65) !important;
  box-shadow: 0 0 0 3px rgba(56,189,248,0.19), inset 0 1px 0 rgba(255,255,255,0.14) !important;
  background: rgba(255,255,255,0.105) !important;
}
.stTextInput input::placeholder { color: #7d90a8 !important; }

/* 下拉/多选 */
[data-baseweb="select"] > div {
  background: rgba(255,255,255,0.075) !important;
  border: 1px solid rgba(255,255,255,0.15) !important;
  border-radius: 13px !important;
  color: #f1f5f9 !important;
  backdrop-filter: blur(14px);
  transition: all .3s ease;
}
[data-baseweb="select"] > div:hover { border-color: rgba(125,211,252,0.45) !important; }
[data-baseweb="tag"] {
  background: linear-gradient(135deg, rgba(56,189,248,0.34), rgba(168,85,247,0.34)) !important;
  border-radius: 9px !important;
  border: 1px solid rgba(255,255,255,0.19) !important;
}

/* 弹层(下拉菜单) */
[data-baseweb="popover"] div[role="listbox"] {
  background: rgba(15,23,42,0.92) !important;
  backdrop-filter: blur(22px);
  -webkit-backdrop-filter: blur(22px);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 15px;
}

/* 滑块 */
[data-testid="stSlider"] [role="slider"] {
  background: linear-gradient(135deg, #38bdf8, #a855f7) !important;
  box-shadow: 0 0 16px rgba(56,189,248,0.6);
}
[data-testid="stSlider"] [data-baseweb="slider"] div[role="presentation"] > div {
  background: linear-gradient(90deg, #38bdf8, #a855f7) !important;
}

/* 复选框 / 单选 */
[data-testid="stCheckbox"] [data-baseweb="checkbox"] span,
[data-testid="stRadio"] [data-baseweb="radio"] span { border-color: rgba(255,255,255,0.35) !important; }

/* ========== 数据表格 ========== */
[data-testid="stDataFrame"] { padding: 6px; }
[data-testid="stDataFrame"] * { color: #e2e8f0 !important; }

/* ========== 提示/警告/成功框:玻璃化 ========== */
[data-testid="stAlert"] {
  background: rgba(255,255,255,0.085) !important;
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  border: 1px solid rgba(255,255,255,0.16) !important;
  border-radius: 16px !important;
  box-shadow: 0 8px 26px rgba(2,6,23,0.38), inset 0 1px 0 rgba(255,255,255,0.17);
  color: #e2e8f0 !important;
}

/* ========== 图表容器玻璃化 ========== */
[data-testid="stArrowVegaLiteChart"],
[data-testid="stVegaLiteChart"] {
  background: linear-gradient(135deg, rgba(255,255,255,0.085), rgba(255,255,255,0.028));
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  border: 1px solid rgba(255,255,255,0.13);
  border-radius: 20px;
  padding: 14px;
  box-shadow: 0 8px 30px rgba(2,6,23,0.4), inset 0 1px 0 rgba(255,255,255,0.16);
}

/* iframe(知识图谱)玻璃容器 */
[data-testid="stIFrame"] {
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.14);
  box-shadow: 0 14px 44px rgba(2,6,23,0.5), inset 0 1px 0 rgba(255,255,255,0.14);
}

/* Expander 展开器 */
div[data-testid="stExpander"] summary {
  color: #cbd5e1 !important;
  font-weight: 600;
  border-radius: 16px;
}
div[data-testid="stExpander"] summary:hover { color: #7dd3fc !important; }

/* 代码块 */
.stApp code, .stApp pre {
  background: rgba(15,23,42,0.72) !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
  border-radius: 12px !important;
  color: #a5f3fc !important;
}

/* 侧边栏(如出现) */
[data-testid="stSidebar"] {
  background: rgba(10,15,28,0.86) !important;
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border-right: 1px solid rgba(255,255,255,0.1);
}

/* 滚动条 */
::-webkit-scrollbar { width: 11px; height: 11px; }
::-webkit-scrollbar-track { background: rgba(255,255,255,0.035); border-radius: 8px; }
::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, rgba(56,189,248,0.55), rgba(168,85,247,0.55));
  border-radius: 8px;
  border: 2px solid transparent;
  background-clip: content-box;
}
::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(180deg, rgba(56,189,248,0.8), rgba(168,85,247,0.8));
  background-clip: content-box;
}

/* 顶栏透明化:保留最小高度,避免内容顶到屏幕边缘 */
[data-testid="stHeader"] {
  background: transparent !important;
  height: 2.8rem !important;
  min-height: 2.8rem !important;
}
[data-testid="stToolbar"] { right: 1rem; }

/* ========== 沉浸式对话区 ========== */
/* 减弱聊天气泡的分割感:去掉边框和厚重背景,让它融进页面 */
[data-testid="stChatMessage"] {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0.35rem 0 !important;
}
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatar"] {
  background: rgba(255,255,255,0.10) !important;
  border: 1px solid rgba(255,255,255,0.16) !important;
}
/* 助手消息:淡淡的玻璃底色,不用强边框 */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
  background: rgba(255,255,255,0.035) !important;
  border-radius: 16px !important;
  padding: 0.6rem 0.9rem !important;
}

/* 底部输入区:融入背景,不要割裂感 */
/* 底栏容器保持透明,让页面背景透上来 */
[data-testid="stBottom"],
[data-testid="stBottomBlockContainer"],
[data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"] > div {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

/* 只在输入框正下方加一层柔和光晕,而不是整块纯色背景 */
[data-testid="stChatInput"] {
  background: linear-gradient(135deg,
    rgba(255,255,255,0.10) 0%,
    rgba(125,211,252,0.07) 45%,
    rgba(168,85,247,0.07) 100%) !important;
  backdrop-filter: blur(26px) saturate(170%);
  -webkit-backdrop-filter: blur(26px) saturate(170%);
  border: 1px solid rgba(255,255,255,0.18) !important;
  border-radius: 22px !important;
  box-shadow:
    0 12px 40px rgba(2,6,23,0.55),
    0 0 0 1px rgba(125,211,252,0.06),
    inset 0 1px 0 rgba(255,255,255,0.20);
  transition: all .3s ease;
}
[data-testid="stChatInput"]:focus-within {
  border-color: rgba(125,211,252,0.45) !important;
  box-shadow:
    0 14px 46px rgba(56,189,248,0.22),
    inset 0 1px 0 rgba(255,255,255,0.26);
}
[data-testid="stChatInput"] textarea,
[data-testid="stChatInput"] input {
  background: transparent !important;
  border: none !important;
  color: #f1f5f9 !important;
}
[data-testid="stChatInput"] textarea::placeholder,
[data-testid="stChatInput"] input::placeholder { color: #7d90a8 !important; }

/* 输入框上方极淡的渐变,让对话内容自然"淡出"到输入框 */
.stApp [data-testid="stBottom"]::before {
  content: '';
  position: absolute;
  left: 0; right: 0; top: -40px;
  height: 40px;
  background: linear-gradient(to bottom, transparent, rgba(7,11,20,0.5));
  pointer-events: none;
}

/* 汉堡菜单(popover)样式 */
[data-testid="stPopover"] {
  margin-top: 1.7rem;
}
[data-testid="stPopover"] > button {
  border-radius: 13px !important;
  border: 1px solid rgba(255,255,255,0.16) !important;
  background: rgba(255,255,255,0.07) !important;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  color: #dbe6f3 !important;
  font-size: 19px !important;
  padding: 0.3rem 0.7rem !important;
  transition: all .3s ease;
}
[data-testid="stPopover"] > button:hover {
  border-color: rgba(125,211,252,0.5) !important;
  box-shadow: 0 6px 22px rgba(56,189,248,0.25);
  transform: translateY(-1px);
}
[data-testid="stPopoverBody"] {
  background: rgba(15,23,42,0.94) !important;
  backdrop-filter: blur(24px) saturate(160%);
  -webkit-backdrop-filter: blur(24px) saturate(160%);
  border: 1px solid rgba(255,255,255,0.15) !important;
  border-radius: 16px !important;
  box-shadow: 0 18px 50px rgba(2,6,23,0.6);
}

/* 分割线:更柔和 */
hr {
  border-color: rgba(255,255,255,0.06) !important;
  margin: 1.6rem 0 !important;
}

/* ========== 入场动画 ========== */
@keyframes fadeSlideUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}

[data-testid="stMetric"],
.stTabs [role="tablist"],
[data-testid="stArrowVegaLiteChart"],
[data-testid="stVegaLiteChart"] {
  animation: fadeSlideUp .7s cubic-bezier(.22,1,.36,1) both;
}
[data-testid="stMetric"]:nth-of-type(2) { animation-delay: .08s; }
[data-testid="stMetric"]:nth-of-type(3) { animation-delay: .16s; }
[data-testid="stMetric"]:nth-of-type(4) { animation-delay: .24s; }
[data-testid="stMetric"]:nth-of-type(5) { animation-delay: .32s; }

/* ========== 移动端适配 ========== */
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"] { padding-left: 0.9rem; padding-right: 0.9rem; }
  h1 { font-size: 2rem !important; }
  .stTabs [role="tab"] { padding: 0 12px; font-size: 0.85rem; height: 42px; }
  [data-testid="stMetric"] { border-radius: 16px !important; }
  [data-testid="stMetricValue"] { font-size: 1.5rem !important; }
}

/* 页脚文字淡出 */
footer { visibility: hidden; }
</style>
"""


def inject_liquid_theme():
    """注入液态玻璃主题 CSS(每次 rerun 都注入,幂等)。"""
    st.markdown(LIQUID_CSS, unsafe_allow_html=True)
