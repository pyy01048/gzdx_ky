# -*- coding: utf-8 -*-
"""知识库快速入库 CLI（集各家所长 · 新文件快速入库）。

用法：
    python scripts\\ingest_inbox.py                     # 扫描 knowledge_base/inbox 全部文件并入库
    python scripts\\ingest_inbox.py --dry-run           # 只扫描不落库（预演）
    python scripts\\ingest_inbox.py --ocr-backend paddle # 指定 OCR 后端（auto/local-gpu/paddleocr/rapidocr）
    python scripts\\ingest_inbox.py --file <path>       # 快速入库单个文件
    python scripts\\ingest_inbox.py --no-embed          # 跳过向量化
    python scripts\\ingest_inbox.py --no-move           # 入库后不移动原件
    python scripts\\ingest_inbox.py --recursive         # 递归扫描 inbox 子目录
    python scripts\\ingest_inbox.py --status            # 查看 OCR 路由与 knowledge_base 状态

前置：backend-main-fastapi 已安装依赖（pypdf/docx/pptx/rapidocr 等，与既有解析器一致）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _load_env_path() -> str:
    """从 backend-main-fastapi 目录启动时可直接 import services；否则追加到 sys.path。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (here, os.path.dirname(here)):
        if os.path.isfile(os.path.join(cand, "main.py")):
            if cand not in sys.path:
                sys.path.insert(0, cand)
            return cand
    return here


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库快速入库 CLI")
    parser.add_argument("--file", help="入库单个文件（绝对路径）")
    parser.add_argument("--dry-run", action="store_true", help="只扫描/预演，不落库")
    parser.add_argument("--ocr-backend", default="auto",
                        help="OCR 后端：auto/local-gpu/paddleocr/rapidocr/chineseocr-lite")
    parser.add_argument("--no-embed", action="store_true", help="跳过向量化")
    parser.add_argument("--no-move", action="store_true", help="入库后不移动原件")
    parser.add_argument("--recursive", action="store_true", help="递归扫描 inbox 子目录")
    parser.add_argument("--status", action="store_true", help="查看 OCR 路由与 knowledge_base 状态")
    args = parser.parse_args()

    _load_env_path()

    if args.status:
        from services.ocr_router import get_ocr_router
        from services import kb_ingest

        router = get_ocr_router()
        print(json.dumps({
            "ocr_router": router.status(),
            "knowledge_base": {
                "root": kb_ingest.KB_ROOT,
                "inbox": kb_ingest.INBOX_DIR,
                "documents": kb_ingest.DOCUMENTS_DIR,
                "meta": kb_ingest.MANIFEST_PATH,
                "exists": all(os.path.isdir(d) for d in
                              (kb_ingest.INBOX_DIR, kb_ingest.DOCUMENTS_DIR, kb_ingest.META_DIR)),
            },
        }, ensure_ascii=False, indent=2))
        return 0

    from database import SessionLocal
    from services import kb_ingest

    db = SessionLocal()
    try:
        if args.file:
            result = kb_ingest.ingest_file(
                db, args.file,
                ocr_backend=args.ocr_backend,
                do_embeddings=not args.no_embed,
                move_to_documents=not args.no_move,
                dry_run=args.dry_run,
            )
        else:
            result = kb_ingest.scan_inbox(
                db,
                ocr_backend=args.ocr_backend,
                do_embeddings=not args.no_embed,
                move_to_documents=not args.no_move,
                dry_run=args.dry_run,
                recursive=args.recursive,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
