# -*- coding: utf-8 -*-
"""``services/kaoyan/notice_dedup.py`` 判重键与写入防护单测。

重点覆盖 2026-10-12 修复的**空锚点防护**：

    桂林电子科技大学同一处 ``<a href="#">`` 空锚点被采集两次，
    因 ``normalize_notice_url('#')`` 归一化为空、判重退化成按标题、
    而两条空锚点的锚点文本不同（「博士专业学位授权类别」vs 字面「#」），
    最终写成 id=419 / id=945 两行。

修复：``upsert_notice()`` 在 URL 归一化后为空时直接返回 ``"skipped"``。

所有用例跑在内存库上，**绝不触碰真库**。
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.kaoyan.notice_dedup import (  # noqa: E402
    normalize_notice_title,
    normalize_notice_url,
    notice_dedup_key,
    upsert_notice,
)


# --------------------------------------------------------------------------- #
# normalize_notice_url：判据本身
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        # 协议 / www / 尾斜杠 / 大小写 / 查询串 / 锚点都应归一为同一资源
        ("https://www.guet.edu.cn/a/b/", "guet.edu.cn/a/b"),
        ("http://www.guet.edu.cn/a/b", "guet.edu.cn/a/b"),
        ("HTTPS://WWW.GUET.EDU.CN/a/b", "guet.edu.cn/a/b"),
        ("https://www.guet.edu.cn/a/b?from=timeline#top", "guet.edu.cn/a/b"),
        # 空锚点：归一化后必须是空串（这是防护的判据）
        ("#", ""),
        ("", ""),
        (None, ""),
        ("   ", ""),
        ("#top", ""),
        ("?x=1", ""),
    ],
)
def test_normalize_notice_url(raw, expected):
    assert normalize_notice_url(raw) == expected


def test_relative_url_survives_normalization():
    """无协议相对路径**不是**空锚点，归一化后非空，不应被防护挡掉。

    例：``/info/1074/20804.htm`` → ``/info/1074/20804.htm``。
    """
    assert normalize_notice_url("/info/1074/20804.htm") == "/info/1074/20804.htm"
    assert normalize_notice_url("info/1074/20804.htm") == "info/1074/20804.htm"


# --------------------------------------------------------------------------- #
# notice_dedup_key：URL 为空时退化为标题键（修复前后行为不变）
# --------------------------------------------------------------------------- #
def test_dedup_key_uses_url_when_present():
    k1 = notice_dedup_key(208, "博士专业学位授权类别", "https://www.guet.edu.cn/x.htm")
    k2 = notice_dedup_key(208, "完全不同的标题", "http://guet.edu.cn/x.htm")
    assert k1 == k2 == (208, "guet.edu.cn/x.htm")


def test_dedup_key_falls_back_to_title_when_url_empty():
    """URL 归一化为空时仍退回标题键 —— 这是判重函数的既有契约，
    空锚点的拦截发生在 ``upsert_notice`` 而非此处，故本行为不变。"""
    k = notice_dedup_key(208, "博士专业学位授权类别", "#")
    assert k == (208, "title:博士专业学位授权类别")


# --------------------------------------------------------------------------- #
# upsert_notice：空锚点防护（本次修复的核心）
# --------------------------------------------------------------------------- #
@pytest.fixture()
def mem_db():
    """内存库，列与真库 ``kaoyan_notices`` 对齐（含 notice-alert 加的
    ``importance_level`` 列 —— ``upsert_notice`` 的 UPDATE 会引用它）。"""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE kaoyan_notices ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " school_id INTEGER, school_name TEXT, title TEXT NOT NULL,"
        " notice_type TEXT, publish_date TEXT, url TEXT, source TEXT,"
        " fetched_at TEXT, importance_level TEXT, importance_score REAL,"
        " importance_reason TEXT, deadline_date TEXT, events_json TEXT,"
        " classified_at TEXT,"
        " is_read INTEGER NOT NULL DEFAULT 0,"
        " is_starred INTEGER NOT NULL DEFAULT 0, read_at TEXT, starred_at TEXT)"
    )
    yield conn
    conn.close()


def test_upsert_rejects_empty_anchor(mem_db):
    """空锚点（href='#'）必须被拒写，且库里不留任何行。"""
    assert upsert_notice(
        mem_db, 208, "桂林电子科技大学", "博士专业学位授权类别", url="#"
    ) == "skipped"
    # 锚点文本是字面「#」的同类空锚点同样被拒
    assert upsert_notice(
        mem_db, 208, "桂林电子科技大学", "#", url="#"
    ) == "skipped"
    assert mem_db.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0] == 0


def test_upsert_rejects_missing_url(mem_db):
    """url 为 None / 空串同样归一化为空，一并拒写。"""
    assert upsert_notice(
        mem_db, 208, "桂林电子科技大学", "某公告", url=None
    ) == "skipped"
    assert upsert_notice(
        mem_db, 208, "桂林电子科技大学", "某公告", url=""
    ) == "skipped"
    assert upsert_notice(
        mem_db, 208, "桂林电子科技大学", "某公告", url="#top"
    ) == "skipped"
    assert mem_db.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0] == 0


def test_upsert_accepts_normal_url(mem_db):
    """正常 URL 必须照常写入（回归保护：防护不能误伤合法数据）。"""
    assert upsert_notice(
        mem_db, 208, "桂林电子科技大学", "2027年硕士研究生招生简章",
        url="https://www.guet.edu.cn/2026/0930/c6358a1/page.htm",
    ) == "inserted"
    assert mem_db.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0] == 1


def test_upsert_accepts_relative_url(mem_db):
    """无协议相对 URL 归一化后非空，应被接受（不是空锚点）。"""
    assert upsert_notice(
        mem_db, 208, "桂林电子科技大学", "某公告", url="/info/1074/20804.htm"
    ) == "inserted"
    assert mem_db.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0] == 1


def test_upsert_idempotent_for_same_url(mem_db):
    """同一 URL 二次写入走 UPDATE，不产生第二行。

    注意：现有 UPDATE 语句**不更新 title**（只更新 url/publish_date/
    notice_type/importance_level/fetched_at），这是既有契约。本用例把它
    固化下来，防止将来有人"顺手"改 UPDATE 列表时破坏它。
    """
    url = "https://www.guet.edu.cn/2026/0930/c6358a1/page.htm"
    assert upsert_notice(mem_db, 208, "桂电", "标题A", url=url) == "inserted"
    assert upsert_notice(mem_db, 208, "桂电", "标题A(改)", url=url) == "updated"
    assert mem_db.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0] == 1
    # title 不被 UPDATE 覆盖（既有契约）
    assert mem_db.execute("SELECT title FROM kaoyan_notices").fetchone()[0] == "标题A"


def test_upsert_never_overwrites_user_state(mem_db):
    """UPDATE 路径永不覆盖 is_read / is_starred（既有契约，防回归）。"""
    url = "https://www.guet.edu.cn/a.htm"
    upsert_notice(mem_db, 208, "桂电", "标题A", url=url)
    mem_db.execute(
        "UPDATE kaoyan_notices SET is_read=1, is_starred=1, "
        "read_at='2026-10-12 10:00:00', starred_at='2026-10-12 10:00:00'"
    )
    mem_db.commit()
    upsert_notice(mem_db, 208, "桂电", "标题A(改)", url=url)
    row = mem_db.execute(
        "SELECT is_read, is_starred, read_at, starred_at FROM kaoyan_notices"
    ).fetchone()
    assert row == (1, 1, "2026-10-12 10:00:00", "2026-10-12 10:00:00")


def test_upsert_does_not_leak_across_schools(mem_db):
    """判重键含 school_id：不同院校的相同 URL 是两条独立通知。"""
    url = "https://www.guet.edu.cn/a.htm"
    assert upsert_notice(mem_db, 208, "桂电", "标题A", url=url) == "inserted"
    assert upsert_notice(mem_db, 209, "他校", "标题A", url=url) == "inserted"
    assert mem_db.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0] == 2
