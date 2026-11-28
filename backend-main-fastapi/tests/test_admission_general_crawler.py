from __future__ import annotations

from pathlib import Path

import pytest
from database import SessionLocal
from pipeline import notice_admission_crawler
from sqlalchemy import text

from models import KaoyanSchool

NOTICE_ID = 9302
SCHOOL_ID = 9302
NOTICE_URL = "https://example.edu.cn/admission/notice-9302"
NOTICE_HTML = """
<html><body><table>
<tr><th>考生编号</th><th>姓名</th><th>专业</th><th>初试成绩</th><th>总成绩</th></tr>
<tr><td>106110002</td><td>测试考生乙</td><td>电子信息</td><td>310</td><td>350</td></tr>
</table></body></html>
""".encode()


@pytest.fixture
def general_module(monkeypatch, tmp_path):
    from pipeline import admission_general_crawler

    monkeypatch.setattr(notice_admission_crawler, "fetch", lambda *args, **kwargs: NOTICE_HTML)
    monkeypatch.setattr(admission_general_crawler, "fetch", lambda *args, **kwargs: NOTICE_HTML)
    monkeypatch.setattr(admission_general_crawler, "polite", lambda: None)
    monkeypatch.setattr(admission_general_crawler, "REPORT_DIR", str(tmp_path))
    return admission_general_crawler


@pytest.fixture
def general_notice(db_schema):
    db = SessionLocal()
    try:
        db.add(KaoyanSchool(id=SCHOOL_ID, name="通用采集隐私测试院校"))
        db.flush()
        db.execute(
            text(
                "INSERT INTO kaoyan_notices "
                "(id, school_id, school_name, notice_type, title, publish_date, url) "
                "VALUES (:id, :school_id, :school_name, '录取', :title, '2026-01-01', :url)"
            ),
            {
                "id": NOTICE_ID,
                "school_id": SCHOOL_ID,
                "school_name": "通用采集隐私测试院校",
                "title": "2026年硕士研究生拟录取名单",
                "url": NOTICE_URL,
            },
        )
        db.commit()
    finally:
        db.close()

    yield NOTICE_ID

    db = SessionLocal()
    try:
        db.execute(
            text("DELETE FROM kaoyan_admission_details WHERE data_source LIKE :pattern"),
            {
                "pattern": f"notice:{NOTICE_ID}:d%",
            },
        )
        db.execute(
            text("DELETE FROM kaoyan_admissions WHERE data_source = :source"),
            {
                "source": f"notice:{NOTICE_ID}",
            },
        )
        db.execute(text("DELETE FROM kaoyan_notices WHERE id = :id"), {"id": NOTICE_ID})
        db.execute(text("DELETE FROM kaoyan_schools WHERE id = :id"), {"id": SCHOOL_ID})
        db.commit()
    finally:
        db.close()


def test_general_crawler_counts_only_new_anonymous_details(general_notice, general_module):
    db = SessionLocal()
    try:
        db.execute(
            text(
                "INSERT INTO kaoyan_admission_details "
                "(school_id, year, exam_no, name, major_name, score_total, data_source) "
                "VALUES (:school_id, 2026, '***0002', '匿名考生', '电子信息', 350, :source)"
            ),
            {"school_id": SCHOOL_ID, "source": f"notice:{NOTICE_ID}:d0"},
        )
        db.commit()
    finally:
        db.close()

    report = general_module.run(limit=10, schools=["通用采集隐私测试院校"])

    assert report["got_data"] == 1
    assert report["details"] == 0
    db = SessionLocal()
    try:
        detail = db.execute(
            text("SELECT exam_no, name FROM kaoyan_admission_details WHERE data_source = :source"),
            {"source": f"notice:{NOTICE_ID}:d0"},
        ).one()
        assert detail.name == "匿名考生"
        assert detail.exam_no == "***0002"
    finally:
        db.close()


def test_general_crawler_anonymizes_new_details(general_notice, general_module):
    report = general_module.run(limit=10, schools=["通用采集隐私测试院校"])

    assert report["details"] == 1
    db = SessionLocal()
    try:
        detail = db.execute(
            text("SELECT exam_no, name FROM kaoyan_admission_details WHERE data_source = :source"),
            {"source": f"notice:{NOTICE_ID}:d0"},
        ).one()
        assert detail.name == "匿名考生"
        assert detail.exam_no == "***0002"
    finally:
        db.close()


def test_general_crawler_dry_run_writes_no_report_or_business_state(general_notice, general_module, tmp_path):
    report = general_module.run(limit=10, schools=["通用采集隐私测试院校"], dry_run=True)

    assert report["got_data"] == 1
    assert list(tmp_path.glob("general_run_*.json")) == []
    db = SessionLocal()
    try:
        assert (
            db.execute(
                text("SELECT count(*) FROM kaoyan_admission_details WHERE data_source LIKE :pattern"),
                {"pattern": f"notice:{NOTICE_ID}:d%"},
            ).scalar_one()
            == 0
        )
        assert (
            db.execute(
                text("SELECT count(*) FROM kaoyan_admissions WHERE data_source = :source"),
                {"source": f"notice:{NOTICE_ID}"},
            ).scalar_one()
            == 0
        )
    finally:
        db.close()


def test_existing_official_details_migration_is_scoped_and_idempotent(general_notice):
    migration = (
        Path(__file__).resolve().parents[1] / "core" / "sql" / "212_admission_details_anonymize.sql"
    ).read_text(encoding="utf-8")
    db = SessionLocal()
    official_source = f"notice:{NOTICE_ID}:legacy"
    sample_source = "zexiaobao_2027:legacy"
    try:
        db.execute(
            text(
                "INSERT INTO kaoyan_admission_details "
                "(school_id, year, exam_no, name, major_name, score_total, data_source) VALUES "
                "(:school_id, 2026, '106110003', '存量测试考生', '电子信息', 350, :official), "
                "(:school_id, 2026, '106110004', '第三方样本考生', '电子信息', 360, :sample), "
                "(:school_id, 2026, NULL, '存量空考号考生', '电子信息', 370, :empty)"
            ),
            {
                "school_id": SCHOOL_ID,
                "official": official_source,
                "sample": sample_source,
                "empty": f"notice:{NOTICE_ID}:empty",
            },
        )
        db.commit()

        db.execute(text(migration))
        db.execute(text(migration))

        rows = db.execute(
            text(
                "SELECT data_source, exam_no, name FROM kaoyan_admission_details "
                "WHERE data_source IN (:official, :sample, :empty) ORDER BY data_source"
            ),
            {"official": official_source, "sample": sample_source, "empty": f"notice:{NOTICE_ID}:empty"},
        ).all()
        assert rows == [
            (f"notice:{NOTICE_ID}:empty", None, "匿名考生"),
            (official_source, "***0003", "匿名考生"),
            (sample_source, "106110004", "第三方样本考生"),
        ]
    finally:
        db.rollback()
        db.execute(
            text("DELETE FROM kaoyan_admission_details WHERE data_source IN (:official, :sample, :empty)"),
            {"official": official_source, "sample": sample_source, "empty": f"notice:{NOTICE_ID}:empty"},
        )
        db.commit()
        db.close()
