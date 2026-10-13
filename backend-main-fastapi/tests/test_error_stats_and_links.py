# -*- coding: utf-8 -*-
"""错题本对接整改的回归测试（docx/22 F2/F3）。

覆盖三个"各算一套 / 硬编码 / 关联错"的真实缺陷：

1. **统计口径唯一**：``GET /api/errors/stats`` 与仪表盘 ``/api/dashboard`` 的
   错题数必须**同源**（都走 ``services/error_linker.error_stats``），
   且三态计数自洽（unlearned+weak+mastered == total）。
2. **掌握度三态真实计算**：``GET /api/errors?mastery_state=X`` 筛出来的条数
   必须等于逐条 ``kp_mastery.error_mastery_state`` 判定为 X 的条数 ——
   不允许页面写死档位、也不允许筛选与展示对不上。
3. **知识点关联按实际链路**：错题 underlying question 在 ``question_knowledge_links``
   的关联（``is_verified=1``）必须出现在 ``GET /api/errors/{id}/knowledge-points``
   里，且标 ``source=question_link`` / ``verified=True``；启发式
   ``error_knowledge_links`` 只作补充（``source`` 为 auto 族 / manual）。
"""
from __future__ import annotations

import pytest

from database import SessionLocal
from models import (
    ErrorRecord,
    ErrorKnowledgeLink,
    KnowledgePoint,
    QuestionKnowledgeLink,
    QuizQuestion,
)
from services import error_linker, kp_mastery

SUBJECT = "数学"


@pytest.fixture()
def db(db_schema):  # noqa: ARG001  依赖 db_schema 确保临时库已建表
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _mk_error(db, content, *, accuracy=0.0, review_count=0, status="active", question_id=None):
    err = ErrorRecord(
        content=content, subject=SUBJECT, accuracy=accuracy, review_count=review_count,
        status=status, question_id=question_id,
    )
    db.add(err)
    db.commit()
    db.refresh(err)
    return err


# --------------------------------------------------------------------------- #
# 一、统计口径唯一 + 三态自洽
# --------------------------------------------------------------------------- #

class TestErrorStatsCaliber:

    def test_endpoint_ok_and_three_state_partition(self, client):
        resp = client.get("/api/errors/stats")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        for key in ("total", "active_errors", "due_errors", "graduated_errors",
                    "unlearned", "weak", "mastered"):
            assert key in data, f"错题统计缺字段 {key}"
        assert data["unlearned"] + data["weak"] + data["mastered"] == data["total"], (
            "三态计数必须严格划分全部错题（未学+薄弱+已掌握 == 总数）"
        )
        assert data["due_errors"] <= data["active_errors"]

    def test_active_matches_db(self, client, db):
        """active_errors 必须等于库里 status='active' 的真实条数。"""
        expected = db.query(ErrorRecord).filter(ErrorRecord.status == "active").count()
        assert client.get("/api/errors/stats").json()["active_errors"] == expected

    def test_same_source_as_dashboard(self, client):
        """错题数与仪表盘同源：dashboard.stats.active_errors == errors/stats.active_errors。"""
        estats = client.get("/api/errors/stats").json()
        dash = client.get("/api/dashboard").json()
        assert dash["stats"]["active_errors"] == estats["active_errors"], (
            "错题本与仪表盘的活跃错题数不一致 —— 说明又各算了一套"
        )
        # 仪表盘同时透出今日到期错题（供今日复习队列使用，同一聚合函数）
        assert dash["stats"]["due_errors"] == estats["due_errors"]

    def test_dashboard_stats_endpoint_same_source(self, client):
        """另一条仪表盘端点 /api/dashboard/stats 也必须同源。"""
        estats = client.get("/api/errors/stats").json()
        dash = client.get("/api/dashboard/stats").json()
        assert dash["active_errors"] == estats["active_errors"]
        assert dash["due_errors"] == estats["due_errors"]


# --------------------------------------------------------------------------- #
# 二、掌握度三态真实计算（筛选 == 逐条判定）
# --------------------------------------------------------------------------- #

