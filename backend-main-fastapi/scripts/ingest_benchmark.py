# -*- coding: utf-8 -*-
"""批量入库基准脚本：把一批 PDF 跑一遍 ``ingest_pdf``，出汇总报告。

用法
----
    # 干跑（默认，不写库）
    D:/Anaconda/python.exe scripts/ingest_benchmark.py --pdf "D:/材料/真题" --limit 5

    # 真写库
    D:/Anaconda/python.exe scripts/ingest_benchmark.py --pdf "D:/材料/真题" --limit 5 --write

    # 输出 JSON 报告
    D:/Anaconda/python.exe scripts/ingest_benchmark.py --pdf a.pdf --write --out report.json

**安全**：不加 ``--write`` 时**绝不写库**（只解析、统计）。
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
import time
import traceback
from typing import Any, Dict, List

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

#: 扫描目录时的 PDF 后缀
PDF_SUFFIXES = (".pdf",)


def _collect_pdfs(target: str, limit: int) -> List[str]:
    """把 --pdf 参数（文件或目录）解析成 PDF 列表。"""
    if os.path.isfile(target):
        return [os.path.abspath(target)][:limit] if limit > 0 else [os.path.abspath(target)]
    if not os.path.isdir(target):
        return []
    found: List[str] = []
    for root, _dirs, files in os.walk(target):
        for name in sorted(files):
            if name.lower().endswith(PDF_SUFFIXES):
                found.append(os.path.abspath(os.path.join(root, name)))
    found.sort()
    return found[:limit] if limit > 0 else found


def _fmt_secs(value: float) -> str:
    return f"{value:.2f}s"


def _load_parse_fn(spec: str):
    """``--parse-fn module:attr`` → 解析函数。

    * attr 是类 → 实例化后取 ``.parse``（如 ``services.parsers.pymupdf_parser:PyMuPDFParser``）
    * attr 是函数 → 直接用（如 ``mymod:parse``）

    路由入口 ``services.parsers.router.route_parse`` 就绪后**不需要**这个参数。
    """
    import importlib

    if ":" not in spec:
        raise SystemExit(f"--parse-fn 格式应为 module:attr，收到 {spec!r}")
    module_name, attr = spec.split(":", 1)
    module = importlib.import_module(module_name)
    obj = getattr(module, attr, None)
    if obj is None:
        raise SystemExit(f"{module_name} 里没有 {attr}")
    if inspect.isclass(obj):
        instance = obj()
        parse = getattr(instance, "parse", None)
        if parse is None:
            raise SystemExit(f"{module_name}.{attr} 既不是函数也没有 .parse()")
        return parse
    return obj


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="批量入库基准（ingest_pdf 汇总报告）")
    parser.add_argument("--pdf", required=True, help="PDF 文件或目录")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少份（0=不限）")
    parser.add_argument("--write", action="store_true", help="真写库（默认只干跑）")
    parser.add_argument("--dry-run", action="store_true", help="只干跑（默认行为，显式声明）")
    parser.add_argument("--out", default="", help="JSON 报告输出路径")
    parser.add_argument("--subject", default="", help="科目（写进 documents.subject）")
    parser.add_argument("--max-pages", type=int, default=None, help="每份最多解析多少页")
    parser.add_argument("--parse-fn", default="", help="解析函数 module:attr（默认用 route_parse）")
    parser.add_argument("--document-id", type=int, default=None,
                        help="写入指定的 documents.id（不传则每次新建文档；传同一个 id 可验证幂等）")
    args = parser.parse_args(argv)

    write = bool(args.write) and not args.dry_run
    pdfs = _collect_pdfs(args.pdf, args.limit)
    if not pdfs:
        print(f"[!] 没找到 PDF：{args.pdf}")
        return 2

    print(f"[i] 待处理 {len(pdfs)} 份 PDF｜模式：{'写库' if write else '干跑（不写库）'}")

    from database import SessionLocal
    from services.ingest_pipeline import ingest_pdf

    parse_fn = _load_parse_fn(args.parse_fn) if args.parse_fn else None

    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    totals = {"pages": 0, "blocks": 0, "questions": 0, "figures_bound": 0, "figure_missing": 0}
    grades = {"A": 0, "B": 0, "C": 0, "JUNK": 0}
    started = time.time()

    for index, pdf_path in enumerate(pdfs, start=1):
        name = os.path.basename(pdf_path)
        db = SessionLocal()
        try:
            stats = ingest_pdf(
                db,
                pdf_path,
                document_id=args.document_id,
                subject=args.subject,
                max_pages=args.max_pages,
                parse_fn=parse_fn,
                write=write,
            )
            for key in totals:
                totals[key] += int(stats.get(key, 0) or 0)
            for key in grades:
                grades[key] += int(stats.get("grades", {}).get(key, 0) or 0)
            results.append({
                "file": name,
                "path": pdf_path,
                "kind": stats.get("pdf_kind"),
                "engine": stats.get("engine"),
                "elapsed_seconds": stats.get("elapsed_seconds"),
                "pages": stats.get("pages"),
                "blocks": stats.get("blocks"),
                "questions": stats.get("questions"),
                "figures_bound": stats.get("figures_bound"),
                "figure_missing": stats.get("figure_missing"),
                "grades": stats.get("grades"),
                "document_id": stats.get("document_id"),
                "issues": len(stats.get("issues", []) or []),
            })
            print(
                f"[{index}/{len(pdfs)}] {name}｜kind={stats.get('pdf_kind')}"
                f" engine={stats.get('engine')} 用时={_fmt_secs(stats.get('elapsed_seconds') or 0)}"
                f" 页={stats.get('pages')} 块={stats.get('blocks')} 题={stats.get('questions')}"
                f" 配图={stats.get('figures_bound')} 缺图={stats.get('figure_missing')}"
            )
        except Exception as exc:  # noqa: BLE001 - 单份失败不中断整批
            failures.append({
                "file": name,
                "path": pdf_path,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=6),
            })
            print(f"[{index}/{len(pdfs)}] {name}｜失败：{type(exc).__name__}: {exc}")
        finally:
            db.rollback()
            db.close()

    report = {
        "mode": "write" if write else "dry-run",
        "target": args.pdf,
        "file_count": len(pdfs),
        "ok_count": len(results),
        "failed_count": len(failures),
        "total_elapsed_seconds": round(time.time() - started, 3),
        "totals": totals,
        "grades": grades,
        "results": results,
        "failures": failures,
    }

    print("\n===== 汇总 =====")
    print(f"成功 {len(results)} / 失败 {len(failures)}｜总用时 {_fmt_secs(report['total_elapsed_seconds'])}")
    print(f"页 {totals['pages']}｜块 {totals['blocks']}｜题 {totals['questions']}"
          f"｜配图命中 {totals['figures_bound']}｜缺图 {totals['figure_missing']}")
    print(f"门禁分布：A={grades['A']} B={grades['B']} C={grades['C']} JUNK={grades['JUNK']}")
    if failures:
        print("\n失败清单：")
        for item in failures:
            print(f"  - {item['file']}：{item['error']}")

    if args.out:
        out_path = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"\n[OK] 报告已写出：{out_path}")

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
