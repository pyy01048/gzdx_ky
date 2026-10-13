"""网盘路由。"""

import datetime
from typing import Optional

import os
import re
import httpx
import mimetypes
from urllib.parse import unquote, quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session



from database import get_db, BASE_DIR
from models import NetdiskFile, PlatformConfig, Document
from services.doc_naming import apply_display_name
from services.smart_ingest import gate_for_write
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
    """网盘文件列表。

    local_files 是本地同步缓存（/netdisk/sync 写入的 netdisk_files 行），
    api_files 是百度网盘实时列表。**授权失效时本接口返回 401 而不是
    静默返回本地缓存** —— 以前 `except Exception: pass` 会让页面拿着
    缓存照样渲染"目录"，用户以为网盘还连着（#netdisk-refactor 修的漏洞）。
    """
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
    api_error = None
    try:
        api_result = await service.get_file_list(path, page, page_size)
        api_files = api_result.get("list", [])
    except NetdiskAuthError as e:
        # 授权失效必须显式 401：前端据此回到平台选择页要求重新授权，
        # 而不是显示一份来路不明的本地缓存目录。
        raise _netdisk_http_error(e)
    except Exception as e:  # noqa: BLE001
        # 网络抖动等非授权错误：保留本地缓存，但把失败原因显式带回前端
        api_error = f"{type(e).__name__}: {e}"

    resp = {
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
                "fs_id": f.fs_id,
                "download_link": f.download_link,
                # toPan 需要真实上传时间；缺字段时前端会退回 localStorage 的旧值，
                # 但绝不能由后端补一个"今天"，那等于伪造同步日期。
                "created_at": f.created_at,
            }
            for f in local_files
        ],
        "api_files": api_files,
    }
    if api_error:
        resp["api_error"] = api_error
    return resp


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
async def sync_files(
    path: str = "",
    max_depth: int = 4,
    max_items: int = 2000,
    deadline: float = 45.0,
    db: Session = Depends(get_db),
):
    """手动同步（**递归**）。

    修复前这里调的是 `get_file_list()` —— 只列一层，于是库里永远是
    「AI笔记 / StarNote / 我的资源」这几个根目录条目，真正的资料一个都进不来。
    现改为 `list_all()`（下钻 4 层 + 条数/耗时双闸 + 截断标记）。

    path 留空时自动使用配置里的 sync_dir（platform_configs.extra.sync_dir）。
    """
    service = NetdiskService(db)

    # 未显式指定目录时，落到配置里的同步根目录
    if not path:
        path = service._get_config().get("sync_dir") or "/"

    try:
        result = await service.list_all(
            path, max_depth=max_depth, max_items=max_items, deadline=deadline
        )
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


async def _proxy_stream(file: NetdiskFile, disposition: str, db: Session, request: Request = None):
    service = NetdiskService(db)
    try:
        # 先把链接取到手：授权失效/token 过期在这一步就该变成干净的 401/502，
        # 而不是响应头已发出、流到一半才炸给浏览器一个残缺文件。
        info = await service.get_download_url(file.fs_id)
    except (NetdiskError, NetdiskAuthError) as e:
        raise _netdisk_http_error(e)

    name = file.file_name or info.get("filename") or f"netdisk_{file.fs_id}"
    size = int(info.get("size") or file.size or 0)
    if size and size > MAX_DOWNLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件 {size / 1048576:.0f}MB 超过代理上限 "
                   f"{MAX_DOWNLOAD_BYTES // 1048576}MB，请先入库再读本地原文")

    media = mimetypes.guess_type(name)[0] or "application/octet-stream"
    ascii_fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip() or f"netdisk_{file.fs_id}"
    headers = {
        "Content-Disposition": (f"{disposition}; filename=\"{ascii_fallback}\"; "
                                f"filename*=UTF-8''{quote(name, safe='')}"),
        "Cache-Control": "no-cache",
        # 声明支持 Range：视频播放器 seek / 图片分段加载都靠它。
        # 上游（百度 dlink）支持 Range 时透传 206，忽略时按 200 全量返回。
        "Accept-Ranges": "bytes",
    }
    if size:
        headers["Content-Length"] = str(size)

    # Range 透传：浏览器 <video> 拖动进度条会带 Range 头。
    # 先打开上游流再构造响应——这样 403/404 在响应头发出前就变成干净的错误码，
    # 不会给前端半个文件。
    range_header = request.headers.get("range") if request else None
    stream_cm = service.open_download(file.fs_id, range_header=range_header)
    resp, _client = await stream_cm.__aenter__()
    if resp.status_code == 403:
        await stream_cm.__aexit__(None, None, None)
        raise _netdisk_http_error(
            NetdiskError(403, "下载被拒绝（403）：请确认请求带 User-Agent: pan.baidu.com"))
    if resp.status_code >= 400:
        await stream_cm.__aexit__(None, None, None)
        raise _netdisk_http_error(
            NetdiskError(resp.status_code, f"上游返回 HTTP {resp.status_code}"))

    status_code = 200
    if range_header and resp.status_code == 206:
        status_code = 206
        content_range = resp.headers.get("content-range")
        if content_range:
            headers["Content-Range"] = content_range
        content_length = resp.headers.get("content-length")
        if content_length:
            headers["Content-Length"] = content_length

    async def _body():
        try:
            async for chunk in resp.aiter_bytes(1 << 20):
                if chunk:
                    yield chunk
        finally:
            await stream_cm.__aexit__(None, None, None)

    return StreamingResponse(_body(), status_code=status_code, media_type=media, headers=headers)


