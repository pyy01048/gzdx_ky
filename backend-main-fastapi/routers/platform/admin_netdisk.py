"""网盘四表管理接口。

提供:
- /api/admin/netdisk/accounts: 第三方账号凭据管理
- /api/admin/netdisk/cache: 文件列表缓存管理
- /api/admin/netdisk/sessions: 预览会话管理
- /api/admin/netdisk/logs: 操作日志查询
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from core.db_session import get_db
from services import netdisk_service
from utils.security import require_admin

router = APIRouter(prefix="/api/admin/netdisk", tags=["admin-netdisk"], dependencies=[Depends(require_admin)])


# --- Pydantic Schemas ---

class AccountCreate(BaseModel):
    provider: str = Field(..., description="服务商：baidu/quark/aliyun")
    uk_provider_uid: str = Field(..., description="平台唯一标识")
    access_token: str = Field(..., description="访问令牌")
    refresh_token: str = Field(..., description="刷新令牌")
    token_expires_at: str = Field(..., description="token过期时间(ISO8601)")
    account_name: Optional[str] = None


class TokenUpdate(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[str] = None


class PreviewSessionUpdate(BaseModel):
    file_id: str = Field(..., description="文件ID")
    play_position: Optional[int] = None
    progress_percent: Optional[float] = None
    page_number: Optional[int] = None


# --- Third Party Accounts ---

@router.get("/accounts")
async def list_accounts(
    user_id: int = Query(..., description="用户ID"),
    db: Session = Depends(get_db),
):
    """列出用户的第三方账号"""
    accounts = netdisk_service.list_user_accounts(db, user_id)
    
    return {
        "total": len(accounts),
        "items": [
            {
                "id": a.id,
                "provider": a.provider,
                "uk_provider_uid": a.uk_provider_uid,
                "account_name": a.account_name,
                "is_active": a.is_active,
                "token_expires_at": a.token_expires_at.isoformat() if a.token_expires_at else None,
                "last_synced_at": a.last_synced_at.isoformat() if a.last_synced_at else None,
                "created_at": a.created_at.isoformat(),
            }
            for a in accounts
        ]
    }


@router.post("/accounts")
async def create_account(
    payload: AccountCreate,
    request: Request,
    user_id: int = Query(..., description="用户ID"),
    db: Session = Depends(get_db),
):
    """创建第三方账号（token加密存储）"""
    from datetime import datetime
    
    try:
        expires_at = datetime.fromisoformat(payload.token_expires_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的过期时间格式")
    
    account = netdisk_service.create_account(
        db=db,
        user_id=user_id,
        provider=payload.provider,
        uk_provider_uid=payload.uk_provider_uid,
        access_token=payload.access_token,
        refresh_token=payload.refresh_token,
        token_expires_at=expires_at,
        account_name=payload.account_name,
    )
    
    # 记录操作日志
    netdisk_service.log_operation(
        db=db,
        user_id=user_id,
        action="netdisk.bind",
        status="success",
        provider=payload.provider,
        resource_id=str(account.id),
        ip_address=request.client.host if request.client else None,
    )
    
    return {"id": account.id, "message": "账号绑定成功"}


@router.put("/accounts/{account_id}/tokens")
async def update_tokens(
    account_id: int,
    payload: TokenUpdate,
    request: Request,
    user_id: int = Query(..., description="用户ID"),
    db: Session = Depends(get_db),
):
    """更新账号token"""
    from datetime import datetime
    
    # 验证账号归属
    account = db.query(netdisk_service.ThirdPartyAccount).filter(
        netdisk_service.ThirdPartyAccount.id == account_id,
        netdisk_service.ThirdPartyAccount.user_id == user_id,
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    
    expires_at = None
    if payload.token_expires_at:
        try:
            expires_at = datetime.fromisoformat(payload.token_expires_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的过期时间格式")
    
    success = netdisk_service.update_account_tokens(
        db=db,
        account_id=account_id,
        access_token=payload.access_token,
        refresh_token=payload.refresh_token,
        token_expires_at=expires_at,
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="更新失败")
    
    # 记录操作日志
    netdisk_service.log_operation(
        db=db,
        user_id=user_id,
        action="netdisk.token_refresh",
        status="success",
        provider=account.provider,
        resource_id=str(account_id),
        ip_address=request.client.host if request.client else None,
    )
    
    return {"message": "token更新成功"}


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: int,
    request: Request,
    user_id: int = Query(..., description="用户ID"),
    db: Session = Depends(get_db),
):
    """解绑账号（停用）"""
    account = db.query(netdisk_service.ThirdPartyAccount).filter(
        netdisk_service.ThirdPartyAccount.id == account_id,
        netdisk_service.ThirdPartyAccount.user_id == user_id,
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    
    success = netdisk_service.deactivate_account(db, account_id)
    if not success:
        raise HTTPException(status_code=500, detail="解绑失败")
    
    # 记录操作日志
    netdisk_service.log_operation(
        db=db,
        user_id=user_id,
        action="netdisk.unbind",
        status="success",
        provider=account.provider,
        resource_id=str(account_id),
        ip_address=request.client.host if request.client else None,
    )
    
    return {"message": "账号已解绑"}


# --- File Cache ---

@router.get("/cache/stats")
async def cache_stats(
    db: Session = Depends(get_db),
):
    """查看缓存统计"""
    total = db.query(netdisk_service.NetdiskFileCache).count()
    expired = (
        db.query(netdisk_service.NetdiskFileCache)
        .filter(netdisk_service.NetdiskFileCache.expires_at < netdisk_service.datetime.now(netdisk_service.timezone.utc))
        .count()
    )
    
    return {
        "total_cached": total,
        "expired": expired,
        "valid": total - expired,
    }


@router.post("/cache/cleanup")
async def cleanup_cache(
    db: Session = Depends(get_db),
):
    """清理过期缓存"""
    count = netdisk_service.cleanup_expired_cache(db)
    return {"cleaned": count, "message": f"已清理{count}条过期缓存"}


# --- Preview Sessions ---

@router.get("/sessions")
async def list_sessions(
    user_id: int = Query(..., description="用户ID"),
    db: Session = Depends(get_db),
):
    """列出用户的预览会话"""
    sessions = (
        db.query(netdisk_service.PreviewSession)
        .filter(
            netdisk_service.PreviewSession.user_id == user_id,
            netdisk_service.PreviewSession.session_expires_at > netdisk_service.datetime.now(netdisk_service.timezone.utc),
        )
        .order_by(netdisk_service.PreviewSession.updated_at.desc())
        .all()
    )
    
    return {
        "total": len(sessions),
        "items": [
            {
                "id": s.id,
                "file_id": s.file_id,
                "play_position": s.play_position,
                "progress_percent": s.progress_percent,
                "page_number": s.page_number,
                "session_expires_at": s.session_expires_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
            }
            for s in sessions
        ]
    }


@router.post("/sessions")
async def update_session(
    payload: PreviewSessionUpdate,
    request: Request,
    user_id: int = Query(..., description="用户ID"),
    db: Session = Depends(get_db),
):
    """更新预览进度"""
    session = netdisk_service.create_or_update_preview_session(
        db=db,
        user_id=user_id,
        file_id=payload.file_id,
        play_position=payload.play_position,
        progress_percent=payload.progress_percent,
        page_number=payload.page_number,
    )
    
    # 记录操作日志
    netdisk_service.log_operation(
        db=db,
        user_id=user_id,
        action="netdisk.preview",
        status="success",
        resource_id=payload.file_id,
        ip_address=request.client.host if request.client else None,
    )
    
    return {"id": session.id, "message": "进度已保存"}


@router.post("/sessions/cleanup")
async def cleanup_sessions(
    db: Session = Depends(get_db),
):
    """清理过期会话"""
    count = netdisk_service.cleanup_expired_sessions(db)
    return {"cleaned": count, "message": f"已清理{count}条过期会话"}


# --- Operation Logs ---

@router.get("/logs")
async def list_logs(
    user_id: int = Query(..., description="用户ID"),
    action: Optional[str] = Query(None, description="操作类型筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """查询操作日志"""
    q = db.query(netdisk_service.NetdiskOperationLog).filter(
        netdisk_service.NetdiskOperationLog.user_id == user_id
    )
    
    if action:
        q = q.filter(netdisk_service.NetdiskOperationLog.action == action)
    if status:
        q = q.filter(netdisk_service.NetdiskOperationLog.status == status)
    
    total = q.count()
    logs = q.order_by(
        netdisk_service.NetdiskOperationLog.created_at.desc()
    ).offset((page - 1) * limit).limit(limit).all()
    
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": log.id,
                "action": log.action,
                "provider": log.provider,
                "resource_id": log.resource_id,
                "status": log.status,
                "error_code": log.error_code,
                "error_message": log.error_message,
                "ip_address": log.ip_address,
                "extra_metadata": log.extra_metadata,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    }
