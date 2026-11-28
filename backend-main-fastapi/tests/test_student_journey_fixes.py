# -*- coding: utf-8 -*-
"""2026-11-22 学生视角公网实测三个 P0/P1 的回归测试。

公网旅程（qa_student01）暴露的三处 500 + 一处口径分裂，这里逐一钉死：

1. **PUT /api/goals 新用户首次设目标 500**
   根因：goals.py 从 core.models 引 Goal（另一套 DeclarativeBase），
   其 MetaData 里没有 users 表 → flush 排序抛 NoReferencedTableError。
   修复：改用 models.py 同源模型。回归点 = 全新用户（库里无 Goal 行）首次 PUT。

2. **POST /api/words/spell-check 第二次复习 500**
   根因：review_schedules.last_reviewed_at 是 TIMESTAMPTZ，PG 读回 aware；
   fsrs.py 用 naive utcnow() 相减 → TypeError。
   修复：to_naive_utc 归一。回归点 = 同一词连续两次拼写（第二次走 elapsed 分支）。

3. **POST /api/tasks 传中文阶段「强化」500**
   根因：prep_stage 枚举只有 basic/intensive/sprint/retest，中文值直插报
   invalid input value for enum。修复：PgEnumAware + _PgEnum 双路径别名归一。
   回归点 = 四个中文阶段各建一条任务，读回必须是规范英文值。

4. **中枢复习队列漏单词（口径分裂）**
   dashboard_service.get_review_queue 此前只算卡片/任务/错题，单词页
   「今日待复习」与中枢「现在可做 N 项」两个数。修复后队列带 words 段。

另附 heatmap compact 契约：summary 的 heatmap 每行只保留前端消费的 5 个字段。
"""

from __future__ import annotations

import datetime
import uuid
from types import SimpleNamespace

import pytest
from database import SessionLocal
from main import app
from tests.asgi_client import ASGIClient
from utils.security import current_user

from models import Goal, Task, User, Word

client = ASGIClient(app)


@pytest.fixture(scope="module", autouse=True)
def _fresh_user():
    """全新用户：没有任何 Goal/Task/Word 行 —— 复现「注册后第一步」场景。"""
    db = SessionLocal()
    try:
        u = User(username=f"jfix{uuid.uuid4().hex[:8]}", display_name="旅程回归用户", role="user", is_active=True)
        u.password_hash = "test-placeholder-never-used-for-login"
        db.add(u)
        db.commit()
        uid = u.id
    finally:
        db.close()

    app.dependency_overrides[current_user] = lambda: SimpleNamespace(
        id=uid,
        username="jfix",
        role="user",
    )
    yield uid
    from utils.security import stub_principal

    app.dependency_overrides[current_user] = lambda: stub_principal()

    db = SessionLocal()
    try:
        from sqlalchemy import text

        db.execute(text("DELETE FROM review_schedules WHERE user_id = :uid"), {"uid": uid})
        db.query(Task).filter(Task.user_id == uid).delete(synchronize_session=False)
        db.query(Word).filter(Word.user_id == uid).delete(synchronize_session=False)
        db.query(Goal).filter(Goal.user_id == uid).delete(synchronize_session=False)
        db.query(User).filter(User.id == uid).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 1. 新用户首次 PUT /goals（NoReferencedTableError 回归）
# --------------------------------------------------------------------------- #
def test_first_goal_put_creates_row_for_fresh_user(_fresh_user):
    r = client.put(
        "/api/goals",
        json={
            "total_score_target": 380,
            "university": "回归测试大学",
            "daily_focus_minutes": 120,
        },
    )
    assert r.status_code == 200, r.text
    gid = r.json()["id"]
    db = SessionLocal()
    try:
        row = db.query(Goal).filter(Goal.id == gid).first()
        assert row is not None and row.user_id == _fresh_user
        assert row.total_score_target == 380
    finally:
        db.close()
    # 第二次 PUT 走更新分支，同样不许 500
    r2 = client.put("/api/goals", json={"total_score_target": 390})
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == gid


# --------------------------------------------------------------------------- #
# 2. 拼写连续两次（aware/naive datetime 混算回归）
# --------------------------------------------------------------------------- #
def test_spell_check_twice_no_datetime_typeerror(_fresh_user):
    db = SessionLocal()
    try:
        w = Word(
            word=f"jfixword{uuid.uuid4().hex[:8]}",
            meaning="回归词",
            status="not_mastered",
            due_date=datetime.date.today(),
            user_id=_fresh_user,
        )
        db.add(w)
        db.commit()
        wid = w.id
    finally:
        db.close()

    body = {"word_id": wid, "answer": "x"}  # 第一次：建 review_schedules 行
    r1 = client.post("/api/words/spell-check", json=body)
    assert r1.status_code == 200, r1.text
    # 第二次：读回 TIMESTAMPTZ（aware）与 now 相减 —— 修复前这里 500
    r2 = client.post("/api/words/spell-check", json=body)
    assert r2.status_code == 200, r2.text
    assert r2.json()["review"]["lapses"] == 2
    # due 必须是可 fromisoformat 的字符串（下游 errors/review 路由直接解析）
    due = r2.json()["review"].get("due")
    assert due is None or isinstance(due, str)


# --------------------------------------------------------------------------- #
# 3. 中文阶段别名（prep_stage 枚举回归）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "zh,en",
    [
        ("基础", "basic"),
        ("强化", "intensive"),
        ("冲刺", "sprint"),
        ("复试", "retest"),
    ],
)
def test_create_task_with_chinese_stage(_fresh_user, zh, en):
    r = client.post(
        "/api/tasks",
        json={
            "title": f"jfix任务-{zh}",
            "subject": "数学",
            "stage": zh,
        },
    )
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    db = SessionLocal()
    try:
        row = db.query(Task).filter(Task.id == tid).first()
        assert row is not None and row.stage == en, f"{zh} 应归一为 {en}，实际 {row.stage}"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 4. 中枢复习队列必须含单词段（口径统一回归）
# --------------------------------------------------------------------------- #
def test_review_queue_includes_due_words(_fresh_user):
    db = SessionLocal()
    try:
        w = Word(
            word=f"jfixdue{uuid.uuid4().hex[:8]}",
            meaning="到期词",
            status="learning",
            due_date=datetime.date.today(),
            user_id=_fresh_user,
        )
        db.add(w)
        db.commit()
        wid = w.id
    finally:
        db.close()

    from services.dashboard_service import DashboardService

    db = SessionLocal()
    try:
        rq = DashboardService.get_review_queue(db, user_id=_fresh_user)
    finally:
        db.close()
    assert "words" in rq, "复习队列缺 words 段（中枢与单词页口径分裂）"
    ids = [item["id"] for item in rq["words"]]
    assert wid in ids
    assert all(item.get("kind") == "word" for item in rq["words"])
    assert rq["total"] >= len(rq["words"])


# --------------------------------------------------------------------------- #
# 5. heatmap compact 契约（首屏减重）
# --------------------------------------------------------------------------- #
def test_summary_heatmap_is_compact(_fresh_user):
    from services.study_calendar import effective_activity_days

    days = effective_activity_days({}, compact=True)
    assert days, "compact 模式也必须给出连续日期序列"
    allowed = {"date", "focus_minutes", "questions_done", "words_done", "is_effective"}
    for row in days:
        assert set(row.keys()) <= allowed, f"compact 行携带多余字段：{set(row.keys()) - allowed}"