def _check_disposition(disposition: str) -> str:
    if disposition not in ("inline", "attachment"):
        raise HTTPException(status_code=400, detail="disposition 只支持 inline / attachment")
    return disposition


@router.get("/files/{file_id}/content")
async def stream_netdisk_content(file_id: int, request: Request, disposition: str = "inline",
                                 db: Session = Depends(get_db)):
    """按本地记录 ID 取网盘原文字节流（支持 Range，供视频播放器 seek）。"""
    file = db.query(NetdiskFile).filter(NetdiskFile.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")
    if not file.fs_id:
        raise HTTPException(status_code=400, detail="文件缺少网盘 ID，无法取流")
    _check_disposition(disposition)
    return await _proxy_stream(file, disposition, db, request)


@router.get("/content")
async def stream_netdisk_content_by_fsid(fs_id: str, request: Request, disposition: str = "inline",
                                         db: Session = Depends(get_db)):
    """按百度 fs_id 取流 —— 前端网盘目录页只持有 fs_id，没有本地记录 ID。

    没有这条的话 Pan.jsx 只能继续 `window.open(dlink)`，而 dlink 缺
    `User-Agent: pan.baidu.com` 必 403，用户看到的就是「下载没反应」。
    """
    if not fs_id.strip().isdigit():
        raise HTTPException(status_code=400, detail="fs_id 必须是数字")
    _check_disposition(disposition)
    file = await _resolve_netdisk_file(db, fs_id)
    return await _proxy_stream(file, disposition, db, request)


@router.post("/logout")
async def logout_netdisk(db: Session = Depends(get_db)):
    """退出百度网盘授权：清除后端 token（保留 app_key 等配置）。

    前端「退出授权」按钮调用。只清授权态不清配置，用户下次可直接重新授权。
    """
    row = (
        db.query(PlatformConfig)
        .filter(PlatformConfig.platform_name == "baidu_netdisk")
        .first()
    )
    if row:
        row.token = ""
        extra = dict(row.extra or {})
        for key in ("refresh_token", "expires_at"):
            extra.pop(key, None)
        row.extra = extra
        db.commit()
    return {"success": True, "message": "已退出百度网盘授权"}


@router.get("/quark/web-view")
async def quark_web_view(db: Session = Depends(get_db)):
    """夸克网盘 Web 视图嵌入地址（配置化）。

    **为什么是 Web 视图而不是 API 对接**：夸克网盘没有对外开放的文件 API
    —— 既无 OAuth 授权体系，也无文件列表/下载接口（与百度 xpan 开放平台
    完全不同）。因此本项目的夸克方案是「配置化 Web 视图嵌入」：

    - 后端只负责提供/校验可嵌入地址（platform_configs.quark_netdisk.extra.web_view_url，
      未配置时用内置默认 https://pan.quark.cn/）；
    - 前端以 iframe 嵌入该地址，用户的夸克登录态由浏览器自己的 Cookie 维护；
    - 站点若设置 X-Frame-Options 禁止嵌入导致白屏，前端提供「新窗口打开」兜底。

    安全：只允许 http/https 协议，拒绝 javascript: 等，防止 iframe 注入。
    """
    cfg = (
        db.query(PlatformConfig)
        .filter(PlatformConfig.platform_name == "quark_netdisk")
        .first()
    )
    extra = (cfg.extra or {}) if cfg else {}
    configured = bool((extra.get("web_view_url") or "").strip())
    url = (extra.get("web_view_url") or "").strip() or QUARK_DEFAULT_WEB_VIEW
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400,
                            detail="web_view_url 必须以 http:// 或 https:// 开头")
    return {
        "url": url,
        "configured": configured,
        "defaulted": not configured,
        "mode": "web_view",
        "message": "夸克网盘未开放官方 API，当前为配置化 Web 视图嵌入模式",
    }


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
    from services.kb_service import detect_doc_meta, has_searchable_chunks, ingest_text
    from services.document_parser import DocumentParser

    if not file.fs_id:
        return {"file_name": file.file_name, "success": False, "message": "缺少网盘 ID，无法下载"}

    save_name = file.file_name or f"netdisk_{file.fs_id}"
    save_name = re.sub(r'[\\/:*?"<>|]', '_', save_name)

    # 已入库则跳过，避免重复。**只按 file_path 认，绝不按 file_name 认**：
    # ① #27 的入库改名会把 file_name 改成「第 1 章 逻辑代数基础」这类正文标题，
    #    按名字认会让同一个网盘文件再下载一遍、长出重复分块；
    # ② 反过来按名字认还会误伤 —— 库里任何一份同名但来源不同的文档都会被
    #    当成「已入库」跳过，并把它的 id 报给前端。下载落盘路径唯一，路径才是身份。
    save_path = os.path.join(UPLOAD_DIR, save_name)
    existing = db.query(Document).filter(Document.file_path == save_path).first()
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

    # 质量闸门：网盘下载来的文件最常见的坏法是"扫描版 PDF 解析出空正文"，
    # 以前直接写成占位提示并标 indexed，检索命中它就等于假答案。
    # 拒绝时这篇 Document 只留 failed 状态，正文和分块都不写。
    verdict = gate_for_write(db, content_text, path=save_path, doc_id=doc.id)
    if not verdict["ok"]:
        doc.index_status = "failed"
        doc.parse_progress = 1.0
        db.commit()
        return {"file_name": save_name, "success": False,
                "message": "质量闸门拒绝入库：" + "；".join(verdict["reasons"])}

    doc.content = content_text
    doc.parse_progress = 0.6
    apply_display_name(db, doc, content_text)
    db.commit()

    chunk_count = 0
    try:
        chunk_count = ingest_text(db, doc.id, doc.file_name, content_text, replace=True)
    except Exception as e:
        print(f"[kb] 网盘文件 {save_name} 入库分块失败: {e}")

    # 打上资料层级 / 扫描件标记（网盘导入的资料同样需要一个口径）
    meta = {}
    try:
        meta = detect_doc_meta(db, doc)
    except Exception as e:
        print(f"[kb] 网盘文件 {save_name} 元信息判定失败: {e}")

    # indexed 的口径 = 库里真有可检索的分块（本轮 0 块但旧块还在，仍算已入库）
    doc.index_status = "indexed" if has_searchable_chunks(db, doc.id) else "failed"
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
    "quark": "quark_netdisk",
    "shengcai": "shengcai",
    "anki": "anki",
    "momo": "momo",
    "bilibili": "bilibili",
    "xmind": "xmind",
}

#: 夸克网盘 Web 视图默认嵌入地址（平台配置 quark_netdisk.extra.web_view_url 可覆盖）。
#: 夸克**没有对外开放的文件 API**（无 OAuth、无文件列表/下载接口），
#: 因此采用「配置化 Web 视图嵌入」方案，详见 GET /quark/web-view 的说明。
QUARK_DEFAULT_WEB_VIEW = "https://pan.quark.cn/"


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

    # ---- 夸克网盘（Web 视图嵌入，无官方 API） ---- #
    elif platform == "quark":
        # 夸克没有官方开放 API，"连接测试"只校验嵌入地址是否合法可填。
        url = (extra.get("web_view_url") or "").strip() or QUARK_DEFAULT_WEB_VIEW
        if not url.lower().startswith(("http://", "https://")):
            return {"connected": False,
                    "message": "Web 视图地址必须以 http:// 或 https:// 开头"}
        return {
            "connected": True,
            "mode": "web_view",
            "message": "夸克网盘为 Web 视图嵌入模式（无官方 API），嵌入地址已配置",
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
