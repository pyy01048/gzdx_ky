# -*- coding: utf-8 -*-
"""院校通知深度采集器（名单主产区专栏 → 详情 URL → 通知补录 → 名单入库）。

背景：普通列表采集（spider_notices）只拿到各校首页/通知栏目公告，而真正的
拟录取/复试名单多在「研究生招生专栏」的详情页及其附件里（名单主产区）。
本模块把采集深度推进到这些专栏：

  入口配置（DEEP_ENTRIES，两种类型）
    ├─ webplus：华工式 CMS，列表 HTML 是 JS 壳，真数据在
    │    /_wp3services/generalQuery JSON 接口（siteId+columnId）
    └─ html： 天大式静态列表页，直接解析 <a> + 标题

  链路（main）：
    拉文章列表 → 标题强过滤（拟录取/复试名单/复试结果/成绩公示/复试成绩，
    排除博士/推免/港澳台/EMBA/国优/少干/骨干/退役/士兵/同等学力）
    → 命中详情 URL 先 upsert 进 kaoyan_notices（通知中心补全，幂等）
    → 复用 notice_admission_crawler 的详情页抓取/附件解析/质量门/入库

合规：同 spider_notices——robots 检查、2-5s 随机延迟、UA 声明个人备考用途；
      KAOYAN_AUTO_COLLECT=1 时才有意义（由 autofill/调度入口统一把关）。
"""
import json
import re
import sys
import time
import random
import statistics
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.kaoyan.spider_notices import (  # noqa: E402
    _abs,
    _fetch,
    _polite,
    _robots_allows,
    ensure_notices_schema,
    infer_notice_type,
    parse_notice_links,
)
from services.kaoyan.notice_dedup import upsert_notice  # noqa: E402
from services.dbapi_compat import wrap_conn  # noqa: E402
from database import SessionLocal  # noqa: E402
from utils.timeutil import naive_utc_iso  # noqa: E402
from sqlalchemy import text  # noqa: E402

# --------------------------------------------------------------------------- #
# 深度入口配置（名单主产区专栏）
# --------------------------------------------------------------------------- #
DEEP_ENTRIES = [
    # 华南理工（webplus CMS，2026-10-19 实测）：
    #   siteId=544；json 接口返回全站栏目混排（简章/网报/预推免都在里面），
    #   由标题强过滤收敛到名单类；url 字段即详情页真实地址。
    {
        "school": "华南理工大学",
        "kind": "webplus",
        "domain": "yz.scut.edu.cn",
        "site_id": "544",
        "columns": [
            {"column_id": "30111", "label": "硕士招生"},
            # 30112=博士（标题过滤会排除）；30384=港澳台（排除）
        ],
        "max_pages": 3,
        "page_size": 30,
    },
    # 天津大学（静态 HTML 列表，2026-10-19 实测）：
    #   yzb.tju.edu.cn/xwzx/tkss_xw/index.htm 统考硕士，gb2312，链接相对形态
    {
        "school": "天津大学",
        "kind": "html",
        "list_url": "https://yzb.tju.edu.cn/xwzx/tkss_xw/index.htm",
        "paging": "index",  # index.htm, index_1.htm, ... 直到空
        "max_pages": 3,
    },
]

# 标题强过滤（与 notice_admission_crawler 同口径；名单主产区只收这些）
TITLE_OK = re.compile(r"拟录取|录取名单|复试名单|复试结果|成绩公示|复试成绩")
TITLE_NO = re.compile(
    r"博士|硕博|直博|档案|政审|调档|推免|推荐免试|推免生|港澳台|香港|澳门|台湾地区|"
    r"免试生|立功表彰|二等功|工商管理硕士|EMBA|国优|少干|骨干人才|退役|士兵计划|"
    r"同等学力|录取通知书|确认通信地址|单独考试"
)


def _title_pass(title: str) -> bool:
    return bool(TITLE_OK.search(title)) and not TITLE_NO.search(title)


