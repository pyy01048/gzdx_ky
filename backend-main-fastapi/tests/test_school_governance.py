# -*- coding: utf-8 -*-
"""C 批次3 回归：地区双口径拆分 / 双一流嵌套 / 筛选端点 / tree 空章节隐藏。"""

from __future__ import annotations

import pytest

SCHOOL_PREFIX = "测试治理大学B3"


@pytest.fixture()
def seed(db_schema):
    from database import SessionLocal
    from models import KaoyanSchool

    db = SessionLocal()
    ids = {}
    try:
        rows = [
            ("甲", "贵州", "西南", "双一流"),  # B区+西南+非211双一流 → 双非+flag
            ("乙", "江苏", "A区", "211"),  # A区+华东+211 → flag
            ("丙", "北京", "华东", "985"),  # 混用列地理值 → 归一A区；985 → flag
            ("丁", "广东", "B区", "双非"),  # 错误B区 → 按省份归一A区；无flag
            ("戊", "甘肃", None, None),  # 缺region → 补B区+西北
        ]
        for _i, (suffix, prov, region, level) in enumerate(rows, start=1):
            s = KaoyanSchool(name=f"{SCHOOL_PREFIX}{suffix}", province=prov, region=region, level=level)
            db.add(s)
            db.commit()
            ids[suffix] = s.id
        yield ids
    finally:
        db.query(KaoyanSchool).filter(KaoyanSchool.name.like(f"{SCHOOL_PREFIX}%")).delete()
        db.commit()
        db.close()


class TestUnits:
    def test_region_maps(self):
        from services.kaoyan.school_governance import exam_region_of, geo_region_of

        assert exam_region_of("贵州") == "B区"
        assert exam_region_of("江苏") == "A区"
        assert exam_region_of(None) is None
        assert geo_region_of("内蒙古") == "华北"
        assert geo_region_of("广东") == "华南"
        assert geo_region_of("西藏") == "西南"

    def test_govern_idempotent(self, seed):
        from database import SessionLocal
        from models import KaoyanSchool
        from services.kaoyan.school_governance import govern_schools

        db = SessionLocal()
        try:
            st = govern_schools(db)
            assert st["level_dfc_migrated"] >= 1
            a = db.query(KaoyanSchool).get(seed["甲"])
            assert (a.exam_region, a.geo_region, a.level) == ("B区", "西南", "双非")
            assert a.is_double_first_class is True
            b = db.query(KaoyanSchool).get(seed["乙"])
            assert b.is_double_first_class is True and b.level == "211"
            c = db.query(KaoyanSchool).get(seed["丙"])
            assert c.region == "A区" and c.geo_region == "华北"
            d = db.query(KaoyanSchool).get(seed["丁"])
            assert d.exam_region == "A区" and d.is_double_first_class is False
            e = db.query(KaoyanSchool).get(seed["戊"])
            assert (e.exam_region, e.geo_region) == ("B区", "西北")
            st2 = govern_schools(db)
            assert st2["level_dfc_migrated"] == 0 and st2["region_normalized"] == 0
        finally:
            db.close()


class TestEndpoints:
    def test_school_filters_dual_region_and_nested_level(self, seed, client):
        from database import SessionLocal
        from services.kaoyan.school_governance import govern_schools

        db = SessionLocal()
        try:
            govern_schools(db)
        finally:
            db.close()
        r = client.get("/api/kaoyan/schools", params={"region": "西南", "page_size": 200})
        assert r.status_code == 200
        names = {i["name"] for i in r.json()["items"]}
        assert f"{SCHOOL_PREFIX}甲" in names
        assert f"{SCHOOL_PREFIX}乙" not in names
        r2 = client.get("/api/kaoyan/schools", params={"region": "B区", "page_size": 200})
        names2 = {i["name"] for i in r2.json()["items"]}
        assert f"{SCHOOL_PREFIX}甲" in names2 and f"{SCHOOL_PREFIX}戊" in names2
        assert f"{SCHOOL_PREFIX}丁" not in names2
        r3 = client.get("/api/kaoyan/schools", params={"level": "双一流", "page_size": 200})
        names3 = {i["name"] for i in r3.json()["items"]}
        assert {f"{SCHOOL_PREFIX}甲", f"{SCHOOL_PREFIX}乙", f"{SCHOOL_PREFIX}丙"} <= names3
        assert f"{SCHOOL_PREFIX}丁" not in names3
        item = next(i for i in r3.json()["items"] if i["name"] == f"{SCHOOL_PREFIX}甲")
        assert item["is_double_first_class"] is True
        assert item["exam_region"] == "B区" and item["geo_region"] == "西南"

    def test_tree_hides_empty_chapters(self, client, db_schema):
        r = client.get("/api/taxonomy/tree")
        assert r.status_code == 200
        tree = r.json()["tree"]
        assert any(s.get("empty_chapter_count", 0) > 0 for s in tree)
        for s in tree:
            for ch in s["chapters"]:
                assert ch["knowledge_point_count"] > 0 or ch["title"] == "未归章"
        r2 = client.get("/api/taxonomy/tree", params={"include_empty": "true"})
        assert r2.status_code == 200
        n1 = sum(len(s["chapters"]) for s in tree)
        n2 = sum(len(s["chapters"]) for s in r2.json()["tree"])
        assert n2 > n1