class TestErrorMasteryState:

    def test_error_mastery_state_pure(self):
        assert kp_mastery.error_mastery_state(0.0, 0, "active") == kp_mastery.STATE_UNLEARNED
        assert kp_mastery.error_mastery_state(None, 1, "active") == kp_mastery.STATE_WEAK
        assert kp_mastery.error_mastery_state(0.3, 2, "active") == kp_mastery.STATE_WEAK
        assert kp_mastery.error_mastery_state(0.9, 1, "active") == kp_mastery.STATE_MASTERED
        assert kp_mastery.error_mastery_state(0.0, 0, "graduated") == kp_mastery.STATE_MASTERED

    def test_list_filter_matches_per_item_state(self, client, db):
        _mk_error(db, "三态-未学样本", accuracy=0.0, review_count=0, status="active")
        _mk_error(db, "三态-薄弱样本", accuracy=0.2, review_count=2, status="active")
        _mk_error(db, "三态-已掌握样本", accuracy=0.95, review_count=3, status="active")

        rows = db.query(ErrorRecord).all()
        for state in (kp_mastery.STATE_UNLEARNED, kp_mastery.STATE_WEAK, kp_mastery.STATE_MASTERED):
            expected = {
                e.id for e in rows
                if kp_mastery.error_mastery_state(e.accuracy, e.review_count, e.status) == state
            }
            resp = client.get("/api/errors", params={"mastery_state": state, "page_size": 500})
            assert resp.status_code == 200, resp.text
            items = resp.json()["items"]
            got = {i["id"] for i in items}
            assert got == expected, f"{state}: 筛选结果与逐条三态判定不一致"
            # 每条都自带三态与中文标签，前端不必写死档位
            assert all(i["mastery_state"] == state for i in items)
            assert all(i["mastery_label"] == kp_mastery.STATE_LABELS[state] for i in items)

    def test_list_items_carry_state(self, client):
        resp = client.get("/api/errors", params={"page_size": 5})
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["mastery_state"] in ("unlearned", "weak", "mastered")
            assert item["mastery_label"] in ("未学", "薄弱", "已掌握")


# --------------------------------------------------------------------------- #
# 三、知识点关联按实际链路（question_knowledge_links 优先）
# --------------------------------------------------------------------------- #

class TestKnowledgeLinksAreReal:

    def test_question_link_surfaces_and_wins(self, client, db):
        # 题目 + 人工校验的题目-知识点关联（权威链路）
        q = QuizQuestion(content="三态-关联题：JK触发器", subject=SUBJECT,
                         answer="A", question_type="single")
        db.add(q)
        db.commit()
        db.refresh(q)

        kp_ok = KnowledgePoint(name="测试-JK触发器", subject=SUBJECT,
                               chapter="第六章 时序逻辑", mastery=0)
        kp_noise = KnowledgePoint(name="测试-噪声知识点", subject=SUBJECT,
                                  chapter="第一章", mastery=0)
        db.add_all([kp_ok, kp_noise])
        db.commit()
        db.refresh(kp_ok)
        db.refresh(kp_noise)

        db.add(QuestionKnowledgeLink(question_id=q.id, knowledge_point_id=kp_ok.id,
                                     role="primary", weight=1.0, is_verified=True))
        # 同一知识点又被启发式挂了一次（应被去重，保留 question_link 的权威来源）
        db.add(QuestionKnowledgeLink(question_id=q.id, knowledge_point_id=kp_noise.id,
                                     role="secondary", weight=0.3, is_verified=False))
        err = _mk_error(db, "三态-关联错题", question_id=q.id)
        db.add(ErrorKnowledgeLink(error_id=err.id, knowledge_point_id=kp_ok.id,
                                  relevance=0.2, source="name_match"))
        db.add(ErrorKnowledgeLink(error_id=err.id, knowledge_point_id=kp_noise.id,
                                  relevance=0.1, source="keyword_match"))
        # 只有启发式、题目侧没有的孤立关联（应作为补充保留）
        kp_extra = KnowledgePoint(name="测试-仅启发式知识点", subject=SUBJECT, chapter="第二章", mastery=0)
        db.add(kp_extra)
        db.commit()
        db.refresh(kp_extra)
        db.add(ErrorKnowledgeLink(error_id=err.id, knowledge_point_id=kp_extra.id,
                                  relevance=0.05, source="keyword_match"))
        db.commit()

        resp = client.get(f"/api/errors/{err.id}/knowledge-points")
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        by_id = {i["knowledge_point_id"]: i for i in items}

        # 权威链路出现且标 question_link
        assert kp_ok.id in by_id
        assert by_id[kp_ok.id]["source"] == "question_link"
        assert by_id[kp_ok.id]["verified"] is True
        # 幂等去重：同一知识点只出现一次
        ids = [i["knowledge_point_id"] for i in items]
        assert len(ids) == len(set(ids)), "知识点关联必须去重"
        # 权威来源排在启发式之前
        assert items[0]["source"] == "question_link"
        # 仅启发式的知识点作为补充保留
        assert kp_extra.id in by_id
        assert by_id[kp_extra.id]["source"] == "keyword_match"

    def test_items_carry_three_state_label(self, client, db):
        kp = KnowledgePoint(name="测试-三态标签", subject=SUBJECT, chapter="第三章",
                            mastery=80, review_count=3)
        db.add(kp)
        db.commit()
        db.refresh(kp)
        err = _mk_error(db, "三态-标签错题", accuracy=0.4, review_count=1)
        db.add(ErrorKnowledgeLink(error_id=err.id, knowledge_point_id=kp.id,
                                  relevance=0.9, source="manual"))
        db.commit()

        items = client.get(f"/api/errors/{err.id}/knowledge-points").json()["items"]
        row = next(i for i in items if i["knowledge_point_id"] == kp.id)
        assert row["state"] == "mastered"       # mastery=80 且有学习记录
        assert row["state_label"] == "已掌握"
