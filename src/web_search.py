"""联网搜索:为知识图谱问答补充实时信息(天气/活动/营业变动等)。

设计:
  - 结构化信息(商家名称、评分、人均、营业时间、电话)由图谱提供
  - 实时/外部信息(天气、活动、临时变动)由联网搜索补充
  - 所有联网信息**必须标注来源**,便于用户核实
"""
import html
import re
import warnings

warnings.filterwarnings("ignore")

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

BING = "https://cn.bing.com/search"


def truncate(s: str, n: int = 160) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def web_search(query: str, max_results: int = 4, timeout: int = 12) -> list:
    """执行联网搜索,返回带来源的结果列表。

    [{"title": ..., "url": ..., "snippet": ..., "source": "域名"}, ...]
    """
    try:
        r = requests.get(
            BING, params={"q": query, "setlang": "zh-CN", "ensearch": "0"},
            headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=timeout,
        )
        r.raise_for_status()
    except Exception:
        return []

    results = []
    blocks = re.findall(r'<li class="b_algo".*?</li>', r.text, re.S)
    for b in blocks:
        # 标题与链接:在 <h2> 内找第一个 http 链接
        hrefs = re.findall(r'href="(https?://[^"]+)"', b)
        url = next((h for h in hrefs if "bing.com" not in h and "microsoft" not in h), None)
        if not url:
            continue
        title = ""
        h2 = re.search(r"<h2[^>]*>(.*?)</h2>", b, re.S)
        if h2:
            title = strip_tags(h2.group(1))
        if not title:
            continue

        snippet = ""
        for pat in (r'<p class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</p>',
                    r"<p[^>]*>(.*?)</p>"):
            m = re.search(pat, b, re.S)
            if m:
                snippet = strip_tags(m.group(1))
                break

        results.append({
            "title": truncate(title, 90),
            "url": url,
            "snippet": truncate(snippet, 200),
            "source": _domain(url),
        })
        if len(results) >= max_results:
            break

    return results


def _domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    if not m:
        return "未知来源"
    host = m.group(1).replace("www.", "")
    # 常见站点中文名
    names = {
        "baike.baidu.com": "百度百科", "zhihu.com": "知乎", "weibo.com": "微博",
        "douyin.com": "抖音", "meituan.com": "美团", "dianping.com": "大众点评",
        "ctrip.com": "携程", "qunar.com": "去哪儿", "mafengwo.cn": "马蜂窝",
        "gov.cn": "政府网站", "xinhuanet.com": "新华网", "people.com.cn": "人民网",
        "amap.com": "高德地图", "baidu.com": "百度", "sohu.com": "搜狐",
        "163.com": "网易", "qq.com": "腾讯网", "toutiao.com": "今日头条",
    }
    for k, v in names.items():
        if host.endswith(k):
            return v
    return host


def dedupe(results: list) -> list:
    """按域名去重,让来源更多样。"""
    seen, out = set(), []
    for r in results:
        if r["source"] in seen:
            continue
        seen.add(r["source"])
        out.append(r)
    return out
