# -*- coding: utf-8 -*-
"""掌握度四态模型（未学 / 学习中 / 薄弱 / 已掌握）回归测试。

背景（2026-10-17，任务 #14）：
此前三态口径把"刚开始学习、掌握度在 0-30 区间"的知识点与"完全没学过"的混在一起。
四态新增 learning 状态，区分"正在积累"和"尚未开始"。

本文件锁死四态口径（services/kp_mastery.py）：
  - 未学（无任何学习记录）→ 灰，不计入薄弱；
  - 有记录且 mastery < 30 → 学习中（蓝）；
  - 有记录且 30 ≤ mastery < 70 → 薄弱（黄）；
  - 有记录且 mastery ≥ 70 → 已掌握（绿）。
"""
from __future__ import annotations

import pytest

from sqlalchemy import text

from database import SessionLocal
from models import (
    AnswerRecord,
    ErrorRecord,
    KnowledgePoint,
    QuestionKnowledgeLink,
    QuizQuestion,
    ReviewRecord,
)
from services import kp_mastery, review_service

# 与 conftest 示例数据同一主线科目（taxonomy 只收大纲内科目进 tree）
SUBJECT = "数学"


@pytest.fixture()
def db(db_schema):  # noqa: ARG001  依赖 db_schema 确保临时库已建表
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _mk_kp(db, name, *, mastery=0, review_count=0):
    """建知识点并强制写入 mastery（临时禁用触发器）。

    ⚠️ ``mastery`` 在 PG 下**写不进去**：knowledge_points.mastery 是**派生列**，
    由 BEFORE INSERT/UPDATE 触发器 ``sync_kp_mastery()`` 用
    ``v_knowledge_mastery``（30 天指数衰减加权正确率）**无条件覆盖**。
    这里临时禁用触发器后直接 UPDATE，再重新启用。
    """
    from sqlalchemy import text
    kp = KnowledgePoint(
        name=name, subject=SUBJECT, chapter="三态测试章",
        exam_frequency=1, difficulty=2, review_count=review_count,
    )
    db.add(kp)
    db.commit()
    db.refresh(kp)
    # 强制写入 mastery：临时禁用触发器 → UPDATE → 重新启用
    if mastery:
        db.execute(text("ALTER TABLE knowledge_points DISABLE TRIGGER trg_kp_mastery_sync"))
        db.execute(text("UPDATE knowledge_points SET mastery = :m WHERE id = :id"),
                   {"m": mastery, "id": kp.id})
        db.execute(text("ALTER TABLE knowledge_points ENABLE TRIGGER trg_kp_mastery_sync"))
        db.commit()
        db.refresh(kp)
    return kp
    db.refresh(kp)
    return kp


def _mk_learned_kp(db, name, *, good=3, bad=0):
    """建一个"有真实学习记录"的知识点，掌握度由派生视图真实算出。

    用 review_records 而不是"题目+答题记录"链路：v_knowledge_mastery 的
    reviewed CTE 直接认 review_records(item_type='knowledge')，
    不需要造 quiz_questions（那条路还要绕题目选项约束，成本高得多）。

    good 条 result='good' → ok=1；bad 条 result='again' → ok=0。
    mastery = 100 * weighted_correct / weighted_total，全 good 即 100（>70 → 已掌握）。
    """
    kp = KnowledgePoint(
        name=name, subject=SUBJECT, chapter="三态测试章",
        exam_frequency=1, difficulty=2, review_count=good + bad,
    )
    db.add(kp)
    db.commit()
    db.refresh(kp)

    for i in range(good + bad):
        db.add(ReviewRecord(
            item_type="knowledge", item_id=kp.id, subject=SUBJECT,
            result="good" if i < good else "again", grade=5 if i < good else 1,
        ))
    db.commit()
    # 掌握度只在 knowledge_points 被 UPDATE 时由触发器刷新，
    # 仅写 review_records 不会自动刷 —— 必须显式 touch。
    # （早期写法 kp.review_count = 同值 无效：ORM 值未变则不发 UPDATE，实测 mastery 恒 0）
    kp_mastery.touch_mastery(db, [kp.id])
    db.commit()
    db.refresh(kp)
    return kp



def _purge_test_chapter(db):
    """清掉本章节的历史遗留。

    progress_overview 的 weak_points 是 **TOP10**（有限名额）。同文件其他用例
    会往同一章节塞知识点，残留行会把本用例的样本挤出榜单 —— 断言于是随执行
    顺序漂移（实测："三态-薄弱样本 not in names"）。
    本文件所有用例都自建数据，清理不伤及后续用例。
    """
    db.execute(text(
        "DELETE FROM review_records WHERE item_id IN "
        "(SELECT id FROM knowledge_points WHERE chapter = '三态测试章')"))
    db.execute(text("DELETE FROM knowledge_points WHERE chapter = '三态测试章'"))
    db.commit()


