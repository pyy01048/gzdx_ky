# -*- coding: utf-8 -*-
"""uvicorn 看门狗启动封装 + 端口/健康自检（P0-3）。

背景（2026-10-21 实测）：后端日志出现
``OSError [WinError 64] Accept failed on a socket`` 之后，**进程仍存活但不再监听**
—— 监控只看"进程在不在"就会误判健康，整站不可用且永远不自愈。

本模块提供两层自愈：

1. **进程内看门狗**（:func:`run_with_watchdog`）：后台线程周期性探活自己的
   监听端口与 ``/api/health``，连续失败就把 uvicorn ``Server.should_exit``
   置位，让进程**干净退出**（而非僵死），交由上层守护进程重启；前台模式则以
   非零码 :data:`EXIT_WATCHDOG` 退出，控制台窗口看得见明确错误。
2. **进程外守护**（``run_server.py`` 守护模式）：子进程退出或探活失败时按
   指数退避重启。见该模块 docstring。

为什么用 ``uvicorn.Server`` 而不是 ``uvicorn.run()``：只有拿到 Server 对象，
看门狗线程才能把 ``should_exit`` 置位，从而把"accept 循环已死、主循环还在
空转"这种半死状态拉回来（``uvicorn.run()`` 拿不到句柄，只能干等）。
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request

#: 看门狗触发退出码 —— 上层守护据此区分"人为停止"与"看门狗自愈"
EXIT_WATCHDOG = 42

#: 启动宽限期：uvicorn startup（建表/补列/索引/OCR 预热）期间探活必然失败，
#: 不该算故障。90s 远大于实测的启动耗时。
DEFAULT_GRACE_S = 90.0

#: 探活周期
DEFAULT_INTERVAL_S = 10.0

#: 端口失联（accept 循环死掉）连续失败次数 → 3 × 10s ≈ 30s 无监听即自愈
TCP_FAIL_LIMIT = 3

#: 端口在但 ``/api/health`` 连续不可用次数 → 事件循环/应用层卡死的兜底，
#: 6 × 10s ≈ 1 分钟无响应才动手，避免把偶发慢请求误判成故障。
HEALTH_FAIL_LIMIT = 6

#: 单次健康探测超时（``/api/health`` 实测 ~240ms，5s 已极宽裕）
HEALTH_TIMEOUT_S = 5.0

_logger_lock = threading.Lock()


def _log(msg: str) -> None:
    with _logger_lock:
        print(f"[watchdog] {msg}", file=sys.stderr, flush=True)


def _loopback(host: str) -> str:
    """把通配监听地址换回可连接的回环地址。"""
    return "127.0.0.1" if host in ("0.0.0.0", "::", "", "[::]") else host


def probe_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    """TCP 层探活：内核是否还在接受连接。

    区别于 HTTP 探活：即使事件循环卡死，内核仍会把连接放进 backlog
    （TCP 握手成功），所以本项只用来发现"监听 socket 没了"这种
    ``WinError 64`` 后的典型状态。
    """
    try:
        with socket.create_connection((_loopback(host), port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_health(host: str, port: int, timeout: float = HEALTH_TIMEOUT_S) -> bool:
    """HTTP 层探活 ``/api/health``。

    绕过代理：本机曾实测 ``http_proxy`` 劫持本机请求（见 scripts/eval_qa_model）。
    """
    url = f"http://{_loopback(host)}:{port}/api/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            return 200 <= status < 400
    except Exception:  # noqa: BLE001 —— 探活失败一律按"不健康"处理
        return False


class ServerWatchdog(threading.Thread):
    """周期探活，连续失败时把 uvicorn ``Server.should_exit`` 置位。

    只读 ``server.should_exit`` 是纯 Python 属性赋值，线程安全；
    uvicorn 主循环每轮 ``while not self.should_exit`` 都会看到它。
    """

    def __init__(
        self,
        server,  #: uvicorn.Server
        host: str,
        port: int,
        *,
        grace_s: float = DEFAULT_GRACE_S,
        interval_s: float = DEFAULT_INTERVAL_S,
        tcp_fail_limit: int = TCP_FAIL_LIMIT,
        health_fail_limit: int = HEALTH_FAIL_LIMIT,
        health_timeout_s: float = HEALTH_TIMEOUT_S,
    ) -> None:
        super().__init__(name="uvicorn-watchdog", daemon=True)
        self._server = server
        self._host = host
        self._port = port
        self._grace_s = grace_s
        self._interval_s = interval_s
        self._tcp_fail_limit = tcp_fail_limit
        self._health_fail_limit = health_fail_limit
        self._health_timeout_s = health_timeout_s
        self._stop_evt = threading.Event()
        self._tcp_fails = 0
        self._health_fails = 0
        #: 看门狗是否因探活失败而触发（用于决定退出码）
        self.triggered = False
        self.reason = ""

    def stop(self) -> None:
        """让看门狗线程尽快退出（服务正常关闭时调用）。"""
        self._stop_evt.set()

    def run(self) -> None:
        # 宽限期内完全不探活：startup 期间端口尚未 listen 是正常状态。
        if self._stop_evt.wait(self._grace_s):
            return
        while not self._stop_evt.is_set():
            try:
                self._tick()
            except Exception as e:  # noqa: BLE001 —— 看门狗自身绝不能崩
                _log(f"探活循环异常（已忽略，下轮重试）: {type(e).__name__}: {e}")
            if self._stop_evt.wait(self._interval_s):
                return

    def _tick(self) -> None:
        if probe_tcp(self._host, self._port):
            self._tcp_fails = 0
            # 端口在 → 才有意义看应用是否响应
            if probe_health(self._host, self._port, timeout=self._health_timeout_s):
                self._health_fails = 0
                return
            self._health_fails += 1
            if self._health_fails >= self._health_fail_limit:
                self._fire(
                    f"端口 {self._port} 在监听但 /api/health 连续 "
                    f"{self._health_fails} 次不可用（事件循环/应用层疑似卡死）"
                )
        else:
            self._tcp_fails += 1
            self._health_fails = 0
            if self._tcp_fails >= self._tcp_fail_limit:
                self._fire(
                    f"端口 {self._port} 连续 {self._tcp_fails} 次连接失败"
                    f"（accept 循环疑似已死，对应 WinError 64 那类故障）"
                )

    def _fire(self, reason: str) -> None:
        if self.triggered:
            return
        self.triggered = True
        self.reason = reason
        _log(f"{reason} → 请求 uvicorn 优雅退出，交由守护进程重启")
        try:
            self._server.should_exit = True
        except Exception as e:  # noqa: BLE001
            _log(f"置位 should_exit 失败: {type(e).__name__}: {e}")


def run_with_watchdog(
    host: str,
    port: int,
    *,
    app: str = "main:app",
    log_level: str = "info",
    grace_s: float = DEFAULT_GRACE_S,
    interval_s: float = DEFAULT_INTERVAL_S,
) -> int:
    """启动 uvicorn 并挂上看门狗，返回进程退出码。

    Returns:
        0 —— 正常退出（人为停止 / Ctrl+C）；
        :data:`EXIT_WATCHDOG` —— 看门狗因探活失败触发的自愈退出。
    """
    import uvicorn

    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level=log_level,
        # Windows 上显式固定 asyncio 事件循环（本机无 uvloop，auto 也是 asyncio，
        # 显式写出来避免不同环境行为漂移），与 P0-3 的崩溃排查口径一致。
        loop="asyncio",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    watchdog = ServerWatchdog(server, host, port, grace_s=grace_s, interval_s=interval_s)
    watchdog.start()
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        watchdog.stop()

    if watchdog.triggered:
        _log(
            f"已退出：{watchdog.reason}。"
            f"退出码={EXIT_WATCHDOG}（守护进程会按退避策略重启）"
        )
        return EXIT_WATCHDOG
    return 0


def ensure_watchdog_env(host: str, port: int) -> None:
    """给需要自己拉起服务的入口复用的 env 归一化（占位，保持接口对称）。"""
    os.environ.setdefault("HOST", host)
    os.environ.setdefault("PORT", str(port))
