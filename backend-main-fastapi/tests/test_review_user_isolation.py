# -*- coding: utf-8 -*-
"""B4 用户隔离回归（复习 / 洞察 / 模考 / 词库）——「诚实初始化」整改验收。

锁死三条口径：
1. 零数据新用户（B）首屏必须空/零：复习统计、到期队列、进度总览、薄弱点、
   联动覆盖率、今日洞察、周报、模考 KPI/热力图、词库，全部不得借用
   他人（A）数据或全局内容伪造"我的数据"；
2. B 的写操作不得污染 A 的行，也不得改写全局 KnowledgePoint 的调度/掌握度
   字段（个人排程权威在 review_schedules 用户行）；
3. 词库模板只能显式导入（首访自动克隆已废除），导入幂等、归属正确，
   非本人资源 CRUD 一律 404（不泄露存在性）。

数据隔离：双用户 A=9101 / B=9102 + 模板所有者 id=1，夹具按用户清理全部
种子与用例写入，不影响其它测试文件（共享会话库）。
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from database import SessionLocal
from models import (
    ErrorKnowledgeLink,
    ErrorRecord,
    KnowledgePoint,
    QuizQuestion,
    ReviewRecord,
    ReviewSchedule,
    StudyEvent,
    StudyStats,
    User,
    Word,
    WordDeck,
)
from sqlalchemy import text
from utils.security import current_user
from utils.timeutil import local_today, utcnow

UID_A = 9101
UID_B = 9102
UID_TPL = 1  # 模板所有者口径与 words 路由 TEMPLATE_OWNER_ID 一致
TPL_DECK_NAME = "隔离模板词库"


def _principal(uid: int, role: str = "user") -> SimpleNamespace:
    """与 stub_principal 同构的登录态；默认普通用户角色，证明个人 CRUD 不再要管理员。"""
    return SimpleNamespace(
        id=uid,
        username=f"iso_{uid}",
        display_name=f"iso_{uid}",
        role=role,
        is_active=True,
        must_change_password=False,
        token_version=0,
        last_login_at=None,
        created_at=None,
    )


@pytest.fixture()
def iso(app_module, db_schema):  # noqa: ARG001 — db_schema 负责建表/播种
    """双用户种子环境：A 有完整个人数据，B 零数据；yield 后全量清理。"""
    from core.models.exams import ExamSession

    db = SessionLocal()
    prev_override = app_module.dependency_overrides.get(current_user)

    def login(uid: int, role: str = "user"):
        app_module.dependency_overrides[current_user] = lambda: _principal(uid, role)

    try:
        # —— 用户（get-or-create，users 行保留无害，个人数据行全部清理）——
        for uid in (UID_A, UID_B, UID_TPL):
            if db.query(User).filter(User.id == uid).first() is None:
                db.add(
                    User(
                        id=uid,
                        username=f"iso_{uid}",
                        password_hash="!disabled-iso-test",
                        display_name=f"iso_{uid}",
                        role="user",
                        is_active=True,
                        must_change_password=False,
                        token_version=0,
                    )
                )
        db.commit()

        now = utcnow()
        past = now - datetime.timedelta(days=1)

        # —— 全局内容（共享，但调度/掌握度字段不许被个人复习改写）——
        kp1 = KnowledgePoint(name="隔离KP-甲", subject="数学", chapter="隔离测试章", exam_frequency=1, difficulty=2)
        kp2 = KnowledgePoint(name="隔离KP-乙", subject="数学", chapter="隔离测试章", exam_frequency=1, difficulty=2)
        qq = QuizQuestion(
            content="隔离测试题：智能组卷兜底用",
            options=["1", "2"],
            answer="A",
            subject="数学",
            knowledge_point="隔离考点",
            is_available=True,
            question_type="single",
        )
        db.add_all([kp1, kp2, qq])
        db.commit()

        # —— A 的个人数据 ——
        err = ErrorRecord(
            user_id=UID_A,
            content="隔离错题-甲",
            my_answer="A",
            correct_answer="B",
            error_reason="隔离测试",
            subject="数学",
            status="active",
            accuracy=0.2,
            review_count=1,
            next_review=past,
            knowledge_point_id=kp1.id,
        )
        db.add(err)
        db.commit()
        db.add(ErrorKnowledgeLink(error_id=err.id, knowledge_point_id=kp1.id, user_id=UID_A, source="manual"))
        db.add_all(
            [
                ReviewSchedule(
                    user_id=UID_A,
                    item_type="knowledge_point",
                    item_id=kp1.id,
                    algorithm="sm2",
                    repetitions=2,
                    interval_days=3,
                    last_reviewed_at=now - datetime.timedelta(days=4),
                    next_review_at=past,
                ),
                ReviewSchedule(
                    user_id=UID_A,
                    item_type="error_record",
                    item_id=err.id,
                    algorithm="sm2",
                    repetitions=1,
                    interval_days=2,
                    last_reviewed_at=now - datetime.timedelta(days=3),
                    next_review_at=past,
                ),
                ReviewRecord(
                    user_id=UID_A,
                    item_type="knowledge",
                    item_id=kp1.id,
                    subject="数学",
                    result="good",
                    grade=5,
                    mastery_before=40,
                    mastery_after=52,
                    created_at=now - datetime.timedelta(days=4),
                ),
                StudyEvent(
                    user_id=UID_A,
                    event_type="answer",
                    subject="数学",
                    knowledge_point_id=kp2.id,
                    is_correct=True,
                    occurred_at=now,
                ),
                StudyStats(user_id=UID_A, date=local_today(), total_duration=60),
            ]
        )
        sess = ExamSession(
            user_id=UID_A,
            blueprint_key="math2:general",
            subject="数学",
            paper="math2",
            mode="normal",
            question_source="external_import",
            config={},
            total_count=2,
            total_score=10.0,
            correct_count=1,
            score=5.0,
            time_limit_minutes=180,
            status="submitted",
            submitted_at=now,
        )
        db.add(sess)
        db.commit()

        # —— 模板词库（user_id=1）+ 2 词条 ——
        tpl_deck = WordDeck(
            user_id=UID_TPL, name=TPL_DECK_NAME, description="隔离测试模板", source="built_in", word_count=2
        )
        db.add(tpl_deck)
        db.commit()
        db.add_all(
            [
                Word(
                    user_id=UID_TPL, deck_id=tpl_deck.id, word="isowordone", meaning="隔离词一", status="not_mastered"
                ),
                Word(
                    user_id=UID_TPL, deck_id=tpl_deck.id, word="isowordtwo", meaning="隔离词二", status="not_mastered"
                ),
            ]
        )
        db.commit()

        yield SimpleNamespace(
            db=db,
            login=login,
            kp1_id=kp1.id,
            kp2_id=kp2.id,
            qq_id=qq.id,
            err_id=err.id,
            sess_id=sess.id,
            tpl_deck_id=tpl_deck.id,
        )
    finally:
        # 恢复 conftest 的管理员旁路，避免污染后续用例
        if prev_override is not None:
            app_module.dependency_overrides[current_user] = prev_override
        else:
            app_module.dependency_overrides.pop(current_user, None)
        # 清理顺序按 FK 依赖：先子表后父表；原生 SQL 走 DB 级 CASCADE
        db.rollback()
        try:
            from sqlalchemy import bindparam

            uids_param = bindparam("uids", expanding=True)
            cleanup = [
                (
                    "DELETE FROM exam_answers WHERE session_id IN"
                    " (SELECT id FROM exam_sessions WHERE user_id IN :uids)",
                    {"uids": (UID_A, UID_B)},
                ),
                ("DELETE FROM exam_sessions WHERE user_id IN :uids", {"uids": (UID_A, UID_B)}),
                (
                    "DELETE FROM error_knowledge_links WHERE user_id IN :uids"
                    " OR error_id IN (SELECT id FROM error_records WHERE user_id IN :uids)",
                    {"uids": (UID_A, UID_B)},
                ),
                ("DELETE FROM review_schedules WHERE user_id IN :uids", {"uids": (UID_A, UID_B)}),
                ("DELETE FROM review_records WHERE user_id IN :uids", {"uids": (UID_A, UID_B)}),
                ("DELETE FROM study_events WHERE user_id IN :uids", {"uids": (UID_A, UID_B)}),
                ("DELETE FROM study_stats WHERE user_id IN :uids", {"uids": (UID_A, UID_B)}),
                ("DELETE FROM error_records WHERE user_id IN :uids", {"uids": (UID_A, UID_B)}),
                ("DELETE FROM words WHERE user_id IN :uids", {"uids": (UID_A, UID_B)}),
                (
                    "DELETE FROM words WHERE deck_id IN (SELECT id FROM word_decks WHERE name = :tpl)",
                    {"tpl": TPL_DECK_NAME},
                ),
                ("DELETE FROM word_decks WHERE user_id IN :uids", {"uids": (UID_A, UID_B)}),
                (
                    "DELETE FROM word_decks WHERE name = :tpl AND user_id = :tpl_uid",
                    {"tpl": TPL_DECK_NAME, "tpl_uid": UID_TPL},
                ),
                ("DELETE FROM quiz_questions WHERE content = '隔离测试题：智能组卷兜底用'", {}),
                ("DELETE FROM knowledge_points WHERE name IN ('隔离KP-甲', '隔离KP-乙')", {}),
            ]
            for sql, params in cleanup:
                stmt = text(sql)
                if "uids" in params:
                    stmt = stmt.bindparams(uids_param)
                db.execute(stmt, params)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _kp_schedule_snapshot(db, kp_id: int) -> dict:
    """全局 KP 的调度/掌握度字段快照（B 提交后必须原样）。"""
    db.expire_all()
    kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == kp_id).first()
    return {
        "mastery": kp.mastery,
        "review_count": kp.review_count,
        "next_review": kp.next_review,
        "interval_days": getattr(kp, "interval_days", None),
        "ease_factor": kp.ease_factor,
        "lapses": kp.lapses,
        "last_review": kp.last_review,
    }


# --------------------------------------------------------------------------- #
# 一、复习域：B 全零 / 全空
# --------------------------------------------------------------------------- #
class TestReviewIsolation:
    def test_stats_zero_for_new_user(self, client, iso):
        iso.login(UID_B)
        d = client.get("/api/review/stats").json()
        assert d == {
            "active_errors": 0,
            "due_errors": 0,
            "graduated_errors": 0,
            "today_reviews": 0,
            "total_reviews": 0,
        }, f"零数据新用户复习统计必须全零：{d}"

    def test_stats_counts_own_rows_for_a(self, client, iso):
        iso.login(UID_A)
        d = client.get("/api/review/stats").json()
        assert d["active_errors"] == 1
        assert d["due_errors"] == 1
        assert d["total_reviews"] == 1

    def test_due_empty_for_new_user(self, client, iso):
        iso.login(UID_B)
        d = client.get("/api/review/due").json()
        assert d["total"] == 0 and d["items"] == [], "零数据用户到期队列必须为空（不得拿全局 KP 当新知识点）"

    def test_due_only_own_items_for_a(self, client, iso):
        iso.login(UID_A)
        d = client.get("/api/review/due").json()
        items = d["items"]
        assert items, "A 有到期调度行 + 接触过的新 KP，队列不应为空"
        for it in items:
            assert it["item_type"] in ("knowledge", "error")
            if it["item_type"] == "knowledge":
                assert it["id"] in (iso.kp1_id, iso.kp2_id)
            else:
                assert it["id"] == iso.err_id
        # kp2 只被 A 接触过（study_events）且无调度行 → 以"新"入队
        new_items = [it for it in items if it["is_new"]]
        assert any(it["id"] == iso.kp2_id for it in new_items)

    def test_progress_zero_for_new_user(self, client, iso):
        iso.login(UID_B)
        d = client.get("/api/review/progress").json()
        assert d["reviewed_count"] == 0
        assert d["due_count"] == 0
        assert d["mastered_count"] == 0
        assert d["learning_count"] == 0
        assert d["weak_count"] == 0
        assert d["unlearned_count"] == d["total_knowledge_points"]
        assert d["avg_mastery"] == 0.0
        assert d["reviews_last_7_days"] == 0
        assert d["weak_points"] == []
        assert d["weak_chapters"] == []

    def test_weak_points_and_link_stats_empty_for_new_user(self, client, iso):
        iso.login(UID_B)
        assert client.get("/api/review/weak-points").json()["items"] == []
        ls = client.get("/api/review/link-stats").json()
        assert ls["total_errors"] == 0
        assert ls["total_links"] == 0
        assert ls["coverage_rate"] == 0.0

    def test_history_empty_for_new_user(self, client, iso):
        iso.login(UID_B)
        d = client.get("/api/review/history").json()
        assert d["total"] == 0 and d["items"] == []

    def test_submit_knowledge_touches_neither_global_kp_nor_a(self, client, iso):
        db = iso.db
        before_kp = _kp_schedule_snapshot(db, iso.kp1_id)
        a_sched = (
            db.query(ReviewSchedule)
            .filter(
                ReviewSchedule.user_id == UID_A,
                ReviewSchedule.item_type == "knowledge_point",
                ReviewSchedule.item_id == iso.kp1_id,
            )
            .first()
        )
        before_a = (a_sched.repetitions, a_sched.interval_days, a_sched.ease_factor, a_sched.next_review_at)

        iso.login(UID_B)
        r = client.post(
            "/api/review/submit",
            json={
                "item_type": "knowledge",
                "item_id": iso.kp1_id,
                "result": "mastered",
            },
        )
        assert r.status_code == 200, r.text

        assert _kp_schedule_snapshot(db, iso.kp1_id) == before_kp, "B 的复习不得改写全局 KP 调度/掌握度字段"
        db.expire_all()
        a_sched = (
            db.query(ReviewSchedule)
            .filter(
                ReviewSchedule.user_id == UID_A,
                ReviewSchedule.item_type == "knowledge_point",
                ReviewSchedule.item_id == iso.kp1_id,
            )
            .first()
        )
        assert (a_sched.repetitions, a_sched.interval_days, a_sched.ease_factor, a_sched.next_review_at) == before_a
        # B 自己的调度行与留痕必须落本人名下
        b_sched = (
            db.query(ReviewSchedule)
            .filter(
                ReviewSchedule.user_id == UID_B,
                ReviewSchedule.item_type == "knowledge_point",
                ReviewSchedule.item_id == iso.kp1_id,
            )
            .first()
        )
        assert b_sched is not None
        b_rec = (
            db.query(ReviewRecord)
            .filter(
                ReviewRecord.user_id == UID_B,
                ReviewRecord.item_type == "knowledge",
                ReviewRecord.item_id == iso.kp1_id,
            )
            .first()
        )
        assert b_rec is not None

    def test_submit_others_error_404_and_untouched(self, client, iso):
        db = iso.db
        iso.login(UID_B)
        r = client.post(
            "/api/review/submit",
            json={
                "item_type": "error",
                "item_id": iso.err_id,
                "result": "mastered",
            },
        )
        assert r.status_code == 404, "他人错题按不存在处理（不泄露存在性）"
        db.expire_all()
        err = db.query(ErrorRecord).filter(ErrorRecord.id == iso.err_id).first()
        assert err.review_count == 1 and err.accuracy == 0.2


# --------------------------------------------------------------------------- #
# 二、洞察域：今日引导 / 周报 / 智能组卷
# --------------------------------------------------------------------------- #
class TestInsightIsolation:
    def test_today_due_review_zero_for_new_user(self, client, iso):
        iso.login(UID_B)
        d = client.get("/api/insight/today").json()
        assert d["due_review_count"] == 0
        review_sug = next(s for s in d["suggestions"] if s["label"] == "到期复习")
        assert review_sug["count"] == 0

    def test_weekly_report_zero_for_new_user(self, client, iso):
        iso.login(UID_B)
        d = client.get("/api/insight/weekly-report").json()
        assert d["this_week"]["answered"] == 0
        assert d["this_week"]["duration"] == 0
        assert d["this_week"]["accuracy"] is None
        assert all(day["answered"] == 0 for day in d["daily"])

    def test_weekly_report_counts_own_for_a(self, client, iso):
        iso.login(UID_A)
        d = client.get("/api/insight/weekly-report").json()
        assert d["this_week"]["answered"] >= 1
        assert d["this_week"]["duration"] >= 60

    @pytest.mark.parametrize("mode,marker", [("weak", "暂无薄弱点数据"), ("error_prone", "暂无错题数据")])
    def test_smart_paper_no_leak_for_new_user(self, client, iso, mode, marker):
        iso.login(UID_B)
        r = client.post("/api/insight/smart-paper", json={"mode": mode, "size": 3, "subject": "数学"})
        assert r.status_code == 200, r.text
        assert marker in r.json()["basis"], "B 无个人错题，组卷依据不得借用他人错题"


# --------------------------------------------------------------------------- #
# 三、模考域：场次互不可见 / KPI / 热力图
# --------------------------------------------------------------------------- #
class TestExamIsolation:
    def test_sessions_mutually_invisible(self, client, iso):
        iso.login(UID_B)
        assert client.get("/api/exam/sessions").json() == []
        iso.login(UID_A)
        ids = [s["id"] for s in client.get("/api/exam/sessions").json()]
        assert iso.sess_id in ids

    def test_detail_report_submit_404_for_non_owner(self, client, iso):
        iso.login(UID_B)
        assert client.get(f"/api/exam/sessions/{iso.sess_id}").status_code == 404
        assert client.get(f"/api/exam/sessions/{iso.sess_id}/report").status_code == 404
        r = client.post(f"/api/exam/{iso.sess_id}/submit", json={"answers": []})
        assert r.status_code == 404

    def test_profile_exam_count_isolated(self, client, iso):
        iso.login(UID_B)
        assert client.get("/api/analysis/profile").json()["overview"]["exam_count"] == 0
        iso.login(UID_A)
        assert client.get("/api/analysis/profile").json()["overview"]["exam_count"] >= 1

    def test_day_ledger_exam_filter(self, iso):
        from services.study_calendar import day_ledger

        today = local_today()
        ledger_b = day_ledger(iso.db, start_day=today, end_day=today, user_id=UID_B)
        assert all(act.exams_done == 0 for act in ledger_b.values())
        ledger_a = day_ledger(iso.db, start_day=today, end_day=today, user_id=UID_A)
        assert ledger_a[today.isoformat()].exams_done == 1


# --------------------------------------------------------------------------- #
# 四、词库域：空态 / 模板目录 / 显式导入幂等 / 归属 CRUD
# --------------------------------------------------------------------------- #
class TestWordsIsolation:
    def test_new_user_decks_empty_no_autoclone(self, client, iso):
        iso.login(UID_B)
        assert client.get("/api/words/decks").json() == []
        assert client.get("/api/words").json()["total"] == 0
        # 首访不得触发任何克隆写库
        assert iso.db.query(WordDeck).filter(WordDeck.user_id == UID_B).count() == 0
        assert iso.db.query(Word).filter(Word.user_id == UID_B).count() == 0

    def test_templates_catalog_visible(self, client, iso):
        iso.login(UID_B)
        catalog = client.get("/api/words/templates").json()
        tpl = next((t for t in catalog if t["id"] == iso.tpl_deck_id), None)
        assert tpl is not None, "模板目录应对所有登录用户可见"
        assert tpl["word_count"] == 2
        assert tpl["imported"] is False

    def test_import_idempotent_and_owned(self, client, iso):
        iso.login(UID_B, role="user")
        r1 = client.post("/api/words/decks/import", json={"template_id": iso.tpl_deck_id})
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        r2 = client.post("/api/words/decks/import", json={"template_id": iso.tpl_deck_id})
        assert r2.status_code == 200
        assert r2.json()["id"] == d1["id"], "重复导入同一模板必须幂等返回既有词库"

        db = iso.db
        db.expire_all()
        own_words = db.query(Word).filter(Word.deck_id == d1["id"]).all()
        assert len(own_words) == 2
        assert all(w.user_id == UID_B for w in own_words)
        # SM-2 调度重置为初始态
        assert all(w.status == "not_mastered" and w.reps == 0 and w.interval_days == 0 for w in own_words)
        # 模板本体不受影响
        assert db.query(Word).filter(Word.deck_id == iso.tpl_deck_id, Word.user_id == UID_TPL).count() == 2
        decks = client.get("/api/words/decks").json()
        assert [d["id"] for d in decks] == [d1["id"]]
        assert decks[0]["word_count"] == 2
        catalog = client.get("/api/words/templates").json()
        assert next(t for t in catalog if t["id"] == iso.tpl_deck_id)["imported"] is True

    def test_import_unknown_template_404(self, client, iso):
        iso.login(UID_B)
        assert client.post("/api/words/decks/import", json={"template_id": 999999}).status_code == 404

    def test_non_owner_crud_404(self, client, iso):
        iso.login(UID_B, role="user")
        deck_id = client.post("/api/words/decks/import", json={"template_id": iso.tpl_deck_id}).json()["id"]
        word_id = client.get("/api/words", params={"deck_id": deck_id}).json()["items"][0]["id"]

        iso.login(UID_A, role="user")
        assert client.put(f"/api/words/{word_id}", json={"meaning": "越权改写"}).status_code == 404
        assert client.delete(f"/api/words/{word_id}").status_code == 404
        assert client.delete(f"/api/words/decks/{deck_id}").status_code == 404
        assert (
            client.post(
                "/api/words",
                json={
                    "deck_id": deck_id,
                    "word": "isohack",
                    "meaning": "越权塞词",
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/words/batch-import",
                json={
                    "deck_id": deck_id,
                    "words": [{"word": "isohack2", "meaning": "越权批量"}],
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/words/import-text",
                json={
                    "deck_id": deck_id,
                    "text": "isohack3 越权文本",
                },
            ).status_code
            == 404
        )
        # A 的越权尝试不得改动 B 的词库
        iso.db.expire_all()
        assert iso.db.query(Word).filter(Word.deck_id == deck_id).count() == 2

    def test_personal_crud_without_admin(self, client, iso):
        iso.login(UID_B, role="user")
        r = client.post("/api/words/decks", json={"name": "隔离自建词库"})
        assert r.status_code == 200, r.text
        deck_id = r.json()["id"]
        r = client.post("/api/words", json={"deck_id": deck_id, "word": "isocrudword", "meaning": "自建词"})
        assert r.status_code == 200, r.text
        word_id = r.json()["id"]
        assert client.put(f"/api/words/{word_id}", json={"meaning": "改释义"}).status_code == 200
        assert client.delete(f"/api/words/{word_id}").status_code == 200
        assert client.delete(f"/api/words/decks/{deck_id}").status_code == 200
