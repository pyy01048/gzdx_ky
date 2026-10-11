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
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "PersonalStudyTool/1.0 (kaoyan personal use)"
    )
}
_CHECKPOINT = Path(__file__).parent / "notices_checkpoint.json"

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
    conn = db_session.connection().connection
    conn.executescript(_DDL)
    db_session.commit()


def _db_path() -> str:
    import os

    return os.environ.get("DATABASE_PATH", "").strip() or str(
        Path(__file__).resolve().parents[3] / "database" / "kaoyan.db"
    )


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def _fetch(url: str, retries: int = 2, timeout: int = 20) -> str:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
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
# 长度下限 2 字：支持「复试通知」「录取公告」等短标题（原 6 字会漏掉）
_LINK_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{2,120})</a>', re.S)
_DATE_NEAR_RE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
_TITLE_KW = ("招生", "简章", "复试", "调剂", "录取", "硕士", "考研", "初试", "公告", "通知")
# 栏目导航链接（首页的「硕士招生/招生工作/通知公告」入口——首页常无具体公告，
# 需跟进一层到列表页才有；限制这些精确栏目词避免把「学校概况」等无关栏目也跟进去）
_SECTION_KW = ("硕士招生", "招生工作", "通知公告", "招生信息", "硕士", "招生")


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
    """
    out: List[Dict[str, str]] = []
    for m in _LINK_RE.finditer(html):
        href, text = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        # 排除首页栏目导航入口（「硕士招生」「通知公告」等精确短词，
        # 由 parse_section_links 跟进一层处理，避免被当成具体公告）
        if text in _SECTION_KW:
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
        out.append({"title": text, "url": href, "publish_date": date})
    return out


def parse_section_links(html: str, base_url: str, limit: int = 4) -> List[str]:
    """抽首页的公告栏目入口（跟进一层到真列表页）。

    只认含精确栏目词的短文本链接（「硕士招生」「通知公告」），不认具体
    公告标题（那些首页少见且 parse_notice_links 已处理）。
    """
    seen, out = set(), []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{2,12})</a>', html):
        text = re.sub(r"\s+", "", m.group(2))
        if text in _SECTION_KW:
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
# --------------------------------------------------------------------------- #
ENGINEERING_NOTICE_URLS: Dict[str, str] = {
    # 目标院校（硕士招生栏目优先——通知公告栏目多为学位授予类，招生信息在 sszs）
    "贵州大学": "https://gs.gzu.edu.cn/sszs/list.htm",
    # 四邮四电（电子/通信核心；域名经 2026-10 实测校正：
    # 北邮 yz.bupt/杭电 yz.hdu DNS 解析失败、浙大 grs 连接拒绝，留待改版后修）
    "电子科技大学": "https://yz.uestc.edu.cn/",
    "西安电子科技大学": "https://gr.xidian.edu.cn/",
    "北京邮电大学": "https://www.bupt.edu.cn/",
    "南京邮电大学": "https://yzb.njupt.edu.cn/",
    "杭州电子科技大学": "https://yjs.hdu.edu.cn/",
    "重庆邮电大学": "https://yjs.cqupt.edu.cn/",
    "桂林电子科技大学": "https://www.guet.edu.cn/",
    # 985 工科强校（用户工科系列覆盖院校）
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
    # 光学/电气系列
    "长春理工大学": "https://yz.cust.edu.cn/",
    "华中科技大学光电学院": "https://oei.hust.edu.cn/",
    "华北电力大学": "https://yjsy.ncepu.edu.cn/",
    "西南交通大学": "https://grs.swjtu.edu.cn/",
    # AI/控制系列 + 408 强校
    "东北大学": "https://yz.neu.edu.cn/",
    "中南大学": "https://gra.csu.edu.cn/",
    "武汉大学": "https://www.gs.whu.edu.cn/",
    "华中师范大学": "https://gs.ccnu.edu.cn/",
}


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
    from models import KaoyanSchool

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
            # 优先 webplus JSON 接口（贵大等大量高校；HTML 列表页只有导航是它的特征）
            domain_str = domain.group(1)
            links = parse_webplus_notices(domain_str, html)
            if not links:
                # 回退：HTML 直解 + 栏目跟进一层
                links = parse_notice_links(html, url, wide_date=True)
                if len(links) < 5:
                    for sec_url in parse_section_links(html, url):
                        sec_html = _fetch(sec_url)
                        if sec_html:
                            # 栏目页也可能是 webplus
                            sec_links = parse_webplus_notices(re.match(r"https?://([^/]+)", sec_url).group(1), sec_html)
                            links.extend(sec_links or parse_notice_links(sec_html, sec_url, wide_date=True))
                        _polite()
            stats["schools"] += 1
            stats["by_school"][name] = len(links)
            if name not in name_to_id:
                stats["not_in_db"] += 1
            if not dry_run and links:
                conn = db_session.connection().connection
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for lk in links[:50]:  # 每校最多存 50 条
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO kaoyan_notices "
                            "(school_id, school_name, title, notice_type, publish_date, url, source, fetched_at)"
                            " VALUES (?,?,?,?,?,?,?,?)",
                            (name_to_id.get(name), name, lk["title"],
                             infer_notice_type(lk["title"]),
                             lk["publish_date"], lk["url"], domain.group(1), now),
                        )
                        stats["notices"] += 1
                    except sqlite3.Error:
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
