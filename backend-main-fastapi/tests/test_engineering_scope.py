from __future__ import annotations

import pytest
from database import SessionLocal
from main import app
from routers.kaoyan import kaoyan
from services.major_coverage import decode_subjects
from tests.asgi_client import ASGIClient

from models import KaoyanAdmission, KaoyanAdmissionDetail, KaoyanCollege, KaoyanMajor, KaoyanSchool, KaoyanScoreLine

client = ASGIClient(app)


@pytest.fixture(scope="module", autouse=True)
def _seed_engineering_scope(db_schema):
    db = SessionLocal()
    try:
        school_ids = (9001, 9201, 9202)
        db.query(KaoyanScoreLine).filter(KaoyanScoreLine.school_id.in_(school_ids)).delete(synchronize_session=False)
        db.query(KaoyanAdmissionDetail).filter(KaoyanAdmissionDetail.school_id.in_(school_ids)).delete(
            synchronize_session=False
        )
        db.query(KaoyanAdmission).filter(KaoyanAdmission.school_id.in_(school_ids)).delete(synchronize_session=False)
        db.query(KaoyanMajor).filter(KaoyanMajor.school_id.in_(school_ids)).delete(synchronize_session=False)
        db.query(KaoyanCollege).filter(KaoyanCollege.school_id.in_(school_ids)).delete(synchronize_session=False)
        db.query(KaoyanSchool).filter(KaoyanSchool.id.in_(school_ids)).delete(synchronize_session=False)
        db.commit()

        db.add_all(
            [
                KaoyanSchool(id=9201, name="工学口径测试甲", province="广东"),
                KaoyanSchool(id=9202, name="工学口径测试乙", province="贵州"),
            ]
        )
        db.flush()
        db.add_all(
            [
                KaoyanCollege(id=9301, school_id=9201, name="电子信息学院"),
                KaoyanCollege(id=9302, school_id=9201, name="人工智能学院"),
                KaoyanCollege(id=9303, school_id=9201, name="电子科学学院"),
            ]
        )
        db.flush()
        db.add_all(
            [
                KaoyanMajor(
                    id=9211,
                    school_id=9201,
                    college_id=9301,
                    code="085400",
                    name="电子信息",
                    subject_code=None,
                    exam_subjects=[{"code": "857", "name": "电子技术基础"}],
                ),
                KaoyanMajor(
                    id=9212,
                    school_id=9201,
                    college_id=9302,
                    code="085401",
                    name="人工智能",
                    subject_code="0854",
                    exam_subjects=["电子技术基础"],
                ),
                KaoyanMajor(
                    id=9213,
                    school_id=9201,
                    college_id=9303,
                    code="080900",
                    name="电子科学与技术",
                    subject_code="0809",
                    exam_subjects=["数学分析"],
                ),
                KaoyanMajor(
                    id=9221,
                    school_id=9202,
                    code="085402",
                    name="通信工程",
                    subject_code=None,
                    exam_subjects=["电路"],
                ),
                KaoyanMajor(
                    id=9222,
                    school_id=9202,
                    code="0802Z1",
                    name="自设光学方向",
                    subject_code="0802",
                    exam_subjects=["信号与系统"],
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                KaoyanAdmission(
                    school_id=9201,
                    major_id=9211,
                    year=2025,
                    data_source="school_official",
                    enroll_count=10,
                    retest_count=20,
                    admit_count=10,
                    admit_avg_score=300,
                    major_avg_score=100,
                    retest_ratio=2.0,
                ),
                KaoyanAdmission(
                    school_id=9201,
                    major_id=9212,
                    year=2025,
                    data_source="school_official",
                    enroll_count=20,
                    retest_count=20,
                    admit_count=20,
                    admit_avg_score=400,
                    major_avg_score=120,
                    retest_ratio=1.0,
                ),
                KaoyanAdmission(
                    school_id=9201,
                    major_id=9213,
                    year=2025,
                    data_source="school_official",
                    enroll_count=1,
                    retest_count=1,
                    admit_count=1,
                    admit_avg_score=350,
                    major_avg_score=130,
                    retest_ratio=1.0,
                ),
                KaoyanAdmission(
                    school_id=9201,
                    major_id=9213,
                    year=2026,
                    data_source="school_official",
                    enroll_count=1000,
                    retest_count=1000,
                    admit_count=1000,
                    admit_avg_score=450,
                    major_avg_score=150,
                    retest_ratio=1.0,
                ),
                KaoyanAdmission(
                    school_id=9201,
                    major_id=9211,
                    year=2024,
                    data_source="school_official",
                    enroll_count=5,
                    retest_count=5,
                    admit_count=5,
                    admit_avg_score=280,
                    major_avg_score=90,
                    retest_ratio=1.0,
                ),
                KaoyanAdmission(
                    school_id=9202,
                    major_id=9222,
                    year=2025,
                    data_source="school_official",
                    enroll_count=5,
                    retest_count=5,
                    admit_count=5,
                    admit_avg_score=200,
                    major_avg_score=80,
                    retest_ratio=1.0,
                ),
                KaoyanAdmission(
                    school_id=9202,
                    major_id=9221,
                    year=2024,
                    data_source="school_official",
                    enroll_count=2,
                    retest_count=2,
                    admit_count=2,
                    admit_avg_score=360,
                    major_avg_score=115,
                    retest_ratio=1.0,
                ),
                KaoyanScoreLine(school_id=9201, major_id=9213, year=2025, total_line=250, national_line=260),
                KaoyanScoreLine(school_id=9201, major_id=9211, year=2025, total_line=340, national_line=300),
                KaoyanScoreLine(school_id=9201, major_id=9212, year=2025, total_line=350, national_line=300),
                KaoyanScoreLine(school_id=9202, major_id=9222, year=2025, total_line=260, national_line=250),
                KaoyanScoreLine(school_id=9202, major_id=9221, year=2025, total_line=300, national_line=290),
                KaoyanScoreLine(school_id=9202, major_id=None, major_code="085403", year=2025, total_line=310),
                KaoyanScoreLine(school_id=9202, major_id=9221, year=2024, total_line=280),
            ]
        )
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture(autouse=True)
def _clear_schools_cache():
    kaoyan._SCHOOLS_LIST_CACHE.clear()
    yield
    kaoyan._SCHOOLS_LIST_CACHE.clear()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("080900", ("08", "0809", "080900")),
        ("085400", ("08", "0854", "085400")),
        ("0802Z1", ("08", "0802", "0802Z1")),
        (" 085401 ", ("08", "0854", "085401")),
        ("08", ("08", None, None)),
        ("bad", (None, None, None)),
    ],
)
def test_code_parts_are_derived_from_authoritative_major_code(raw, expected):
    from services.kaoyan.engineering_codes import derive_code_parts

    assert derive_code_parts(raw) == expected


