"""answer_candidates 去重（解阻塞 uq_ansc_qid_src 唯一索引）。

## 为什么需要

``confidence_service.ensure_conflict_schema`` 要建：
    CREATE UNIQUE INDEX uq_ansc_qid_src ON answer_candidates(question_id, source)

``answer_candidates`` 的 upsert 全靠它：
    INSERT ... ON CONFLICT(question_id, source) DO UPDATE ...

但库里已有重复的 (question_id, source)（本次实测 10 组 / 12 行冗余），
索引建不出来 —— 而这条失败原先被裸 ``except: pass`` 吞掉，直到
/api/conflicts/*/resolve 报 ``column "provenance" does not exist`` 才间接暴露。

更糟的是：**没有唯一约束时 ``ON CONFLICT`` 本身就会报错**
（"there is no unique or exclusion constraint matching the ON CONFLICT
specification"），所以这不是"可选优化"而是功能阻塞。

## 保留策略（保守优先，宁可留旧的也不丢"已用于判分"的）

按优先级从高到低挑一条保留，其余删除：
  1. ``used_for_grading = TRUE`` 优先 —— 已参与判分的候选被删会导致
     成绩重算口径漂移，绝不能丢；
  2. confidence 高者优先 —— 更可信的答案更值得留；
  3. id 大者优先 —— 后写入的通常带更新的 explanation / provenance。

## 用法

    python scripts/dedupe_answer_candidates.py            # dry-run，只报告
    python scripts/dedupe_answer_candidates.py --apply    # 实际删除
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402

# 排名：rn=1 即要保留的那条
_RANK_SQL = """
SELECT id, question_id, source, answer, confidence, used_for_grading,
       ROW_NUMBER() OVER (
           PARTITION BY question_id, source
           ORDER BY used_for_grading DESC NULLS LAST,
                    confidence DESC NULLS LAST,
                    id DESC
       ) AS rn
FROM answer_candidates
"""


def _dup_rows(db):
    return db.execute(text(f"""
        SELECT * FROM ({_RANK_SQL}) t WHERE t.rn > 1 ORDER BY question_id, source
    """)).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description="answer_candidates 去重")
    ap.add_argument("--apply", action="store_true", help="实际删除（默认 dry-run）")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        total = db.execute(text("SELECT count(*) FROM answer_candidates")).scalar() or 0
        dups = _dup_rows(db)

        if not dups:
            print(f"answer_candidates 共 {total} 行，无重复 —— 无需处理。")
        else:
            print(f"answer_candidates 共 {total} 行，待删除冗余 {len(dups)} 行：")
            print(f"{'id':>8} {'qid':>8} {'source':<16} {'conf':>6} {'graded':>7}  answer")
            for r in dups:
                print(f"{r[0]:>8} {r[1]:>8} {str(r[2])[:16]:<16} "
                      f"{r[4] if r[4] is not None else '-':>6} "
                      f"{str(r[5]):>7}  {str(r[3])[:40]}")

        if not args.apply:
            print("\n[dry-run] 未做任何修改。确认无误后加 --apply 执行。")
            return 0

        if not dups:
            return 0

        ids = [r[0] for r in dups]
        # 用 IN 显式列 id：避免再算一遍窗口函数时数据已变，删除范围不可控
        db.execute(
            text("DELETE FROM answer_candidates WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
        db.commit()
        print(f"\n[apply] 已删除 {len(ids)} 行。")

        # 顺手把唯一索引建出来（此前因重复数据一直失败）
        try:
            db.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ansc_qid_src "
                "ON answer_candidates(question_id, source)"
            ))
            db.commit()
            print("[apply] uq_ansc_qid_src 唯一索引已建立。")
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            print(f"[warn] 唯一索引仍未建立：{str(exc)[:200]}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
