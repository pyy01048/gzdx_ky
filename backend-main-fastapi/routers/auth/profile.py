# -*- coding: utf-8 -*-
"""个人资料与偏好路由（W6 设置页高级化）：``/api/profile``。

为什么单独一张 ``user_profiles`` 表而不是改 ``users``：
  ``users`` 由 auth 域拥有（104/107/116 分片 + ``routers/auth/auth.py``），
  在并行波次里加列等于踩别人的地基。档案扩展（头像 / 称号 / 偏好 / 已解锁权益）
  是**可丢的展示层数据**，与登录凭据分级存放反而更安全；``display_name`` 这类
  认证域字段仍写回 ``users``，由本接口代理，绝不做双份存储。

写前备份闸门：本接口只写个人域一行（一人一行 UPSERT），与 tasks/words 同级别，
不走全库备份；备份闸门的适用面见 ``routers/study/gamification.py`` 模块头。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from core.models.gamification import UserProfile
from database import get_db
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from services import gamification as gami
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from utils.exceptions import BusinessException, ErrorCode
from utils.scope import owner_id
from utils.security import current_user

router = APIRouter(prefix="/api/profile", tags=["个人资料"])

#: 内置头像表情（不依赖任何外部图床，离线可用）
AVATAR_PRESETS: List[str] = ["🦉", "🐼", "🚀", "📚", "🧠", "⚡", "🌊", "🔥", "🌱", "🏔️", "🎯", "🛰️"]

#: 首字头像配色（键给前端做 CSS class，值只是给管理端看的说明）
AVATAR_COLORS: Dict[str, str] = {
    "teal": "学术青",
    "indigo": "远空靛",
    "amber": "暖橙",
    "rose": "玫瑰",
    "emerald": "松绿",
    "slate": "石墨",
}

#: 偏好白名单：键 → (类型, 允许值 / 范围, 默认值)。**每个键都必须在前端真被消费**，
#: 存了没人读的开关就是"死控件"，是本轮整改明确要消灭的东西，不要往这里加。
PREF_SPEC: Dict[str, tuple] = {
    "reduce_motion": ("bool", None, False),
    "font_scale": ("enum", ("sm", "md", "lg"), "md"),
    "compact_mode": ("bool", None, False),
    "week_start": ("enum", ("mon", "sun"), "mon"),
    "coin_toast": ("bool", None, True),
    "calendar_days": ("int", (7, 120), 35),
}

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value: Optional[str], *, limit: int, field: str, required: bool = False) -> Optional[str]:
    if value is None:
        if required:
            raise BusinessException(ErrorCode.INVALID_PARAMETER, f"{field} 不能为空", status_code=422)
        return None
    text = _CONTROL_RE.sub("", str(value)).strip()
    if len(text) > limit:
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER, f"{field} 最长 {limit} 个字符（当前 {len(text)}）", status_code=422
        )
    if required and not text:
        raise BusinessException(ErrorCode.INVALID_PARAMETER, f"{field} 不能为空", status_code=422)
    return text


def _clean_avatar(kind: Optional[str], value: Optional[str]) -> tuple:
    """头像校验：只接受三种形态，外链必须 http(s)（挡掉 ``javascript:`` 与本地路径）。"""
    if kind is None:
        return None, None
    if kind not in ("initials", "preset", "url"):
        raise BusinessException(ErrorCode.INVALID_PARAMETER, "头像类型只支持 initials / preset / url", status_code=422)
    text = _clean_text(value, limit=300, field="头像值")
    if kind == "initials":
        color = (text or "teal").lower()
        if color not in AVATAR_COLORS:
            raise BusinessException(
                ErrorCode.INVALID_PARAMETER,
                f"未知配色 {color}，可选：{'、'.join(AVATAR_COLORS)}",
                status_code=422,
            )
        return kind, color
    if kind == "preset":
        if text not in AVATAR_PRESETS:
            raise BusinessException(ErrorCode.INVALID_PARAMETER, "头像表情不在内置清单里", status_code=422)
        return kind, text
    if not text:
        raise BusinessException(ErrorCode.INVALID_PARAMETER, "外链头像需要填写图片地址", status_code=422)
    if not re.match(r"^https?://[^\s]+$", text):
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER, "头像地址必须是 http(s) 开头的完整图片链接", status_code=422
        )
    return kind, text


def _clean_prefs(patch: Optional[Dict[str, Any]]) -> tuple:
    """按白名单合并偏好：未知键忽略并回给调用方（不静默、也不炸请求）。"""
    if not patch:
        return None, []
    merged: Dict[str, Any] = {}
    ignored: List[str] = []
    for key, raw in patch.items():
        spec = PREF_SPEC.get(key)
        if spec is None:
            ignored.append(str(key))
            continue
        kind, allowed, default = spec
        if kind == "bool":
            merged[key] = bool(raw)
        elif kind == "enum":
            val = str(raw or default)
            if val not in allowed:
                raise BusinessException(
                    ErrorCode.INVALID_PARAMETER, f"{key} 只能是 {'/'.join(allowed)}", status_code=422
                )
            merged[key] = val
        else:  # int
            lo, hi = allowed
            try:
                val = int(raw)
            except (TypeError, ValueError):
                raise BusinessException(ErrorCode.INVALID_PARAMETER, f"{key} 需是整数", status_code=422) from None
            if not lo <= val <= hi:
                raise BusinessException(ErrorCode.INVALID_PARAMETER, f"{key} 需在 {lo}~{hi} 之间", status_code=422)
            merged[key] = val
    return merged, ignored


def default_prefs() -> Dict[str, Any]:
    return {k: spec[2] for k, spec in PREF_SPEC.items()}


def _equipped(db: Session, profile: Optional[UserProfile], user_id: int) -> Dict[str, Any]:
    """佩戴项校验：只用**已解锁**的头像框/称号，被回收的下架商品自动脱落。"""
    unlocked = gami._unlocked_maps(db, user_id)
    frames, titles = set(unlocked["frames"]), set(unlocked["titles"])
    frame = profile.avatar_frame if profile else None
    title = profile.title if profile else None
    return {
        "avatar_frame": frame if frame in frames else None,
        "avatar_title": title if title in titles else None,
        "unlocked": unlocked,
        "frame_catalog": [
            {"code": i["code"], "name": i["name"], "frame": (i["payload"] or {}).get("frame")}
            for i in gami.list_items(db, only_active=False)
            if i["kind"] == "avatar_frame"
        ],
        "title_catalog": [
            {"code": i["code"], "name": i["name"], "title": (i["payload"] or {}).get("title")}
            for i in gami.list_items(db, only_active=False)
            if i["kind"] == "title"
        ],
    }


def profile_dict(db: Session, profile: Optional[UserProfile], user_id: int) -> Dict[str, Any]:
    prefs = default_prefs()
    if profile and isinstance(profile.prefs, dict):
        for k, v in profile.prefs.items():
            if k in prefs:
                prefs[k] = v
    return {
        "avatar_kind": (profile.avatar_kind if profile else "initials") or "initials",
        "avatar_value": (profile.avatar_value if profile else None),
        "bio": (profile.bio if profile else None) or "",
        "grade": (profile.grade if profile else None) or "",
        "major": (profile.major if profile else None) or "",
        "prefs": prefs,
        **_equipped(db, profile, user_id),
    }


class ProfileUpdateBody(BaseModel):
    display_name: Optional[str] = Field(None, max_length=64)
    bio: Optional[str] = Field(None, max_length=200)
    grade: Optional[str] = Field(None, max_length=20)
    major: Optional[str] = Field(None, max_length=60)
    avatar_kind: Optional[str] = Field(None, max_length=12)
    avatar_value: Optional[str] = Field(None, max_length=300)
    avatar_frame: Optional[str] = Field(None, max_length=40)
    avatar_title: Optional[str] = Field(None, max_length=40)
    prefs: Optional[Dict[str, Any]] = None


def _get_or_create_profile(db: Session, user_id: int) -> UserProfile:
    row = db.query(UserProfile).filter(UserProfile.user_id == user_id).one_or_none()
    if row is not None:
        return row
    row = UserProfile(
        user_id=user_id,
        avatar_kind="initials",
        avatar_value="teal",
        prefs=default_prefs(),
        unlocked={"frames": [], "titles": []},
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        row = db.query(UserProfile).filter(UserProfile.user_id == user_id).one_or_none()
    return row


@router.get("")
def get_profile(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    """档案 + 认证域基本信息 + 可选项清单（设置页一次拉齐）。"""
    gami.ensure_gamification_schema(db)
    uid = owner_id(user)
    row = db.query(UserProfile).filter(UserProfile.user_id == uid).one_or_none()
    account = gami.find_account(db, uid) if uid is not None else None
    account_dict = gami._account_dict(account)
    return {
        "account": {
            "id": uid,
            "username": user.username,
            "display_name": getattr(user, "display_name", None) or user.username,
            "role": getattr(user, "role", None),
            "email": getattr(user, "email", None),
            "email_verified": getattr(user, "email_verified_at", None) is not None,
            "created_at": getattr(user, "created_at", None),
            "last_login_at": getattr(user, "last_login_at", None),
        },
        "profile": profile_dict(db, row, uid),
        "coins": {"balance": account_dict["balance"], "makeup_cards": account_dict["makeup_cards"]},
        "options": {
            "avatar_presets": AVATAR_PRESETS,
            "avatar_colors": list(AVATAR_COLORS.keys()),
            "pref_keys": sorted(PREF_SPEC.keys()),
        },
    }


@router.put("")
def update_profile(
    body: ProfileUpdateBody,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    """改档案（PATCH 语义：只动传了的字段）。"""
    gami.ensure_gamification_schema(db)
    uid = owner_id(user)
    patch = body.model_dump(exclude_unset=True)
    ignored: List[str] = []
    row = _get_or_create_profile(db, uid)

    if "display_name" in patch:
        # display_name 属认证域（users 表），在这里代理写入，user 与 session 同源，
        # 不再多查一次 users —— 查了反而可能拿到另一份身份映射对象。
        user.display_name = _clean_text(patch["display_name"], limit=64, field="显示名", required=True)

    if "avatar_kind" in patch or "avatar_value" in patch:
        kind, value = _clean_avatar(patch.get("avatar_kind") or row.avatar_kind, patch.get("avatar_value"))
        if patch.get("avatar_kind") is not None:
            row.avatar_kind = kind
        if value is not None:
            row.avatar_value = value
    if "bio" in patch:
        row.bio = _clean_text(patch["bio"], limit=200, field="简介")
    if "grade" in patch:
        row.grade = _clean_text(patch["grade"], limit=20, field="年级")
    if "major" in patch:
        row.major = _clean_text(patch["major"], limit=60, field="专业")

    unlocked = gami._unlocked_maps(db, uid)
    if "avatar_frame" in patch:
        frame = patch["avatar_frame"]
        if frame:
            if frame not in unlocked["frames"]:
                raise BusinessException(
                    ErrorCode.INVALID_PARAMETER, "该头像框尚未解锁，可在金币商店兑换后使用", status_code=422
                )
            row.avatar_frame = frame
        else:
            row.avatar_frame = None
    if "avatar_title" in patch:
        title = patch["avatar_title"]
        if title:
            if title not in unlocked["titles"]:
                raise BusinessException(
                    ErrorCode.INVALID_PARAMETER, "该称号尚未解锁，可在金币商店兑换后佩戴", status_code=422
                )
            row.title = title
        else:
            row.title = None

    if "prefs" in patch:
        merged, ignored = _clean_prefs(patch["prefs"])
        if merged:
            current = row.prefs if isinstance(row.prefs, dict) else {}
            row.prefs = {**default_prefs(), **{k: v for k, v in current.items() if k in PREF_SPEC}, **merged}

    db.commit()
    data = profile_dict(db, row, uid)
    return {**data, "ignored_pref_keys": ignored}
