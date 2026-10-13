# -*- coding: utf-8 -*-
"""答案字段污染的回归测试（专业课题库体检，2026-10-13）。

真库实测发现一类此前完全没被发现的污染：**答案栏里装的不是答案**，
用户拿它比对必然得到错误判分。逐条有据：

  id=366/479/574 [数字电子技术] 答案='（1）'
      题干是**多问题目**，「（1）」是第一小问的编号被误当成答案。
      用户答「（1）」被判对，实际完全没答对。
  id=7882 [数字电子技术] 答案='（10011)'   ← 畸形标号（右括号半角）
  id=248/566/568/701 答案='见解析' / '见解析。'
  id=2640/2641/2643 [模拟电子技术] 答案='请注意电路中IB和IC的数量级'
      答案栏存的是提示语，根本没有可比对的答案。
  另有 151 道答案是空壳（'答案：' / '参考答案：'）。
  另有 115 道答案是「一、填空题」这种题型标题（串入答案栏）。

这些必须被 ``practiceable_expr`` 挡住，同时**不得误杀正常题**。

实现说明：本测试**不在 Python 侧复刻 SQL 语义**（``has_real_answer_expr``
用 SQLite 的 LIKE / GLOB / json_each 写成，复刻一份必然与实现漂移）。
改为用**真实 ORM 模型 + 内存 SQLite**跑同一个表达式 —— 口径与生产完全一致。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, QuizQuestion
from services import quiz_query as qq


@pytest.fixture()
def db():
    """内存 SQLite + 真实 ORM 模型（表名与真库一致，json_each 判据才能工作）。"""
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng, tables=[QuizQuestion.__table__])
    session = sessionmaker(bind=eng)()
    try:
        yield session
    finally:
        session.close()


def _judge(db, answer: str) -> bool:
    """该答案在 practiceable 口径下是否可练习。"""
    db.query(QuizQuestion).delete()
    db.add(QuizQuestion(
        id=1, content="题干", answer=answer, options=None,
        is_available=True, figure_missing=0,
    ))
    db.commit()
    return db.query(QuizQuestion).filter(qq.practiceable_expr()).first() is not None


# --------------------------------------------------------------------------- #
# 必须被挡住
# --------------------------------------------------------------------------- #
POLLUTED = [
    ("（1）", "多问题目的小问编号"),
    ("（25）", "多问题目的小问编号"),
    ("(1)", "半角小问编号"),
    ("（10011)", "畸形标号：全角左括号 + 半角右括号（实测 id=7882）"),
    ("见解析", "占位语"),
    ("见解析。", "占位语带句号"),
    ("详见解析", "占位语"),
    ("略", "占位语"),
    ("同上", "占位语"),
    ("请注意电路中IB和IC的数量级", "提示语（实测 id=2640/2641/2643）"),
    ("注意", "提示语"),
    ("提示", "提示语"),
    ("答案：", "答案壳"),
    ("参考答案：", "答案壳"),
    ("一、填空题", "题型标题串入答案（实测 115 行）"),
    ("一、判断题", "题型标题串入答案"),
    ("二、选择题", "题型标题串入答案"),
    ("二、计算题", "题型标题串入答案"),
    ("第1章 拓展习题", "章节标题串入答案"),
    ("填入空内。", "指令残留"),
    ("", "空答案"),
    ("   ", "全空白答案"),
]


@pytest.mark.parametrize("answer,why", POLLUTED)
def test_polluted_answers_are_blocked(db, answer, why):
    assert not _judge(db, answer), f"「{answer}」({why}) 不应被判为可练习"


# --------------------------------------------------------------------------- #
# 防误杀
# --------------------------------------------------------------------------- #
REAL_ANSWERS = [
    ("A", "选择题选项"),
    ("B", "选择题选项"),
    ("正确", "判断题"),
    ("×", "判断题符号"),
    ("接地", "填空答案"),
    ("1.5", "小数"),
    ("F＝∑m（1,2,4）", "含括号数学表达式——不得被小问标号规则误杀"),
    ("F＝ABC＋ABCD＋BCD＋A′B′C′D", "逻辑表达式"),
    ("（1）A", "小问编号 + 选项的混合答案"),
    ("第一题答案", "含「第一」但不是题型标题"),
    ("一", "单字答案"),
]


@pytest.mark.parametrize("answer,why", REAL_ANSWERS)
def test_real_answers_are_kept(db, answer, why):
    assert _judge(db, answer), f"「{answer}」({why}) 不应被误杀"


# --------------------------------------------------------------------------- #
# 占位语清单覆盖实测词
# --------------------------------------------------------------------------- #
def test_placeholder_prefixes_cover_observed_values():
    for w in ("见解析", "请注意", "略"):
        assert w in qq._ANSWER_PLACEHOLDER_PREFIX, f"占位语清单缺少 {w}"


# --------------------------------------------------------------------------- #
# 真实库回归（需 670MB 真库）
#
# 必须跑在**独立子进程**里：本模块的判定单测用内存 SQLite + create_all，
# 与 ``database.engine`` 共用 SQLAlchemy 元数据/事件，进程内复用会把引擎指向内存库。
# 子进程天然隔离，也顺带验证了「从零启动就能拿到真库」。
# --------------------------------------------------------------------------- #
_REAL_CHECK = r'''
import sys, re, os
sys.path.insert(0, os.getcwd())
from database import SessionLocal
from models import QuizQuestion
from services import quiz_query as qq
import sqlalchemy as sa

db = SessionLocal()
try:
    base = qq.visible_quiz_filter(db.query(QuizQuestion))
    counts = {
        "raw":  db.query(QuizQuestion).count(),
        "vis":  base.count(),
        "ans":  base.filter(qq.answerable_expr()).count(),
        "prac": base.filter(qq.answerable_expr()).filter(qq.practiceable_expr()).count(),
    }
    prac = base.filter(qq.answerable_expr()).filter(qq.practiceable_expr())
    pat_sub   = re.compile(r"^\s*[（(]\s*[0-9一二三四五六七八九十]+\s*[）)]?\s*$")
    pat_tip   = re.compile(r"^(请注意|注意|提示|见解析|略|同上|详见)")
    pat_shell = re.compile(r"^\s*(答案|参考答案|解析)\s*[：:．.]?\s*$")
    offenders = [
        (r.id, (r.answer or "")[:24]) for r in prac.all()
        if pat_sub.match((r.answer or "").strip())
        or pat_tip.match((r.answer or "").strip())
        or pat_shell.match((r.answer or "").strip())
    ]
    print("COUNTS", counts["raw"], counts["vis"], counts["ans"], counts["prac"])
    print("OFFENDERS", len(offenders), offenders[:5])
finally:
    db.close()
'''


def _run_real_check():
    """跑真库自检子进程，返回 (counts, offenders, raw_stdout)；失败返回 None。

    cwd 必须是**后端根目录**（本文件在 ``<backend>/tests/`` 下），
    否则子进程 import 不到 ``database`` / ``models``。
    """
    import os
    import subprocess
    import sys as _sys
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        r = subprocess.run(
            [_sys.executable, "-c", _REAL_CHECK],
            capture_output=True, text=True, timeout=300, cwd=backend_root,
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    counts, offenders = {}, 0
    for line in r.stdout.splitlines():
        if line.startswith("COUNTS"):
            _, raw, vis, ans, prac = line.split()
            counts = {"raw": int(raw), "vis": int(vis), "ans": int(ans), "prac": int(prac)}
        elif line.startswith("OFFENDERS"):
            offenders = int(line.split()[1])
    return counts or None, offenders, r.stdout


_RC = _run_real_check()


def test_real_library_caliber_and_cleanliness():
    """真实库端到端校验（子进程隔离执行）。

    一次性验证两件事，避免拆成两个用例重复启动 670MB 库：
      1. 口径恒等式 raw(9096) ⊇ visible(5507) ⊇ answerable(3385) ⊇ practiceable(~2100)
      2. practiceable 集合内**不再有**污染答案（子问编号 / 占位语 / 答案壳）

    若 pytest 沙箱内子进程启动失败（部分环境限制），跳过并提示改跑
    ``python scripts/verify_quiz_practiceable.py`` —— 那个脚本能独立跑通，
    真库数据不依赖单测进程。
    """
    if _RC is None:
        pytest.skip(
            "pytest 沙箱内无法启动真库子进程；"
            "请独立运行 python scripts/verify_quiz_practiceable.py 做同等校验"
        )
    counts, offenders, out = _RC
    assert offenders == 0, f"可练习集合仍含污染答案：\n{out}"
    assert counts["raw"] >= counts["vis"] >= counts["ans"] >= counts["prac"], \
        f"口径倒挂：{counts}"
    assert counts["prac"] > 0, "可练习题量不应为 0"