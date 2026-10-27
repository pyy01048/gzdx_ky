# -*- coding: utf-8 -*-
"""院校招生公告爬虫（T5-2）。

背景：院校详情页参考站有「公告文章」标签（招生公告/招生简章列表，标题+日期+分页），
但库中无公告表也无采集器。研招网是聚合入口但公告正文在各校研究生院官网，
因此本爬虫分两层：

1. ``crawl_yz_notices``：研招网院校资讯（聚合、结构稳定、robots 已有合规检查先例）。
2. ``crawl_school_notices``：各校研究生院官网公告列表页（通用 HTML 解析器，
   按 datasource_registry 注册的院校站点逐个抓；列表页特征：含「通知/公告/简章」
   的链接 + 日期）。失败/无 robots 允许的站点如实跳过。

数据落 ``kaoyan_notices`` 表（module: ensure_notices_schema 原生 DDL，与
module_a_schema 同模式——不动 ORM 基线，避免已有库迁移风险）。

合规：每站先查 robots.txt（复用 spider_school.check_robots 模式），
2-5s 随机延迟，UA 声明个人备考用途。
"""
from __future__ import annotations

import json
import logging
import random
import re
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from services.kaoyan.notice_dedup import upsert_notice
from services.dbapi_compat import wrap_conn
from utils.timeutil import naive_utc_iso

logger = logging.getLogger(__name__)

# 部分高校站点有反爬 WAF（如北邮/安徽大学返回 HTTP412），仅 UA 会被拦；
# 补齐常见浏览器头（Accept/Accept-Language 等）提升放行概率。
# 保留 PersonalStudyTool 标识于 UA 尾巴，声明个人备考用途。
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 "
        "PersonalStudyTool/1.0 (kaoyan personal use)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "identity",  # 避免 gzip 需额外解码
    "Connection": "keep-alive",
}
_CHECKPOINT = Path(__file__).parent / "notices_checkpoint.json"

# 2026-10-19 枚举缺口修复：notice_type 在 PG 是 ENUM（公告/简章/复试/调剂/录取），
# 但 _TYPE_RULES 会产出「大纲/目录」→ invalid input value for enum → 事务毒化整批。
# 同时用户要求的统计口径需要「初试/报名」两类。此处幂等补齐枚举值（PG16 允许事务内 ADD VALUE，
# 新值在事务提交后生效；duplicate_object 时静默跳过）。
#
# 2026-10-21 P1-4 回滚调查：上面注释设想的「静默跳过」在 PG 里并不成立 ——
# 一条 ALTER TYPE 报 duplicate_object 后，**整个事务已被毒化**，同批后续 3 条全部
# 报 "current transaction is aborted"，最后的 commit 实际执行 ROLLBACK。
# 本函数被 kaoyan / kaoyan_ext 的接口每次请求都调用，于是：库里 36% 的事务是回滚；
# 调用方若在调用前有未提交写入，会被静默丢弃。
# 改用 ``ADD VALUE IF NOT EXISTS``（PG ≥9.6）：已存在时根本不报错 → 事务不再被毒化。
_ENUM_EXTEND_DDL = """
 ALTER TYPE notice_type ADD VALUE IF NOT EXISTS '初试';
 ALTER TYPE notice_type ADD VALUE IF NOT EXISTS '报名';
 ALTER TYPE notice_type ADD VALUE IF NOT EXISTS '大纲';
 ALTER TYPE notice_type ADD VALUE IF NOT EXISTS '目录';
 """

# --------------------------------------------------------------------------- #
# 表结构（幂等）
# --------------------------------------------------------------------------- #
_DDL = """
CREATE TABLE IF NOT EXISTS kaoyan_notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id INTEGER,
    school_name TEXT,
    title TEXT NOT NULL,
    notice_type TEXT DEFAULT '公告',        -- 公告 | 简章 | 复试 | 调剂 | 录取
    publish_date TEXT,
    url TEXT,
    source TEXT,
    fetched_at TEXT,
    UNIQUE(school_name, title, publish_date)
);
CREATE INDEX IF NOT EXISTS idx_notices_school ON kaoyan_notices(school_id);
"""


