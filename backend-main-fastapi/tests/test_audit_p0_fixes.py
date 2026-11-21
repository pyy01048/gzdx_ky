# -*- coding: utf-8 -*-
"""2026-11-21 实测审计 P0 修复回归测试。

覆盖三处代码级 P0：
  * P0-1 匿名接口泄露个人掌握进度 → taxonomy 三端点字段级隔离 + B4 按用户隔离；
  * P0-2 改考记录分页被截断       → /api/kaoyan/reforms 真分页（page/page_size/offset）；
  * P0-5 考情大盘字典 repr 当标签 → _parse_exam_subjects 解析 dict-repr + 名称归一。

红线：只连 conftest 隔离出的测试库（kaoyan_test / 临时 SQLite），不碰生产库。
"""

from __future__ import annotations

import pytest

# --------------------------------------------------------------------------- #
# 纯函数层：科目解析 / 归一 / 个人字段剥离（不依赖数据库）
# --------------------------------------------------------------------------- #
from routers.kaoyan.kaoyan import (
    _canonical_exam_subject_name,
    _parse_exam_subjects,
)
from routers.knowledge.taxonomy import _strip_personal
from sqlalchemy import text


class TestExamSubjectParsing:
    def test_dict_repr_segment_parsed_not_used_as_label(self):
        raw = "{'code': '201', 'name': '英语（一）'} | (204)英语（二）"
        got = _parse_exam_subjects(raw)
        assert got == [
            {"code": "201", "name": "英语（一）"},
            {"code": "204", "name": "英语（二）"},
        ]
        # 绝不允许字典 repr 残留在 name 里
        assert all("{" not in item["name"] for item in got)

    def test_json_object_segment_in_list(self):
        got = _parse_exam_subjects([{"code": "201", "name": "英语（一）"}])
        assert got == [{"code": "201", "name": "英语（一）"}]

    def test_legacy_format_still_works(self):
        got = _parse_exam_subjects("(302)数学（二）|（101）思想政治理论")
        assert {"code": "302", "name": "数学（二）"} in got
        assert {"code": "101", "name": "思想政治理论"} in got

    @pytest.mark.parametrize(
        "raw_name,expected",
        [
            ("英语(一)", "英语（一）"),
            ("英语（一） 或 (202)俄语 或 (203)日语", "英语（一）"),
            ("英语（一）或", "英语（一）"),
            ("英（一）/俄语/日语", "英语（一）"),
            ("数学（二）", "数学（二）"),
        ],
    )
    def test_canonical_name_variants(self, raw_name, expected):
        assert _canonical_exam_subject_name(raw_name) == expected

    def test_variants_merge_into_single_label(self):
        raw = "英语(一)|英语（一） 或 (202)俄语|英（一）/俄语/日语|英语（一）或"
        got = _parse_exam_subjects(raw)
        assert got == [{"code": None, "name": "英语（一）"}]


