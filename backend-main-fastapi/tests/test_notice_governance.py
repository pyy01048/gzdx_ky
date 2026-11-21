# -*- coding: utf-8 -*-
"""C 批次2 回归：标题清洗 / 日期证据打标 / 白名单三态 / 去重 / 改考置信度分级 /
审核队列鉴权与人工裁定幂等 / feed 与改考列表噪声出列。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

UID = 990011
SCHOOL = "测试治理大学B2"


@pytest.fixture()
def seed(db_schema):
    from database import SessionLocal
    from services.dbapi_compat import wrap_conn
    from services.kaoyan.notice_governance import run_batch2  # noqa: F401  (确保模块可导入)
    from services.kaoyan.reform_detector import ensure_reforms_schema
    from services.kaoyan.spider_notices import ensure_notices_schema

    db = SessionLocal()
    ids = {}
    try:
        ensure_notices_schema(db)
        ensure_reforms_schema(db)
        conn = wrap_conn(db.connection().connection)
        notices = [
            ("2027年硕士研究生招生简章", "简章", "2026-09-01", ""),
            ("春分", "公告", "2026-03-20", ""),
            ("【2026-10-12】关于复试调剂的通知", "调剂", "", ""),
            ("2026-10-12 关于复试调剂的通知", "调剂", "2026-10-12", ""),
            ("校园开放日安排", "公告", "", ""),
            ("硕士研究生招生咨询周公告", "公告", "", ""),
        ]
        for i, (title, ntype, pdate, _x) in enumerate(notices, start=1):
            cur = conn.execute(
                "INSERT INTO kaoyan_notices (school_name, title, notice_type, publish_date, "
                "url, source, content, is_noise) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
                (SCHOOL, title, ntype, pdate, f"https://yjszs.test.edu.cn/n{i}", "测试源", "正文内容。" * 20, False),
            )
            ids[f"n{i}"] = cur.fetchone()[0]
        reforms = [
            ("2027年改考科目：812 改为 408", "改考科目", 0, 0.8, "auto", ids["n1"]),
            ("JOINT TRAINING 联培专项招生（BRT）基本制度测试", "新增专业", 0, 0.8, "auto", None),
            ("停招某专业通知", "停招", 2026, 0.8, "manual", None),
            ("研究生招生校园开放日精彩瞬间", "招生政策变化", 0, 0.8, "auto", None),
        ]
        for i, (title, ctype, year, conf, rsource, nid) in enumerate(reforms, start=1):
            cur = conn.execute(
                "INSERT INTO kaoyan_reforms (school_name, title, year, change_type, keywords, "
                "confidence, url, source, notice_id, detail_hash, review_status, review_source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (
                    SCHOOL,
                    title,
                    year,
                    ctype,
                    "改考",
                    conf,
                    f"https://yjszs.test.edu.cn/r{i}",
                    "测试源",
                    nid,
                    f"b2hash{i}",
                    "ok",
                    rsource,
                ),
            )
            ids[f"r{i}"] = cur.fetchone()[0]
        conn.commit()
        yield ids
    finally:
        conn = wrap_conn(db.connection().connection)
        conn.execute("DELETE FROM kaoyan_reforms WHERE school_name=?", (SCHOOL,))
        conn.execute("DELETE FROM kaoyan_notices WHERE school_name=?", (SCHOOL,))
        conn.commit()
        db.close()


@pytest.fixture()
def admin_client(client, app_module):
    from utils.security import current_user

    prev = app_module.dependency_overrides.get(current_user)
    app_module.dependency_overrides[current_user] = lambda: SimpleNamespace(id=UID, role="admin", username="b2_admin")
    yield client
    if prev is None:
        app_module.dependency_overrides.pop(current_user, None)
    else:
        app_module.dependency_overrides[current_user] = prev


class TestUnits:
    def test_clean_title_prefix(self):
        from services.kaoyan.notice_governance import clean_title

        assert clean_title("【2026-10-12】关于复试的通知") == "关于复试的通知"
        assert clean_title("20261012 招生简章") == "招生简章"
        assert clean_title("2026年10月12日-复试安排") == "复试安排"
        assert clean_title("普通标题不变") == "普通标题不变"

    def test_date_evidence_order(self):
        from services.kaoyan.notice_governance import parse_date_evidence

        d, src = parse_date_evidence("通知 2026-01-02 发布", "https://x/2025-03-04", "")
        assert (d, src) == ("2026-01-02", "title")
        d, src = parse_date_evidence("无日期标题", "https://x/2025-03-04/a", "")
        assert (d, src) == ("2025-03-04", "url")
        d, src = parse_date_evidence("无", "", "发布于 2024年5月6日 的通知")
        assert (d, src) == ("2024-05-06", "content")
        assert parse_date_evidence("无", "", "无") == (None, "unknown")

    def test_classify_three_states(self):
        from services.kaoyan.notice_governance import classify_notice

        assert classify_notice("硕士研究生招生简章") == "ok"
        assert classify_notice("春分") == "noise"
        assert classify_notice("组织部") == "noise"
        assert classify_notice("张三") == "noise"
        assert classify_notice("校园开放日安排") == "pending_review"

    def test_confidence_grading(self):
        from services.kaoyan.notice_governance import score_reform_confidence

        c1, b1 = score_reform_confidence(
            "2027年改考科目：812 改为 408", "https://yjszs.x.edu.cn/a", "校研招网", "改考科目", 0.8
        )
        c2, b2 = score_reform_confidence("改考通知", "", "", "改考科目", 0.8)
        assert c1 > c2
        assert 0.40 <= c1 <= 0.95 and 0.40 <= c2 <= 0.95
        assert any(s.startswith("year_in_title") for s in json.loads(b1))
        cn, bn = score_reform_confidence("JOINT TRAINING 测试", "", "", "新增专业", 0.75)
        assert cn < 0.75 and any(s.startswith("noise_marker") for s in json.loads(bn))
        from services.kaoyan.notice_governance import REFORM_NOISE_RE

        assert REFORM_NOISE_RE.search("研究生招生校园开放日精彩瞬间")
        assert REFORM_NOISE_RE.search("关于开展研究生“评优评奖示范月”专项工作的通知")


class TestGovern:
    def test_batch2_states_and_idempotent_manual(self, seed):
        from database import SessionLocal
        from services.dbapi_compat import wrap_conn
        from services.kaoyan.notice_governance import run_batch2

        db = SessionLocal()
        try:
            rep = run_batch2(db)
            assert rep["notices"]["duplicate"] >= 1
            assert rep["notices"]["noise"] >= 1
            conn = wrap_conn(db.connection().connection)

            def nrow(key):
                return conn.execute(
                    "SELECT title, title_raw, publish_date, date_source, review_status, "
                    "is_noise, review_source FROM kaoyan_notices WHERE id=?",
                    (seed[key],),
                ).fetchone()

            n2 = nrow("n2")
            assert n2[4] == "noise" and n2[5] in (True, 1)
            n3 = nrow("n3")
            assert n3[0] == "关于复试调剂的通知" and n3[1].startswith("【2026-10-12】")
            assert n3[2] == "2026-10-12" and n3[3] == "title"
            assert nrow("n4")[4] == "duplicate"
            n5 = nrow("n5")
            assert n5[4] == "pending_review" and n5[3] == "unknown"
            assert nrow("n6")[3] == "unknown"
            r1 = conn.execute(
                "SELECT confidence, confidence_basis, year, review_status FROM kaoyan_reforms WHERE id=?", (seed["r1"],)
            ).fetchone()
            assert r1[0] != 0.8 and json.loads(r1[1]) and r1[2] == 2027 and r1[3] == "ok"
            r2 = conn.execute("SELECT review_status FROM kaoyan_reforms WHERE id=?", (seed["r2"],)).fetchone()
            assert r2[0] == "noise"
            r4 = conn.execute("SELECT review_status FROM kaoyan_reforms WHERE id=?", (seed["r4"],)).fetchone()
            assert r4[0] == "noise"  # 校园开放日/评优评奖类活动误判出列
            r3 = conn.execute(
                "SELECT confidence, review_source FROM kaoyan_reforms WHERE id=?", (seed["r3"],)
            ).fetchone()
            assert r3[0] == 0.8 and r3[1] == "manual"  # 人工行重跑不覆盖
            # 幂等：再跑一次不产生新 duplicate/不翻转 manual
            rep2 = run_batch2(db)
            assert rep2["notices"]["manual_skipped"] == 0
            conn = wrap_conn(db.connection().connection)  # 二次 run 后重取连接
            assert (
                conn.execute("SELECT review_source FROM kaoyan_reforms WHERE id=?", (seed["r3"],)).fetchone()[0]
                == "manual"
            )
        finally:
            db.close()

    def test_feed_filters_and_date_source(self, seed, client):
        from database import SessionLocal
        from services.kaoyan.notice_governance import run_batch2

        db = SessionLocal()
        try:
            run_batch2(db)
        finally:
            db.close()
        r = client.get("/api/kaoyan/notices/feed", params={"page_size": 100})
        assert r.status_code == 200
        items = {i["id"]: i for i in r.json()["items"] if i["school_name"] == SCHOOL}
        assert seed["n1"] in items and seed["n3"] in items and seed["n6"] in items
        assert seed["n2"] not in items and seed["n4"] not in items and seed["n5"] not in items
        assert items[seed["n6"]]["date_source"] == "unknown"

    def test_review_queue_auth_and_manual_resolve(self, seed, client, app_module, admin_client):
        from database import SessionLocal
        from services.kaoyan.notice_governance import govern_notices, run_batch2
        from utils.security import current_user

        db = SessionLocal()
        try:
            run_batch2(db)
        finally:
            db.close()
        prev = app_module.dependency_overrides.get(current_user)
        app_module.dependency_overrides[current_user] = lambda: SimpleNamespace(id=UID, role="user", username="b2_user")
        try:
            assert client.get("/api/kaoyan/notices/review-queue").status_code == 403
        finally:
            if prev is None:
                app_module.dependency_overrides.pop(current_user, None)
            else:
                app_module.dependency_overrides[current_user] = prev
        rq = admin_client.get("/api/kaoyan/notices/review-queue")
        assert rq.status_code == 200
        assert any(i["id"] == seed["n5"] for i in rq.json()["items"])
        assert (
            admin_client.post(f"/api/kaoyan/notices/{seed['n5']}/review", json={"action": "bogus"}).status_code == 400
        )
        assert admin_client.post("/api/kaoyan/notices/99999999/review", json={"action": "ok"}).status_code == 404
        r = admin_client.post(f"/api/kaoyan/notices/{seed['n5']}/review", json={"action": "ok"})
        assert r.status_code == 200
        db = SessionLocal()
        try:
            govern_notices(db)  # 重跑：manual 裁定不被自动分类翻转
        finally:
            db.close()
        feed = client.get("/api/kaoyan/notices/feed", params={"page_size": 100})
        assert any(i["id"] == seed["n5"] for i in feed.json()["items"])

    def test_reforms_list_and_review(self, seed, admin_client, client):
        from database import SessionLocal
        from services.kaoyan.notice_governance import run_batch2

        db = SessionLocal()
        try:
            run_batch2(db)
        finally:
            db.close()
        r = client.get("/api/kaoyan/reforms", params={"page_size": 200})
        assert r.status_code == 200
        items = {i["id"]: i for i in r.json() if i["school_name"] == SCHOOL}
        assert seed["r1"] in items and seed["r3"] in items
        assert seed["r2"] not in items
        assert items[seed["r1"]]["confidence_basis"]
        st = client.get("/api/kaoyan/reforms/stats")
        assert st.status_code == 200
        rr = admin_client.post(f"/api/kaoyan/reforms/{seed['r2']}/review", json={"action": "ok"})
        assert rr.status_code == 200
        r2 = client.get("/api/kaoyan/reforms", params={"page_size": 200})
        assert any(i["id"] == seed["r2"] for i in r2.json())
