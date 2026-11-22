# -*- coding: utf-8 -*-
"""金币激励路由（W6）：``/api/gamification/*``。

个人域接口全部按 B4 行级隔离取 ``owner_id(user)``，服务层只按该 id 读写；
管理端接口挂在 ``/api/gamification/admin`` 下并**逐个** ``Depends(require_admin)``，
同时 ``/api/gamification/admin`` 也已登记进 ``utils.access_policy.ADMIN_PREFIXES``：
个人域靠"默认拒绝 = 要登录"兜住，管理端则是**两道独立闸**（路由内 require_admin
+ 全局策略层），漏写一个 Depends 也不至于让普通用户改到全站发币口径。

写前备份闸门（``services.kb_service.ensure_write_backup``）用在哪：
  * 用在**共享配置**的改动上（规则单价、全局参数、商品上下架、人工调整账目）——
    这些一改就影响全体用户的发币口径，属于"没有回滚点就不该发生"的写；
  * **不用**在个人earning 路径（sync/checkin/redeem）上：那些是 append-only 幂等流水，
    一次点击就做一次全库备份既拖死接口，也拦不住任何真实风险。
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from database import get_db
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from services import gamification as gami
from sqlalchemy.orm import Session
from utils.response import page_params, paginate_query
from utils.scope import owner_id
from utils.security import current_user, require_admin
from utils.timeutil import local_today

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gamification", tags=["金币激励"])


# --------------------------------------------------------------------------- #
# 依赖：登录用户 + 表结构自愈
# --------------------------------------------------------------------------- #
# ``current_user`` 必须走 ``Depends`` 组合，**不能**在 _gate 里直接调用：
# 全仓测试台（tests/conftest.py）与各 router 都靠
# ``dependency_overrides[current_user]`` 这一道接缝注入身份，直接函数调用会绕过
# 它拿到真实 token，于是本机契约巡检（test_api_contract）一律 401。
# routers/study/goals.py / growth.py 用的都是 ``user=Depends(current_user)``，此处保持一致。
def _gate(db: Session = Depends(get_db), user=Depends(current_user)):
    """个人域统一入口：确认登录态、确保表在、默认值已播种。"""
    gami.ensure_gamification_schema(db)
    return user


def _admin_gate(db: Session = Depends(get_db), user=Depends(current_user)):
    user = require_admin(user)
    gami.ensure_gamification_schema(db)
    return user


def _backup_gate() -> None:
    """共享配置写前的备份闸门（备份做不成就别改全局口径）。"""
    from services.kb_service import ensure_write_backup

    ensure_write_backup()


def _uid(user) -> int:
    uid = owner_id(user)
    if uid is None:
        from utils.exceptions import BusinessException, ErrorCode

        raise BusinessException(ErrorCode.UNAUTHORIZED, "需要登录", status_code=401)
    return int(uid)


def _parse_day(value: Optional[str], *, field: str = "date") -> datetime.date:
    if not value:
        return local_today()
    try:
        return datetime.date.fromisoformat(value.strip())
    except ValueError:
        from utils.exceptions import BusinessException, ErrorCode

        raise BusinessException(
            ErrorCode.INVALID_PARAMETER, f"{field} 需是 YYYY-MM-DD", detail={field: value}, status_code=422
        ) from None


# --------------------------------------------------------------------------- #
# 请求体
# --------------------------------------------------------------------------- #
class SyncBody(BaseModel):
    date: Optional[str] = Field(None, description="折算哪个北京自然日，缺省=今天")


class MakeupBody(BaseModel):
    date: str = Field(..., description="要补签的日期 YYYY-MM-DD")


class RedeemBody(BaseModel):
    code: str = Field(..., max_length=40, description="商品码")


class RuleUpdateBody(BaseModel):
    coins: Optional[int] = Field(None, ge=0, le=500)
    daily_cap: Optional[int] = Field(None, ge=0, le=50)
    per_units: Optional[int] = Field(None, ge=1, le=200)
    label: Optional[str] = Field(None, max_length=60)
    is_active: Optional[bool] = None


class SettingsPatchBody(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict, description="要改的全局参数键值")


class ItemBody(BaseModel):
    code: str = Field(..., max_length=40)
    name: str = Field(..., max_length=60)
    kind: str = Field(..., max_length=20)
    cost_coins: int = Field(..., ge=0, le=100000)
    description: Optional[str] = Field(None, max_length=200)
    payload: Dict[str, Any] = Field(default_factory=dict)
    monthly_limit: int = Field(0, ge=0, le=1000)
    sort_order: int = 0
    is_active: Optional[bool] = None


class ItemToggleBody(BaseModel):
    is_active: bool


class AdjustBody(BaseModel):
    user_id: int
    coins: int = Field(..., description="正数发放、负数收回")
    reason: str = Field(..., min_length=4, max_length=300)


# --------------------------------------------------------------------------- #
# 个人域
# --------------------------------------------------------------------------- #
@router.get("/summary")
def get_summary(db: Session = Depends(get_db), user=Depends(_gate)):
    """金币中心总览：余额 / 今日进度 / 两个"连续" / 下一个里程碑。"""
    return gami.summary(db, _uid(user))


@router.get("/rules")
def get_rules(db: Session = Depends(get_db), user=Depends(_gate)):  # noqa: ARG001 —— 仅要求登录
    """规则说明（钱怎么算的必须能查到，不能是个黑箱）。"""
    return gami.rules_doc(db)


@router.post("/sync")
def sync(
    body: SyncBody,
    db: Session = Depends(get_db),
    user=Depends(_gate),
):
    """把已发生的学习痕迹折算成金币（幂等：同一天重复调只补差额）。"""
    day = _parse_day(body.date)
    if day > local_today():
        from utils.exceptions import BusinessException, ErrorCode

        raise BusinessException(ErrorCode.INVALID_PARAMETER, "不能折算未来的日子", status_code=422)
    return gami.sync_day(db, _uid(user), day=day)


@router.post("/checkin")
def checkin(db: Session = Depends(get_db), user=Depends(_gate)):
    """当日签到（必须已有学习痕迹）。"""
    return gami.checkin(db, _uid(user))


@router.post("/checkin/makeup")
def checkin_makeup(
    body: MakeupBody,
    db: Session = Depends(get_db),
    user=Depends(_gate),
):
    """补签：消耗补签卡，补最近窗口内有学习痕迹的漏签日。"""
    return gami.makeup(db, _uid(user), _parse_day(body.date))


@router.get("/calendar")
def calendar(
    days: int = Query(35, ge=7, le=400),
    db: Session = Depends(get_db),
    user=Depends(_gate),
):
    """签到日历（含自动计入的有效学习日；week_start 由前端按偏好渲染）。"""
    return gami.calendar_dict(db, _uid(user), days=days)


@router.get("/ledger")
def ledger(
    params: dict = Depends(page_params),
    direction: Optional[str] = Query(None, description="earn | spend | adjust"),
    db: Session = Depends(get_db),
    user=Depends(_gate),
):
    """金币流水（分页壳 {items,total,page,page_size,total_pages}）。"""
    q = gami.history(db, _uid(user), direction=direction)
    return paginate_query(q, page=params["page"], page_size=params["page_size"], serialize=gami.ledger_dict).dict()


@router.get("/shop")
def shop(db: Session = Depends(get_db), user=Depends(_gate)):
    """商店：余额 + 每件商品的兑换障碍（已拥有 / 达上限 / 币不够）。"""
    return gami.shop(db, _uid(user))


@router.post("/redeem")
def redeem(
    body: RedeemBody,
    db: Session = Depends(get_db),
    user=Depends(_gate),
):
    """兑换（扣款与发货同事务）。"""
    return gami.redeem(db, _uid(user), body.code.strip())


# --------------------------------------------------------------------------- #
# 管理端（激励运营）
# --------------------------------------------------------------------------- #
@router.get("/admin/overview")
def admin_overview(
    days: int = Query(14, ge=7, le=90),
    db: Session = Depends(get_db),
    admin=Depends(_admin_gate),  # noqa: ARG001
):
    return gami.admin_overview(db, days=days)


@router.get("/admin/rules")
def admin_rules(db: Session = Depends(get_db), admin=Depends(_admin_gate)):  # noqa: ARG001
    return {"items": gami.list_rules(db), "count_fields": gami.RULE_COUNT_FIELD}


@router.put("/admin/rules/{code}")
def admin_rule_update(
    code: str,
    body: RuleUpdateBody,
    db: Session = Depends(get_db),
    admin=Depends(_admin_gate),  # noqa: ARG001
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        from utils.exceptions import BusinessException, ErrorCode

        raise BusinessException(ErrorCode.INVALID_PARAMETER, "没有要改的字段", status_code=422)
    _backup_gate()
    return gami.admin_update_rule(db, code, fields)


@router.get("/admin/settings")
def admin_settings(db: Session = Depends(get_db), admin=Depends(_admin_gate)):  # noqa: ARG001
    return {
        "values": gami.get_settings(db),
        "labels": {k: v["label"] for k, v in gami.DEFAULT_SETTINGS.items()},
    }


@router.put("/admin/settings")
def admin_settings_update(
    body: SettingsPatchBody,
    db: Session = Depends(get_db),
    admin=Depends(_admin_gate),  # noqa: ARG001
):
    _backup_gate()
    return {"values": gami.admin_update_settings(db, body.values)}


@router.get("/admin/items")
def admin_items(db: Session = Depends(get_db), admin=Depends(_admin_gate)):  # noqa: ARG001
    return {"items": gami.list_items(db), "kinds": list(gami.VALID_ITEM_KINDS)}


@router.post("/admin/items")
def admin_item_upsert(
    body: ItemBody,
    db: Session = Depends(get_db),
    admin=Depends(_admin_gate),  # noqa: ARG001
):
    _backup_gate()
    return gami.admin_upsert_item(db, body.code, body.model_dump())


@router.patch("/admin/items/{code}")
def admin_item_toggle(
    code: str,
    body: ItemToggleBody,
    db: Session = Depends(get_db),
    admin=Depends(_admin_gate),  # noqa: ARG001
):
    """只做上下架：物理删除会让历史流水指向不存在的商品，审计断链。"""
    _backup_gate()
    return gami.admin_toggle_item(db, code, body.is_active)


@router.post("/admin/adjust")
def admin_adjust(
    body: AdjustBody,
    db: Session = Depends(get_db),
    admin=Depends(_admin_gate),
):
    """人工调整某个用户的金币（必填原因，记操作者，进流水）。"""
    _backup_gate()
    return gami.admin_adjust(db, actor_id=owner_id(admin), user_id=body.user_id, coins=body.coins, reason=body.reason)


@router.get("/admin/ledger")
def admin_ledger(
    params: dict = Depends(page_params),
    user_id: Optional[int] = Query(None),
    rule_code: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin=Depends(_admin_gate),  # noqa: ARG001
):
    q = gami.admin_ledger_query(db, user_id=user_id, rule_code=rule_code, direction=direction)
    return paginate_query(
        q, page=params["page"], page_size=params["page_size"], serialize=lambda r: gami.ledger_with_user(db, r)
    ).dict()


@router.get("/admin/users/{user_id}")
def admin_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin=Depends(_admin_gate),  # noqa: ARG001
):
    return gami.admin_user_detail(db, user_id)


@router.get("/admin/trend")
def admin_trend(
    days: int = Query(14, ge=7, le=90),
    db: Session = Depends(get_db),
    admin=Depends(_admin_gate),  # noqa: ARG001
):
    """只看趋势（大盘卡片复用 overview，这里给图表单独的轻接口）。"""
    data = gami.admin_overview(db, days=days)
    out: List[Dict[str, Any]] = data.get("per_day", [])
    return {"days": days, "per_day": out}
