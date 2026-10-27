"""账号认证与角色授权（doc 11 F11-01/02/03/08）。

会话走 httpOnly cookie（access + refresh），同时接受 ``Authorization: Bearer``。
用 cookie 而不是前端存 token 的原因：iframe 预览、``<a download>``、CSV 导出、
SSE 这些浏览器自己发起的请求带不了自定义头，cookie 是唯一不用逐处补丁的通道，
也省掉了旧方案把密码塞进 ``?password=`` 落进访问日志的问题。
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from types import SimpleNamespace
from typing import Optional

import jwt
from fastapi import Depends, Request, status
from sqlalchemy.orm import Session

from database import get_db
from utils.exceptions import BusinessException, ErrorCode

logger = logging.getLogger(__name__)

ACCESS_COOKIE = "kaoyan_access"
REFRESH_COOKIE = "kaoyan_refresh"
REFRESH_COOKIE_PATH = "/api/auth"

ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLES = (ROLE_ADMIN, ROLE_USER)

PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
MIN_PASSWORD_LEN = 8


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


ACCESS_MINUTES = _env_int("JWT_ACCESS_MIN", 20)
REFRESH_DAYS = _env_int("JWT_REFRESH_DAYS", 14)


# --------------------------------------------------------------------------- #
# 密码哈希：标准库 PBKDF2（免编译依赖，2C2G 机器 pip 不会卡在 bcrypt 构建）
# --------------------------------------------------------------------------- #
_PBKDF2_ITERS = 240_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, dk_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), dk_hex)
    except (ValueError, AttributeError):
        return False


def validate_new_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LEN:
        raise BusinessException(
            code=ErrorCode.INVALID_PARAMETER,
            message=f"新密码至少 {MIN_PASSWORD_LEN} 位",
        )


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
_secret_cache: Optional[bytes] = None


def _jwt_secret() -> bytes:
    """JWT_SECRET 优先；未配置时从凭据主密钥派生。

    派生而不是进程内随机：多 worker / 重启后签名必须一致，否则每次部署
    所有人被踢下线、两个 worker 互不认对方签的 token。
    """
    global _secret_cache
    if _secret_cache is None:
        raw = (os.getenv("JWT_SECRET") or "").strip()
        if raw:
            _secret_cache = raw.encode("utf-8")
        else:
            from utils.secret_codec import _load_key

            _secret_cache = hmac.new(_load_key(), b"kaoyan-jwt-v1", hashlib.sha256).digest()
    return _secret_cache


def _encode(user, typ: str, ttl: datetime.timedelta) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "ver": int(user.token_version or 0),
        "typ": typ,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def create_access_token(user) -> str:
    return _encode(user, "access", datetime.timedelta(minutes=ACCESS_MINUTES))


def create_refresh_token(user) -> str:
    return _encode(user, "refresh", datetime.timedelta(days=REFRESH_DAYS))


def decode_token(token: str, typ: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("typ") == typ else None


# --------------------------------------------------------------------------- #
# cookie
# --------------------------------------------------------------------------- #
def _secure(request: Request) -> bool:
    # 反代后面靠 uvicorn --proxy-headers 把 scheme 还原成 https
    return request.url.scheme == "https"


def set_session_cookies(response, request: Request, user) -> str:
    access = create_access_token(user)
    secure = _secure(request)
    response.set_cookie(
        ACCESS_COOKIE, access, max_age=ACCESS_MINUTES * 60,
        httponly=True, samesite="strict", secure=secure, path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE, create_refresh_token(user), max_age=REFRESH_DAYS * 86400,
        httponly=True, samesite="strict", secure=secure, path=REFRESH_COOKIE_PATH,
    )
    return access


def clear_session_cookies(response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


# --------------------------------------------------------------------------- #
# 依赖：current_user / require_admin
# --------------------------------------------------------------------------- #
def _unauthorized(message: str = "未登录或登录已过期") -> BusinessException:
    return BusinessException(
        code=ErrorCode.UNAUTHORIZED, message=message, status_code=status.HTTP_401_UNAUTHORIZED
    )


def _bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip() or None
    return None


def load_token_user(db: Session, payload: Optional[dict]):
    from models import User

    if not payload:
        return None
    try:
        uid = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    user = db.get(User, uid)
    # 已软删除（deleted_at 非空）或已禁用的账号一律视为不存在：
    # 删除要立刻断掉既有会话，否则被删用户仍能用旧 token 继续操作。
    if user is None or not user.is_active or user.deleted_at is not None:
        return None
    if int(payload.get("ver", -1)) != int(user.token_version or 0):
        return None
    return user


# 改密前仍可访问的接口：其余一律 403，前端据 code 跳强制改密页
_PASSWORD_CHANGE_ALLOWED = (
    "/api/auth/me",
    "/api/auth/change-password",
    "/api/auth/logout",
)


def current_user(request: Request, db: Session = Depends(get_db)):
    token = _bearer(request) or request.cookies.get(ACCESS_COOKIE)
    user = load_token_user(db, decode_token(token, "access") if token else None)
    if user is None:
        raise _unauthorized()
    if user.must_change_password and request.url.path not in _PASSWORD_CHANGE_ALLOWED:
        raise BusinessException(
            code=PASSWORD_CHANGE_REQUIRED,
            message="请先修改初始密码",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    request.state.user = user
    return user


def require_admin(user=Depends(current_user)):
    if user.role != ROLE_ADMIN:
        raise BusinessException(
            code=ErrorCode.FORBIDDEN, message="需要管理员权限", status_code=status.HTTP_403_FORBIDDEN
        )
    return user


_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def admin_for_writes(request: Request, user=Depends(current_user)):
    """共享数据（题库/知识库/科目树…）：登录即可读，写需要管理员。"""
    if request.method in _WRITE_METHODS and user.role != ROLE_ADMIN:
        raise BusinessException(
            code=ErrorCode.FORBIDDEN, message="需要管理员权限", status_code=status.HTTP_403_FORBIDDEN
        )
    return user


def user_snapshot(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": bool(user.is_active),
        "must_change_password": bool(user.must_change_password),
        "last_login_at": user.last_login_at,
        "created_at": getattr(user, "created_at", None),
        "deleted_at": getattr(user, "deleted_at", None),
    }


def stub_principal(role: str = ROLE_ADMIN) -> SimpleNamespace:
    """测试套件用的已登录身份（conftest 覆盖 current_user）。"""
    return SimpleNamespace(
        id=0, username="pytest", display_name="pytest", role=role,
        is_active=True, must_change_password=False, token_version=0,
        last_login_at=None, created_at=None,
    )


# --------------------------------------------------------------------------- #
# 登录限流：进程内滑动窗口（2G 机器不上 Redis）
# --------------------------------------------------------------------------- #
class LoginRateLimiter:
    """同一 IP+用户名 window 秒内失败 max_failures 次即锁 lock 秒。

    多 worker 下每个进程各计各的，实际上限是 max_failures × workers；
    Nginx 的 limit_req 在入口再挡一层（doc 10/11 e.7）。
    """

    def __init__(self, max_failures: int = 10, window: int = 300, lock: int = 300):
        """失败 max_failures 次锁 lock 秒。

        2026-10-18 调参：原 5 次/锁 900s 对单用户自用场景过紧——
        用户几次手误即被锁 15 分钟，且锁定期间无法自助恢复（限流器在
        进程内存，只能等服务重启）。现放宽到 10 次/锁 5 分钟：
        防爆破由 nginx limit_req（429）+ 强密码承担，应用层只做兜底。
        """
        self.max_failures = max_failures
        self.window = window
        self.lock = lock
        self._fails: dict[str, deque] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}
        self._mu = threading.Lock()

    @staticmethod
    def key(ip: str, username: str) -> str:
        return f"{ip}|{(username or '').strip().lower()}"

    def retry_after(self, key: str) -> int:
        with self._mu:
            until = self._locked_until.get(key, 0.0)
            left = until - time.monotonic()
            if left <= 0:
                self._locked_until.pop(key, None)
                return 0
            return int(left) + 1

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._mu:
            q = self._fails[key]
            q.append(now)
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_failures:
                self._locked_until[key] = now + self.lock
                q.clear()

    def success(self, key: str) -> None:
        with self._mu:
            self._fails.pop(key, None)
            self._locked_until.pop(key, None)

    def reset(self) -> None:
        with self._mu:
            self._fails.clear()
            self._locked_until.clear()


login_limiter = LoginRateLimiter(
    max_failures=_env_int("LOGIN_MAX_FAILURES", 5),
    window=_env_int("LOGIN_FAIL_WINDOW_SEC", 300),
    lock=_env_int("LOGIN_LOCK_SEC", 900),
)


def client_ip(request: Request) -> str:
    # 不读 X-Forwarded-For：可伪造，任何人都能换 IP 绕开限流。
    # 部署在反代后时由 uvicorn --proxy-headers --forwarded-allow-ips 还原真实地址。
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------- #
# 内置管理员
# --------------------------------------------------------------------------- #
BOOTSTRAP_ADMIN = "pyy"


def ensure_bootstrap_admin(db: Session) -> Optional[str]:
    """users 为空时建内置管理员，返回建出的用户名（已有用户则什么都不做）。

    初始密码取 ADMIN_INITIAL_PASSWORD；没配就随机生成并只在日志里打印一次。
    无论哪种都置 must_change_password，首登必须改。
    """
    from models import User

    if db.query(User.id).first() is not None:
        return None
    username = (os.getenv("ADMIN_USERNAME") or BOOTSTRAP_ADMIN).strip() or BOOTSTRAP_ADMIN
    password = os.getenv("ADMIN_INITIAL_PASSWORD") or ""
    generated = not password
    if generated:
        password = secrets.token_urlsafe(12)
    db.add(User(
        username=username,
        password_hash=hash_password(password),
        display_name="管理员",
        role=ROLE_ADMIN,
        is_active=True,
        must_change_password=True,
        token_version=0,
    ))
    db.commit()
    if generated:
        logger.warning(
            "已创建内置管理员 %s，随机初始密码：%s（仅显示这一次，首登强制改密）",
            username, password,
        )
    else:
        logger.warning("已创建内置管理员 %s（密码取自 ADMIN_INITIAL_PASSWORD，首登强制改密）", username)
    return username