def _clean_url(url: str, base_url: str) -> str:
    """补全相对链接（含 ./、../ 相对形态），并修复 parse_notice_links 残留的
    页面文件名残段（.../index.htm/./202604/... → .../202604/...）。"""
    u = _abs(url, base_url)
    # 修复「文件名被当目录」残段：/xxx.htm/./ 或 /xxx.htm/../yy/ → /yy/
    u = re.sub(r"/[^/]+\.htm/\.\./", "/", u)
    u = re.sub(r"/[^/]+\.htm/\./", "/", u)
    u = re.sub(r"/\./", "/", u)
    return u


# --------------------------------------------------------------------------- #
# 聚合页二级抓取（天大形态）
# --------------------------------------------------------------------------- #
# 天大复试/拟录取公示是「学院聚合页」：正文只有各学院子站名单链接
# （https://<sub>.tju.edu.cn/info/<c>/<n>.htm），网页本身无表格、无附件；
# 名单在各学院子站详情页，附件多为美萍 CMS 的 download.jsp（无扩展名、
# 需带 Referer 防盗链）。此处对子站逐一执行与一级相同的解析链路。
_SUB_LINK_RE = re.compile(r"https?://[\w.\-]+\.edu\.cn/info/\d+/\d+(?:\.htm)?", re.I)
# 附件识别：常规扩展名 OR 美萍 download.jsp（label 带 .pdf/.xlsx 等）
_ATTACH_RE = re.compile(r"\.(xlsx|xls|pdf)(\?|$)", re.I)


def find_subpage_links(html: str, base_url: str) -> list:
    """从聚合页正文提取学院子站名单链接（去空白、去重、保序）。

    返回形如 https://snmc.tju.edu.cn/info/1120/7688.htm 的绝对 URL 列表。
    """
    out, seen = [], set()
    for m in re.finditer(_SUB_LINK_RE, html):
        raw = re.sub(r"\s+", "", m.group(0))
        url = _clean_url(raw, base_url)
        key = re.sub(r"^https?://", "", url).rstrip("/")
        if url.startswith("http") and key not in seen:
            seen.add(key)
            out.append(url)
    return out


