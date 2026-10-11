# -*- coding: utf-8 -*-
"""题目↔知识点关联建链（P0-2，2026-10）。

背景：question_knowledge_links 表长期 0 行，但 quiz_questions.knowledge_point（5924 题）
与 knowledge_points.name 存在大量精确同名（科目一致口径 6288 条 join）。
「按知识点练习」目前只能走章节字符串过滤，知识点树上的题数（kp.question_count）也不准。

做法（确定性，非 LLM）：
1. 主链：q.knowledge_point == kp.name 且 q.subject == kp.subject → role=primary,
   weight=1.0, is_verified=1（同名同科，可信）。
2. 备链：科目不一致但该名字全库唯一 → role=related, weight=0.6, is_verified=0
   （容忍个别科目命名漂移，标记待核）。
3. 幂等：已存在的 (question_id, knowledge_point_id) 跳过；重跑只补增量。
4. 完成后回填 kp.question_count = 实际关联题数，让知识地图题数真实。

用法：
    python scripts/backfill_kp_links.py            # 预览
    python scripts/backfill_kp_links.py --apply    # 写库（先备份）
"""
from __future__ import annotations

import os

import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DATABASE_PATH", "").strip() or os.path.join(
    os.path.dirname(BASE_DIR), "database", "kaoyan.db"
)


def main() -> int:
    apply = "--apply" in sys.argv
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")  # 并发容忍：答案回填进程可能同时在写
    cur = con.cursor()

    # 1) 主链：科目+同名
    primary = cur.execute(
        """
        SELECT q.id, kp.id FROM quiz_questions q
        JOIN knowledge_points kp ON q.knowledge_point = kp.name AND q.subject = kp.subject
        WHERE q.knowledge_point IS NOT NULL AND q.knowledge_point != ''
        """
    ).fetchall()

    # 2) 备链：名字全库唯一但科目不一致（排除已进主链的题）
    primary_qids = {q for q, _ in primary}
    unique_names = cur.execute(
        """
        SELECT name FROM knowledge_points GROUP BY name HAVING COUNT(*) = 1
        """
    ).fetchall()
    unique_set = {n for (n,) in unique_names}
    related = []
    if unique_set:
        rows = cur.execute(
            """
            SELECT q.id, q.knowledge_point, q.subject FROM quiz_questions q
            WHERE q.knowledge_point IS NOT NULL AND q.knowledge_point != ''
            """
        ).fetchall()
        kp_by_name = {n: (kid, subj) for kid, n, subj in cur.execute(
            "SELECT id, name, subject FROM knowledge_points")}
        for qid, kp_name, qsubj in rows:
            if qid in primary_qids or kp_name not in unique_set:
                continue
            kid, ksubj = kp_by_name[kp_name]
            if ksubj != qsubj:
                related.append((qid, kid))

    print(f"数据库: {DB_PATH}")
    print(f"主链(科目+同名, verified): {len(primary)} 条")
    print(f"备链(全库唯一名, 待核):    {len(related)} 条")

    if not apply:
        print("\n[DRY-RUN] 未写库。确认后加 --apply 执行。")
        con.close()
        return 0

    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(bak_dir, f"kaoyan_pre_kplink_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    # 用 sqlite backup API 而非直接拷文件：WAL 模式下未 checkpoint 的提交
    # 只在 -wal 文件里，copy2 会拷出缺数据的库
    with sqlite3.connect(bak) as dest:
        con.backup(dest)
    print(f"已备份 → {bak}")

    existing = {
        (r[0], r[1]) for r in cur.execute(
            "SELECT question_id, knowledge_point_id FROM question_knowledge_links")
    }
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ins_primary = [x for x in primary if (x[0], x[1]) not in existing]
    ins_related = [x for x in related if (x[0], x[1]) not in existing]

    cur.executemany(
        "INSERT INTO question_knowledge_links (question_id, knowledge_point_id, role, weight, is_verified, created_at)"
        " VALUES (?, ?, 'primary', 1.0, 1, ?)", [(q, k, now) for q, k in ins_primary])
    cur.executemany(
        "INSERT INTO question_knowledge_links (question_id, knowledge_point_id, role, weight, is_verified, created_at)"
        " VALUES (?, ?, 'related', 0.6, 0, ?)", [(q, k, now) for q, k in ins_related])

    # 回填知识点真实题数
    cur.execute(
        """
        UPDATE knowledge_points SET question_count = (
            SELECT COUNT(*) FROM question_knowledge_links l
            WHERE l.knowledge_point_id = knowledge_points.id AND l.role = 'primary'
        )
        """
    )
    con.commit()

    total = cur.execute("SELECT COUNT(*) FROM question_knowledge_links").fetchone()[0]
    kps_with_q = cur.execute(
        "SELECT COUNT(*) FROM knowledge_points WHERE question_count > 0").fetchone()[0]
    print(f"新增 primary {len(ins_primary)} + related {len(ins_related)}；"
          f"links 总数 {total}；有题的知识点 {kps_with_q}/651")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
