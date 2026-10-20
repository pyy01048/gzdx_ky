# -*- coding: utf-8 -*-
"""院校招生数据逐一采集器（v2 严格门禁版）。

从 kaoyan_notices 的复试/录取类通知中逐一获取官方数据：
  通知详情页 → 网页内嵌表格 / xlsx 附件 → 姓名+成绩名单 → 质量门 → kaoyan_admissions。

质量门（2026-10-19 试点教训）：
  1. 标题强过滤：必须含 拟录取|录取名单|复试名单|复试结果|成绩公示；
     排除 博士|硕博|直博|档案|政审|调档|推免（接收）|国优（专项口径混）。
  2. 表格门：须含「姓名」列；成绩列中位数必须落在 [150, 500]（硕士初试总分区间），
     全表 ≤100 视为面试/复试成绩 → 只记人数不记均分。
  3. 幂等：data_source = notice:<id>，重跑不重复。
  4. 合规：仅公开页，1.5-2.5s 限速，附件 ≤8MB。
"""
import io
import re
import sys
from pathlib import Path
import time
import random
import statistics
import traceback
from datetime import datetime, timezone

# 仓库根目录按文件位置推导（原先写死本机 D:\平台\...，换机即失效，
# 且 test_path_binding_guard 会红）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402

import openpyxl  # noqa: E402
from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402
from models import KaoyanAdmission  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36 PersonalStudyTool/1.0 (kaoyan personal use)"}
TITLE_OK = re.compile(r"拟录取|录取名单|复试名单|复试结果|成绩公示|复试成绩")
TITLE_NO = re.compile(r"博士|硕博|直博|档案|政审|调档|推免|推荐免试|推免生|港澳台|工商管理硕士|EMBA|国优|少干|骨干人才|退役|士兵计划|同等学力")
SCORE_MIN, SCORE_MAX = 150, 500


def polite():
    time.sleep(random.uniform(1.5, 2.5))


def _decode_html(raw: bytes) -> str:
    """按页面声明/回退顺序解码，兼容 GBK 站点与残缺 UTF-8。"""
    head = raw[:4096].decode("ascii", "ignore")
    m = re.search(r"charset=[\"']?([\w-]+)", head, re.I)
    cs = m.group(1).strip().lower() if m else None
    cands = []
    if cs:
        cands.append(cs)
    cands += ["utf-8", "gbk", "utf-8-sig"]
    for enc in cands:
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore")


_SSL_CTX = None


def _loose_ssl_ctx():
    """高校站点常见老旧 TLS/证书 → 降级重试一次。"""
    global _SSL_CTX
    if _SSL_CTX is None:
        import ssl

        _SSL_CTX = ssl.create_default_context()
        _SSL_CTX.check_hostname = False
        _SSL_CTX.verify_mode = ssl.CERT_NONE
        try:
            _SSL_CTX.minimum_version = ssl.TLSVersion.TLSv1
        except Exception:  # noqa: BLE001
            pass
    return _SSL_CTX


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:  # noqa: BLE001
        with urllib.request.urlopen(req, timeout=timeout, context=_loose_ssl_ctx()) as r:
            return r.read()


def parse_pdf(blob: bytes):
    """拟录取名单最常见形态是 PDF 附表 → pdfplumber 抽表。

    无文字层（扫描件）自动降级：走 pdf_scan_ocr 的 RapidOCR 兜底，
    超大 PDF（>15MB，多为整刊/高清扫描件）先跳过 pdfplumber 直接 OCR。
    """
    big = len(blob) > 15 * 1024 * 1024
    if not big:
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
        except Exception:  # noqa: BLE001 —— 打开的解析失败（损坏/加密）也交给 OCR 兜底
            pass
    # 扫描件/超大 PDF 兜底：DeepSeek-OCR（本机 GPU，结构化 HTML 表格）优先，
    # 不可用时回退 pypdfium2 渲染 + RapidOCR（CPU）名单重构。
    try:
        from pipeline.dsocr_backend import ocr_pdf_admission as ds_ocr

        res = ds_ocr(blob)
        if res:
            return res
    except Exception:  # noqa: BLE001
        pass
    from pipeline.pdf_scan_ocr import ocr_pdf_admission

    try:
        res = ocr_pdf_admission(blob)
        return res or None
    except Exception:  # noqa: BLE001
        return None


