"""
数据库备份管理路由 V3.0
支持：列出备份、创建备份、恢复备份、删除备份
"""
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.backup_service import (
    create_backup,
    list_backups,
    restore_backup,
    BACKUP_DIR,
)

router = APIRouter(prefix="/api/backup", tags=["backup"])


class RestoreRequest(BaseModel):
    backup_path: str


class DeleteRequest(BaseModel):
    backup_path: str


@router.get("")
async def get_backups():
    """列出所有数据库备份"""
    backups = list_backups()
    return {"items": backups, "total": len(backups), "backup_dir": BACKUP_DIR}


@router.post("/create")
async def create_new_backup():
    """手动创建数据库备份"""
    backup_path = create_backup()
    if not backup_path:
        raise HTTPException(status_code=500, detail="备份创建失败")
    return {"success": True, "backup_path": backup_path, "message": "备份创建成功"}


@router.post("/restore")
async def restore_from_backup(req: RestoreRequest):
    """从备份恢复数据库（需要重启服务后生效）"""
    if not os.path.exists(req.backup_path):
        raise HTTPException(status_code=404, detail="备份文件不存在")
    success = restore_backup(req.backup_path)
    if not success:
        raise HTTPException(status_code=500, detail="恢复失败")
    return {"success": True, "message": "数据库已恢复，请重启服务使变更生效"}


@router.post("/delete")
async def delete_backup(req: DeleteRequest):
    """删除指定备份"""
    if not os.path.exists(req.backup_path):
        raise HTTPException(status_code=404, detail="备份文件不存在")
    if not req.backup_path.startswith(BACKUP_DIR):
        raise HTTPException(status_code=400, detail="只能删除备份目录下的文件")
    try:
        os.unlink(req.backup_path)
        return {"success": True, "message": "备份已删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")
