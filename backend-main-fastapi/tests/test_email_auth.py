# -*- coding: utf-8 -*-
"""邮箱注册 / 验证 / 找回密码 / 状态机 / RBAC 的真实链路测试（《用户管理界面.md》）。

复用 test_auth 的 auth_app（清空 users、去掉身份替身）与 TestClient（cookie 罐）。
邮件发送被替身捕获：断言"该发的信发了、不该发的信坚决不发"，并从链接里取 token。
"""

from __future__ import annotations

import re
import time

import pytest
from test_auth import ADMIN_PW, TestClient, auth_app  # noqa: F401 —— fixture 复用
from utils.security import (
    forgot_email_limiter,
    forgot_ip_limiter,
    register_limiter,
)

REG_PW = "Register-Pass-1"
NEW_PW = "Reset-Pass-22"


@pytest.fixture()
def mail_out(monkeypatch):
    """捕获 send_email，返回 (收件人, 主题, 正文) 列表。"""
    from services import email_service

    sent = []

    def fake_send(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(email_service, "send_email", fake_send)
    return sent


@pytest.fixture()
def email_app(auth_app, mail_out):  # noqa: F811
    register_limiter.reset()
    forgot_ip_limiter.reset()
    forgot_email_limiter.reset()
    yield auth_app
    register_limiter.reset()
    forgot_ip_limiter.reset()
    forgot_email_limiter.reset()


def _register(c, email="stu@example.com", password=REG_PW):
    return c.post("/api/auth/register", json={"email": email, "password": password})


def _admin_client(app):
    """内置管理员首登强制改密：先改密再调管理接口，否则一律 403。"""
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": "pyy", "password": ADMIN_PW}).status_code == 200
    r = c.post("/api/auth/change-password", json={"old_password": ADMIN_PW, "new_password": "Admin-Pass-9x"})
    assert r.status_code == 200, r.text
    return c


def _token_from(sent, pattern):
    assert sent, "应当发出一封邮件"
    m = re.search(pattern, sent[-1][2])
    assert m, f"邮件正文里找不到 token：{sent[-1][2]}"
    return m.group(1)


def _verify(c, sent):
    token = _token_from(sent, r"/verify-email\?token=([A-Za-z0-9_\-]+)")
    r = c.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 200, r.text
    return token


def test_register_verify_login_full_loop(email_app, mail_out):
    c = TestClient(email_app)
    r = _register(c)
    assert r.status_code == 200
    assert "如果该邮箱可用" in r.json()["message"]  # 无差别提示
    assert len(mail_out) == 1 and "验证" in mail_out[0][1]

    from database import SessionLocal
    from models import User

    s = SessionLocal()
    u = s.query(User).filter(User.email == "stu@example.com").first()
    assert u is not None and u.status == "unverified" and u.email_verified_at is None
    uid = u.id
    s.close()

    # 未验证也能登录（软门槛），但 payload 标记未验证
    r = c.post("/api/auth/login", json={"username": "stu@example.com", "password": REG_PW})
    assert r.status_code == 200 and r.json()["email_verified"] is False

    _verify(c, mail_out)
    s = SessionLocal()
    u = s.get(User, uid)
    assert u.email_verified_at is not None and u.status == "active"
    s.close()

    # 验证链接一次性：重放失败
    token = _token_from(mail_out, r"/verify-email\?token=([A-Za-z0-9_\-]+)")
    assert c.post("/api/auth/verify-email", json={"token": token}).status_code == 400


def test_register_existing_email_is_indistinguishable(email_app, mail_out):
    c = TestClient(email_app)
    assert _register(c).status_code == 200
    _verify(c, mail_out)
    n_users_before = len(mail_out)
    r = _register(c)  # 已注册已验证 → 不发信、不报错、提示一致
    assert r.status_code == 200
    assert r.json()["message"] == "如果该邮箱可用，验证邮件已发送，请查收（记得看看垃圾箱）。"
    assert len(mail_out) == n_users_before


def test_register_rejects_weak_password_and_disposable(email_app):
    c = TestClient(email_app)
    assert _register(c, password="alllowercase1").status_code == 400  # 只 2 类
    assert _register(c, password="Ab1!").status_code == 400  # 太短
    assert _register(c, email="x@mailinator.com").status_code == 400
    assert _register(c, email="not-an-email").status_code == 400


def test_forgot_password_branches_and_timing(email_app, mail_out):
    c = TestClient(email_app)
    # 不存在的邮箱：通用提示、不发信、耗时 ≥150ms（计时侧信道抹平）
    t0 = time.monotonic()
    r = c.post("/api/auth/forgot-password", json={"email": "ghost@example.com"})
    assert r.status_code == 200 and time.monotonic() - t0 >= 0.15
    assert not mail_out

    # 未验证邮箱：不发信（防抢注劫持），审计 blocked_unverified
    assert _register(c).status_code == 200
    # 注册验证信留底：随后清空 mail_out 以断言 forgot 对未验证账号不发信，
    # 但验证步骤仍需用注册时那封信里的 token（forgot 不会补发验证信）。
    verify_sent = list(mail_out)
    mail_out.clear()
    forgot_email_limiter.reset()
    r = c.post("/api/auth/forgot-password", json={"email": "stu@example.com"})
    assert r.status_code == 200 and not mail_out
    from database import SessionLocal
    from models import AuthEvent

    s = SessionLocal()
    assert s.query(AuthEvent).filter(AuthEvent.event_type == "password_reset_blocked_unverified").count() == 1
    s.close()

    # 验证后：发重置邮件
    _verify(c, verify_sent)
    mail_out.clear()
    forgot_email_limiter.reset()
    r = c.post("/api/auth/forgot-password", json={"email": "stu@example.com"})
    assert r.status_code == 200 and len(mail_out) == 1


def test_reset_flow_cookie_redirect_one_time_and_password_binding(email_app, mail_out):
    c = TestClient(email_app)
    _register(c)
    _verify(c, mail_out)
    mail_out.clear()
    forgot_email_limiter.reset()
    c.post("/api/auth/forgot-password", json={"email": "stu@example.com"})
    token = _token_from(mail_out, r"/api/auth/reset-link\?token=([A-Za-z0-9_\-]+)")
    mail_out.clear()  # 重置链接信已取走 token；后面只断言重置通知信这一封

    # 邮件链接 → token 进 httpOnly cookie → 302 到干净路径
    r = c.get(f"/api/auth/reset-link?token={token}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/reset-password")
    assert "kaoyan_reset" in r.cookies
    assert "token=" not in r.headers["location"]

    assert c.post("/api/auth/reset-password/inspect", json={}).json()["valid"] is True
    r = c.post("/api/auth/reset-password", json={"new_password": NEW_PW})
    assert r.status_code == 200, r.text
    assert len(mail_out) == 1 and "已被重置" in mail_out[0][1]  # 重置通知邮件

    # 旧密码失效、新密码可登录；token 一次性
    assert c.post("/api/auth/login", json={"username": "stu@example.com", "password": REG_PW}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "stu@example.com", "password": NEW_PW}).status_code == 200
    assert (
        c.post("/api/auth/reset-password", json={"token": token, "new_password": "Another-Pass-3"}).status_code == 400
    )

    # 密码哈希绑定：改密后旧重置链接立即失效
    mail_out.clear()
    forgot_email_limiter.reset()
    c.post("/api/auth/forgot-password", json={"email": "stu@example.com"})
    token2 = _token_from(mail_out, r"/api/auth/reset-link\?token=([A-Za-z0-9_\-]+)")
    login = TestClient(email_app)
    login.post("/api/auth/login", json={"username": "stu@example.com", "password": NEW_PW})
    assert (
        login.post(
            "/api/auth/change-password", json={"old_password": NEW_PW, "new_password": "Third-Pass-44"}
        ).status_code
        == 200
    )
    assert (
        c.post("/api/auth/reset-password", json={"token": token2, "new_password": "Fourth-Pass-5"}).status_code == 400
    )