def find_table_attachments(html: str, base: str):
    out = []
    for m in re.finditer(r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        href, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if re.search(r"\.(xlsx|xls|pdf)(\?|$)", href, re.I):
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                p = urllib.parse.urlparse(base)
                href = f"{p.scheme}://{p.netloc}{href}"
            elif not href.startswith("http"):
                href = base.rsplit("/", 1)[0] + "/" + href
            out.append(href)
    return out


def _extract_table(rows, sheet_name):
    """名单表提取：返回 {students, totals, majors, rows} 或 None。质量门在此。"""
    header_idx, header = None, None
    for i, row in enumerate(rows[:20]):
        joined = "".join(str(c or "") for c in row)
        if re.search(r"姓名|准考证号|考号|学号", joined):
            header_idx, header = i, [str(c or "") for c in row]
            break
    if header_idx is None:
        return None
    cols = {name: j for j, name in enumerate(header)}
    total_col = next((cols[k] for k in cols if re.search(r"初试成绩|总成绩|总分", k)), None)
    name_col = next((j for j, k in enumerate(cols) if re.search(r"姓名|准考证号|考号|学号", k)), None)
    major_col = next((cols[k] for k in cols if re.search(r"专业|学科|方向|领域", k)), None)
    exam_col = next((cols.get(k) for k in cols if re.search(r"考生编号|准考证号|考号|学号", k)), None)
    score_retest_col = next((cols.get(k) for k in cols if re.search(r"复试成绩|复试分数", k)), None)
    score_initial_col = next((cols.get(k) for k in cols
                              if re.search(r"初试成绩|初试总分|初试分数", k)), None)
    if name_col is None:
        return None
    students, totals, majors = 0, [], {}
    detail_rows = []
    for row in rows[header_idx + 1:]:
        nm = row[name_col] if name_col < len(row) else None
        # 表头噪音行 + 未录取/放弃/不合规行（如"调剂不录取"）一律不计入名单
        if not nm or not str(nm).strip() or re.search(r"姓名|准考证号|考号|学号|注：|备注|合计|平均|未录取|放弃|不合格|不予录取|不录取", str(nm)):
            continue
        students += 1
        rec = {"name": str(nm).strip()[:60]}
        if exam_col is not None and exam_col < len(row) and row[exam_col]:
            rec["exam_no"] = str(row[exam_col]).strip()[:40]
        if major_col is not None and major_col < len(row) and row[major_col]:
            m = str(row[major_col]).strip()[:120]
            rec["major"] = m
            majors.setdefault(m[:60], 0)
            majors[m[:60]] += 1
        for key, col in (("total", total_col), ("retest", score_retest_col),
                         ("initial", score_initial_col)):
            if col is not None and col < len(row) and row[col] is not None:
                try:
                    rec[key] = float(row[col])
                except (TypeError, ValueError):
                    pass
        if "total" in rec:
            totals.append(rec["total"])
        detail_rows.append(rec)
    if students == 0:
        return None
    if totals and not (SCORE_MIN <= statistics.median(totals) <= SCORE_MAX):
        totals = []  # 中位数不在硕士总分区间 → 不记均分（只记人数）
    return {"students": students, "totals": totals, "majors": majors, "rows": detail_rows}


def parse_xlsx(blob: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        res = _extract_table(rows, ws.title) if rows else None
        if res:
            return res
    return None


class _WS:
    def __init__(self, rows, title):
        self._rows, self.title = rows, title

    def iter_rows(self, values_only=True):
        for r in self._rows:
            yield tuple(r)


def parse_html_tables(html: str):
    from html.parser import HTMLParser

    class TP(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tables, self._t, self._r, self._c = [], None, None, None

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self._t = []
            elif tag == "tr" and self._t is not None:
                self._r = []
            elif tag in ("td", "th") and self._r is not None:
                self._c = []

        def handle_endtag(self, tag):
            if tag == "table" and self._t is not None:
                if self._t:
                    self.tables.append(self._t)
                self._t = self._r = self._c = None
            elif tag == "tr" and self._t is not None and self._r is not None:
                self._t.append(self._r)
                self._r = None
            elif tag in ("td", "th") and self._r is not None and self._c is not None:
                self._r.append("".join(self._c).strip())
                self._c = None

        def handle_data(self, data):
            if self._c is not None:
                self._c.append(data)

    p = TP()
    p.feed(html)
    for i, t in enumerate(p.tables):
        head = "".join("".join(str(c or "") for c in row) for row in t[:8])
        if "姓名" in head:
            res = _extract_table(t, f"html-{i}")
            if res:
                return res
    return None


def main(limit=80):
    db = SessionLocal()
    rep = {"cand": 0, "fetched": 0, "got_data": 0, "inserted": 0, "err": 0, "per_school": {}}
    try:
        rows = db.execute(text(
            "SELECT id, school_id, school_name, notice_type, title, url, publish_date "
            "FROM kaoyan_notices WHERE url IS NOT NULL AND url <> '' "
            "AND title ~ :pat AND title !~ :patno "
            "ORDER BY publish_date DESC NULLS LAST LIMIT :lim"
        ), {"pat": TITLE_OK.pattern, "patno": TITLE_NO.pattern, "lim": limit}).fetchall()
        print(f"候选（强过滤后）{len(rows)} 条")
        for nid, sid, sname, ntype, title, url, pdate in rows:
            rep["cand"] += 1
            try:
                year = int((pdate or "")[:4]) if pdate else 2026
                src = f"notice:{nid}"
                if db.query(KaoyanAdmission.id).filter(
                        KaoyanAdmission.school_id == sid, KaoyanAdmission.year == year,
                        KaoyanAdmission.data_source == src).first():
                    continue
                raw = fetch(url)
                html = _decode_html(raw)
                rep["fetched"] += 1
                data = None
                for href in find_table_attachments(html, url)[:3]:
                    try:
                        blob = fetch(href, timeout=60)
                        if href.lower().endswith(".pdf"):
                            data = parse_pdf(blob)
                        else:
                            data = parse_xlsx(blob)
                        if data:
                            break
                        polite()
                    except Exception:  # noqa: BLE001
                        polite()
                if not data:
                    data = parse_html_tables(html)
                if not data:
                    polite()
                    continue
                rep["got_data"] += 1
                st = data["totals"]
                is_admit = ntype in ("录取", "调剂")  # 调剂公示多为"校内/院系调剂拟录取名单"
                db.add(KaoyanAdmission(
                    school_id=sid, year=year,
                    retest_count=data["students"] if ntype == "复试" else None,
                    admit_count=data["students"] if is_admit else None,
                    admit_avg_score=round(statistics.mean(st), 1) if st else None,
                    data_source=src,
                ))
                db.commit()
                rep["inserted"] += 1
                ps = rep["per_school"].setdefault(sname, {"admit": 0, "retest": 0})
                if is_admit or ntype == "录取":
                    ps["admit"] += 1
                else:
                    ps["retest"] += 1
                print(f"[OK] {sname} {ntype} {year} {data['students']}人 "
                      f"avg={round(statistics.mean(st),1) if st else '-'} ← {title[:30]}")
                polite()
            except Exception as e:  # noqa: BLE001
                db.rollback()
                rep["err"] += 1
                print(f"[ERR] {sname}: {str(e)[:90]}")
                polite()
        print("REPORT", rep)
    finally:
        db.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 80)
