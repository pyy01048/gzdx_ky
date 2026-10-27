# -*- coding: utf-8 -*-
"""清理早期 AI 生成的垃圾答案（T6 附带发现，2026-10）。

背景：早期（id < ~500）一批 ai_generated=1 的答案是把 OCR 噪声存成了
answer（如「及总结」「必须写在答题纸上否则后果自负！」），A6 交叉校验
已证实与新独立作答完全冲突。这批答案参与判分会冤枉用户。

规则（保守三选一）：
1. 该题在 answer_candidates 有 used_for_grading=1 且 confidence≥0.7 的
   extracted/llm 候选 → 用候选答案替换（标 verified=0 保持待核）。
2. 无可用候选 → answer/analysis 置空（宁可没答案，不要错答案）。
3. 仅处理「垃圾特征」命中的答案（OCR 噪声/超短/警告语），正常 AI 答案不动。

幂等；--apply 前自动备份。
"""
from __future__ import annotations

import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# 路径按本文件位置推导（P0-B2：拆除机器专属绝对路径绑定）
_REPO = Path(__file__).resolve().parents[2]
DB_PATH = _REPO / "database" / "kaoyan.db"

# 垃圾答案特征：OCR 页眉页脚/警告语/无意义超短串
_GARBAGE_PATTERNS = [
    r"^及总结", r"答题纸上否则后果自负", r"^必须写", r"^\s*$",
    r"^\W{1,4}$",                      # 纯符号
    r"^(?:第?\s*[一二三四五六七八九十\d]+\s*[页题部分]|共\s*\d+\s*页)",
    r"公众号|QQ|微信|扫码|下载|百度网盘",  # 广告水印
]
_GARBAGE_RE = re.compile("|".join(_GARBAGE_PATTERNS))


def is_garbage(answer: str) -> bool:
    a = (answer or "").strip()
    if not a:
        return False  # 空不算垃圾（本来就空）
    if len(a) <= 4 and not re.search(r"[A-D\d]", a):
        return True   # 超短且不含选项字母/数字
    return bool(_GARBAGE_RE.search(a))


def main() -> int:
    apply = "--apply" in sys.argv
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    rows = cur.execute(
        "SELECT id, answer FROM quiz_questions WHERE ai_generated = 1 AND verified = 0"
        " AND answer IS NOT NULL AND answer != ''"
    ).fetchall()
    garbage = [(qid, ans) for qid, ans in rows if is_garbage(ans)]
    print(f"AI未核验答案: {len(rows)} 道，其中垃圾特征命中: {len(garbage)} 道")

    replace_plan, clear_plan = [], []
    for qid, ans in garbage:
        cand = cur.execute(
            "SELECT answer FROM answer_candidates"
            " WHERE question_id = ? AND used_for_grading = 1 AND confidence >= 0.7"
            " AND source IN ('extracted','llm') ORDER BY confidence DESC LIMIT 1",
            (qid,),
        ).fetchone()
        if cand and (cand[0] or "").strip():
            replace_plan.append((cand[0].strip(), qid))
        else:
            clear_plan.append(qid)

    print(f"处理计划: {len(replace_plan)} 道用候选替换, {len(clear_plan)} 道置空")
    for a, qid in replace_plan[:8]:
        print(f"  替换 q{qid}: → {a[:40]!r}")
    for qid in clear_plan[:5]:
        print(f"  置空 q{qid}")

    if not apply:
        print("\n[DRY-RUN] 未写库。确认后加 --apply 执行。")
        con.close()
        return 0

    bak = DB_PATH.parent / f"kaoyan_pre_cleanai_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    with sqlite3.connect(str(bak)) as dest:
        con.backup(dest)
    print(f"已备份 → {bak}")

    cur.executemany(
        "UPDATE quiz_questions SET answer = ?, analysis = COALESCE(NULLIF(analysis,''), NULL) WHERE id = ?",
        replace_plan,
    )
    cur.executemany(
        "UPDATE quiz_questions SET answer = NULL, analysis = NULL WHERE id = ?",
        [(q,) for q in clear_plan],
    )
    con.commit()
    left = cur.execute(
        "SELECT COUNT(*) FROM quiz_questions WHERE ai_generated = 1 AND verified = 0"
        " AND answer IS NOT NULL AND answer != ''"
    ).fetchone()[0]
    print(f"完成。剩余 AI 未核验答案 {left} 道（正常待校验）。")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
