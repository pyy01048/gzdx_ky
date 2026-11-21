# -*- coding: utf-8 -*-
"""工学学科评估 API 回归（119 分片 / routers/kaoyan/school_eval.py）。

隔离说明：全部走 conftest 改写的临时库；种子用哨兵校名/代码，
模块级先清后建（测试库跨轮持久，直接 INSERT 第二轮会 UniqueViolation）。

覆盖：
1. GET /schools 匿名 200 + 分页壳 + caveats 口径必须随响应下发；
2. 筛选（q/province/is_985/unit_type/data_status）与排序/分页/422 校验；
3. GET /schools/{id} 详情：评估按等级排序、双一流、kaoyan_schools 联动 id、404；
4. GET /disciplines 字典含 school_cnt；
5. GET /disciplines/{code}/rank：normal/joint/institute 分组不混排 + 等级排序 + 404。
"""

from __future__ import annotations

import pytest
from core.models import KaoyanSchool
from database import SessionLocal
from main import app
from sqlalchemy import text
from tests.asgi_client import ASGIClient

client = ASGIClient(app)

BASE = "/api/kaoyan/school-eval"
# 哨兵：T 前缀学科代码 + 「评估测试」校名，不与真实数据（0801-0861/329 校）冲突
DISC = "T901"
DISC2 = "T900"  # 代码序在 T901 前但等级更低（B），证明详情按等级而非代码排序
S_A, S_B, S_J, S_I = "评估测试大学A", "评估测试大学B", "评估测试联合大学", "评估测试研究院"
KY_SCHOOL_ID = 9003


def _clean(db):
    db.execute(text("DELETE FROM ky_school_double_first WHERE school_name LIKE '评估测试%'"))
    db.execute(text("DELETE FROM ky_school_discipline_eval WHERE school_name LIKE '评估测试%'"))
    db.execute(text("DELETE FROM ky_school WHERE name LIKE '评估测试%'"))
    db.execute(text("DELETE FROM ky_discipline WHERE code IN (:c, :c2)"), {"c": DISC, "c2": DISC2})
    db.query(KaoyanSchool).filter(KaoyanSchool.id == KY_SCHOOL_ID).delete(synchronize_session=False)
    db.commit()


@pytest.fixture(scope="module", autouse=True)
def _seed(db_schema):
    db = SessionLocal()
    try:
        _clean(db)
        db.execute(
            text("""INSERT INTO ky_discipline (code, name, degree_type, eval4_status, note)
                           VALUES (:c, '测试工学', 1, 1, NULL),
                                  (:c2, '测试工学二', 1, 1, NULL)"""),
            {"c": DISC, "c2": DISC2},
        )
        # A：985/211/双一流/自划线，2 个上榜学科；B：双非待核验；J：joint；I：institute
        db.execute(
            text("""INSERT INTO ky_school
            (name, province, city, school_type, unit_type, is_985, is_211,
             is_double_first, is_self_marked, eval_cnt, a_cnt, bp_cnt,
             heat_tag, industry_tags, strengths_json, data_status, intro)
            VALUES
            (:a, '北京', '北京', 2, 1, 1, 1, 1, 1, 2, 1, 2,
             '高', '["电子信息"]', '[{"code": "T901", "name": "测试工学", "grade": "A+", "double_first": true}]', 2, '哨兵A简介'),
            (:b, '甘肃', '兰州', 1, 1, 0, 0, 0, 0, 1, 0, 0,
             '低', '[]', '[]', 3, '哨兵B简介'),
            (:j, '山东', '青岛', 2, 1, 0, 1, 1, 0, 1, 0, 1,
             '中', '[]', '[]', 2, NULL),
            (:i, '北京', '北京', 13, 2, 0, 0, 0, 0, 1, 1, 1,
             '特殊', '[]', '[]', 2, NULL)"""),
            {"a": S_A, "b": S_B, "j": S_J, "i": S_I},
        )
        db.execute(
            text("""INSERT INTO ky_school_discipline_eval
            (school_name, school_code, discipline_code, grade, eval_round, eval_scope, source)
            VALUES
            (:a, '99901', :c, 'A+', 4, 'normal', 'test'),
            (:b, '99902', :c, 'B-', 4, 'normal', 'test'),
            (:j, '99903', :c, 'B+', 4, 'joint', 'test'),
            (:i, '99904', :c, 'A', 4, 'institute', 'test')"""),
            {"a": S_A, "b": S_B, "j": S_J, "i": S_I, "c": DISC},
        )
        # A 的第二个学科：代码序 T900 < T901，但等级 B < A+ → 详情必须 A+ 在前
        db.execute(
            text("""INSERT INTO ky_school_discipline_eval
            (school_name, school_code, discipline_code, grade, eval_round, eval_scope, source)
            VALUES (:a, '99901', :c2, 'B', 4, 'normal', 'test')"""),
            {"a": S_A, "c2": DISC2},
        )
        db.execute(
            text("""INSERT INTO ky_school_double_first
            (school_name, discipline_code, discipline_name, round)
            VALUES (:a, :c, '测试工学', 2)"""),
            {"a": S_A, "c": DISC},
        )
        # 站内院校库联动：同名 kaoyan_schools 行
        db.add(KaoyanSchool(id=KY_SCHOOL_ID, name=S_A, level="985", province="北京"))
        db.commit()
        yield
        _clean(db)
    finally:
        db.close()


