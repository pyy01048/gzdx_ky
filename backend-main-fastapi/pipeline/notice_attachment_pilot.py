# -*- coding: utf-8 -*-
"""试点：院校通知附件（xlsx/csv）→ kaoyan_admissions 结构化采集。

流程：复试/录取类通知 → 抓通知页 → 找表格附件（xlsx/xls/csv）→ 下载 →
openpyxl 解析名单（拟录取：人数/均分/最低分；复试：人数）→ 单校单事务入库。
合规：仅公开页面，1.5-2.5s 限速，附件 ≤8MB，data_source 溯源到通知 URL。
"""
import io
import re
import sys
import time
import random
import traceback
from datetime import datetime, timezone
from pathlib import Path

# 仓库根目录按文件位置推导（原先写死本机 D:\平台\...，换机即失效，
# 且 test_path_binding_guard 会红）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import urllib.request  # noqa: E402

import openpyxl  # noqa: E402
from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402
from models import KaoyanAdmission  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36 PersonalStudyTool/1.0 (kaoyan personal use)"}
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 20


def naive_utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def polite():
    time.sleep(random.uniform(1.5, 2.5))


def find_attachments(html: str, base: str):
    """从通知页 HTML 提取表格附件链接（绝对化）。"""
    out = []
    for m in re.finditer(r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        href, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if re.search(r"\.(xlsx|xls|csv)(\?|$)", href, re.I):
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                p = urllib.parse.urlparse(base)
                href = f"{p.scheme}://{p.netloc}{href}"
            elif not href.startswith("http"):
                href = base.rsplit("/", 1)[0] + "/" + href
            out.append((href, label))
    return out


def parse_roster(xlsx_bytes: bytes):
    """解析名单表 → {kind, year_hint, rows:[{major, total}], stat:{admit_count, admit_avg, admit_min}}。

    识别含「姓名」的表头行；总分列取 (初试成绩|总分|总成绩|成绩) 之一；
    专业列取 (专业|学科|方向) 之一。
    """
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    return _extract_from_rows_iter(wb.worksheets)


def _extract_from_rows_iter(sheets_iter):
    for ws in sheets_iter:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if not rows:
            continue
        header_idx, header = None, None
        for i, row in enumerate(rows[:20]):
            cells = [str(c or "") for c in row]
            joined = "".join(cells)
            if "姓名" in joined:
                header_idx, header = i, cells
                break
        if header_idx is None:
            continue
        cols = {name: j for j, name in enumerate(header)}
        total_col = next((cols[k] for k in cols if re.search(r"初试成绩|总成绩|总分|复试成绩|成绩", k)), None)
        major_col = next((cols[k] for k in cols if re.search(r"专业|学科|方向|领域", k)), None)
        name_col = next((j for j, k in enumerate(cols) if "姓名" in k), None)
        if name_col is None:
            continue
        students, totals = 0, []
        majors = {}
        for row in rows[header_idx + 1:]:
            nm = row[name_col] if name_col < len(row) else None
            if not nm or not str(nm).strip():
                continue
            if re.search(r"姓名|注：|备注|合计|平均", str(nm)):
                continue
            students += 1
            if total_col is not None and total_col < len(row):
                try:
                    v = float(row[total_col])
                    totals.append(v)
                except (TypeError, ValueError):
                    pass
            if major_col is not None and major_col < len(row) and row[major_col]:
                majors[str(row[major_col]).strip()[:60]] = majors.get(str(row[major_col]).strip()[:60], 0) + 1
        if students < 3:  # 名单太短，误判可能性大
            continue
        stat = {"students": students}
        if totals:
            stat["avg"] = round(sum(totals) / len(totals), 1)
            stat["min"] = min(totals)
        return {"stat": stat, "majors": majors, "sheet": ws.title, "has_scores": bool(totals)}
    return None


def parse_roster_html(html: str):
    """解析网页内嵌 <table> 名单（拟录取/复试名单多为网页表格而非附件）。"""
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
                self._t = None
            elif tag == "tr" and self._r is not None:
                self._t.append(self._r)
                self._r = None
            elif tag in ("td", "th") and self._c is not None:
                self._r.append("".join(self._c).strip())
                self._c = None

        def handle_data(self, data):
            if self._c is not None:
                self._c.append(data)

    p = TP()
    p.feed(html)

    class _WS:
        """把 HTML 表适配成 openpyxl worksheet 的 iter_rows 接口。"""

        def __init__(self, rows, title):
            self._rows = rows
            self.title = title

        def iter_rows(self, values_only=True):
            for r in self._rows:
                yield tuple(r)

    for i, t in enumerate(p.tables):
        joined = "".join("".join(str(c or "") for c in row) for row in t[:8])
        if "姓名" in joined:
            res = _extract_from_rows_iter([_WS(t, f"html-table-{i}")])
            if res:
                return res
    return None


def main():
    db = SessionLocal()
    report = {"checked": 0, "with_attach": 0, "downloaded": 0, "parsed": 0,
              "inserted": 0, "pdf_only": 0, "errors": 0, "details": []}
    try:
        rows = db.execute(text(
            "SELECT n.id, n.school_id, n.school_name, n.notice_type, n.title, n.url, n.publish_date "
            "FROM kaoyan_notices n WHERE n.url IS NOT NULL AND n.url <> '' "
            "AND n.notice_type IN ('复试','录取') ORDER BY n.publish_date DESC NULLS LAST LIMIT :lim"
        ), {"lim": LIMIT}).fetchall()
        print(f"候选通知 {len(rows)} 条")
        for nid, sid, sname, ntype, title, url, pdate in rows:
            report["checked"] += 1
            try:
                year = int((pdate or "")[:4]) if pdate else 2026
                html_bytes = fetch(url)
                try:
                    html = html_bytes.decode("utf-8", "ignore")
                except Exception:
                    html = html_bytes.decode("gbk", "ignore")
                atts = find_attachments(html, url)
                table_atts = [(h, l) for h, l in atts]
                if not table_atts:
                    if re.search(r"\.pdf", html, re.I):
                        report["pdf_only"] += 1
                    embedded = parse_roster_html(html)  # 无附件 → 页面内嵌表格
                    if embedded:
                        st = embedded["stat"]
                        year2 = int((pdate or "")[:4]) if pdate else 2026
                        src2 = f"notice:{nid}"
                        ex2 = db.query(KaoyanAdmission.id).filter(
                            KaoyanAdmission.school_id == sid, KaoyanAdmission.year == year2,
                            KaoyanAdmission.data_source == src2).first()
                        if not ex2:
                            db.add(KaoyanAdmission(
                                school_id=sid, year=year2,
                                retest_count=st["students"] if ntype == "复试" else None,
                                admit_count=st["students"] if ntype == "录取" else None,
                                admit_avg_score=st.get("avg"),
                                data_source=src2,
                            ))
                            db.commit()
                            report["inserted"] += 1
                            report["parsed"] += 1
                        report["details"].append({"id": nid, "school": sname, "status": "embedded_ok",
                                                  "students": st["students"], "avg": st.get("avg")})
                        print(f"[EMB] {sname} {ntype} {year2}: {st['students']}人 avg={st.get('avg')} ← {title[:24]}")
                    else:
                        report["details"].append({"id": nid, "school": sname, "status": "no_table_attach"})
                    polite()
                    continue
                report["with_attach"] += 1
                href, label = table_atts[0]
                blob = fetch(href, timeout=40)
                if len(blob) > 8 * 1024 * 1024:
                    report["details"].append({"id": nid, "school": sname, "status": "too_big"})
                    polite()
                    continue
                report["downloaded"] += 1
                if href.lower().endswith(".csv"):
                    parsed = None  # CSV 名单结构千奇百怪，试点阶段跳过
                else:
                    parsed = parse_roster(blob)
                if not parsed:
                    parsed = parse_roster_html(html)  # 附件解析失败 → 页面内嵌表格兜底
                if not parsed:
                    report["details"].append({"id": nid, "school": sname, "status": "parse_fail"})
                    polite()
                    continue
                report["parsed"] += 1
                st = parsed["stat"]
                # 幂等：同校同年同来源只写一行（按 data_source 判重）
                src = f"notice:{nid}"
                exists = db.query(KaoyanAdmission.id).filter(
                    KaoyanAdmission.school_id == sid, KaoyanAdmission.year == year,
                    KaoyanAdmission.data_source == src).first()
                if not exists:
                    db.add(KaoyanAdmission(
                        school_id=sid, year=year,
                        retest_count=st["students"] if ntype == "复试" else None,
                        admit_count=st["students"] if ntype == "录取" else None,
                        admit_avg_score=st.get("avg"),
                        data_source=src,
                    ))
                    db.commit()
                    report["inserted"] += 1
                report["details"].append({
                    "id": nid, "school": sname, "type": ntype, "year": year,
                    "students": st["students"], "avg": st.get("avg"), "min": st.get("min"),
                    "majors_top": sorted(parsed["majors"].items(), key=lambda x: -x[1])[:2],
                })
                print(f"[OK] {sname} {ntype} {year}: {st['students']}人 avg={st.get('avg')} ← {title[:24]}")
                polite()
            except Exception as e:  # noqa: BLE001
                db.rollback()
                report["errors"] += 1
                report["details"].append({"id": nid, "school": sname, "status": "error", "err": str(e)[:100]})
                polite()
        print("REPORT", {k: v for k, v in report.items() if k != "details"})
    finally:
        db.close()


if __name__ == "__main__":
    main()
