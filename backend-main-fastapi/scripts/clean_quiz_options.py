# -*- coding: utf-8 -*-
"""题库选项清洗落库：把历史脏 options 归一为规范 {key,text} 数组。

背景（2026-10 体检实测 9096 题）
--------------------------------
用户反馈"题目有两三个 abcd 选项""识别是空题"，实测确认：
    · 8099 题 options 存的是字符串 ``"null"``   ← 脏表示法，该存 SQL NULL
    · 158 题 单选却只有 1-3 个选项（正常应 4 个）
    · 存在 42/21/16 项等极端脏数据（整页被当成选项）
    · 真正损坏：空题干 19 题、乱码 24 题

清洗口径（复用 pipeline.question_schema.normalize_options，不另造轮子）：
    · 在被打散的标签序列里找回最长 A→B→C→… 连续递增段
    · 剔除空壳项、乱码项、粘连的下一题型标题
    · 主观题（calc/essay/fill/draw）本就无选项 → 归一为 SQL NULL

安全红线：
  1. 只改 options 一列，不碰 content / answer / analysis。
  2. 默认 dry-run；``--apply`` 前用 SQLite backup() 备份（WAL 模式禁 cp）。
  3. 清洗后选项数 < 2 的客观题，同步把 question_type 降级依据留给人工，
     此处只记录到报告，不擅自改题型。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.question_schema import normalize_options  # noqa: E402

DB_DEFAULT = r"D:\平台\database\kaoyan.db"
#: 主观题本就不该有选项，归一为 SQL NULL
SUBJECTIVE_TYPES = {"calc", "essay", "fill", "draw", "proof"}


def backup_db(db_path: str) -> str:
    target = f"{db_path}.bak-optclean-{time.strftime('%Y%m%d-%H%M%S')}"
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description="题库选项清洗")
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, options, question_type FROM quiz_questions"
        ).fetchall()

        changes, anomalies = [], []
        for r in rows:
            raw = r["options"]
            qtype = (r["question_type"] or "").strip()
            opts, diag = normalize_options(raw)

            # 目标值：主观题 → NULL；客观题 → 规范数组（无有效项则 NULL）
            if qtype in SUBJECTIVE_TYPES:
                target = None
            else:
                target = opts if len(opts) >= 2 else None

            new_val = json.dumps(target, ensure_ascii=False) if target else None
            # 关键：不能把字面量 "null" 当作"已经是 NULL"而跳过。
            # 历史库把「无选项」存成四字符串 "null"（既非 SQL NULL 也非空串），
            # 只有真正 (raw is None) 才算无需改写；"null" 必须被写回成 SQL NULL。
            old_val = None if raw is None else raw
            if (old_val or None) != (new_val or None):
                # old_count：解析前的项数（"null" 视为 0 项）
                old_count = 0 if (raw is None or str(raw).strip().lower() in ("", "null")) \
                    else diag.get("before", 0)
                changes.append({
                    "id": r["id"], "question_type": qtype,
                    "old_count": old_count,
                    "new_count": len(target) if target else 0,
                })

            # 异常留证：客观题清洗后仍无选项
            if qtype in {"single", "multiple", "judge"} and not target:
                anomalies.append({"id": r["id"], "question_type": qtype,
                                  "reason": "客观题无可提取选项"})

        print("=" * 60)
        print("题库选项清洗计划")
        print("=" * 60)
        print(f"  题目总数        {len(rows)}")
        print(f"  需改写          {len(changes)}")
        print(f"  客观题缺选项    {len(anomalies)}")

        if changes:
            from collections import Counter
            dist = Counter(f"{c['old_count']}→{c['new_count']}" for c in changes)
            print("\n  改写分布（旧→新项数）：")
            for k, v in dist.most_common(10):
                print(f"    {k:<10} {v}")

        if args.report:
            Path(args.report).write_text(
                json.dumps({"changes": changes, "anomalies": anomalies},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n  报告：{args.report}")

        if not args.apply:
            print("\n[预览模式] 未改动数据库。")
            return 0

        backup = backup_db(args.db)
        print(f"\n已备份���{backup}")

        done = 0
        for c in changes:
            r = conn.execute("SELECT options, question_type FROM quiz_questions WHERE id=?",
                             (c["id"],)).fetchone()
            opts, _ = normalize_options(r["options"])
            target = None if (r["question_type"] or "") in SUBJECTIVE_TYPES else (
                opts if len(opts) >= 2 else None)
            # 明确写 SQL NULL（不是字符串 'null'）
            if target is None:
                conn.execute("UPDATE quiz_questions SET options=NULL WHERE id=?", (c["id"],))
            else:
                conn.execute("UPDATE quiz_questions SET options=? WHERE id=?",
                             (json.dumps(target, ensure_ascii=False), c["id"]))
            done += 1
        conn.commit()
        print(f"已改写 {done} 题")

        # 复核：>6 项的脏数据应为 0
        dirty = conn.execute(
            "SELECT COUNT(*) FROM quiz_questions "
            "WHERE options IS NOT NULL AND options <> 'null' "
            "AND json_valid(options) AND json_array_length(options) > 6"
        ).fetchone()[0]
        nullstr = conn.execute(
            "SELECT COUNT(*) FROM quiz_questions WHERE options = 'null'"
        ).fetchone()[0]
        print(f"复核：超 6 项脏数据 {dirty} 条（清洗前 33）；字符串 null {nullstr} 条（清洗前 8099）")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
