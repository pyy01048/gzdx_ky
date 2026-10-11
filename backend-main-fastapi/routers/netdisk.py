"""网盘路由。"""

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import os
import re
import httpx
from urllib.parse import unquote



from database import get_db, BASE_DIR
from models import NetdiskFile, PlatformConfig, Document
from services.netdisk_service import NetdiskService, NetdiskError, NetdiskAuthError
from utils.timeutil import utcnow  # 统一 naive UTC 时间规范（P0-4）

router = APIRouter(prefix="/api/netdisk", tags=["netdisk"])

UPLOAD_DIR = os.path.join(BASE_DIR, "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

#: 单个网盘文件下载上限（默认 200MB）—— 防止误点视频把磁盘/内存吃光
MAX_DOWNLOAD_BYTES = int(os.getenv("NETDISK_MAX_DOWNLOAD_MB", "200")) * 1024 * 1024


def _netdisk_http_error(e: Exception) -> HTTPException:
    """把网盘异常翻译成带人话提示的 HTTP 错误。"""
    if isinstance(e, NetdiskAuthError):
        return HTTPException(
            status_code=401,
            detail={"message": e.errmsg, "errno": e.errno, "action": "reauthorize"},
        )
    if isinstance(e, NetdiskError):
        return HTTPException(
            status_code=502,
            detail={"message": e.errmsg, "errno": e.errno, "request_id": e.request_id},
        )
    return HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@router.get("/auth-url")
async def get_auth_url(redirect_uri: str = "oob", db: Session = Depends(get_db)):
    """获取百度网盘 OAuth 授权 URL。"""
    service = NetdiskService(db)
    url = service.get_auth_url(redirect_uri)
    return {"auth_url": url}


@router.get("/token-status")
async def token_status(db: Session = Depends(get_db)):
    """token 状态：是否已授权、还能用多久、有无 refresh_token。

    前端应据此在"即将过期/已过期"时提示重新授权。
    """
    return NetdiskService(db).token_status()


@router.post("/refresh-token")
async def refresh_token(db: Session = Depends(get_db)):
    """手动刷新 access_token（通常在 token-status 提示过期后调用）。"""
    service = NetdiskService(db)
    try:
        return await service.refresh_access_token()
    except Exception as e:
        raise _netdisk_http_error(e)


@router.post("/callback")
async def handle_callback(code: str, redirect_uri: str = "oob", db: Session = Depends(get_db)):
    """OAuth 回调处理。"""
    service = NetdiskService(db)
    try:
        result = await service.handle_callback(code, redirect_uri)
        return result
    except Exception as e:
        raise _netdisk_http_error(e)


@router.get("/search")
async def search_netdisk(
    keyword: str,
    dir_path: str = "/",
    page: int = 1,
    db: Session = Depends(get_db),
):
    """按关键词搜索网盘文件。

    考研资料通常埋在「科目/章节/年份」多层目录里，一层层点太慢，
    搜索才是找资料的主入口。
    """
    if not keyword.strip():
        raise HTTPException(status_code=400, detail="关键词不能为空")
    service = NetdiskService(db)
    try:
        data = await service.search_files(keyword, dir_path=dir_path, page=page)
    except Exception as e:
        raise _netdisk_http_error(e)
    items = data.get("list") or []
    return {
        "keyword": keyword,
        "total": len(items),
        "items": [_decorate_netdisk_item(it, service) for it in items],
    }


@router.get("/recursive-files")
async def recursive_files(
    path: str = "/",
    max_items: int = 500,
    max_depth: int = 2,
    deadline: float = 25.0,
    db: Session = Depends(get_db),
):
    """递归列出目录下文件（含子目录）。

    ⚠️ **实测性能提醒**：百度网盘单次列表请求约 6-7 秒，
    递归每多一层就多几倍请求。实测账号有 1.3TB 资料时，
    深度 4 + 2000 条的默认值会跑到超时。

    所以默认收得很紧（深度 2 / 500 条 / 25 秒），宁可返回部分结果 + 截断标记。
    **找具体资料请优先用 `/search`（关键词搜索，一次请求跨全盘）。**
    """
    service = NetdiskService(db)
    try:
        data = await service.list_all(
            path, max_items=max_items, max_depth=max_depth, deadline=deadline
        )
    except Exception as e:
        raise _netdisk_http_error(e)
    items = data.get("list") or []
    return {
        "path": path,
        "total": len(items),
        "truncated": data.get("truncated", False),
        "reason": data.get("reason"),
        "hint": data.get("hint"),
        "params": {"max_items": max_items, "max_depth": max_depth, "deadline": deadline},
        "items": [_decorate_netdisk_item(it, service) for it in items],
    }


@router.get("/quota")
async def netdisk_quota(db: Session = Depends(get_db)):
    """网盘容量。"""
    try:
        return await NetdiskService(db).get_quota()
    except Exception as e:
        raise _netdisk_http_error(e)


def _decorate_netdisk_item(item: dict, service: NetdiskService) -> dict:
    """给网盘原始条目补上：大小可读化、自动分类、科目猜测、能否入库。"""
    from services.document_parser import DocumentParser

    name = item.get("server_filename") or item.get("filename") or ""
    # 百度 category：1 视频 2 音频 3 图片 4 文档 5 应用 6 其他 7 种子
    cat_map = {1: "视频", 2: "音频", 3: "图片", 4: "文档", 5: "应用", 6: "其他", 7: "种子"}
    file_type = DocumentParser.file_type(name)
    return {
        "fs_id": item.get("fs_id"),
        "file_name": name,
        "path": item.get("path"),
        "isdir": bool(item.get("isdir")),
        "size": item.get("size", 0),
        "size_mb": round((item.get("size") or 0) / 1048576, 2),
        "md5": item.get("md5"),
        "server_mtime": item.get("server_mtime"),
        "category": cat_map.get(item.get("category"), service.auto_classify(name)),
        "subject_guess": service.auto_classify(name),
        # 只有可解析的类型才允许入库，避免前端点了没反应
        "ingestible": (not item.get("isdir")) and file_type != "other",
        "file_type": file_type,
    }


@router.get("/files")
async def list_files(
    path: str = "/",
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    """网盘文件列表。"""
    # 先从本地数据库查
    local_files = (
        db.query(NetdiskFile)
        .filter(NetdiskFile.path.like(f"{path}%"))
        .order_by(NetdiskFile.file_name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    total = db.query(NetdiskFile).filter(NetdiskFile.path.like(f"{path}%")).count()

    # 尝试从网盘 API 实时获取
    service = NetdiskService(db)
    api_files = []
    try:
        api_result = await service.get_file_list(path, page, page_size)
        api_files = api_result.get("list", [])
    except Exception:
        pass  # API 不可用时返回本地缓存

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "local_files": [
            {
                "id": f.id,
                "file_name": f.file_name,
                "path": f.path,
                "file_type": f.file_type,
                "size": f.size,
                "category": f.category,
                "play_progress": f.play_progress,
            }
            for f in local_files
        ],
        "api_files": api_files,
    }


@router.get("/files/{file_id}")
async def get_file_detail(file_id: int, db: Session = Depends(get_db)):
    """文件详情。"""
    file = db.query(NetdiskFile).filter(NetdiskFile.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")
    return {
        "id": file.id,
        "file_name": file.file_name,
        "path": file.path,
        "file_type": file.file_type,
        "size": file.size,
        "category": file.category,
        "download_link": file.download_link,
        "play_progress": file.play_progress,
        "fs_id": file.fs_id,
    }


@router.post("/sync")
async def sync_files(path: str = "/", db: Session = Depends(get_db)):
    """手动同步。"""
    service = NetdiskService(db)
    try:
        result = await service.get_file_list(path)
        files = result.get("list", [])
        synced = 0
        for f in files:
            fs_id = str(f.get("fs_id", ""))
            existing = db.query(NetdiskFile).filter(NetdiskFile.fs_id == fs_id).first()
            file_data = {
                "file_name": f.get("server_filename", f.get("filename", "")),
                "path": f.get("path", ""),
                "file_type": _guess_type(f.get("server_filename", "")),
                "size": f.get("size", 0),
                "category": service.auto_classify(f.get("server_filename", "")),
                "fs_id": fs_id,
            }
            if existing:
                for key, value in file_data.items():
                    setattr(existing, key, value)
            else:
                db.add(NetdiskFile(**file_data))
            synced += 1

        # 更新同步时间
        config = (
            db.query(PlatformConfig)
            .filter(PlatformConfig.platform_name == "baidu_netdisk")
            .first()
        )
        if config:
            config.last_sync = utcnow()  # naive UTC，与 DB 列对齐（P0-4）

        db.commit()
        return {"synced": synced, "message": f"同步完成，共 {synced} 个文件"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步失败：{str(e)}")


@router.get("/preview/{file_id}")
async def get_preview(file_id: int, db: Session = Depends(get_db)):
    """文件预览链接。"""
    file = db.query(NetdiskFile).filter(NetdiskFile.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")

    service = NetdiskService(db)
    if file.fs_id:
        try:
            result = await service.get_preview_link(file.fs_id)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"获取预览链接失败：{str(e)}")
    raise HTTPException(status_code=400, detail="文件缺少网盘 ID")


@router.post("/classify")
async def classify_files(db: Session = Depends(get_db)):
    """AI 自动分类。"""
    service = NetdiskService(db)
    files = db.query(NetdiskFile).all()
    classified = 0
    for f in files:
        if not f.category or f.category == "其他":
            f.category = service.auto_classify(f.file_name)
            classified += 1
    db.commit()
    return {"classified": classified, "message": f"自动分类完成，共 {classified} 个文件"}


def _guess_type(filename: str) -> str:
    """根据文件名推断类型。"""
    name = (filename or "").lower()
    if any(name.endswith(ext) for ext in [".mp4", ".avi", ".mkv", ".mov", ".flv"]):
        return "video"
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".mp3", ".wav", ".flac")):
        return "audio"
    if name.endswith((".doc", ".docx", ".txt")):
        return "doc"
    return "other"


# --------------------------------------------------------------------------- #
# 网盘文件 -> 本地知识库（P0-1 闭环：打通"网盘资料进知识库"）
# --------------------------------------------------------------------------- #
async def _resolve_netdisk_file(db: Session, fs_id, file_name=None, path=None) -> NetdiskFile:
    """按 fs_id 查找或创建 NetdiskFile 记录（前端始终持有 baidu fs_id）。"""
    file = db.query(NetdiskFile).filter(NetdiskFile.fs_id == str(fs_id)).first()
    if file:
        return file
    service = NetdiskService(db)
    try:
        info = await service.get_file_info(str(fs_id))
    except Exception:
        info = {}
    name = file_name or info.get("filename") or f"netdisk_{fs_id}"
    fpath = path or info.get("path") or "/"
    file = NetdiskFile(
        file_name=name,
        path=fpath,
        file_type=_guess_type(name),
        size=info.get("size", 0),
        category=service.auto_classify(name),
        fs_id=str(fs_id),
    )
    db.add(file)
    db.commit()
    db.refresh(file)
    return file


async def _ingest_netdisk_file(db: Session, file: NetdiskFile) -> dict:
    """下载单个网盘文件并入库到本地知识库，返回结果摘要。

    注意：下载走**流式**写入磁盘（`download_to_file`），不再把整个文件
    读进内存 —— 之前用 `resp.content` 一次性读，遇上百 MB 课件容易把进程撑爆。
    """
    from services.kb_service import ingest_text, detect_doc_meta
    from services.document_parser import DocumentParser

    if not file.fs_id:
        return {"file_name": file.file_name, "success": False, "message": "缺少网盘 ID，无法下载"}

    save_name = file.file_name or f"netdisk_{file.fs_id}"
    save_name = re.sub(r'[\\/:*?"<>|]', '_', save_name)

    # 已入库则跳过，避免重复
    existing = db.query(Document).filter(Document.file_name == save_name).first()
    if existing and existing.index_status == "indexed" and existing.content:
        return {
            "file_name": save_name, "success": True, "skipped": True,
            "document_id": existing.id, "chunk_count": 0,
            "message": "已入库，跳过",
        }

    # 下载前先判类型：不支持的类型不必浪费带宽
    file_type = DocumentParser.file_type(save_name)
    if file_type == "other":
        return {"file_name": save_name, "success": False,
                "message": "不支持的文件类型（仅 PDF/DOC/DOCX/PPT/PPTX/TXT/MD）"}

    service = NetdiskService(db)
    save_path = os.path.join(UPLOAD_DIR, save_name)
    try:
        dl = await service.download_to_file(file.fs_id, save_path, max_bytes=MAX_DOWNLOAD_BYTES)
    except Exception as e:
        return {"file_name": save_name, "success": False, "message": f"文件下载失败：{e}"}
    size = dl.get("size", 0)

    doc = Document(
        file_name=save_name,
        file_path=save_path,
        file_type=file_type,
        size=size,
        index_status="indexing",
        parse_progress=0.2,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    parser = DocumentParser()
    try:
        content_text = parser.parse(save_path)
    except Exception as e:
        doc.index_status = "failed"
        db.commit()
        return {"file_name": save_name, "success": False, "message": f"文档解析失败：{str(e)}"}
    if not content_text or not content_text.strip():
        content_text = f"[{file_type} 文件，未能提取到文本内容] 文件名：{save_name}"

    doc.content = content_text
    doc.parse_progress = 0.6
    db.commit()

    chunk_count = 0
    try:
        chunk_count = ingest_text(db, doc.id, save_name, content_text, replace=True)
    except Exception as e:
        print(f"[kb] 网盘文件 {save_name} 入库分块失败: {e}")

    # 打上资料层级 / 扫描件标记（网盘导入的资料同样需要一个口径）
    meta = {}
    try:
        meta = detect_doc_meta(db, doc)
    except Exception as e:
        print(f"[kb] 网盘文件 {save_name} 元信息判定失败: {e}")

    doc.index_status = "indexed"
    doc.parse_progress = 1.0
    db.commit()
    return {
        "file_name": save_name,
        "document_id": doc.id,
        "chunk_count": chunk_count,
        "size": size,
        "ocr_used": meta.get("ocr_used", False),
        "doc_type": meta.get("doc_type"),
        "success": chunk_count > 0,
        "message": f"已下载并入库，生成 {chunk_count} 个知识分块" if chunk_count else "已解析但未生成分块",
    }


@router.post("/ingest")
async def ingest_by_fsid(payload: dict, db: Session = Depends(get_db)):
    """按 fs_id 将网盘文件下载、解析并入库到本地知识库（前端主入口）。

    前端始终持有 baidu fs_id，故以此为入参；后端自动查找或创建 NetdiskFile 记录再入库。
    """
    fs_id = payload.get("fs_id") or (payload.get("file") or {}).get("fs_id")
    if not fs_id:
        raise HTTPException(status_code=400, detail="缺少 fs_id")
    file = await _resolve_netdisk_file(db, fs_id, payload.get("file_name"), payload.get("path"))
    result = await _ingest_netdisk_file(db, file)
    if not result.get("success") and not result.get("skipped"):
        raise HTTPException(status_code=400, detail=result.get("message", "入库失败"))
    return result


@router.post("/files/{file_id}/ingest")
async def ingest_netdisk_file(file_id: int, db: Session = Depends(get_db)):
    """将单个网盘文件下载、解析并入库到本地知识库（按后端文件 ID）。"""
    file = db.query(NetdiskFile).filter(NetdiskFile.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")
    result = await _ingest_netdisk_file(db, file)
    if not result.get("success") and not result.get("skipped"):
        raise HTTPException(status_code=400, detail=result.get("message", "入库失败"))
    return result


@router.post("/ingest-all")
async def ingest_all_netdisk(db: Session = Depends(get_db)):
    """批量将网盘文件（支持的类型）下载并入库到本地知识库。"""
    supported = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".txt", ".md"}
    files = db.query(NetdiskFile).all()
    results = []
    for f in files:
        if not f.file_name:
            continue
        ext = os.path.splitext(f.file_name)[1].lower()
        if ext not in supported:
            continue
        results.append(await _ingest_netdisk_file(db, f))
    ingested = sum(1 for r in results if r.get("success") and not r.get("skipped"))
    skipped = sum(1 for r in results if r.get("skipped"))
    failed = sum(1 for r in results if not r.get("success"))
    return {
        "total": len(results),
        "ingested": ingested,
        "skipped": skipped,
        "failed": failed,
        "results": results,
        "message": f"批量入库完成：新入库 {ingested}，跳过 {skipped}，失败 {failed}，共 {len(results)} 个文件",
    }


# --------------------------------------------------------------------------- #
# 平台配置管理
# --------------------------------------------------------------------------- #
# 平台名 -> 数据库 platform_name 的映射
_PLATFORM_MAP = {
    "baidu": "baidu_netdisk",
    "shengcai": "shengcai",
    "anki": "anki",
    "momo": "momo",
    "bilibili": "bilibili",
    "xmind": "xmind",
}


def _serialize_config(cfg: PlatformConfig) -> dict:
    """将 PlatformConfig 行序列化为前端可用的扁平字典。"""
    extra = cfg.extra or {}
    return {
        "platform": cfg.platform_name,
        "token": cfg.token or "",
        "app_key": cfg.app_key or "",
        "secret_key": cfg.secret_key or "",
        "sync_enabled": cfg.sync_enabled,
        "sync_frequency": cfg.sync_frequency or "daily",
        "last_sync": cfg.last_sync.isoformat() if cfg.last_sync else None,
        "extra": extra,
        # 同时把 extra 的键提升到顶层，方便前端直接 v-model
        **extra,
    }


@router.get("/platform-configs")
async def list_platform_configs(db: Session = Depends(get_db)):
    """获取所有平台配置。"""
    configs = db.query(PlatformConfig).all()
    # 以 platform_name 为键返回
    result = {}
    for cfg in configs:
        key = cfg.platform_name
        # 反查短 id
        short = next((k for k, v in _PLATFORM_MAP.items() if v == key), key)
        result[short] = _serialize_config(cfg)
    return {"configs": result}


@router.get("/platform-config/{platform}")
async def get_platform_config(platform: str, db: Session = Depends(get_db)):
    """获取指定平台配置。"""
    name = _PLATFORM_MAP.get(platform, platform)
    cfg = (
        db.query(PlatformConfig)
        .filter(PlatformConfig.platform_name == name)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=f"平台 {platform} 配置不存在")
    return _serialize_config(cfg)


@router.put("/platform-config/{platform}")
async def update_platform_config(platform: str, body: dict, db: Session = Depends(get_db)):
    """更新平台配置。

    请求体可包含标准字段（token/app_key/secret_key/sync_enabled/sync_frequency）
    以及平台专属字段（存入 extra JSON）。
    """
    name = _PLATFORM_MAP.get(platform, platform)
    cfg = (
        db.query(PlatformConfig)
        .filter(PlatformConfig.platform_name == name)
        .first()
    )
    if not cfg:
        # 不存在则新建
        cfg = PlatformConfig(platform_name=name)
        db.add(cfg)

    # 标准字段白名单
    standard_fields = {
        "token": str,
        "app_key": str,
        "secret_key": str,
        "sync_frequency": str,
    }
    extra = dict(cfg.extra or {})

    for key, value in body.items():
        if key in standard_fields:
            setattr(cfg, key, standard_fields[key](value) if value is not None else None)
        elif key == "sync_enabled":
            cfg.sync_enabled = bool(value)
        elif key in ("platform", "last_sync", "extra"):
            # 跳过只读 / 嵌套字段
            continue
        else:
            # 其余字段写入 extra
            extra[key] = value

    cfg.extra = extra
    db.commit()
    db.refresh(cfg)
    return _serialize_config(cfg)


# --------------------------------------------------------------------------- #
# 平台连接测试
# --------------------------------------------------------------------------- #
@router.post("/test-connection/{platform}")
async def test_platform_connection(platform: str, db: Session = Depends(get_db)):
    """测试指定平台的连接状态。

    根据平台类型执行不同的验证逻辑：
    - baidu: 检查 OAuth 授权状态
    - anki: 检查 AnkiConnect 服务是否可达
    - bilibili: 检查 SESSDATA Cookie 有效性
    - shengcai/momo/xmind: 检查必要配置是否填写
    """
    import httpx

    name = _PLATFORM_MAP.get(platform, platform)
    cfg = (
        db.query(PlatformConfig)
        .filter(PlatformConfig.platform_name == name)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail=f"平台 {platform} 配置不存在，请先保存配置")

    extra = cfg.extra or {}

    # ---- 百度网盘 ---- #
    if platform == "baidu":
        # 走 NetdiskService.test_connection()：除了看有没有 token，
        # 还会真实调一次接口验证授权是否仍有效（token 会过期），
        # 并汇报容量与剩余有效期。
        service = NetdiskService(db)
        result = await service.test_connection()
        status = service.token_status()
        return {
            "connected": bool(result.get("ok")),
            "message": result.get("message", ""),
            "authorized": result.get("authorized"),
            "has_refresh_token": result.get("has_refresh_token"),
            "auth_url": result.get("auth_url"),
            "quota": result.get("quota"),
            "token": status,
        }

    # ---- Anki (AnkiConnect 本地服务) ---- #
    elif platform == "anki":
        url = extra.get("anki_connect_url", "http://localhost:8765")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    json={"action": "version", "version": 6},
                    timeout=5,
                )
            if resp.status_code == 200:
                version = resp.json().get("result", "unknown")
                return {"connected": True, "message": f"AnkiConnect 连接成功（版本 {version}），请确保 Anki 桌面端正在运行"}
            return {"connected": False, "message": "AnkiConnect 响应异常"}
        except Exception as e:
            return {"connected": False, "message": f"AnkiConnect 不可用：{str(e)}。请确保 Anki 桌面端已启动并安装 AnkiConnect 插件"}

    # ---- B站 ---- #
    elif platform == "bilibili":
        sessdata = extra.get("sessdata", "")
        if not sessdata:
            return {"connected": False, "message": "请先填写 B站 SESSDATA Cookie"}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.bilibili.com/x/web-interface/nav",
                    cookies={"SESSDATA": sessdata},
                    timeout=10,
                )
            data = resp.json()
            if data.get("code") == 0:
                uname = data.get("data", {}).get("uname", "未知用户")
                return {"connected": True, "message": f"B站连接成功，当前用户：{uname}"}
            return {"connected": False, "message": "SESSDATA Cookie 无效或已过期，请重新获取"}
        except Exception as e:
            return {"connected": False, "message": f"B站连接失败：{str(e)}"}

    # ---- 圣才教育 ---- #
    elif platform == "shengcai":
        username = extra.get("username", "")
        password = extra.get("password", "")
        if not username or not password:
            return {"connected": False, "message": "请先填写圣才教育用户名和密码"}
        # 圣才教育无公开 API，配置保存即为"就绪"
        return {"connected": True, "message": "圣才教育配置已就绪（用户名/密码已填写），实际登录需通过浏览器自动化对接"}

    # ---- 墨墨背词 ---- #
    elif platform == "momo":
        device_id = extra.get("device_id", "")
        if not device_id:
            return {"connected": False, "message": "请先填写墨墨设备 ID"}
        return {"connected": True, "message": "墨墨背词配置已就绪（设备 ID 已填写），数据导入需通过墨墨导出文件对接"}

    # ---- XMind / 幕布 ---- #
    elif platform == "xmind":
        import_dir = extra.get("import_dir", "")
        if not import_dir:
            return {"connected": False, "message": "请先设置思维导图导入目录"}
        import os
        if not os.path.exists(import_dir):
            return {"connected": False, "message": f"导入目录不存在：{import_dir}"}
        return {"connected": True, "message": f"XMind 配置已就绪，导入目录有效：{import_dir}"}

    return {"connected": False, "message": f"未知平台：{platform}"}


# --------------------------------------------------------------------------- #
# 已删除 ingest_netdisk_file_to_kb()（2026-10）
#
# 原因：该函数按一套**不存在的 schema** 编写，调用即崩 —— 它引用了
#   Document.source / file_size / title / netdisk_file_id / parse_error
#   / parsed_at / uploaded_at（这些列均不存在），
#   并使用了 index_status="ready"/"indexing"（真实取值是
#   pending/indexing/indexed/failed），还把本地路径当 fs_id 传给下载接口。
#
# 它从未被任何代码调用（仅此处定义），实际入库链路走 _ingest_netdisk_file()。
# --------------------------------------------------------------------------- #
