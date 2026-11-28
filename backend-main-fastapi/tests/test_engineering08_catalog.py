# -*- coding: utf-8 -*-
"""工科08学习空间后端契约：迁移、回填、目录 facets 与可见题库。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND_DIR / "core" / "sql" / "207_engineering08_major_subject_links.sql"
CATALOG_URL = "/api/kaoyan/engineering-08/catalog"
QUESTIONS_URL = "/api/kaoyan/engineering-08/questions"
_UID_BASE = 1_200_000_000 + int(uuid.uuid4().hex[:8], 16) % 400_000_000
UID_A = _UID_BASE
UID_B = _UID_BASE + 1


def _principal(uid: int, role: str = "user") -> SimpleNamespace:
    return SimpleNamespace(
        id=uid,
        username=f"eng08_{uid}",
        display_name=f"eng08_{uid}",
        role=role,
        is_active=True,
        must_change_password=False,
        token_version=0,
    )


def _ok(response):
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def engineering08(app_module, db_schema, client):  # noqa: ARG001
    """Isolated 08/non-08 catalog graph and A/B-owned questions."""
    from database import SessionLocal
    from utils.security import current_user, optional_user

    from models import (
        Discipline,
        KaoyanMajor,
        KaoyanMajorSubjectLink,
        KaoyanSchool,
        QuizQuestion,
        Subject,
        SubjectDisciplineLink,
        User,
    )

    db = SessionLocal()
    marker = f"ENG08-{uuid.uuid4().hex[:12]}"
    dependencies = (current_user, optional_user)
    saved = {dep: app_module.dependency_overrides.get(dep) for dep in dependencies}
    d08 = d08b = non08 = None
    school_a = school_b = None
    subject_a = subject_b = subject_non08 = None

    def login(uid: int | None, role: str = "user") -> None:
        principal = None if uid is None else _principal(uid, role)
        app_module.dependency_overrides[current_user] = lambda: principal
        app_module.dependency_overrides[optional_user] = lambda: principal

    try:
        for uid in (UID_A, UID_B):
            if db.get(User, uid) is None:
                db.add(
                    User(
                        id=uid,
                        username=f"eng08_{uid}",
                        password_hash="!disabled-eng08-test",
                        display_name=f"eng08_{uid}",
                        role="user",
                        is_active=True,
                    )
                )
        d08 = Discipline(code=f"0899{marker[-4:]}", name=f"{marker}-计算机", category="工学")
        d08b = Discipline(code=f"0898{marker[-4:]}", name=f"{marker}-光学", category="工学")
        non08 = Discipline(code=f"0799{marker[-4:]}", name=f"{marker}-理学", category="理学")
        school_a = KaoyanSchool(name=f"{marker}-school-a", province="测试省")
        school_b = KaoyanSchool(name=f"{marker}-school-b", province="测试省")
        subject_a = Subject(code=f"{marker}_a", name=f"{marker}-subject-a", category="public")
        subject_b = Subject(code=f"{marker}_b", name=f"{marker}-subject-b", category="professional")
        subject_non08 = Subject(code=f"{marker}_non08", name=f"{marker}-subject-non08", category="professional")
        db.add_all([d08, d08b, non08, school_a, school_b, subject_a, subject_b, subject_non08])
        db.flush()
        majors = [
            KaoyanMajor(
                school_id=school_a.id, code="0812", name=f"{marker}-major-1", subject_code=d08.code, exam_subjects=[]
            ),
            KaoyanMajor(
                school_id=school_a.id, code="0803", name=f"{marker}-major-2", subject_code=d08b.code, exam_subjects=[]
            ),
            KaoyanMajor(
                school_id=school_a.id,
                code="0712",
                name=f"{marker}-major-non08",
                subject_code=non08.code,
                exam_subjects=[],
            ),
            KaoyanMajor(
                school_id=school_b.id, code="0812", name=f"{marker}-major-4", subject_code=d08.code, exam_subjects=[]
            ),
        ]
        db.add_all(majors)
        db.flush()
        db.add_all(
            [
                SubjectDisciplineLink(subject_id=subject_a.id, discipline_id=d08.id),
                SubjectDisciplineLink(subject_id=subject_a.id, discipline_id=d08b.id),
                SubjectDisciplineLink(subject_id=subject_b.id, discipline_id=d08.id),
                SubjectDisciplineLink(subject_id=subject_b.id, discipline_id=d08b.id),
                SubjectDisciplineLink(subject_id=subject_a.id, discipline_id=non08.id),
                SubjectDisciplineLink(subject_id=subject_non08.id, discipline_id=non08.id),
            ]
        )
        db.add_all(
            [
                KaoyanMajorSubjectLink(
                    major_id=majors[0].id,
                    subject_id=subject_a.id,
                    exam_subject_code="201",
                    exam_subject_name="raw-a",
                    source={"i": 0},
                ),
                KaoyanMajorSubjectLink(
                    major_id=majors[0].id,
                    subject_id=subject_b.id,
                    exam_subject_code="302",
                    exam_subject_name="raw-b",
                    source={"i": 1},
                ),
                KaoyanMajorSubjectLink(
                    major_id=majors[0].id,
                    subject_id=None,
                    exam_subject_name="ambiguous",
                    match_status="ambiguous",
                    confidence=0,
                ),
                KaoyanMajorSubjectLink(
                    major_id=majors[2].id, subject_id=subject_non08.id, exam_subject_name="non08", source={"i": 0}
                ),
                KaoyanMajorSubjectLink(
                    major_id=majors[3].id, subject_id=subject_a.id, exam_subject_name="school-b", source={"i": 0}
                ),
            ]
        )
        common = {
            "options": [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
            "answer": "A",
            "analysis": f"{marker} 解析",
            "difficulty": 2,
            "source_label": "工科08契约测试",
            "source_kind": "external_import",
            "question_type": "single",
            "question_category": "习题",
            "answer_type": "objective",
            "is_available": True,
            "is_junk": False,
        }
        target_facets = {
            "year": 2025,
            "question_type": "single",
            "source_kind": "past_exam",
            "difficulty": 4,
        }
        questions = [
            QuizQuestion(
                **{**common, **target_facets},
                content=f"{marker}-public-a-1",
                subject=subject_a.name,
                subject_id=subject_a.id,
            ),
            QuizQuestion(
                **{**common, "year": 2024, "question_type": "multiple", "source_kind": "textbook", "difficulty": 2},
                content=f"{marker}-public-a-2",
                subject=subject_a.name,
                subject_id=subject_a.id,
            ),
            QuizQuestion(
                **{**common, "year": 2025, "question_type": "judge", "source_kind": "mock_exam", "difficulty": 3},
                content=f"{marker}-public-b",
                subject=subject_b.name,
                subject_id=subject_b.id,
            ),
            QuizQuestion(
                **{**common, "year": 2023, "question_type": "essay", "source_kind": "ai_generated", "difficulty": 1},
                content=f"{marker}-answerable",
                subject=subject_b.name,
                subject_id=subject_b.id,
            ),
            QuizQuestion(
                **{**common, **target_facets, "is_available": False},
                content=f"{marker}-unavailable",
                subject=subject_a.name,
                subject_id=subject_a.id,
            ),
            QuizQuestion(
                **{**common, **target_facets},
                content=f"{marker}-private-a",
                subject=subject_a.name,
                subject_id=subject_a.id,
                owner_user_id=UID_A,
            ),
            QuizQuestion(
                **{**common, **target_facets},
                content=f"{marker}-private-b",
                subject=subject_a.name,
                subject_id=subject_a.id,
                owner_user_id=UID_B,
            ),
            QuizQuestion(
                **{**common, **target_facets},
                content=f"{marker}-non08",
                subject=subject_non08.name,
                subject_id=subject_non08.id,
            ),
            QuizQuestion(
                **{**common, **target_facets, "is_junk": True},
                content=f"{marker}-junk",
                subject=subject_a.name,
                subject_id=subject_a.id,
            ),
        ]
        db.add_all(questions)
        db.commit()
        login(None)
        yield SimpleNamespace(
            api=client,
            db=db,
            marker=marker,
            login=login,
            d08=d08,
            d08b=d08b,
            non08=non08,
            school_a=school_a,
            school_b=school_b,
            major_1=majors[0],
            major_2=majors[1],
            major_non08=majors[2],
            major_4=majors[3],
            subject_a=subject_a,
            subject_b=subject_b,
            subject_non08=subject_non08,
            questions=questions,
        )
    finally:
        db.rollback()
        for dep in dependencies:
            if saved[dep] is None:
                app_module.dependency_overrides.pop(dep, None)
            else:
                app_module.dependency_overrides[dep] = saved[dep]
        try:
            db.query(QuizQuestion).filter(QuizQuestion.content.like(f"{marker}%")).delete(synchronize_session=False)
            db.query(KaoyanMajorSubjectLink).filter(
                KaoyanMajorSubjectLink.exam_subject_name.like(f"{marker}%")
                | KaoyanMajorSubjectLink.exam_subject_name.in_(["raw-a", "raw-b", "raw-b2", "non08", "school-b"])
            ).delete(synchronize_session=False)
            db.query(KaoyanMajor).filter(KaoyanMajor.name.like(f"{marker}%")).delete(synchronize_session=False)
            db.query(KaoyanSchool).filter(KaoyanSchool.name.like(f"{marker}%")).delete(synchronize_session=False)
            subject_ids = [row.id for row in (subject_a, subject_b, subject_non08) if row is not None]
            discipline_ids = [row.id for row in (d08, d08b, non08) if row is not None]
            db.query(SubjectDisciplineLink).filter(SubjectDisciplineLink.subject_id.in_(subject_ids)).delete(
                synchronize_session=False
            )
            db.query(Subject).filter(Subject.id.in_(subject_ids)).delete(synchronize_session=False)
            db.query(Discipline).filter(Discipline.id.in_(discipline_ids)).delete(synchronize_session=False)
            db.query(User).filter(User.id.in_([UID_A, UID_B])).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


def test_migration_207_is_registered_after_dependencies_and_idempotent(db_schema):  # noqa: ARG001
    from core.db_session import engine
    from core.migrations import exec_ddl, split_statements

    assert MIGRATION.is_file(), "缺少 207 工科08专业—考试科目关联迁移"
    schema = (BACKEND_DIR / "core" / "pg_schema.sql").read_text(encoding="utf-8")
    assert schema.index(r"\ir sql/060_schools.sql") < schema.index(r"\ir sql/207_engineering08_major_subject_links.sql")
    assert schema.index(r"\ir sql/010_system_config.sql") < schema.index(
        r"\ir sql/207_engineering08_major_subject_links.sql"
    )

    statements = split_statements(MIGRATION.read_text(encoding="utf-8"))
    assert statements, "207 迁移不能为空"
    for _ in range(2):
        for statement in statements:
            with engine.begin() as conn:
                exec_ddl(conn, statement)

    inspector = inspect(engine)
    assert "kaoyan_major_subject_links" in inspector.get_table_names()
    columns = {col["name"] for col in inspector.get_columns("kaoyan_major_subject_links")}
    assert {
        "id",
        "major_id",
        "subject_id",
        "exam_subject_code",
        "exam_subject_name",
        "source",
        "match_status",
        "confidence",
    } <= columns
    foreign_keys = inspector.get_foreign_keys("kaoyan_major_subject_links")
    assert {fk["referred_table"] for fk in foreign_keys} >= {"kaoyan_majors", "subjects"}
    assert all(fk.get("options", {}).get("ondelete") == "CASCADE" for fk in foreign_keys)


def test_catalog_reports_08_only_facets_with_distinct_visible_counts(engineering08):
    from models import KaoyanMajorSubjectLink

    link = engineering08.db.query(KaoyanMajorSubjectLink).filter_by(exam_subject_name="raw-a").one()
    engineering08.db.refresh(link)
    assert link.source == {"i": 0}
    data = _ok(engineering08.api.get(CATALOG_URL))

    assert [row["code"] for row in data["disciplines"]] == [
        engineering08.d08.code,
        engineering08.d08b.code,
    ]
    schools = {row["id"]: row for row in data["schools"]}
    assert set(schools) == {engineering08.school_a.id, engineering08.school_b.id}
    assert schools[engineering08.school_a.id]["question_count"] == 4
    assert schools[engineering08.school_b.id]["question_count"] == 2
    majors = {row["id"]: row for row in data["majors"]}
    assert set(majors) == {
        engineering08.major_1.id,
        engineering08.major_2.id,
        engineering08.major_4.id,
    }
    assert majors[engineering08.major_1.id]["question_count"] == 4
    assert majors[engineering08.major_2.id]["question_count"] == 0
    assert majors[engineering08.major_4.id]["question_count"] == 2
    subjects = {row["id"]: row for row in data["subjects"]}
    assert set(subjects) == {engineering08.subject_a.id, engineering08.subject_b.id}
    assert subjects[engineering08.subject_a.id]["question_count"] == 2
    assert subjects[engineering08.subject_b.id]["question_count"] == 2


def test_catalog_avoids_link_question_join_fanout(engineering08):
    from sqlalchemy import event

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    engine = engineering08.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        data = _ok(engineering08.api.get(CATALOG_URL))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert data["majors"]
    fanout_queries = [
        statement
        for statement in statements
        if "kaoyan_major_subject_links" in statement and "quiz_questions" in statement
    ]
    assert fanout_queries == []


def test_questions_intersect_facets_and_deduplicate_with_08_visibility(engineering08):
    ctx = engineering08
    public_ids = {row.id for row in ctx.questions[:4]}

    anonymous = _ok(ctx.api.get(QUESTIONS_URL))
    assert anonymous["total"] == 4
    assert {row["id"] for row in anonymous["items"]} == public_ids
    assert all(row["is_available"] is True for row in anonymous["items"])
    assert all("-non08" not in row["content"] and "-junk" not in row["content"] for row in anonymous["items"])

    ctx.login(UID_A)
    user_a = _ok(ctx.api.get(QUESTIONS_URL))
    assert user_a["total"] == 5
    assert {row["id"] for row in user_a["items"]} == public_ids | {ctx.questions[5].id}
    assert all(row["owner_user_id"] in (None, UID_A) for row in user_a["items"])

    ctx.login(UID_B)
    user_b = _ok(ctx.api.get(QUESTIONS_URL))
    assert user_b["total"] == 5
    assert {row["id"] for row in user_b["items"]} == public_ids | {ctx.questions[6].id}
    assert all(row["owner_user_id"] in (None, UID_B) for row in user_b["items"])

    ctx.login(UID_A, role="admin")
    admin = _ok(ctx.api.get(QUESTIONS_URL))
    assert admin["total"] == 6
    assert {row["id"] for row in admin["items"]} == public_ids | {
        ctx.questions[5].id,
        ctx.questions[6].id,
    }

    ctx.login(None)
    intersections = [
        (
            {
                "discipline_code": ctx.d08.code,
                "school_id": ctx.school_a.id,
                "major_id": ctx.major_1.id,
                "subject_id": ctx.subject_a.id,
            },
            {ctx.questions[0].id, ctx.questions[1].id},
        ),
        (
            {
                "discipline_code": ctx.d08.code,
                "school_id": ctx.school_b.id,
                "major_id": ctx.major_4.id,
                "subject_id": ctx.subject_a.id,
            },
            {ctx.questions[0].id, ctx.questions[1].id},
        ),
        ({"major_id": ctx.major_1.id, "subject_id": ctx.subject_b.id}, {ctx.questions[2].id, ctx.questions[3].id}),
        ({"discipline_code": ctx.d08b.code, "major_id": ctx.major_1.id}, set()),
        ({"discipline_code": ctx.d08b.code, "school_id": ctx.school_a.id, "major_id": ctx.major_2.id}, set()),
        ({"school_id": ctx.school_b.id, "subject_id": ctx.subject_b.id}, set()),
        ({"discipline_code": ctx.non08.code}, set()),
        ({"school_id": ctx.school_a.id, "major_id": ctx.major_non08.id}, set()),
        ({"subject_id": ctx.subject_non08.id}, set()),
    ]
    for params, expected in intersections:
        result = _ok(ctx.api.get(QUESTIONS_URL, params=params))
        assert result["total"] == len(expected), params
        assert {row["id"] for row in result["items"]} == expected, params
        assert len(result["items"]) == len({row["id"] for row in result["items"]}), params


def test_questions_paginate_with_stable_deduplicated_boundaries(engineering08):
    ctx = engineering08
    first = _ok(ctx.api.get(QUESTIONS_URL, params={"page": 1, "page_size": 2}))
    second = _ok(ctx.api.get(QUESTIONS_URL, params={"page": 2, "page_size": 2}))
    beyond = _ok(ctx.api.get(QUESTIONS_URL, params={"page": 3, "page_size": 2}))

    assert first["total"] == second["total"] == beyond["total"] == 4
    assert first["total_pages"] == 2
    assert [row["id"] for row in first["items"]] == [ctx.questions[0].id, ctx.questions[1].id]
    assert [row["id"] for row in second["items"]] == [ctx.questions[2].id, ctx.questions[3].id]
    assert not ({row["id"] for row in first["items"]} & {row["id"] for row in second["items"]})
    assert beyond["items"] == []
    assert ctx.api.get(QUESTIONS_URL, params={"page_size": 201}).status_code == 422


def test_questions_intersect_four_new_facets_with_stable_pagination_and_visibility(engineering08):
    from models import QuizQuestion

    ctx = engineering08
    extras = [
        QuizQuestion(
            content=f"{ctx.marker}-facet-page-{index}",
            subject=ctx.subject_a.name,
            subject_id=ctx.subject_a.id,
            options=[{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
            answer="A",
            analysis="facet",
            year=2025,
            question_type="single",
            source_kind="past_exam",
            source_label="facet",
            difficulty=4,
            question_category="习题",
            answer_type="objective",
            is_available=True,
            is_junk=False,
        )
        for index in (2, 3)
    ]
    ctx.db.add_all(extras)
    ctx.db.commit()
    params = {
        "school_id": ctx.school_a.id,
        "major_id": ctx.major_1.id,
        "subject_id": ctx.subject_a.id,
        "year": 2025,
        "question_type": "single",
        "source_kind": "past_exam",
        "difficulty": 4,
    }
    expected_public = sorted([ctx.questions[0].id, *(row.id for row in extras)])

    pages = [_ok(ctx.api.get(QUESTIONS_URL, params={**params, "page": page, "page_size": 1})) for page in (1, 2, 3)]
    assert all(page["total"] == 3 and page["total_pages"] == 3 for page in pages)
    assert [page["items"][0]["id"] for page in pages] == expected_public
    assert {row["id"] for page in pages for row in page["items"]} == set(expected_public)
    assert _ok(ctx.api.get(QUESTIONS_URL, params={**params, "year": 2024}))["items"] == []
    assert _ok(ctx.api.get(QUESTIONS_URL, params={**params, "difficulty": 2}))["items"] == []

    ctx.login(UID_A)
    user_a = _ok(ctx.api.get(QUESTIONS_URL, params=params))
    assert {row["id"] for row in user_a["items"]} == set(expected_public) | {ctx.questions[5].id}
    assert ctx.questions[6].id not in {row["id"] for row in user_a["items"]}

    ctx.login(UID_A, role="admin")
    admin = _ok(ctx.api.get(QUESTIONS_URL, params=params))
    assert {row["id"] for row in admin["items"]} == set(expected_public) | {
        ctx.questions[5].id,
        ctx.questions[6].id,
    }
    excluded = {ctx.questions[4].id, ctx.questions[7].id, ctx.questions[8].id}
    assert not (excluded & {row["id"] for row in admin["items"]})

    for invalid in ({"year": 1899}, {"year": 2101}, {"difficulty": 0}, {"difficulty": 6}):
        assert ctx.api.get(QUESTIONS_URL, params=invalid).status_code == 422


def test_legacy_orm_maps_exam_subjects_without_losing_question_ownership():
    from models import Discipline, KaoyanMajorSubjectLink, QuizQuestion, Subject

    assert QuizQuestion.__table__.name == "quiz_questions"
    assert next(iter(QuizQuestion.subject_id.property.columns[0].foreign_keys)).column.table.name == "subjects"
    assert QuizQuestion.owner_user_id.property.columns[0].nullable is True
    assert KaoyanMajorSubjectLink.__table__.name == "kaoyan_major_subject_links"
    assert (
        next(iter(KaoyanMajorSubjectLink.major_id.property.columns[0].foreign_keys)).column.table.name
        == "kaoyan_majors"
    )
    assert (
        next(iter(KaoyanMajorSubjectLink.subject_id.property.columns[0].foreign_keys)).column.table.name == "subjects"
    )
    assert Subject.__tablename__ == "subjects"
    assert Discipline.__tablename__ == "disciplines"


def test_backfill_plan_preserves_shapes_and_never_guesses_ambiguous_names():
    from scripts.data.backfill_major_subject_links import SubjectRecord, build_backfill_plan

    subjects = [
        SubjectRecord(id=1, code="english", name="英语（一）", short_name="英语", legacy_names=["英语一"]),
        SubjectRecord(id=2, code="circuit", name="电路", short_name="电路", legacy_names=[]),
        SubjectRecord(id=3, code="signal", name="信号与系统", short_name="信号", legacy_names=[]),
        SubjectRecord(id=4, code="analog", name="模拟电子技术", short_name="模电", legacy_names=[]),
    ]
    aliases = [
        ("201", 1),
        ("204", 1),
        ("通原", 1),
        ("数模电", 3),
        ("数模电", 4),
    ]
    raw_values = [
        [
            {"code": "201", "name": "历史显示名"},
            {"name": "通原"},
            {"name": "数模电"},
            {"name": "不存在的科目"},
        ],
        [{"code": "unknown-local", "name": "电路"}, "(302)数学（二）|信号与系统|(204)冲突显示名"],
        '["电路", {"label": "通原"}]',
        {"code": "unknown-local", "name": "信号与系统"},
        None,
    ]

    report = build_backfill_plan([(11, raw) for raw in raw_values], subjects, aliases)

    assert report["statistics"]["majors"] == 5
    assert set(report["statistics"]["shapes"]) >= {
        "list_of_objects",
        "list_mixed",
        "json_array_string",
        "object",
        "null",
    }
    links = report["links"]
    assert [(row["major_id"], row["subject_id"], row["match_status"]) for row in links] == [
        (11, 1, "matched"),
        (11, 1, "matched"),
        (11, None, "ambiguous"),
        (11, None, "unmatched"),
        (11, 2, "matched"),
        (11, None, "unmatched"),
        (11, 3, "matched"),
        (11, 1, "matched"),
        (11, 2, "matched"),
        (11, 1, "matched"),
        (11, 3, "matched"),
        (11, None, "unmatched"),
    ]
    by_name = {row["exam_subject_name"]: row for row in links}
    assert by_name["历史显示名"]["exam_subject_code"] == "201"
    assert by_name["历史显示名"]["match_method"] == "exam_code"
    assert by_name["冲突显示名"]["exam_subject_code"] == "204"
    assert by_name["冲突显示名"]["match_method"] == "exam_code"
    assert by_name["冲突显示名"]["source"]["raw"] == "(204)冲突显示名"
    assert by_name["通原"]["match_method"] == "alias"
    assert by_name["数模电"]["candidate_subject_ids"] == [3, 4]
    assert all(row["source"]["field"] == "exam_subjects" for row in links)
    assert all(row["source"]["raw"] is not None for row in links)
    assert {row["match_status"] for row in report["unmatched"]} == {"ambiguous", "unmatched"}
    assert len(report["unmatched"]) == 4
    assert all(row["subject_id"] is None for row in report["unmatched"])


def test_backfill_cli_defaults_to_dry_run_on_test_database(db_schema):  # noqa: ARG001
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env["PG_DATABASE"] = "kaoyan_test"
    env["DATABASE_BACKEND"] = "postgresql"
    completed = subprocess.run(
        [sys.executable, str(BACKEND_DIR / "scripts" / "data" / "backfill_major_subject_links.py")],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["dry_run"] is True
    assert report["write"] == {"attempted": False, "inserted": 0}


def test_backfill_engineering08_only_excludes_other_disciplines(db_schema):  # noqa: ARG001
    from core.db_session import engine
    from scripts.data.backfill_major_subject_links import backfill_database

    marker = f"ENG08ONLY-{uuid.uuid4().hex[:12]}"
    school_id = major08_id = major_non08_id = subject_id = None
    try:
        with engine.begin() as conn:
            school_id = conn.execute(
                text("INSERT INTO kaoyan_schools (name) VALUES (:name) RETURNING id"), {"name": f"{marker}-school"}
            ).scalar_one()
            subject_id = conn.execute(
                text("INSERT INTO subjects (code, name, category) VALUES (:code, :name, 'professional') RETURNING id"),
                {"code": marker, "name": f"{marker}-subject"},
            ).scalar_one()
            for discipline_code, category in (("0812", "工学"), ("0712", "理学")):
                conn.execute(
                    text(
                        "INSERT INTO disciplines (code, name, category) "
                        "VALUES (:code, :name, :category) "
                        "ON CONFLICT (code) DO NOTHING"
                    ),
                    {"code": discipline_code, "name": f"{marker}-{discipline_code}", "category": category},
                )
            for major_code, discipline_code in (
                ("0812", "0812"),
                ("0712", "0712"),
            ):
                inserted_major_id = conn.execute(
                    text("""
                    INSERT INTO kaoyan_majors
                        (school_id, code, name, subject_code, exam_subjects)
                    VALUES (:school, :code, :name, :discipline_code,
                            CAST(:raw AS jsonb)) RETURNING id
                """),
                    {
                        "school": school_id,
                        "code": major_code,
                        "name": f"{marker}-{major_code}",
                        "discipline_code": discipline_code,
                        "raw": json.dumps([{"code": marker, "name": f"{marker}-subject"}], ensure_ascii=False),
                    },
                ).scalar_one()
                if major_code == "0812":
                    major08_id = inserted_major_id
                else:
                    major_non08_id = inserted_major_id

        preview = backfill_database(engine, engineering08_only=True)
        planned_major_ids = {row["major_id"] for row in preview["links"]}
        assert major08_id in planned_major_ids
        assert major_non08_id not in planned_major_ids
        assert preview["statistics"]["majors"] == len(planned_major_ids)
        assert preview["write"] == {"attempted": False, "inserted": 0}

        applied = backfill_database(engine, apply=True, engineering08_only=True)
        assert applied["write"]["inserted"] >= 1
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM kaoyan_major_subject_links "
                        "WHERE major_id = :mid AND subject_id = :sid AND match_status = 'matched'"
                    ),
                    {"mid": major08_id, "sid": subject_id},
                ).scalar_one()
                == 1
            )
            assert (
                conn.execute(
                    text("SELECT count(*) FROM kaoyan_major_subject_links WHERE major_id = :mid"),
                    {"mid": major_non08_id},
                ).scalar_one()
                == 0
            )
    finally:
        with engine.begin() as conn:
            for major_id in (major08_id, major_non08_id):
                if major_id is not None:
                    conn.execute(text("DELETE FROM kaoyan_major_subject_links WHERE major_id = :id"), {"id": major_id})
                    conn.execute(text("DELETE FROM kaoyan_majors WHERE id = :id"), {"id": major_id})
            if school_id is not None:
                conn.execute(text("DELETE FROM kaoyan_schools WHERE id = :id"), {"id": school_id})
            if subject_id is not None:
                conn.execute(text("DELETE FROM subjects WHERE id = :id"), {"id": subject_id})


def test_national_exam_codes_map_to_exact_platform_subject_banks():
    from scripts.data.backfill_major_subject_links import SubjectRecord, build_backfill_plan

    subjects = [
        SubjectRecord(id=1, code="politics", name="政治"),
        SubjectRecord(id=2, code="english", name="英语"),
        SubjectRecord(id=3, code="math", name="数学"),
        SubjectRecord(id=4, code="japanese", name="日语"),
    ]
    report = build_backfill_plan(
        [
            (
                11,
                [
                    "(101)思想政治理论",
                    "(201)英语（一）",
                    "(204)英语（二）",
                    "(301)数学（一）",
                    "(302)数学（二）",
                    "(303)数学（三）",
                    "(203)日语",
                ],
            )
        ],
        subjects,
    )
    assert [(row["subject_id"], row["match_method"]) for row in report["links"]] == [
        (1, "platform_exam_subject"),
        (2, "platform_exam_subject"),
        (2, "platform_exam_subject"),
        (3, "platform_exam_subject"),
        (3, "platform_exam_subject"),
        (3, "platform_exam_subject"),
        (4, "exam_code"),
    ]
    assert report["unmatched"] == []


def test_national_exam_subject_seed_plan_is_exact_and_idempotent():
    from scripts.data.seed_national_exam_subjects import build_seed_plan

    subjects = [
        {"id": 1, "code": "existing", "name": "已有科目"},
        {"id": 2, "code": "national_exam_101", "name": "思想政治理论"},
        {"id": 3, "code": "custom_408", "name": "计算机学科专业基础408"},
    ]
    aliases = [{"alias": "408", "subject_id": 3, "is_primary": True}]
    first = build_seed_plan(subjects, aliases, ("101", "201", "204", "301", "302", "303"))
    assert [row["code"] for row in first["subjects"]] == [
        "national_exam_201",
        "national_exam_204",
        "national_exam_301",
        "national_exam_302",
        "national_exam_303",
    ]
    assert {row["subject_id"] for row in first["subjects_skipped"]} == {2}
    assert [row["alias"] for row in first["aliases"]] == ["计算机学科专业基础", "计算机专业基础综合"]
    assert first["conflicts"] == []

    seeded_subjects = subjects + [
        {"id": row["id"], "code": row["code"], "name": row["name"]} for row in first["subjects"]
    ]
    seeded_aliases = aliases + [
        {"alias": row["alias"], "subject_id": 3, "is_primary": row["is_primary"]} for row in first["aliases"]
    ]
    second = build_seed_plan(seeded_subjects, seeded_aliases, ("101", "201", "204", "301", "302", "303"))
    assert second["subjects"] == []
    assert second["aliases"] == []
    assert second["conflicts"] == []


def test_national_exam_subject_seed_apply_is_idempotent_and_preserves_ownership(db_schema):  # noqa: ARG001
    from core.db_session import engine
    from scripts.data.seed_national_exam_subjects import seed_database

    codes = ("national_exam_203",)
    try:
        with engine.connect() as conn:
            before = conn.execute(
                text(
                    "SELECT count(*), md5(coalesce(string_agg(id::text||':'||coalesce(owner_user_id::text,'null'),',' ORDER BY id),'')) FROM quiz_questions"
                )
            ).one()
        first = seed_database(engine, apply=True, exam_codes=("203",))
        assert first["write"]["inserted_subjects"] >= 1
        second = seed_database(engine, apply=True, exam_codes=("203",))
        assert second["write"]["inserted_subjects"] == 0
        with engine.connect() as conn:
            after = conn.execute(
                text(
                    "SELECT count(*), md5(coalesce(string_agg(id::text||':'||coalesce(owner_user_id::text,'null'),',' ORDER BY id),'')) FROM quiz_questions"
                )
            ).one()
            assert after == before
            assert conn.execute(
                text("SELECT count(*) FROM subjects WHERE code = ANY(:codes) AND category = 'public'"),
                {"codes": list(codes)},
            ).scalar_one() == len(codes)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM subjects WHERE code = ANY(:codes)"), {"codes": list(codes)})


def test_backfill_business_database_requires_exact_explicit_designation(db_schema):  # noqa: ARG001
    from types import SimpleNamespace

    from core.db_session import engine
    from scripts.data.backfill_major_subject_links import backfill_database

    class BusinessTargetProbe:
        url = SimpleNamespace(database="kaoyan")
        dialect = engine.dialect

        def connect(self):
            return engine.connect()

        def begin(self):
            raise AssertionError("exact designation passed the write guard")

    with pytest.raises(RuntimeError, match="Refusing to write"):
        backfill_database(BusinessTargetProbe(), apply=True)
    with pytest.raises(AssertionError, match="passed the write guard"):
        backfill_database(BusinessTargetProbe(), apply=True, database_name="kaoyan")


def test_backfill_apply_is_idempotent_and_preserves_question_ownership(db_schema):  # noqa: ARG001
    from core.db_session import engine
    from scripts.data.backfill_major_subject_links import backfill_database

    marker = f"ENG08BF-{uuid.uuid4().hex[:12]}"
    uid = 1_100_000_000 + int(uuid.uuid4().hex[:8], 16) % 500_000_000
    school_id = major_id = subject_a = subject_b = question_id = None
    try:
        with engine.begin() as conn:
            school_id = conn.execute(
                text("INSERT INTO kaoyan_schools (name) VALUES (:name) RETURNING id"), {"name": f"{marker}-school"}
            ).scalar_one()
            subject_a = conn.execute(
                text("INSERT INTO subjects (code, name, category) VALUES (:code, :name, 'professional') RETURNING id"),
                {"code": f"{marker}_a", "name": f"{marker}-A"},
            ).scalar_one()
            subject_b = conn.execute(
                text("INSERT INTO subjects (code, name, category) VALUES (:code, :name, 'professional') RETURNING id"),
                {"code": f"{marker}_b", "name": f"{marker}-B"},
            ).scalar_one()
            conn.execute(
                text("INSERT INTO subject_aliases (alias, subject_id) VALUES (:alias, :sid)"),
                [
                    {"alias": f"{marker}-ambiguous", "sid": subject_a},
                    {"alias": f"{marker}-ambiguous", "sid": subject_b},
                ],
            )
            major_id = conn.execute(
                text("""
                INSERT INTO kaoyan_majors (school_id, code, name, subject_code, exam_subjects)
                VALUES (:school, '0812', :name, '0812', CAST(:raw AS jsonb)) RETURNING id
            """),
                {
                    "school": school_id,
                    "name": f"{marker}-major",
                    "raw": '[{"code":"' + marker + '_a","name":"raw-name"},{"name":"' + marker + '-ambiguous"}]',
                },
            ).scalar_one()
            conn.execute(
                text("""
                INSERT INTO users (id, username, password_hash, display_name)
                VALUES (:uid, :username, '!disabled-eng08-test', :username)
            """),
                {"uid": uid, "username": f"eng08bf_{uid}"},
            )
            question_id = conn.execute(
                text("""
                INSERT INTO quiz_questions
                    (content, owner_user_id, subject_id, answer, subject, source_kind, question_category)
                VALUES (:content, :uid, :sid, 'A', :name, 'external_import', '习题') RETURNING id
            """),
                {"content": f"{marker}-question", "uid": uid, "sid": subject_a, "name": f"{marker}-A"},
            ).scalar_one()

        before = backfill_database(engine)
        major_plan = [row for row in before["links"] if row["major_id"] == major_id]
        assert [row["match_status"] for row in major_plan] == ["matched", "ambiguous"]
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM kaoyan_major_subject_links WHERE major_id = :mid"), {"mid": major_id}
                ).scalar_one()
                == 0
            )
            assert (
                conn.execute(
                    text("SELECT owner_user_id FROM quiz_questions WHERE id = :qid"), {"qid": question_id}
                ).scalar_one()
                == uid
            )

        # A designation must name the actual connected target, not another DB.
        with pytest.raises(RuntimeError, match="does not match"):
            backfill_database(engine, apply=True, database_name="another_test")

        first = backfill_database(engine, apply=True)
        assert first["write"]["database"] == engine.url.database
        assert first["write"]["inserted"] >= 1
        second = backfill_database(engine, apply=True)
        assert second["write"]["inserted"] == 0
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text("""
                SELECT subject_id, match_status, source FROM kaoyan_major_subject_links
                WHERE major_id = :mid
            """),
                    {"mid": major_id},
                )
                .mappings()
                .all()
            )
            assert len(rows) == 1
            assert rows[0]["subject_id"] == subject_a
            assert rows[0]["match_status"] == "matched"
            assert rows[0]["source"]["entry_index"] == 0
            assert rows[0]["source"]["major_value"][1]["name"] == f"{marker}-ambiguous"
            assert (
                conn.execute(
                    text("SELECT owner_user_id FROM quiz_questions WHERE id = :qid"), {"qid": question_id}
                ).scalar_one()
                == uid
            )
    finally:
        with engine.begin() as conn:
            if question_id is not None:
                conn.execute(text("DELETE FROM quiz_questions WHERE id = :id"), {"id": question_id})
            if major_id is not None:
                conn.execute(text("DELETE FROM kaoyan_majors WHERE id = :id"), {"id": major_id})
            if school_id is not None:
                conn.execute(text("DELETE FROM kaoyan_schools WHERE id = :id"), {"id": school_id})
            for sid in (subject_a, subject_b):
                if sid is not None:
                    conn.execute(text("DELETE FROM subjects WHERE id = :id"), {"id": sid})
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})
