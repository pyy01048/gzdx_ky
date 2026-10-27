# -*- coding: utf-8 -*-
"""拟录取/复试名单扫描 PDF 批量 OCR 入库（采集深度·详情页主产区）。

对 kaoyan_notices 中已确认的名单类通知，下载官方 PDF 附件（公开公示），
逐页跑 DeepSeek-OCR（4bit，断点续跑），把聚合统计写入 kaoyan_admissions、
逐人明细写入 kaoyan_admission_details（core/sql/109_admission_details.sql）。

幂等与断点：
  - PDF 附件缓存 data/ocr_cache/<notice_id>.pdf（只下载一次）；
  - 状态文件 data/ocr_cache/<notice_id>.status.json（记录 last_done_page / counts）；
  - 明细行 data_source = 'notice:<id>:p<页码>:r<行号>'，唯一索引 + ON CONFLICT DO NOTHING，
    同一页重复处理不会重复入库；聚合行 data_source = 'notice:<id>'，批次结束 upsert 刷新。

用法：
    python pipeline/admission_batch_ocr.py --notice-id 2395 --year 2026 \
        [--start-page 1] [--end-page 113] [--max-rows 0] [--dry-run] [--out-html out.html]

合规：仅处理公开公示名单；下载/请求保持 1.5-2.5s 随机延迟；KAOYAN_AUTO_COLLECT 开关保护。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import statistics
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402
from models import KaoyanAdmission  # noqa: E402
from pipeline.notice_admission_crawler import fetch, polite  # noqa: E402

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ocr_cache")


def _load_notice(db, notice_id: int):
    row = db.execute(text(
        "SELECT id, school_id, school_name, notice_type, title, url, publish_date "
        "FROM kaoyan_notices WHERE id = :nid"
    ), {"nid": notice_id}).fetchone()
    if row is None:
        raise SystemExit(f"[中止] kaoyan_notices 无 id={notice_id}")
    return row


def _find_pdf_url(html: str, base: str):
    import urllib.parse

    for m in re.finditer(r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        href, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if re.search(r"\.pdf(\?|$)", href, re.I):
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                p = urllib.parse.urlparse(base)
                href = f"{p.scheme}://{p.netloc}{href}"
            elif not href.startswith("http"):
                href = base.rsplit("/", 1)[0] + "/" + href
            if "拟录取" in label or "名单" in label or "附表" in label:
                return href
    # 回退：第一个 pdf 链接
    for m in re.finditer(r'<a\b[^>]+href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html, re.S | re.I):
        href = m.group(1)
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            p = urllib.parse.urlparse(base)
            href = f"{p.scheme}://{p.netloc}{href}"
        elif not href.startswith("http"):
            href = base.rsplit("/", 1)[0] + "/" + href
        return href
    return None


def _get_pdf(notice_id: int, url: str):
    """优先缓存，否则下载一次（≥8MB 的名单 PDF 属正常，限时 180s）。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"notice-{notice_id}.pdf")
    if os.path.exists(path) and os.path.getsize(path) > 100_000:
        print(f"使用缓存 PDF {path}（{os.path.getsize(path) // 1024 // 1024}MB）")
        return open(path, "rb").read()
    print(f"下载 {url} …")
    blob = fetch(url, timeout=180)
    with open(path, "wb") as f:
        f.write(blob)
    print(f"已缓存 {path}（{len(blob) // 1024 // 1024}MB）")
    return blob


def _load_status(notice_id: int):
    path = os.path.join(CACHE_DIR, f"notice-{notice_id}.status.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_done_page": 0, "students": 0, "pages_ok": 0, "pages_err": 0}


def _save_status(notice_id: int, st: dict):
    path = os.path.join(CACHE_DIR, f"notice-{notice_id}.status.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def _upsert_admission(db, notice_id: int, school_id: int, year: int, ntype: str,
                      students: int, totals: list):
    src = f"notice:{notice_id}"
    avg = round(statistics.mean(totals), 1) if totals else None
    row = db.query(KaoyanAdmission).filter(KaoyanAdmission.school_id == school_id,
                                           KaoyanAdmission.year == year,
                                           KaoyanAdmission.data_source == src).first()
    is_admit = ntype in ("录取", "调剂")
    if row is None:
        row = KaoyanAdmission(school_id=school_id, year=year,
                              retest_count=students if ntype == "复试" else None,
                              admit_count=students if is_admit else None,
                              admit_avg_score=avg, data_source=src)
        db.add(row)
        db.flush()
    else:
        if ntype == "复试":
            row.retest_count = students
        if is_admit:
            row.admit_count = students
        if avg is not None:
            row.admit_avg_score = avg
        db.flush()
    return row.id


