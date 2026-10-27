# -*- coding: utf-8 -*-
"""公告时间戳契约（#19 残留：写库口径 / 出参补 Z / 北京日归日）。

三件事必须一起锁——错在任何一处，首页「最近采集」「今日更新」都会显示成早 8 小时：

1. 写入值必须是 **naive UTC + ISO「T」分隔**（唯一出口 ``timeutil.naive_utc_iso``）。
   ``utils/response.py`` 的补 ``Z`` 正则只认带 ``T`` 的形态，空格分隔的展示串不匹配，
   前端 ``new Date()`` 于是按本地时区解析一个 UTC 墙钟。
2. 出参 ``fetched_at`` 端到端必须带 ``Z``（走真实响应类，而不是只看库里的值）。
3. ``/api/kaoyan/notices/updates`` 的「更新日期」按 **北京自然日** 归日：北京 00:30
   采集的公告（= UTC 前一天 16:30）必须记在今天，不能掉到前一天。

库里可能留有其它测试种下的行，所以断言只针对本用例自己插入的 ``school_name``，
并在用例结束时删掉自己插的行。
"""
from __future__ import annotations

import datetime as dt
import re

import pytest

from database import SessionLocal
from services.dbapi_compat import wrap_conn
from services.kaoyan.notice_dedup import upsert_notice
from services.kaoyan.spider_notices import ensure_notices_schema
from utils import timeutil as tu

ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
SCHOOL = "时间口径契约测试校"
URL = "https://test-example.edu.cn/notice/time-contract"


@pytest.fixture()
def db(db_schema):  # noqa: ARG001  依赖 db_schema 确保临时库已建表
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def notice_row(db):
    """插入一条「无发布日、只有采集时间」的公告，用例结束即删除。

    采集时刻取 **北京今天 00:30**，它等于 UTC 前一天 16:30 —— 这正是能区分
    「按 UTC 日」与「按北京日」两种归日口径的时刻。
    """
    ensure_notices_schema(db)
    day, start, _end = tu.local_day_window()
    assert start.date() != day, "用例要落在能区分 UTC 日与北京日的时刻，否则等于没测"
    moment = start + dt.timedelta(minutes=30)
    # 每次拿到 Session 的底层连接都要重新取：commit 会释放它（见
    # services/kaoyan/notice_alert.py 里同类注释），复用旧 conn 会拿到已关闭的连接。
    conn = wrap_conn(db.connection().connection)
    upsert_notice(
        conn,
        school_id=None,
        school_name=SCHOOL,
        title="时间口径契约用例公告",
        notice_type="公告",
        publish_date=None,
        url=URL,
        source="test-example.edu.cn",
        fetched_at=moment.isoformat(timespec="seconds"),
    )
    db.commit()
    try:
        yield {"day": day, "moment": moment}
    finally:
        wrap_conn(db.connection().connection).execute(
            "DELETE FROM kaoyan_notices WHERE url = ?", (URL,)
        )
        db.commit()


def test_naive_utc_iso_is_iso_t_naive():
    """存储格式：naive UTC、带 ``T``、秒精度、不带 ``Z``（Z 由响应类补）。"""
    value = tu.naive_utc_iso()
    assert len(value) == 19 and value[10] == "T", value
    assert not value.endswith("Z") and "+" not in value
    parsed = dt.datetime.fromisoformat(value)
    assert parsed.tzinfo is None
    # 与 utcnow 同源：同一瞬间取值应完全一致
    assert value == tu.utcnow().isoformat(timespec="seconds")


def test_notice_list_returns_fetched_at_with_z(db, client, notice_row):
    """端到端：出参的 ``fetched_at`` 带 ``Z``，前端按本地时区解析即为北京时间。"""
    resp = client.get("/api/kaoyan/notices", params={"keyword": "时间口径契约用例公告", "limit": 5})
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    mine = [i for i in items if i.get("school_name") == SCHOOL]
    assert mine, f"没查到本用例插入的公告：{items}"
    stamped = mine[0]["fetched_at"]
    assert ISO_Z_RE.match(stamped), f"补 Z 失败（前端会按本地时间解析）：{stamped!r}"
    # 补上来的 Z 必须指向同一瞬间，不能只是"格式对但时刻错"
    got = dt.datetime.strptime(stamped, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    assert got == notice_row["moment"].replace(tzinfo=dt.timezone.utc)


def test_updates_endpoint_buckets_fetched_at_by_beijing_day(db, notice_row):
    """「今日更新」按北京日归日：北京 00:30 的采集记在今天，不是 UTC 的前一天。"""
    from routers.kaoyan import notice_updates

    data = notice_updates(days=1, db=db)
    mine = [s for s in data["schools"] if s["school_name"] == SCHOOL]
    assert mine, f"北京日凌晨采集的公告被归到了前一天：{data['schools']}"
    assert mine[0]["latest_date"] == notice_row["day"].isoformat()
    assert mine[0]["latest_date"] != notice_row["moment"].date().isoformat()


def test_stats_latest_fetched_at_is_parseable(db, client, notice_row):
    """概览里的「最近采集」同样必须带 Z —— 首页 NoticeBoard 直接渲染它。"""
    resp = client.get("/api/kaoyan/notices", params={"limit": 200})
    assert resp.status_code == 200, resp.text
    latest = resp.json()["stats"]["latest_fetched_at"]
    if latest is None:
        pytest.skip("库里没有带采集时间的公告")
    assert ISO_Z_RE.match(latest), f"latest_fetched_at 未补 Z：{latest!r}"
