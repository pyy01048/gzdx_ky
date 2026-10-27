# -*- coding: utf-8 -*-
"""uvicorn 看门狗单测（P0-3 回归护栏）。

背景：`OSError [WinError 64] Accept failed on a socket` 之后进程仍存活但不再
监听，监控只看"进程在不在"会误判健康。看门狗的职责是把这种**半死状态**拉回来：
端口失联/健康连续失败 → 置位 `Server.should_exit` → 干净退出 → 守护重启。

这里不真的起 uvicorn（太贵），而是用假 Server 对象验证决策逻辑，
外加对真实 TCP/HTTP 探针的行为验证。
"""
from __future__ import annotations

import os
import socket
import sys
import threading
from wsgiref.simple_server import WSGIRequestHandler, make_server

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.server_watchdog import (  # noqa: E402
    EXIT_WATCHDOG,
    ServerWatchdog,
    probe_health,
    probe_tcp,
)


class _FakeServer:
    """只模拟 uvicorn.Server 被看门狗用到的那一个属性。"""

    should_exit = False


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_watchdog(server, host, port, **kw) -> ServerWatchdog:
    """起一个宽限期/周期都压到毫秒级的看门狗，同步等它 fire 一次。"""
    wd = ServerWatchdog(
        server, host, port,
        grace_s=kw.pop("grace_s", 0.0),
        interval_s=kw.pop("interval_s", 0.02),
        tcp_fail_limit=kw.pop("tcp_fail_limit", 2),
        health_fail_limit=kw.pop("health_fail_limit", 2),
        health_timeout_s=kw.pop("health_timeout_s", 0.5),
        **kw,
    )
    wd.start()
    return wd


def _wait_fired(wd: ServerWatchdog, timeout: float = 10.0) -> bool:
    """等到触发或超时（探活周期已压到 20ms，留足余量只为吸收 Windows 计时抖动）。"""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if wd.triggered:
            return True
        time.sleep(0.02)
    return wd.triggered


def test_probe_tcp_closed_port_is_down() -> None:
    assert probe_tcp("127.0.0.1", _free_port(), timeout=0.3) is False


def test_probe_tcp_live_port_is_up() -> None:
    port = _free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        assert probe_tcp("127.0.0.1", port, timeout=0.3) is True


def test_probe_tcp_rewrites_wildcard_host() -> None:
    """watchdog 在 HOST=0.0.0.0 下探活必须走 127.0.0.1（Windows 连不通 0.0.0.0）。"""
    port = _free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        assert probe_tcp("0.0.0.0", port, timeout=0.3) is True


def test_probe_health_down_on_closed_port() -> None:
    assert probe_health("127.0.0.1", _free_port(), timeout=0.3) is False


def test_watchdog_fires_when_port_is_gone() -> None:
    """端口失联（accept 循环已死的等价场景）→ 连续失败达阈值 → 置位 should_exit。"""
    server = _FakeServer()
    wd = _run_watchdog(server, "127.0.0.1", _free_port())
    try:
        assert _wait_fired(wd), "端口失联未触发看门狗"
        assert server.should_exit is True
        assert "连接失败" in wd.reason
    finally:
        wd.stop()
        wd.join(timeout=3)


def test_watchdog_quiet_when_healthy() -> None:
    """端口与健康都正常 → 不该误触发（避免把健康服务重启掉）。"""
    server = _FakeServer()

    def app(environ, start_response):
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b'{"status":"ok"}']

    port = _free_port()
    httpd = make_server("127.0.0.1", port, app, handler_class=WSGIRequestHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        assert probe_health("127.0.0.1", port, timeout=1.0) is True
        wd = _run_watchdog(server, "127.0.0.1", port, grace_s=0.0)
        threading.Event().wait(0.3)  # 覆盖若干轮探活
        assert wd.triggered is False, f"健康服务被误判: {wd.reason}"
        assert server.should_exit is False
        wd.stop()
        wd.join(timeout=3)
    finally:
        httpd.shutdown()


def test_grace_period_suppresses_probing() -> None:
    """宽限期内（启动建表/OCR 预热）完全不探活 —— 否则启动期必被误杀。"""
    server = _FakeServer()
    wd = _run_watchdog(server, "127.0.0.1", _free_port(), grace_s=5.0)
    try:
        threading.Event().wait(0.2)
        assert wd.triggered is False
        assert server.should_exit is False
    finally:
        wd.stop()
        wd.join(timeout=3)


def test_exit_code_constant_is_distinctive() -> None:
    """守护靠退出码区分「人为停止(0)」与「看门狗自愈(42)」。"""
    assert EXIT_WATCHDOG == 42
    assert EXIT_WATCHDOG != 0
