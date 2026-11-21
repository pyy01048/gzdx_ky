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
from database import get_db
from fastapi import Depends, Request, status
from sqlalchemy.orm import Session
from utils.exceptions import BusinessException, ErrorCode

logger = logging.getLogger(__name__)

ACCESS_COOKIE = "kaoyan_access"
REFRESH_COOKIE = "kaoyan_refresh"
REFRESH_COOKIE_PATH = "/api/auth"

ROLE_ADMIN = "admin"
ROLE_DOC_ADMIN = "doc_admin"
ROLE_USER = "user"
ROLES = (ROLE_ADMIN, ROLE_DOC_ADMIN, ROLE_USER)

# 账号状态机（《用户管理界面.md》§5.1，core/sql/116 ck_users_status）
STATUS_UNVERIFIED = "unverified"
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUS_PENDING_DELETION = "pending_deletion"
STATUS_DELETED = "deleted"
# 允许登录的状态（unverified 是软门槛：可登录浏览，不可上传/找回密码）
LOGIN_OK_STATUSES = (STATUS_UNVERIFIED, STATUS_ACTIVE)

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
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except (ValueError, AttributeError):
        return False


def validate_new_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LEN:
        raise BusinessException(
            code=ErrorCode.INVALID_PARAMETER,
            message=f"新密码至少 {MIN_PASSWORD_LEN} 位",
        )


def password_category_count(password: str) -> int:
    """大小写字母 / 数字 / 特殊字符 四类中占了几类（邮箱版方案 §3.1）。"""
    cats = 0
    if any(c.islower() for c in password):
        cats += 1
    if any(c.isupper() for c in password):
        cats += 1
    if any(c.isdigit() for c in password):
        cats += 1
    if any(not c.isalnum() for c in password):
        cats += 1
    return cats


def validate_strong_password(password: str) -> None:
    """注册 / 邮箱找回密码的强度门：8–128 位且至少 3 类字符。"""
    if not isinstance(password, str) or not (MIN_PASSWORD_LEN <= len(password) <= 128):
        raise BusinessException(
            code=ErrorCode.INVALID_PARAMETER,
            message=f"密码需 {MIN_PASSWORD_LEN}–128 位",
        )
    if password_category_count(password) < 3:
        raise BusinessException(
            code=ErrorCode.INVALID_PARAMETER,
            message="密码需包含大写字母、小写字母、数字、特殊字符中的至少 3 类",
        )


def mask_email(email: Optional[str]) -> Optional[str]:
    """ab***@example.com 形式的脱敏（文档管理员待审队列用，§5.3）。"""
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    keep = local[:2] if len(local) > 2 else local[:1]
    return f"{keep}***@{domain}"


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


def _encode(user, typ: str, ttl: datetime.timedelta, extra: Optional[dict] = None) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "ver": int(user.token_version or 0),
        "typ": typ,
        "iat": now,
        "exp": now + ttl,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def create_access_token(user, sid: Optional[str] = None) -> str:
    return _encode(user, "access", datetime.timedelta(minutes=ACCESS_MINUTES), {"sid": sid} if sid else None)


def create_refresh_token(user, sid: Optional[str] = None, jti: Optional[str] = None) -> str:
    extra = {}
    if sid:
        extra["sid"] = sid
    if jti:
        extra["jti"] = jti
    return _encode(user, "refresh", datetime.timedelta(days=REFRESH_DAYS), extra or None)


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
    """cookie 是否带 Secure 属性（完善方案 08 §3.3）。

    1) 请求本身是 https（反代后靠 uvicorn --proxy-headers 还原 scheme）→ Secure
    2) APP_ENV=production → 默认 Secure（生产入口必须 TLS，失败即暴露配置问题）
       明文过渡期可显式 COOKIE_SECURE=0 临时关闭，整改完必须移除该开关
    """
    if request.url.scheme == "https":
        return True
    if (os.getenv("COOKIE_SECURE") or "").strip() == "0":
        return False
    from utils.access_policy import is_production

    return is_production()


def set_session_cookies(response, request: Request, user, sid: Optional[str] = None, jti: Optional[str] = None) -> str:
    access = create_access_token(user, sid)
    secure = _secure(request)
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=ACCESS_MINUTES * 60,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        create_refresh_token(user, sid, jti),
        max_age=REFRESH_DAYS * 86400,
        httponly=True,
        samesite="strict",
        secure=secure,
        path=REFRESH_COOKIE_PATH,
    )
    return access


