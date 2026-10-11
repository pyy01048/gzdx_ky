# -*- coding: utf-8 -*-
"""V10 新功能回归测试：改考雷达 / 全局通知流 / 分数全景 / 自动调整。

隔离说明：全部走 conftest 改写的临时库，绝不触碰真实 kaoyan.db。

覆盖：
1. reform_detector.classify_reform_title 纯函数分类正确（8 类规则）；
2. scan_notices_for_reforms 能从公告标题生成事件，且重复扫描幂等；
3. GET /api/kaoyan/notices/feed 分页 + 类型过滤 + 关键词搜索；
4. GET /api/kaoyan/analysis/score-detail/{id} 返回多年分数/录取/趋势结构；
5. POST /api/kaoyan/analysis/auto-adjust 三档分箱正确 + 422 校验。
"""
from __future__ import annotations

import pytest

from database import Base, SessionLocal, engine
from models import KaoyanAdmission, KaoyanMajor, KaoyanSchool, KaoyanScoreLine
from services.kaoyan import reform_detector
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    """建 ORM 表 + 种子数据（临时库，模块级一次）。"""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        s1 = KaoyanSchool(id=9001, name="测试大学A", level="211", province="广东")
        s2 = KaoyanSchool(id=9002, name="测试大学B", level="双一流", province="湖北")
        db.add_all([s1, s2])
        db.flush()
        m1 = KaoyanMajor(id=9101, school_id=9001, code="085400", name="电子信息")
        db.add(m1)
        db.flush()
        # 分数线：2024/2025 两年
        db.add_all([
            KaoyanScoreLine(school_id=9001, major_id=9101, year=2024, total_line=330,
                            politics_line=55, english_line=55, math_line=80,
                            major_line=90, national_line=273, retest_line=335,
                            line_type="复试线"),
            KaoyanScoreLine(school_id=9001, major_id=9101, year=2025, total_line=340,
                            politics_line=55, english_line=55, math_line=85,
                            major_line=90, national_line=275, retest_line=345,
                            line_type="复试线"),
        ])
        db.add_all([
            KaoyanAdmission(school_id=9001, major_id=9101, year=2024, enroll_count=30,
                            retest_count=45, admit_count=30, admit_avg_score=355,
                            major_avg_score=110, retest_ratio=1.5),
            KaoyanAdmission(school_id=9001, major_id=9101, year=2025, enroll_count=30,
                            retest_count=42, admit_count=30, admit_avg_score=362,
                            major_avg_score=112, retest_ratio=1.4),
        ])
        db.commit()
    finally:
        db.close()
    yield
    # conftest 会清理临时库目录，无需显式 drop


def _add_notices(rows):
    """直接往 kaoyan_notices 表插数据（原生 DDL 表）。"""
    from services.kaoyan.spider_notices import ensure_notices_schema
    db = SessionLocal()
    try:
        ensure_notices_schema(db)
        conn = db.connection().connection
        for title, school_id, school_name, ntype, date in rows:
            conn.execute(
                "INSERT INTO kaoyan_notices (school_id, school_name, title, "
                "notice_type, publish_date, url, source) VALUES (?,?,?,?,?,?,?)",
                (school_id, school_name, title, ntype, date,
                 "https://example.com/n", "test"),
            )
        conn.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 1. 分类纯函数
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("title,expect", [
    ("2026年计算机学院初试科目调整公告", "改考科目"),
    ("关于改用全国统考数学一的说明", "改考科目"),
    ("XX专业2026年暂停招生的通知", "停招"),
    ("新增人工智能专业硕士点的公示", "新增专业"),
    ("2026年硕士研究生招生考试自命题科目考试大纲调整", "大纲调整"),
    ("初试参考书目变更说明", "参考书变更"),
    ("复试科目及形式调整的通知", "复试调整"),
    ("全日制硕士学制由两年调整为三年的公告", "学制/学费调整"),
])
def test_classify_reform_title(title, expect):
    result = reform_detector.classify_reform_title(title)
    assert (result["change_type"] if result else None) == expect


def test_classify_normal_notice_returns_none():
    assert reform_detector.classify_reform_title("国庆节放假安排的通知") is None


