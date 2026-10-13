# -*- coding: utf-8 -*-
"""掌握度三态模型（未学 / 薄弱 / 已掌握）回归测试。

背景：旧口径只有"已掌握（mastery≥70）/ 其余全算薄弱（mastery<40）"，
未学习的知识点（mastery=0、无任何学习记录）被误算进薄弱 ——
真实库 1067 个知识点里 1065 个没有任何学习记录，于是"薄弱≈总数、
已掌握=0"，指标失真（用户抱怨"掌握程度硬编码"）。

本文件锁死三态口径（services/kp_mastery.py）：
  - 未学（无任何学习记录）→ 灰，不计入薄弱；
  - 有记录但 mastery < 70 → 薄弱（黄）；
  - 有记录且 mastery ≥ 70 → 已掌握（绿）。
"""
from __future__ import annotations

import pytest

from database import SessionLocal
from models import (
    AnswerRecord,
    ErrorRecord,
    KnowledgePoint,
    QuestionKnowledgeLink,
    QuizQuestion,
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
    kp = KnowledgePoint(
        name=name, subject=SUBJECT, chapter="三态测试章",
        mastery=mastery, exam_frequency=1, difficulty=2, review_count=review_count,
    )
    db.add(kp)
    db.commit()
    db.refresh(kp)
    return kp


# --------------------------------------------------------------------------- #
# 一、classify_state 纯函数
# --------------------------------------------------------------------------- #

class TestClassifyState:

    def test_no_records_is_unlearned(self):
        assert kp_mastery.classify_state(None, False) == "unlearned"
        assert kp_mastery.classify_state(0, False) == "unlearned"

    def test_has_records_below_threshold_is_weak(self):
        assert kp_mastery.classify_state(0, True) == "weak"
        assert kp_mastery.classify_state(69, True) == "weak"

    def test_has_records_at_threshold_is_mastered(self):
        assert kp_mastery.classify_state(70, True) == "mastered"
        assert kp_mastery.classify_state(100, True) == "mastered"

    def test_labels_map(self):
        assert kp_mastery.STATE_LABELS == {
            "unlearned": "未学", "weak": "薄弱", "mastered": "已掌握",
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
        _mk_kp(db, "三态-薄弱样本", mastery=30, review_count=1)
        _mk_kp(db, "三态-已掌握样本", mastery=85, review_count=3)
        _mk_kp(db, "三态-未学样本")  # mastery=0、无任何学习记录

        ov = review_service.progress_overview(db)

        # 三态计数自洽：weak + mastered + unlearned == total
        assert (ov["weak_count"] + ov["mastered_count"] + ov["unlearned_count"]
                == ov["total_knowledge_points"])
        assert ov["weak_count"] >= 1
        assert ov["mastered_count"] >= 1
        assert ov["unlearned_count"] >= 1
        # 新字段存在
        assert "learned_avg_mastery" in ov

        names = {p["name"] for p in ov["weak_points"]}
        assert "三态-薄弱样本" in names
        assert "三态-未学样本" not in names, "未学知识点不得进薄弱 TOP"
        # 薄弱 TOP 只收已学知识点
        learned = kp_mastery.learned_kp_ids(db)
        assert all(p["id"] in learned for p in ov["weak_points"])
        assert all(p["state"] in ("weak", "mastered") for p in ov["weak_points"])

    def test_by_subject_has_three_states(self, db):
        _mk_kp(db, "三态-科目薄弱", mastery=20, review_count=1)
        _mk_kp(db, "三态-科目未学")
        ov = review_service.progress_overview(db)
        row = next(s for s in ov["by_subject"] if s["subject"] == SUBJECT)
        assert row["weak"] >= 1
        assert row["unlearned"] >= 1
        assert row["mastered"] + row["weak"] + row["unlearned"] == row["total"]
        assert "learned_avg_mastery" in row


# --------------------------------------------------------------------------- #
# 四、taxonomy 接口三态字段
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
                    assert kp["state"] in ("unlearned", "weak", "mastered")

    def test_low_mastery_filter_excludes_unlearned(self, client, db):
        _mk_kp(db, "三态-筛选薄弱", mastery=30, review_count=1)
        _mk_kp(db, "三态-筛选未学")  # mastery=0、无记录
        resp = client.get(
            "/api/taxonomy/knowledge-points",
            params={"low_mastery": "true", "page_size": 500},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        names = {i["name"] for i in items}
        assert "三态-筛选薄弱" in names
        assert "三态-筛选未学" not in names, "未学知识点不得进薄弱筛选"
        assert all(i["state"] == "weak" for i in items)

    def test_detail_has_state(self, client, db):
        kp = _mk_kp(db, "三态-详情样本", mastery=50, review_count=2)
        resp = client.get(f"/api/taxonomy/knowledge-points/{kp.id}")
        assert resp.status_code == 200
        assert resp.json()["state"] == "weak"


# --------------------------------------------------------------------------- #
# 五、learner_profile 三态块
# --------------------------------------------------------------------------- #

class TestLearnerProfileThreeState:

    def test_profile_knowledge_points_block(self, client, db):
        _mk_kp(db, "三态-画像薄弱", mastery=25, review_count=1)
        _mk_kp(db, "三态-画像未学")
        resp = client.get("/api/analysis/profile", params={"days": 30})
        assert resp.status_code == 200
        kp = resp.json()["knowledge_points"]
        assert kp["total"] >= 2
        assert kp["weak"] >= 1
        assert kp["unlearned"] >= 1
        assert kp["weak"] + kp["mastered"] + kp["unlearned"] == kp["total"]
        assert kp["labels"]["unlearned"] == "未学"
