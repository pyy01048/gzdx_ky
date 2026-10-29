"""路由注册中心（架构重构 · V3.1）。

把 53 个 router 按领域收敛为 6 个域，所有挂载点收口到这里。
main.py 只做一件事：``for r in iter_routers(): app.include_router(r)``。

域划分（与 docs/ARCHITECTURE.md 保持一致）：

- auth      : 登录 / JWT / 管理员认证
- study     : 学习主链路（刷题 / 错题 / 复习 / 单词 / 计划 / 统计）
- knowledge : 知识库 / 文档 / RAG / 题库导入
- ai        : AI 对话 / 答疑 / 记忆 / 推荐 / 模型训练
- kaoyan    : 院校 / 资讯 / 院校采集管理
- platform  : 网盘 / 系统设置 / 备份 / 管理后台
"""
from __future__ import annotations

from typing import Iterable, List, Tuple

from fastapi import APIRouter

# --------------------------------------------------------------------------- #
# 每个条目：模块名 -> 该模块暴露的 APIRouter 属性名（个别模块有多个 router）
# --------------------------------------------------------------------------- #
DOMAIN_ROUTERS: dict[str, List[Tuple[str, List[str]]]] = {
    "auth": [
        ("auth", ["router", "admin_router"]),
    ],
    "study": [
        ("dashboard", ["router"]),
        ("tasks", ["router"]),
        ("planner", ["router"]),
        ("plan", ["router"]),
        ("goals", ["router"]),
        ("growth", ["router"]),
        ("review", ["router"]),
        ("flashcards", ["router"]),
        ("words", ["router"]),
        ("errors", ["router"]),
        ("quiz", ["router"]),
        ("papers", ["router"]),
        ("exam", ["router"]),
        ("answers", ["router"]),
        ("codebank", ["router"]),
        ("code_oj", ["router"]),
        ("favorites", ["router"]),
        ("blind_spot", ["router"]),
        ("analytics", ["router"]),
        ("insight", ["router"]),
        ("quality", ["router"]),
        ("stats_export", ["router", "errors_router", "quiz_export_router"]),
        ("qa_tools", ["router"]),
        ("analysis", ["router"]),
    ],
    "knowledge": [
        ("documents", ["router"]),
        ("kb", ["router"]),
        ("kb_import", ["router"]),
        ("taxonomy", ["router"]),
        ("textbooks", ["router"]),
        ("formula", ["router"]),
        ("imports", ["router"]),
        ("storage", ["router"]),
        ("gate", ["router"]),
        ("conflicts", ["router"]),
    ],
    "ai": [
        ("ai", ["router"]),
        ("ai_tutoring", ["router"]),
        ("tutor_orchestrator", ["router"]),
        ("memory", ["router"]),
        ("recommend", ["router"]),
        ("model_training", ["router"]),
    ],
    "kaoyan": [
        ("kaoyan", ["router"]),
        ("kaoyan_ext", ["router"]),
        ("notices", ["router"]),
        ("notice_alert", ["router"]),
        ("admin_schools", ["router"]),
        ("admin_schools_crawler", ["router"]),
    ],
    "platform": [
        ("netdisk", ["router"]),
        ("admin_netdisk", ["router"]),
        ("customization", ["router"]),
        ("watermark_admin", ["router"]),
        ("admin_system", ["router"]),
        ("backup", ["router"]),
    ],
}


def _load(domain: str, module: str, attrs: List[str]) -> List[APIRouter]:
    """导入 ``routers.<domain>.<module>`` 并取出指定 router 属性。"""
    import importlib

    mod = importlib.import_module(f"routers.{domain}.{module}")
    return [getattr(mod, attr) for attr in attrs]


def iter_routers() -> Iterable[APIRouter]:
    """按领域顺序产出全部 APIRouter（main.py 唯一挂载入口）。"""
    for domain, modules in DOMAIN_ROUTERS.items():
        for module, attrs in modules:
            yield from _load(domain, module, attrs)


def domain_summary() -> dict[str, int]:
    """返回 {领域: router 数量}，供启动日志 / 健康检查使用。"""
    return {domain: sum(len(attrs) for _, attrs in modules) for domain, modules in DOMAIN_ROUTERS.items()}