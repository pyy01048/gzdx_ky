# -*- coding: utf-8 -*-
"""按文件名在项目内实际存储目录中找回"丢失"的源文件。

背景：documents.file_path 记录的是历史绝对路径 D:\考研资料数据集V1.0\...，
该目录已不存在；但同一批资料在项目内有副本
（backend-main-fastapi/data/storage/documents/...）。
本脚本建立 文件名 → 实际路径 索引，据此回填 file_path。
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import func
from database import SessionLocal, BASE_DIR
from models import Document

STORAGE_ROOTS = [
    os.path.join(BASE_DIR, "data", "storage", "documents"),
    os.path.join(BASE_DIR, "data", "storage"),
    os.path.join(BASE_DIR, "data", "uploads"),
]


def build_index() -> dict:
    """文件名(小写) → [绝对路径]"""
    idx = defaultdict(list)
    for root in STORAGE_ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                idx[f.lower()].append(os.path.join(dirpath, f))
    return idx


def main() -> int:
    idx = build_index()
    print(f"已索引本地文件 {sum(len(v) for v in idx.values())} 个（来自 {len(STORAGE_ROOTS)} 个存储根）")

    db = SessionLocal()
    try:
        docs = db.query(Document).filter(
            (Document.content.is_(None)) | (func.length(func.trim(Document.content)) == 0)
        ).all()
        print(f"待找回的空正文文档 {len(docs)} 篇\n")

        found = miss = 0
        for d in docs:
            name = (d.file_name or "").lower()
            hits = idx.get(name) or []
            if not hits and name.endswith(".pdf"):
                # 有些文件名被去掉了尾部 ".pdf" 后缀重复
                for cand in (name[:-4], name + ".pdf"):
                    hits = idx.get(cand) or []
                    if hits:
                        break
            if hits:
                found += 1
                if found <= 6:
                    print(f"  [找到] {d.file_name[:50]}")
                    print(f"         {hits[0][:105]}")
            else:
                miss += 1
                if miss <= 6:
                    print(f"  [缺失] {d.file_name[:60]}")

        print(f"\n结果：可找回 {found} 篇 / 确实缺失 {miss} 篇")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
