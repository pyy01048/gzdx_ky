# -*- coding: utf-8 -*-
"""可练习口径的真库独立校验脚本（2026-10-13）。

为什么独立成脚本而不是单测：真库 670MB，把它挂进 pytest 会拖慢整轮测试，
且部分沙箱环境不允许子进程再开库。故做成可独立运行的脚本，随时可复核。

用法：
    D:/Anaconda/python.exe scripts/verify_quiz_practiceable.py
退出码 0 = 全部通过，1 = 有问题。
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 答案栏被污染的三种形态（与 tests/test_quiz_answer_pollution.py 同源）
PAT_SUB = re.compile(r"^\s*[（(]\s*[0-9一二三四五六七八九十]+\s*[）)]?\s*$")
PAT_TIP = re.compile(r"^(请注意|注意|提示|见解析|略|同上|详见)")
PAT_SHELL = re.compile(r"^\s*(答案|参考答案|解析)\s*[：:．.]?\s*$")


def main() -> int:
    from sqlalchemy import text

    from database import SessionLocal
    from models import QuizQuestion
    from services import quiz_query as qq

    db = SessionLocal()
    problems = []
    try:
        total = db.execute(text("select count(*) from quiz_questions")).scalar()
        base = qq.visible_quiz_filter(db.query(QuizQuestion))
        vis = base.count()
        ans = base.filter(qq.answerable_expr()).count()
        prac_q = base.filter(qq.answerable_expr()).filter(qq.practiceable_expr())
        prac = prac_q.count()

        print("=" * 64)
        print("题库口径（raw ⊇ visible ⊇ answerable ⊇ practiceable）")
        print("=" * 64)
        print(f"  raw        (全部)          {total:>6}")
        print(f"  visible    (排除 OCR 碎片) {vis:>6}")
        print(f"  answerable (有 is_available) {ans:>6}")
        print(f"  practiceable(真正能刷)     {prac:>6}")

        if not (total >= vis >= ans >= prac):
            problems.append(f"口径倒挂：raw={total} vis={vis} ans={ans} prac={prac}")
        if prac == 0:
            problems.append("可练习题量为 0")

        offenders = []
        for r in prac_q.all():
            a = (r.answer or "").strip()
            if PAT_SUB.match(a) or PAT_TIP.match(a) or PAT_SHELL.match(a):
                offenders.append((r.id, r.subject, a[:28]))

        print()
        print("=" * 64)
        print("可练习集合内的答案污染")
        print("=" * 64)
        print(f"  残留污染题数: {len(offenders)}")
        for qid, subj, a in offenders[:15]:
            print(f"    id={qid:<6} [{subj}] {a!r}")
        if offenders:
            problems.append(f"可练习集合仍含 {len(offenders)} 道污染答案题")

        # 分科可练量
        print()
        print("=" * 64)
        print("分科可练量")
        print("=" * 64)
        print(f'  {"科目":<22}{"全部":>7}{"可见":>7}{"可答":>7}{"可练":>7}')
        rows = db.execute(text("""
            select coalesce(subject,'(未标)') s, count(*) n,
              sum(case when coalesce(is_junk,0)=0 then 1 else 0 end) v,
              sum(case when coalesce(is_junk,0)=0 and coalesce(is_available,1)=1 then 1 else 0 end) a
            from quiz_questions group by 1 order by n desc
        """)).fetchall()
        prac_by_subj = dict(
            db.execute(text("""
                select coalesce(subject,'(未标)') s, count(*) n from (
                  select q.id from quiz_questions q
                    join knowledge_chunks_dummy_dummy_dummy_dummy_dummy x on 1=0
                ) group by 1
            """)).fetchall()
        ) if False else {}
        # 分科可练量直接用 Python 侧逐条判定，避免复杂 SQL
        per = {}
        for r in base.filter(qq.answerable_expr()).filter(qq.practiceable_expr()).all():
            per[r.subject or "(未标)"] = per.get(r.subject or "(未标)", 0) + 1
        for s, n, v, a in rows:
            print(f"  {s:<22}{n:>7}{v:>7}{a:>7}{per.get(s, 0):>7}")

        # 解析覆盖
        no_ana = sum(1 for r in prac_q.all() if not (r.analysis or "").strip())
        print()
        print(f"  可练题中无解析: {no_ana} / {prac}  ({no_ana / prac * 100:.0f}%)"
              if prac else "  可练题为 0")

        print()
        print("=" * 64)
        if problems:
            print("发现问题：")
            for p in problems:
                print(f"  ✗ {p}")
            return 1
        print("全部校验通过。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())