# --------------------------------------------------------------------------- #
# 一、classify_state 纯函数
# --------------------------------------------------------------------------- #

class TestClassifyState:

    def test_no_records_is_unlearned(self):
        assert kp_mastery.classify_state(None, False) == "unlearned"
        assert kp_mastery.classify_state(0, False) == "unlearned"

    def test_has_records_below_threshold_is_learning(self):
        # 有记录但 mastery < 30 → 学习中（蓝）
        assert kp_mastery.classify_state(0, True) == "learning"
        assert kp_mastery.classify_state(29, True) == "learning"
        # 30 ≤ mastery < 70 → 薄弱（黄）
        assert kp_mastery.classify_state(30, True) == "weak"
        assert kp_mastery.classify_state(69, True) == "weak"

    def test_has_records_at_threshold_is_mastered(self):
        assert kp_mastery.classify_state(70, True) == "mastered"
        assert kp_mastery.classify_state(100, True) == "mastered"

    def test_labels_map(self):
        assert kp_mastery.STATE_LABELS == {
            "unlearned": "未学", "learning": "学习中", "weak": "薄弱", "mastered": "已掌握",
        }


# --------------------------------------------------------------------------- #
# 二、「有学习记录」判定
# --------------------------------------------------------------------------- #

class TestLearnedDetection:

    def test_review_count_counts_as_learned(self, db):
        kp = _mk_kp(db, "三态-复习过", review_count=1)
        assert kp.id in kp_mastery.learned_kp_ids(db)

    def test_linked_answer_counts_as_learned(self, db):
        kp = _mk_kp(db, "三态-答过题")
        q = QuizQuestion(content="三态测试题-答", subject=SUBJECT,
                         answer="B", question_type="single")
        db.add(q)
        db.commit()
        db.refresh(q)
        db.add(QuestionKnowledgeLink(question_id=q.id, knowledge_point_id=kp.id))
        db.add(AnswerRecord(question_id=q.id, is_correct=False, subject=SUBJECT))
        db.commit()
        assert kp.id in kp_mastery.learned_kp_ids(db)

    def test_error_knowledge_link_counts_as_learned(self, db):
        from models import ErrorKnowledgeLink

        kp = _mk_kp(db, "三态-错过题")
        db.add(ErrorRecord(content="三态错题", subject=SUBJECT, status="active",
                           accuracy=0.0))
        db.commit()
        err = db.query(ErrorRecord).filter(ErrorRecord.content == "三态错题").first()
        db.add(ErrorKnowledgeLink(error_id=err.id, knowledge_point_id=kp.id, source="manual"))
        db.commit()
        assert kp.id in kp_mastery.learned_kp_ids(db)

    def test_untouched_kp_is_not_learned(self, db):
        kp = _mk_kp(db, "三态-没学过")
        assert kp.id not in kp_mastery.learned_kp_ids(db)


# --------------------------------------------------------------------------- #
# 三、progress_overview 三态口径
# --------------------------------------------------------------------------- #

class TestProgressOverviewThreeState:

    def test_unlearned_not_counted_as_weak(self, db):
        _purge_test_chapter(db)
        # 注意：mastery 是派生列（触发器无条件覆盖手写值），
        # 所以"薄弱/已掌握"必须用真实学习记录造，不能直接写 mastery。
        _mk_learned_kp(db, "三态-薄弱样本", good=2, bad=1)   # ~67% → weak (30-69)
        _mk_learned_kp(db, "三态-已掌握样本", good=3, bad=0)  # 100% → mastered
        _mk_kp(db, "三态-未学样本")  # 无任何学习记录 → unlearned

        ov = review_service.progress_overview(db)

        # 四态计数自洽：learning + weak + mastered + unlearned == total
        assert (ov.get("learning_count", 0) + ov["weak_count"] + ov["mastered_count"] + ov["unlearned_count"]
                == ov["total_knowledge_points"])
        assert ov["weak_count"] >= 1
        assert ov["mastered_count"] >= 1
        assert ov["unlearned_count"] >= 1
        # 新字段存在
        assert "learned_avg_mastery" in ov

        # 薄弱 TOP 的"是否上榜"不做断言：progress_overview 是**全库**统计，
        # weak_points 只取 TOP10 名额，测试库里有其他测试文件的残留知识点，
        # 会随执行顺序把本用例样本挤出榜单（实测：断言随环境漂移，不可复现）。
        # 这里改为验证**语义不变量** —— 与榜单构成无关，才是真正要锁的东西。
        names = {p["name"] for p in ov["weak_points"]}
        assert "三态-未学样本" not in names, "未学知识点不得进薄弱 TOP"

        # 薄弱 TOP 只收已学知识点（未学是"还没开始"，不是"薄弱"）
        learned = kp_mastery.learned_kp_ids(db)
        assert ov["weak_points"], "应至少有一个薄弱项"
        assert all(p["id"] in learned for p in ov["weak_points"])
        assert all(p["state"] in ("learning", "weak", "mastered") for p in ov["weak_points"])

        # 本用例造的样本必须被正确分类（用计数验证，不依赖 TOP10 名额）
        mine = db.query(KnowledgePoint).filter(
            KnowledgePoint.name.in_(["三态-薄弱样本", "三态-已掌握样本", "三态-未学样本"])
        ).all()
        by_name = {k.name: kp_mastery.classify_state(int(k.mastery or 0), k.id in learned)
                   for k in mine}
        assert by_name.get("三态-已掌握样本") == "mastered", by_name
        assert by_name.get("三态-薄弱样本") == "weak", by_name
        assert by_name.get("三态-未学样本") == "unlearned", by_name

    def test_by_subject_has_four_states(self, db):
        _mk_kp(db, "四态-科目薄弱", mastery=50, review_count=1)
        _mk_kp(db, "四态-科目学习中", mastery=20, review_count=1)
        _mk_kp(db, "四态-科目未学")
        ov = review_service.progress_overview(db)
        row = next(s for s in ov["by_subject"] if s["subject"] == SUBJECT)
        assert row.get("learning", 0) >= 1
        assert row["weak"] >= 1
        assert row["unlearned"] >= 1
        assert row.get("learning", 0) + row["mastered"] + row["weak"] + row["unlearned"] == row["total"]
        assert "learned_avg_mastery" in row


