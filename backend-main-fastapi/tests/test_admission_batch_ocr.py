from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from database import SessionLocal
from sqlalchemy import text

from models import KaoyanAdmission, KaoyanSchool

NOTICE_ID = 9301
SCHOOL_ID = 9301
NOTICE_URL = "https://example.edu.cn/admission/notice-9301"


@pytest.fixture
def ocr_module(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "pipeline.notice_admission_crawler",
        SimpleNamespace(fetch=lambda *args, **kwargs: b""),
    )
    from pipeline import admission_batch_ocr

    return admission_batch_ocr


@pytest.fixture
def ocr_notice(db_schema):
    db = SessionLocal()
    try:
        db.add(KaoyanSchool(id=SCHOOL_ID, name="OCR幂等测试院校"))
        db.flush()
        db.execute(
            text(
                "INSERT INTO kaoyan_notices "
                "(id, school_id, school_name, notice_type, title, publish_date, url) "
                "VALUES (:id, :school_id, :school_name, '录取', :title, "
                "'2026-01-01', :url)"
            ),
            {
                "id": NOTICE_ID,
                "school_id": SCHOOL_ID,
                "school_name": "OCR幂等测试院校",
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
            {"pattern": f"notice:{NOTICE_ID}:p%"},
        )
        db.execute(
            text("DELETE FROM kaoyan_admissions WHERE data_source = :source"),
            {"source": f"notice:{NOTICE_ID}"},
        )
        db.execute(text("DELETE FROM kaoyan_notices WHERE id = :id"), {"id": NOTICE_ID})
        db.execute(text("DELETE FROM kaoyan_schools WHERE id = :id"), {"id": SCHOOL_ID})
        db.commit()
    finally:
        db.close()


def _stub_ocr_boundaries(monkeypatch, tmp_path, ocr_module):
    monkeypatch.setattr(ocr_module, "CACHE_DIR", str(tmp_path))

    def fake_fetch(url, **kwargs):
        if url == NOTICE_URL:
            return b'<html><a href="/files/admit.pdf">\xe6\x8b\x9f\xe5\xbd\x95\xe5\x8f\x96\xe5\x90\x8d\xe5\x8d\x95</a></html>'
        return b"%PDF-1.4\n" + b"0" * 100_001

    class FakePdfDocument:
        def __init__(self, blob):
            self.blob = blob

        def __len__(self):
            return 1

        def close(self):
            pass

    monkeypatch.setattr(ocr_module, "fetch", fake_fetch)
    monkeypatch.setitem(
        sys.modules,
        "pypdfium2",
        SimpleNamespace(PdfDocument=FakePdfDocument),
    )

    from pipeline import dsocr_backend

    monkeypatch.setattr(dsocr_backend, "_load_model", lambda: (object(), None))
    monkeypatch.setattr(
        dsocr_backend,
        "ocr_pdf_admission_ds",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "page": 1,
                    "exam_no": "106110001",
                    "name": "测试考生",
                    "major": "电子信息",
                    "initial": 310.0,
                    "retest": 40.0,
                    "total": 350.0,
                }
            ]
        },
    )