def _find_attachments(html: str, base: str) -> list:
    """详情页附件链接（比 notice_admission_crawler.find_table_attachments
    多识别美萍 CMS 的 download.jsp 下载形态，label 带扩展名）。"""
    out, seen = [], set()
    for m in re.finditer(r"<a\b[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, re.S | re.I):
        href, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if _ATTACH_RE.search(href) or ("download" in href.lower() and _ATTACH_RE.search(label)):
            u = _clean_url(href, base)
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out


def _parse_blob(blob: bytes):
    """按文件头判断格式后解析（download.jsp 无扩展名，只能看 magic bytes）。"""
    from pipeline import notice_admission_crawler as mac

    if blob.startswith(b"%PDF"):
        return mac.parse_pdf(blob)
    if blob[:2] == b"PK":  # xlsx 是 zip 容器
        return mac.parse_xlsx(blob)
    return None


def _fetch_blob(url: str, referer: str = "", timeout: int = 90) -> bytes:
    """带 Referer 抓取二进制（天大子站附件 download.jsp 有防盗链）。"""
    import urllib.request

    from pipeline import notice_admission_crawler as mac

    headers = {"User-Agent": mac.UA["User-Agent"]}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:  # noqa: BLE001 老旧 TLS/证书站点降级一次
        with urllib.request.urlopen(req, timeout=timeout, context=mac._loose_ssl_ctx()) as r:
            return r.read()


def _extract_sub_pages(
    db, notice_id: int, school_id: int, school_name: str,
    notice_type: str, year: int, html: str, url: str,
    max_sub: int = 0,
) -> dict:
    """学院聚合页二级抓取：对正文子站链接逐一执行名单解析并入库。

    幂等：data_source = notice:<父id>:<子序号>，重跑跳过已入库子站。
    返回 {"status": "inserted_sub"/"no_data", "rows", "detail"}。
    """
    from pipeline import notice_admission_crawler as mac

    subs = find_subpage_links(html, url)
    if not subs:
        return {"status": "no_data", "reason": "no_subpages"}
    if max_sub:
        subs = subs[:max_sub]
    rows, detail = 0, []
    for i, sub_url in enumerate(subs, 1):
        src = f"notice:{notice_id}:{i}"
        exists = db.execute(
            text("SELECT 1 FROM kaoyan_admissions WHERE school_id=:s AND year=:y AND data_source=:d"),
            {"s": school_id, "y": year, "d": src},
        ).first()
        if exists:
            continue
        try:
            sub_raw = mac.fetch(sub_url, timeout=30)
            sub_html = mac._decode_html(sub_raw)
            data = None
            for href in _find_attachments(sub_html, sub_url)[:3]:
                blob = _fetch_blob(href, referer=sub_url)
                if not blob:
                    mac.polite()
                    continue
                data = _parse_blob(blob)
                if data:
                    break
                mac.polite()
            if not data:
                data = mac.parse_html_tables(sub_html)
            if not data:
                mac.polite()
                continue
            st = data["totals"]
            is_admit = notice_type in ("录取", "调剂")
            db.execute(
                text(
                    "INSERT INTO kaoyan_admissions "
                    "(school_id, major_id, year, enroll_count, retest_count, admit_count, "
                    " admit_avg_score, major_avg_score, retest_ratio, data_source) "
                    "VALUES (:s, NULL, :y, NULL, :rc, :ac, :avg, NULL, NULL, :src)"
                ),
                {
                    "s": school_id, "y": year,
                    "rc": data["students"] if notice_type == "复试" else None,
                    "ac": data["students"] if is_admit else None,
                    "avg": round(statistics.mean(st), 1) if st else None,
                    "src": src,
                },
            )
            db.commit()
            rows += 1
            detail.append(
                f"{school_name} 子站[{i}] {data['students']}人 "
                f"avg={round(statistics.mean(st), 1) if st else '-'} ← {sub_url.split('/')[-2]}/{sub_url.split('/')[-1]}"
            )
            mac.polite()
        except Exception as e:  # noqa: BLE001
            db.rollback()
            mac.polite()
            detail.append(f"子站[{i}] err {str(e)[:60]}")
    return {"status": "inserted_sub" if rows else "no_data", "rows": rows, "detail": detail}


# --------------------------------------------------------------------------- #
# 两种入口的列表抓取
# --------------------------------------------------------------------------- #
def list_webplus_entries(entry: dict) -> list:
    """webplus JSON 接口：分页拉文章列表，返回 [{title,url,publish_date}]。"""
    out, seen = [], set()
    domain = entry["domain"]
    for col in entry.get("columns", []):
        for page in range(1, entry.get("max_pages", 2) + 1):
            api = (
                f"https://{domain}/_wp3services/generalQuery"
                f"?queryObj=articles&siteId={entry['site_id']}&columnId={col['column_id']}"
                f"&pageSize={entry.get('page_size', 30)}&pageNumber={page}"
            )
            body = _fetch(api, retries=1, timeout=20)
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
                url = it.get("url") or it.get("wapUrl") or it.get("trueWapUrl") or ""
                key = (title, url)
                if not title or not url or key in seen:
                    continue
                seen.add(key)
                out.append({
                    "title": title,
                    "url": _clean_url(url, f"https://{domain}/"),
                    "publish_date": (it.get("publishTime") or "")[:10] or None,
                })
            if len(data) < entry.get("page_size", 30):
                break
            _polite()
    return out


def list_html_entries(entry: dict) -> list:
    """静态 HTML 列表：index.htm + 分页 index_1/index_2 ... 直到空/失败。

    链接 URL 用 parse_notice_links 内部 _abs 补全后可能残留页面文件名残段
    （.../index.htm/./202604/...），由 _clean_url 兜底修复。
    """
    out, seen = [], set()
    base = entry["list_url"]
    for i in range(1, entry.get("max_pages", 2) + 1):
        url = base if i == 1 else re.sub(r"index\.htm$", f"index_{i-1}.htm", base)
        html = _fetch(url)
        if not html:
            break  # 分页耗尽 / 首页失败
        links = parse_notice_links(html, url, wide_date=True)
        if not links and i > 1:
            break  # 分页为空 → 停止
        dir_base = url.rsplit("/", 1)[0] + "/"
        for lk in links:
            key = (lk["title"], lk["url"])
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "title": lk["title"],
                "url": _clean_url(lk["url"], dir_base),
                "publish_date": lk["publish_date"],
            })
        _polite()
    return out