def _school_id(name: str) -> int:
    r = client.get(f"{BASE}/schools", params={"q": name})
    assert r.status_code == 200
    items = r.json()["items"]
    hit = [x for x in items if x["name"] == name]
    assert hit, f"哨兵院校 {name} 未入库"
    return hit[0]["id"]


# --------------------------------------------------------------------------- #
# 列表                                                                        #
# --------------------------------------------------------------------------- #
def test_schools_anon_shell_and_caveats():
    r = client.get(f"{BASE}/schools")
    assert r.status_code == 200
    d = r.json()
    assert {"total", "page", "page_size", "items", "caveats"} <= set(d)
    assert d["total"] >= 4
    # 口径纪律：caveats 必须随每个响应下发（前端据此渲染免责口径）
    assert any("前70%" in c for c in d["caveats"])
    assert any("0838" in c for c in d["caveats"])


def test_schools_filters():
    d = client.get(f"{BASE}/schools", params={"q": "评估测试"}).json()
    assert d["total"] == 4
    d = client.get(f"{BASE}/schools", params={"q": "评估测试", "is_985": True}).json()
    assert [x["name"] for x in d["items"]] == [S_A]
    assert d["items"][0]["is_985"] is True and d["items"][0]["is_211"] is True
    d = client.get(f"{BASE}/schools", params={"q": "评估测试", "province": "甘肃"}).json()
    assert [x["name"] for x in d["items"]] == [S_B]
    d = client.get(f"{BASE}/schools", params={"q": "评估测试", "unit_type": 2}).json()
    assert [x["name"] for x in d["items"]] == [S_I]
    d = client.get(f"{BASE}/schools", params={"q": "评估测试", "data_status": 3}).json()
    assert [x["name"] for x in d["items"]] == [S_B]
    d = client.get(f"{BASE}/schools", params={"q": "评估测试", "is_double_first": False}).json()
    assert S_A not in [x["name"] for x in d["items"]]


def test_schools_sort_and_pagination():
    d = client.get(f"{BASE}/schools", params={"q": "评估测试", "sort": "a_cnt"}).json()
    assert d["items"][0]["name"] in (S_A, S_I)  # a_cnt=1 的两所排在最前
    assert d["items"][0]["a_cnt"] >= d["items"][-1]["a_cnt"]
    d1 = client.get(f"{BASE}/schools", params={"q": "评估测试", "sort": "name", "page": 1, "page_size": 2}).json()
    d2 = client.get(f"{BASE}/schools", params={"q": "评估测试", "sort": "name", "page": 2, "page_size": 2}).json()
    assert d1["total"] == d2["total"] == 4
    names = [x["name"] for x in d1["items"] + d2["items"]]
    assert len(set(names)) == 4  # 分页不重不漏


def test_schools_validation_422():
    assert client.get(f"{BASE}/schools", params={"sort": "DROP TABLE"}).status_code == 422
    assert client.get(f"{BASE}/schools", params={"page_size": 999}).status_code == 422
    assert client.get(f"{BASE}/schools", params={"page": 0}).status_code == 422
    assert client.get(f"{BASE}/schools", params={"unit_type": 9}).status_code == 422


# --------------------------------------------------------------------------- #
# 详情                                                                        #
# --------------------------------------------------------------------------- #
def test_school_detail_contract():
    sid = _school_id(S_A)
    r = client.get(f"{BASE}/schools/{sid}")
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == S_A
    assert d["kaoyan_school_id"] == KY_SCHOOL_ID  # 站内院校库联动
    assert d["strengths"][0]["name"] == "测试工学" and d["strengths"][0]["grade"] == "A+"
    assert d["industry_tags"] == ["电子信息"]
    grades = [e["grade"] for e in d["evals"]]
    assert grades == ["A+", "B"]  # 按等级排序，而非学科代码
    assert d["double_first_disciplines"] == [{"discipline_code": DISC, "discipline_name": "测试工学"}]
    assert d["caveats"]


def test_school_detail_unlinked_and_404():
    sid = _school_id(S_B)
    d = client.get(f"{BASE}/schools/{sid}").json()
    assert d["kaoyan_school_id"] is None
    assert d["data_status"] == 3
    assert client.get(f"{BASE}/schools/99999999").status_code == 404


# --------------------------------------------------------------------------- #
# 学科字典与榜单                                                              #
# --------------------------------------------------------------------------- #
def test_disciplines_dict():
    r = client.get(f"{BASE}/disciplines")
    assert r.status_code == 200
    items = r.json()["items"]
    hit = [x for x in items if x["code"] == DISC]
    assert hit and hit[0]["school_cnt"] == 4
    assert {"code", "name", "degree_type", "eval4_status", "school_cnt"} <= set(hit[0])


def test_discipline_rank_groups():
    r = client.get(f"{BASE}/disciplines/{DISC}/rank")
    assert r.status_code == 200
    d = r.json()
    assert d["discipline"]["code"] == DISC
    assert d["total"] == 4
    g = d["groups"]
    # 分组纪律：joint/institute 不与普通高校混排
    assert [x["school_name"] for x in g["normal"]] == [S_A, S_B]  # A+ 在 B- 前
    assert [x["school_name"] for x in g["joint"]] == [S_J]
    assert [x["school_name"] for x in g["institute"]] == [S_I]
    a = g["normal"][0]
    assert a["ky_school_id"] == _school_id(S_A)
    assert a["is_985"] is True and a["province"] == "北京"
    assert d["caveats"]


def test_discipline_rank_404():
    assert client.get(f"{BASE}/disciplines/ZZZZ/rank").status_code == 404
