"""百度网盘 API 对接服务（xpan 开放平台）。

### 本模块修掉的实际缺陷

| 问题 | 后果 |
|------|------|
| access_token 不记过期时间 | 30 天后必失效且无从判断，网盘功能整体挂掉 |
| 有 refresh_token 但**从不使用** | 每次过期都要重新走一遍人工 OAuth |
| 下载 dlink 不带 `User-Agent: pan.baidu.com` | 百度**强制要求**该 UA，否则 403 |
| 下载把整个文件读进内存 | 大课件/视频直接吃光内存 |
| 不检查百度错误码 | 失败被当成成功，前端只看到空列表 |
| `ingest_netdisk_file_to_kb` 查 `Document.source`（该列不存在） | 调用即崩 |

### 官方接口约定（要点）

- 授权：`https://openapi.baidu.com/oauth/2.0/authorize`
- 换 token：`POST https://openapi.baidu.com/oauth/2.0/token`
- 文件列表：`GET https://pan.baidu.com/rest/2.0/xpan/file?method=list`
- 文件信息：`GET https://pan.baidu.com/rest/2.0/xpan/multimedia?method=filemetas&dlink=1`
- 搜索：`GET https://pan.baidu.com/rest/2.0/xpan/file?method=search`
- **dlink 下载必须带 `User-Agent: pan.baidu.com`**
- 错误返回形如 `{"errno": -6, "errmsg": "..."}`（errno=0 才是成功）

参考：https://pan.baidu.com/union/doc/
"""

import datetime
import os
import re
from typing import Any, Dict, Iterator, Optional

import httpx
from sqlalchemy.orm import Session

from models import PlatformConfig
from utils.timeutil import utcnow, to_naive_utc  # 统一 naive UTC 时间规范（P0-4）

# 从 .env 加载网盘凭证（避免密钥硬编码）
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass


class NetdiskError(RuntimeError):
    """百度网盘 API 返回的业务错误（errno != 0）。"""

    def __init__(self, errno: int, errmsg: str, *, request_id: str = ""):
        self.errno = errno
        self.errmsg = errmsg
        self.request_id = request_id
        super().__init__(f"百度网盘错误 {errno}: {errmsg}")


class NetdiskAuthError(NetdiskError):
    """未授权 / token 失效，需要用户重新 OAuth。"""


# 常见 errno → 人话（便于前端直接展示）
ERRNO_HINT = {
    -6: "身份验证失败（access_token 无效或过期），请重新授权",
    2: "参数错误",
    -7: "文件或目录不存在",
    -8: "文件已存在",
    -9: "文件不存在",
    -10: "目录不存在",
    -62: "文件被占用",
    31034: "需要授权的权限范围不足（scope 缺少 netdisk）",
    31064: "文件不存在或已被删除",
    31066: "该文件不允许此操作",
}


def _generate_device_id() -> str:
    """生成百度要求的 device_id（32 位十六进制）。"""
    return os.urandom(16).hex()


def _looks_valid_device_id(value: str) -> bool:
    return bool(value and re.fullmatch(r"[0-9a-fA-F]{32}", value or ""))


