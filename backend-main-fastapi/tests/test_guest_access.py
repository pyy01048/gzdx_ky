# -*- coding: utf-8 -*-
"""访客只读白名单回归（2026-10-19 访客模式，2026-10-21 收口）。

utils/access_policy.enforce_access 的约定：
1. 共享参考数据（/api/kaoyan /api/taxonomy /api/textbooks /api/papers）
   对未登录 GET/HEAD 开放 —— 访客能浏览院校库/通知/知识树/真题索引；
2. 个人数据（任务/单词/卡片…）与一切写操作仍然默认拒绝（401）；
3. 管理工具前缀（crawl-targets/collection/spider）不给访客；
4. /api/quiz、/api/notices、/api/papers/attempts 不在白名单内 —— 内部
   全是按登录用户读写，声明开放只会得到一批「白名单 401」的死配置；
   精确路径例外只有 /api/quiz/papers-index 与 /api/quiz/years（纯元数据）。

本模块临时弹出 conftest 的鉴权旁路，让真实策略跑；结束恢复，不影响其他模块。
"""
from __future__ import annotations

import pytest

from tests.asgi_client import ASGIClient
from main import app
from utils.access_policy import enforce_access
from utils.security import current_user

client = ASGIClient(app)


@pytest.fixture(scope="module", autouse=True)
def _real_auth():
    saved = {}
    for dep in (enforce_access, current_user):
        saved[dep] = app.dependency_overrides.pop(dep, None)
    yield
    for dep, val in saved.items():
        if val is not None:
            app.dependency_overrides[dep] = val


def test_guest_can_read_shared_data():
    assert client.get("/api/kaoyan/analysis/hot").status_code == 200
    assert client.get("/api/taxonomy/subjects").status_code == 200
    assert client.get("/api/textbooks").status_code == 200
    assert client.get("/api/papers").status_code == 200


def test_guest_personal_data_rejected():
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/words").status_code == 401
    assert client.get("/api/favorites").status_code == 401


def test_guest_writes_rejected():
    # 访客只读：任何写方法都不在白名单内
    assert client.post("/api/tasks", json={"title": "访客写入应被拒"}).status_code == 401


def test_guest_admin_tool_reads_rejected():
    # 采集源配置属管理工具读取，不给访客（GUEST_READ_DENY_PREFIXES）
    assert client.get("/api/kaoyan/crawl-targets").status_code == 401


def test_guest_personal_quiz_and_notice_state_rejected():
    # 以前它们在 GUEST_READ_PREFIXES 里，但路由内部全要登录 —— 白名单与实现矛盾。
    assert client.get("/api/quiz/questions").status_code == 401
    assert client.get("/api/quiz/subjects").status_code == 401
    assert client.get("/api/notices/list").status_code == 401


def test_guest_can_read_exam_metadata():
    # /exam 真题索引页的纯元数据：不依赖 current_user，也不含个人作答/错题状态
    assert client.get("/api/quiz/papers-index", params={"source_kind": "exam"}).status_code == 200
    assert client.get("/api/quiz/years", params={"source_kind": "exam"}).status_code == 200


def test_guest_paper_attempts_rejected():
    # 卷索引可公开；作答历史/报告是个人数据
    assert client.get("/api/papers/attempts/history").status_code == 401
    assert client.get("/api/papers/attempts/1/report").status_code == 401