def test_school_filter_uses_code_prefix_even_when_subject_code_is_null():
    response = client.get("/api/kaoyan/schools", params={"subject_code": "08", "page_size": 200})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {row["id"] for row in body["items"]} == {9201, 9202}


def test_major_aggregate_is_scoped_weighted_and_same_year():
    response = client.get("/api/kaoyan/schools", params={"subject_code": "0854", "page_size": 200})

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["items"]}
    assert set(rows) == {9201, 9202}
    first = rows[9201]
    assert first["metric_scope"] == "major"
    assert first["subject_code"] == "0854"
    assert first["major_count"] == 1
    assert first["direction_count"] == 2
    assert first["college_count"] == 2
    assert first["year"] == 2025
    assert first["enroll_count"] == 30
    assert first["retest_count"] == 40
    assert first["admit_count"] == 30
    assert first["admit_avg_score"] == 366.7
    assert first["major_avg_score"] == 113.3
    assert first["retest_ratio"] == 1.33

    second = rows[9202]
    assert second["year"] == 2025
    assert second["metric_scope"] == "major"
    assert second["college_count"] == 0
    assert second["enroll_count"] is None
    assert second["retest_count"] is None
    assert second["admit_count"] is None
    assert second["admit_avg_score"] is None
    assert second["major_avg_score"] is None
    assert second["retest_ratio"] is None


