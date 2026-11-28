import uuid

from scripts.datasource.import_08_engineering_catalog_pg import build_plan, college_decision
from sqlalchemy import text


def college(name, ref_type="参照校级", unit="10001"):
    return {
        "unit_code": unit,
        "school": "北京大学",
        "province": "北京",
        "college": name,
        "ref_type": ref_type,
        "source_url": "",
    }


def major(code="080900", name="电子科学与技术", degree="学术学位", subject="0809", line=2):
    return {
        "unit_code": "10001",
        "school": "北京大学",
        "province": "北京",
        "zydm": code,
        "zymc": name,
        "yjxkdm": subject,
        "yjxkmc": "电子科学与技术",
        "xwlx": degree,
        "catalog_year": "2027",
        "_line": line,
    }


def row(line, **values):
    return {**major(line=line), **values}


def test_college_gate_rejects_noise_but_keeps_valid_names():
    assert college_decision("电子科学学院", "参照校级") == ("insert", "eligible")
    assert college_decision("研招网院系设置", "研招网院系设置")[0] == "review"
    assert college_decision("第一临床医学院（第一医院）", "参照校级")[0] == "review"
    assert college_decision("001&amp;nbsp;中医学院", "参照校级")[0] == "review"
    assert college_decision("重点实验室", "参照校级")[0] == "review"


def test_catalog_plan_never_creates_schools_or_guesses_college_ownership():
    plan = build_plan(
        [college("电子科学学院"), {**college("不存在的学院"), "school": "不存在的大学"}],
        [major(), row(3, school="不存在的大学")],
        [{"id": 1, "name": "北京大学", "enabled": True, "deleted_at": None}],
        {"北京大学", "不存在的大学"},
        [],
        [],
    )
    assert plan["unmatched_schools"] == ["不存在的大学"]
    assert plan["statistics"]["colleges"] == {"insert": 1}
    assert plan["statistics"]["majors"] == {"insert": 1}
    assert plan["major_plan"][0]["decision"] == "insert"
    assert plan["major_plan"][0]["college_id"] is None


def test_catalog_plan_fills_only_empty_subject_and_preserves_existing_degree():
    existing = [
        {
            "id": 7,
            "school_id": 1,
            "code": "080900",
            "name": "电子科学与技术",
            "subject_code": None,
            "degree_type": "academic",
        }
    ]
    plan = build_plan([], [major()], [{"id": 1, "name": "北京大学"}], {"北京大学"}, [], existing)
    assert plan["major_plan"][0]["decision"] == "fill"
    assert plan["major_plan"][0]["target_ids"] == [7]
    existing[0]["subject_code"] = "0809"
    assert (
        build_plan([], [major()], [{"id": 1, "name": "北京大学"}], {"北京大学"}, [], existing)["major_plan"][0][
            "decision"
        ]
        == "skip"
    )
    existing[0]["degree_type"] = "professional"
    assert (
        build_plan([], [major()], [{"id": 1, "name": "北京大学"}], {"北京大学"}, [], existing)["major_plan"][0][
            "decision"
        ]
        == "review"
    )


def test_duplicate_degree_rows_are_not_silently_collapsed():
    plan = build_plan(
        [],
        [major(line=2), row(3, degree="专业学位")],
        [{"id": 1, "name": "北京大学"}],
        {"北京大学"},
        [],
        [],
    )
    assert plan["major_plan"][0]["decision"] == "review"
    assert plan["major_plan"][0]["source_lines"] == [2, 3]


