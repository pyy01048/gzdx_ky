"""知识库文档正文质量清洗（提高"识别度"的可读性）。

针对审计发现的系统性噪声：
  1. 图片引用残留 `![alt](path)` —— IMA 抓取内容与部分解析产物里成片存在
  2. 控制字符 / 零宽字符残留
  3. 连续空行、行尾空白
  4. 纯噪声行（如 `![未能识别到文本内容](...)`）

保守原则：**只做可逆的格式清洗，不改写语义内容**；不臆造、不翻译、不纠错正文。
真正需要重做的是"解析失败/扫描件"，那部分由入库管线负责。

用法：
    python scripts/clean_document_text.py            # dry-run
    python scripts/clean_document_text.py --apply
    python scripts/clean_document_text.py --apply --retry-empty   # 顺带尝试重解析近空文档
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

# ![alt](path) —— 保留 alt 文本（可能是有用标签，如 CLK / Q1），丢弃路径
_IMG_REF = re.compile(r"!\[([^\]]{0,80})\]\([^)]*\)")
# 零宽与 BOM
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
# 控制字符（保留 \n \t \r）
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 3+ 连续空行
_MULTI_NL = re.compile(r"\n{3,}")
# 行尾空白
_TRAIL_WS = re.compile(r"[ \t]+\n")
# 纯噪声行
_NOISE_LINE = re.compile(r"^\s*!\[\s*(未能识别到文本内容|图片|image)\s*\]\s*$", re.I)


def clean(text: str) -> str:
    if not text:
        return text
    s = text
    s = _ZERO_WIDTH.sub("", s)
    s = _CTRL.sub("", s)

    def _img(m: re.Match) -> str:
        alt = (m.group(1) or "").strip()
        if not alt or re.fullmatch(r"(未能识别到文本内容|图片|image|img)", alt, re.I):
            return ""
        # alt 是短标签（信号名/公式片段）才保留，避免把长描述当正文
        return alt if len(alt) <= 40 else ""

    s = _IMG_REF.sub(_img, s)
    s = "\n".join(l for l in s.split("\n") if not _NOISE_LINE.match(l))
    s = _TRAIL_WS.sub("\n", s)
    s = _MULTI_NL.sub("\n\n", s)
    return s.strip()


def backup(con: sqlite3.Connection) -> str:
    d = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"kaoyan_pre_doctextclean_{datetime.now():%Y%m%d_%H%M%S}.db")
    with sqlite3.connect(p) as dest:
        con.backup(dest)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")

    rows = con.execute("SELECT id, file_name, content FROM documents").fetchall()
    changes = []
    for did, fn, c in rows:
        if not c:
            continue
        new = clean(c)
        if new != c:
            changes.append((did, fn, len(c), len(new), new))

    print(f"文档 {len(rows)}，需清洗 {len(changes)} 篇")
    delta = sum(o - n for _, _, o, n, _ in changes)
    print(f"预计删除噪声字符 {delta}")
    for did, fn, o, n, _ in changes[:10]:
        print(f"  #{did} {str(fn)[:38]} {o} → {n}")

    if args.apply and changes:
        bak = backup(con)
        print(f"\n备份 → {bak}")
        con.execute("BEGIN")
        for did, _, _, _, new in changes:
            con.execute("UPDATE documents SET content=? WHERE id=?", (new, did))
        con.commit()
        print(f"已清洗 {len(changes)} 篇")

    print("\n=== 复核 ===")
    left_img = con.execute(
        "SELECT count(*) FROM documents WHERE content LIKE '%![%](%'").fetchone()[0]
    left_fffd = con.execute(
        "SELECT count(*) FROM documents WHERE content LIKE '%\ufffd%'").fetchone()[0]
    empty = con.execute(
        "SELECT count(*) FROM documents WHERE content IS NULL OR length(content)<50"
    ).fetchone()[0]
    print(f"  残留图片引用: {left_img}")
    print(f"  含替换符: {left_fffd}")
    print(f"  近空文档: {empty}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
