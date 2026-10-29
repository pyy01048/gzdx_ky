"""登录 / 会话 / 用户管理（doc 11 F11-02/05/08/09）。"""
from __future__ import annotations

import ipaddress
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.models.schools import AuditLog
from database import get_db
from models import User
from utils.exceptions import BusinessException, ErrorCode
from utils.response import page_params, paginate_query
from utils.security import (
    MIN_PASSWORD_LEN,
    REFRESH_COOKIE,
    ROLE_ADMIN,
    ROLES,
    clear_session_cookies,
    client_ip,
    current_user,
    decode_token,
    hash_password,
    load_token_user,
    login_limiter,
    require_admin,
    set_session_cookies,
    user_snapshot,
    validate_new_password,
    verify_password,
)
from utils.timeutil import utcnow

router = APIRouter(prefix="/api/auth", tags=["认证"])
admin_router = APIRouter(
    prefix="/api/admin/users", tags=["用户管理"], dependencies=[Depends(require_admin)]
)


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


def _invalid(message: str) -> BusinessException:
    return BusinessException(code=ErrorCode.INVALID_PARAMETER, message=message)


def _session_payload(user: User, access: str) -> dict:
    return {
        "user": user_snapshot(user),
        "access_token": access,
        "token_type": "bearer",
        "must_change_password": bool(user.must_change_password),
    }


def _valid_ip(value: str) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _audit(db: Session, request: Request, operator, user: User, action: str,
           before: Optional[dict], summary: str) -> None:
    # deleted_at 与另两个时间列一样是 datetime：进 JSON 列会序列化失败（500），
    # 且它是本次操作的结果而非"字段变更"，审计里不需要。before 由调用方给。
    skip = ("last_login_at", "created_at", "deleted_at")
    after = {k: v for k, v in user_snapshot(user).items() if k not in skip}
    db.add(AuditLog(
        table_name="users",
        record_id=user.id,
        action=action,
        operator_id=getattr(operator, "id", None),
        operator_ip=_valid_ip(client_ip(request)),
        before_data=before,
        after_data=after,
        change_summary=summary,
    ))


