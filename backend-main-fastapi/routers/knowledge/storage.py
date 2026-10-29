"""
V3.0 本地存储库管理路由
提供存储库扫描、文件入库、统计等API接口。
"""
import os
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.storage_watcher import StorageWatcher
from utils.security import require_admin

router = APIRouter(prefix="/api/storage", tags=["storage"], dependencies=[Depends(require_admin)])


class IngestRequest(BaseModel):
    force: bool = False
    file_path: str = None  # 可选：指定单个文件入库


@router.get("")
def get_storage_stats(db: Session = Depends(get_db)):
    """获取存储库统计信息。

    注意：这里是同步 def，FastAPI 会自动丢到线程池执行。
    StorageWatcher 会做全盘目录遍历（数秒级），绝不能占用事件循环。
    """
    watcher = StorageWatcher(db)
    return watcher.get_storage_stats()


@router.get("/scan")
def scan_storage(force: bool = False, db: Session = Depends(get_db)):
    """扫描存储库，识别新文件或变更文件。

    P0 修复：原为 `async def` + 同步 IO，77 秒的全盘扫描把事件循环完全占死，
    期间所有其他请求（含 /api/health）都无法响应，表现为"服务假死"。
    改为同步 def 后由Starlette 自动在 anyio 线程池执行，事件循环保持可响应。

    Depends(get_db) 在同步 def 中同样有效，依赖注入不受影响。
    """
    watcher = StorageWatcher(db)
    return watcher.scan_storage(force=force)


@router.post("/ingest")
def ingest_files(
    req: IngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    批量入库新文件或变更文件。
    如果文件较多，会在后台任务中执行。

    同步 def：解析文档 + 写库是重IO/ CPU 操作，放线程池避免阻塞事件循环。
    """
    watcher = StorageWatcher(db)

    # 如果指定了单个文件，先扫描找到它
    if req.file_path:
        scan_result = watcher.scan_storage(force=req.force)
        all_files = scan_result.get('new_files_list', []) + scan_result.get('modified_files_list', [])
        target = next((f for f in all_files if f['path'] == req.file_path or f['relative_path'] == req.file_path), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"未找到文件: {req.file_path}")
        return watcher.ingest_file(target)

    # 批量入库
    result = watcher.ingest_all_new_files(force=req.force)
    return result


@router.get("/processed")
def get_processed_files(db: Session = Depends(get_db)):
    """获取已处理文件列表。"""
    watcher = StorageWatcher(db)
    files = watcher.get_processed_files()
    return {"items": files, "total": len(files)}


@router.post("/rescan")
def rescan_all(db: Session = Depends(get_db)):
    """强制重新扫描所有文件（忽略已处理记录）。"""
    watcher = StorageWatcher(db)
    return watcher.scan_storage(force=True)


@router.delete("/processed/{file_key}")
def remove_processed_record(file_key: str, db: Session = Depends(get_db)):
    """删除已处理文件记录（允许重新入库）。"""
    watcher = StorageWatcher(db)
    if file_key in watcher.processed_files:
        del watcher.processed_files[file_key]
        watcher._save_processed_files()
        return {"success": True, "message": f"已删除记录: {file_key}"}
    raise HTTPException(status_code=404, detail=f"未找到记录: {file_key}")
