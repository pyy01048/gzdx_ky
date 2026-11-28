# -*- coding: utf-8 -*-
"""学习者画像的个人数据隔离回归。"""

from __future__ import annotations

import uuid
from datetime import timedelta

from database import SessionLocal
from fastapi import Request
from services import kp_mastery, recommend_loop, review_service, taxonomy
from services.learner_profile import build_profile
from sqlalchemy import text
from utils.security import create_access_token
from utils.timeutil import local_day_window, local_today, utcnow

from models import (
    AnswerRecord,
    Document,
    ErrorKnowledgeLink,
    ErrorRecord,
    KnowledgePoint,
    QuestionKnowledgeLink,
    QuizQuestion,
    ReviewSchedule,
    SubjectConfig,
    Task,
    User,
)


def test_profile_aggregates_only_the_current_user(db_schema):  # noqa: ARG001
    base = 1_000_000_000 + int(uuid.uuid4().hex[:8], 16) % 1_000_000_000
    uid_a, uid_b = base, base + 1
    tag = f"profile-isolation-{uuid.uuid4().hex[:12]}"
    day_start = local_day_window()[1]
    now = day_start + timedelta(hours=4)
    db = SessionLocal()
    kps = []
    questions = []
    try:
        db.add_all(
            [
                User(
                    id=uid,
                    username=f"{tag}-{uid}",
                    password_hash="!disabled-profile-isolation",
                    display_name=tag,
                    role="user",
                    is_active=True,
                )
                for uid in (uid_a, uid_b)
            ]
        )
        db.flush()
        kps = [
            KnowledgePoint(name=f"{tag}-a", subject="数学", mastery=0, exam_frequency=0),
            KnowledgePoint(name=f"{tag}-b", subject="英语", mastery=0, exam_frequency=0),
            KnowledgePoint(name=f"{tag}-only-a", subject="数学", mastery=0, exam_frequency=0),
        ]
        db.add_all(kps)
        db.flush()

        questions = [QuizQuestion(content=f"{tag}-question-{i}", subject="数学", answer="A") for i in range(2)]
        db.add_all(questions)
        db.flush()
        db.add_all(
            [
                QuestionKnowledgeLink(question_id=questions[0].id, knowledge_point_id=kps[0].id),
                QuestionKnowledgeLink(question_id=questions[1].id, knowledge_point_id=kps[1].id),
            ]
        )
        db.add_all(
            [
                AnswerRecord(
                    user_id=uid_a,
                    question_id=questions[0].id,
                    subject="数学",
                    is_correct=True,
                    created_at=now,
                )
                for _ in range(5)
            ]
        )
        db.add_all(
            [
                AnswerRecord(
                    user_id=uid_b,
                    question_id=questions[0].id,
                    subject="数学",
                    is_correct=False,
                    created_at=now,
                )
                for _ in range(5)
            ]
        )
        db.add_all(
            [
                AnswerRecord(user_id=uid_a, subject="数学", is_correct=True, created_at=now),
                AnswerRecord(user_id=uid_a, subject="数学", is_correct=False, created_at=now),
                AnswerRecord(user_id=uid_a, subject="数学", is_correct=None, created_at=now),
                AnswerRecord(
                    user_id=uid_b,
                    subject="英语",
                    is_correct=True,
                    created_at=now - timedelta(days=10),
                ),
            ]
        )
        err_a = ErrorRecord(
            user_id=uid_a,
            subject="数学",
            status="active",
            next_review=now - timedelta(days=1),
        )
        err_b = ErrorRecord(user_id=uid_b, subject="英语", status="active")
        err_a_only = ErrorRecord(user_id=uid_a, subject="数学", status="active")
        err_b_done = ErrorRecord(user_id=uid_b, subject="英语", status="graduated")
        db.add_all([err_a, err_b, err_a_only, err_b_done])
        db.flush()
        db.add_all(
            [
                ErrorKnowledgeLink(error_id=err_a.id, knowledge_point_id=kps[0].id),
                ErrorKnowledgeLink(error_id=err_a_only.id, knowledge_point_id=kps[2].id),
                ErrorKnowledgeLink(error_id=err_b.id, knowledge_point_id=kps[1].id),
            ]
        )
        db.add_all(
            [
                Task(user_id=uid_a, title=tag, status="done", updated_at=now - timedelta(days=2)),
                Task(user_id=uid_b, title=tag, status="pending", updated_at=now),
            ]
        )
        db.execute(
            text(
                "INSERT INTO exam_sessions "
                "(user_id, subject, status, score, started_at, created_at) "
                "VALUES (:uid, :subject, 'submitted', :score, :now, :now)"
            ),
            [
                {"uid": uid_a, "subject": "数学", "score": 80, "now": now},
                {"uid": uid_b, "subject": "英语", "score": 40, "now": now},
            ],
        )
        db.commit()

        profile_a = build_profile(db, days=7, user_id=uid_a)
        profile_b = build_profile(db, days=7, user_id=uid_b)

        assert profile_a["overview"]["total_answers"] == 8
        assert profile_a["overview"]["graded_answers"] == 7
        assert profile_a["overview"]["pending_answers"] == 1
        assert profile_a["overview"]["overall_accuracy"] == 85.7
        assert profile_a["overview"]["error_stock"] == 2
        assert profile_a["overview"]["error_resolved"] == 0
        assert profile_a["overview"]["exam_count"] == 1
        assert profile_a["overview"]["exam_avg_score"] == 80.0
        assert profile_a["overview"]["study_days"] == 2
        assert [s["subject"] for s in profile_a["subjects"]] == ["数学"]
        assert [p["name"] for p in profile_a["weak_points"]] == [
            f"{tag}-only-a",
            f"{tag}-a",
        ]
        assert [p["mastery"] for p in profile_a["weak_points"]] == [0, 100]
        assert profile_a["review_queue"] == {
            "scheduled": 1,
            "overdue": 1,
            "due_today": 0,
            "no_schedule": 1,
        }
        today_answers = [row for row in profile_a["trend"] if row["date"] == local_today().isoformat()]
        assert len(today_answers) == 1
        assert today_answers[0]["answers"] == 8
        assert today_answers[0]["graded"] == 7
        assert today_answers[0]["pending"] == 1

        assert profile_b["overview"]["total_answers"] == 6
        assert profile_b["overview"]["graded_answers"] == 6
        assert profile_b["overview"]["pending_answers"] == 0
        assert profile_b["overview"]["overall_accuracy"] == 16.7
        assert profile_b["overview"]["error_stock"] == 1
        assert profile_b["overview"]["error_resolved"] == 1
        assert profile_b["overview"]["exam_count"] == 1
        assert profile_b["overview"]["exam_avg_score"] == 40.0
        assert profile_b["overview"]["study_days"] == 2
        assert [s["subject"] for s in profile_b["subjects"]] == ["数学", "英语"]
        assert [p["name"] for p in profile_b["weak_points"]] == [f"{tag}-b"]
        assert all(p["mastery"] == 0 for p in profile_b["weak_points"])
        assert profile_b["review_queue"] == {
            "scheduled": 0,
            "overdue": 0,
            "due_today": 0,
            "no_schedule": 1,
        }
        today_b = [row for row in profile_b["trend"] if row["date"] == local_today().isoformat()]
        assert len(today_b) == 1
        assert today_b[0]["answers"] == 5
        assert today_b[0]["errors"] == 2

        assert kp_mastery.learned_kp_ids(db, user_id=uid_a) == {kps[0].id, kps[2].id}
        assert kp_mastery.learned_kp_ids(db, user_id=uid_b) == {kps[0].id, kps[1].id}
        all_kps = db.query(KnowledgePoint.id).all()
        for profile, learned, scores in (
            (profile_a, {kps[0].id, kps[2].id}, {kps[0].id: 100}),
            (profile_b, {kps[0].id, kps[1].id}, {}),
        ):
            expected = {"total": 0, "unlearned": 0, "learning": 0, "weak": 0, "mastered": 0}
            for (kp_id,) in all_kps:
                expected["total"] += 1
                expected[kp_mastery.classify_state(scores.get(kp_id, 0), kp_id in learned)] += 1
            assert profile["knowledge_points"] == {**expected, "labels": kp_mastery.STATE_LABELS}
    finally:
        db.rollback()
        db.execute(
            text("DELETE FROM exam_sessions WHERE user_id IN (:uid_a, :uid_b)"),
            {"uid_a": uid_a, "uid_b": uid_b},
        )
        db.query(QuestionKnowledgeLink).filter(
            QuestionKnowledgeLink.question_id.in_([question.id for question in questions])
        ).delete(synchronize_session=False)
        db.query(QuizQuestion).filter(QuizQuestion.content.like(f"{tag}%")).delete(synchronize_session=False)
        db.query(ErrorKnowledgeLink).filter(ErrorKnowledgeLink.knowledge_point_id.in_([kp.id for kp in kps])).delete(
            synchronize_session=False
        )
        db.query(ErrorRecord).filter(ErrorRecord.user_id.in_([uid_a, uid_b])).delete(synchronize_session=False)
        db.query(AnswerRecord).filter(AnswerRecord.user_id.in_([uid_a, uid_b])).delete(synchronize_session=False)
        db.query(Task).filter(Task.user_id.in_([uid_a, uid_b])).delete(synchronize_session=False)
        db.query(KnowledgePoint).filter(KnowledgePoint.name.like(f"{tag}%")).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_([uid_a, uid_b])).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_analytics_http_routes_scope_logged_in_users(client, db_schema, app_module, monkeypatch):  # noqa: ARG001
    base = 1_000_000_000 + int(uuid.uuid4().hex[:8], 16) % 1_000_000_000
    uid_a, uid_b = base, base + 1
    tag = f"analytics-isolation-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    kps = []
    questions = []
    now = utcnow()
    try:
        users = [
            User(
                id=uid,
                username=f"{tag}-{uid}",
                password_hash="!disabled-analytics-isolation",
                display_name=tag,
                role="user",
                is_active=True,
            )
            for uid in (uid_a, uid_b)
        ]
        db.add_all(users)
        db.flush()
        kps = [KnowledgePoint(name=f"{tag}-kp", subject="数学", mastery=0)]
        questions = [QuizQuestion(content=f"{tag}-question", subject="数学", answer="A")]
        db.add_all([*kps, *questions])
        db.flush()
        db.add(QuestionKnowledgeLink(question_id=questions[0].id, knowledge_point_id=kps[0].id))
        db.add_all(
            [
                AnswerRecord(
                    user_id=uid_a, question_id=questions[0].id, subject="数学", is_correct=True, created_at=now
                ),
                AnswerRecord(
                    user_id=uid_a, question_id=questions[0].id, subject="数学", is_correct=False, created_at=now
                ),
                AnswerRecord(
                    user_id=uid_a, question_id=questions[0].id, subject="数学", is_correct=None, created_at=now
                ),
                AnswerRecord(user_id=uid_b, subject="数学", is_correct=True, created_at=now - timedelta(days=1)),
                AnswerRecord(user_id=uid_b, subject="数学", is_correct=True, created_at=now - timedelta(days=1)),
                Task(user_id=uid_a, title=tag, status="done", completed_at=now),
            ]
        )
        error = ErrorRecord(user_id=uid_a, subject="数学", status="active", content=tag)
        foreign_error = ErrorRecord(
            user_id=uid_b,
            subject="数学",
            status="graduated",
            content=f"{tag}-foreign",
        )
        db.add_all([error, foreign_error])
        db.flush()
        db.add(ErrorKnowledgeLink(error_id=error.id, knowledge_point_id=kps[0].id))
        db.commit()

        ai_calls = []

        async def fake_chat(self, messages):  # noqa: ARG001
            ai_calls.append(messages)
            return {"content": "测试报告"}

        monkeypatch.setattr("services.ai_service.AIService.chat", fake_chat)
        from types import SimpleNamespace

        from fastapi import HTTPException
        from routers.study.analytics import _optional_user_id
        from utils.security import current_user

        def request_user(request: Request):
            uid = _optional_user_id(request, db)
            if uid is None:
                raise HTTPException(status_code=401, detail="未登录或登录已过期")
            return SimpleNamespace(id=uid)

        monkeypatch.setitem(app_module.dependency_overrides, current_user, request_user)
        headers = {uid: {"Authorization": f"Bearer {create_access_token(db.get(User, uid))}"} for uid in (uid_a, uid_b)}

        for uid, total, accuracy, errors in ((uid_a, 3, 50.0, 1), (uid_b, 2, 100.0, 0)):
            response = client.get("/api/analytics/weak-points", headers=headers[uid])
            assert response.status_code == 200
            body = response.json()
            assert body["total_questions"] == total
            assert body["correct_rate"] == accuracy
            assert body["total_errors"] == errors
            assert [p["knowledge_point"] for p in body["weak_points"]] == ([f"{tag}-kp"] if uid == uid_a else [])

            traces = client.get("/api/analytics/traces?days=7", headers=headers[uid]).json()
            assert traces["total_questions_done"] == total
            assert traces["total_tasks_completed"] == (1 if uid == uid_a else 0)

            overview = client.get("/api/analytics/overview", headers=headers[uid]).json()
            assert overview["weekly_questions"] == total
            assert overview["total_errors"] == errors
            assert [p["knowledge_point"] for p in overview["top_weak_points"]] == (
                [f"{tag}-kp"] if uid == uid_a else []
            )

            profile_response = client.get("/api/analysis/profile?days=7", headers=headers[uid])
            assert profile_response.status_code == 200, profile_response.text
            profile = profile_response.json()
            assert profile["overview"]["total_answers"] == total

            report = client.post("/api/analytics/report", json={"report_type": "weekly"}, headers=headers[uid])
            assert report.status_code == 200
            assert report.json()["weak_point_diagnosis"]["total_questions"] == total
            assert report.json()["learning_traces"]["total_questions_done"] == total

        own_analysis = client.post(f"/api/analytics/errors/{error.id}/analyze", headers=headers[uid_a])
        assert own_analysis.status_code == 200
        assert own_analysis.json()["question"] == tag
        calls_after_own = len(ai_calls)

        for request_headers, target_id, expected_status in (
            (headers[uid_a], foreign_error.id, 404),
            (headers[uid_b], error.id, 404),
            (headers[uid_a], 0, 404),
            ({}, foreign_error.id, 401),
        ):
            response = client.post(f"/api/analytics/errors/{target_id}/analyze", headers=request_headers)
            assert response.status_code == expected_status, response.text
        assert len(ai_calls) == calls_after_own

        invalid_headers = {"Authorization": "Bearer invalid-test-token"}
        for method, path, kwargs in (
            ("GET", "/api/analytics/weak-points", {}),
            ("GET", "/api/analytics/traces", {}),
            ("GET", "/api/analytics/study-summary", {}),
            ("GET", "/api/analytics/overview", {}),
            ("POST", "/api/analytics/report", {"json": {"report_type": "weekly"}}),
        ):
            response = client.request(method, path, headers=invalid_headers, **kwargs)
            assert response.status_code == 401, f"{path}: {response.status_code} {response.text}"
        assert len(ai_calls) == calls_after_own
    finally:
        db.rollback()
        db.query(QuestionKnowledgeLink).filter(
            QuestionKnowledgeLink.question_id.in_([question.id for question in questions])
        ).delete(synchronize_session=False)
        db.query(QuizQuestion).filter(QuizQuestion.content.like(f"{tag}%")).delete(synchronize_session=False)
        db.query(ErrorKnowledgeLink).filter(ErrorKnowledgeLink.knowledge_point_id.in_([kp.id for kp in kps])).delete(
            synchronize_session=False
        )
        db.query(ErrorRecord).filter(ErrorRecord.user_id.in_([uid_a, uid_b])).delete(synchronize_session=False)
        db.query(AnswerRecord).filter(AnswerRecord.user_id.in_([uid_a, uid_b])).delete(synchronize_session=False)
        db.query(Task).filter(Task.user_id.in_([uid_a, uid_b])).delete(synchronize_session=False)
        db.query(KnowledgePoint).filter(KnowledgePoint.name.like(f"{tag}%")).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_([uid_a, uid_b])).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_personal_mastery_is_consistent_across_knowledge_routes(client, db_schema, app_module, monkeypatch):  # noqa: ARG001
    base = 1_000_000_000 + int(uuid.uuid4().hex[:8], 16) % 1_000_000_000
    uid_a, uid_b = base, base + 1
    tag = f"kp-route-isolation-{uuid.uuid4().hex[:12]}"
    subject = f"{tag}-subject"
    db = SessionLocal()
    questions = []
    kps = []
    try:
        db.add_all(
            [
                User(
                    id=uid,
                    username=f"{tag}-{uid}",
                    password_hash="!disabled-kp-route-isolation",
                    display_name=tag,
                    role="user",
                    is_active=True,
                )
                for uid in (uid_a, uid_b)
            ]
        )
        db.add(SubjectConfig(subject=subject, chapters=[tag], is_custom=True))
        document = Document(
            file_name=f"{tag}.txt",
            file_path=f"{tag}.txt",
            size=1,
            subject=subject,
            doc_type="raw",
            index_status="indexed",
        )
        db.add(document)
        db.flush()
        kps = [
            KnowledgePoint(
                name=f"{tag}-shared",
                subject=subject,
                chapter=tag,
                exam_frequency=1,
                document_id=document.id,
            ),
            KnowledgePoint(
                name=f"{tag}-pending",
                subject=subject,
                chapter=tag,
                exam_frequency=1,
                document_id=document.id,
            ),
        ]
        questions = [QuizQuestion(content=f"{tag}-question-{i}", subject=subject, answer="A") for i in range(2)]
        db.add_all([*kps, *questions])
        db.flush()
        db.add_all(
            [
                QuestionKnowledgeLink(question_id=questions[0].id, knowledge_point_id=kps[0].id),
                QuestionKnowledgeLink(question_id=questions[1].id, knowledge_point_id=kps[1].id),
            ]
        )
        db.add_all(
            [
                AnswerRecord(
                    user_id=uid_a,
                    question_id=questions[0].id,
                    subject=subject,
                    is_correct=True,
                    created_at=utcnow(),
                )
                for _ in range(5)
            ]
        )
        db.add_all(
            [
                AnswerRecord(
                    user_id=uid_b,
                    question_id=questions[0].id,
                    subject=subject,
                    is_correct=False,
                    created_at=utcnow(),
                )
                for _ in range(5)
            ]
        )
        db.add(
            AnswerRecord(
                user_id=uid_a,
                question_id=questions[1].id,
                subject=subject,
                is_correct=None,
                created_at=utcnow(),
            )
        )
        errors = [
            ErrorRecord(user_id=uid, subject=subject, status="active", content=f"{tag}-{uid}") for uid in (uid_a, uid_b)
        ]
        db.add_all(errors)
        db.flush()
        db.add_all(
            [
                ReviewSchedule(
                    user_id=uid,
                    item_type="knowledge_point",
                    item_id=kps[0].id,
                    next_review_at=utcnow() - timedelta(days=1),
                )
                for uid in (uid_a, uid_b)
            ]
        )
        db.add_all([ErrorKnowledgeLink(error_id=error.id, knowledge_point_id=kps[0].id) for error in errors])
        db.commit()
        kp_mastery.touch_mastery(db, [kp.id for kp in kps])
        db.commit()
        taxonomy.load_configured_subjects(db)
        db.refresh(kps[0])
        assert int(kps[0].mastery or 0) == 50
        assert kps[1].id not in kp_mastery.learned_kp_ids(db, user_id=uid_a)

        from utils.security import _bearer, current_user, decode_token, load_token_user, optional_user

        def request_principal(request: Request):
            token = _bearer(request)
            return load_token_user(db, decode_token(token, "access")) if token else None

        monkeypatch.setitem(app_module.dependency_overrides, current_user, request_principal)
        monkeypatch.setitem(app_module.dependency_overrides, optional_user, request_principal)
        headers = {uid: {"Authorization": f"Bearer {create_access_token(db.get(User, uid))}"} for uid in (uid_a, uid_b)}

        for uid, expected_mastery, expected_state in (
            (uid_a, 100, "mastered"),
            (uid_b, 0, "learning"),
        ):
            response = client.get(
                "/api/taxonomy/knowledge-points",
                params={"subject": subject, "chapter": tag, "page_size": 20},
                headers=headers[uid],
            )
            assert response.status_code == 200, response.text
            items = {item["name"]: item for item in response.json()["items"]}
            assert items[f"{tag}-shared"]["mastery"] == expected_mastery
            assert items[f"{tag}-shared"]["state"] == expected_state
            assert items[f"{tag}-pending"]["mastery"] == 0
            assert items[f"{tag}-pending"]["state"] == "unlearned"

            detail = client.get(f"/api/taxonomy/knowledge-points/{kps[0].id}", headers=headers[uid]).json()
            assert detail["mastery"] == expected_mastery
            assert detail["state"] == expected_state

            tree_response = client.get("/api/taxonomy/tree", params={"subject": subject}, headers=headers[uid])
            assert tree_response.status_code == 200, tree_response.text
            subject_node = next(node for node in tree_response.json()["tree"] if node["subject"] == subject)
            points = {
                point["id"]: point
                for chapter in subject_node["chapters"]
                for point in chapter.get("knowledge_points", [])
            }
            assert points[kps[0].id]["mastery"] == expected_mastery
            assert points[kps[0].id]["state"] == expected_state
            assert points[kps[1].id]["state"] == "unlearned"

            overview = review_service.progress_overview(db, subject=subject, user_id=uid)
            shared = next(point for point in overview["weak_points"] if point["id"] == kps[0].id)
            assert shared["mastery"] == expected_mastery
            assert shared["state"] == expected_state
            assert kps[1].id not in {point["id"] for point in overview["weak_points"]}

            due = review_service.due_items(db, subject=subject, user_id=uid, include_new=False, limit=20)
            due_shared = next(item for item in due if item["id"] == kps[0].id)
            assert due_shared["mastery"] == expected_mastery

            frequency = client.get(
                "/api/quiz/frequency",
                params={"dimension": "kp", "subject": subject, "limit": 20},
                headers=headers[uid],
            )
            assert frequency.status_code == 200, frequency.text
            frequency_shared = next(item for item in frequency.json()["items"] if item["name"] == f"{tag}-shared")
            assert frequency_shared["mastery"] == expected_mastery

            document_points = client.get(f"/api/documents/{document.id}/knowledge-points", headers=headers[uid])
            assert document_points.status_code == 200, document_points.text
            document_shared = next(item for item in document_points.json() if item["name"] == f"{tag}-shared")
            assert document_shared["mastery"] == expected_mastery

            weak = recommend_loop.identify_weak_points(db, user_id=uid, subject=subject, limit=20)
            weak_shared = next(item for item in weak if item["knowledge_point_id"] == kps[0].id)
            assert weak_shared["mastery"] == expected_mastery

            gate = recommend_loop.mastery_gate(db, user_id=uid, kp_id=kps[0].id)
            assert gate["mastered"] is (uid == uid_a)
            assert gate["mastery"] == expected_mastery

            error_id = errors[0 if uid == uid_a else 1].id
            linked = client.get(f"/api/errors/{error_id}/knowledge-points", headers=headers[uid]).json()["items"]
            shared_link = next(item for item in linked if item["knowledge_point_id"] == kps[0].id)
            assert shared_link["mastery"] == expected_mastery
            assert shared_link["state"] == expected_state

        low_a = client.get(
            "/api/taxonomy/knowledge-points",
            params={"subject": subject, "chapter": tag, "low_mastery": "true"},
            headers=headers[uid_a],
        ).json()
        low_b = client.get(
            "/api/taxonomy/knowledge-points",
            params={"subject": subject, "chapter": tag, "low_mastery": "true"},
            headers=headers[uid_b],
        ).json()
        assert low_a["total"] == 0
        assert [item["id"] for item in low_b["items"]] == [kps[0].id]
    finally:
        db.rollback()
        db.query(ErrorKnowledgeLink).filter(ErrorKnowledgeLink.knowledge_point_id.in_([kp.id for kp in kps])).delete(
            synchronize_session=False
        )
        db.query(ReviewSchedule).filter(
            ReviewSchedule.user_id.in_([uid_a, uid_b]),
            ReviewSchedule.item_type == "knowledge_point",
            ReviewSchedule.item_id.in_([kp.id for kp in kps]),
        ).delete(synchronize_session=False)
        db.query(ErrorRecord).filter(ErrorRecord.user_id.in_([uid_a, uid_b])).delete(synchronize_session=False)
        db.query(AnswerRecord).filter(AnswerRecord.user_id.in_([uid_a, uid_b])).delete(synchronize_session=False)
        db.query(QuestionKnowledgeLink).filter(
            QuestionKnowledgeLink.question_id.in_([question.id for question in questions])
        ).delete(synchronize_session=False)
        db.query(QuizQuestion).filter(QuizQuestion.content.like(f"{tag}%")).delete(synchronize_session=False)
        db.query(KnowledgePoint).filter(KnowledgePoint.name.like(f"{tag}%")).delete(synchronize_session=False)
        db.query(Document).filter(Document.file_name == f"{tag}.txt").delete(synchronize_session=False)
        db.query(SubjectConfig).filter(SubjectConfig.subject == subject).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_([uid_a, uid_b])).delete(synchronize_session=False)
        db.commit()
        taxonomy.load_configured_subjects(db)
        db.close()
