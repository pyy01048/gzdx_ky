# -*- coding: utf-8 -*-
"""探测源文件夹下所有 PDF：分类（digital/scanned/hybrid）、页数、估计 OCR 页数、科目、文件用途。

不做 OCR，只做文字层探测，输出 .temp/pdf_manifest.json 供规划。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.parsers.pdf_classifier import classify_pdf, needs_ocr_pages  # noqa: E402

ROOT = os.environ.get("PDF_SOURCE_ROOT", r"D:\下载\QQ\压缩文件.zip\压缩文件")
OUT = os.path.join(_BACKEND_ROOT, ".temp", "pdf_manifest.json")


def file_fingerprint(path):
    st = os.stat(path)
    return hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()


NAME_HAS_QUESTIONS = re.compile(
    r"题库|习题|真题|题解|试题|考研真题|课后习题|习题集|错题|1000题|300题|777题|260题|模拟题"
)
NAME_IS_NOTES = re.compile(r"笔记|复习笔记|知识总结|提纲|讲义|复习要点|公式总结|概念公式|课件|全程导学|习题全解|答案")


def subject_from_path(path: str, root: str) -> str:
    rel = os.path.relpath(path, root)
    parts = rel.split(os.sep)
    # 学科\XX.科目名\...  或  教材\NNN.科目名\...
    if len(parts) >= 2 and parts[0] in ("学科", "教材"):
        seg = parts[1]
        m = re.match(r"^\d+\.?\s*(.+)$", seg)
        return m.group(1).strip() if m else seg.strip()
    # 学科\信号与系统\...（无编号）
    if len(parts) >= 2 and parts[0] == "学科":
        return parts[1].strip()
    return parts[0].strip() if parts else ""


def file_category(name: str, top: str) -> str:
    if top == "教材":
        return "textbook"
    if NAME_HAS_QUESTIONS.search(name):
        return "questions"
    if NAME_IS_NOTES.search(name):
        return "notes"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT, help="PDF 源目录；也可用环境变量 PDF_SOURCE_ROOT")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    if not os.path.isdir(args.root):
        ap.error(f"PDF 源目录不存在：{args.root}")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    rows = []
    n_ok = n_err = 0
    pages_scanned = pages_hybrid = pages_digital = 0
    ocr_pages_est = 0
    for dirpath, _dirs, files in os.walk(args.root):
        for fn in files:
            if not fn.lower().endswith(".pdf"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, args.root)
            top = rel.split(os.sep)[0]
            rec = {
                "rel": rel,
                "name": fn,
                "top": top,
                "subject": subject_from_path(path, args.root),
                "category": file_category(fn, top),
                "size_mb": round(os.path.getsize(path) / 1024 / 1024, 1),
                "size_bytes": os.path.getsize(path),
                "fp": file_fingerprint(path),
            }
            try:
                prof = classify_pdf(path)
                kind = prof.kind
                rec.update(kind=kind, pages=prof.total_pages, avg_chars=round(prof.avg_chars_per_page, 1))
                if kind == "scanned":
                    ocr = prof.total_pages
                    pages_scanned += prof.total_pages
                elif kind == "hybrid":
                    ocr = len(needs_ocr_pages(prof))
                    pages_hybrid += prof.total_pages
                else:
                    ocr = 0
                    pages_digital += prof.total_pages
                rec["ocr_pages_est"] = ocr
                ocr_pages_est += ocr
                n_ok += 1
            except Exception as e:
                rec.update(kind="error", pages=0, avg_chars=0, ocr_pages_est=0, error=f"{type(e).__name__}: {e}")
                n_err += 1
            rows.append(rec)
    summary = {
        "total_pdfs": len(rows),
        "classified_ok": n_ok,
        "errors": n_err,
        "pages_scanned": pages_scanned,
        "pages_hybrid": pages_hybrid,
        "pages_digital": pages_digital,
        "ocr_pages_est_total": ocr_pages_est,
        "by_kind": {},
        "by_category": {},
    }
    for r in rows:
        summary["by_kind"][r["kind"]] = summary["by_kind"].get(r["kind"], 0) + 1
        summary["by_category"][r["category"]] = summary["by_category"].get(r["category"], 0) + 1
    summary["by_subject"] = {}
    for r in rows:
        s = r["subject"]
        summary["by_subject"].setdefault(s, {"pdfs": 0, "ocr_pages_est": 0, "pages": 0})
        summary["by_subject"][s]["pdfs"] += 1
        summary["by_subject"][s]["ocr_pages_est"] += r.get("ocr_pages_est", 0)
        summary["by_subject"][s]["pages"] += r.get("pages", 0)
    payload = {"summary": summary, "files": rows}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nmanifest -> {args.out}")


if __name__ == "__main__":
    main()
