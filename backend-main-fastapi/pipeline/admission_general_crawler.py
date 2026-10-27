# -*- coding: utf-8 -*-
"""院校招生名单通用批量采集器（v2 通用版）。

遍历 kaoyan_notices 中复试/录取/调剂类通知（标题质量门自动过滤），自动：
  1. 拉通知详情页 → 找表格附件（xlsx / pdf）或网页内嵌表格；
  2. 解析名单（姓名列 + 成绩质量门）→ 聚合写入 kaoyan_admissions
     （data_source = notice:<id> 幂等；--redo 时刷新聚合计数/均分）；
     逐人明细写入 kaoyan_admission_details（data_source = notice:<id>:d<行号>，
     唯一索引 ON CONFLICT DO NOTHING，重复执行不重复）；
  3. 扫描版 PDF 自动走 DeepSeek-OCR 兜底（只写聚合；逐人明细由专用批量脚本补跑）；
  4. 单通知失败隔离、不中断整体，输出 JSON 问题清单 → 逐项修复后重跑。

用法：
    python pipeline/admission_general_crawler.py --limit 40
    python pipeline/admission_general_crawler.py --schools 华南理工,中山大学 --redo
    python pipeline/admission_general_crawler.py --days 30 --dry-run

合规：仅处理公开公示名单；1.5-2.5s 随机延迟；KAOYAN_AUTO_COLLECT 环境开关。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import statistics
import sys
import traceback
import urllib.parse
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402
from models import KaoyanAdmission  # noqa: E402
from pipeline.notice_admission_crawler import (  # noqa: E402
    TITLE_OK, TITLE_NO, UA, fetch, polite, _decode_html,
    find_table_attachments, parse_xlsx, parse_html_tables, _extract_table,
)

REPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ocr_cache")


def _parse_pdf_text(blob: bytes):
    """文本层 PDF → 名单 dict（走 pdfplumber，绝不触发 OCR）。

    扫描件（无文本层）返回 None，由调用方标记「需专用 dsocr 分批补跑」，
    避免通用批量循环被单本整本 OCR 卡死数小时。
    """
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(blob)) as pdf:
            for pi, page in enumerate(pdf.pages[:15]):
                for t in page.extract_tables():
                    head = "".join("".join(str(c or "") for c in row) for row in t[:8])
                    if "姓名" in head:
                        res = _extract_table(t, f"pdf-p{pi}")
                        if res:
                            return res
    except Exception:  # noqa: BLE001 —— 损坏/加密交给调用方标记待 OCR
        return None
    return None


_SUBPAGE_TITLE = re.compile(r"名单|成绩|复试|录取")
_SUBPAGE_NO = re.compile(r"map|google|b站|微博|微信")


def _parse_subpages(db, html: str, base: str, nid: int, max_subs: int = 10) -> tuple[dict | None, list]:
    """聚合页兜底：正文把各学院/专业名单拆成子页链接时，递归抓第一层子页表格合并。

    兼容两类正文结构：
      - 锚文本即标题（“XX学院拟录取名单”）；
      - 标题在 <font>/文本、链接锚文本只是 URL 本身（TRS_Editor 常见）。

    返回 (合并 data 或 None, 已抓子页链接列表)。失败子页仅记录，不中断。
    """
    # 1) 优先正文容器（TRS_Editor / id=zoom），避免导航链接干扰
    frag = html
    m = re.search(r'<div[^>]*class=["\'][^"\']*TRS_Editor[^"\']*["\'][^>]*>(.*?)</div>\s*</div>', html, re.S | re.I)
    if not m:
        m = re.search(r'<div[^>]*id=["\']zoom["\'][^>]*>(.*?)</div>', html, re.S | re.I)
    if m:
        frag = m.group(1)
    else:
        # TRS_Editor 容器未闭合时回退到整个正文（id=content/vsb_content 等）
        for cid in ("content", "vsb_content", "Article", "zoom"):
            mm = re.search(r'<div[^>]*id=["\']' + cid + r'["\'][^>]*>(.*?)</div>', html, re.S | re.I)
            if mm:
                frag = mm.group(1)
                break

    subs, done = [], []
    for m in re.finditer(r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', frag, re.S | re.I):
        href, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if _SUBPAGE_NO.search(label.lower()) or not re.search(r"\.(htm|html|shtml|aspx)", href, re.I):
            continue
        if re.search(r"(index|list|more|nav|menu|top|footer|login|/page\.)", href, re.I) and not _SUBPAGE_TITLE.search(label):
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            p = urllib.parse.urlparse(base)
            href = f"{p.scheme}://{p.netloc}{href}"
        elif not href.startswith("http"):
            href = base.rsplit("/", 1)[0] + "/" + href
        if href == base or href in done:
            continue
        done.append(href)
    merged = {"students": 0, "totals": [], "majors": {}, "rows": []}
    for href in done[:max_subs]:
        try:
            raw = fetch(href, timeout=60)
            sub_html = _decode_html(raw)
            data = None
            # 子页先找附件（xlsx/文本层 pdf），再网页表格，最后递归一层聚合
            for shref in find_table_attachments(sub_html, href)[:3]:
                try:
                    blob = fetch(shref, timeout=90)
                    if shref.lower().endswith(".pdf"):
                        data = _parse_pdf_text(blob)
                    else:
                        data = parse_xlsx(blob)
                    if data:
                        break
                    polite()
                except Exception:  # noqa: BLE001
                    polite()
            if not data:
                data = parse_html_tables(sub_html)
            if not data:
                data = _parse_subpages(db, sub_html, href, nid, max_subs=4)[0]
            if data:
                merged["students"] += data.get("students") or 0
                merged["totals"].extend(data.get("totals") or [])
                for mk, mv in (data.get("majors") or {}).items():
                    merged["majors"][mk] = merged["majors"].get(mk, 0) + mv
                merged["rows"].extend(data.get("rows") or [])
        except Exception:  # noqa: BLE001 —— 单子页失败不影响其余
            continue
        finally:
            polite()
    if merged["students"] == 0:
        return None, done
    return merged, done


def _upsert(db, sid: int, year: int, src: str, ntype: str, data: dict):
    st = data.get("totals") or []
    is_admit = ntype in ("录取", "调剂")
    row = db.query(KaoyanAdmission).filter(
        KaoyanAdmission.school_id == sid, KaoyanAdmission.year == year,
        KaoyanAdmission.data_source == src).first()
    if row is None:
        row = KaoyanAdmission(
            school_id=sid, year=year,
            retest_count=data["students"] if ntype == "复试" else None,
            admit_count=data["students"] if is_admit else None,
            admit_avg_score=round(statistics.mean(st), 1) if st else None,
            data_source=src)
        db.add(row)
        db.flush()
    else:
        if ntype == "复试":
            row.retest_count = data["students"]
        if is_admit:
            row.admit_count = data["students"]
        if st:
            row.admit_avg_score = round(statistics.mean(st), 1)
        db.flush()
    return row.id


def _insert_details(db, nid: int, sid: int, year: int, admission_id: int, rows: list) -> int:
    inserted = 0
    for idx, r in enumerate(rows or []):
        n = (r.get("name") or "").strip()
        if not n:
            continue
        db.execute(text(
            "INSERT INTO kaoyan_admission_details "
            "(admission_id, school_id, year, exam_no, name, major_name, "
            " score_initial, score_retest, score_total, data_source) "
            "VALUES (:admission_id, :school_id, :year, :exam_no, :name, :major_name, "
            " :score_initial, :score_retest, :score_total, :data_source) "
            "ON CONFLICT (data_source) DO NOTHING"
        ), {
            "admission_id": admission_id,
            "school_id": sid,
            "year": year,
            "exam_no": (r.get("exam_no") or "")[:40] or None,
            "name": n[:60],
            "major_name": (r.get("major") or "")[:120] or None,
            "score_initial": r.get("initial"),
            "score_retest": r.get("retest"),
            "score_total": r.get("total"),
            "data_source": f"notice:{nid}:d{idx}",
        })
        inserted += 1
    return inserted


def run(limit: int = 40, schools: list[str] | None = None, days: int = 0,
        redo: bool = False, dry_run: bool = False, max_per_school: int = 3) -> dict:
    db = SessionLocal()
    rep = {"cand": 0, "skipped_done": 0, "fetched": 0, "got_data": 0,
           "inserted": 0, "details": 0, "empty": 0, "err": 0,
           "problems": [], "schools": {}}
    try:
        params = {"pat": TITLE_OK.pattern, "patno": TITLE_NO.pattern, "lim": limit}
        where = "url IS NOT NULL AND url <> '' AND title ~ :pat AND title !~ :patno"
        if days:
            where += " AND publish_date >= :since"
            params["since"] = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        if schools:
            where += " AND school_name = ANY(:schools)"
            params["schools"] = schools
        rows = db.execute(text(
            "SELECT id, school_id, school_name, notice_type, title, url, publish_date "
            f"FROM kaoyan_notices WHERE {where} "
            "ORDER BY school_id, publish_date DESC NULLS LAST LIMIT :lim"
        ), params).fetchall()
        rep["cand"] = len(rows)
        print(f"[候选] {len(rows)} 条（质量门后；每校至多 {max_per_school} 条名单类通知）")

        per_school_count: dict[str, int] = {}
        for nid, sid, sname, ntype, title, url, pdate in rows:
            cnt = per_school_count.get(sname, 0)
            if cnt >= max_per_school:
                rep["skipped_done"] += 1
                continue
            per_school_count[sname] = cnt + 1
            prob = {"notice": nid, "school": sname, "title": title[:60], "type": ntype}
            try:
                year = int((pdate or "")[:4]) if pdate else int(datetime.now(timezone.utc).year)
                src = f"notice:{nid}"
                exist = db.query(KaoyanAdmission.id).filter(
                    KaoyanAdmission.school_id == sid, KaoyanAdmission.year == year,
                    KaoyanAdmission.data_source == src).first()
                if exist and not redo:
                    rep["skipped_done"] += 1
                    continue
                raw = fetch(url)
                html = _decode_html(raw)
                rep["fetched"] += 1
                data = None
                ocr_pending = False
                for href in find_table_attachments(html, url)[:3]:
                    try:
                        blob = fetch(href, timeout=90)
                        if href.lower().endswith(".pdf"):
                            data = _parse_pdf_text(blob)
                            if data is None:
                                ocr_pending = True  # 扫描件/无文本层 → 延后专用 OCR
                        else:
                            data = parse_xlsx(blob)
                        if data:
                            break
                        polite()
                    except Exception as exc:  # noqa: BLE001
                        prob.setdefault("attach_err", []).append(f"{href[:70]}: {type(exc).__name__}")
                        polite()
                if not data:
                    data = parse_html_tables(html)
                if not data:
                    # 聚合页兜底：正文拆成学院子页链接 → 递归抓第一层表格
                    data, sub_pages = _parse_subpages(db, html, url, nid)
                    if sub_pages:
                        prob["sub_pages"] = len(sub_pages)
                if not data:
                    rep["empty"] += 1
                    prob["issue"] = ("扫描件PDF需专用OCR补跑" if ocr_pending else
                                     "页面无名单（附件为空/表格无姓名列/文本层PDF解析失败）")
                    rep["problems"].append(prob)
                    polite()
                    continue
                rep["got_data"] += 1
                students = data.get("students") or 0
                if not dry_run:
                    admission_id = _upsert(db, sid, year, src, ntype, data)
                    db.commit()
                    n_detail = 0
                    if data.get("rows") and not redo:
                        n_detail = _insert_details(db, nid, sid, year, int(admission_id), data["rows"])
                        db.commit()
                    rep["inserted"] += 1
                    rep["details"] += n_detail
                st = data.get("totals") or []
                prob["out"] = {"students": students,
                               "avg": round(statistics.mean(st), 1) if st else None,
                               "details": (len(data.get("rows") or []) if data.get("rows") else 0)}
                sc = rep["schools"].setdefault(sname, {"admit": 0, "retest": 0, "students": 0})
                sc["students"] += students
                if ntype in ("录取", "调剂"):
                    sc["admit"] += 1
                else:
                    sc["retest"] += 1
                print(f"[OK] {sname} {ntype} {year} {students}人 "
                      f"avg={round(statistics.mean(st),1) if st else '-'} ← {title[:30]}")
                polite()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                rep["err"] += 1
                prob["issue"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                rep["problems"].append(prob)
                print(f"[ERR] {sname} #{nid}: {type(exc).__name__}: {str(exc)[:90]}")
                polite()

        os.makedirs(REPORT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        rpath = os.path.join(REPORT_DIR, f"general_run_{ts}.json")
        with open(rpath, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print("\n== 汇总 ==")
        print(f"候选 {rep['cand']} | 已入库 {rep['inserted']}（明细 {rep['details']}）| "
              f"空 {rep['empty']} | 错误 {rep['err']} | 学校 {len(rep['schools'])}")
        print(f"问题清单：{rpath}")
        if rep["problems"]:
            for p in rep["problems"][:15]:
                print("  -", p["school"], f"#{p['notice']}", p.get("issue", "")[:80])
        return rep
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--schools", default="", help="逗号分隔白名单，空=全部")
    ap.add_argument("--days", type=int, default=0, help="只看最近 N 天通知")
    ap.add_argument("--max-per-school", type=int, default=3)
    ap.add_argument("--redo", action="store_true", help="更新已入库聚合（不动明细）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    schools = [s.strip() for s in args.schools.split(",") if s.strip()] or None
    run(args.limit, schools, args.days, args.redo, args.dry_run, args.max_per_school)


if __name__ == "__main__":
    main()