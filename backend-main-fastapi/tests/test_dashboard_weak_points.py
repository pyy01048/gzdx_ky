"""薄弱知识点 Top3（01-仪表盘 §2.1 D-10，P1：正确率/薄弱知识点 Top3，联动错题本）。

锁五件事：
1. 首屏的 Top3 就是 ``error_linker.weak_knowledge_points`` 的前 3 条 ——
   仪表盘不再自己排一次序，否则「最薄弱考点」在仪表盘、错题本、复习页会有三个答案；
2. ``weak_points`` 这个键**恒在**（没错题时是空列表），界面据此显示「还没归集」而不是拿科目名冒充考点；
3. 不外泄内部评分字段（``weak_score`` 是排序用的加权和，不是给用户看的数字）；
4. 点了 Top3 里的某一项，``GET /api/errors?knowledge_point_id=`` 真的只返回挂在该考点上的
   错题，并且能与学科筛选、分页壳叠加；
5. 学习画像 TOP10、今日洞察 weak_top、`GET /api/analytics/weak-points` 与
   `/api/analytics/overview` 取的是同一份投影
   （``error_linker.weak_points_view``）—— 四个展示面不给三份答案，
   analytics 那边尤其不能再用正则从题干猜出来的「考点名」。
"""
from __future__ import annotations

import pytest

TAG = "d10weak"


@pytest.fixture()
def seeded(db_schema):  # noqa: ARG001
    """4 个知识点 + 各自若干活跃错题挂接，用完即删。

    分值 = 错题数×2 + 考频 − 掌握度/20（``error_linker.weak_knowledge_points`` 的口径）：
    a=20 题/freq5/mastery0 → 45，b=10 题/freq1/0 → 21，c=5 题/freq1/0 → 11，
    d=1 题/freq1/0 → 3。d 是唯一注定进不了 Top3 的那个。
    """
    import datetime

    from database import SessionLocal
    from models import ErrorKnowledgeLink, ErrorRecord, KnowledgePoint

    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    db = SessionLocal()
    kps, errs = [], []
    try:
        plan = [("a", 20, 5, 0), ("b", 10, 1, 0), ("c", 5, 1, 0), ("d", 1, 1, 0)]
        for suffix, n, freq, mastery in plan:
            kp = KnowledgePoint(
                name=f"{TAG}-kp{suffix}", subject="数学", chapter=f"{TAG}章",
                mastery=mastery, exam_frequency=freq,
            )
            db.add(kp)
            db.flush()
            kps.append(kp)
            for i in range(n):
                err = ErrorRecord(
                    user_id=0,
                    content=f"{TAG}-e{suffix}-{i}", correct_answer="B", my_answer="A",
                    subject="数学", status="active", next_review=now,
                )
                db.add(err)
                db.flush()
                errs.append(err)
                db.add(ErrorKnowledgeLink(
                    error_id=err.id, knowledge_point_id=kp.id, relevance=0.8, source="auto",
                ))
        db.commit()
        yield {"kps": [k.id for k in kps], "names": [k.name for k in kps]}
    finally:
        ids = [k.id for k in kps]
        db.query(ErrorKnowledgeLink).filter(
            ErrorKnowledgeLink.knowledge_point_id.in_(ids)
        ).delete(synchronize_session=False)
        db.query(ErrorRecord).filter(ErrorRecord.content.like(f"{TAG}%")).delete(synchronize_session=False)
        db.query(KnowledgePoint).filter(KnowledgePoint.name.like(f"{TAG}%")).delete(synchronize_session=False)
        db.commit()
        db.close()


def _weak_from_service():
    from database import SessionLocal
    from services.dashboard_service import DashboardService

    db = SessionLocal()
    try:
        return DashboardService.get_weakness(db)
    finally:
        db.close()


def test_dashboard_top3_is_the_same_list_as_the_authority(seeded):
    """首屏 Top3 必须逐条等于 error_linker 的前 3 条（含顺序）。"""
    from database import SessionLocal
    from services import error_linker

    got = _weak_from_service()["weak_points"]
    db = SessionLocal()
    try:
        authority = error_linker.weak_knowledge_points(db, limit=3)
    finally:
        db.close()

    assert [p["knowledge_point_id"] for p in got] == [p["knowledge_point_id"] for p in authority], (
        "仪表盘自己排了一次序：同一份错题数据给出了不同的「最薄弱考点」"
    )