def fetch_deep_entries(entry: dict) -> list:
    if entry.get("kind") == "webplus":
        return list_webplus_entries(entry)
    if entry.get("kind") == "html":
        return list_html_entries(entry)
    return []


# --------------------------------------------------------------------------- #
# 单条详情页 → 名单入库（复用 notice_admission_crawler 的解析链路）
# --------------------------------------------------------------------------- #
def _extract_admission_from_notice(
    db,
    notice_id: int,
    school_id: int,
    school_name: str,
    notice_type: str,
    title: str,
    url: str,
    publish_date: str,
) -> dict:
    """对通知详情页执行：附件/网页表格解析 → 质量门 → kaoyan_admissions。

    复用 notice_admission_crawler.fetch/_decode_html/find_table_attachments/
    parse_pdf/parse_xlsx/parse_html_tables/_extract_table（质量门在其内部）。
    幂等：data_source = notice:<id> 已存在则跳过。
    """
    from pipeline import notice_admission_crawler as mac

    year = int((publish_date or "")[:4]) if publish_date else 2026
    src = f"notice:{notice_id}"
    exists = db.execute(
        text("SELECT 1 FROM kaoyan_admissions WHERE school_id=:s AND year=:y AND data_source=:d"),
        {"s": school_id, "y": year, "d": src},
    ).first()
    if exists:
        return {"status": "skipped_exists"}

    raw = mac.fetch(url)
    html = mac._decode_html(raw)
    data = None
    for href in mac.find_table_attachments(html, url)[:3]:
        try:
            blob = mac.fetch(href, timeout=60)
            if href.lower().endswith(".pdf"):
                data = mac.parse_pdf(blob)
            else:
                data = mac.parse_xlsx(blob)
            if data:
                break
            mac.polite()
        except Exception:  # noqa: BLE001
            mac.polite()
    if not data:
        data = mac.parse_html_tables(html)
    if not data:
        mac.polite()
        # 一级无直挂名单 → 若是「学院聚合页」（天大形态），子站二级抓取
        sub = _extract_sub_pages(
            db, notice_id, school_id, school_name, notice_type, year, html, url,
        )
        if sub["status"] == "inserted_sub":
            return {
                "status": "inserted_sub",
                "rows": sub["rows"],
                "detail": sub["detail"],
                "title": title[:50],
            }
        return {"status": "no_data", "title": title[:50]}

    st = data["totals"]
    is_admit = notice_type in ("录取", "调剂")
    db.execute(
        text(
            "INSERT INTO kaoyan_admissions "
            "(school_id, major_id, year, enroll_count, retest_count, admit_count, "
            " admit_avg_score, major_avg_score, retest_ratio, data_source) "
            "VALUES (:s, NULL, :y, NULL, :rc, :ac, :avg, NULL, NULL, :src)"
        ),
        {
            "s": school_id, "y": year,
            "rc": data["students"] if notice_type == "复试" else None,
            "ac": data["students"] if is_admit else None,
            "avg": round(statistics.mean(st), 1) if st else None,
            "src": src,
        },
    )
    db.commit()
    mac.polite()
    return {
        "status": "inserted",
        "students": data["students"],
        "avg": round(statistics.mean(st), 1) if st else None,
        "title": title[:50],
    }


