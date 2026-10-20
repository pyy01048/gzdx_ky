"""全局默认拒绝的访问策略（doc 11 F11-04/05）。

挂在 ``FastAPI(dependencies=[...])`` 上，所以**新加的路由默认也要登录**——
不靠每个 router 自己记得加 ``Depends``。管理端接口按路径分类集中在这里，
改分类只改这一张表。
"""
from __future__ import annotations

import os
import re
from typing import Iterable, Tuple

from fastapi import Depends, Request, status
from sqlalchemy.orm import Session

from database import get_db
from utils.exceptions import BusinessException, ErrorCode
from utils.security import ROLE_ADMIN, current_user

PUBLIC_PATHS = frozenset({
    "/api/health",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/logout",
})

# 访客（未登录）可读的共享数据前缀：只放行 GET/HEAD，写操作仍然一律要求登录。
# 选择口径：纯「公共参考数据」（院校/通知/教材/知识树/真题卷索引），
# 不含任何个人学习记录（任务/单词/卡片/错题/收藏/计划全部仍需登录）。
# 注意：不得与 ADMIN_PREFIXES 重叠 —— 管理端读接口不给访客。
GUEST_READ_PREFIXES: Tuple[str, ...] = (
    "/api/kaoyan",      # 院校库/通知/分数线/散点图等共享择校数据
    "/api/taxonomy",    # 科目与知识点树（知识图谱只读）
    "/api/textbooks",   # 教材目录
    "/api/papers",      # 真题卷索引（作答/保存仍需登录）
    "/api/notices",     # 考研通知（共享数据；未读/星标等个人状态需登录才有意义）
    "/api/quiz",        # 题库/真题元数据与题目只读（提交作答仍需登录）
)

# 访客白名单内的例外：管理工具性质的读取也不给访客
GUEST_READ_DENY_PREFIXES: Tuple[str, ...] = (
    "/api/kaoyan/crawl-targets",
    "/api/kaoyan/collection",
    "/api/kaoyan/spider",
)


def is_guest_readable(method: str, path: str) -> bool:
    """访客只读白名单：GET/HEAD 且命中共享数据前缀、不落在管理工具前缀内。"""
    if method.upper() not in ("GET", "HEAD"):
        return False
    if not any(path == p or path.startswith(p + "/") for p in GUEST_READ_PREFIXES):
        return False
    return not any(path.startswith(p) for p in GUEST_READ_DENY_PREFIXES)

# 任何方法都只给管理员
ADMIN_PREFIXES: Tuple[str, ...] = (
    "/api/admin/",
    "/api/backup",
    "/api/storage",
    "/api/quality",
    "/api/model-training",
    "/api/kb-import",
    "/api/imports",
    "/api/kb/",
    "/api/performance",
    "/api/netdisk/platform-config",
)

# 共享数据：登录可读，写需管理员
ADMIN_WRITE_PREFIXES: Tuple[str, ...] = (
    "/api/taxonomy",
    "/api/textbooks",
    "/api/documents",
    "/api/codebank",
    "/api/conflicts",
    "/api/links",
    "/api/settings",
    "/api/ai/providers",
)