def test_dashboard_ranking_and_limit(seeded):
    """按分值降序、只给 3 条：错题最多且考频最高的排第一，注定垫底的 d 不出现。"""
    names = [p["name"] for p in _weak_from_service()["weak_points"]]
    assert names[:3] == [f"{TAG}-kpa", f"{TAG}-kpb", f"{TAG}-kpc"], names
    assert f"{TAG}-kpd" not in names, "Top3 之外的考点被塞进首屏了"


def test_internal_score_is_not_exposed(seeded):
    """契约里只留界面要显示的字段；weak_score 是加权和，不是给用户读的数字。"""
    for p in _weak_from_service()["weak_points"]:
        assert set(p) == {
            "knowledge_point_id", "name", "subject", "chapter", "mastery", "error_count",
        }


def test_summary_carries_the_key_even_without_weakness(client, db_schema):  # noqa: ARG001
    """``weak_points`` 恒在：空态是 []，不是缺键（缺键会让界面读 undefined.length 崩）。"""
    summary = client.get("/api/dashboard/summary").json()
    weakness = summary["weakness"]
    assert "weak_points" in weakness
    assert isinstance(weakness["weak_points"], list)
    if not weakness["has_weakness"]:
        assert weakness["weak_points"] == []


def test_errors_list_filters_by_knowledge_point(client, seeded):
    """联动错题本：?knowledge_point_id= 只返回挂在该考点的错题，条数与首屏 error_count 一致。

    结果里没有重复行是由数据库保证的 —— ``uq_error_kp`` 让一道错题在同一个考点上
    只能有一条挂接（曾试图插第二条，直接 UniqueViolation），所以这里只核对总数。
    """
    kp_a = seeded["kps"][0]
    payload = client.get("/api/errors", params={"knowledge_point_id": kp_a, "page_size": 100}).json()
    assert payload["total"] == 20, "该考点挂了 20 道活跃错题"
    assert all(item["content"].startswith(f"{TAG}-e") for item in payload["items"])
    assert len({item["id"] for item in payload["items"]}) == payload["total"]

    other = client.get("/api/errors", params={"knowledge_point_id": seeded["kps"][3], "page_size": 100}).json()
    assert other["total"] == 1


def test_kp_filter_combines_with_subject_and_paging(client, seeded):
    """考点筛选和既有筛选是叠加的，不互相覆盖；分页壳字段照旧自洽。"""
    kp_b = seeded["kps"][1]  # 10 道，全部 subject=数学
    got = client.get(
        "/api/errors",
        params={"knowledge_point_id": kp_b, "subject": "数学", "page_size": 4, "page": 2},
    ).json()
    assert got["total"] == 10
    assert len(got["items"]) == 4
    assert got["total_pages"] == 3
    assert got["page"] == 2

    none = client.get("/api/errors", params={"knowledge_point_id": kp_b, "subject": "英语"}).json()
    assert none["total"] == 0, "叠加筛选被后写的条件覆盖了"


# --------------------------------------------------------------------------- #
# 同一份名单要覆盖全部三个展示面：仪表盘 Top3、学习画像 Top10、今日洞察 weak_top。
# 画像此前另有一套 question_knowledge_links 的 SQL，洞察更是用正则从错题正文猜
# 「考点名」，于是同一个人同一天能看到三份互不相同的薄弱清单。
# --------------------------------------------------------------------------- #

def test_profile_top10_is_the_same_authority_list(seeded):
    from database import SessionLocal
    from services import error_linker
    from services.learner_profile import WEAK_POINTS_ON_PROFILE, build_profile

    db = SessionLocal()
    try:
        authority = error_linker.weak_points_view(db, limit=WEAK_POINTS_ON_PROFILE)
        profile_points = build_profile(db, days=30)["weak_points"]
    finally:
        db.close()

    assert profile_points == authority, "学习画像又排了一次序"
    # 本用例造的三个考点之间相对次序稳定（库里可能有其它测试残留的考点，故不锁绝对位置）
    mine = [p["name"] for p in profile_points if p["name"].startswith(TAG)]
    assert mine[:3] == [f"{TAG}-kpa", f"{TAG}-kpb", f"{TAG}-kpc"], mine
    for p in profile_points:
        assert set(p) == {
            "knowledge_point_id", "name", "subject", "chapter", "mastery", "error_count",
        }, "画像外泄了内部评分字段"