def clear_session_cookies(response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


# --------------------------------------------------------------------------- #
# 服务端会话（120，V3.12 评审 C5/C6）：refresh 一次性轮换 + 登出即吊销
# --------------------------------------------------------------------------- #
def create_session(db: Session, request: Request, user) -> tuple:
    """登录成功后登记一行会话，返回 (sid, jti)。调用方负责 commit。"""
    import uuid

    from models import AuthSession
    from utils.timeutil import utcnow

    sid = uuid.uuid4().hex
    jti = uuid.uuid4().hex
    db.add(
        AuthSession(
            id=sid,
            user_id=user.id,
            refresh_jti=jti,
            expires_at=utcnow() + datetime.timedelta(days=REFRESH_DAYS),
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:300],
        )
    )
    # 顺手清理该用户已过期/已吊销 30 天以上的旧行，表不会无限膨胀
    cutoff = utcnow() - datetime.timedelta(days=30)
    db.query(AuthSession).filter(
        AuthSession.user_id == user.id,
        AuthSession.expires_at < cutoff,
    ).delete(synchronize_session=False)
    return sid, jti


def _live_session(db: Session, sid: str, user_id: int):
    from models import AuthSession
    from utils.timeutil import utcnow

    return (
        db.query(AuthSession)
        .filter(
            AuthSession.id == sid,
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
        .first()
    )


def rotate_refresh(db: Session, user, payload: dict):
    """消费一次性 refresh jti，返回新 jti；无效/重放返回 None。

    重放检测：jti 与会话当前值不符 = 旧 token 被再次使用（可能被盗），
    吊销整行会话并自增 token_version —— 该用户所有会话一并失效，
    攻击者与受害者都被迫重新登录（标准 refresh rotation 失效语义）。
    调用方负责 commit。
    """
    import uuid

    from utils.timeutil import utcnow

    sid = payload.get("sid")
    jti = payload.get("jti")
    if not sid or not jti:
        return None
    session = _live_session(db, sid, user.id)
    if session is None:
        return None
    if session.refresh_jti != jti:
        session.revoked_at = utcnow()
        user.token_version = int(user.token_version or 0) + 1
        logger.warning("检测到 refresh token 重放（user_id=%s, sid=%s），已吊销全部会话", user.id, sid)
        return None
    new_jti = uuid.uuid4().hex
    session.refresh_jti = new_jti
    session.last_used_at = utcnow()
    return new_jti


def revoke_session(db: Session, sid: Optional[str]) -> None:
    """登出吊销：只断当前会话，其他设备不受影响。调用方负责 commit。"""
    if not sid:
        return
    from models import AuthSession
    from utils.timeutil import utcnow

    db.query(AuthSession).filter(AuthSession.id == sid, AuthSession.revoked_at.is_(None)).update(
        {"revoked_at": utcnow()}, synchronize_session=False
    )


# --------------------------------------------------------------------------- #
# 依赖：current_user / require_admin
# --------------------------------------------------------------------------- #
def _unauthorized(message: str = "未登录或登录已过期") -> BusinessException:
    return BusinessException(code=ErrorCode.UNAUTHORIZED, message=message, status_code=status.HTTP_401_UNAUTHORIZED)


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
    # 状态机（116）：pending_deletion / deleted / disabled 同样拒绝；
    # 旧行 status 可能为 NULL（迁移前签发），按 is_active 口径放行。
    status = getattr(user, "status", None)
    if status is not None and status not in LOGIN_OK_STATUSES:
        return None
    if int(payload.get("ver", -1)) != int(user.token_version or 0):
        return None
    # 会话级吊销（120）：带 sid 的 token 必须对应一行未吊销、未过期的会话。
    # 登出只吊销本会话 → 该会话 access/refresh 立即 401，其他设备不受影响。
    # 无 sid 的旧 token（升级前签发，≤20 分钟寿命）按 ver 口径放行，平滑过渡。
    sid = payload.get("sid")
    if sid and _live_session(db, sid, user.id) is None:
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


def optional_user(request: Request, db: Session = Depends(get_db)):
    """可选登录依赖：匿名返回 None，供访客可读的共享接口使用（2026-11-20 访客扩容）。

    与 current_user 的唯一区别：无 token / token 失效不抛 401。
    强制改密门槛不放松：must_change_password 账号仍 403，不能借访客端点绕过。

    ⚠️ 调用方必须显式处理 user=None：scoped(Model, None) 恒真（见 utils/scope.py），
    把 None 直接传进个人域查询会读到**全部用户**的数据。正确姿势是先判空再查。
    """
    token = _bearer(request) or request.cookies.get(ACCESS_COOKIE)
    user = load_token_user(db, decode_token(token, "access") if token else None)
    if user is None:
        return None
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


def has_permission(db: Session, role: str, permission: str) -> bool:
    """操作级权限查 role_permission 表（116，映射不硬编码）。

    admin 兜底全权：表缺行时不至于把管理员锁在门外（种子数据由 116 写入）。
    """
    if role == ROLE_ADMIN:
        return True
    from models import RolePermission

    return (
        db.query(RolePermission).filter(RolePermission.role == role, RolePermission.permission == permission).first()
        is not None
    )


def require_permission(permission: str):
    """FastAPI 依赖工厂：按操作级权限拦截（文档管理员与管理员分权的关键）。"""

    def _dep(request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
        if not has_permission(db, user.role, permission):
            raise BusinessException(
                code=ErrorCode.FORBIDDEN,
                message=f"需要权限 {permission}",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return user

    return _dep


def require_verified_email(user=Depends(current_user)):
    """未验证邮箱的软门槛（邮箱版方案 §3.1）：可登录浏览，不可上传资料。"""
    if getattr(user, "status", None) == STATUS_UNVERIFIED:
        raise BusinessException(
            code=ErrorCode.FORBIDDEN,
            message="请先验证邮箱后再上传资料（验证邮件可在注册邮箱查收，或重新发送）",
            status_code=status.HTTP_403_FORBIDDEN,
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
        # 邮箱版用户管理（116）
        "email": getattr(user, "email", None),
        "email_verified_at": getattr(user, "email_verified_at", None),
        "status": getattr(user, "status", None) or ("active" if user.is_active else "disabled"),
        "disabled_reason": getattr(user, "disabled_reason", None),
        "deletion_requested_at": getattr(user, "deletion_requested_at", None),
        "last_login_ip": getattr(user, "last_login_ip", None),
        "login_count": int(getattr(user, "login_count", 0) or 0),
    }


def stub_principal(role: str = ROLE_ADMIN) -> SimpleNamespace:
    """测试套件用的已登录身份（conftest 覆盖 current_user）。"""
    return SimpleNamespace(
        id=0,
        username="pytest",
        display_name="pytest",
        role=role,
        is_active=True,
        must_change_password=False,
        token_version=0,
        last_login_at=None,
        created_at=None,
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


class WindowLimiter:
    """通用滑动窗口计数限流（注册 5 次/10 分钟、找回 3 次/小时等，邮箱版方案 §3.2/§4.2）。

    与 LoginRateLimiter 一样是进程内实现（2G 机器不上 Redis）；
    多 worker 下实际上限 = max_hits × workers，入口由 nginx limit_req 再挡一层。
    """

    def __init__(self, max_hits: int, window: int):
        self.max_hits = max_hits
        self.window = window
        self._hits: dict[str, deque] = defaultdict(deque)
        self._mu = threading.Lock()

    def retry_after(self, key: str) -> int:
        """已达上限时返回需等待的秒数，否则 0。"""
        now = time.monotonic()
        with self._mu:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_hits:
                return int(self.window - (now - q[0])) + 1
            return 0

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._mu:
            q = self._hits[key]
            q.append(now)
            while q and now - q[0] > self.window:
                q.popleft()

    def reset(self) -> None:
        with self._mu:
            self._hits.clear()


# 注册提交：单 IP 5 次/10 分钟（§3.2）
register_limiter = WindowLimiter(max_hits=_env_int("REGISTER_IP_MAX", 5), window=600)
# 找回密码：单 IP 3 次/小时 + 单邮箱 1 次/10 分钟（§4.2，账号查找之前执行）
forgot_ip_limiter = WindowLimiter(max_hits=_env_int("FORGOT_IP_MAX", 3), window=3600)
forgot_email_limiter = WindowLimiter(max_hits=1, window=600)


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
    db.add(
        User(
            username=username,
            password_hash=hash_password(password),
            display_name="管理员",
            role=ROLE_ADMIN,
            is_active=True,
            must_change_password=True,
            token_version=0,
        )
    )
    db.commit()
    if generated:
        logger.warning(
            "已创建内置管理员 %s，随机初始密码：%s（仅显示这一次，首登强制改密）",
            username,
            password,
        )
    else:
        logger.warning("已创建内置管理员 %s（密码取自 ADMIN_INITIAL_PASSWORD，首登强制改密）", username)
    return username
