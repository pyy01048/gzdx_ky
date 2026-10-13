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
# 水印片段规则（按「强特征」排序，长特征在前，避免被短特征吃掉）
# 全部来自实测抽样，覆盖公众号/微信/QQ/店铺/文库站名/引流话术。
# --------------------------------------------------------------------------- #
_SPAN_PATTERNS: tuple[str, ...] = (
    # —— 品牌/公众号家族（实测残留逐一收编）——
    r"东坡哥微信\s*[:：]?\s*haidongpo\d*",
    r"haidongpo\d*",
    r"公众号【[^】]*】[^\n]{0,40}",
    r"研池大叔",
    r"蜂考[《》】\w]{0,10}[^\n]{0,24}",
    r"水木观畴",
    r"笃学考研",
    r"考研班主任",
    r"各大高校真题资料",
    r"获取联系方式",
    r"视频课程加",
    r"全套视频和资料|独家视频讲解",
    r"观畴考研[，,、]?\s*你身边的考研专家",
    r"模电考研全套视频和资料",
    r"电子与通信工程考研",
    r"关注微信公众号\s*[:：]?\s*[\w\u4e00-\u9fff]{0,20}[”\"']?",
    r"微信公众号\s*[:：]?\s*[\w\u4e00-\u9fff]{0,20}",
    r"公众号\s*[:：]\s*[\w\u4e00-\u9fff]{0,20}",
    r"微信号\s*[:：]?\s*[\w]{0,20}",
    r"微信扫一扫",
    r"微信\s*[:：]\s*[\w]{0,20}",
    r"加微信\s*[:：]?\s*[\w]{0,20}",
    # —— QQ / 群引流（支持小写、QQ群、可选冒号）——
    r"(?i)qq\s*群?\s*[:：]?\s*\d{5,12}",
    r"(?i)(?:加|联系|关注)\s*(?:qq|微信)\s*群?",
    r"Q{4,}",
    r"扫描?二维码",
    r"扫码(获取|关注|进群)?",
    r"淘宝[^\s]{0,6}(店铺|店|代购|打印)",
    r"光速考研工作室",
    r"更多考研资料",
    r"(道客巴巴|百度文库|豆丁|原创力|小木虫)",
    r"关注【[^】]*】",
    r"免费(?:分享|提供|获取)[^\n]{0,16}",
    # 版权声明水印（收窄：只删「侵权必究/侵权删除」这类声明词，不删裸「侵权」——
    # 政治/法律题里会出现「侵权责任」等正常内容，裸词会误伤）
    r"资料仅供学习交流|仅供学习交流|请勿转载|侵权必究|侵权删除",
)
_SPAN_RES = tuple(re.compile(p) for p in _SPAN_PATTERNS)

#: 快速预筛标记：行内不含任一标记就直接跳过全部正则（实测此举把 132M 字符的
#: 全量扫描从十几分钟降到一个量级以内；标记集合刻意放宽，只求不漏）。
_FAST_MARKERS: tuple[str, ...] = (
    "微信", "公众号", "haidongpo", "QQ", "qq", "Q群", "淘宝", "扫码", "二维码",
    "MOOC", "慕课", "研池", "蜂考", "观畴", "笃学", "考研班主任", "侵权", "转载",
    "http", "www.", "资料", "加群", "联系",
)

#: 独立 URL —— 考研资料正文里的裸链接几乎全是水印/引流；
#: 但只在「该行实义汉字很少」时才整行丢弃，避免误删正文里的正常链接。
_URL_RE = re.compile(r"(?:https?://|www\.)\S{6,}")

#: 整行丢弃阈值：抹掉水印后，实义字符（中英文数字）少于该值即视为纯水印行。
_MIN_MEANINGFUL = 4

_RE_MEANINGFUL = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


def _meaningful_count(s: str) -> int:
    return len(_RE_MEANINGFUL.findall(s))


def clean_line(line: str) -> tuple[str | None, bool]:
    """清洗单行。

    Returns:
        (新行 or None 表示整行丢弃, 是否发生过水印移除)
    """
    raw = line
    # 快速预筛：不含任何水印标记的行直接跳过全部正则（大幅加速）
    if not any(m in line for m in _FAST_MARKERS):
        return line, False
    t = line
    touched = False
    for rx in _SPAN_RES:
        new = rx.sub(" ", t)
        if new != t:
            touched = True
            t = new
    # URL 单独处理：只有当整行去掉水印与 URL 后几乎没有正文时才丢弃
    if _URL_RE.search(t):
        stripped = _URL_RE.sub(" ", t)
        if _meaningful_count(stripped) < _MIN_MEANINGFUL:
            touched = True
            t = stripped
            # 走到这里 remainder 已很短 → 下面会整行丢弃
        else:
            # 正文里夹链接：保留，仅去首尾多余空白（不删链接，避免误伤）
            pass
    t = re.sub(r"[ \t]{2,}", " ", t).strip()

    if not touched:
        return line, False

    if _meaningful_count(t) < _MIN_MEANINGFUL:
        return None, True
    return t, True


def clean_text(text: str | None) -> tuple[str, int, int]:
    """清洗整段文本。

    只在**确实移除过水印**时才改动文本；未命中水印的行按原样保留，
    避免把「仅换行/空白归一」误算成命中（也避免 \x0b 等控制符被当换行重组）。

    Returns:
        (清洗后文本, 被丢弃的纯水印行数, 被移除水印片段的混合行数)
    """
    if not text:
        return text or "", 0, 0
    kept: list[str] = []
    dropped = 0
    mixed = 0
    # 只用 "\n" 切分（不能用 splitlines()——它会把 \x0b/\x0c 等当换行，污染判定）
    for line in text.split("\n"):
        if not line.strip():
            kept.append(line)
            continue
        new, touched = clean_line(line)
        if new is None:
            dropped += 1
            continue
        if touched:
            mixed += 1
        kept.append(new)
    if dropped == 0 and mixed == 0:
        return text, 0, 0
    out = "\n".join(kept)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, dropped, mixed


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