class NetdiskService:
    """百度网盘 API 对接。"""

    DEFAULT_APP_KEY = os.getenv("BAIDU_NETDISK_APP_KEY", "")
    DEFAULT_SECRET_KEY = os.getenv("BAIDU_NETDISK_SECRET_KEY", "")
    DEFAULT_APP_ID = os.getenv("BAIDU_NETDISK_APP_ID", "")

    AUTH_BASE = "https://openapi.baidu.com"
    PAN_BASE = "https://pan.baidu.com"

    #: dlink 下载**必须**带这个 UA，否则百度直接 403
    PAN_USER_AGENT = "pan.baidu.com"

    #: 提前多久刷新 token（秒）
    REFRESH_MARGIN = 3600

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ #
    # 配置读写
    # ------------------------------------------------------------------ #
    def _config_row(self) -> Optional[PlatformConfig]:
        return (
            self.db.query(PlatformConfig)
            .filter(PlatformConfig.platform_name == "baidu_netdisk")
            .first()
        )

    def _get_config(self) -> Dict[str, Any]:
        """从数据库读取网盘配置，缺失项回退到 .env。"""
        extra: Dict[str, Any] = {}
        row = self._config_row()
        if row:
            extra = dict(row.extra or {})
        return {
            "app_key": (row.app_key if row and row.app_key else self.DEFAULT_APP_KEY),
            "secret_key": (row.secret_key if row and row.secret_key else self.DEFAULT_SECRET_KEY),
            "app_id": extra.get("app_id") or self.DEFAULT_APP_ID,
            "access_token": (row.token if row else "") or "",
            "refresh_token": extra.get("refresh_token", "") or "",
            "expires_at": extra.get("expires_at"),          # ISO 字符串
            "device_id": extra.get("device_id", "") or "",
            "scope": extra.get("scope", "basic,netdisk"),
        }

    def _save_config(self, **fields) -> None:
        """写回配置（token / refresh_token / expires_at / device_id ...）。"""
        row = self._config_row()
        if not row:
            row = PlatformConfig(
                platform_name="baidu_netdisk",
                app_key=self.DEFAULT_APP_KEY,
                secret_key=self.DEFAULT_SECRET_KEY,
            )
            self.db.add(row)
        extra = dict(row.extra or {})
        for key in ("refresh_token", "expires_at", "device_id", "scope", "app_id", "uid"):
            if key in fields and fields[key] is not None:
                extra[key] = fields[key]
        if "access_token" in fields:
            row.token = fields["access_token"]
        row.extra = extra
        self.db.commit()

    def _save_token(self, data: Dict[str, Any]) -> None:
        """保存 OAuth 返回的 token，并**记录过期时间**。"""
        expires_in = int(data.get("expires_in") or 2592000)   # 百度默认 30 天
        # naive UTC：写入配置的是 ISO 字符串，比较侧也用 naive，保持同语义
        expires_at = (utcnow() + datetime.timedelta(seconds=expires_in)).isoformat()
        self._save_config(
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scope=data.get("scope"),
        )

    # ------------------------------------------------------------------ #
    # OAuth 授权
    # ------------------------------------------------------------------ #
    def get_auth_url(self, redirect_uri: str = "oob") -> str:
        """生成 OAuth 授权 URL。

        device_id 百度要求 32 位十六进制，缺失时自动生成并持久化 ——
        否则每次授权都是"新设备"，历史授权记录会乱。
        """
        cfg = self._get_config()
        device_id = cfg["device_id"]
        if not _looks_valid_device_id(device_id):
            device_id = _generate_device_id()
            self._save_config(device_id=device_id)

        params = {
            "client_id": cfg["app_key"],
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": cfg["scope"] or "basic,netdisk",
            "device_id": device_id,
        }
        import urllib.parse
        return f"{self.AUTH_BASE}/oauth/2.0/authorize?{urllib.parse.urlencode(params)}"

    async def handle_callback(self, code: str, redirect_uri: str = "oob") -> Dict[str, Any]:
        """用授权码换取 access_token。"""
        cfg = self._get_config()
        url = f"{self.AUTH_BASE}/oauth/2.0/token"
        params = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": cfg["app_key"],
            "client_secret": cfg["secret_key"],
            "redirect_uri": redirect_uri,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, params=params)
            data = self._parse_json(resp)

        access_token = data.get("access_token", "")
        if not access_token:
            # 百度把授权失败也放 errno/error 字段里
            raise NetdiskAuthError(
                int(data.get("errno") or -1),
                data.get("error_description") or data.get("error") or "换取 access_token 失败",
            )

        self._save_token(data)
        return {
            "success": True,
            "access_token": access_token,
            "expires_in": data.get("expires_in"),
            "scope": data.get("scope"),
            "has_refresh_token": bool(data.get("refresh_token")),
        }

    async def refresh_access_token(self) -> Dict[str, Any]:
        """用 refresh_token 换新 token。

        这是长跑场景的关键：不实现的话 30 天后整个网盘模块静默失效。
        """
        cfg = self._get_config()
        if not cfg["refresh_token"]:
            raise NetdiskAuthError(-6, "没有 refresh_token，请重新授权")

        url = f"{self.AUTH_BASE}/oauth/2.0/token"
        params = {
            "grant_type": "refresh_token",
            "refresh_token": cfg["refresh_token"],
            "client_id": cfg["app_key"],
            "client_secret": cfg["secret_key"],
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, params=params)
            data = self._parse_json(resp)

        if not data.get("access_token"):
            raise NetdiskAuthError(
                int(data.get("errno") or -6),
                data.get("error_description") or "refresh_token 已失效，请重新授权",
            )
        # 刷新响应可能不带新 refresh_token，保留旧的
        if not data.get("refresh_token"):
            data["refresh_token"] = cfg["refresh_token"]
        self._save_token(data)
        return {"success": True, "expires_in": data.get("expires_in")}

    def token_status(self) -> Dict[str, Any]:
        """token 状态（给前端显示"还剩多久过期"）。"""
        cfg = self._get_config()
        expires_at = cfg.get("expires_at")
        remaining = None
        expired = None
        if expires_at:
            try:
                dt = to_naive_utc(datetime.datetime.fromisoformat(expires_at))
                remaining = int((dt - utcnow()).total_seconds())
                expired = remaining <= 0
            except (ValueError, TypeError):
                pass
        return {
            "authorized": bool(cfg["access_token"]),
            "has_refresh_token": bool(cfg["refresh_token"]),
            "expires_at": expires_at,
            "expires_in_seconds": remaining,
            "expired": expired,
            "device_id": cfg.get("device_id") or None,
        }

    async def _ensure_token(self) -> str:
        """确保有可用 token：无 token 报错，将过期则自动刷新。"""
        cfg = self._get_config()
        token = cfg["access_token"]
        if not token:
            raise NetdiskAuthError(-6, "百度网盘未授权，请先完成 OAuth 授权")

        expires_at = cfg.get("expires_at")
        if expires_at:
            try:
                dt = to_naive_utc(datetime.datetime.fromisoformat(expires_at))
                remaining = (dt - utcnow()).total_seconds()
            except (ValueError, TypeError):
                remaining = None
            if remaining is not None and remaining <= self.REFRESH_MARGIN:
                if cfg["refresh_token"]:
                    try:
                        await self.refresh_access_token()
                        token = self._get_config()["access_token"]
                    except NetdiskError:
                        if remaining <= 0:
                            raise
                elif remaining <= 0:
                    raise NetdiskAuthError(-6, "access_token 已过期且无 refresh_token，请重新授权")
        return token

    # ------------------------------------------------------------------ #
    # 响应解析
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_json(resp: httpx.Response) -> Dict[str, Any]:
        try:
            data = resp.json()
        except Exception:
            raise NetdiskError(-1, f"响应不是合法 JSON（HTTP {resp.status_code}）")
        if not isinstance(data, dict):
            raise NetdiskError(-1, "响应格式异常")
        return data

    @staticmethod
    def _check_errno(data: Dict[str, Any]) -> Dict[str, Any]:
        """百度用 errno=0 表示成功，非 0 一律抛错（含人话提示）。"""
        errno = data.get("errno")
        if errno in (None, 0):
            return data
        errno = int(errno)
        msg = data.get("errmsg") or ERRNO_HINT.get(errno, "未知错误")
        hint = ERRNO_HINT.get(errno)
        full = f"{msg}（{hint}）" if hint and hint not in msg else msg
        if errno in (-6, 31034):
            raise NetdiskAuthError(errno, full, request_id=str(data.get("request_id", "")))
        raise NetdiskError(errno, full, request_id=str(data.get("request_id", "")))

    # ------------------------------------------------------------------ #
    # 文件操作
    # ------------------------------------------------------------------ #
    async def get_file_list(
        self, path: str = "/", page: int = 1, num: int = 100
    ) -> Dict[str, Any]:
        """获取目录下的文件列表（单层）。"""
        token = await self._ensure_token()
        url = f"{self.PAN_BASE}/rest/2.0/xpan/file"
        params = {
            "method": "list",
            "access_token": token,
            "dir": path,
            "order": "name",
            "start": (page - 1) * num,
            "limit": num,
            "web": 1,
        }
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": self.PAN_USER_AGENT}) as client:
            resp = await client.get(url, params=params)
            return self._check_errno(self._parse_json(resp))

    async def list_all(
        self,
        path: str = "/",
        *,
        max_items: int = 2000,
        max_depth: int = 4,
        deadline: float = 45.0,
        _depth: int = 0,
        _start: float | None = None,
    ) -> Dict[str, Any]:
        """递归列出目录下所有文件。

        考研资料通常按「科目/章节」多层建目录，只列一层找不到东西。

        ⚠️ 实测教训：账号里有 **1.3TB 资料**时，全量递归会跑几十分钟，
        直接把 HTTP 请求拖超时。所以这里有三道闸：

        - `max_depth`：默认只下钻 4 层（够覆盖「科目/章节/年份/文件」）
        - `max_items`：条数上限
        - `deadline`：总耗时上限（秒），到点就返回已收集的部分并标记 `truncated`

        宁可返回"部分结果 + 已截断"标记，也不要让调用方一直等。
        """
        import time

        started = _start if _start is not None else time.time()
        if _depth > max_depth:
            return {"list": [], "truncated": True, "reason": f"超过最大深度 {max_depth}"}
        if time.time() - started > deadline:
            return {"list": [], "truncated": True, "reason": f"超过耗时上限 {deadline}s"}

        out: list[dict] = []
        truncated = False
        reason = ""
        start = 0

        while True:
            if time.time() - started > deadline:
                truncated, reason = True, f"超过耗时上限 {deadline}s"
                break
            token = await self._ensure_token()
            url = f"{self.PAN_BASE}/rest/2.0/xpan/file"
            params = {
                "method": "list", "access_token": token, "dir": path,
                "order": "name", "start": start, "limit": 200, "web": 1,
            }
            async with httpx.AsyncClient(
                timeout=20.0, headers={"User-Agent": self.PAN_USER_AGENT}
            ) as client:
                resp = await client.get(url, params=params)
                data = self._check_errno(self._parse_json(resp))

            items = data.get("list") or []
            if not items:
                break

            for it in items:
                if len(out) >= max_items:
                    truncated, reason = True, f"超过条数上限 {max_items}"
                    break
                if it.get("isdir"):
                    sub = await self.list_all(
                        it.get("path", ""),
                        max_items=max_items - len(out),
                        max_depth=max_depth,
                        deadline=deadline,
                        _depth=_depth + 1,
                        _start=started,
                    )
                    out.extend(sub.get("list", []))
                    if sub.get("truncated"):
                        truncated = True
                        reason = reason or sub.get("reason", "")
                else:
                    out.append(it)

            if truncated or len(items) < 200:
                break
            start += len(items)

        result: Dict[str, Any] = {"list": out, "truncated": truncated}
        if reason:
            result["reason"] = reason
        if truncated:
            result["hint"] = (
                "资料太多未能一次列完。建议改用「关键词搜索」精确找文件，"
                "或指定更具体的子目录。"
            )
        return result

    async def search_files(self, keyword: str, *, dir_path: str = "/", page: int = 1) -> Dict[str, Any]:
        """按关键词搜索文件（找资料比一层层翻目录快得多）。"""
        token = await self._ensure_token()
        url = f"{self.PAN_BASE}/rest/2.0/xpan/file"
        params = {
            "method": "search",
            "access_token": token,
            "key": keyword,
            "dir": dir_path,
            "page": page,
            "num": 100,
            "recursion": 1,
            "web": 1,
        }
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": self.PAN_USER_AGENT}) as client:
            resp = await client.get(url, params=params)
            return self._check_errno(self._parse_json(resp))

    async def get_file_info(self, fs_id: str) -> Dict[str, Any]:
        """获取文件详情（含 dlink）。"""
        token = await self._ensure_token()
        url = f"{self.PAN_BASE}/rest/2.0/xpan/multimedia"
        params = {
            "method": "filemetas",
            "access_token": token,
            "fsids": f"[{fs_id}]",
            "dlink": 1,
        }
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": self.PAN_USER_AGENT}) as client:
            resp = await client.get(url, params=params)
            data = self._check_errno(self._parse_json(resp))
        items = data.get("list") or []
        return items[0] if items else {}

    async def get_download_url(self, fs_id: str) -> Dict[str, Any]:
        """拿到可直接下载的 URL（已拼 access_token）。"""
        token = await self._ensure_token()
        info = await self.get_file_info(fs_id)
        dlink = info.get("dlink", "")
        if not dlink:
            raise NetdiskError(-9, "该文件没有下载链接（可能是目录或已被删除）")
        sep = "&" if "?" in dlink else "?"
        return {
            "download_url": f"{dlink}{sep}access_token={token}",
            "filename": info.get("filename", ""),
            "size": info.get("size", 0),
            "md5": info.get("md5", ""),
        }

    # 兼容旧调用名
    async def download_file(self, fs_id: str) -> Dict[str, Any]:
        return await self.get_download_url(fs_id)

    async def iter_download(self, fs_id: str, *, chunk_size: int = 1 << 20) -> Iterator[bytes]:
        """流式下载（大文件不爆内存）。

        关键点：必须带 `User-Agent: pan.baidu.com`，否则百度返回 403。
        """
        dl = await self.get_download_url(fs_id)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=300.0),
            follow_redirects=True,
            headers={"User-Agent": self.PAN_USER_AGENT},
        ) as client:
            async with client.stream("GET", dl["download_url"]) as resp:
                if resp.status_code == 403:
                    raise NetdiskError(403, "下载被拒绝（403）：请确认请求带 User-Agent: pan.baidu.com")
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size):
                    if chunk:
                        yield chunk

    async def download_to_file(self, fs_id: str, dest_path: str, *, max_bytes: int = 0) -> Dict[str, Any]:
        """流式下载到指定路径。

        :param max_bytes: 上限（字节），0 表示不限制；超限抛错并清理半成品
        """
        tmp_path = dest_path + ".part"
        written = 0
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".", exist_ok=True)
        try:
            with open(tmp_path, "wb") as fh:
                async for chunk in self.iter_download(fs_id):
                    written += len(chunk)
                    if max_bytes and written > max_bytes:
                        raise NetdiskError(
                            -1,
                            f"文件超过大小上限（已下载 {written / 1048576:.1f}MB > "
                            f"{max_bytes / 1048576:.1f}MB）",
                        )
                    fh.write(chunk)
            os.replace(tmp_path, dest_path)
        except Exception:
            for p in (tmp_path, dest_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass
            raise
        return {"path": dest_path, "size": written}

    async def get_preview_link(self, fs_id: str) -> Dict[str, Any]:
        """获取视频转码播放链接。"""
        token = await self._ensure_token()
        url = f"{self.PAN_BASE}/rest/2.0/xpan/multimedia"
        params = {
            "method": "streaming",
            "access_token": token,
            "path": fs_id,
            "type": "M3U8_AUTO_480",
        }
        import urllib.parse
        return {"preview_url": f"{url}?{urllib.parse.urlencode(params)}"}

    # ------------------------------------------------------------------ #
    # 自动分类
    # ------------------------------------------------------------------ #
    #: 考研资料分类（按文件名关键词，比扩展名分类有用得多）
    SUBJECT_KEYWORDS = {
        "数字电子技术": ["数电", "数字电子", "数字电路", "逻辑代数", "卡诺图", "触发器", "时序逻辑"],
        "模拟电子技术": ["模电", "模拟电子", "模拟电路", "放大电路", "运放", "三极管", "场效应"],
        "数学": ["数学", "高数", "线代", "线性代数", "概率", "张宇", "660", "1000题", "数二"],
        "英语": ["英语", "单词", "词汇", "长难句", "阅读", "作文", "完形", "翻译", "恋恋有词"],
        "政治": ["政治", "马原", "毛中特", "史纲", "肖秀荣", "腿姐", "徐涛"],
        "真题": ["真题", "834", "历年", "考试卷", "试题"],
        "讲义": ["讲义", "课件", "ppt", "笔记", "辅导"],
        "视频": ["视频", "网课", "课程", "讲解"],
    }

    EXT_CATEGORY = {
        ".mp4": "视频", ".avi": "视频", ".mkv": "视频", ".mov": "视频", ".flv": "视频",
        ".pdf": "PDF资料", ".doc": "文档", ".docx": "文档", ".txt": "文档", ".md": "文档",
        ".ppt": "课件", ".pptx": "课件",
        ".mp3": "音频", ".wav": "音频", ".flac": "音频",
        ".zip": "压缩包", ".rar": "压缩包", ".7z": "压缩包",
    }

    def auto_classify(self, filename: str) -> str:
        """按文件名分类：优先学科（对考研更有用），否则按扩展名。"""
        name = filename or ""
        for subject, kws in self.SUBJECT_KEYWORDS.items():
            if any(kw.lower() in name.lower() for kw in kws):
                return subject
        low = name.lower()
        for ext, cat in self.EXT_CATEGORY.items():
            if low.endswith(ext):
                return cat
        return "其他"

    # ------------------------------------------------------------------ #
    # 连通性自检
    # ------------------------------------------------------------------ #
    async def test_connection(self) -> Dict[str, Any]:
        """检测凭证与授权状态（前端"测试连接"按钮用）。"""
        cfg = self._get_config()
        result: Dict[str, Any] = {
            "has_app_key": bool(cfg["app_key"]),
            "has_secret_key": bool(cfg["secret_key"]),
            "authorized": bool(cfg["access_token"]),
            "has_refresh_token": bool(cfg["refresh_token"]),
            "ok": False,
        }
        if not cfg["app_key"] or not cfg["secret_key"]:
            result["message"] = "缺少 AppKey / SecretKey，请在 backend-main-fastapi/.env 配置 BAIDU_NETDISK_APP_KEY / SECRET_KEY"
            return result
        if not cfg["access_token"]:
            result["message"] = "凭证已配置，但尚未授权。请点击「授权」完成 OAuth。"
            result["auth_url"] = self.get_auth_url()
            return result
        try:
            data = await self.get_file_list("/", 1, 1)
            result["ok"] = True
            result["message"] = "连接正常，授权有效"
            result["root_item_count"] = len(data.get("list") or [])
            # 顺带汇报配额（接口不总是可用，失败不影响结论）
            try:
                quota = await self.get_quota()
                result["quota"] = quota
            except Exception:
                pass
        except NetdiskAuthError as e:
            result["message"] = f"授权失效：{e.errmsg}"
            result["auth_url"] = self.get_auth_url()
        except NetdiskError as e:
            result["message"] = f"接口报错：{e.errmsg}"
        except Exception as e:
            result["message"] = f"连接失败：{type(e).__name__}: {e}"
        return result

    async def get_quota(self) -> Dict[str, Any]:
        """获取网盘容量。"""
        token = await self._ensure_token()
        url = f"{self.PAN_BASE}/api/quota"
        params = {"access_token": token, "checkfree": 1, "checkexpire": 1}
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": self.PAN_USER_AGENT}) as client:
            resp = await client.get(url, params=params)
            data = self._check_errno(self._parse_json(resp))
        total = data.get("total") or 0
        used = data.get("used") or 0
        return {
            "total": total,
            "used": used,
            "free": max(0, total - used),
            "used_ratio": round(used / total, 4) if total else 0,
            "total_gb": round(total / 1024 ** 3, 2),
            "used_gb": round(used / 1024 ** 3, 2),
        }