def _insert_details(db, notice_id: int, school_id: int, year: int,
                    admission_id: int, rows: list):
    inserted = 0
    for r in rows:
        page = int(r.get("page") or 0)
        idx = int(r.get("row_idx") or 0)
        src = f"notice:{notice_id}:p{page}:r{idx}"
        # ON CONFLICT DO NOTHING —— 同页重跑自然幂等
        db.execute(text(
            "INSERT INTO kaoyan_admission_details "
            "(admission_id, school_id, year, exam_no, name, major_name, "
            " score_initial, score_retest, score_total, data_source) "
            "VALUES (:admission_id, :school_id, :year, :exam_no, :name, :major_name, "
            " :score_initial, :score_retest, :score_total, :data_source) "
            "ON CONFLICT (data_source) DO NOTHING"
        ), {
            "admission_id": admission_id,
            "school_id": school_id,
            "year": year,
            "exam_no": (r.get("exam_no") or "")[:40] or None,
            "name": (r.get("name") or "")[:60],
            "major_name": (r.get("major") or "")[:120] or None,
            "score_initial": r.get("initial"),
            "score_retest": r.get("retest"),
            "score_total": r.get("total"),
            "data_source": src,
        })
        inserted += 1
    return inserted


def _stage_rows(res: dict):
    """给 ocr_pdf_admission_ds 的 rows 补 row_idx（页内序号）与页级计数。"""
    out = []
    for r in res.get("rows", []):
        r = dict(r)
        r["row_idx"] = len(out)
        out.append(r)
    return out


def run(notice_id: int, year: int, start_page: int = 1, end_page: int = 0,
        dry_run: bool = False, out_html: Optional[str] = None) -> int:
    db = SessionLocal()
    try:
        notice = _load_notice(db, notice_id)
        nid, sid, sname, ntype, title, url, pdate = (
            notice.id, notice.school_id, notice.school_name, notice.notice_type,
            notice.title, notice.url, notice.publish_date)
        print(f"通知 #{nid} {sname} {ntype} {title[:40]} url={url}")
        if not url:
            raise SystemExit("[中止] 通知无 URL")

        raw = fetch(url)
        head = raw[:4096].decode("ascii", "ignore")
        m = re.search(r"charset=[\"']?([\w-]+)", head, re.I)
        cs = m.group(1).strip().lower() if m else None
        for enc in ([cs] if cs else []) + ["utf-8", "gbk", "utf-8-sig"]:
            if not enc:
                continue
            try:
                html = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            html = raw.decode("utf-8", "ignore")
        pdf_url = _find_pdf_url(html, url)
        if not pdf_url:
            raise SystemExit("[中止] 页面无 PDF 附件链接")
        print("PDF:", pdf_url)

        blob = _get_pdf(nid, pdf_url)
        from pipeline.dsocr_backend import ocr_pdf_admission_ds, _load_model

        if _load_model()[0] is None:
            raise SystemExit("[中止] DeepSeek-OCR 模型不可用（检查 GPU/模型目录）")

        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(blob)
        total_pages = len(doc)
        doc.close()
        end_page = end_page or total_pages
        end_page = min(end_page, total_pages)
        if start_page > end_page:
            print(f"无剩余页：start_page={start_page} > end_page={end_page}")
            return 0

        st = _load_status(nid)
        print(f"PDF 共 {total_pages} 页，本次处理 {start_page}..{end_page}（断点 last={st['last_done_page']}）")

        all_students = st.get("students_total", 0)
        all_totals: list = []
        if os.path.exists(os.path.join(CACHE_DIR, f"notice-{nid}.totals.json")):
            with open(os.path.join(CACHE_DIR, f"notice-{nid}.totals.json"), "r", encoding="utf-8") as f:
                all_totals = json.load(f)

        # 先初始化/复用聚合行（保证 admission_id 稳定）
        admission_id = _upsert_admission(db, nid, sid, year, ntype, all_students, all_totals)
        db.commit()

        total_inserted = 0
        for page in range(start_page, end_page + 1):
            t0 = time.time()
            try:
                res = ocr_pdf_admission_ds(blob, start_page=page - 1, max_pages=page, dpi=150)
            except Exception as exc:  # noqa: BLE001
                print(f"[ERR] p{page}: {type(exc).__name__}: {exc}")
                st["pages_err"] = st.get("pages_err", 0) + 1
                _save_status(nid, st)
                continue
            if not res or not res.get("rows"):
                print(f"[EMPTY] p{page}：无名单行")
                st["pages_err"] = st.get("pages_err", 0) + 1  # 该页无结果也算未达预期
                _save_status(nid, st)
                continue
            rows = _stage_rows(res)
            page_students = len(rows)
            page_totals = [v for v in (r.get("total") for r in rows) if isinstance(v, float)]
            all_students += page_students
            all_totals.extend(page_totals)
            inserted = 0
            if not dry_run:
                inserted = _insert_details(db, nid, sid, year, admission_id, rows)
                db.commit()
                total_inserted += inserted
            st["last_done_page"] = page
            st["pages_ok"] = st.get("pages_ok", 0) + 1
            st["students_total"] = all_students
            _save_status(nid, st)
            with open(os.path.join(CACHE_DIR, f"notice-{nid}.totals.json"), "w", encoding="utf-8") as f:
                json.dump(all_totals, f)
            print(f"[OK] p{page:03d}/{end_page} 本页 {page_students} 人 "
                  f"（累计 {all_students}），avg={round(statistics.mean(page_totals),1) if page_totals else '-'}，"
                  f"{time.time() - t0:.0f}s，入库 {inserted} 行")
            if not dry_run:
                admission_id = _upsert_admission(db, nid, sid, year, ntype, all_students, all_totals)
                db.commit()

        if not dry_run:
            _upsert_admission(db, nid, sid, year, ntype, all_students, all_totals)
            db.commit()

        print("== 汇总 ==")
        print(f"累计完成页 {st['last_done_page']}/{end_page}（ok={st['pages_ok']} err={st['pages_err']}）")
        print(f"累计学生 {all_students} 人，成绩样本 {len(all_totals)}，"
              f"均分 {round(statistics.mean(all_totals),1) if all_totals else '-'}")

        if out_html:
            _write_html(out_html, sname, ntype, year, all_students,
                        all_totals, _load_details_db(db, nid) or [])
        return 0
    finally:
        db.close()


