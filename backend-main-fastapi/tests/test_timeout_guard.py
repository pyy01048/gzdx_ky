# -*- coding: utf-8 -*-
"""V11：timeout_guard 按路径前缀的专用超时映射测试。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.timeout_guard import (  # noqa: E402
    DEFAULT_PATH_TIMEOUTS,
    TimeoutGuardMiddleware,
    timeout_for_method,
)


def test_chat_router_has_300s_override():
    assert DEFAULT_PATH_TIMEOUTS.get("/api/ai/chat/router") == 300.0  # T4 读图链放宽
    assert timeout_for_method("POST", "/api/ai/chat/router") == 300.0


def test_other_post_unchanged_60s():
    assert timeout_for_method("POST", "/api/ai/providers") == 60.0
    assert timeout_for_method("POST", "/api/other") == 60.0


def test_get_default_30s():
    assert timeout_for_method("GET", "/api/anything") == 30.0


def test_env_path_map_override(monkeypatch):
    monkeypatch.setenv("API_TIMEOUT_PATH_MAP", "/api/custom=45")
    g = TimeoutGuardMiddleware(app=None)
    assert g._timeout_for("POST", "/api/custom") == 45.0
    # 未命中的仍走默认
    assert g._timeout_for("POST", "/api/other") == 60.0


def test_path_prefix_match():
    g = TimeoutGuardMiddleware(app=None)
    # 前缀命中
    assert g._timeout_for("POST", "/api/ai/chat/router/extra") == 300.0
