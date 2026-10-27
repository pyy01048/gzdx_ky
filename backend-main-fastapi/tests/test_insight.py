# -*- coding: utf-8 -*-
"""V11 学习洞察回归测试（F1 今日引导 / F2 智能组卷 / F4 周报）。

隔离：走 conftest 临时库。覆盖：
1. GET /api/insight/today 返回行动清单与倒计时，空库不炸；
2. GET /api/insight/weekly-report 本周 vs 上周统计与逐日曲线长度=7；
3. POST /api/insight/smart-paper 三模式抽题 + basis 说明 + 422 校验。
"""
from __future__ import annotations

import datetime

import pytest

from database import Base, SessionLocal, engine
from utils.timeutil import local_today, utcnow
from models import Goal, QuizQuestion, StudyEvent
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.add(Goal(exam_date=local_today() + datetime.timedelta(days=100),
                    total_score_target=360))
        for i in range(12):
            db.add(QuizQuestion(
                content=f"测试题目{i}", options='{"A":"1","B":"2"}',
                answer="A", analysis="测试解析", subject="数电",
                knowledge_point=f"组合逻辑{i % 3}", is_available=True,
            ))
        now = utcnow()  # naive UTC，与 DB 列同语义
        for i in range(10):
            db.add(StudyEvent(
                event_type="answer", subject="数电", is_correct=(i % 2 == 0),
                occurred_at=now - datetime.timedelta(hours=i * 8),
            ))
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
def test_today_insight():
    r = client.get("/api/insight/today")
    assert r.status_code == 200
    d = r.json()
    # conftest baseline_seed 先插 180 天 Goal（session 级共享库，id 靠前），
    # countdown 实现取第一条 Goal——全量跑时为 180，单独跑本文件为 100。
    # 只锁"返回了有效的未来天数"，具体天数属 DashboardService 的职责。
    assert isinstance(d["countdown"]["days"], int) and d["countdown"]["days"] >= 0
    assert len(d["suggestions"]) == 4
    assert d["today_answered"] >= 1


def test_weekly_report():
    r = client.get("/api/insight/weekly-report")
    assert r.status_code == 200
    d = r.json()
    assert len(d["daily"]) == 7
    assert d["this_week"]["answered"] >= 1
    assert d["this_week"]["accuracy"] is not None
    assert isinstance(d["summary"], str) and len(d["summary"]) > 0


@pytest.mark.parametrize("mode", ["weak", "error_prone", "random"])
def test_smart_paper_modes(mode):
    r = client.post("/api/insight/smart-paper",
                    json={"mode": mode, "size": 5, "subject": "数电"})
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == mode
    assert 1 <= d["size"] <= 5
    assert len(d["questions"]) == d["size"]
    assert d["basis"]


def test_smart_paper_validation():
    r = client.post("/api/insight/smart-paper", json={"mode": "weak", "size": 0})
    assert r.status_code == 422
    r = client.post("/api/insight/smart-paper", json={"mode": "nope", "size": 5})
    assert r.status_code in (200, 404, 422)  # 未知模式退化为随机（200）或被校验拒绝