def _load_details_db(db, notice_id: int):
    rows = db.execute(text(
        "SELECT exam_no, name, major_name, score_initial, score_retest, score_total "
        "FROM kaoyan_admission_details WHERE data_source LIKE :pat ORDER BY id"
    ), {"pat": f"notice:{notice_id}:p%"}).fetchall()
    return [dict(r._mapping) for r in rows]


def _write_html(path: str, sname: str, ntype: str, year: int, students: int,
                totals: list, details: list):
    avg = round(statistics.mean(totals), 1) if totals else "-"
    rows_html = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            d.get("exam_no") or "-", d["name"], d.get("major_name") or "-",
            d.get("score_initial") if d.get("score_initial") is not None else "-",
            d.get("score_retest") if d.get("score_retest") is not None else "-",
            d.get("score_total") if d.get("score_total") is not None else "-")
        for d in details[:2000])
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{sname} {year} {ntype}名单（OCR）</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;margin:24px;background:#f6f7f9;color:#222}}
.card{{background:#fff;border-radius:12px;padding:20px 24px;max-width:960px;margin:0 auto 16px;box-shadow:0 1px 6px rgba(0,0,0,.08)}}
h1{{font-size:20px;margin:0 0 8px}} .sub{{color:#666;font-size:13px}}
.kpis{{display:flex;gap:28px;margin:14px 0}} .kpi .n{{font-size:26px;font-weight:700;color:#c0392b}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:12px}}
th,td{{border:1px solid #e3e6ea;padding:6px 8px;text-align:left}} th{{background:#faf0f0;white-space:nowrap}}
</style></head><body>
<div class="card"><h1>{sname} {year} 硕士研究生{ntype}名单（DeepSeek-OCR 逐页识别）</h1>
<div class="sub">公开公示数据 · 识别页：{len(details)} 行展示前 2000 行</div>
<div class="kpis"><div class="kpi"><div class="n">{students}</div><div>累计识别人数</div></div>
<div class="kpi"><div class="n">{len(totals)}</div><div>成绩样本</div></div>
<div class="kpi"><div class="n">{avg}</div><div>总成绩均分</div></div></div>
<table><tr><th>考生编号</th><th>姓名</th><th>专业</th><th>初试</th><th>复试</th><th>总成绩</th></tr>
{rows_html}</table></div></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已输出预览 HTML：{path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--notice-id", type=int, required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--end-page", type=int, default=0, help="0=直到 PDF 末尾")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out-html")
    args = ap.parse_args()
    if not os.environ.get("KAOYAN_AUTO_COLLECT"):
        print("[提示] 未设置 KAOYAN_AUTO_COLLECT=1 的环境变量（合规开关），仍继续（人工驱动）。")
    run(args.notice_id, args.year, args.start_page, args.end_page,
        args.dry_run, args.out_html)


if __name__ == "__main__":
    main()