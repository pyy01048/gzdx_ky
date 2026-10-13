# -*- coding: utf-8 -*-
"""知识库文档正文「行内水印」清洗（documents.content + knowledge_chunks.text）。

背景
----
`clean_junk_chunks.py` 只处理**尾部**纯水印（截尾），对**行内水印**无能为力；
而 `_probe_watermark_options.py`（只读探针）实测水印仍广泛残留：

    documents.content     561 / 2553 篇（22.0%）含水印行
    knowledge_chunks.text 7469 / 61091 块（12.23%）含水印行

典型形态（实测抽样）：:

    documents.content（多为纯水印整行）
        东坡哥微信:haidongpo3
        微信公众号:电子与通信工程考研

    knowledge_chunks.text（整行重复 / 前缀拼在真题正文上）
        观畴考研，你身边的考研专家东坡哥微信:haidongpo3QQ:3428047568
            微信公众号:电子与通信工程考研水木观畴月考-数字电路2023 年5 月满分：150
        关注微信公众号:电子与通信工程考研”关注微信公众号:…

策略（**宁可漏删，不可误杀正文**）
--------------------------------
1. 逐行处理：先抹掉水印片段；
   - 抹掉后**实义字符 < 4 个** → 判定为纯水印行，整行丢弃；
   - 否则只删片段、保留正文（行内水印清理）。
2. 空块处理：清洗后变空的 chunk，连 `_vec/_fts/error_knowledge_links` 一并删除
   （与 `clean_junk_chunks.py` 同一依赖清理口径，且走物理删除闸门）。
3. `--apply` 前强制用 SQLite `backup()` API 备份（禁 cp/copy2）。
4. 同步 `knowledge_chunks_fts.content`，保证检索侧立即干净。

用法
----
    python scripts/clean_document_watermarks.py                 # dry-run（默认）
    python scripts/clean_document_watermarks.py --show-samples 20
    python scripts/clean_document_watermarks.py --apply         # 真清洗（自动先备份）
    python scripts/clean_document_watermarks.py --selftest      # 只跑判据自检
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
DEP_TABLES = ("knowledge_chunks_vec", "knowledge_chunks_fts", "error_knowledge_links")

# --------------------------------------------------------------------------- #
# 水印清洗规则：**唯一落点**已抽到 services/extraction_noise.py，本脚本只做
# 批量刷库（扫描 → 备份 → 写库 → 同步 FTS）。导入时预清洗与存量清洗因此共用
# 同一份规则，避免两套规则各自演化、清过的又被重新导入弄脏。
# 下面用 `as` 别名保留本脚本既有内部名（clean_line/clean_text 等），
# 使自带 selftest 与主流程零改动。
# --------------------------------------------------------------------------- #
from services.extraction_noise import (  # noqa: E402
    DOC_WATERMARK_FAST_MARKERS as _FAST_MARKERS,
    DOC_WATERMARK_SPAN_PATTERNS as _SPAN_PATTERNS,
    DOC_URL_RE as _URL_RE,
    MIN_MEANINGFUL_CHARS as _MIN_MEANINGFUL,
    clean_document_line as clean_line,
    clean_document_text as clean_text,
    meaningful_count as _meaningful_count,
)
def backup_db(src_path: str, dst_path: str) -> str:
    """SQLite 官方 backup() API —— 唯一正确的备份方式（copy2/cp 会丢 WAL 数据）。"""
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dst_path


def _scan(conn: sqlite3.Connection) -> tuple[list, list, dict[str, int]]:
    """扫描 documents 与 knowledge_chunks，返回待改清单与统计。"""
    doc_changes: list[tuple[int, str, int, int]] = []   # (id, new_content, dropped, mixed)
    chunk_changes: list[tuple[int, str, int, int]] = []  # (id, new_text, dropped, mixed)
    stat = {"doc_scanned": 0, "doc_hit": 0, "doc_dropped_lines": 0, "doc_mixed_lines": 0,
            "chunk_scanned": 0, "chunk_hit": 0, "chunk_dropped_lines": 0, "chunk_mixed_lines": 0}

    for did, content in conn.execute(
        "SELECT id, content FROM documents WHERE content IS NOT NULL AND content <> ''"
    ):
        stat["doc_scanned"] += 1
        new, dropped, mixed = clean_text(content)
        if new != content:
            doc_changes.append((did, new, dropped, mixed))
            stat["doc_hit"] += 1
            stat["doc_dropped_lines"] += dropped
            stat["doc_mixed_lines"] += mixed

    for cid, txt in conn.execute(
        "SELECT id, text FROM knowledge_chunks WHERE text IS NOT NULL AND text <> ''"
    ):
        stat["chunk_scanned"] += 1
        new, dropped, mixed = clean_text(txt)
        if new != txt:
            chunk_changes.append((cid, new, dropped, mixed))
            stat["chunk_hit"] += 1
            stat["chunk_dropped_lines"] += dropped
            stat["chunk_mixed_lines"] += mixed

    return doc_changes, chunk_changes, stat


def _sample_report(conn: sqlite3.Connection, doc_changes, chunk_changes, n: int) -> None:
    print(f"  待改样例（前 {n} 条）：")
    print("   · documents.content")
    for did, new, dr, mx in doc_changes[:n]:
        old = conn.execute("SELECT content FROM documents WHERE id=?", (did,)).fetchone()[0]
        print(f"     #{did} 丢{dr}行/删{mx}行  旧 {old[:46]!r}")
        print(f"                    新 {new[:46]!r}")
    print("   · knowledge_chunks.text")
    for cid, new, dr, mx in chunk_changes[:n]:
        old = conn.execute("SELECT text FROM knowledge_chunks WHERE id=?", (cid,)).fetchone()[0]
        print(f"     #{cid} 丢{dr}行/删{mx}行  旧 {old[:46]!r}")
        print(f"                    新 {new[:46]!r}")


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    def one(sql: str) -> int:
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.Error:
            return -1

    return {
        "documents": one("SELECT COUNT(*) FROM documents"),
        "knowledge_chunks": one("SELECT COUNT(*) FROM knowledge_chunks"),
        "doc_wm": one("SELECT COUNT(*) FROM documents WHERE content LIKE '%微信公众号%' "
                      "OR content LIKE '%haidongpo%' OR content LIKE '%QQ:%' OR content LIKE '%QQ：%'"),
        "chunk_wm": one("SELECT COUNT(*) FROM knowledge_chunks WHERE text LIKE '%微信公众号%' "
                        "OR text LIKE '%haidongpo%' OR text LIKE '%微信:%' OR text LIKE '%QQ%'"),
    }


def selftest() -> int:
    cases: list[tuple[str, str, str]] = [
        ("纯水印行", "东坡哥微信:haidongpo3", "drop"),
        ("纯公众号行", "微信公众号:电子与通信工程考研", "drop"),
        ("重复水印行", "微信公众号：电子与通信工程考信公众号：电子与通信工程考研", "drop"),
        ("关注水印行", "关注微信公众号:电子与通信工程考研”", "drop"),
        ("前缀水印+正文", "观畴考研，你身边的考研专家东坡哥微信:haidongpo3QQ:3428047568微信公众号:电子与通信工程考研水木观畴月考-数字电路2023年5月满分：150", "keep"),
        ("公众号研池大叔", "公众号【研池大叔】，免费分享考研干货！", "drop"),
        ("蜂考QQ群", "蜂考《数电》系统课 QQ群:713044392", "drop"),
        ("笃学考研小写qq", "笃学考研，各大高校真题资料，视频课程加QQ获取联系方式qq95022861", "drop"),
        ("重复Q串", "QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ", "drop"),
        ("正常题目（无水印）", "8位DAC转换器，设转换系数k=0.05，数字01000001转换后的电压值为（ ）V。A.0.05 B.0.10", "keep"),
        ("正常正文提到微信", "本题考察三极管放大电路的静态工作点计算方法，属于共射极放大电路分析。", "keep"),
    ]
    print("=" * 64)
    print("SELFTEST：行内水印清洗判据（防误杀优先）")
    print("=" * 64)
    failed = 0
    for desc, text, expect in cases:
        new, dropped, mixed = clean_text(text)
        got = "drop" if (not new or _meaningful_count(new) < _MIN_MEANINGFUL) else "keep"
        # 关键底线：正常题目绝不能被删空
        ok = got == expect
        mark = "✓" if ok else "✗ FAIL"
        print(f"  [{mark}] {desc}  期望={expect} 实际={got}")
        print(f"         → {new[:60]!r}  (丢{dropped}/删{mixed})")
        if not ok:
            failed += 1
    print(f"\n  通过 {len(cases) - failed}/{len(cases)}  →  "
          + ("PASS" if failed == 0 else f"FAIL ({failed})"))
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="知识库文档行内水印清洗（dry-run 默认）")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--apply", action="store_true", help="真正写库（自动先备份）")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--show-samples", type=int, default=6)
    ap.add_argument("--backup", default=None)
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not os.path.isfile(args.db):
        print(f"数据库不存在: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    try:
        before = stats(conn)
        doc_changes, chunk_changes, st = _scan(conn)

        print("=" * 74)
        print("文档行内水印清洗" + ("（DRY-RUN，不写库）" if not args.apply else "（APPLY）"))
        print("=" * 74)
        print(f"  扫描：documents {st['doc_scanned']} 篇 → 命中 {st['doc_hit']} 篇"
              f"（丢行 {st['doc_dropped_lines']} / 删片段行 {st['doc_mixed_lines']}）")
        print(f"        knowledge_chunks {st['chunk_scanned']} 块 → 命中 {st['chunk_hit']} 块"
              f"（丢行 {st['chunk_dropped_lines']} / 删片段行 {st['chunk_mixed_lines']}）")
        empty_chunks = [c for c in chunk_changes if not c[1].strip()]
        print(f"        清洗后变空的 chunk = {len(empty_chunks)}（将连同 vec/fts 一并删除）")
        print()
        _sample_report(conn, doc_changes, chunk_changes, args.show_samples)
        print()

        if not args.apply:
            print(">>> DRY-RUN 结束，未做任何改动。确认无误后加 --apply 执行（自动先备份）。")
            return 0

        if not doc_changes and not chunk_changes:
            print(">>> 无需清洗。")
            return 0

        bk = args.backup or (args.db + ".watermark.bak")
        print(f">>> 备份中（SQLite backup() API）→ {bk}")
        backup_db(args.db, bk)
        print(f">>> 备份完成（{os.path.getsize(bk) / 1e6:.1f} MB）")

        # 1) documents.content
        doc_done = 0
        for did, new, _dr, _mx in doc_changes:
            doc_done += conn.execute(
                "UPDATE documents SET content=? WHERE id=?", (new, did)
            ).rowcount
        # 2) knowledge_chunks.text（同步 FTS）
        chunk_done = 0
        for cid, new, _dr, _mx in chunk_changes:
            r = conn.execute("UPDATE knowledge_chunks SET text=? WHERE id=?", (new, cid))
            if r.rowcount:
                chunk_done += 1
                try:
                    conn.execute(
                        "UPDATE knowledge_chunks_fts SET content=? WHERE chunk_id=?",
                        (new if new.strip() else " ", cid),
                    )
                except sqlite3.Error:
                    pass
        # 3) 清洗后变空的块 → 连同依赖表删除
        dep_done: dict[str, Any] = {}
        if empty_chunks:
            ids = [c[0] for c in empty_chunks]
            ph = ",".join("?" * len(ids))
            for t in DEP_TABLES:
                try:
                    dep_done[t] = conn.execute(
                        f"DELETE FROM {t} WHERE chunk_id IN ({ph})", ids
                    ).rowcount
                except sqlite3.Error as e:
                    dep_done[t] = f"SKIP({e})"
            deleted = conn.execute(
                f"DELETE FROM knowledge_chunks WHERE id IN ({ph})", ids
            ).rowcount
        else:
            deleted = 0
        conn.commit()

        after = stats(conn)
        print(f">>> 已清洗 documents.content {doc_done} 篇")
        print(f">>> 已清洗 knowledge_chunks.text {chunk_done} 块")
        print(f">>> 已删除清空块 {deleted} 行")
        for t, v in dep_done.items():
            print(f"    {t:<24} {v}")
        print("\n  清洗前后对比：")
        for k in before:
            b, a = before[k], after[k]
            flag = " ✓" if a < b else ("" if a == b else " ✗")
            print(f"    {k:<20} {b:>7} → {a:>7}{flag}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
