# -*- coding: utf-8 -*-
"""切题源头三处修复的试切对比脚本（只读，不写库）。

用途：在2-3 本真书上跑修复前/ 修复后的切题结果，给出对比数字。
**绝不写库** —— 只调用 extract_questions 并打印统计。

对比维度（对应三个根因信号）：
  1. 脏答案条数（页眉/页脚/试卷通知被当成答案）
  2. 答案为孤立选项字母 A/B/C/D 的条数（选项切出失败）
  3. 题干尾部串接题型大标题的条数（跨题串接）

用法::

    python scripts/trial_extraction_fix.py            # 跑修复后
    python scripts/trial_extraction_fix.py --before   # 跑修复前（还原旧逻辑）
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import qbank_builder  # noqa: E402

DB = r"D:\平台\database\kaoyan.db"

#: 试切用的真书（覆盖模电、数电、试卷三类）
TRIAL_DOCS = [
    (169, "【电子技术基础】考试卷带解析--- (1).txt"),
    (413, "贵州大学2023年真题及答案23 (1).txt"),
    (416, "贵州大学电子技术基础真题16-21.txt"),
]

_OPTION_ONLY_RE = re.compile(r"^\s*[A-F]\s*$")
_CROSS_TAIL_RE = re.compile(
    r"[一二三四五六七八九十]+\s*[、.．]\s*"
    r"(?:选择题|填空题|判断题|简答题|计算题|分析题|设计题|简答|选择|填空|判断)"
    r"\s*(?:[（(][^）)]{0,40}[）)])?\s*$"
)


def _dirty_answer(q: dict) -> bool:
    """答案是否为页眉/页脚/试卷通知噪声。"""
    from services.extraction_noise import is_running_header_noise

    ans = (q.get("answer") or "").strip()
    return bool(ans) and is_running_header_noise(ans)


def _option_only(q: dict) -> bool:
    """答案是否只是一个孤立选项字母。"""
    return bool(_OPTION_ONLY_RE.match((q.get("answer") or "").strip()))


def _cross_leak(q: dict) -> bool:
    """题干是否尾部串接了题型大标题。"""
    lines = [ln for ln in (q.get("content") or "").splitlines() if ln.strip()]
    return bool(lines) and bool(_CROSS_TAIL_RE.match(lines[-1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", action="store_true", help="跑修复前逻辑")
    args = ap.parse_args()

    from services import extraction_noise as en

    if args.before:
        # 还原为修复前的旧行为，便于对比
        en.clean_answer = lambda a: a
        en.clean_content = lambda c: c
        en.split_stem_and_options = lambda body, sec_type=None, **kw: (
            re.sub(r"\s+", " ", body).strip(),
            [],
        )
        en.strip_cross_question_leak = lambda t: ((t or "").strip(), False)
        import services.qbank_builder as qb

        qb._clean_answer = en.clean_answer
        qb._clean_content = en.clean_content
        qb._split_stem_options = en.split_stem_and_options
        qb._strip_cross_leak = en.strip_cross_question_leak

    db = sqlite3.connect(DB)
    total = dirty = optonly = cross = 0
    for did, name in TRIAL_DOCS:
        row = db.execute(
            "SELECT content, subject FROM documents WHERE id=?", (did,)
        ).fetchone()
        if not row or not row[0]:
            print(f"[skip] doc {did} 无内容")
            continue
        text, subject = row[0], row[1]
        qs = qbank_builder.extract_questions(text, source_hint=name)
        d = sum(1 for q in qs if _dirty_answer(q))
        o = sum(1 for q in qs if _option_only(q))
        c = sum(1 for q in qs if _cross_leak(q))
        total += len(qs)
        dirty += d
        optonly += o
        cross += c
        print(
            f"[doc {did}] {name[:34]:34s} 切出 {len(qs):4d} 条 | "
            f"脏答案 {d:3d} | 仅字母答案 {o:3d} | 串接 {c:3d}"
        )
    db.close()

    tag = "修复前" if args.before else "修复后"
    print(f"\n[{tag}] 合计切出 {total} 条")
    print(f"[{tag}] 脏答案（页眉/通知）      = {dirty}")
    print(f"[{tag}] 答案仅为孤立字母 A-F    = {optonly}")
    print(f"[{tag}] 题干尾部串接题型大标题= {cross}")
    return 0


if __name__ == "__main__":
    sys.exit(main())