def test_forgot_ip_throttle(email_app, mail_out):
    c = TestClient(email_app)
    for i in range(3):
        forgot_email_limiter.reset()
        assert c.post("/api/auth/forgot-password", json={"email": f"nobody{i}@example.com"}).status_code == 200
    forgot_email_limiter.reset()
    r = c.post("/api/auth/forgot-password", json={"email": "nobody9@example.com"})
    assert r.status_code == 429


def test_disable_requires_reason_and_blocks_login_with_reason(email_app, mail_out):
    admin = _admin_client(email_app)
    c = TestClient(email_app)
    _register(c)
    _verify(c, mail_out)
    from database import SessionLocal
    from models import User

    s = SessionLocal()
    uid = s.query(User).filter(User.email == "stu@example.com").first().id
    s.close()

    assert admin.patch(f"/api/admin/users/{uid}", json={"is_active": False}).status_code == 400
    r = admin.patch(f"/api/admin/users/{uid}", json={"is_active": False, "disabled_reason": "发布违规资料"})
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    r = c.post("/api/auth/login", json={"username": "stu@example.com", "password": REG_PW})
    assert r.status_code == 403 and "发布违规资料" in r.json()["message"]
    # 禁用账号不发重置邮件
    mail_out.clear()
    forgot_email_limiter.reset()
    assert c.post("/api/auth/forgot-password", json={"email": "stu@example.com"}).status_code == 200
    assert not mail_out
    # 启用后回到 active
    r = admin.patch(f"/api/admin/users/{uid}", json={"is_active": True})
    assert r.status_code == 200 and r.json()["status"] == "active"