def test_third_party_samples_do_not_change_official_risk_metrics():
    db = SessionLocal()
    db.add(KaoyanMajor(id=9214, school_id=9201, code="085404", name="第三方样本测试专业"))
    db.flush()
    sample = KaoyanAdmission(
        school_id=9201,
        major_id=9214,
        year=2025,
        data_source="zexiaobao_2027:9201:9214:r0",
        enroll_count=1000,
        retest_count=1000,
        admit_count=1000,
        admit_avg_score=999,
        retest_ratio=99,
    )
    db.add(sample)
    db.commit()
    sample_id = sample.id
    try:
        response = client.get("/api/kaoyan/schools", params={"subject_code": "0854", "page_size": 200})
        assert response.status_code == 200
        row = next(item for item in response.json()["items"] if item["id"] == 9201)
        assert row["enroll_count"] == 30
        assert row["admit_count"] == 30
        assert row["admit_avg_score"] == 366.7
        assert row["retest_ratio"] == 1.33
        recommendation = client.get(
            "/api/kaoyan/analysis/recommend",
            params={"score": 350, "subject_code": "0854", "year": 2025},
        )
        assert recommendation.status_code == 200
        recommended = next(item for item in recommendation.json()["recommendations"] if item["school_id"] == 9201)
        assert recommended["admission_evidence"]["sources"] == [
            {
                "data_source": "school_official",
                "record_kind": "official_list",
                "source_type": "school_official",
                "verification_status": "official",
            }
        ]

        admissions = client.get("/api/kaoyan/schools/9201/admissions", params={"subject_code": "0854"})
        assert admissions.status_code == 200
        labeled = next(item for item in admissions.json() if item["data_source"] == sample.data_source)
        assert labeled["record_kind"] == "score_sample"
        assert labeled["source_type"] == "aggregator"
        assert labeled["verification_status"] == "reference"
    finally:
        db.query(KaoyanAdmission).filter(KaoyanAdmission.id == sample_id).delete()
        db.query(KaoyanMajor).filter(KaoyanMajor.id == 9214).delete()
        db.commit()
        db.close()


def test_descending_metric_sort_key_puts_real_zero_before_missing():
    rows = [{"value": None}, {"value": 0}, {"value": 5}, {"value": -2}]

    rows.sort(key=lambda row: kaoyan._descending_metric_sort_key(row["value"]))

    assert [row["value"] for row in rows] == [5, 0, -2, None]


def test_major_aggregate_tolerates_one_missing_headcount():
    db = SessionLocal()
    admission = (
        db.query(KaoyanAdmission)
        .filter(
            KaoyanAdmission.major_id == 9211,
            KaoyanAdmission.year == 2025,
        )
        .one()
    )
    original_enroll = admission.enroll_count
    admission.enroll_count = None
    db.commit()
    try:
        response = client.get("/api/kaoyan/schools", params={"subject_code": "0854", "page_size": 200})
        assert response.status_code == 200
        row = next(item for item in response.json()["items"] if item["id"] == 9201)
        assert row["enroll_count"] is None
        assert row["admit_count"] == 30
        assert row["heat"] == 30
    finally:
        admission.enroll_count = original_enroll
        db.commit()
        db.close()


def test_major_aggregate_missing_weight_does_not_bias_average():
    db = SessionLocal()
    admission = (
        db.query(KaoyanAdmission)
        .filter(
            KaoyanAdmission.major_id == 9212,
            KaoyanAdmission.year == 2025,
        )
        .one()
    )
    original_count = admission.admit_count
    admission.admit_count = None
    db.commit()
    try:
        response = client.get("/api/kaoyan/schools", params={"subject_code": "0854", "page_size": 200})
        assert response.status_code == 200
        row = next(item for item in response.json()["items"] if item["id"] == 9201)
        assert row["admit_count"] is None
        assert row["admit_avg_score"] == 300
        assert row["retest_ratio"] is None
    finally:
        admission.admit_count = original_count
        db.commit()
        db.close()


def test_explicit_year_is_respected_for_major_aggregate():
    response = client.get(
        "/api/kaoyan/schools",
        params={"subject_code": "0854", "year": 2024, "page_size": 200},
    )

    rows = {row["id"]: row for row in response.json()["items"]}
    assert rows[9201]["year"] == 2024
    assert rows[9201]["admit_count"] == 5
    assert rows[9202]["year"] == 2024
    assert rows[9202]["admit_count"] == 2
    assert rows[9202]["admit_avg_score"] == 360