class TestStripPersonal:
    def test_recursive_strip_keeps_public_fields(self):
        node = {
            "tree": [
                {
                    "subject": "数学",
                    "mastered_count": 2,
                    "weak_count": 0,
                    "avg_mastery": 1.2,
                    "learned_avg_mastery": 1.2,
                    "knowledge_point_count": 3,
                    "chapters": [
                        {
                            "title": "第一章",
                            "avg_mastery": 0.5,
                            "knowledge_points": [
                                {
                                    "id": 1,
                                    "name": "随机事件",
                                    "mastery": 100,
                                    "state": "mastered",
                                    "review_count": 3,
                                    "last_review": "2026-11-20T00:00:00",
                                    "next_review": "2026-11-25T00:00:00",
                                    "difficulty": 2,
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        out = _strip_personal(node)
        kp = out["tree"][0]["chapters"][0]["knowledge_points"][0]
        assert kp == {"id": 1, "name": "随机事件", "difficulty": 2}
        subj = out["tree"][0]
        assert "mastered_count" not in subj
        assert "avg_mastery" not in subj
        assert subj["knowledge_point_count"] == 3  # 公共目录字段保留

    def test_strip_is_idempotent_and_non_destructive(self):
        node = {"mastery": 1, "name": "x"}
        out = _strip_personal(node)
        assert out == {"name": "x"}
        assert node == {"mastery": 1, "name": "x"}  # 不修改入参


# --------------------------------------------------------------------------- #
# 接口层：匿名隔离 / 登录态保留 / 改考分页（依赖隔离测试库）
# --------------------------------------------------------------------------- #
_PERSONAL_KEYS = {
    "mastery",
    "state",
    "review_count",
    "last_review",
    "next_review",
    "interval",
    "ease_factor",
    "lapses",
    "mastered_count",
    "weak_count",
    "avg_mastery",
    "learned_avg_mastery",
}


def _assert_no_personal_keys(node, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            assert k not in _PERSONAL_KEYS, f"匿名响应泄露个人字段 {path}.{k}"
            _assert_no_personal_keys(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _assert_no_personal_keys(v, f"{path}[{i}]")


class TestTaxonomyAnonymousIsolation:
    @pytest.fixture(autouse=True)
    def anon(self, app_module):
        """conftest 默认把 optional_user bypass 成登录态；本类显式还原匿名。

        teardown 必须**恢复原 override** 而非 pop：session 级 auth_bypass
        的登录态假设要被后续测试文件继续继承（pop 会污染全局）。
        """
        from utils.security import optional_user

        prev = app_module.dependency_overrides.get(optional_user)
        app_module.dependency_overrides[optional_user] = lambda: None
        yield
        if prev is None:
            app_module.dependency_overrides.pop(optional_user, None)
        else:
            app_module.dependency_overrides[optional_user] = prev

    def test_tree_anonymous_has_no_personal_fields(self, client, sample_data):
        r = client.get("/api/taxonomy/tree")
        assert r.status_code == 200
        _assert_no_personal_keys(r.json())

    def test_knowledge_points_anonymous_has_no_personal_fields(self, client, sample_data):
        r = client.get("/api/taxonomy/knowledge-points")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        _assert_no_personal_keys(body)

    def test_kp_detail_anonymous_has_no_personal_data(self, client, sample_data):
        kp_id = sample_data["kp_id"]
        r = client.get(f"/api/taxonomy/knowledge-points/{kp_id}")
        assert r.status_code == 200
        body = r.json()
        _assert_no_personal_keys(body)
        assert body["related_errors"] == []
        assert body["review_history"] == []
        # 公共目录字段仍在
        assert body["id"] == kp_id
        assert "name" in body

    def test_low_mastery_anonymous_returns_empty(self, client, sample_data):
        r = client.get("/api/taxonomy/knowledge-points", params={"low_mastery": "true"})
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_logged_in_keeps_personal_fields(self, client, sample_data, app_module):
        from utils.security import optional_user, stub_principal

        prev = app_module.dependency_overrides.get(optional_user)
        app_module.dependency_overrides[optional_user] = lambda: stub_principal()
        try:
            r = client.get("/api/taxonomy/knowledge-points")
            assert r.status_code == 200
            items = r.json()["items"]
            assert items, "登录态应能看到知识点"
            assert "mastery" in items[0]
            assert "state" in items[0]
        finally:
            if prev is None:
                app_module.dependency_overrides.pop(optional_user, None)
            else:
                app_module.dependency_overrides[optional_user] = prev


class TestLearnedKpUserIsolation:
    """B4：学习流水按 user_id 隔离，匿名/他人进度不串号。"""

    def test_learned_kp_ids_scoped_per_user(self, db_schema, sample_data):
        from database import SessionLocal
        from models import KnowledgePoint, User
        from services import kp_mastery

        db = SessionLocal()
        uid_b = 990002
        try:
            if db.query(User).filter(User.id == uid_b).first() is None:
                db.add(
                    User(
                        id=uid_b,
                        username="qa_p0_iso",
                        password_hash="!disabled",
                        display_name="qa_p0_iso",
                        role="user",
                        is_active=True,
                        must_change_password=False,
                        token_version=0,
                    )
                )
            kps = []
            for nm in ("QA-P0-隔离KP1", "QA-P0-隔离KP2"):
                kp = KnowledgePoint(
                    name=nm,
                    subject="数学",
                    chapter="QA-章节",
                    mastery=0,
                    exam_frequency=1,
                    difficulty=2,
                    question_count=0,
                )
                db.add(kp)
                db.flush()
                kps.append(kp)
            assert len(kps) == 2
            kp_a, kp_b = kps[0].id, kps[1].id
            db.execute(
                text(
                    "INSERT INTO review_records (item_type, item_id, user_id, grade) "
                    "VALUES ('knowledge', :a, 0, 3), ('knowledge', :b, :uid, 3)"
                ),
                {"a": kp_a, "b": kp_b, "uid": uid_b},
            )
            db.commit()

            learned_a = kp_mastery.learned_kp_ids(db, user_id=0)
            learned_b = kp_mastery.learned_kp_ids(db, user_id=uid_b)
            assert kp_a in learned_a
            assert kp_b not in learned_a, "用户0 不应看到用户B 的学习流水"
            assert kp_b in learned_b
            assert kp_a not in learned_b, "用户B 不应看到用户0 的学习流水"
        finally:
            db.rollback()
            db.execute(
                text(
                    "DELETE FROM review_records WHERE user_id IN (0, :uid) "
                    "AND item_type = 'knowledge' AND item_id IN (:a, :b)"
                ),
                {"uid": uid_b, "a": kp_a, "b": kp_b},
            )
            db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid_b})
            db.execute(text("DELETE FROM knowledge_points WHERE name IN ('QA-P0-隔离KP1', 'QA-P0-隔离KP2')"))
            db.commit()
            db.close()


class TestReformsPagination:
    """P0-2：page/page_size 真分页，total 之外的情报不再不可达。"""

    SCHOOL_ID = 990001

    @pytest.fixture()
    def reform_rows(self, db_schema):
        from database import SessionLocal
        from services.kaoyan import reform_detector

        db = SessionLocal()
        try:
            reform_detector.ensure_reforms_schema(db)
            db.execute(text("DELETE FROM kaoyan_reforms WHERE school_id = :sid"), {"sid": self.SCHOOL_ID})
            for i in range(150):
                db.execute(
                    text(
                        "INSERT INTO kaoyan_reforms "
                        "(school_id, school_name, title, year, change_type, confidence, source) "
                        "VALUES (:sid, 'QA分页院校', :title, 2026, '考试科目调整', 0.8, 'qa')"
                    ),
                    {"sid": self.SCHOOL_ID, "title": f"QA分页事件{i:03d}"},
                )
            db.commit()
            yield
        finally:
            db.rollback()
            db.execute(text("DELETE FROM kaoyan_reforms WHERE school_id = :sid"), {"sid": self.SCHOOL_ID})
            db.commit()
            db.close()

    def test_service_offset_pagination(self, db_schema, reform_rows):
        from database import SessionLocal
        from services.kaoyan import reform_detector

        db = SessionLocal()
        try:
            page1 = reform_detector.list_reforms(db, school_id=self.SCHOOL_ID, limit=100, offset=0)
            page2 = reform_detector.list_reforms(db, school_id=self.SCHOOL_ID, limit=100, offset=100)
            assert len(page1) == 100
            assert len(page2) == 50, "第 2 页应取回剩余 50 条（此前被硬截断丢失）"
            ids1 = {r["id"] for r in page1}
            ids2 = {r["id"] for r in page2}
            assert not (ids1 & ids2), "两页不得重叠"
            assert len(ids1 | ids2) == 150
        finally:
            db.close()

    def test_api_page_params_honored(self, client, reform_rows):
        r1 = client.get("/api/kaoyan/reforms", params={"school_id": self.SCHOOL_ID, "page": 1, "page_size": 100})
        r2 = client.get("/api/kaoyan/reforms", params={"school_id": self.SCHOOL_ID, "page": 2, "page_size": 100})
        assert r1.status_code == 200 and r2.status_code == 200
        assert len(r1.json()) == 100
        assert len(r2.json()) == 50
        assert {r["id"] for r in r1.json()} != {r["id"] for r in r2.json()}

    def test_api_backward_compat_limit_only(self, client, reform_rows):
        r = client.get("/api/kaoyan/reforms", params={"school_id": self.SCHOOL_ID, "limit": 30})
        assert r.status_code == 200
        assert len(r.json()) == 30


class TestErrorStatsUserIsolation:
    """复测整改（2026-11-21）：/api/errors/stats 曾漏传 user_id → 新账号看到他人错题计数。

    线上实证：reviewer02（空账号）stats.total=8，而 8 条错题归属 pyy(5)/ui_reviewer(3)。
    服务层与路由层双断言，防回归。
    """

    UID_A = 990003
    UID_B = 990004

    @pytest.fixture()
    def error_rows(self, db_schema):
        from database import SessionLocal
        from models import ErrorRecord, User

        db = SessionLocal()
        try:
            for uid, nm in ((self.UID_A, "qa_iso_err_a"), (self.UID_B, "qa_iso_err_b")):
                if db.query(User).filter(User.id == uid).first() is None:
                    db.add(
                        User(
                            id=uid,
                            username=nm,
                            password_hash="!disabled",
                            display_name=nm,
                            role="user",
                            is_active=True,
                            must_change_password=False,
                            token_version=0,
                        )
                    )
            db.flush()
            for uid, n in ((self.UID_A, 2), (self.UID_B, 1)):
                for i in range(n):
                    db.add(
                        ErrorRecord(
                            user_id=uid,
                            content=f"QA-隔离错题-{uid}-{i}",
                            subject="数学",
                            status="active",
                        )
                    )
            db.commit()
            yield
        finally:
            db.rollback()
            db.execute(
                text("DELETE FROM error_records WHERE user_id IN (:a, :b)"),
                {"a": self.UID_A, "b": self.UID_B},
            )
            db.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": self.UID_A, "b": self.UID_B})
            db.commit()
            db.close()

    def test_service_stats_scoped(self, db_schema, error_rows):
        from database import SessionLocal
        from services import error_linker

        db = SessionLocal()
        try:
            sa = error_linker.error_stats(db, user_id=self.UID_A)
            sb = error_linker.error_stats(db, user_id=self.UID_B)
            assert sa["total"] == 2
            assert sb["total"] == 1
        finally:
            db.close()

    def test_route_stats_scoped(self, client, app_module, error_rows):
        from types import SimpleNamespace

        from utils.security import current_user, stub_principal

        def as_user(uid):
            p = stub_principal(role="user")
            return SimpleNamespace(**{**vars(p), "id": uid})

        prev = app_module.dependency_overrides.get(current_user)
        try:
            app_module.dependency_overrides[current_user] = lambda: as_user(self.UID_A)
            ra = client.get("/api/errors/stats")
            app_module.dependency_overrides[current_user] = lambda: as_user(self.UID_B)
            rb = client.get("/api/errors/stats")
            assert ra.status_code == 200 and rb.status_code == 200
            assert ra.json()["total"] == 2, "路由层必须按当前用户过滤（曾漏传 user_id）"
            assert rb.json()["total"] == 1
        finally:
            if prev is None:
                app_module.dependency_overrides.pop(current_user, None)
            else:
                app_module.dependency_overrides[current_user] = prev
