from services.kaoyan.datasource_registry import (
    official_source_condition,
    resolve_evidence,
    resolve_source_type,
)
from sqlalchemy import Column, MetaData, String, Table, select


def test_evidence_classification_keeps_official_and_samples_distinct():
    assert resolve_evidence("notice:9301:p1:r0") == {
        "record_kind": "official_list",
        "source_type": "school_official",
        "verification_status": "official",
    }
    assert resolve_evidence("https://YZ.EXAMPLE.EDU.CN/admit")["verification_status"] == "official"
    assert resolve_evidence("yz.chsi.com.cn")["verification_status"] == "official"
    for source in (
        "https://agg.edu.cn.evil.test",
        "https://example.edu.cn@evil.test",
        "https://evil.test/?next=.edu.cn",
    ):
        assert resolve_evidence(source) == {
            "record_kind": "unverified",
            "source_type": "unverified",
            "verification_status": "unverified",
        }
    assert resolve_evidence("zexiaobao_2027:9201:9211:r0") == {
        "record_kind": "score_sample",
        "source_type": "aggregator",
        "verification_status": "reference",
    }
    assert resolve_evidence("unknown-source") == {
        "record_kind": "unverified",
        "source_type": "unverified",
        "verification_status": "unverified",
    }
    assert resolve_evidence(None) == resolve_evidence("unknown-source")


def test_official_risk_filter_excludes_samples_and_unknown_sources():
    from database import engine

    table = Table(
        "source_registry_test",
        MetaData(),
        Column("source", String),
        prefixes=["TEMPORARY"],
    )
    values = [
        {"source": "notice:9301:p1:r0"},
        {"source": "school_official"},
        {"source": "https://yz.example.edu.cn/admit"},
        {"source": "https://YZ.EXAMPLE.EDU.CN/admit"},
        {"source": "yz.chsi.com.cn"},
        {"source": "zexiaobao_2027:9201:9211:r0"},
        {"source": "zexiaobao:https://example.edu.cn/scores"},
        {"source": "https://agg.edu.cn.evil.test"},
        {"source": "https://example.edu.cn@evil.test"},
        {"source": "https://evil.test/?next=.edu.cn"},
        {"source": "unknown-source"},
        {"source": None},
    ]
    with engine.begin() as conn:
        table.create(conn)
        try:
            conn.execute(table.insert(), values)
            rows = conn.execute(select(table.c.source).where(official_source_condition(table.c.source))).scalars().all()
        finally:
            table.drop(conn)

    assert rows == [
        "notice:9301:p1:r0",
        "school_official",
        "https://yz.example.edu.cn/admit",
        "https://YZ.EXAMPLE.EDU.CN/admit",
        "yz.chsi.com.cn",
    ]


def test_third_party_score_source_resolves_as_aggregator():
    assert resolve_source_type("zexiaobao_2027:9201:9211:r0") == "聚合"
    assert resolve_source_type("zexiaobao:https://example.edu.cn/scores") == "聚合"
    assert resolve_source_type("notice:9301:p1:r0") == "官方"