def test_reprocessing_same_page_does_not_inflate_admission_totals(
    db_schema,
    ocr_notice,
    ocr_module,
    monkeypatch,
    tmp_path,
):
    _stub_ocr_boundaries(monkeypatch, tmp_path, ocr_module)
    out_html = tmp_path / "admission.html"

    assert ocr_module.run(ocr_notice, 2026, out_html=str(out_html)) == 0
    first_status = json.loads((tmp_path / f"notice-{NOTICE_ID}.status.json").read_text(encoding="utf-8"))
    first_totals = json.loads((tmp_path / f"notice-{NOTICE_ID}.totals.json").read_text(encoding="utf-8"))
    assert first_status["students_total"] == 1
    assert first_totals == [350.0]

    assert ocr_module.run(ocr_notice, 2026, out_html=str(out_html)) == 0
    second_status = json.loads((tmp_path / f"notice-{NOTICE_ID}.status.json").read_text(encoding="utf-8"))
    second_totals = json.loads((tmp_path / f"notice-{NOTICE_ID}.totals.json").read_text(encoding="utf-8"))
    assert second_status["students_total"] == 1
    assert second_totals == [350.0]
    assert out_html.read_text(encoding="utf-8").count("匿名考生") == 1

    db = SessionLocal()
    try:
        admission = db.query(KaoyanAdmission).filter(KaoyanAdmission.data_source == f"notice:{NOTICE_ID}").one()
        assert admission.admit_count == 1
        assert float(admission.admit_avg_score) == 350.0
        detail_count = db.execute(
            text("SELECT count(*) FROM kaoyan_admission_details WHERE data_source LIKE :pattern"),
            {"pattern": f"notice:{NOTICE_ID}:p%"},
        ).scalar_one()
        assert detail_count == 1
    finally:
        db.close()


def test_ocr_anonymizes_identity_in_storage_and_preview(
    db_schema,
    ocr_notice,
    ocr_module,
    monkeypatch,
    tmp_path,
):
    _stub_ocr_boundaries(monkeypatch, tmp_path, ocr_module)
    out_html = tmp_path / "anonymized.html"

    assert ocr_module.run(ocr_notice, 2026, out_html=str(out_html)) == 0

    db = SessionLocal()
    try:
        detail = db.execute(
            text("SELECT exam_no, name FROM kaoyan_admission_details WHERE data_source = :source"),
            {"source": f"notice:{NOTICE_ID}:p1:r0"},
        ).one()
        assert detail.name == "匿名考生"
        assert detail.exam_no == "***0001"
    finally:
        db.close()

    preview = out_html.read_text(encoding="utf-8")
    assert "测试考生" not in preview
    assert "106110001" not in preview
    assert "匿名考生" in preview
    assert "***0001" in preview


def test_dry_run_previews_without_persisting_admission_state(
    db_schema,
    ocr_notice,
    ocr_module,
    monkeypatch,
    tmp_path,
):
    _stub_ocr_boundaries(monkeypatch, tmp_path, ocr_module)

    assert ocr_module.run(ocr_notice, 2026, dry_run=True) == 0

    assert not (tmp_path / f"notice-{NOTICE_ID}.status.json").exists()
    assert not (tmp_path / f"notice-{NOTICE_ID}.totals.json").exists()
    db = SessionLocal()
    try:
        assert (
            db.execute(
                text("SELECT count(*) FROM kaoyan_admission_details WHERE data_source LIKE :pattern"),
                {"pattern": f"notice:{NOTICE_ID}:p%"},
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


def test_resume_reconciles_inflated_checkpoint_with_unique_details(
    db_schema,
    ocr_notice,
    ocr_module,
    monkeypatch,
    tmp_path,
):
    _stub_ocr_boundaries(monkeypatch, tmp_path, ocr_module)
    assert ocr_module.run(ocr_notice, 2026) == 0

    status_path = tmp_path / f"notice-{NOTICE_ID}.status.json"
    totals_path = tmp_path / f"notice-{NOTICE_ID}.totals.json"
    stale_status = json.loads(status_path.read_text(encoding="utf-8"))
    stale_status["students_total"] = 7
    status_path.write_text(json.dumps(stale_status), encoding="utf-8")
    totals_path.write_text(json.dumps([350.0] * 7), encoding="utf-8")

    assert ocr_module.run(ocr_notice, 2026) == 0

    assert json.loads(status_path.read_text(encoding="utf-8"))["students_total"] == 1
    assert json.loads(totals_path.read_text(encoding="utf-8")) == [350.0]
    db = SessionLocal()
    try:
        admission = db.query(KaoyanAdmission).filter(KaoyanAdmission.data_source == f"notice:{NOTICE_ID}").one()
        assert admission.admit_count == 1
        assert float(admission.admit_avg_score) == 350.0
    finally:
        db.close()
