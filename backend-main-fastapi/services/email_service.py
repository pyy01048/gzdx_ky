# -*- coding: utf-8 -*-
"""邮件发送（《用户管理界面.md》邮箱版：注册验证 / 找回密码 / 重置通知）。

两种模式：
* ``smtp``    —— 配置了 SMTP_HOST 时走真实 SMTP（SSL/STARTTLS 自动按端口选择）。
* ``outbox``  —— 未配置 SMTP 时的本机降级：邮件写入 ``DATA_DIR/outbox/*.eml``
                 并把链接打进服务器日志。**不是静默丢弃**——本机自用场景
                 （平台当前形态）管理员/用户可以从 outbox 拿到验证链接，
                 保证"邮箱注册/找回"流程在没有 SMTP 凭据时依然可走通。

安全纪律（方案 §3.1）：
* 链接域名一律取服务端配置 ``APP_URL``，绝不从请求 Host 头拼接（防 Host 头注入）。
* 发送失败只记日志并返回 False，调用方对外仍返回无差别提示（不泄露账号存在性）。
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from typing import Optional

logger = logging.getLogger(__name__)


def app_url() -> str:
    """前端站点根地址（验证/重置链接的域名来源，只能来自服务端配置）。"""
    return (os.getenv("APP_URL") or "http://127.0.0.1:5175").rstrip("/")


def smtp_configured() -> bool:
    return bool((os.getenv("SMTP_HOST") or "").strip())


def _send_smtp(to: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "465") or 465)
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("MAIL_FROM", "").strip() or user
    use_ssl = (os.getenv("SMTP_SSL", "").strip() or ("1" if port == 465 else "0")) == "1"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("硕途考研平台", "utf-8")), sender))
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as s:
                if user:
                    s.login(user, password)
                s.sendmail(sender, [to], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.ehlo()
                if port != 25:
                    s.starttls(context=ssl.create_default_context())
                if user:
                    s.login(user, password)
                s.sendmail(sender, [to], msg.as_string())
        return True
    except Exception:  # noqa: BLE001 —— 发信失败不能把注册/找回流程打成 500
        logger.exception("SMTP 发信失败 to=%s subject=%s", to, subject)
        return False


def _send_outbox(to: str, subject: str, body: str) -> bool:
    """本机降级：落盘 outbox + 日志。返回 True 表示"已投递到 outbox"。"""
    from database import DATA_DIR

    outbox = os.path.join(DATA_DIR, "outbox")
    os.makedirs(outbox, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    safe_to = to.replace("@", "_at_").replace("/", "_")
    path = os.path.join(outbox, f"{stamp}_{safe_to}.eml")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"To: {to}\nSubject: {subject}\nDate: {stamp}\n\n{body}\n")
        logger.warning("[outbox 模式] 邮件已写入 %s（未配置 SMTP_HOST，真实发信需配置 SMTP）", path)
        return True
    except OSError:
        logger.exception("outbox 写入失败 to=%s", to)
        return False


def send_email(to: str, subject: str, body: str) -> bool:
    if smtp_configured():
        return _send_smtp(to, subject, body)
    return _send_outbox(to, subject, body)


# --------------------------------------------------------------------------- #
# 三类邮件模板（纯文本，链接域名来自 APP_URL）
# --------------------------------------------------------------------------- #
def send_verification_email(to: str, token: str, display_name: Optional[str] = None) -> bool:
    link = f"{app_url()}/verify-email?token={token}"
    name = display_name or to
    body = (
        f"{name}，你好：\n\n"
        "欢迎注册硕途考研学习平台。请点击下面的链接验证你的邮箱（24 小时内有效）：\n\n"
        f"{link}\n\n"
        "验证邮箱后才可以上传资料与使用找回密码。未验证不影响登录与浏览公开资料。\n"
        "如果这不是你本人的操作，请忽略本邮件。\n\n—— 硕途考研平台"
    )
    return send_email(to, "验证你的邮箱 · 硕途考研", body)


def send_reset_email(to: str, token: str, display_name: Optional[str] = None) -> bool:
    # 走后端 /api/auth/reset-link：token 进 httpOnly cookie 后 302 到干净路径，
    # 避免 token 以 URL 形式留在前端日志 / Referer（方案 §4.1）。
    link = f"{app_url()}/api/auth/reset-link?token={token}"
    name = display_name or to
    body = (
        f"{name}，你好：\n\n"
        "我们收到了你的密码找回请求。请点击下面的链接重置密码（60 分钟内有效，仅可使用一次）：\n\n"
        f"{link}\n\n"
        "如果你没有发起该请求，请忽略本邮件，你的密码不会发生变化。\n\n—— 硕途考研平台"
    )
    return send_email(to, "重置你的密码 · 硕途考研", body)


def send_reset_notice_email(to: str, when: str) -> bool:
    body = f"你的密码已于 {when} 被重置，所有已登录设备均已退出。\n如非本人操作，请立即联系管理员。\n\n—— 硕途考研平台"
    return send_email(to, "你的密码已被重置 · 硕途考研", body)
