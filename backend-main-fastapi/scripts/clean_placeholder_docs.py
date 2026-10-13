# -*- coding: utf-8 -*-
"""清理 OCR 通道失效期间入库的「占位错误文本」毒化文档。

背景（2026-10-12 修复）：OCR 依赖缺失（Pillow/six/PyYAML）导致扫描件PDF
渲染全失败，而 `DocumentParser.parse()` / `_ocr_pdf_pages()` 在失败时
**返回**一句方括号错误串（如 `"[扫描版 PDF OCR 失败: No module named'PIL']"`，
恰好 39 字）而非抛异常。旧逻辑只拦`[解析失败`，漏掉 OCR 类，
于是这句错误提示被当成正文入库 —— 表现为「✓ 成功入库 39 字」，
并让知识点抽取 100% 跳过（正文过短）。

本脚本**只删** content 整篇为占位错误串的文档（正则整篇匹配，宁缺勿滥），
不碰任何真实正文。默认 dry-run，加 --apply 才真正删除。

注意：备份使用 SQLite `backup()` API（**禁止 cp .db**，WAL 模式下 cp 会丢未合并数据）。

用法：
    python scripts/clean_placeholder_docs.py# 预演
    python scripts/clean_placeholder_docs.py --apply           # 备份+ 删除
    python scripts/clean_placeholder_docs.py --apply --no-backup
"""
from __future__ import annotations

import argparse
import os

import sqlite3
import sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
BACKUP_PATH = DB_PATH + ".bak_placeholder_cleanup"

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from services.delete_guard import require_physical_delete_enabled  # noqa: E402

#: 判定复用服务端**同一个** `is_placeholder_text`（单一事实来源，避免两处正则漂移）。
#: 该判据已覆盖两种真实故障族：
#:   1. OCR/解析失败串： `[扫描版 PDF OCR 失败: [WinError -536870904] Windows Error 0xe0000008]`
#:   2. 图片无文本占位：   `[image 文件，未能提取到文本内容] 文件名：xxx.jpg`
sys.path.insert(0, BASE_DIR)
from services.smart_ingest import is_placeholder_text  # noqa: E402


def find_poisoned(conn: sqlite3.Connection):
    """找出 content 为占位/错误文本的文档 id（含 OCR 失败串与图片无文本占位）。"""
    rows = conn.execute(
        "SELECT id, file_name, content FROM documents "
        "WHERE content LIKE '%OCR 失败%' OR content LIKE '%解析失败%' "
        "OR content LIKE '%未能提取到文本内容%' OR content LIKE '%WinError%'"
    ).fetchall()
    return [(i, fn, c) for i, fn, c in rows if is_placeholder_text(c or "")]


def classify(text: str) -> str:
    """给占位内容归类，便于报告。"""
    t = text or ""
    if "未能提取到文本内容" in t:
        return "图片无文本占位"
    if "WinError" in t or "OCR 失败" in t or "PIL" in t:
        return "OCR/渲染失败占位"
    return "其他占位"


def backup_database(conn: sqlite3.Connection) -> str:
    """用 SQLite backup() API 做一致性备份（WAL 安全，禁用 cp）。"""
    dest = sqlite3.connect(BACKUP_PATH)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return BACKUP_PATH


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正删除（默认预演）")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份（不推荐）")
    args = ap.parse_args()

    if not os.path.isfile(DB_PATH):
        print(f"数据库不存在: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    try:
        poisoned = find_poisoned(conn)

        print(f"占位毒化文档（可安全删除）: {len(poisoned)} 篇")
        if poisoned:
            from collections import Counter as _C
            print("分类:", dict(_C(classify(c) for _, _, c in poisoned)))
            print("字数分布:", Counter(len(c.strip()) for _, _, c in poisoned).most_common(8))
            for i, fn, c in poisoned[:10]:
                print(f"  #{i:<6} {len(c.strip()):>3}字  {classify(c):<14}  {(fn or '')[:40]}")

        if not args.apply:
            print("\n预演模式，未改动任何数据。加 --apply 执行。")
            return 0

        if not args.no_backup:
            bp = backup_database(conn)
            print(f"\n已备份(WAL 安全)→ {bp}  "
                  f"({os.path.getsize(bp) / 1024 / 1024:.1f} MB)")

        ids = [i for i, _, _ in poisoned]
        conn.execute("BEGIN")
        conn.executemany("DELETE FROM documents WHERE id = ?",
                         [(i,) for i in ids])
        conn.commit()

        #清理孤儿分块
        orphan = conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id NOT IN "
            "(SELECT id FROM documents)").fetchone()[0]
        if orphan:
            # 物理删除闸门：knowledge_chunks 物理删除不可逆。孤儿判定
            # 若因外键/事务问题误判，会连带清空正常分块，必须显式放行。
            require_physical_delete_enabled("knowledge_chunks")
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id NOT IN "
                         "(SELECT id FROM documents)")
            conn.commit()
        print(f"已删除 documents {len(ids)} 篇；顺带清理孤儿分块 {orphan} 条")
        print("剩余 documents:",
              conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())