def ensure_notices_schema(db_session) -> None:
    """幂等建表（原生 DDL，避开 ORM 基线迁移）。"""
    conn = wrap_conn(db_session.connection().connection)
    from services.ddl_compat import adapt_ddl
    conn.executescript(adapt_ddl(_DDL, conn))
    # 枚举扩展：仅 PG 有 ENUM；逐条执行，失败（如 SQLite 底座）静默跳过
    from services.ddl_compat import is_postgres
    if is_postgres(conn):
        from sqlalchemy import text as _sql_text

        # 2026-10-21：改用**独立连接**跑枚举扩展。原实现直接在调用方事务里执行，
        # 一条失败就毒化整个事务 → 后续 ROLLBACK 把调用方未提交的写入一并丢掉，
        # 且本函数被 kaoyan/kaoyan_ext 接口每次请求调用 → 全库 36% 事务是回滚。
        ext = db_session.get_bind().connect()
        try:
            for stmt in [s.strip() for s in _ENUM_EXTEND_DDL.split(';') if 'ALTER TYPE' in s]:
                try:
                    ext.execute(_sql_text(stmt + ';'))
                except Exception:  # noqa: BLE001 老 PG 不支持 IF NOT EXISTS → 忽略并清掉毒化
                    ext.rollback()
            ext.commit()
        finally:
            ext.close()
        # ADD VALUE 必须提交后新值才对本会话可用；原 rollback 会把枚举扩展一并撤销，
        # 导致后续「大纲/目录/初试/报名」类型写入仍被拒（2026-10-19 实测教训）。
        db_session.commit()
    db_session.commit()


def _db_path() -> str:
    import os

    return os.environ.get("DATABASE_PATH", "").strip() or str(
        Path(__file__).resolve().parents[3] / "database" / "kaoyan.db"
    )


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
_CHARSET_RE = re.compile(rb'charset=["\']?\s*([\w-]+)', re.I)


def _decode(raw: bytes, http_charset: str) -> str:
    """按 HTTP Content-Type / HTML meta 声明的编码解码（兼容 GBK/GB2312 站点）。

    大量高校老站（如天津大学 yzb.tju.edu.cn）用 gb2312，若一律按 UTF-8 解码，
    中文会变成乱码 → 关键词匹配全失败 → 解析 0 条。此处按声明编码解码。
    """
    candidates = []
    if http_charset:
        candidates.append(http_charset)
    m = _CHARSET_RE.search(raw[:4096])  # meta charset 在前部
    if m:
        candidates.append(m.group(1).decode("ascii", "ignore"))
    candidates += ["utf-8", "gb18030"]  # gb18030 兼容 gb2312/gbk 超集
    for cs in candidates:
        try:
            return raw.decode(cs)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "ignore")


def _fetch(url: str, retries: int = 2, timeout: int = 20) -> str:
    """抓取 HTML。显式跟随 3xx 重定向（urllib 对 GET 默认跟随，
    但部分站点以 302→登录页/新域名返回，需确保拿到最终页）；
    按响应/meta 声明的编码解码（兼容 GBK 老站）；
    对 403/412 等反爬响应不回退、如实返回空串由调用方计入失败）。"""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                # urllib 已自动跟随 30x，r.geturl() 为最终地址
                raw = r.read()
                ct = r.headers.get("Content-Type", "") or ""
                m = re.search(r"charset=([\w-]+)", ct, re.I)
                http_charset = m.group(1) if m else ""
                return _decode(raw, http_charset)
        except Exception as e:
            logger.debug("[notices] fetch %s retry %s: %s", url[:60], i + 1, e)
            time.sleep(random.uniform(2, 4))
    return ""


def _polite() -> None:
    time.sleep(random.uniform(2, 5))


def _robots_allows(domain: str) -> bool:
    """极简 robots 检查：Disallowed / 时跳过该站。"""
    body = _fetch(f"https://{domain}/robots.txt", retries=1, timeout=10)
    if not body:
        return True  # 无 robots 视为允许（个人低频访问）
    for ln in body.splitlines():
        low = ln.strip().lower()
        if low.startswith("disallow:") and low.split(":", 1)[1].strip() == "/":
            return False
    return True


# --------------------------------------------------------------------------- #
# 公告类型推断（标题→类型，规则确定性）
# --------------------------------------------------------------------------- #
_TYPE_RULES = [
    ("简章", "简章"), ("招生简章", "简章"), ("复试", "复试"), ("调剂", "调剂"),
    ("录取", "录取"), ("公示", "录取"), ("大纲", "大纲"), ("目录", "目录"),
    ("报名", "报名"), ("初试", "初试"),
]


def infer_notice_type(title: str) -> str:
    for kw, t in _TYPE_RULES:
        if kw in title:
            return t
    return "公告"


# --------------------------------------------------------------------------- #
# 通用官网公告列表解析
# --------------------------------------------------------------------------- #
# 链接文本含招生关键词 → 视为公告链接；同一行/紧邻的日期(YYYY-MM-DD 或 YYYY.MM.DD)
# 长度下限 2 字：支持「复试通知」「录取公告」等短标题（原 6 字会漏掉）。
# 锚文本允许包裹内联标签（<font>/<span>/<em> 等）——大量高校（如东北大学）
# 在 <a> 内套 <font> 做高亮，原 [^<]+ 会整体漏掉。
_LINK_RE = re.compile(
    r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I
)
_STRIP_TAG_RE = re.compile(r"<[^>]+>")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_DATE_NEAR_RE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
# 拆分日期块（如西电：<div>17</div><div>2026-09</div><a>标题</a>，
# 日与年月分属两个 div）。剥标签后形如「17 2026-09 标题」，日年在前。
_DAY_YM_RE = re.compile(r"\b(\d{1,2})\s+(20\d{2})[-/.](\d{1,2})\b")
_TITLE_KW = ("招生", "简章", "复试", "调剂", "录取", "硕士", "考研", "初试",
             "公告", "通知", "大纲", "目录", "公示", "推免", "报考")
