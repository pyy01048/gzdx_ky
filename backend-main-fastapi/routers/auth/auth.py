"""登录 / 会话 / 用户管理（doc 11 F11-02/05/08/09）+ 邮箱注册/找回（《用户管理界面.md》）。"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional

from core.models.schools import AuditLog
from database import get_db
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from services import email_service
from sqlalchemy import func
from sqlalchemy.orm import Session
from utils.exceptions import BusinessException, ErrorCode
from utils.response import page_params, paginate_query
from utils.security import (
    ACCESS_COOKIE,
    MIN_PASSWORD_LEN,
    REFRESH_COOKIE,
    ROLE_ADMIN,
    ROLES,
    STATUS_ACTIVE,
    STATUS_DELETED,
    STATUS_DISABLED,
    STATUS_PENDING_DELETION,
    STATUS_UNVERIFIED,
    clear_session_cookies,
    client_ip,
    create_session,
    current_user,
    decode_token,
    forgot_email_limiter,
    forgot_ip_limiter,
    hash_password,
    load_token_user,
    login_limiter,
    mask_email,
    register_limiter,
    require_admin,
    revoke_session,
    rotate_refresh,
    set_session_cookies,
    user_snapshot,
    validate_new_password,
    validate_strong_password,
    verify_password,
)
from utils.timeutil import iso_utc_z, to_naive_utc, utcnow

from models import AuthEvent, EmailToken, Role, RolePermission, User

router = APIRouter(prefix="/api/auth", tags=["认证"])
admin_router = APIRouter(prefix="/api/admin/users", tags=["用户管理"], dependencies=[Depends(require_admin)])


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class ChangePasswordBody(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)


class UserCreateBody(BaseModel):
    username: str = Field(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    display_name: Optional[str] = Field(None, max_length=64)
    role: str = "user"
    password: Optional[str] = Field(None, max_length=256)


class UserPatchBody(BaseModel):
    display_name: Optional[str] = Field(None, max_length=64)
    role: Optional[str] = None
    is_active: Optional[bool] = None
    disabled_reason: Optional[str] = Field(None, max_length=500)
    email: Optional[str] = Field(None, max_length=255)


def _invalid(message: str) -> BusinessException:
    return BusinessException(code=ErrorCode.INVALID_PARAMETER, message=message)


def _session_payload(user: User) -> dict:
    """登录/刷新响应体（V3.12 评审 B-03 整改：不再返回 access_token）。

    会话凭据只走 httpOnly cookie 单通道 —— 响应体里的 token 会落进
    前端日志/代理缓存/浏览器历史，等于把「防 XSS 读 token」的 cookie
    设计撕开一个口子。前端已核实不消费 body token（AuthContext 只用 user）。
    """
    return {
        "user": user_snapshot(user),
        "must_change_password": bool(user.must_change_password),
        "email_verified": bool(getattr(user, "email_verified_at", None)),
    }


def _valid_ip(value: str) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _audit(
    db: Session, request: Request, operator, user: User, action: str, before: Optional[dict], summary: str
) -> None:
    # deleted_at 与另两个时间列一样是 datetime：进 JSON 列会序列化失败（500），
    # 且它是本次操作的结果而非"字段变更"，审计里不需要。before 由调用方给。
    skip = ("last_login_at", "created_at", "deleted_at")

    def _jsonable(snapshot: Optional[dict]) -> Optional[dict]:
        # 116 新增的 email_verified_at / deletion_requested_at 也是 datetime
        # （PG 侧 TIMESTAMPTZ → 驱动返回 aware），同样不能裸进 JSONB：统一转 ISO 字符串。
        if snapshot is None:
            return None
        return {k: (iso_utc_z(v) if isinstance(v, datetime) else v) for k, v in snapshot.items()}

    after = _jsonable({k: v for k, v in user_snapshot(user).items() if k not in skip})
    db.add(
        AuditLog(
            table_name="users",
            record_id=user.id,
            action=action,
            operator_id=getattr(operator, "id", None),
            operator_ip=_valid_ip(client_ip(request)),
            before_data=_jsonable(before),
            after_data=after,
            change_summary=summary,
        )
    )
    # 同步写一条 auth_events（§5.2 只读审计视图统一从这里读，管理操作也要可见）。
    # 自助操作（operator 即本人，如申请注销）已有专属事件，不再重复记 admin_*。
    if getattr(operator, "id", None) != user.id:
        _audit_event(
            db,
            request,
            f"admin_{action.lower()}",
            user_id=user.id,
            email=getattr(user, "email", None),
            actor_id=getattr(operator, "id", None),
            detail=summary,
        )


# --------------------------------------------------------------------------- #
# 会话
# --------------------------------------------------------------------------- #
@router.get("/status")
def auth_status() -> dict:
    return {"enabled": True, "mode": "account", "message": "请使用账号密码登录"}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    key = login_limiter.key(client_ip(request), body.username)
    wait = login_limiter.retry_after(key)
    if wait:
        raise BusinessException(
            code=ErrorCode.RATE_LIMITED,
            message=f"尝试过多，请 {max(1, wait // 60)} 分钟后再试",
            detail={"retry_after": wait},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(wait)},
        )
    ident = body.username.strip().lower()
    q = db.query(User).filter(User.deleted_at.is_(None))
    # 邮箱版：登录凭证支持邮箱或用户名（邮箱是主凭证，用户名兼容旧账号）
    if "@" in ident:
        user = q.filter(func.lower(User.email) == ident).first()
    else:
        user = q.filter(func.lower(User.username) == ident).first()
    if user is None or not verify_password(body.password, user.password_hash):
        login_limiter.fail(key)
        _audit_event(
            db,
            request,
            "login_failure",
            user_id=getattr(user, "id", None),
            email=ident if "@" in ident else None,
            success=False,
            detail="账号或密码不匹配",
        )
        db.commit()
        # 不区分「无此用户」「密码错」，避免枚举账号
        raise BusinessException(
            code=ErrorCode.UNAUTHORIZED,
            message="用户名或密码错误",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    st = getattr(user, "status", None) or (STATUS_ACTIVE if user.is_active else STATUS_DISABLED)
    if st in (STATUS_DISABLED,) or not user.is_active:
        login_limiter.fail(key)
        _audit_event(db, request, "login_blocked_disabled", user_id=user.id, success=False)
        db.commit()
        # 方案 §5.2：禁用原因在登录时作为提示返回（管理员写入的原因）
        reason = getattr(user, "disabled_reason", None)
        raise BusinessException(
            code=ErrorCode.FORBIDDEN,
            message=f"账号已被禁用{('：' + reason) if reason else ''}，如有疑问请联系管理员",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    if st in (STATUS_PENDING_DELETION, STATUS_DELETED):
        login_limiter.fail(key)
        raise BusinessException(
            code=ErrorCode.UNAUTHORIZED,
            message="用户名或密码错误",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    login_limiter.success(key)
    user.last_login_at = utcnow()
    user.last_login_ip = _valid_ip(client_ip(request))
    user.login_count = int(user.login_count or 0) + 1
    _audit_event(db, request, "login_success", user_id=user.id)
    # 会话登记（120）：sid/jti 进 token 声明，登出/重放可服务端吊销
    sid, jti = create_session(db, request, user)
    db.commit()
    set_session_cookies(response, request, user, sid, jti)
    return _session_payload(user)


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(REFRESH_COOKIE)
    payload = decode_token(token, "refresh") if token else None
    user = load_token_user(db, payload)
    if user is None:
        clear_session_cookies(response)
        raise BusinessException(
            code=ErrorCode.UNAUTHORIZED,
            message="登录已过期，请重新登录",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    # 一次性轮换（120 / 评审 C5）：旧 jti 即刻作废；重放 → 全家族吊销。
    # 无 sid/jti 的旧 refresh（升级前签发）按旧语义放行一次并补登记会话，
    # 14 天过渡期后所有 refresh 都带 jti。
    if payload.get("sid") and payload.get("jti"):
        new_jti = rotate_refresh(db, user, payload)
        if new_jti is None:
            db.commit()
            clear_session_cookies(response)
            raise BusinessException(
                code=ErrorCode.UNAUTHORIZED,
                message="登录已失效，请重新登录",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        sid = payload["sid"]
    else:
        sid, new_jti = create_session(db, request, user)
    db.commit()
    set_session_cookies(response, request, user, sid, new_jti)
    return _session_payload(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    # 服务端吊销（120 / 评审 C6）：只清 cookie 不够 —— 被窃取的 token
    # 在过期前仍可用。吊销本会话后，该会话 access/refresh 立即 401，
    # 其他设备的会话不受影响。
    for cookie_name, typ in ((REFRESH_COOKIE, "refresh"), (ACCESS_COOKIE, "access")):
        payload = decode_token(request.cookies.get(cookie_name), typ)
        if payload and payload.get("sid"):
            revoke_session(db, payload["sid"])
            break
    db.commit()
    clear_session_cookies(response)
    return {"success": True}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_snapshot(user)


@router.post("/change-password")
def change_password(
    body: ChangePasswordBody,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(body.old_password, user.password_hash):
        raise _invalid("原密码错误")
    validate_new_password(body.new_password)
    if body.new_password == body.old_password:
        raise _invalid("新密码不能与原密码相同")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.token_version = int(user.token_version or 0) + 1  # 其他设备上的旧会话一并失效
    # 当前会话换新 sid（旧会话随 ver 自增已失效，顺手吊销保持会话表干净）
    old = decode_token(request.cookies.get(REFRESH_COOKIE), "refresh") or decode_token(
        request.cookies.get(ACCESS_COOKIE), "access"
    )
    if old and old.get("sid"):
        revoke_session(db, old["sid"])
    sid, jti = create_session(db, request, user)
    db.commit()
    set_session_cookies(response, request, user, sid, jti)
    return _session_payload(user)


# --------------------------------------------------------------------------- #
# 用户管理（仅管理员）
# --------------------------------------------------------------------------- #
def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise BusinessException(
            code=ErrorCode.RESOURCE_NOT_FOUND,
            message="用户不存在",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return user


def _other_active_admins(db: Session, user_id: int) -> int:
    return (
        db.query(User)
        .filter(
            User.role == ROLE_ADMIN,
            User.is_active.is_(True),
            User.deleted_at.is_(None),  # 已软删的管理员不算"还活着的其他管理员"
            User.id != user_id,
        )
        .count()
    )


def _parse_day_or_400(value: str, field: str) -> datetime:
    """日期参数先在 Python 侧校验再进查询：坏字符串过去直接到 PG 隐式转换失败 = 500。"""
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError as e:
        raise _invalid(f"{field} 需为 YYYY-MM-DD 格式") from e


@admin_router.get("")
def list_users(
    params: dict = Depends(page_params),
    keyword: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    status_filter: Optional[str] = None,
    registered_from: Optional[str] = None,
    registered_to: Optional[str] = None,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    q = db.query(User)
    # 软删除的用户默认不出现在列表里（deleted_at 非空）；勾选"含已删除"才带出来，
    # 否则管理员建错一个用户名就只能停用、看不到、也删不掉（本次修复的原始诉求）。
    if not include_deleted:
        q = q.filter(User.deleted_at.is_(None))
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter((User.username.ilike(like)) | (User.display_name.ilike(like)) | (User.email.ilike(like)))
    if role:
        q = q.filter(User.role == role)
    if is_active is not None:
        q = q.filter(User.is_active.is_(is_active))
    if status_filter:
        q = q.filter(User.status == status_filter)
    if registered_from:
        q = q.filter(User.created_at >= _parse_day_or_400(registered_from, "registered_from"))
    if registered_to:
        # 含注册当日全天：< 次日零点，比拼接 " 23:59:59" 字符串更稳（不依赖 PG 隐式转换）
        q = q.filter(User.created_at < _parse_day_or_400(registered_to, "registered_to") + timedelta(days=1))
    q = q.order_by(User.id.asc())
    return paginate_query(q, page=params["page"], page_size=params["page_size"], serialize=user_snapshot).dict()


@admin_router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreateBody, request: Request, operator=Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    if body.role not in ROLES:
        raise _invalid(f"角色只能是 {'/'.join(ROLES)}")
    exists = db.query(User.id).filter(func.lower(User.username) == body.username.lower()).first()
    if exists:
        raise BusinessException(code=ErrorCode.CONFLICT, message="用户名已存在", status_code=status.HTTP_409_CONFLICT)
    temp = None
    if body.password:
        # 创建场景下"新密码"措辞会让管理员误以为在改自己的密码，
        # 且前端输入框没有长度约束提示——这里给出创建语境的明确报错。
        try:
            validate_new_password(body.password)
        except BusinessException as e:
            raise _invalid(f"初始密码至少 {MIN_PASSWORD_LEN} 位；留空则由系统自动生成临时密码") from e
        password = body.password
    else:
        password = temp = secrets.token_urlsafe(9)
    user = User(
        username=body.username,
        display_name=body.display_name,
        role=body.role,
        password_hash=hash_password(password),
        is_active=True,
        status=STATUS_ACTIVE,  # 管理员建的账号不走邮箱验证（无邮箱），直接 active
        must_change_password=True,
        token_version=0,
    )
    db.add(user)
    db.flush()
    _audit(db, request, operator, user, "INSERT", None, f"新建用户 {user.username}（{user.role}）")
    db.commit()
    return {"user": user_snapshot(user), "temporary_password": temp}


@admin_router.patch("/{user_id}")
def update_user(
    user_id: int, body: UserPatchBody, request: Request, operator=Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    user = _get_user(db, user_id)
    before = {k: v for k, v in user_snapshot(user).items() if k not in ("last_login_at", "created_at", "deleted_at")}
    revoke = False
    summary_parts = []
    if body.role is not None and body.role != user.role:
        if body.role not in ROLES:
            raise _invalid(f"角色只能是 {'/'.join(ROLES)}")
        if user.role == ROLE_ADMIN and _other_active_admins(db, user.id) == 0:
            raise _invalid("不能撤销最后一个管理员")
        summary_parts.append(f"角色 {user.role}→{body.role}")
        user.role = body.role
        revoke = True
    if body.is_active is not None and body.is_active != user.is_active:
        if not body.is_active:
            if user.id == getattr(operator, "id", None):
                raise _invalid("不能禁用自己")
            if user.role == ROLE_ADMIN and _other_active_admins(db, user.id) == 0:
                raise _invalid("不能禁用最后一个管理员")
            # 方案 §5.2：禁用必须填写原因，原因写入日志并在其登录时提示
            reason = (body.disabled_reason or "").strip()
            if not reason:
                raise _invalid("禁用用户必须填写原因")
            user.disabled_reason = reason
            user.disabled_at = utcnow()
            user.status = STATUS_DISABLED
            summary_parts.append(f"禁用（原因：{reason}）")
        else:
            user.disabled_reason = None
            user.disabled_at = None
            user.status = STATUS_ACTIVE if user.email_verified_at else STATUS_UNVERIFIED
            summary_parts.append("启用")
        user.is_active = body.is_active
        revoke = True
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or None
    if body.email is not None:
        new_email = body.email.strip().lower() or None
        if new_email is not None:
            if not EMAIL_RE.match(new_email):
                raise _invalid("邮箱格式不正确")
            clash = db.query(User.id).filter(func.lower(User.email) == new_email, User.id != user.id).first()
            if clash:
                raise BusinessException(
                    code=ErrorCode.CONFLICT, message="该邮箱已被其他账号使用", status_code=status.HTTP_409_CONFLICT
                )
        if new_email != (user.email or None):
            # 管理员改绑邮箱：验证状态清零，需重新验证
            user.email = new_email
            user.email_verified_at = None
            if user.status == STATUS_ACTIVE:
                user.status = STATUS_UNVERIFIED
            summary_parts.append("改绑邮箱（需重新验证）")
    if revoke:
        user.token_version = int(user.token_version or 0) + 1
    _audit(
        db,
        request,
        operator,
        user,
        "UPDATE",
        before,
        f"修改用户 {user.username}" + ("：" + "；".join(summary_parts) if summary_parts else ""),
    )
    db.commit()
    return user_snapshot(user)


class AdminResetBody(BaseModel):
    mode: str = Field("temp", pattern=r"^(temp|email)$")


@admin_router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    request: Request,
    body: Optional[AdminResetBody] = None,
    operator=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """强制重置密码（§5.2）：临时密码（默认）或发送重置邮件，均记审计。"""
    user = _get_user(db, user_id)
    mode = body.mode if body else "temp"
    if mode == "email":
        if not user.email:
            raise _invalid("该账号未绑定邮箱，无法发送重置邮件，请改用临时密码")
        token = _issue_email_token(db, request, user, "reset", RESET_TTL)
        sent = email_service.send_reset_email(user.email, token, user.display_name)
        _audit(
            db,
            request,
            operator,
            user,
            "UPDATE",
            None,
            f"向 {user.username} 发送密码重置邮件（{mask_email(user.email)}）",
        )
        _audit_event(
            db,
            request,
            "admin_force_reset_email",
            user_id=user.id,
            actor_id=getattr(operator, "id", None),
            email=user.email,
        )
        db.commit()
        return {"user": user_snapshot(user), "mode": "email", "sent": sent, "email_masked": mask_email(user.email)}
    temp = secrets.token_urlsafe(9)
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.token_version = int(user.token_version or 0) + 1
    _audit(db, request, operator, user, "UPDATE", None, f"重置用户 {user.username} 的密码")
    _audit_event(db, request, "admin_force_reset_temp", user_id=user.id, actor_id=getattr(operator, "id", None))
    db.commit()
    return {"user": user_snapshot(user), "temporary_password": temp, "mode": "temp"}


# --------------------------------------------------------------------------- #
# 软删除 / 恢复
# --------------------------------------------------------------------------- #
# 做软删除而不是物理删除的原因见 core/sql/107 头注释：用户往往带着目标、复习计划、
# 学习轨迹等关联数据，物理删除会留下孤儿行且不可逆。删除 = 写 deleted_at，
# 恢复 = 清空 deleted_at，数据原样回来。用户名在软删期间仍被 UNIQUE 占用，
# 这正是"可恢复"的代价——要复用同名得先恢复或换一个。
@admin_router.delete("/{user_id}")
def delete_user(user_id: int, request: Request, operator=Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    user = _get_user(db, user_id)
    if user.deleted_at is not None:
        raise BusinessException(
            code=ErrorCode.RESOURCE_NOT_FOUND,
            message="用户不存在或已删除",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if user.id == getattr(operator, "id", None):
        raise _invalid("不能删除自己")
    if user.role == ROLE_ADMIN and _other_active_admins(db, user.id) == 0:
        raise _invalid("不能删除最后一个管理员")

    before = {k: v for k, v in user_snapshot(user).items() if k not in ("last_login_at", "created_at", "deleted_at")}
    user.deleted_at = utcnow()
    user.status = STATUS_DELETED
    # 立刻断掉该用户所有既有会话（token_version 自增），否则被删用户仍能用旧 token 操作。
    user.token_version = int(user.token_version or 0) + 1
    _audit(db, request, operator, user, "DELETE", before, f"软删除用户 {user.username}")
    db.commit()
    return {"success": True, "user": user_snapshot(user)}


@admin_router.post("/{user_id}/restore")
def restore_user(
    user_id: int, request: Request, operator=Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    user = _get_user(db, user_id)
    if user.deleted_at is None:
        raise _invalid("用户未被删除，无需恢复")
    user.deleted_at = None
    # 恢复后回到状态机：邮箱未验证→unverified，否则 active
    user.status = STATUS_ACTIVE if user.email_verified_at else STATUS_UNVERIFIED
    user.is_active = True
    _audit(db, request, operator, user, "UPDATE", None, f"恢复用户 {user.username}")
    db.commit()
    return {"success": True, "user": user_snapshot(user)}


# =========================================================================== #
# 邮箱注册 / 验证 / 找回密码（《用户管理界面.md》邮箱版，core/sql/116）
#
# 三条安全底线：
#   1. 不泄露账号存在性——注册/找回对外一律无差别提示；
#   2. 未验证邮箱不能进敏感路径——找回密码只对 active+已验证 开放；
#   3. 每一次权限使用都有痕迹——auth_events 审计。
# =========================================================================== #
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
# 一次性邮箱域名拦截（入口降滥用，§3.1；名单可运营扩充）
DISPOSABLE_DOMAINS = {
    "mailinator.com",
    "guerrillamail.com",
    "10minutemail.com",
    "tempmail.com",
    "temp-mail.org",
    "yopmail.com",
    "throwawaymail.com",
    "getnada.com",
    "sharklasers.com",
    "trashmail.com",
    "dispostable.com",
    "maildrop.cc",
}
VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(minutes=60)
RESET_COOKIE = "kaoyan_reset"
UNIFORM_REGISTER_MSG = "如果该邮箱可用，验证邮件已发送，请查收（记得看看垃圾箱）。"
UNIFORM_FORGOT_MSG = "如果该邮箱已注册且已验证，重置邮件已发送，请查收（记得看看垃圾箱）。"


class RegisterBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)
    display_name: Optional[str] = Field(None, max_length=64)


class EmailOnlyBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)


class TokenBody(BaseModel):
    token: str = Field(..., min_length=8, max_length=256)


class InspectResetBody(BaseModel):
    # inspect 允许不带 token：缺省时读 reset-link 写入的 httpOnly cookie。
    # 不能复用 TokenBody（token 必填会让纯 cookie 探测直接 422）。
    token: Optional[str] = Field(None, max_length=256)


class ResetPasswordBody(BaseModel):
    token: Optional[str] = Field(None, max_length=256)  # 缺省时读 reset-link 写入的 cookie
    new_password: str = Field(..., min_length=1, max_length=128)


def _audit_event(
    db: Session,
    request: Optional[Request],
    event_type: str,
    user_id: Optional[int] = None,
    email: Optional[str] = None,
    actor_id: Optional[int] = None,
    success: bool = True,
    detail: Optional[str] = None,
) -> None:
    db.add(
        AuthEvent(
            event_type=event_type,
            user_id=user_id,
            email=email,
            actor_id=actor_id,
            success=success,
            ip=_valid_ip(client_ip(request)) if request is not None else None,
            user_agent=(request.headers.get("user-agent", "")[:255] if request is not None else None),
            detail=detail,
        )
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _pwd_fingerprint(user: User) -> str:
    """重置 token 与当前密码哈希绑定：改密后旧链接立即失效（§4.1）。"""
    return hashlib.sha256((user.password_hash or "").encode("utf-8")).hexdigest()[:32]


def _find_by_email(db: Session, email: str) -> Optional[User]:
    return (
        db.query(User)
        .filter(
            func.lower(User.email) == email.strip().lower(),
            User.deleted_at.is_(None),
        )
        .first()
    )


def _issue_email_token(db: Session, request: Request, user: User, kind: str, ttl: timedelta) -> str:
    raw = secrets.token_urlsafe(32)
    if kind == "reset":
        # 新重置链接签发即作废旧的未使用链接（一次只有一个有效重置链接）
        db.query(EmailToken).filter(
            EmailToken.user_id == user.id,
            EmailToken.kind == "reset",
            EmailToken.used_at.is_(None),
        ).update({"used_at": utcnow()})
    db.add(
        EmailToken(
            user_id=user.id,
            kind=kind,
            token_hash=_token_hash(raw),
            pwd_fingerprint=_pwd_fingerprint(user) if kind == "reset" else None,
            expires_at=utcnow() + ttl,
            request_ip=_valid_ip(client_ip(request)),
        )
    )
    return raw


def _load_valid_token(db: Session, token: str, kind: str) -> Optional[EmailToken]:
    if not token:
        return None
    row = (
        db.query(EmailToken)
        .filter(
            EmailToken.token_hash == _token_hash(token),
            EmailToken.kind == kind,
            EmailToken.used_at.is_(None),
            EmailToken.expires_at > utcnow(),
        )
        .first()
    )
    if row is None:
        return None
    user = db.get(User, row.user_id)
    if user is None or user.deleted_at is not None:
        return None
    if kind == "reset":
        # 密码哈希指纹对不上 = 用户已经改过密码，链接作废
        if row.pwd_fingerprint != _pwd_fingerprint(user):
            return None
        st = getattr(user, "status", STATUS_ACTIVE)
        if st != STATUS_ACTIVE or not user.email_verified_at:
            return None
    return row


def _verify_send_allowed(db: Session, user_id: int) -> bool:
    """重发验证邮件节流（§3.2）：间隔 ≥60s，24h 内 ≤5 封。

    用 email_tokens 的签发记录做节流依据（跨 worker / 重启一致），
    达到上限后 24 小时内不再发信。
    """
    now = utcnow()
    recent = (
        db.query(EmailToken.created_at)
        .filter(
            EmailToken.user_id == user_id,
            EmailToken.kind == "verify",
            EmailToken.created_at > now - timedelta(hours=24),
        )
        .order_by(EmailToken.created_at.desc())
        .all()
    )
    if len(recent) >= 5:
        return False
    # TIMESTAMPTZ 列读回是 aware datetime，utcnow() 是 naive：先归一再相减，
    # 否则 naive-aware 直接 TypeError（重发验证 / 补发验证邮件全 500）。
    if recent and (now - to_naive_utc(recent[0][0])).total_seconds() < 60:
        return False
    return True


def _unique_username(db: Session, email: str) -> str:
    """邮箱注册时从邮箱前缀派生用户名（仅展示用，不作为登录凭证）。"""
    local = re.sub(r"[^A-Za-z0-9_.\-]", "", email.split("@", 1)[0])[:48] or "user"
    if len(local) < 2:
        local = f"user_{local}"
    candidate = local
    for _ in range(20):
        if db.query(User.id).filter(func.lower(User.username) == candidate.lower()).first() is None:
            return candidate
        candidate = f"{local}_{secrets.token_hex(2)}"
    return f"user_{secrets.token_hex(4)}"


def _floor_elapsed(start: float, min_ms: int = 150) -> None:
    """抹平响应时间侧信道（§4.1）：所有分支耗时不低于 min_ms。

    单次 time.sleep 在粗粒度时钟平台（Windows ~15.6ms）会下冲，击穿防枚举下限；
    改用单调时钟 deadline 循环补睡，保证真实耗时 ≥ min_ms（跨平台确定性达标）。
    """
    deadline = start + min_ms / 1000
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        time.sleep(left)


def _normalize_email_or_400(email: str) -> str:
    value = email.strip().lower()
    if not EMAIL_RE.match(value):
        raise _invalid("邮箱格式不正确")
    return value


@router.post("/register")
def register(body: RegisterBody, request: Request, db: Session = Depends(get_db)) -> dict:
    ip = client_ip(request)
    wait = register_limiter.retry_after(ip)
    if wait:
        raise BusinessException(
            code=ErrorCode.RATE_LIMITED,
            message=f"注册提交过于频繁，请 {max(1, wait // 60)} 分钟后再试",
            detail={"retry_after": wait},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(wait)},
        )
    register_limiter.hit(ip)
    email = _normalize_email_or_400(body.email)
    if email.split("@", 1)[1] in DISPOSABLE_DOMAINS:
        raise _invalid("不支持一次性邮箱，请使用常用邮箱注册")
    validate_strong_password(body.password)

    user = _find_by_email(db, email)
    if user is None:
        user = User(
            username=_unique_username(db, email),
            display_name=(body.display_name or "").strip() or None,
            email=email,
            role="user",
            password_hash=hash_password(body.password),
            is_active=True,
            status=STATUS_UNVERIFIED,
            must_change_password=False,
            token_version=0,
        )
        db.add(user)
        db.flush()
        _audit_event(db, request, "register", user_id=user.id, email=email)
        if _verify_send_allowed(db, user.id):
            token = _issue_email_token(db, request, user, "verify", VERIFY_TTL)
            email_service.send_verification_email(email, token, user.display_name)
    else:
        # 已注册：对外无差别。未验证且账号可用时补发验证邮件（受重发节流约束）；
        # 已验证 / 已禁用的账号什么都不做（绝不返回"该邮箱已注册"）。
        st = getattr(user, "status", STATUS_ACTIVE)
        if user.email_verified_at is None and user.is_active and st != STATUS_DISABLED:
            if _verify_send_allowed(db, user.id):
                token = _issue_email_token(db, request, user, "verify", VERIFY_TTL)
                email_service.send_verification_email(email, token, user.display_name)
        else:
            _audit_event(db, request, "register_attempt_existing", user_id=user.id, email=email)
    db.commit()
    return {"success": True, "message": UNIFORM_REGISTER_MSG}


@router.post("/resend-verification")
def resend_verification(body: EmailOnlyBody, request: Request, db: Session = Depends(get_db)) -> dict:
    email = _normalize_email_or_400(body.email)
    user = _find_by_email(db, email)
    if (
        user is not None
        and user.email_verified_at is None
        and user.is_active
        and getattr(user, "status", STATUS_ACTIVE) != STATUS_DISABLED
    ):
        if _verify_send_allowed(db, user.id):
            token = _issue_email_token(db, request, user, "verify", VERIFY_TTL)
            email_service.send_verification_email(email, token, user.display_name)
            _audit_event(db, request, "verification_resent", user_id=user.id, email=email)
        else:
            _audit_event(db, request, "verification_send_throttled", user_id=user.id, email=email)
    db.commit()
    return {"success": True, "message": UNIFORM_REGISTER_MSG}


@router.post("/verify-email")
def verify_email(body: TokenBody, request: Request, db: Session = Depends(get_db)) -> dict:
    row = _load_valid_token(db, body.token, "verify")
    if row is None:
        raise _invalid("验证链接无效或已过期，请重新发送验证邮件")
    user = db.get(User, row.user_id)
    user.email_verified_at = utcnow()
    if getattr(user, "status", None) == STATUS_UNVERIFIED:
        user.status = STATUS_ACTIVE
    row.used_at = utcnow()
    _audit_event(db, request, "email_verified", user_id=user.id, email=user.email)
    db.commit()
    return {"success": True, "message": "邮箱验证成功，现在可以上传资料和使用找回密码了。"}


@router.post("/forgot-password")
def forgot_password(body: EmailOnlyBody, request: Request, db: Session = Depends(get_db)) -> dict:
    start = time.monotonic()
    # 节流在账号查找之前（§4.2）：IP 3 次/小时 + 邮箱 1 次/10 分钟，任一触发即拒绝。
    ip = client_ip(request)
    ip_wait = forgot_ip_limiter.retry_after(ip)
    email = body.email.strip().lower()
    email_wait = forgot_email_limiter.retry_after(email)
    if ip_wait or email_wait:
        _floor_elapsed(start)
        wait = max(ip_wait, email_wait)
        raise BusinessException(
            code=ErrorCode.RATE_LIMITED,
            message="请求过于频繁，请稍后再试",
            detail={"retry_after": wait},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(wait)},
        )
    forgot_ip_limiter.hit(ip)
    forgot_email_limiter.hit(email)
    if not EMAIL_RE.match(email):
        _floor_elapsed(start)
        raise _invalid("邮箱格式不正确")

    user = _find_by_email(db, email)
    # 对外无差别，对内分支严格（§4.1 表格）
    if user is None:
        _audit_event(db, request, "password_reset_no_account", email=email, success=False)
    elif not user.is_active or getattr(user, "status", STATUS_ACTIVE) == STATUS_DISABLED:
        _audit_event(db, request, "password_reset_blocked_disabled", user_id=user.id, email=email, success=False)
    elif user.email_verified_at is None:
        _audit_event(db, request, "password_reset_blocked_unverified", user_id=user.id, email=email, success=False)
    else:
        token = _issue_email_token(db, request, user, "reset", RESET_TTL)
        email_service.send_reset_email(email, token, user.display_name)
        _audit_event(db, request, "password_reset_requested", user_id=user.id, email=email)
    db.commit()
    _floor_elapsed(start)
    return {"success": True, "message": UNIFORM_FORGOT_MSG}


@router.get("/reset-link")
def reset_link(token: str, db: Session = Depends(get_db)) -> RedirectResponse:
    """邮件链接入口：token 移入 httpOnly cookie 后 302 到干净路径（§4.1）。

    避免 token 以 URL 形式留在前端访问日志 / Referer / 浏览器历史。
    """
    row = _load_valid_token(db, token, "reset")
    target = f"{email_service.app_url()}/reset-password"
    if row is None:
        return RedirectResponse(f"{target}?error=invalid", status_code=302)
    resp = RedirectResponse(target, status_code=302)
    resp.set_cookie(
        RESET_COOKIE,
        token,
        max_age=600,
        httponly=True,
        samesite="strict",
        path="/api/auth",
    )
    return resp


@router.post("/reset-password/inspect")
def inspect_reset(request: Request, body: Optional[InspectResetBody] = None, db: Session = Depends(get_db)) -> dict:
    token = (body.token if body else None) or request.cookies.get(RESET_COOKIE)
    row = _load_valid_token(db, token or "", "reset")
    if row is None:
        return {"valid": False}
    user = db.get(User, row.user_id)
    return {"valid": True, "email_masked": mask_email(user.email)}


@router.post("/reset-password")
def reset_password_via_email(
    body: ResetPasswordBody, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict:
    token = body.token or request.cookies.get(RESET_COOKIE)
    row = _load_valid_token(db, token or "", "reset")
    if row is None:
        raise _invalid("重置链接无效或已过期，请重新发起找回密码")
    validate_strong_password(body.new_password)
    user = db.get(User, row.user_id)
    if verify_password(body.new_password, user.password_hash):
        raise _invalid("新密码不能与当前密码相同")
    # 同一事务：更新密码 + 所有现有会话失效（token_version 自增）+ token 一次性消费
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.token_version = int(user.token_version or 0) + 1
    row.used_at = utcnow()
    _audit_event(db, request, "password_reset_success", user_id=user.id, email=user.email)
    db.commit()
    response.delete_cookie(RESET_COOKIE, path="/api/auth")
    when = utcnow().strftime("%Y-%m-%d %H:%M UTC")
    if user.email:
        email_service.send_reset_notice_email(user.email, when)
    return {"success": True, "message": "密码已重置，所有设备已退出，请用新密码登录。"}


# --------------------------------------------------------------------------- #
# 自助注销（软删除 + 7 天冷静期，§5.1）
# --------------------------------------------------------------------------- #
@router.post("/delete-request")
def request_deletion(
    request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    if getattr(user, "status", None) == STATUS_PENDING_DELETION:
        raise _invalid("已提交注销申请，冷静期内可取消")
    user.status = STATUS_PENDING_DELETION
    user.deletion_requested_at = utcnow()
    user.token_version = int(user.token_version or 0) + 1  # 冷静期内不可登录
    _audit_event(db, request, "deletion_requested", user_id=user.id)
    _audit(db, request, user, user, "UPDATE", None, f"用户 {user.username} 申请注销（7 天冷静期）")
    db.commit()
    clear_session_cookies(response)
    return {"success": True, "message": "注销申请已提交，7 天冷静期内可取消；冷静期结束后账号将被软删除。"}


@router.post("/delete-cancel")
def cancel_deletion(body: LoginBody, request: Request, db: Session = Depends(get_db)) -> dict:
    """冷静期内凭原账号密码取消注销（此时无法登录，故不走会话）。"""
    ident = body.username.strip().lower()
    q = db.query(User).filter(User.deleted_at.is_(None), User.status == STATUS_PENDING_DELETION)
    user = (
        q.filter(func.lower(User.email) == ident).first()
        if "@" in ident
        else q.filter(func.lower(User.username) == ident).first()
    )
    if user is None or not verify_password(body.password, user.password_hash):
        raise BusinessException(
            code=ErrorCode.UNAUTHORIZED, message="用户名或密码错误", status_code=status.HTTP_401_UNAUTHORIZED
        )
    user.status = STATUS_ACTIVE if user.email_verified_at else STATUS_UNVERIFIED
    user.deletion_requested_at = None
    _audit_event(db, request, "deletion_cancelled", user_id=user.id)
    db.commit()
    return {"success": True, "message": "注销申请已取消，账号恢复正常。"}


# --------------------------------------------------------------------------- #
# 管理端：用户详情 / 角色权限目录 / 认证审计（只读）
# --------------------------------------------------------------------------- #
@admin_router.get("/roles")
def list_roles(db: Session = Depends(get_db)) -> dict:
    roles = db.query(Role).order_by(Role.role).all()
    perms = db.query(RolePermission).all()
    by_role: dict = {}
    for p in perms:
        by_role.setdefault(p.role, []).append(p.permission)
    return {
        "items": [
            {
                "role": r.role,
                "label": r.label,
                "description": r.description,
                "permissions": sorted(by_role.get(r.role, [])),
            }
            for r in roles
        ]
    }


@admin_router.get("/auth-events")
def list_auth_events(
    params: dict = Depends(page_params),
    event_type: Optional[str] = None,
    user_id: Optional[int] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    q = db.query(AuthEvent)
    if event_type:
        q = q.filter(AuthEvent.event_type == event_type)
    if user_id is not None:
        q = q.filter(AuthEvent.user_id == user_id)
    if keyword:
        q = q.filter(AuthEvent.email.ilike(f"%{keyword.strip()}%"))
    q = q.order_by(AuthEvent.id.desc())

    def _ser(e: AuthEvent) -> dict:
        return {
            "id": e.id,
            "event_type": e.event_type,
            "user_id": e.user_id,
            "email": e.email,
            "actor_id": e.actor_id,
            "success": bool(e.success),
            "ip": e.ip,
            "detail": e.detail,
            "created_at": e.created_at,
        }

    return paginate_query(q, page=params["page"], page_size=params["page_size"], serialize=_ser).dict()


@admin_router.get("/{user_id}")
def user_detail(user_id: int, db: Session = Depends(get_db)) -> dict:
    user = _get_user(db, user_id)
    events = db.query(AuthEvent).filter(AuthEvent.user_id == user_id).order_by(AuthEvent.id.desc()).limit(20).all()
    return {
        "user": user_snapshot(user),
        "recent_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "success": bool(e.success),
                "ip": e.ip,
                "detail": e.detail,
                "created_at": e.created_at,
            }
            for e in events
        ],
    }
