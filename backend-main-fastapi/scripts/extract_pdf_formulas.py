"""从扫描版 PDF 提取公式并输出 LaTeX 报告。

用途
----
数学类 PDF 几乎全是扫描件，公式在 OCR 里被**读错**（`f(x)`→`f(α)`），
错误文本入库后 LLM 读到的是错误数学式。本脚本用
``services/parsers/pdf_formula_extract.py``（版面检测 + 公式识别，全 ONNX）
把每页的公式识别成 LaTeX，产出可核对的报告。

**当前是「报告模式」，不改库。** 把 LaTeX 精确插回正文需要文本块 bbox
一起参与排序，属于下一阶段；先让人能核对「这页有哪些公式、识别成了什么」。

用法
----
```
# 单份 PDF 的前 3 页，导出裁图 + JSON 报告
python scripts/extract_pdf_formulas.py --pdf "D:/x/某真题.pdf" --max-pages 3 \
    --crops "D:/平台/temp/crops" --report "D:/平台/temp/formula_report.json"

# 按文档 id（从库里查路径）
python scripts/extract_pdf_formulas.py --doc-id 597 --max-pages 2

# 批量：挑污染最重的几篇
python scripts/extract_pdf_formulas.py --top-polluted 5 --max-pages 2
```
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolve_by_doc_id(doc_id: int) -> str:
    from database import SessionLocal
    from models import Document

    db = SessionLocal()
    try:
        d = db.get(Document, doc_id)
        if not d:
            raise SystemExit(f"文档 {doc_id} 不存在")
        print(f"[文档] {doc_id} {d.file_name}")
        return d.file_path or ""
    finally:
        db.close()


def _top_polluted(limit: int) -> list:
    """按「公式误读特征」块数排序，找出污染最重的 PDF。"""
    from database import SessionLocal
    from models import Document, KnowledgeChunk
    from sqlalchemy import func

    pats = ["f(α)", "f（α）", "f(r)", "f（r）", "f()", "f（）", "fLg", "%，，"]
    db = SessionLocal()
    try:
        cond = None
        for p in pats:
            c = KnowledgeChunk.text.ilike(f"%{p}%")
            cond = c if cond is None else (cond | c)
        rows = (
            db.query(KnowledgeChunk.document_id, func.count(KnowledgeChunk.id).label("n"))
            .filter(cond)
            .group_by(KnowledgeChunk.document_id)
            .order_by(func.count(KnowledgeChunk.id).desc())
            .limit(limit * 4)
            .all()
        )
        out = []
        for did, n in rows:
            d = db.get(Document, did)
            if not d or not (d.file_path or "").lower().endswith(".pdf"):
                continue
            if not os.path.exists(d.file_path):
                continue
            out.append({"doc_id": did, "name": d.file_name, "path": d.file_path, "blocks": n})
            if len(out) >= limit:
                break
        return out
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="从扫描版 PDF 提取公式并输出 LaTeX 报告")
    ap.add_argument("--pdf", help="PDF 路径")
    ap.add_argument("--doc-id", type=int, action="append", default=[], help="按文档 id（可多次）")
    ap.add_argument("--top-polluted", type=int, default=0, help="自动取污染最重的 N 篇")
    ap.add_argument("--pages", help="指定页码，逗号分隔（0 基），如 0,1,5")
    ap.add_argument("--max-pages", type=int, default=2, help="每份最多处理多少页（默认 2）")
    ap.add_argument("--dpi", type=int, default=200, help="渲染 DPI（默认 200）")
    ap.add_argument("--min-score", type=float, default=0.3,
                    help="版面检测置信度门槛（实测 0.3 最优，默认 0.3）")
    ap.add_argument("--crops", help="裁图输出目录")
    ap.add_argument("--report", help="JSON 报告输出路径")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = ap.parse_args()

    from services.parsers.pdf_formula_extract import (
        extract_pdf_formulas,
        formulas_to_markdown,
    )

    targets = []
    if args.pdf:
        targets.append({"doc_id": None, "name": os.path.basename(args.pdf), "path": args.pdf})
    for did in args.doc_id:
        targets.append({"doc_id": did, "name": os.path.basename(_resolve_by_doc_id(did)),
                        "path": _resolve_by_doc_id(did)})
    if args.top_polluted:
        for t in _top_polluted(args.top_polluted):
            targets.append(t)
            if not args.quiet:
                print(f"[污染] doc={t['doc_id']:>5} 块={t['blocks']:>4} {t['name'][:50]}")

    if not targets:
        print("没有目标。用 --pdf / --doc-id / --top-polluted 指定。")
        return 2

    pages = None
    if args.pages:
        pages = [int(x) for x in args.pages.split(",") if x.strip().isdigit()]

    reports = []
    grand_t0 = time.time()
    for t in targets:
        p = t["path"]
        if not p or not os.path.exists(p):
            print(f"[跳过] 文件不存在: {p}")
            continue
        out_dir = os.path.join(args.crops, str(t.get("doc_id") or "misc")) if args.crops else None
        t0 = time.time()
        res = extract_pdf_formulas(
            p,
            pages=pages,
            dpi=args.dpi,
            out_dir=out_dir,
            min_score=args.min_score,
            max_pages=args.max_pages if pages is None else 0,
        )
        dt = time.time() - t0
        print(
            f"\n=== {t['name'][:60]} ==="
            f"\n  页 {len(res.pages)}/{res.total_pages} | "
            f"公式 {res.total_formulas} | 成功 {res.total_ok} | "
            f"{res.elapsed_seconds:.1f}s" + (f" | ERROR {res.error}" if res.error else "")
        )
        if res.error:
            reports.append({"target": t, "error": res.error})
            continue

        for pg in res.pages:
            if not args.quiet:
                print(f"\n  --- 第 {pg.page_no} 页（{pg.width}x{pg.height}，{pg.elapsed:.1f}s）---")
                print("  版面:", dict(sorted(pg.layout_counts.items(), key=lambda kv: -kv[1])[:8]))
                md = formulas_to_markdown(pg)
                if md:
                    for line in md.split("\n\n")[:12]:
                        print("   ", line[:110])
                    if len(md.split("\n\n")) > 12:
                        print(f"    ...（共 {len(pg.formulas)} 个公式）")

        reports.append({
            "target": t,
            "seconds": round(dt, 1),
            "result": res.to_dict(),
        })

    if args.report:
        os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(reports, fh, ensure_ascii=False, indent=2)
        print(f"\n[报告] 已写 {args.report}")

    total_f = sum(r.get("result", {}).get("total_formulas", 0) for r in reports if "result" in r)
    total_ok = sum(r.get("result", {}).get("total_ok", 0) for r in reports if "result" in r)
    print(
        f"\n[汇总] {len(reports)} 份 | 公式 {total_f} | 成功 {total_ok}"
        + (f" ({total_ok / total_f:.1%})" if total_f else "")
        + f" | 总耗时 {time.time() - grand_t0:.1f}s"
    )
    print("提示：当前为报告模式，不改库。回写需要在正文混排阶段做。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
