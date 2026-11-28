# -*- coding: utf-8 -*-
"""doc 11 登录与权限：账号/会话/限流/角色/用户管理的真实链路（不走 conftest 的身份替身）。"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from conftest import TEST_USER_ID
from sqlalchemy import text
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


_FK_COLS_CACHE: list[tuple[str, str, bool]] | None = None


def _user_fk_columns(session):
    """列出所有 ``<table>.<column> REFERENCES users(id)``（含 SQL-only 表）。

    返回 (表, 列, 可空)：可空列置空即可解除引用；NOT NULL 列（如
    email_tokens.user_id）只能删行——置空会违反非空约束。

    缓存（2026-11-20）：该查询在 100+ 表 / 数千约束的测试库上要 1~3 分钟，
    而 fixture 每个用例都会调用一次——不缓存会让整个测试套件跑几小时（实测）。
    一个测试会话内 schema 不变，缓存安全。
    """
    global _FK_COLS_CACHE
    if _FK_COLS_CACHE is not None:
        return _FK_COLS_CACHE
    rows = session.execute(
        text("""
        SELECT tc.table_name, kcu.column_name, c.is_nullable
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        JOIN information_schema.columns c
          ON c.table_schema = tc.table_schema
         AND c.table_name = tc.table_name
         AND c.column_name = kcu.column_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND ccu.table_name = 'users'
    """)
    ).all()
    _FK_COLS_CACHE = [(t, c, n == "YES") for t, c, n in rows]
    return _FK_COLS_CACHE


def _detach_user_refs(session, fk_cols):
    """解除指向 users 的引用，让 ``DELETE FROM users`` 不被外键挡住。

    可空列置 NULL（结束后挂回测试主体）；NOT NULL 列直接删行
    （这些行本来就属于被清掉的账号，如邮箱 token）。
    """
    for table, col, nullable in fk_cols:
        if nullable:
            session.execute(text(f'UPDATE "{table}" SET "{col}" = NULL WHERE "{col}" IS NOT NULL'))
        else:
            session.execute(text(f'DELETE FROM "{table}" WHERE "{col}" IS NOT NULL'))


@pytest.fixture()
def auth_app(app_module, db_schema, monkeypatch):  # noqa: ARG001
    """清空 users、去掉身份替身、重置限流，结束后原样恢复。

    2026-10-20 修正：个人域表（goals / error_records / favorites …）都有
    ``user_id REFERENCES users(id)``，PG 上外键是真的。直接 ``DELETE FROM users``
    会被这些行挡住（ForeignKeyViolation）。所以删用户前先把所有指向 users 的
    外键列置空，用例结束再把它们挂回测试主体 —— 身份相关的断言要的是"没有用户"，
    而不是"顺带把别人的学习数据删掉"。
    """
    from core.models.schools import AuditLog
    from database import SessionLocal

    from models import AuthEvent, User

    s0 = SessionLocal()
    try:
        fk_cols = _user_fk_columns(s0)
    finally:
        s0.close()

    def wipe():
        s = SessionLocal()
        try:
            s.query(AuditLog).filter(AuditLog.table_name == "users").delete()
            # auth_events.user_id 可空，_detach 只会置空不删行：跨用例/跨运行累积
            # 会让「某事件恰好 1 条」这类计数断言失真。测试库里审计事件随账号一起清。
            s.query(AuthEvent).delete()
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
                s.add(
                    User(
                        id=TEST_USER_ID,
                        username="pytest",
                        password_hash="!disabled-test-principal",
                        display_name="pytest",
                        role="admin",
                        is_active=True,
                        must_change_password=False,
                        token_version=0,
                    )
                )
                s.flush()
            for table, col, nullable in fk_cols:
                if not nullable:
                    continue  # NOT NULL 归属列的行已在 wipe 时删除，无法挂回
                s.execute(text(f'UPDATE "{table}" SET "{col}" = :uid WHERE "{col}" IS NULL'), {"uid": TEST_USER_ID})
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


def _cookie_value(resp, name: str) -> str:
    """从响应 set-cookie 里取指定 cookie 的值（V3.12 后 body 不再含 token）。"""
    for ck in resp.headers.get_list("set-cookie"):
        if ck.lower().startswith(f"{name}="):
            return ck.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"响应未下发 cookie {name}")


def test_login_session_timestamps_use_timestamptz(auth_app):
    from database import SessionLocal

    from models import AuthSession

    c = TestClient(auth_app)
    assert _login(c).status_code == 200
    s = SessionLocal()
    try:
        row = s.query(AuthSession).one()
        assert row.created_at.tzinfo is not None
        assert row.last_used_at.tzinfo is not None
        assert row.expires_at.tzinfo is not None
        columns = s.execute(
            text("""
            SELECT count(*)
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'auth_sessions'
               AND column_name IN ('created_at', 'last_used_at', 'expires_at', 'revoked_at')
               AND data_type = 'timestamp with time zone'
        """)
        ).scalar_one()
        assert columns == 4
    finally:
        s.close()


def test_change_password_revokes_old_tokens(auth_app):
    c = TestClient(auth_app)
    old_access = _cookie_value(_login(c), "kaoyan_access")
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
    # V3.12 评审 C1：429 必须带标准 Retry-After 头（客户端可机读退避）
    assert int(locked.headers["Retry-After"]) > 0


def test_login_body_carries_no_token(auth_app):
    """V3.12 评审 B-03：会话凭据只走 httpOnly cookie，响应体不得含 token。"""
    c = TestClient(auth_app)
    r = _login(c)
    assert r.status_code == 200
    body = r.json()
    assert "access_token" not in body and "token_type" not in body
    assert body["user"]["username"] == "pyy"
    assert _cookie_value(r, "kaoyan_access") and _cookie_value(r, "kaoyan_refresh")


def test_refresh_rotation_single_use_and_replay_kills_family(auth_app):
    """V3.12 评审 C5：refresh 一次性轮换；旧 jti 重放 → 全部会话失效。"""
    c = TestClient(auth_app)
    r0 = _login(c)
    old_refresh = _cookie_value(r0, "kaoyan_refresh")

    r1 = c.post("/api/auth/refresh")
    assert r1.status_code == 200
    assert "access_token" not in r1.json()
    new_refresh = _cookie_value(r1, "kaoyan_refresh")
    assert new_refresh != old_refresh
    assert c.get("/api/auth/me").status_code == 200

    # 重放旧 refresh：不仅自身 401，还要吊销整个会话家族（token_version 自增）。
    # 用干净客户端 + 裸 Cookie 头重放：http.cookiejar 对显式 domain="testserver"
    # （无前导点）做严格域匹配会**静默丢 cookie**，401 就成了「没带 token」的假绿。
    replayer = TestClient(auth_app)
    replay = replayer.post("/api/auth/refresh", headers={"Cookie": f"kaoyan_refresh={old_refresh}"})
    assert replay.status_code == 401
    # 必须走「重放吊销」分支而非「缺 token/过期」分支，否则家族吊销没被验证
    assert replay.json()["message"] == "登录已失效，请重新登录"
    assert c.post("/api/auth/refresh").status_code == 401
    assert c.get("/api/auth/me").status_code == 401


def test_logout_revokes_session_server_side(auth_app):
    """V3.12 评审 C6：登出后旧 access/refresh 立即 401（不是只清 cookie）。"""
    c = TestClient(auth_app)
    r0 = _login(c)
    access = _cookie_value(r0, "kaoyan_access")
    refresh = _cookie_value(r0, "kaoyan_refresh")
    assert c.get("/api/auth/me").status_code == 200

    # 用登出前窃取的 token 重放：服务端会话已吊销 → 401。
    # 裸 Cookie 头（cookiejar 显式 domain 会静默丢 cookie，见轮换测试注释）。
    stolen = TestClient(auth_app)
    # 阳性对照：登出前同一份窃取 token 必须可用，证明后面的 401 是吊销所致
    assert stolen.get("/api/auth/me", headers={"Cookie": f"kaoyan_access={access}"}).status_code == 200
    assert c.post("/api/auth/logout").status_code == 200
    assert stolen.get("/api/auth/me", headers={"Cookie": f"kaoyan_access={access}"}).status_code == 401
    assert stolen.post("/api/auth/refresh", headers={"Cookie": f"kaoyan_refresh={refresh}"}).status_code == 401


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
    off = admin.patch(f"/api/admin/users/{sid}", json={"is_active": False, "disabled_reason": "测试禁用：离线账号清理"})
    assert off.status_code == 200 and off.json()["is_active"] is False
    assert stu.get("/api/auth/me").status_code == 401

    listing = admin.get("/api/admin/users", params={"keyword": "stu"}).json()
    assert listing["total"] == 1 and listing["items"][0]["username"] == "stu2"
    assert "password_hash" not in listing["items"][0]


def test_user_admin_writes_are_audited(auth_app):
    from core.models.schools import AuditLog
    from database import SessionLocal

    admin = _bootstrap_and_change(auth_app)
    uid = admin.post("/api/admin/users", json={"username": "stu3"}).json()["user"]["id"]
    admin.patch(f"/api/admin/users/{uid}", json={"display_name": "三号"})
    admin.post(f"/api/admin/users/{uid}/reset-password")
    s = SessionLocal()
    try:
        rows = (
            s.query(AuditLog)
            .filter(AuditLog.table_name == "users", AuditLog.record_id == uid)
            .order_by(AuditLog.id)
            .all()
        )
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
        r.path
        for r in app_module.routes
        if isinstance(r, APIRoute) and not any(d.call is enforce_access for d in r.dependant.dependencies)
    ]
    assert missing == []


@pytest.mark.parametrize(
    "method,path,admin",
    [
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
    ],
)
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
    for method, path in [
        ("PUT", "/api/settings"),
        ("POST", "/api/quiz/questions"),
        ("GET", "/api/backup"),
        ("POST", "/api/kaoyan/spider/run"),
    ]:
        r = stu.request(method, path, json={})
        assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN", (method, path, r.text)


# --------------------------------------------------------------------------- #
# 用户软删除（2026-10-19：DELETE 原本 405 无端点 → deleted_at 软删 + 可恢复）
# --------------------------------------------------------------------------- #
def test_soft_delete_hides_user_blocks_login_and_is_restorable(auth_app):
    admin = _bootstrap_and_change(auth_app)
    uid = admin.post("/api/admin/users", json={"username": "todel", "password": "Todel-Pass-1"}).json()["user"]["id"]

    # 删除前可见
    assert "todel" in [u["username"] for u in admin.get("/api/admin/users").json()["items"]]

    r = admin.request("DELETE", f"/api/admin/users/{uid}")
    assert r.status_code == 200, r.text

    # 默认列表隐藏，include_deleted 才带出
    assert "todel" not in [u["username"] for u in admin.get("/api/admin/users").json()["items"]]
    assert "todel" in [u["username"] for u in admin.get("/api/admin/users?include_deleted=true").json()["items"]]

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
    uid = admin.post("/api/admin/users", json={"username": "sessuser", "password": "Sess-Pass-1"}).json()["user"]["id"]
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


def test_rbac_matrix_admin_endpoints_reject_user_and_anonymous(auth_app):
    """V3.12 评审 C3/C4：管理端点越权矩阵（user→403，匿名→401）。"""
    admin = _bootstrap_and_change(auth_app)
    created = admin.post("/api/admin/users", json={"username": "rbac1", "role": "user"})
    assert created.status_code == 201, created.text
    temp = created.json()["temporary_password"]

    stu = TestClient(auth_app)
    assert _login(stu, "rbac1", temp).status_code == 200
    assert stu.post("/api/auth/change-password", json={"old_password": temp, "new_password": NEW_PW}).status_code == 200

    admin_only_gets = [
        "/api/admin/users",
        "/api/admin/users/auth-events",
        "/api/health/detail",
        "/api/performance",
        "/api/storage",
    ]
    for path in admin_only_gets:
        assert stu.get(path).status_code == 403, f"user 应 403: {path}"
    anon = TestClient(auth_app)
    for path in admin_only_gets:
        assert anon.get(path).status_code == 401, f"匿名应 401: {path}"

    # documents 写操作（V3.12 整改前 12 个写端点无鉴权，匿名可删文档）
    assert stu.post("/api/documents/1/parse").status_code == 403
    assert stu.request("DELETE", "/api/documents/1").status_code == 403
    assert anon.post("/api/documents/1/parse").status_code == 401
    assert anon.request("DELETE", "/api/documents/1").status_code == 401

    # 访客可读白名单（2026-11-20 访客扩容既定决策）：文库/教材清单匿名可读
    assert anon.get("/api/documents", params={"page_size": 1}).status_code == 200
    assert anon.get("/api/textbooks", params={"page_size": 1}).status_code == 200

    # 公共健康探针：零泄露（无 kb 表行数 / git_sha），且强制分页边界 422
    body = anon.get("/api/health").json()
    assert body.get("status") == "ok"
    assert "kb" not in body and "git_sha" not in body
    assert anon.get("/api/documents", params={"page_size": 101}).status_code == 422
    assert anon.get("/api/documents", params={"page": 0}).status_code == 422
    assert anon.get("/api/textbooks", params={"page_size": 201}).status_code == 422