# --------------------------------------------------------------------------- #
# 四、taxonomy 接口四态字段
# --------------------------------------------------------------------------- #

class TestTaxonomyThreeStateAPI:

    def test_tree_has_three_state_fields(self, client):
        resp = client.get("/api/taxonomy/tree")
        assert resp.status_code == 200
        tree = resp.json()["tree"]
        for subj in tree:
            for key in ("mastered_count", "weak_count", "unlearned_count",
                        "learned_avg_mastery"):
                assert key in subj, f"科目节点缺字段 {key}"
            for ch in subj["chapters"]:
                for key in ("mastered_count", "weak_count", "unlearned_count"):
                    assert key in ch, f"章节节点缺字段 {key}"
                for kp in ch["knowledge_points"]:
                    assert kp["state"] in ("unlearned", "learning", "weak", "mastered")

    def test_low_mastery_filter_excludes_unlearned(self, client, db):
        _mk_kp(db, "四态-筛选薄弱", mastery=50, review_count=1)   # 30 ≤ m < 70 → weak
        _mk_kp(db, "四态-筛选学习中", mastery=20, review_count=1)  # 0 < m < 30 → learning
        _mk_kp(db, "四态-筛选未学")  # mastery=0、无记录 → unlearned
        # 用 chapter 把范围收到本用例自己造的知识点上：全站知识点有几百条，
        # "一页 200 条取全量"不成立（实测 total=366 会被截断，断言只比对了子集）。
        resp = client.get(
            "/api/taxonomy/knowledge-points",
            params={"low_mastery": "true", "chapter": "三态测试章", "page_size": 200},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] <= 200, f"共 {body['total']} 条，需翻页取全"
        items = body["items"]
        names = {i["name"] for i in items}
        assert "四态-筛选薄弱" in names
        assert "四态-筛选学习中" in names, "学习中知识点也应进薄弱筛选"
        assert "四态-筛选未学" not in names, "未学知识点不得进薄弱筛选"
        assert all(i["state"] in ("weak", "learning") for i in items)

    def test_detail_has_state(self, client, db):
        kp = _mk_kp(db, "四态-详情样本", mastery=50, review_count=2)
        resp = client.get(f"/api/taxonomy/knowledge-points/{kp.id}")
        assert resp.status_code == 200
        assert resp.json()["state"] == "weak"


# --------------------------------------------------------------------------- #
# 五、learner_profile 三态块
# --------------------------------------------------------------------------- #

class TestLearnerProfileFourState:

    def test_profile_knowledge_points_block(self, client, db):
        _mk_kp(db, "四态-画像薄弱", mastery=50, review_count=1)
        _mk_kp(db, "四态-画像学习中", mastery=20, review_count=1)
        _mk_kp(db, "四态-画像未学")
        resp = client.get("/api/analysis/profile", params={"days": 30})
        assert resp.status_code == 200
        kp = resp.json()["knowledge_points"]
        assert kp["total"] >= 3
        assert kp.get("learning", 0) >= 1
        assert kp["weak"] >= 1
        assert kp["unlearned"] >= 1
        assert kp.get("learning", 0) + kp["weak"] + kp["mastered"] + kp["unlearned"] == kp["total"]
        assert kp["labels"]["unlearned"] == "未学"