def test_subject_code_fill_requires_unique_school_code_and_empty_target():
    existing = [
        {"id": 7, "school_id": 1, "code": "080900", "name": "历史显示名", "subject_code": None},
        {"id": 8, "school_id": 1, "code": "080900", "name": "已回填", "subject_code": "0809"},
        {"id": 9, "school_id": 2, "code": "080900", "name": "其他学校", "subject_code": None},
        {"id": 10, "school_id": 1, "code": "080900", "name": "已停用", "subject_code": None, "enabled": False},
    ]
    plan = build_plan(
        [],
        [major(line=2), row(3, zymc="目录异名")],
        [{"id": 1, "name": "北京大学"}, {"id": 2, "name": "清华大学"}],
        {"北京大学"},
        [],
        existing,
    )
    assert plan["subject_code_fill_plan"] == [
        {
            "target_id": 7,
            "school_id": 1,
            "code": "080900",
            "name": "历史显示名",
            "subject_code": "0809",
            "source_lines": [2, 3],
            "catalog_year": "2027",
            "unit_code": "10001",
            "match_method": "school_code_unique_subject",
        }
    ]
    assert plan["statistics"]["subject_code_fills"] == 1


def test_subject_code_fill_rejects_conflicting_catalog_subjects():
    existing = [{"id": 7, "school_id": 1, "code": "080900", "name": "历史显示名", "subject_code": None}]
    plan = build_plan(
        [],
        [major(line=2), row(3, zymc="目录异名", yjxkdm="0810")],
        [{"id": 1, "name": "北京大学"}],
        {"北京大学"},
        [],
        existing,
    )
    assert plan["subject_code_fill_plan"] == []
    assert plan["statistics"]["subject_code_fills"] == 0


def test_subject_code_fill_apply_is_idempotent_and_preserves_existing(db_schema):  # noqa: ARG001
    from database import engine
    from scripts.datasource.import_08_engineering_catalog_pg import apply_plan

    marker = f"catalog-fill-{uuid.uuid4().hex[:12]}"
    school_id = missing_id = preserved_id = None
    try:
        with engine.begin() as conn:
            school_id = conn.execute(
                text("INSERT INTO kaoyan_schools (name) VALUES (:name) RETURNING id"), {"name": marker}
            ).scalar_one()
            missing_id = conn.execute(
                text(
                    "INSERT INTO kaoyan_majors (school_id, code, name, subject_code) "
                    "VALUES (:school, '080900', :name, NULL) RETURNING id"
                ),
                {"school": school_id, "name": f"{marker}-missing"},
            ).scalar_one()
            preserved_id = conn.execute(
                text(
                    "INSERT INTO kaoyan_majors (school_id, code, name, subject_code) "
                    "VALUES (:school, '080900', :name, '0810') RETURNING id"
                ),
                {"school": school_id, "name": f"{marker}-preserved"},
            ).scalar_one()
        existing = [
            {
                "id": missing_id,
                "school_id": school_id,
                "code": "080900",
                "name": f"{marker}-missing",
                "subject_code": None,
            },
            {
                "id": preserved_id,
                "school_id": school_id,
                "code": "080900",
                "name": f"{marker}-preserved",
                "subject_code": "0810",
            },
        ]
        plan = build_plan(
            [],
            [major(name="目录标准名")],
            [{"id": school_id, "name": "北京大学"}],
            {"北京大学"},
            [],
            existing,
        )
        plan["college_plan"] = []
        plan["major_plan"] = []
        raw = engine.raw_connection()
        try:
            first = apply_plan(raw, plan)
            raw.commit()
            second = apply_plan(raw, plan)
            raw.commit()
        finally:
            raw.close()
        assert first["fallback_filled_subject_codes"] == 1
        assert second["fallback_filled_subject_codes"] == 0
        with engine.connect() as conn:
            values = dict(
                conn.execute(
                    text("SELECT id, subject_code FROM kaoyan_majors WHERE id IN (:missing, :preserved)"),
                    {"missing": missing_id, "preserved": preserved_id},
                ).all()
            )
        assert values == {missing_id: "0809", preserved_id: "0810"}
    finally:
        if school_id is not None:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM kaoyan_majors WHERE school_id = :school"), {"school": school_id})
                conn.execute(text("DELETE FROM kaoyan_schools WHERE id = :school"), {"school": school_id})
