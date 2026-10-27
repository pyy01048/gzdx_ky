# -*- coding: utf-8 -*-
"""doc 11 登录与权限：账号/会话/限流/角色/用户管理的真实链路（不走 conftest 的身份替身）。"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy import text

from conftest import TEST_USER_ID

from utils import security
from utils.access_policy import enforce_access, is_public, needs_admin
from utils.security import current_user, ensure_bootstrap_admin, hash_password, verify_password

_OPEN: list = []


class TestClient:
    """带 cookie 罐的同步 ASGI 客户端（本机 starlette 0.27 的 TestClient 与 httpx 0.28 不兼容）。"""

    __test__ = False

    def __init__(self, app):
        self._loop = asyncio.new_event_loop()
        self._c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        )
        _OPEN.append(self)

    @property
    def cookies(self):
        return self._c.cookies

    def request(self, method, url, **kw):
        return self._loop.run_until_complete(self._c.request(method, url, **kw))

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def patch(self, url, **kw):
        return self.request("PATCH", url, **kw)

    def close(self):
        self._loop.run_until_complete(self._c.aclose())
        self._loop.close()


ADMIN_PW = "Init-Pass-001"
NEW_PW = "Changed-Pass-002"


def _user_fk_columns(session):
    """列出所有 ``<table>.<column> REFERENCES users(id)``（含 SQL-only 表）。"""
    rows = session.execute(text("""
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND ccu.table_name = 'users'
    """)).all()
    return [(t, c) for t, c in rows]


def _detach_user_refs(session, fk_cols):
    """把指向 users 的归属列置空，让 ``DELETE FROM users`` 不被外键挡住。"""
    for table, col in fk_cols:
        session.execute(text(
            f'UPDATE "{table}" SET "{col}" = NULL WHERE "{col}" IS NOT NULL'
        ))


@pytest.fixture()
def auth_app(app_module, db_schema, monkeypatch):  # noqa: ARG001
    """清空 users、去掉身份替身、重置限流，结束后原样恢复。

    2026-10-20 修正：个人域表（goals / error_records / favorites …）都有
    ``user_id REFERENCES users(id)``，PG 上外键是真的。直接 ``DELETE FROM users``
    会被这些行挡住（ForeignKeyViolation）。所以删用户前先把所有指向 users 的
    外键列置空，用例结束再把它们挂回测试主体 —— 身份相关的断言要的是"没有用户"，
    而不是"顺带把别人的学习数据删掉"。
    """
    from database import SessionLocal
    from models import User
    from core.models.schools import AuditLog

    s0 = SessionLocal()
    try:
        fk_cols = _user_fk_columns(s0)
    finally:
        s0.close()

    def wipe():
        s = SessionLocal()
        try:
            s.query(AuditLog).filter(AuditLog.table_name == "users").delete()
            _detach_user_refs(s, fk_cols)
            s.query(User).delete()
            s.commit()
        finally:
            s.close()

    def restore():
        """把测试主体和它的个人域数据归属补回来。"""
        s = SessionLocal()
        try:
            if s.query(User).filter(User.id == TEST_USER_ID).first() is None:
                s.add(User(
                    id=TEST_USER_ID, username="pytest",
                    password_hash="!disabled-test-principal",
                    display_name="pytest", role="admin", is_active=True,
                    must_change_password=False, token_version=0,
                ))
                s.flush()
            for table, col in fk_cols:
                s.execute(text(
                    f'UPDATE "{table}" SET "{col}" = :uid '
                    f'WHERE "{col}" IS NULL'
                ), {"uid": TEST_USER_ID})
            s.commit()
        finally:
            s.close()

    wipe()
    saved = {dep: app_module.dependency_overrides.pop(dep, None) for dep in (current_user, enforce_access)}
    security.login_limiter.reset()
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", ADMIN_PW)
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    s = SessionLocal()
    try:
        ensure_bootstrap_admin(s)
    finally:
        s.close()
    yield app_module
    while _OPEN:
        _OPEN.pop().close()
    security.login_limiter.reset()
    for dep, fn in saved.items():
        if fn is not None:
            app_module.dependency_overrides[dep] = fn
    wipe()
    restore()


def _login(client, username="pyy", password=ADMIN_PW):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _bootstrap_and_change(app):
    c = TestClient(app)
    assert _login(c).status_code == 200
    r = c.post("/api/auth/change-password", json={"old_password": ADMIN_PW, "new_password": NEW_PW})
    assert r.status_code == 200, r.text
    return c


def test_password_hash_is_salted_pbkdf2_and_never_plaintext():
    a, b = hash_password("secret-123"), hash_password("secret-123")
    assert a != b and a.startswith("pbkdf2_sha256$")
    assert "secret-123" not in a
    assert verify_password("secret-123", a) and not verify_password("secret-124", a)
    assert not verify_password("x", "garbage")


def test_bootstrap_admin_is_idempotent_and_forces_password_change(auth_app):
    from database import SessionLocal
    from models import User

    s = SessionLocal()
    try:
        assert ensure_bootstrap_admin(s) is None
        users = s.query(User).all()
        assert [(u.username, u.role, u.must_change_password) for u in users] == [("pyy", "admin", True)]
        assert ADMIN_PW not in users[0].password_hash
    finally:
        s.close()


def test_unauthenticated_requests_get_401(auth_app):
    c = TestClient(auth_app)
    r = c.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED"
    assert c.get("/api/admin/users").status_code == 401
    assert c.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_login_sets_httponly_strict_cookies_and_gates_until_password_changed(auth_app):
    c = TestClient(auth_app)
    bad = _login(c, password="wrong-password")
    assert bad.status_code == 401 and bad.json()["message"] == "用户名或密码错误"

    r = _login(c, username="PYY")
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is True
    set_cookie = ";".join(r.headers.get_list("set-cookie")).lower()
    assert "kaoyan_access=" in set_cookie and "kaoyan_refresh=" in set_cookie
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie
    assert "path=/api/auth" in set_cookie

    assert c.get("/api/auth/me").json()["username"] == "pyy"
    gated = c.get("/api/admin/users")
    assert gated.status_code == 403 and gated.json()["code"] == "PASSWORD_CHANGE_REQUIRED"


def test_change_password_revokes_old_tokens(auth_app):
    c = TestClient(auth_app)
    old_access = _login(c).json()["access_token"]
    weak = c.post("/api/auth/change-password", json={"old_password": ADMIN_PW, "new_password": "short"})
    assert weak.status_code == 400
    wrong = c.post("/api/auth/change-password", json={"old_password": "nope", "new_password": NEW_PW})
    assert wrong.status_code == 400

    ok = c.post("/api/auth/change-password", json={"old_password": ADMIN_PW, "new_password": NEW_PW})
    assert ok.status_code == 200 and ok.json()["must_change_password"] is False
    assert c.get("/api/admin/users").status_code == 200
    stale = TestClient(auth_app).get("/api/auth/me", headers={"Authorization": f"Bearer {old_access}"})
    assert stale.status_code == 401
    assert _login(TestClient(auth_app), password=ADMIN_PW).status_code == 401
    assert _login(TestClient(auth_app), password=NEW_PW).status_code == 200


def test_login_rate_limit_locks_even_correct_password(auth_app):
    c = TestClient(auth_app)
    for _ in range(security.login_limiter.max_failures):
        assert _login(c, password="wrong-password").status_code == 401
    locked = _login(c)
    assert locked.status_code == 429 and locked.json()["code"] == "RATE_LIMITED"
    assert locked.json()["detail"]["retry_after"] > 0


def test_refresh_reissues_access_and_dies_after_reset(auth_app):
    admin = _bootstrap_and_change(auth_app)
    created = admin.post("/api/admin/users", json={"username": "stu1", "role": "user"})
    assert created.status_code == 201, created.text
    temp = created.json()["temporary_password"]
    uid = created.json()["user"]["id"]

    stu = TestClient(auth_app)
    assert _login(stu, "stu1", temp).status_code == 200
    stu.post("/api/auth/change-password", json={"old_password": temp, "new_password": NEW_PW})
    stu.cookies.delete("kaoyan_access")
    assert stu.get("/api/auth/me").status_code == 401
    refreshed = stu.post("/api/auth/refresh")
    assert refreshed.status_code == 200 and refreshed.json()["user"]["username"] == "stu1"
    assert stu.get("/api/auth/me").status_code == 200

    reset = admin.post(f"/api/admin/users/{uid}/reset-password")
    assert reset.status_code == 200 and reset.json()["temporary_password"]
    assert stu.get("/api/auth/me").status_code == 401
    assert stu.post("/api/auth/refresh").status_code == 401


def test_learner_cannot_reach_admin_and_last_admin_is_protected(auth_app):
    admin = _bootstrap_and_change(auth_app)
    created = admin.post("/api/admin/users", json={"username": "stu2", "password": NEW_PW})
    assert created.status_code == 201
    assert admin.post("/api/admin/users", json={"username": "STU2"}).status_code == 409

    stu = TestClient(auth_app)
    _login(stu, "stu2", NEW_PW)
    stu.post("/api/auth/change-password", json={"old_password": NEW_PW, "new_password": NEW_PW + "x"})
    denied = stu.get("/api/admin/users")
    assert denied.status_code == 403 and denied.json()["code"] == "FORBIDDEN"

    me = admin.get("/api/auth/me").json()
    assert admin.patch(f"/api/admin/users/{me['id']}", json={"role": "user"}).status_code == 400
    assert admin.patch(f"/api/admin/users/{me['id']}", json={"is_active": False}).status_code == 400

    sid = created.json()["user"]["id"]
    off = admin.patch(f"/api/admin/users/{sid}", json={"is_active": False})
    assert off.status_code == 200 and off.json()["is_active"] is False
    assert stu.get("/api/auth/me").status_code == 401

    listing = admin.get("/api/admin/users", params={"keyword": "stu"}).json()
    assert listing["total"] == 1 and listing["items"][0]["username"] == "stu2"
    assert "password_hash" not in listing["items"][0]


def test_user_admin_writes_are_audited(auth_app):
    from database import SessionLocal
    from core.models.schools import AuditLog

    admin = _bootstrap_and_change(auth_app)
    uid = admin.post("/api/admin/users", json={"username": "stu3"}).json()["user"]["id"]
    admin.patch(f"/api/admin/users/{uid}", json={"display_name": "三号"})
    admin.post(f"/api/admin/users/{uid}/reset-password")
    s = SessionLocal()
    try:
        rows = s.query(AuditLog).filter(AuditLog.table_name == "users", AuditLog.record_id == uid) \
            .order_by(AuditLog.id).all()
        assert [r.action for r in rows] == ["INSERT", "UPDATE", "UPDATE"]
        assert all(r.operator_id is not None for r in rows)
        assert all("password_hash" not in (r.after_data or {}) for r in rows)
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# 全站默认拒绝（utils/access_policy.py）
# --------------------------------------------------------------------------- #
def test_every_api_route_carries_the_access_gate(app_module):
    from fastapi.routing import APIRoute

    missing = [
        r.path for r in app_module.routes
        if isinstance(r, APIRoute)
        and not any(d.call is enforce_access for d in r.dependant.dependencies)
    ]
    assert missing == []


@pytest.mark.parametrize("method,path,admin", [
    ("GET", "/api/backup/list", True),
    ("GET", "/api/admin/schools", True),
    ("GET", "/api/kb/health", True),
    ("GET", "/api/kb-import/tasks", True),
    ("GET", "/api/netdisk/platform-config/baidu", True),
    ("GET", "/api/taxonomy/tree", False),
    ("POST", "/api/taxonomy/nodes", True),
    ("PUT", "/api/settings", True),
    ("GET", "/api/settings", False),
    ("POST", "/api/quiz/questions", True),
    ("PUT", "/api/quiz/questions/12", True),
    ("POST", "/api/quiz/submit", False),
    # 2026-10-18 安全加固（access_policy.ADMIN_ENDPOINTS §B3）：题目复核/作废改动的是
    # **共享题库**，网盘 sync 用的是**共享凭据**并写共享文件，两者都是管理操作。
    # 旧期望（False）是加固前的口径，这里按现行策略校正。
    ("POST", "/api/quiz/review/12", True),
    ("POST", "/api/quiz/batch-delete", True),
    # 错题批量删除是**个人域**（端点内 scoped 限定本人），普通用户必须可用。
    ("POST", "/api/errors/batch-delete", False),
    ("DELETE", "/api/papers/7", True),
    # 组卷写共享 papers；答案交叉校验写 answer_candidates 并改题目置信度
    ("POST", "/api/papers/build", True),
    ("POST", "/api/answers/check", True),
    ("POST", "/api/answers/check-batch", True),
    ("POST", "/api/papers/attempts/start", False),
    ("POST", "/api/netdisk/files/9/ingest", True),
    # 同上：同步写共享网盘缓存，属管理操作（2026-10-18 §B3）。
    ("POST", "/api/netdisk/sync", True),
    ("POST", "/api/ai/chat", False),
    ("POST", "/api/ai/providers/3/test", True),
    ("POST", "/api/kaoyan/spider/run", True),
    ("POST", "/api/kaoyan/assistant/query", False),
])
def test_admin_classification(method, path, admin):
    assert needs_admin(method, path) is admin


def test_public_paths():
    assert is_public("/api/health") and is_public("/api/auth/login") and is_public("/")
    assert is_public("/assets/index.js")
    assert not is_public("/api/auth/me") and not is_public("/api/dashboard/summary")
    assert not is_public("/api/healthz")


def test_gate_enforced_end_to_end(auth_app):
    anon = TestClient(auth_app)
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/auth/status").status_code == 200
    r = anon.get("/api/settings")
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED"
    assert anon.post("/api/quiz/submit", json={}).status_code == 401

    admin = _bootstrap_and_change(auth_app)
    assert admin.post("/api/admin/users", json={"username": "stu4", "password": NEW_PW}).status_code == 201
    assert admin.get("/api/settings").status_code == 200

    stu = TestClient(auth_app)
    _login(stu, "stu4", NEW_PW)
    gated = stu.get("/api/settings")
    assert gated.status_code == 403 and gated.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    stu.post("/api/auth/change-password", json={"old_password": NEW_PW, "new_password": NEW_PW + "x"})

    assert stu.get("/api/settings").status_code == 200
    for method, path in [("PUT", "/api/settings"), ("POST", "/api/quiz/questions"),
                         ("GET", "/api/backup"), ("POST", "/api/kaoyan/spider/run")]:
        r = stu.request(method, path, json={})
        assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN", (method, path, r.text)


# --------------------------------------------------------------------------- #
# 用户软删除（2026-10-19：DELETE 原本 405 无端点 → deleted_at 软删 + 可恢复）
# --------------------------------------------------------------------------- #
def test_soft_delete_hides_user_blocks_login_and_is_restorable(auth_app):
    admin = _bootstrap_and_change(auth_app)
    uid = admin.post("/api/admin/users",
                     json={"username": "todel", "password": "Todel-Pass-1"}).json()["user"]["id"]

    # 删除前可见
    assert "todel" in [u["username"] for u in admin.get("/api/admin/users").json()["items"]]

    r = admin.request("DELETE", f"/api/admin/users/{uid}")
    assert r.status_code == 200, r.text

    # 默认列表隐藏，include_deleted 才带出
    assert "todel" not in [u["username"] for u in admin.get("/api/admin/users").json()["items"]]
    assert "todel" in [u["username"] for u in
                       admin.get("/api/admin/users?include_deleted=true").json()["items"]]

    # 已删用户不能登录（密码正确也拒）
    c2 = TestClient(auth_app)
    assert _login(c2, "todel", "Todel-Pass-1").status_code == 401

    # 恢复后可登录
    assert admin.post(f"/api/admin/users/{uid}/restore").status_code == 200
    c3 = TestClient(auth_app)
    assert _login(c3, "todel", "Todel-Pass-1").status_code == 200


def test_soft_delete_refuses_self_and_double_delete(auth_app):
    admin = _bootstrap_and_change(auth_app)
    my_id = admin.get("/api/auth/me").json()["id"]

    # 不能删自己
    r = admin.request("DELETE", f"/api/admin/users/{my_id}")
    assert r.status_code == 400 and "自己" in r.json()["message"]

    # 重复删 → 404
    uid = admin.post("/api/admin/users", json={"username": "twice"}).json()["user"]["id"]
    assert admin.request("DELETE", f"/api/admin/users/{uid}").status_code == 200
    assert admin.request("DELETE", f"/api/admin/users/{uid}").status_code == 404


def test_soft_delete_kills_existing_session_immediately(auth_app):
    """删除要立刻断掉既有会话，否则被删用户仍能用旧 token 操作。"""
    admin = _bootstrap_and_change(auth_app)
    uid = admin.post("/api/admin/users",
                     json={"username": "sessuser", "password": "Sess-Pass-1"}).json()["user"]["id"]
    u = TestClient(auth_app)
    assert _login(u, "sessuser", "Sess-Pass-1").status_code == 200
    assert u.get("/api/auth/me").status_code == 200

    assert admin.request("DELETE", f"/api/admin/users/{uid}").status_code == 200
    # 旧会话立即失效
    assert u.get("/api/auth/me").status_code == 401


def test_deleted_username_still_reserved_until_restore(auth_app):
    """软删期间用户名仍被 UNIQUE 占用——这是"可恢复"的代价，删除后建同名应 409。"""
    admin = _bootstrap_and_change(auth_app)
    uid = admin.post("/api/admin/users", json={"username": "reserved"}).json()["user"]["id"]
    assert admin.request("DELETE", f"/api/admin/users/{uid}").status_code == 200
    # 再建同名 → 409 冲突
    assert admin.post("/api/admin/users", json={"username": "reserved"}).status_code == 409
    # 恢复后同名恢复可登录
    assert admin.post(f"/api/admin/users/{uid}/restore").status_code == 200