def test_school_majors_filter_and_expose_code_parts():
    response = client.get("/api/kaoyan/schools/9201/majors", params={"subject_code": "0854"})

    assert response.status_code == 200
    body = response.json()
    assert [item["code"] for item in body] == ["085400", "085401"]
    assert body[0]["category_code"] == "08"
    assert body[0]["major_code"] == "0854"
    assert body[0]["direction_code"] == "085400"


def test_full_direction_code_is_matched_exactly_and_ignores_conflicting_subject_code():
    db = SessionLocal()
    major = db.query(KaoyanMajor).filter(KaoyanMajor.id == 9211).one()
    original_subject_code = major.subject_code
    major.subject_code = "0809"
    db.commit()
    try:
        response = client.get("/api/kaoyan/schools", params={"subject_code": "085400", "page_size": 200})
        assert response.status_code == 200
        rows = response.json()["items"]
        assert [row["id"] for row in rows] == [9201]
        assert rows[0]["major_count"] == 1
        assert rows[0]["direction_count"] == 1
        assert rows[0]["admit_count"] == 10
    finally:
        major.subject_code = original_subject_code
        db.commit()
        db.close()


def test_recommendation_does_not_mix_other_major_scores_or_admissions():
    response = client.get(
        "/api/kaoyan/analysis/recommend",
        params={"score": 350, "subject_code": "0854", "year": 2025},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metric_scope"] == "major"
    assert body["subject_code"] == "0854"
    rows = {row["school_id"]: row for row in body["recommendations"]}
    assert set(rows) == {9201, 9202}
    assert rows[9201]["total_line"] == 340
    assert rows[9201]["admit_avg_score"] == 366.7
    assert rows[9201]["retest_ratio"] == 1.33
    assert rows[9202]["total_line"] == 300
    assert rows[9202]["admit_avg_score"] is None
    assert rows[9202]["retest_ratio"] is None
    assert all(row["score_breakdown"]["subject"] == 10.0 for row in rows.values())
    assert rows[9201]["admission_evidence"]["sources"] == [
        {
            "data_source": "school_official",
            "record_kind": "official_list",
            "source_type": "school_official",
            "verification_status": "official",
        }
    ]
    assert rows[9202]["admission_evidence"]["sources"] == []
    assert rows[9201]["scoreline_evidence"]["sources"] == [
        {
            "data_source": None,
            "record_kind": "unverified",
            "source_type": "unverified",
            "verification_status": "unverified",
        }
    ]


def test_recommendation_keeps_all_scorelines_from_one_evidence_record():
    db = SessionLocal()
    lowest = (
        db.query(KaoyanScoreLine)
        .filter(
            KaoyanScoreLine.school_id == 9202,
            KaoyanScoreLine.major_id == 9221,
            KaoyanScoreLine.year == 2025,
        )
        .one()
    )
    original = (lowest.retest_line, lowest.national_line, lowest.source)
    lowest.retest_line = None
    lowest.national_line = None
    lowest.source = None
    db.add(
        KaoyanScoreLine(
            school_id=9202,
            major_id=9221,
            year=2025,
            line_type="direction",
            total_line=310,
            retest_line=330,
            national_line=300,
            source="notice:9202:9221:direction",
        )
    )
    db.commit()
    try:
        response = client.get(
            "/api/kaoyan/analysis/recommend",
            params={"score": 350, "subject_code": "0854", "year": 2025},
        )
        assert response.status_code == 200
        row = next(item for item in response.json()["recommendations"] if item["school_id"] == 9202)
        assert row["total_line"] == 300
        assert row["retest_line"] is None
        assert row["national_line"] is None
        assert row["scoreline_evidence"]["sources"] == [
            {
                "data_source": None,
                "record_kind": "unverified",
                "source_type": "unverified",
                "verification_status": "unverified",
            }
        ]
    finally:
        lowest.retest_line, lowest.national_line, lowest.source = original
        db.query(KaoyanScoreLine).filter(
            KaoyanScoreLine.school_id == 9202,
            KaoyanScoreLine.major_id == 9221,
            KaoyanScoreLine.year == 2025,
            KaoyanScoreLine.line_type == "direction",
        ).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_recommendation_uses_latest_matching_major_year_and_scoped_coverage():
    response = client.get(
        "/api/kaoyan/analysis/recommend",
        params={"score": 350, "subject_code": "0854"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2025
    assert body["available_years"] == [2025, 2024]
    rows = {row["school_id"]: row for row in body["recommendations"]}
    assert rows[9201]["kb_coverage"]["majors"] == 2
    assert rows[9202]["kb_coverage"]["majors"] == 1


def test_recommendation_does_not_reward_missing_admission_metrics():
    response = client.get(
        "/api/kaoyan/analysis/recommend",
        params={"score": 350, "subject_code": "0854", "year": 2025},
    )

    assert response.status_code == 200
    row = next(item for item in response.json()["recommendations"] if item["school_id"] == 9202)
    assert row["retest_ratio"] is None
    assert row["admit_avg_score"] is None
    assert row["score_breakdown"]["retest_ratio"] == 0
    assert row["score_breakdown"]["admit_avg"] == 0
    assert row["score"] == 35


def test_compare_0854_uses_same_year_and_matching_major_facts_only():
    response = client.get(
        "/api/kaoyan/analysis/compare",
        params={"school_ids": "9201,9202", "subject_code": "0854", "year": 2025},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["subject_code"] == "0854"
    assert body["year"] == 2025
    assert body["metric_scope"] == "major"
    rows = {row["id"]: row for row in body["items"]}
    assert rows[9201]["recent_scores"] == [{"year": 2025, "total_line": 340, "retest_line": None}]
    assert rows[9201]["recent_admissions"] == [
        {
            "year": 2025,
            "enroll_count": 30,
            "admit_count": 30,
            "admit_avg_score": 366.7,
        }
    ]
    assert rows[9202]["recent_scores"] == [{"year": 2025, "total_line": 300, "retest_line": None}]
    assert rows[9202]["recent_admissions"] == []


def test_auto_adjust_0854_uses_authoritative_code_prefix_only():
    response = client.post(
        "/api/kaoyan/analysis/auto-adjust",
        json={"user_score": 360, "subject_code": "0854"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metric_scope"] == "major"
    assert body["subject_code"] == "0854"
    assert body["year_window"] == [2024, 2025]
    rows = {row["school_id"]: row for bucket in body["buckets"].values() for row in bucket}
    assert set(rows) == {9201, 9202}, body
    assert rows[9201]["avg3"] == 354.3
    assert rows[9201]["years_used"] == 2
    assert rows[9202]["avg3"] == 360
    assert rows[9202]["years_used"] == 1
    assert any("2025总分线 340" in reason for reason in rows[9201]["reasons"])
    assert any("2025总分线 300" in reason for reason in rows[9202]["reasons"])


def test_school_detail_does_not_fill_missing_headcounts_or_use_unit_weights():
    from services.kaoyan.score_insight import school_score_detail

    db = SessionLocal()
    admission = (
        db.query(KaoyanAdmission)
        .filter(
            KaoyanAdmission.major_id == 9212,
            KaoyanAdmission.year == 2025,
        )
        .one()
    )
    original_count = admission.admit_count
    original_enroll = admission.enroll_count
    admission.admit_count = None
    admission.enroll_count = None
    db.commit()
    try:
        detail = school_score_detail(db, 9201)
        row = next(item for item in detail["admissions_detail"] if item["year"] == 2025)
        assert row["admit_count"] is None
        assert row["enroll_count"] is None
        assert row["admit_avg_score"] == 304.5
        assert row["retest_ratio"] is None
    finally:
        admission.admit_count = original_count
        admission.enroll_count = original_enroll
        db.commit()
        db.close()


def test_auto_adjust_skips_scores_without_admission_weight():
    db = SessionLocal()
    admission = (
        db.query(KaoyanAdmission)
        .filter(
            KaoyanAdmission.major_id == 9212,
            KaoyanAdmission.year == 2025,
        )
        .one()
    )
    original_count = admission.admit_count
    admission.admit_count = None
    db.commit()
    try:
        response = client.post(
            "/api/kaoyan/analysis/auto-adjust",
            json={"user_score": 330, "subject_code": "0854"},
        )
        assert response.status_code == 200
        row = next(
            item for bucket in response.json()["buckets"].values() for item in bucket if item["school_id"] == 9201
        )
        assert row["avg3"] == 293.3
    finally:
        admission.admit_count = original_count
        db.commit()
        db.close()


def test_auto_adjust_separates_score_position_from_evidence_confidence():
    response = client.post(
        "/api/kaoyan/analysis/auto-adjust",
        json={"user_score": 360, "subject_code": "0854"},
    )

    assert response.status_code == 200
    body = response.json()
    row = next(item for bucket in body["buckets"].values() for item in bucket if item["school_id"] == 9201)
    assert "confidence" not in row
    assert row["retest_ratio"] == 1.29
    assert any("复录比约 1.29" in reason for reason in row["reasons"])
    assert 0 < row["score_position"] < 1
    assert row["position"]
    assert 0 < row["evidence_confidence"] <= 1
    assert "非录取概率" in body["method"]


def test_analysis_dashboard_uses_latest_year_and_weighted_entity_aggregates():
    db = SessionLocal()
    db.query(KaoyanAdmission).filter(KaoyanAdmission.major_id == 9299).delete(synchronize_session=False)
    db.query(KaoyanMajor).filter(KaoyanMajor.id == 9299).delete(synchronize_session=False)
    extra_major = KaoyanMajor(
        id=9299,
        school_id=9202,
        code="085400",
        name="电子信息",
        subject_code="0854",
    )
    db.add(extra_major)
    db.flush()
    db.add(
        KaoyanAdmission(
            school_id=9202,
            major_id=9299,
            year=2025,
            data_source="school_official",
            enroll_count=90,
            retest_count=90,
            admit_count=90,
            admit_avg_score=100,
            major_avg_score=80,
            retest_ratio=1.0,
        )
    )
    original = (
        db.query(KaoyanAdmission)
        .filter(
            KaoyanAdmission.major_id == 9211,
            KaoyanAdmission.year == 2025,
        )
        .one()
    )
    original_enroll = original.enroll_count
    db.commit()
    try:
        latest = client.get("/api/kaoyan/analysis/dashboard")
        assert latest.status_code == 200
        assert latest.json()["year"] == 2026
        electronic_science = next(row for row in latest.json()["major_comparison"] if row["major_code"] == "080900")
        assert electronic_science["admit_avg"] == 450

        response = client.get("/api/kaoyan/analysis/dashboard", params={"year": 2025})
        assert response.status_code == 200
        body = response.json()
        electronic_info = next(row for row in body["major_comparison"] if row["major_code"] == "085400")
        assert electronic_info["enroll_count"] == 100
        assert electronic_info["admit_avg"] == 120
        assert electronic_info["major_avg"] == 82
        assert electronic_info["retest_ratio"] == 1.1
        assert (
            next(row for row in body["college_enroll"] if row["college"] == "电子信息学院")["school_name"]
            == "工学口径测试甲"
        )

        original.enroll_count = None
        db.commit()
        kaoyan._SCHOOLS_LIST_CACHE.clear()
        response = client.get("/api/kaoyan/analysis/dashboard", params={"year": 2025})
        electronic_info = next(row for row in response.json()["major_comparison"] if row["major_code"] == "085400")
        assert electronic_info["enroll_count"] is None
    finally:
        original.enroll_count = original_enroll
        db.query(KaoyanAdmission).filter(KaoyanAdmission.major_id == 9299).delete(synchronize_session=False)
        db.query(KaoyanMajor).filter(KaoyanMajor.id == 9299).delete(synchronize_session=False)
        db.commit()
        db.close()
        kaoyan._SCHOOLS_LIST_CACHE.clear()


def test_object_exam_subjects_are_decoded_as_names():
    raw = [
        {"code": "204", "name": "英语（二）"},
        {"code": "857", "name": "电子技术基础"},
    ]

    assert decode_subjects(raw) == ["英语", "电子技术基础"]


def test_unknown_national_line_category_is_not_assumed_to_be_engineering():
    from services.kaoyan.engineering_codes import line_category_for_code

    assert line_category_for_code("9999") is None


def test_interdisciplinary_codes_use_cross_discipline_national_line():
    from services.kaoyan.engineering_codes import get_national_line, line_category_for_code

    assert line_category_for_code("140100") == "交叉学科"
    assert line_category_for_code("140500") == "交叉学科"
    assert get_national_line(2026, "交叉学科") == (266, 36, 54)
    assert get_national_line(2022, "交叉学科") is None


def test_school_detail_scope_and_coverage_labels_preserve_missing_values():
    response = client.get("/api/kaoyan/schools/9201", params={"subject_code": "0854"})

    assert response.status_code == 200
    body = response.json()
    assert body["metric_scope"] == "major"
    assert body["subject_code"] == "0854"
    assert body["major_count"] == 1
    assert body["direction_count"] == 2
    assert body["college_count"] == 2
    assert body["admit_count"] == 30
    majors = next(item for item in body["coverage_items"] if item["key"] == "majors")
    admissions = next(item for item in body["coverage_items"] if item["key"] == "admissions")
    assert majors["detail"] == "1 个专业 · 2 个方向"
    assert admissions["detail"] == "拟录取 30 人"

    db = SessionLocal()
    admission = (
        db.query(KaoyanAdmission)
        .filter(
            KaoyanAdmission.major_id == 9212,
            KaoyanAdmission.year == 2025,
        )
        .one()
    )
    original_count = admission.admit_count
    admission.admit_count = None
    db.commit()
    try:
        response = client.get("/api/kaoyan/schools/9201", params={"subject_code": "0854"})
        assert response.status_code == 200
        admissions = next(item for item in response.json()["coverage_items"] if item["key"] == "admissions")
        assert response.json()["admit_count"] is None
        assert admissions["detail"] == "暂无拟录取数据"
        assert admissions["ok"] is False
    finally:
        admission.admit_count = original_count
        db.commit()
        db.close()


def test_score_detail_counts_authoritative_major_codes_and_filters_scope():
    response = client.get("/api/kaoyan/analysis/score-detail/9201")
    assert response.status_code == 200
    row = next(item for item in response.json()["years_detail"] if item["year"] == 2025)
    assert row["major_count"] == 2

    response = client.get("/api/kaoyan/analysis/score-detail/9201", params={"subject_code": "0854"})
    assert response.status_code == 200
    body = response.json()
    assert body["metric_scope"] == "major"
    assert body["subject_code"] == "0854"
    row = next(item for item in body["years_detail"] if item["year"] == 2025)
    assert row["major_count"] == 1
    assert {item["year"] for item in body["admissions_detail"]} == {2024, 2025}
    assert next(item for item in body["admissions_detail"] if item["year"] == 2025)["admit_count"] == 30


def test_school_score_admission_and_plan_endpoints_filter_to_major_scope():
    scores = client.get("/api/kaoyan/schools/9201/scores", params={"subject_code": "0854"}).json()
    assert {row["major_code"] for row in scores} == {"085400", "085401"}

    admissions = client.get("/api/kaoyan/schools/9201/admissions", params={"subject_code": "0854"}).json()
    assert {row["major_code"] for row in admissions} == {"085400", "085401"}
    assert {row["year"] for row in admissions} == {2024, 2025}

    plan = client.get("/api/kaoyan/schools/9201/enrollment-plan", params={"subject_code": "0854"}).json()
    assert plan["metric_scope"] == "major"
    assert plan["year"] == 2025
    assert {row["major_code"] for row in plan["items"]} == {"085400", "085401"}


def test_school_admission_details_filter_to_major_scope():
    db = SessionLocal()
    admissions = {
        major_id: db.query(KaoyanAdmission)
        .filter(
            KaoyanAdmission.major_id == major_id,
            KaoyanAdmission.year == 2025,
        )
        .one()
        for major_id in (9211, 9213)
    }
    db.add_all(
        [
            KaoyanAdmissionDetail(
                admission_id=admissions[9211].id,
                school_id=9201,
                year=2025,
                name="0854考生",
                score_total=350,
                data_source="scope-test-0854",
            ),
            KaoyanAdmissionDetail(
                admission_id=admissions[9213].id,
                school_id=9201,
                year=2025,
                name="0809考生",
                score_total=400,
                data_source="scope-test-0809",
            ),
        ]
    )
    db.commit()
    try:
        rows = client.get("/api/kaoyan/schools/9201/admissions/details", params={"subject_code": "0854"}).json()
        assert [row["major_name"] for row in rows] == ["电子信息"]
    finally:
        db.query(KaoyanAdmissionDetail).filter(
            KaoyanAdmissionDetail.data_source.in_(["scope-test-0854", "scope-test-0809"])
        ).delete(synchronize_session=False)
        db.commit()
        db.close()