# 其余模块里零散的维护类写接口（方法, 路径模板）
ADMIN_ENDPOINTS: Tuple[Tuple[str, str], ...] = (
    ("PUT", "/api/ai/routing"),
    ("POST", "/api/ai/rebuild-fts"),
    ("POST", "/api/ai/build-embeddings"),
    ("POST", "/api/ai/local/test"),
    ("POST", "/api/quiz/questions"),
    ("PUT", "/api/quiz/questions/{id}"),
    ("DELETE", "/api/quiz/questions/{id}"),
    ("POST", "/api/quiz/import"),
    ("POST", "/api/quiz/import/markdown"),
    ("POST", "/api/quiz/import/confirm"),
    ("POST", "/api/quiz/extract-knowledge-points"),
    ("POST", "/api/quiz/batch-delete"),
    # 2026-10-18 补漏（docs/plan-gap/B-auth.md §B3）：共享数据的复核/硬删接口，此前普通用户可调
    ("POST", "/api/quiz/review/{question_id}"),
    # 注意：/api/errors/batch-delete **不在此列**。错题是个人域数据，
    # 端点内部已用 scoped(ErrorRecord, user) 限定"仅本人"，普通用户应当可用；
    # 把它收进管理员会直接废掉错题本的批量删除功能。
    ("POST", "/api/papers/save"),
    ("DELETE", "/api/papers/{id}"),
    ("POST", "/api/kaoyan/notices/crawl"),
    ("POST", "/api/kaoyan/spider/run"),
    ("POST", "/api/kaoyan/collection/runs"),
    ("POST", "/api/kaoyan/collection/refresh"),
    ("POST", "/api/kaoyan/reforms/scan"),
    ("POST", "/api/kaoyan/crawl-targets/toggle"),
    ("POST", "/api/kaoyan/crawl-targets/bulk"),
    ("POST", "/api/kaoyan/crawl-targets/reset"),
    ("POST", "/api/notice-alert/classify"),
    ("POST", "/api/notice-alert/backfill"),
    ("POST", "/api/notice-alert/scan"),
    ("POST", "/api/notice-alert/import"),
    ("POST", "/api/notice-alert/import/batch"),
    ("POST", "/api/notices/backfill-important"),
    ("POST", "/api/netdisk/test-connection/{platform}"),
    ("POST", "/api/netdisk/classify"),
    ("POST", "/api/netdisk/ingest"),
    ("POST", "/api/netdisk/files/{id}/ingest"),
    ("POST", "/api/netdisk/ingest-all"),
    # 2026-10-18 补漏（docs/plan-gap/B-auth.md §B3）：网盘为共享凭据，同步/换绑/刷新/解绑属管理操作
    ("POST", "/api/netdisk/sync"),
    ("POST", "/api/netdisk/logout"),
    ("POST", "/api/netdisk/refresh-token"),
    ("POST", "/api/netdisk/callback"),
    ("POST", "/api/qa/import-qbank"),
    ("POST", "/api/qa/refresh-weak"),
    ("POST", "/api/qa/review-queue/{id}/resolve"),
)

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _compile(endpoints: Iterable[Tuple[str, str]]):
    out = []
    for method, template in endpoints:
        pattern = re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template))
        out.append((method, re.compile(f"^{pattern}/?$")))
    return tuple(out)


_ADMIN_ENDPOINT_RES = _compile(ADMIN_ENDPOINTS)


def _prefix_hit(path: str, prefixes: Tuple[str, ...]) -> bool:
    for p in prefixes:
        if p.endswith("/"):
            if path.startswith(p) or path == p[:-1]:
                return True
        elif path == p or path.startswith(p + "/"):
            return True
    return False


def is_public(path: str) -> bool:
    return not path.startswith("/api/") or path.rstrip("/") in PUBLIC_PATHS


def needs_admin(method: str, path: str) -> bool:
    method = method.upper()
    if _prefix_hit(path, ADMIN_PREFIXES):
        return True
    if method in _WRITE_METHODS and _prefix_hit(path, ADMIN_WRITE_PREFIXES):
        return True
    return any(m == method and rx.match(path) for m, rx in _ADMIN_ENDPOINT_RES)


def enforce_access(request: Request, db: Session = Depends(get_db)):
    path = request.url.path
    if is_public(path):
        return None
    # 访客模式（2026-10-19）：共享参考数据对未登录用户只读开放，
    # 其余仍然默认拒绝（未登录 → 401）。管理端读接口不在白名单内。
    if is_guest_readable(request.method, path):
        return None
    user = current_user(request, db)
    if needs_admin(request.method, path) and user.role != ROLE_ADMIN:
        raise BusinessException(
            code=ErrorCode.FORBIDDEN, message="需要管理员权限", status_code=status.HTTP_403_FORBIDDEN
        )
    return user


def is_production() -> bool:
    return (os.getenv("APP_ENV") or "").strip().lower() in {"prod", "production"}