def test_doc_admin_role_and_permission_table(email_app):
    admin = _admin_client(email_app)
    r = admin.get("/api/admin/users/roles")
    assert r.status_code == 200
    roles = {x["role"]: x for x in r.json()["items"]}
    assert "doc_admin" in roles
    assert "doc:review" in roles["doc_admin"]["permissions"]
    assert "user:list" not in roles["doc_admin"]["permissions"]  # 审核权 ≠ 用户管理权
    assert "user:list" in roles["admin"]["permissions"]

    r = admin.post("/api/admin/users", json={"username": "docmgr", "role": "doc_admin"})
    assert r.status_code == 201
    uid = r.json()["user"]["id"]
    temp = r.json()["temporary_password"]
    d = TestClient(email_app)
    assert d.post("/api/auth/login", json={"username": "docmgr", "password": temp}).status_code == 200
    d.post("/api/auth/change-password", json={"old_password": temp, "new_password": "DocAdmin-Pass1"})
    # 文档管理员不能进用户管理
    assert d.get("/api/admin/users").status_code == 403
    # 管理员可以把 doc_admin 撤成 user（角色变更只能管理员执行）
    assert admin.patch(f"/api/admin/users/{uid}", json={"role": "user"}).status_code == 200


def test_admin_force_reset_email_mode_and_audit_events(email_app, mail_out):
    admin = _admin_client(email_app)
    c = TestClient(email_app)
    _register(c)
    _verify(c, mail_out)
    from database import SessionLocal
    from models import User

    s = SessionLocal()
    uid = s.query(User).filter(User.email == "stu@example.com").first().id
    s.close()
    mail_out.clear()
    r = admin.post(f"/api/admin/users/{uid}/reset-password", json={"mode": "email"})
    assert r.status_code == 200 and r.json()["mode"] == "email"
    assert len(mail_out) == 1 and "重置" in mail_out[0][1]
    # 审计只读可查
    r = admin.get("/api/admin/users/auth-events", params={"user_id": uid})
    assert r.status_code == 200
    types = [e["event_type"] for e in r.json()["items"]]
    assert "register" in types and "email_verified" in types and "admin_force_reset_email" in types
    # 用户详情带最近事件
    r = admin.get(f"/api/admin/users/{uid}")
    assert r.status_code == 200 and r.json()["recent_events"]


def test_deletion_cooling_off_and_cancel(email_app, mail_out):
    c = TestClient(email_app)
    _register(c)
    _verify(c, mail_out)
    assert c.post("/api/auth/login", json={"username": "stu@example.com", "password": REG_PW}).status_code == 200
    r = c.post("/api/auth/delete-request")
    assert r.status_code == 200
    # 冷静期内不可登录
    assert c.post("/api/auth/login", json={"username": "stu@example.com", "password": REG_PW}).status_code == 401
    # 凭原密码取消注销
    r = c.post("/api/auth/delete-cancel", json={"username": "stu@example.com", "password": REG_PW})
    assert r.status_code == 200
    assert c.post("/api/auth/login", json={"username": "stu@example.com", "password": REG_PW}).status_code == 200


def test_resend_verification_throttle(email_app, mail_out):
    c = TestClient(email_app)
    _register(c)
    n = len(mail_out)
    # 60 秒内重发：对外提示一致，但不再发信
    r = c.post("/api/auth/resend-verification", json={"email": "stu@example.com"})
    assert r.status_code == 200 and len(mail_out) == n