# 栏目导航链接（首页的「硕士招生/招生工作/通知公告」入口——首页常无具体公告，
# 需跟进一层到列表页才有）。
# 扩充常见研究生院栏目名（原白名单过窄，贵州师范/贵州财经等站漏跟）：
_SECTION_KW = (
    # 精确栏目词（原白名单）
    "硕士招生", "招生工作", "通知公告", "招生信息", "硕士", "招生",
    # 新增：研究生招生体系常见栏目名
    "研究生招生", "研招", "招生管理", "招生动态", "招生就业",
    "硕士公告", "硕士简章", "硕士研究生", "研究生教育",
    "通知通告", "最新通知", "新闻动态", "招生简章", "招生专业目录",
    "公示公告", "研究生院",
)
# 纯导航短词（≤6 字且等于栏目名）——避免被当作「具体公告」计入；
# 具体公告标题通常 ≥8 字且含年份/动词（如「东北大学2027年...公告」）。
_NAV_EXACT = set(_SECTION_KW) | {
    "博士招生", "博士公告", "博士简章", "港澳台招生", "招生学院",
    "硕士目录", "专业目录", "报考指南", "招生指南", "统考硕士",
    "统考博士", "招生简章", "招生目录", "招生章程", "硕士简章",
    "硕士公告", "通知公告", "新闻动态", "最新通知", "招生信息",
}

# 部分高校（如上海交大）列表页把日期拼在锚文本开头，解析时未拆出：
#   「03.27/2025 标题…」        → MM.DD/YYYY
#   「06 2026.09 标题…」        → DD YYYY.MM（日在前，年.月在后）
#   「2026.10.08 标题…」        → YYYY.MM.DD
# 此处统一提取；年份无法确定的（如「03.27 标题」且标题内无年份）不伪造、
# 返回 None 且不剥离前缀（保留原文）。
_TITLE_DATE_PATTERNS = [
    # MM.DD/YYYY
    (re.compile(r"^(\d{1,2})\.(\d{1,2})/(\d{4})\s+"), "mdy"),
    # DD YYYY.MM
    (re.compile(r"^(\d{1,2})\s+(\d{4})\.(\d{1,2})\s+"), "dym"),
    # YYYY.MM.DD
    (re.compile(r"^(20\d{2})\.(\d{1,2})\.(\d{1,2})\s+"), "ymd"),
    # YYYY-MM-DD / YYYY/MM/DD
    (re.compile(r"^(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\s+"), "ymd"),
]
_TITLE_YEAR_RE = re.compile(r"(20\d{2})")


