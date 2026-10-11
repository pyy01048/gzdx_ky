# -*- coding: utf-8 -*-
"""检查 SFT 样本与真题题干/答案的可配对程度，判断重建训练集的可行性。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from database import SessionLocal
from models import SFTExample, QuizQuestion


def main():
    db = SessionLocal()
    try:
        print("=" * 74)
        print("1) SFTExample 表（原训练数据来源）")
        print("=" * 74)
        total = db.query(SFTExample).count()
        print(f"  总数 {total}")
        if total:
            rows = db.query(SFTExample).limit(3).all()
            for r in rows:
                print(f"\n  --- id={r.id} subject={r.subject} split={r.split} ---")
                print(f"  user[:120]      = {(r.user or '')[:120]!r}")
                print(f"  assistant[:120] = {(r.assistant or '')[:120]!r}")
                u = re.sub(r"\s+", "", r.user or "")
                a = re.sub(r"\s+", "", r.assistant or "")
                print(f"  assistant 是否为 user 子串: {a[:80] in u if a else None}")
            # 统计整体重合
            same = 0
            n = 0
            for r in db.query(SFTExample).all():
                u = re.sub(r"\s+", "", r.user or "")
                a = re.sub(r"\s+", "", r.assistant or "")
                if not a or len(a) < 20:
                    continue
                n += 1
                if a[:120] in u:
                    same += 1
            print(f"\n  ⚠️ assistant 是 user 子串的比例: {same}/{n} "
                  f"({same/max(n,1)*100:.1f}%)")

        print()
        print("=" * 74)
        print("2) QuizQuestion（真题）—— 能否做成真 Q&A 对")
        print("=" * 74)
        q_total = db.query(QuizQuestion).count()
        with_ans = db.query(QuizQuestion).filter(
            QuizQuestion.answer.isnot(None), QuizQuestion.answer != ""
        ).count()
        with_ana = db.query(QuizQuestion).filter(
            QuizQuestion.analysis.isnot(None), QuizQuestion.analysis != ""
        ).count()
        print(f"  题目总数 {q_total}")
        print(f"  有答案   {with_ans}  ({with_ans/max(q_total,1)*100:.1f}%)")
        print(f"  有解析   {with_ana}  ({with_ana/max(q_total,1)*100:.1f}%)")

        print("\n  有答案的样例:")
        for q in db.query(QuizQuestion).filter(
            QuizQuestion.answer.isnot(None), QuizQuestion.answer != ""
        ).limit(5).all():
            print(f"    [{q.subject}] {q.chapter}")
            print(f"      题干: {(q.content or '')[:90]!r}")
            print(f"      答案: {(q.answer or '')[:60]!r}")
            print(f"      解析: {(q.analysis or '')[:60]!r}")

        print()
        print("=" * 74)
        print("3) 知识点 + 知识分块 —— 能否生成「讲解式」训练样本")
        print("=" * 74)
        from models import KnowledgePoint, KnowledgeChunk

        kp_total = db.query(KnowledgePoint).count()
        print(f"  知识点 {kp_total}（含 description 的: "
              f"{db.query(KnowledgePoint).filter(KnowledgePoint.description.isnot(None)).count()}）")
        chunk_total = db.query(KnowledgeChunk).count()
        print(f"  知识分块 {chunk_total}")
        for c in db.query(KnowledgeChunk).limit(3).all():
            print(f"    [{c.subject}] {(c.text or '')[:100]!r}")
        print()
        print("  说明：真题答案 + 知识分块可作为「真 Q&A」的来源，")
        print("       但答案只有 293 条，规模远小于现有 4203 条。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