# --------------------------------------------------------------------------- #
# 2. 扫描 + 幂等
# --------------------------------------------------------------------------- #
def test_scan_creates_and_dedups():
    _add_notices([
        ("计算机学院2026年初试科目调整公告", 9001, "测试大学A", "公告", "2025-09-01"),
        ("软件工程专业暂停招生", 9001, "测试大学A", "公告", "2025-09-02"),
        ("关于新增网络空间安全专业硕士点的公示", 9002, "测试大学B", "公告", "2025-09-03"),
        ("国庆节放假安排", 9002, "测试大学B", "公告", "2025-09-04"),
    ])
    db = SessionLocal()
    try:
        r1 = reform_detector.scan_notices_for_reforms(db)
        assert r1["inserted"] == 3, r1
        # 幂等：再扫一遍不新增
        r2 = reform_detector.scan_notices_for_reforms(db)
        assert r2["inserted"] == 0
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 3. 全局通知流
# --------------------------------------------------------------------------- #
def test_notices_feed_filter_and_paging():
    r = client.get("/api/kaoyan/notices/feed", params={"notice_type": "公告"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 4
    assert all(n["notice_type"] == "公告" for n in data["items"])

    r = client.get("/api/kaoyan/notices/feed", params={"q": "科目调整"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and "科目调整" in items[0]["title"]

    r = client.get("/api/kaoyan/notices/feed", params={"page": 1, "page_size": 2})
    assert r.status_code == 200
    assert len(r.json()["items"]) <= 2


# --------------------------------------------------------------------------- #
# 4. 分数全景
# --------------------------------------------------------------------------- #
def test_score_detail_shape():
    r = client.get("/api/kaoyan/analysis/score-detail/9001")
    assert r.status_code == 200
    d = r.json()
    assert d["school_name"] == "测试大学A"
    assert d["trends"]["admit_avg_trend"] in ("持续上涨", "持续下降", "波动较大", "基本平稳", "数据不足")
    assert len(d["years_detail"]) == 2
    y2025 = [y for y in d["years_detail"] if y["year"] == 2025][0]
    assert y2025["total_line"] == 340
    assert y2025["math_line"] == 85
    assert d["line_vs_national"]["diff"] == 65  # 340 - 275
    assert any(a["admit_avg_score"] == 362 for a in d["admissions_detail"])

    r404 = client.get("/api/kaoyan/analysis/score-detail/9999")
    assert r404.status_code == 404


# --------------------------------------------------------------------------- #
# 5. 自动调整
# --------------------------------------------------------------------------- #
def test_auto_adjust_buckets():
    # A 校近两年录取均分 355/362 → 基准约 358.5（加权近期）
    # 390 分：gap≈+31.5 → 保；340 分：gap≈-18.5 → 冲
    for score, expect_bucket in ((390, "safe"), (340, "rush")):
        r = client.post("/api/kaoyan/analysis/auto-adjust",
                        json={"user_score": score})
        assert r.status_code == 200
        d = r.json()
        assert d["buckets"][expect_bucket], f"score={score} 应命中 {expect_bucket}"
        hit = d["buckets"][expect_bucket][0]
        assert hit["school_id"] == 9001
        assert hit["reasons"], "每档必须有数据化理由"
        assert 0 < hit["confidence"] < 1


def test_auto_adjust_validation():
    r = client.post("/api/kaoyan/analysis/auto-adjust", json={"user_score": 100})
    assert r.status_code == 422
    r = client.post("/api/kaoyan/analysis/auto-adjust", json={"user_score": "abc"})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# 6. 改考列表 API
# --------------------------------------------------------------------------- #
def test_reforms_api():
    r = client.get("/api/kaoyan/reforms", params={"school_id": 9001})
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert len(items) == 2  # 改考科目 + 停招
    assert all(i["school_id"] == 9001 for i in items)

    r = client.get("/api/kaoyan/reforms", params={"change_type": "停招"})
    assert r.status_code == 200
    assert all(i["change_type"] == "停招" for i in r.json())

    r = client.get("/api/kaoyan/reforms/stats")
    assert r.status_code == 200
    assert r.json()["total"] >= 3

    r = client.post("/api/kaoyan/reforms/scan", json={})
    assert r.status_code == 200
    assert r.json()["inserted"] == 0  # 已扫过，幂等