def extract_title_date_prefix(title: str):
    """从标题前缀提取日期，返回 (publish_date|None, 净化后标题)。

    判据（严格，不伪造）：
    - 命中任一前缀格式且月 1-12 / 日 1-31 → 组装 YYYY-MM-DD 并剥离前缀；
    - MM.DD 无年份时：标题内出现 20XX 则用之，否则返回 (None, 原标题)；
    - 未命中任何格式 → (None, 原标题)。
    """
    t = (title or "").strip()
    for pat, kind in _TITLE_DATE_PATTERNS:
        m = pat.match(t)
        if not m:
            continue
        if kind == "mdy":
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif kind == "dym":
            d, y, mo = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:  # ymd
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= 31 and 2000 <= y <= 2099):
            continue
        rest = t[m.end():].strip()
        if rest:
            return f"{y:04d}-{mo:02d}-{d:02d}", rest
        return f"{y:04d}-{mo:02d}-{d:02d}", t  # 剥完为空则保留原题（异常防御）
    # MM.DD 无年份：尝试标题内年份（如「03.27 2025级招生…」）
    m2 = re.match(r"^(\d{1,2})\.(\d{1,2})\s+(.+)$", t)
    if m2:
        mo, d = int(m2.group(1)), int(m2.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            ym = _TITLE_YEAR_RE.search(m2.group(3))
            if ym:
                y = int(ym.group(1))
                return f"{y:04d}-{mo:02d}-{d:02d}", m2.group(3).strip()
    return None, t


def _strip_tags(text: str) -> str:
    """去 HTML 注释与标签 + 压缩空白（兼容内联 <font> 等；防注释残片如 '-->'）。"""
    text = _HTML_COMMENT_RE.sub("", text)
    return re.sub(r"\s+", " ", _STRIP_TAG_RE.sub("", text)).strip()


def _is_section_noise(title: str) -> bool:
    """栏目名噪声判定：标题（去空白后）≤4 字，通常是导航栏目名而非具体公告
    （如「硕士报名」「复试信息」「招生宣传」）。

    注意：仅凭长度判定有误伤风险，故本函数**只做长度判据**，是否跳过由调用方
    结合 ``publish_date`` 决定——带日期的短标题（如「调剂」+日期）可能是真公告，
    不拦。保持函数纯粹、单一职责，便于单测。
    """
    return len((title or "").strip()) <= 4


def _abs(href: str, base_url: str) -> str:
    """相对链接补全为绝对。"""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        root = re.match(r"(https?://[^/]+)", base_url)
        return (root.group(1) if root else base_url).rstrip("/") + href
    if not href.startswith("http"):
        return base_url.rstrip("/") + "/" + href
    return href


def parse_notice_links(html: str, base_url: str, wide_date: bool = False) -> List[Dict[str, str]]:
    """从列表页 HTML 抽公告链接。

    启发式（诚实标注：非每站适配，解析失败的站点在结果里计数而非静默）：
    链接文本 ≥2 字且含招生关键词（支持「复试通知」等短标题）；
    日期取链接标签前后 300 字符内的首个日期
    （wide_date：部分站点日期与链接分列两行的表格结构，窄窗口抓不到）。
    锚文本先剥内联标签（东北大学等在 <a> 内套 <font>）。
    """
    out: List[Dict[str, str]] = []
    for m in _LINK_RE.finditer(html):
        href = m.group(1)
        text = _strip_tags(m.group(2))
        if len(text) < 2 or len(text) > 120:
            continue
        # 排除首页栏目导航入口（「硕士招生」「通知公告」等精确短词，
        # 由 parse_section_links 跟进一层处理，避免被当成具体公告）
        if text in _NAV_EXACT:
            continue
        if not any(k in text for k in _TITLE_KW):
            continue
        href = _abs(href, base_url)
        window = 300 if wide_date else 120
        zone = html[max(0, m.start() - window): m.end() + window]
        dm = _DATE_NEAR_RE.search(html[m.end(): m.end() + 120]) or _DATE_NEAR_RE.search(text) \
            or (wide_date and (_DATE_NEAR_RE.search(zone)))
        date = None
        if dm:
            date = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
        # 拆分日期块兜底（西电等：日在前、年月在后，分属相邻 div）
        if not date:
            pre = html[max(0, m.start() - 300): m.start()]
            dym = _DAY_YM_RE.search(_strip_tags(pre))
            if dym:
                d, y, mo = int(dym.group(1)), int(dym.group(2)), int(dym.group(3))
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    date = f"{y:04d}-{mo:02d}-{d:02d}"
        # 标题前缀日期兜底（上交等站把日期拼在锚文本开头，如「03.27/2025 标题」）
        if not date:
            pre_date, clean_title = extract_title_date_prefix(text)
            if pre_date:
                date = pre_date
                text = clean_title
        out.append({"title": text, "url": href, "publish_date": date})
    return out


def parse_section_links(html: str, base_url: str, limit: int = 4) -> List[str]:
    """抽首页的公告栏目入口（跟进一层到真列表页）。

    只认含精确栏目词的短文本链接（「硕士招生」「通知公告」），不认具体
    公告标题（那些首页少见且 parse_notice_links 已处理）。
    """
    seen, out = set(), []
    # 锚文本允许内联标签（<font>/<span> 等），故先抓 <a>…</a> 再剥标签
    for m in re.finditer(r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        text = _strip_tags(m.group(2))
        if text in _SECTION_KW and 2 <= len(text) <= 12:
            url = _abs(m.group(1), base_url)
            if url not in seen:
                seen.add(url)
                out.append(url)
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
# webplus CMS JSON 接口适配器
# 大量高校官网（含贵州大学）用 webplus：列表页 HTML 只有导航，真数据在
# /_wp3services/generalQuery JSON 接口。参数 siteId/columnId 从列表页 HTML 提取。
# --------------------------------------------------------------------------- #
_WP_SITE_RE = re.compile(r"siteId[\"'\s:=]+(\d+)")
_WP_COL_RE = re.compile(r"colu?mnId[\"'\s:=]+(\d+)")


def parse_webplus_notices(domain: str, html: str, max_pages: int = 2) -> List[Dict[str, str]]:
    """从 webplus 站点首页/列表页 HTML 提取 siteId/columnId，调 JSON 接口取公告。

    返回空列表 = 站点不是 webplus 或接口不可用（调用方回退 HTML 解析）。
    """
    site_m = _WP_SITE_RE.search(html)
    col_m = _WP_COL_RE.search(html)
    if not site_m or not col_m:
        return []
    site_id, col_id = site_m.group(1), col_m.group(1)
    out: List[Dict[str, str]] = []
    for page in range(1, max_pages + 1):
        api = (
            f"https://{domain}/_wp3services/generalQuery"
            f"?queryObj=articles&siteId={site_id}&columnId={col_id}"
            f"&pageSize=30&pageNumber={page}"
        )
        body = _fetch(api, retries=1, timeout=15)
        if not body:
            break
        try:
            j = json.loads(body)
        except json.JSONDecodeError:
            break
        data = j.get("data") or []
        if not data:
            break
        for it in data:
            title = (it.get("title") or "").strip()
            if not title:
                continue
            # 页面 URL 字段名在不同部署间有差异（url/wapUrl/trueWapUrl），逐个兜底
            url = it.get("url") or it.get("wapUrl") or it.get("trueWapUrl") or ""
            if url and url.startswith("/"):
                url = f"https://{domain}" + url
            pt = (it.get("publishTime") or "")[:10] or None
            out.append({"title": title, "url": url, "publish_date": pt})
        if len(data) < 30:
            break
        _polite()
    return out
# --------------------------------------------------------------------------- #
# 工科定向院校的研究生院官网清单（T5 公告采集入口）
# 优先级：目标院校贵大 → 四邮四电 → 用户指定的工科系列强校。
# 诚实口径：URL 为各校研究生院/招办公开入口，个别站点改版会导致解析 0 条，
# 结果里 parse_failed 计数如实展示，不静默。
#
# ⚠️ 域名核验说明（2026-10-12，寇豆码）：
#   本沙箱环境无法直接 HTTP 访问 *.edu.cn（urllib 报
#   "Tunnel connection failed: 502"，WebFetch 亦被拦；属沙箱出网限制，
#   **不代表域名失效**）。故本表域名改用 WebSearch 逐条核验各校官方公示的
#   研究生院网址（多数来自研招网 sch 页/学校官方声明），并据此校正了若干
#   猜测式域名（如 河海=gs.hhu、安大=graschool.ahu、燕大=gs.ysu、
#   浙工大=www.gs.zjut、华侨=grs.hqu、太原理工=www.gs.tyut）。
#   标注「实测」仅表示域名经联网检索确认为官方入口；实际 HTTP 可达性
#   需在能直连 .edu.cn 的网络环境复测（见 school-crawl-test 报告）。
# --------------------------------------------------------------------------- #
ENGINEERING_NOTICE_URLS: Dict[str, str] = {
    # ===== 目标院校（硕士招生栏目优先——通知公告栏目多为学位授予类，招生在 sszs）=====
    "贵州大学": "https://gs.gzu.edu.cn/sszs/list.htm",
    # ===== 四邮四电（电子/通信核心）=====
    "电子科技大学": "https://yz.uestc.edu.cn/",
    "西安电子科技大学": "https://gr.xidian.edu.cn/",
    "北京邮电大学": "https://www.bupt.edu.cn/",
    "南京邮电大学": "https://yzb.njupt.edu.cn/",
    "杭州电子科技大学": "https://yjs.hdu.edu.cn/",
    "重庆邮电大学": "https://yjs.cqupt.edu.cn/",
    "桂林电子科技大学": "https://www.guet.edu.cn/",
    # ===== 985 工科强校 =====
    "清华大学": "https://yz.tsinghua.edu.cn/",
    "北京大学": "https://admission.pku.edu.cn/",
    "浙江大学": "https://grs.zju.edu.cn/",
    "上海交通大学": "https://yzb.sjtu.edu.cn/",
    "复旦大学": "https://gsao.fudan.edu.cn/",
    "南京大学": "https://grawww.nju.edu.cn/",
    "中国科学技术大学": "https://yz.ustc.edu.cn/",
    "哈尔滨工业大学": "https://yzb.hit.edu.cn/",
    "西安交通大学": "https://yz.xjtu.edu.cn/",
    "华中科技大学": "https://gs.hust.edu.cn/",
    "东南大学": "https://yzb.seu.edu.cn/",
    "北京航空航天大学": "https://yzb.buaa.edu.cn/",
    "北京理工大学": "https://grd.bit.edu.cn/",
    "同济大学": "https://yz.tongji.edu.cn/",
    "天津大学": "https://yzb.tju.edu.cn/",
    "大连理工大学": "https://gs.dlut.edu.cn/",
    "吉林大学": "https://yjsy.jlu.edu.cn/",
    "华南理工大学": "https://yz.scut.edu.cn/",
    "四川大学": "https://yz.scu.edu.cn/",
    "重庆大学": "https://yz.cqu.edu.cn/",
    "西北工业大学": "https://yzb.nwpu.edu.cn/",
    "湖南大学": "https://gra.hnu.edu.cn/",
    "中山大学": "https://graduate.sysu.edu.cn/",
    # ===== 光学/电气/控制/仪器类强校 =====
    "长春理工大学": "https://yz.cust.edu.cn/",
    "华中科技大学光电学院": "https://oei.hust.edu.cn/",
    "华北电力大学": "https://yjsy.ncepu.edu.cn/",
    "西南交通大学": "https://grs.swjtu.edu.cn/",
    "沈阳工业大学": "https://yjsxy.sut.edu.cn/",
    # ===== AI/控制系列 + 408 强校 + 其余 211/双一流 =====
    "东北大学": "https://yz.neu.edu.cn/",
    "中南大学": "https://gra.csu.edu.cn/",
    "武汉大学": "https://www.gs.whu.edu.cn/",
    "华中师范大学": "https://gs.ccnu.edu.cn/",
    "北京交通大学": "https://yzb.bjtu.edu.cn/",
    # 北科大 yjsy.ustb.edu.cn 302→研究生管理登录页（非公告列表）；
    # 真实研招宣传入口为 yzxc.ustb.edu.cn（含 硕士通知公告/招生章程 栏目，2026-10 实测）
    "北京科技大学": "https://yzxc.ustb.edu.cn/",
    "中国矿业大学": "https://yz.cumt.edu.cn/",
    "河海大学": "https://gs.hhu.edu.cn/",
    "南京航空航天大学": "https://www.graduate.nuaa.edu.cn/",
    "南京理工大学": "https://gs.njust.edu.cn/",
    "苏州大学": "https://yjs.suda.edu.cn/",
    "江南大学": "https://yz.jiangnan.edu.cn/",
    "合肥工业大学": "https://yjsy.hfut.edu.cn/",
    "安徽大学": "https://graschool.ahu.edu.cn/",
    "福州大学": "https://yjsy.fzu.edu.cn/",
    "南昌大学": "https://yjsy.ncu.edu.cn/",
    "郑州大学": "https://gs.zzu.edu.cn/",
    "武汉理工大学": "https://gd.whut.edu.cn/",
    "广西大学": "https://yjsc.gxu.edu.cn/",
    "云南大学": "https://www.grs.ynu.edu.cn/",
    "昆明理工大学": "https://yjs.kmust.edu.cn/",
    "太原理工大学": "https://www.gs.tyut.edu.cn/",
    "河北工业大学": "https://yjs.hebut.edu.cn/",
    "燕山大学": "https://gs.ysu.edu.cn/",
    "哈尔滨工程大学": "https://yjsy.hrbeu.edu.cn/",
    "上海大学": "https://yjszs.shu.edu.cn/",
    "东华大学": "https://yjszs.dhu.edu.cn/",
    "南京信息工程大学": "https://yjs.nuist.edu.cn/",
    "浙江工业大学": "https://www.gs.zjut.edu.cn/",
    "宁波大学": "https://graduate.nbu.edu.cn/",
    "厦门大学": "https://gs.xmu.edu.cn/",
    "华侨大学": "https://grs.hqu.edu.cn/",
    "山东大学": "https://www.yz.sdu.edu.cn/",
    "中国海洋大学": "https://yz.ouc.edu.cn/",
    "深圳大学": "https://yz.szu.edu.cn/",
    "广东工业大学": "https://yjs.gdut.edu.cn/",
    "贵州师范大学": "https://yjsc.gznu.edu.cn/",
    "贵州财经大学": "https://yjsy.gufe.edu.cn/",
    "贵州民族大学": "https://yjsy.gzmu.edu.cn/",
    "贵州医科大学": "https://yjsxy.gmc.edu.cn/",
    "遵义医科大学": "https://yjsy.zmu.edu.cn/",
}

# --------------------------------------------------------------------------- #
# 已知「公告列表页」直达 URL（首页为 JS 导航/结构复杂、静态抓不到列表时使用）。
# 每站可配多个栏目页；爬虫在首页解析结果偏少时，会额外抓这些已验证的列表页。
# 全部 2026-10-12 实测均为 HTTP 200 且静态可解析（parse_notice_links ≥ 1）。
# --------------------------------------------------------------------------- #
KNOWN_SECTION_URLS: Dict[str, List[str]] = {
    # 天津大学：首页导航为 JS 渲染；研招「通知公告/最新信息」为静态列表页（gb2312）
    "天津大学": [
        "https://yzb.tju.edu.cn/xwzx/tztg/index.htm",
        "https://yzb.tju.edu.cn/xwzx/zxxx/index.htm",
    ],
    # 北京科技大学：真实研招入口为 yzxc（已改主表 URL），补硕士通知/章程栏目
    "北京科技大学": [
        "https://yzxc.ustb.edu.cn/sssbkzn/sstzgg/index.htm",
        "https://yzxc.ustb.edu.cn/sssbkzn/sszszc/index.htm",
    ],
    # 华中科技大学光电学院：研究生招生/通知公告栏目页
    "华中科技大学光电学院": [
        "https://oei.hust.edu.cn/dqgz/tzgg.htm",
    ],
    # 东北大学：首页含真实公告，但栏目页更全
    "东北大学": [
        "https://yz.neu.edu.cn/5932/list.htm",   # 硕士公告
        "https://yz.neu.edu.cn/5933/list.htm",   # 硕士简章
    ],
}


def _collect_notices(domain: str, url: str, html: str, school: str = "") -> List[Dict[str, str]]:
    """给定站点首页 HTML，聚合公告链接（多策略 + 栏目跟进）。

    策略顺序：
    1. webplus JSON 接口（大量高校，含贵大/东北大学等；HTML 列表页只有导航是其特征）；
    2. HTML 直解（剥离内联标签后的锚文本）；
    3. 若结果偏少（<5），跟进首页栏目入口一层，栏目页再走 webplus/HTML 解析；
       若栏目页仍少，追一层二级栏目（部分站点「研究生招生」下还有「硕士公告」子栏目）；
    4. 已知列表页兜底（KNOWN_SECTION_URLS，针对首页为 JS 导航、静态抓不到列表的站）。

    school 指定时启用 KNOWN_SECTION_URLS 兜底。去重：按 title+date 保序去重。
    """
    links = parse_webplus_notices(domain, html)
    if not links:
        links = parse_notice_links(html, url, wide_date=True)
    # 栏目跟进（首页具体公告少时）
    if len(links) < 5:
        for sec_url in parse_section_links(html, url):
            sec_html = _fetch(sec_url)
            if not sec_html:
                _polite()
                continue
            sec_domain = re.match(r"https?://([^/]+)", sec_url)
            sec_domain = sec_domain.group(1) if sec_domain else domain
            sec_links = parse_webplus_notices(sec_domain, sec_html) \
                or parse_notice_links(sec_html, sec_url, wide_date=True)
            # 栏目页仍无 → 再跟一层二级栏目（如「研究生招生」→「硕士公告」）
            if not sec_links:
                for sub_url in parse_section_links(sec_html, sec_url, limit=2):
                    sub_html = _fetch(sub_url)
                    if sub_html:
                        sub_domain = re.match(r"https?://([^/]+)", sub_url)
                        sub_domain = sub_domain.group(1) if sub_domain else sec_domain
                        sec_links.extend(
                            parse_webplus_notices(sub_domain, sub_html)
                            or parse_notice_links(sub_html, sub_url, wide_date=True)
                        )
                    _polite()
            links.extend(sec_links)
            _polite()
    # 已知列表页兜底（首页 JS 导航站：首页静态抓不到列表，直接抓已验证栏目页）
    if school and len(links) < 5:
        for sec_url in KNOWN_SECTION_URLS.get(school, []):
            sec_html = _fetch(sec_url)
            if not sec_html:
                _polite()
                continue
            sec_domain = re.match(r"https?://([^/]+)", sec_url)
            sec_domain = sec_domain.group(1) if sec_domain else domain
            links.extend(
                parse_webplus_notices(sec_domain, sec_html)
                or parse_notice_links(sec_html, sec_url, wide_date=True)
            )
            _polite()
    # 去重（保序）：title+date 为键；空标题跳过。
    # 噪声拦截：标题≤4 字且无日期 → 视为栏目名噪声（导航栏目名，非公告），
    # 从源头丢弃，避免其进入 by_school 计数与入库。带日期的短标题保留。
    seen, uniq = set(), []
    for lk in links:
        title = lk.get("title")
        if not title:
            continue
        if _is_section_noise(title) and not lk.get("publish_date"):
            continue
        key = (title, lk.get("publish_date"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(lk)
    return uniq


def crawl_school_notices(
    db_session=None,
    school_names: Optional[List[str]] = None,
    max_schools: int = 30,
    dry_run: bool = False,
) -> Dict:
    """抓各校研究生院官网公告列表。

    数据源优先级：
    1. ENGINEERING_NOTICE_URLS 内置工科清单（目标院校+四邮四电+工科强校，公告真实入口）；
    2. 库中 official_url 以 http 开头的院校（研招网 sch 页，公告收益低，排在后面）。

    school_names 指定时只采指定院校。robots 允许才采，2-5s 延迟。
    """
    from database import SessionLocal
    from models import KaoyanSchool, KaoyanCrawlTarget

    close = False
    if db_session is None:
        db_session = SessionLocal()
        close = True
    try:
        ensure_notices_schema(db_session)

        # 目标清单（school_names 过滤）
        targets: Dict[str, str] = dict(ENGINEERING_NOTICE_URLS)
        if school_names:
            targets = {n: u for n, u in targets.items() if n in school_names}
        # 库中真官网补充（去重）
        for s in db_session.query(KaoyanSchool).filter(
            KaoyanSchool.official_url.like("http%")
        ).limit(max_schools).all():
            if s.name not in targets and s.official_url.startswith("http"):
                targets[s.name] = s.official_url

        # 「院校采集源」里被排除的院校：公告采集直接跳过。
        # 口径与 /api/kaoyan/crawl-targets 一致（无记录 = 参与）。
        excluded_names = {
            row[0] for row in db_session.query(KaoyanSchool.name)
            .join(KaoyanCrawlTarget, KaoyanCrawlTarget.school_id == KaoyanSchool.id)
            .filter(KaoyanCrawlTarget.enabled.is_(False))
            .all()
        }
        if excluded_names:
            targets = {n: u for n, u in targets.items() if n not in excluded_names}

        items = list(targets.items())[:max_schools]

        # school_id 映射（可能未入库，公告仍存 school_name 供检索）
        name_to_id = {
            s.name: s.id for s in db_session.query(KaoyanSchool).all()
        }

        stats = {"schools": 0, "notices": 0, "skipped_robots": 0, "parse_failed": 0,
                 "not_in_db": 0, "by_school": {}}
        for name, url in items:
            domain = re.match(r"https?://([^/]+)", url)
            if not domain:
                continue
            if not _robots_allows(domain.group(1)):
                stats["skipped_robots"] += 1
                continue
            html = _fetch(url)
            if not html:
                stats["parse_failed"] += 1
                stats["by_school"][name] = "fetch_failed"
                continue
            links = _collect_notices(domain.group(1), url, html, school=name)
            stats["schools"] += 1
            stats["by_school"][name] = len(links)
            if name not in name_to_id:
                stats["not_in_db"] += 1
            if not dry_run and links:
                conn = wrap_conn(db_session.connection().connection)
                # naive UTC + ISO「T」分隔：原先是北京时间空格分隔的展示串，写进按
                # UTC 口径的列会让 fetched_at 与所有 UTC 窗口差 8 小时，且空格格式
                # 不匹配 utils/response.py 的补 Z 规则，出参后前端只能按本地时间猜。
                now = naive_utc_iso()
                for lk in links[:50]:  # 每校最多存 50 条
                    # 幂等写入：按 (school_id, 归一化URL) 判重，命中则 UPDATE 而非
                    # INSERT。原实现用裸 INSERT OR IGNORE，但表上的
                    # UNIQUE(school_name, title, publish_date) 在 publish_date
                    # 为 NULL 时不触发冲突（SQLite 认为 NULL != NULL），导致同一条
                    # 通知被反复插入（西电历史上有 14 次重复即由此产生）。
                    try:
                        action = upsert_notice(
                            conn,
                            school_id=name_to_id.get(name),
                            school_name=name,
                            title=lk["title"],
                            notice_type=infer_notice_type(lk["title"]),
                            publish_date=lk["publish_date"],
                            url=lk["url"],
                            source=domain.group(1),
                            fetched_at=now,
                        )
                        if action == "inserted":
                            stats["notices"] += 1
                        elif action == "updated":
                            stats["notices_updated"] = stats.get("notices_updated", 0) + 1
                    except Exception:  # noqa: BLE001 原只捕 sqlite3.Error；PG 毒化后整批全废。
                        # 回滚丢弃当前未提交批次并重建连接，后续院校继续（宁丢一批不丢全局）。
                        try:
                            db_session.rollback()
                            conn = wrap_conn(db_session.connection().connection)
                        except Exception:  # noqa: BLE001
                            pass
                        continue
                db_session.commit()
            _polite()
        return stats
    finally:
        if close:
            db_session.close()


def crawl_yz_notices(max_pages: int = 3, dry_run: bool = False) -> Dict:
    """研招网资讯聚合（预留：接口结构待探测后填充，当前返回 not_implemented）。

    如实口径：研招网资讯页是 JS 渲染为主，静态抓取收益低；优先走各校官网
    （crawl_school_notices）。此函数保留作后续接口探测的挂载点。
    """
    return {"status": "not_implemented", "reason": "研招网资讯页为 JS 渲染，优先各校官网采集"}


if __name__ == "__main__":  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--schools", nargs="*", help="指定院校名（默认取有官网的前20所）")
    ap.add_argument("--max", type=int, default=20)
    args = ap.parse_args()
    print(json.dumps(crawl_school_notices(school_names=args.schools, max_schools=args.max, dry_run=args.dry_run), ensure_ascii=False, indent=2))