# --------------------------------------------------------------------------- #
# 主流程：入口 → 列表 → 过滤 → 通知补录 → 名单入库
# --------------------------------------------------------------------------- #
def main(
    school_names=None,
    db_session=None,
    dry_run: bool = False,
    do_extract: bool = True,
    max_entries: int = None,
) -> dict:
    """深度采集主流程。

    school_names 只采指定院校；dry_run 只拉列表不进库；
    do_extract=False 只做通知补录（名单提取交给 autofill 的 B 段）。
    """
    close = False
    if db_session is None:
        db_session = SessionLocal()
        close = True
    try:
        ensure_notices_schema(db_session)

        entries = DEEP_ENTRIES
        if school_names:
            entries = [e for e in entries if e["school"] in school_names]
        if max_entries:
            entries = entries[:max_entries]

        # school_id 映射
        rows = db_session.execute(text("SELECT id, name FROM kaoyan_schools")).fetchall()
        name_to_id = {n: i for i, n in rows}

        stats = {"entries": len(entries), "list_total": 0, "filtered": 0,
                 "notices_new": 0, "notices_updated": 0, "admissions": {}}

        for entry in entries:
            school = entry["school"]
            domain = re.match(r"https?://([^/]+)", entry.get("list_url") or f"https://{entry['domain']}/")
            host = domain.group(1) if domain else entry.get("domain", "")
            if host and not _robots_allows(host):
                stats.setdefault("robots_blocked", []).append(school)
                continue

            links = fetch_deep_entries(entry)
            hits = [lk for lk in links if _title_pass(lk["title"])]
            stats["list_total"] += len(links)
            stats["filtered"] += len(hits)
            stats.setdefault("by_school", {})[school] = {
                "list": len(links), "hits": len(hits),
            }

            if dry_run or not hits:
                _polite()
                continue

            conn = wrap_conn(db_session.connection().connection)
            now = naive_utc_iso()
            new_ids = []  # 本次新增/更新的通知 id：随后执行名单提取
            for lk in hits[:60]:
                try:
                    action = upsert_notice(
                        conn,
                        school_id=name_to_id.get(school),
                        school_name=school,
                        title=lk["title"],
                        notice_type=infer_notice_type(lk["title"]),
                        publish_date=lk["publish_date"],
                        url=lk["url"],
                        source=host,
                        fetched_at=now,
                    )
                    if action == "inserted":
                        stats["notices_new"] += 1
                    elif action == "updated":
                        stats["notices_updated"] += 1
                    new_ids.append(
                        conn.execute(
                            "SELECT id FROM kaoyan_notices WHERE school_name=? AND url=?",
                            (school, lk["url"]),
                        ).fetchone()[0]
                    )
                except Exception:  # noqa: BLE001 单条失败不毒化整批
                    try:
                        db_session.rollback()
                        conn = wrap_conn(db_session.connection().connection)
                    except Exception:  # noqa: BLE001
                        pass
                    continue
            db_session.commit()

            if do_extract:
                per_school = {"admit": 0, "retest": 0, "sub": 0, "no_data": 0, "detail": []}
                for nid in new_ids:
                    nrow = db_session.execute(
                        text("SELECT id, school_id, school_name, notice_type, title, url, publish_date "
                             "FROM kaoyan_notices WHERE id = :i"),
                        {"i": nid},
                    ).fetchone()
                    if not nrow:
                        continue
                    try:
                        r = _extract_admission_from_notice(
                            db_session, nrow[0], nrow[1] or name_to_id.get(school),
                            nrow[2] or school, nrow[3], nrow[4], nrow[5], nrow[6],
                        )
                        if r["status"] == "inserted":
                            if nrow[3] in ("录取", "调剂"):
                                per_school["admit"] += 1
                            else:
                                per_school["retest"] += 1
                            per_school["detail"].append(
                                f"{nrow[2] or school} {r['students']}人 "
                                f"avg={r['avg']} ← {title_short(r['title'])}"
                            )
                        elif r["status"] == "inserted_sub":
                            per_school["sub"] += r["rows"]
                            per_school["detail"] += [
                                d for d in r.get("detail", []) if not d.startswith("子站[") or "err" not in d
                            ]
                        elif r["status"] == "no_data":
                            per_school["no_data"] += 1
                    except Exception as e:  # noqa: BLE001
                        db_session.rollback()
                        stats.setdefault("extract_err", 0)
                        stats["extract_err"] += 1
                stats["admissions"][school] = per_school
            _polite()

        return stats
    finally:
        if close:
            db_session.close()


def title_short(t: str, n: int = 40) -> str:
    return (t or "")[:n]


if __name__ == "__main__":  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只拉列表不进库")
    ap.add_argument("--no-extract", action="store_true", help="只通知补录，不跑名单提取")
    ap.add_argument("--schools", nargs="*", help="指定院校名")
    args = ap.parse_args()
    print(json.dumps(main(
        school_names=args.schools,
        dry_run=args.dry_run,
        do_extract=not args.no_extract,
    ), ensure_ascii=False, indent=2))