def test_insight_today_weak_top_matches_the_authority(client, seeded):
    from database import SessionLocal
    from services import error_linker

    db = SessionLocal()
    try:
        names = [p["name"] for p in error_linker.weak_points_view(db, limit=3)]
    finally:
        db.close()

    weak_top = client.get("/api/insight/today").json()["weak_top"]
    assert [w["kp"] for w in weak_top] == names, "首屏「薄弱点练习」和 D-10 卡片名单不一致"
    for w in weak_top:
        assert set(w) == {
            "kp", "knowledge_point_id", "subject", "error_count", "mastery", "level",
        }
        # level 的中文口径与 kp_mastery.STATE_LABELS 一致，前端沿用旧展示
        assert w["level"] in ("薄弱", "已掌握")


def test_analytics_weak_points_is_the_same_authority(client, seeded):
    """`GET /api/analytics/weak-points` 不能再自己猜一遍考点。

    旧实现用正则在错题正文里抓「…定理/…公式」这类词，再按 `100 - 次数×15`
    编造 mastery —— 猜出来的名字既不是 knowledge_points 里的行，也没有
    knowledge_point_id，界面点不动、错题本对不上。
    """
    from database import SessionLocal
    from services import error_linker

    db = SessionLocal()
    try:
        authority = error_linker.weak_points_view(db, limit=20)
    finally:
        db.close()

    payload = client.get("/api/analytics/weak-points", params={"limit": 20}).json()
    got = payload["weak_points"]
    assert [p["knowledge_point_id"] for p in got] == [p["knowledge_point_id"] for p in authority], (
        "analytics 端点又给出了一份不同的「薄弱考点」名单"
    )
    for p, a in zip(got, authority):
        assert p["knowledge_point"] == a["name"]
        assert p["mastery"] == a["mastery"], "mastery 是编出来的，不是 knowledge_points 里的真值"
        assert p["error_count"] == a["error_count"]
        assert p["level"] in ("学习中", "薄弱", "已掌握")
        assert set(p) <= {
            "knowledge_point_id", "knowledge_point", "subject", "chapter",
            "error_count", "mastery", "level", "suggestion",
        }


def test_analytics_overview_top3_matches_dashboard(client, seeded):
    """`/api/analytics/overview` 的 top_weak_points 就是首屏那三条，同源同序。"""
    summary = client.get("/api/dashboard/summary").json()
    top = client.get("/api/analytics/overview").json()["top_weak_points"]
    card = summary["weakness"]["weak_points"]
    if card:
        assert [p["knowledge_point_id"] for p in top] == [p["knowledge_point_id"] for p in card]


def test_graduated_error_moves_from_stock_to_resolved(db_schema):  # noqa: ARG001
    """error_records 只有 active/graduated 两个状态：毕业的那道要从存量移到已解决。

    旧实现数的是 status='resolved'，而 'resolved' 从来没有写入点（'submitted' 属于
    exam_sessions），所以「错题已解决」永远显示 0 —— 这里用增量断言，避开共享库里
    其它测试残留的错题。
    """
    from database import SessionLocal
    from models import ErrorRecord
    from services.learner_profile import build_profile

    content = f"{TAG}-graduated"
    db = SessionLocal()
    try:
        before = build_profile(db, days=30)["overview"]
        db.add(ErrorRecord(
            content=content, correct_answer="B", my_answer="A",
            subject="数学", status="graduated",
        ))
        db.commit()
        after = build_profile(db, days=30)["overview"]
        assert after["error_resolved"] == before["error_resolved"] + 1
        assert after["error_stock"] == before["error_stock"], "已毕业的错题仍算在存量里"
    finally:
        db.query(ErrorRecord).filter(ErrorRecord.content == content).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()