# --------------------------------------------------------------------------- #
# 会话
# --------------------------------------------------------------------------- #
@router.get("/status")
def auth_status():
    return {"enabled": True, "mode": "account", "message": "请使用账号密码登录"}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    key = login_limiter.key(client_ip(request), body.username)
    wait = login_limiter.retry_after(key)
    if wait:
        raise BusinessException(
            code=ErrorCode.RATE_LIMITED,
            message=f"尝试过多，请 {max(1, wait // 60)} 分钟后再试",
            detail={"retry_after": wait},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    user = db.query(User).filter(
        func.lower(User.username) == body.username.strip().lower(),
        User.deleted_at.is_(None),
    ).first()
    if user is None or not verify_password(body.password, user.password_hash) or not user.is_active:
        login_limiter.fail(key)
        # 不区分「无此用户」「密码错」「已禁用」，避免枚举账号
        raise BusinessException(
            code=ErrorCode.UNAUTHORIZED, message="用户名或密码错误",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    login_limiter.success(key)
    user.last_login_at = utcnow()
    db.commit()
    access = set_session_cookies(response, request, user)
    return _session_payload(user, access)


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    user = load_token_user(db, decode_token(token, "refresh") if token else None)
    if user is None:
        clear_session_cookies(response)
        raise BusinessException(
            code=ErrorCode.UNAUTHORIZED, message="登录已过期，请重新登录",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    access = set_session_cookies(response, request, user)
    return _session_payload(user, access)


@router.post("/logout")
def logout(response: Response):
    clear_session_cookies(response)
    return {"success": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_snapshot(user)


@router.post("/change-password")
def change_password(body: ChangePasswordBody, request: Request, response: Response,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise _invalid("原密码错误")
    validate_new_password(body.new_password)
    if body.new_password == body.old_password:
        raise _invalid("新密码不能与原密码相同")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.token_version = int(user.token_version or 0) + 1  # 其他设备上的旧会话一并失效
    db.commit()
    access = set_session_cookies(response, request, user)
    return _session_payload(user, access)


# --------------------------------------------------------------------------- #
# 用户管理（仅管理员）
# --------------------------------------------------------------------------- #
def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise BusinessException(
            code=ErrorCode.RESOURCE_NOT_FOUND, message="用户不存在",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return user


def _other_active_admins(db: Session, user_id: int) -> int:
    return db.query(User).filter(
        User.role == ROLE_ADMIN, User.is_active.is_(True),
        User.deleted_at.is_(None),          # 已软删的管理员不算"还活着的其他管理员"
        User.id != user_id,
    ).count()


@admin_router.get("")
def list_users(params: dict = Depends(page_params), keyword: Optional[str] = None,
               role: Optional[str] = None, is_active: Optional[bool] = None,
               include_deleted: bool = False, db: Session = Depends(get_db)):
    q = db.query(User)
    # 软删除的用户默认不出现在列表里（deleted_at 非空）；勾选"含已删除"才带出来，
    # 否则管理员建错一个用户名就只能停用、看不到、也删不掉（本次修复的原始诉求）。
    if not include_deleted:
        q = q.filter(User.deleted_at.is_(None))
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter((User.username.ilike(like)) | (User.display_name.ilike(like)))
    if role:
        q = q.filter(User.role == role)
    if is_active is not None:
        q = q.filter(User.is_active.is_(is_active))
    q = q.order_by(User.id.asc())
    return paginate_query(
        q, page=params["page"], page_size=params["page_size"], serialize=user_snapshot
    ).dict()


@admin_router.post("", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreateBody, request: Request, operator=Depends(require_admin),
                db: Session = Depends(get_db)):
    if body.role not in ROLES:
        raise _invalid(f"角色只能是 {'/'.join(ROLES)}")
    exists = db.query(User.id).filter(func.lower(User.username) == body.username.lower()).first()
    if exists:
        raise BusinessException(code=ErrorCode.CONFLICT, message="用户名已存在",
                                status_code=status.HTTP_409_CONFLICT)
    temp = None
    if body.password:
        # 创建场景下"新密码"措辞会让管理员误以为在改自己的密码，
        # 且前端输入框没有长度约束提示——这里给出创建语境的明确报错。
        try:
            validate_new_password(body.password)
        except BusinessException:
            raise _invalid(f"初始密码至少 {MIN_PASSWORD_LEN} 位；留空则由系统自动生成临时密码")
        password = body.password
    else:
        password = temp = secrets.token_urlsafe(9)
    user = User(
        username=body.username, display_name=body.display_name, role=body.role,
        password_hash=hash_password(password), is_active=True,
        must_change_password=True, token_version=0,
    )
    db.add(user)
    db.flush()
    _audit(db, request, operator, user, "INSERT", None, f"新建用户 {user.username}（{user.role}）")
    db.commit()
    return {"user": user_snapshot(user), "temporary_password": temp}


@admin_router.patch("/{user_id}")
def update_user(user_id: int, body: UserPatchBody, request: Request,
                operator=Depends(require_admin), db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    before = {k: v for k, v in user_snapshot(user).items()
              if k not in ("last_login_at", "created_at", "deleted_at")}
    revoke = False
    if body.role is not None and body.role != user.role:
        if body.role not in ROLES:
            raise _invalid(f"角色只能是 {'/'.join(ROLES)}")
        if user.role == ROLE_ADMIN and _other_active_admins(db, user.id) == 0:
            raise _invalid("不能撤销最后一个管理员")
        user.role = body.role
        revoke = True
    if body.is_active is not None and body.is_active != user.is_active:
        if not body.is_active:
            if user.id == getattr(operator, "id", None):
                raise _invalid("不能禁用自己")
            if user.role == ROLE_ADMIN and _other_active_admins(db, user.id) == 0:
                raise _invalid("不能禁用最后一个管理员")
        user.is_active = body.is_active
        revoke = True
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or None
    if revoke:
        user.token_version = int(user.token_version or 0) + 1
    _audit(db, request, operator, user, "UPDATE", before, f"修改用户 {user.username}")
    db.commit()
    return user_snapshot(user)


@admin_router.post("/{user_id}/reset-password")
def reset_password(user_id: int, request: Request, operator=Depends(require_admin),
                   db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    temp = secrets.token_urlsafe(9)
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.token_version = int(user.token_version or 0) + 1
    _audit(db, request, operator, user, "UPDATE", None, f"重置用户 {user.username} 的密码")
    db.commit()
    return {"user": user_snapshot(user), "temporary_password": temp}


# --------------------------------------------------------------------------- #
# 软删除 / 恢复
# --------------------------------------------------------------------------- #
# 做软删除而不是物理删除的原因见 core/sql/107 头注释：用户往往带着目标、复习计划、
# 学习轨迹等关联数据，物理删除会留下孤儿行且不可逆。删除 = 写 deleted_at，
# 恢复 = 清空 deleted_at，数据原样回来。用户名在软删期间仍被 UNIQUE 占用，
# 这正是"可恢复"的代价——要复用同名得先恢复或换一个。
@admin_router.delete("/{user_id}")
def delete_user(user_id: int, request: Request, operator=Depends(require_admin),
                db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    if user.deleted_at is not None:
        raise BusinessException(
            code=ErrorCode.RESOURCE_NOT_FOUND, message="用户不存在或已删除",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if user.id == getattr(operator, "id", None):
        raise _invalid("不能删除自己")
    if user.role == ROLE_ADMIN and _other_active_admins(db, user.id) == 0:
        raise _invalid("不能删除最后一个管理员")

    before = {k: v for k, v in user_snapshot(user).items()
              if k not in ("last_login_at", "created_at", "deleted_at")}
    user.deleted_at = utcnow()
    # 立刻断掉该用户所有既有会话（token_version 自增），否则被删用户仍能用旧 token 操作。
    user.token_version = int(user.token_version or 0) + 1
    _audit(db, request, operator, user, "DELETE", before, f"软删除用户 {user.username}")
    db.commit()
    return {"success": True, "user": user_snapshot(user)}


@admin_router.post("/{user_id}/restore")
def restore_user(user_id: int, request: Request, operator=Depends(require_admin),
                 db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    if user.deleted_at is None:
        raise _invalid("用户未被删除，无需恢复")
    user.deleted_at = None
    _audit(db, request, operator, user, "UPDATE", None, f"恢复用户 {user.username}")
    db.commit()
    return {"success": True, "user": user_snapshot(user)}
