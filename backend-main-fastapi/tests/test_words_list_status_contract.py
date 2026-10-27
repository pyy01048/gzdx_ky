# -*- coding: utf-8 -*-
"""单词列表状态契约回归（dogfood ISSUE-004 根因锁）。

DB 权威枚举是 not_mastered（没有 'new'），API/前端契约用 new；
映射的唯一实现是 WordOut.status 的 field_validator。list_words 早先
手工组装响应、把 ORM 行直接塞进 items，绕过了映射 → 前端复习队列的
两个桶（new / learning+reviewing）都接不住 not_mastered，导入 20 词后
队列恒空，页面却显示「今日单词已全部复习完成」。

锁三件事：
1. GET /api/words 返回的 status 必须是 API 契约词（new），不是 DB 枚举原文；
2. 新词 due_date 为今天（前端 dueCards 依此纳入今日队列）；
3. 分页壳 items/total/page/page_size/total_pages 不回退（utils/response.py 约定）。

隔离纪律（B4 用户隔离生效后）：words 是严格的本人数据（user_id 外键），
所以本模块把 current_user 覆盖为测试库已有的引导管理员，契约词挂它名下；
词名带 uuid、每个用例自建自清，全量套件里的其它单词评分测试不会碰这批数据。
"""
from __future__ import annotations

import datetime
import uuid
from types import SimpleNamespace

import pytest

from database import SessionLocal
from models import User, Word
from tests.asgi_client import ASGIClient
from main import app
from utils.security import current_user

client = ASGIClient(app)


@pytest.fixture(scope="module", autouse=True)
def _owner_user():
    """把 current_user 指向测试库已有用户（B4 归属口径下本人数据才可见）。

    桩只带 words 域实际消费的字段（id/username/role）。
    """
    db = SessionLocal()
    try:
        # password_hash 非空约束：本用户永不登录，落一个明确的测试占位串即可
        u = User(username=f"contract{uuid.uuid4().hex[:8]}", display_name="契约用户",
                 role="user", is_active=True)
        u.password_hash = "test-placeholder-never-used-for-login"
        db.add(u)
        db.commit()
        uid, uname = u.id, u.username
    finally:
        db.close()

    app.dependency_overrides[current_user] = lambda: SimpleNamespace(
        id=uid, username=uname, role="user",
    )
    yield uid
    # 恢复 conftest.auth_bypass 的默认桩（不能 pop，否则后续测试文件全部 401）
    from utils.security import stub_principal
    app.dependency_overrides[current_user] = lambda: stub_principal()

    db = SessionLocal()
    try:
        db.query(Word).filter(Word.user_id == uid,
                              Word.word.like("contract%")).delete(synchronize_session=False)
        db.query(User).filter(User.id == uid).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _make_word(owner_id: int) -> str:
    """给契约用户建一个 uuid 命名的未学新词（due=今天），返回词名。"""
    name = f"contract{uuid.uuid4().hex[:10]}"
    db = SessionLocal()
    try:
        db.add(Word(word=name, meaning="契约测试词", status="not_mastered",
                    due_date=datetime.date.today(), user_id=owner_id))
        db.commit()
    finally:
        db.close()
    return name


def test_list_maps_not_mastered_to_new(_owner_user):
    name = _make_word(_owner_user)
    r = client.get("/api/words", params={"search": name})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    item = next(w for w in body["items"] if w["word"] == name)
    # 1) API 契约词，不是 DB 枚举原文 not_mastered
    assert item["status"] == "new"
    # 2) 新词今天到期：前端 dueCards/队列靠这个字段排期
    assert item["due_date"] == datetime.date.today().isoformat()
    # 3) 分页壳完整
    assert {"items", "total", "page", "page_size", "total_pages"} <= set(body)


def test_stats_still_counts_new_separately(_owner_user):
    """stats 口径不受序列化修复影响：not_mastered 计入 new。"""
    _make_word(_owner_user)
    r = client.get("/api/words/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["new"] >= 1
    # V12 口径：新词不算「今日待复习」（复习债），防两处口径互相污染
    assert body["due_today"] >= 0
