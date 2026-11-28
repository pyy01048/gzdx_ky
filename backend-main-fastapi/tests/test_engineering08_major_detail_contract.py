# -*- coding: utf-8 -*-
"""P1 专业详情纯函数与契约测试；不访问数据库。"""

from __future__ import annotations

from pathlib import Path

from routers.kaoyan.engineering08 import (
    _major_resource_pack,
    _serialize_matched_subjects,
    router,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND_DIR / "core" / "sql" / "210_major_subject_resources.sql"


def test_major_detail_route_contract():
    routes = {route.path: route for route in router.routes}
    assert "/api/kaoyan/majors/{major_id}" in routes
    assert "/api/kaoyan/engineering-08/majors/{major_id}" in routes
    assert "/api/kaoyan/engineering-08/catalog" in routes
    assert "/api/kaoyan/engineering-08/questions" in routes


def test_matched_subjects_are_deduplicated_without_double_counting():
    rows = [
        {
            "link_id": 1,
            "subject_id": 101,
            "subject_code": "201",
            "subject_name": "数学一",
            "short_name": "数一",
            "category": "公共课",
            "exam_subject_code": "101",
            "exam_subject_name": "数学",
            "confidence": 0.9,
            "source": {"method": "manual"},
            "question_count": 3,
        },
        {
            "link_id": 2,
            "subject_id": 101,
            "subject_code": "201",
            "subject_name": "数学一",
            "short_name": "数一",
            "category": "公共课",
            "exam_subject_code": "101-别名",
            "exam_subject_name": "数学",
            "confidence": 0.95,
            "source": {"method": "official"},
            "question_count": 3,
        },
    ]

    result = _serialize_matched_subjects(rows)

    assert len(result) == 1
    assert result[0]["question_count"] == 3
    assert result[0]["confidence"] == 0.95
    assert result[0]["exam_subject_codes"] == ["101", "101-别名"]
    assert len(result[0]["match_sources"]) == 2


def test_resource_query_keeps_public_or_current_user_private_scope():
    statements = []

    class Result:
        def scalar(self):
            return "kaoyan_major_subject_resources"

        def mappings(self):
            return self

        def all(self):
            return []

    class FakeSession:
        def execute(self, statement, params):
            statements.append((str(statement), params))
            return Result()

    pack = _major_resource_pack(FakeSession(), 11, 101, None)

    assert pack == {
        "status": "ready",
        "scope": "major_subject",
        "total": 0,
        "items": [],
    }
    sql, params = statements[-1]
    assert "r.is_public = TRUE OR" in sql
    assert "r.owner_user_id = :user_id" in sql
    assert "r.verification_status <> 'rejected'" in sql
    assert "l.match_status = 'matched'" in sql
    assert params == {"major_id": 11, "subject_id": 101, "user_id": None}


def test_210_migration_is_idempotent_and_has_provenance_controls():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS kaoyan_major_subject_resources" in sql
    assert "CREATE INDEX IF NOT EXISTS" in sql
    assert "DROP TRIGGER IF EXISTS" in sql
    assert "source JSONB NOT NULL" in sql
    assert "verification_status VARCHAR(20) NOT NULL" in sql
    assert "sort_order INTEGER NOT NULL" in sql
    assert "owner_user_id BIGINT REFERENCES users(id)" in sql
    assert "kaoyan_major_subject_resources" in sql
    assert "textbook_schools" not in sql.split("CREATE TABLE", 1)[1].split(";", 1)[0]


def test_210_migration_does_not_reference_forbidden_future_migrations():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "209_" not in sql
    assert "211_" not in sql
