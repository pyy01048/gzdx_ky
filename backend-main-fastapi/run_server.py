# -*- coding: utf-8 -*-
"""后台模式启动器 —— **守护型**（父进程监控 + 退避重启 + 停止协同）。

由 启动.bat 的后台模式调用：
    python run_server.py > data/server.log 2>&1

两种模式（同一文件）：
    python run_server.py            # 守护模式（默认）：拉起 --serve 子进程并盯着
    python run_server.py --serve    # 服务模式：跑 uvicorn + 进程内看门狗

### 为什么从"直接 uvicorn.run"改成守护（P0-3）

2026-10-21 实测：日志出现 ``OSError [WinError 64] Accept failed on a socket``
之后，**进程还活着但端口不再接受连接** —— 监控看"进程在不在"会误判健康，
整站不可用且不会自愈，只能人工重启。

现在分两层：
  1. 子进程内 ``utils.server_watchdog``：端口/健康连续失败 → uvicorn 干净退出；
  2. 本守护进程：子进程退出 → 指数退避重启（重启前先看 ``data/server.stop`` 标记）。

人为停止怎么区分？
    ``scripts/launcher.py::stop_backend`` 停服务前先写 ``data/server.stop`` 标记，
    再杀端口进程与本守护的 PID。守护看到标记就**不再重启**并自行退出；
    下次启动时清掉旧标记。这样"停止"不会被守护当成崩溃拉起来。

### 退避策略
    子进程活得够久（>60s，运行中突发故障）→ 重启计数清零；
    连续快速崩溃 ≥10 次 → 放弃并打印诊断（大概率是配置/端口占用问题，
    无限重试只会把日志刷爆）。
"""

import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PID_FILE = os.path.join(DATA_DIR, "server.pid")
STOP_MARKER = os.path.join(DATA_DIR, "server.stop")
SERVER_LOG = os.path.join(DATA_DIR, "server.log")

#: 子进程活得超过该秒数就认为"这次启动是成功的"，崩溃计数清零
STABLE_SECONDS = 60.0
#: 连续快速崩溃上限（配置错/端口占用时避免无限刷日志）
MAX_FAST_FAILS = 10
#: 退避上限（秒）
MAX_BACKOFF = 30.0
#: 外层探活周期与连续失败阈值（子进程看门狗正常会先触发，这里是兜底）
PROBE_INTERVAL = 15.0
PROBE_FAIL_LIMIT = 4
#: 启动宽限：给建表/补列/OCR 预热留时间，期间不探活
PROBE_GRACE = 120.0

EXIT_WATCHDOG = 42  # 与 utils.server_watchdog.EXIT_WATCHDOG 一致


def _log(msg: str) -> None:
    print(f"[守护] {msg}", flush=True)


def _load_env() -> tuple[str, int]:
    """加载 .env —— 否则 HOST/PORT 读不到，「局域网模式」会静默失效。"""
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(BASE_DIR, ".env"))
    except Exception:  # noqa: BLE001
        pass
    host = os.getenv("HOST", "127.0.0.1")
    try:
        port = int(os.getenv("PORT", "8000"))
    except ValueError:
        port = 8000
    return host, port


def _remove(*paths: str) -> None:
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def _stop_requested() -> bool:
    return os.path.exists(STOP_MARKER)


def _pid_alive(pid: int) -> bool:
    """跨平台判活；Windows 用 Kernel32（无需 psutil）。"""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return bool(ok and code.value == STILL_ACTIVE)
    finally:
        kernel32.CloseHandle(handle)


def serve() -> int:
    """服务模式：跑 uvicorn + 进程内看门狗，退出码透传给守护。"""
    from utils.server_watchdog import run_with_watchdog

    host, port = _load_env()
    return run_with_watchdog(host, port)


def _spawn_child() -> "subprocess.Popen":
    cmd = [sys.executable, os.path.abspath(__file__), "--serve"]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    kwargs: dict = {"cwd": BASE_DIR, "env": env}
    if os.name == "nt":
        # 0x08000000 = CREATE_NO_WINDOW：后台模式不弹黑框
        kwargs["creationflags"] = 0x08000000
    return subprocess.Popen(cmd, **kwargs)


def _terminate(child: "subprocess.Popen") -> None:
    if child.poll() is not None:
        return
    try:
        child.terminate()
        child.wait(timeout=10)
    except Exception:  # noqa: BLE001
        try:
            child.kill()
            child.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


def _health_ok(host: str, port: int) -> bool:
    from utils.server_watchdog import probe_health, probe_tcp

    return probe_tcp(host, port) and probe_health(host, port)


def supervise() -> int:
    """守护模式：拉起子进程、探活、退避重启、响应停止标记。"""
    os.makedirs(DATA_DIR, exist_ok=True)

    # 防止重复守护：PID 文件里的进程若还活着且不是自己，直接退出。
    if os.path.exists(PID_FILE):
        try:
            old_pid = int(open(PID_FILE, encoding="utf-8").read().strip())
        except (ValueError, OSError):
            old_pid = 0
        if old_pid and old_pid != os.getpid() and _pid_alive(old_pid):
            _log(f"已有守护进程在运行（PID={old_pid}），本进程退出")
            return 0

    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    # 上次非正常退出可能留下旧标记 —— 新一轮启动意味着"要跑"，清掉。
    # （stop 写标记 → 守护看到后退出；若守护被强杀没来得及清，这里兜底。）
    _remove(STOP_MARKER)

    host, port = _load_env()
    _log(f"服务模式启动：{host}:{port}（PID={os.getpid()}）")
    _log(f"日志：{SERVER_LOG}")

    def _cleanup(*_a):
        _remove(PID_FILE, STOP_MARKER)
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, _cleanup)
        signal.signal(signal.SIGTERM, _cleanup)
    except Exception:  # noqa: BLE001
        pass

    fast_fails = 0
    backoff = 1.0
    rc = 0

    try:
        while not _stop_requested():
            child = _spawn_child()
            _log(f"子进程已拉起 PID={child.pid}")
            started = time.time()
            first_probe_at = started + PROBE_GRACE
            next_probe_at = first_probe_at
            probe_fails = 0
            killed_for_health = False

            # ---- 盯着这个子进程 ----
            while True:
                time.sleep(1.0)
                if _stop_requested():
                    _log("收到停止标记，不再重启")
                    _terminate(child)
                    return 0
                if child.poll() is not None:
                    rc = child.returncode
                    break

                now = time.time()
                if now >= next_probe_at:
                    next_probe_at = now + PROBE_INTERVAL
                    if _health_ok(host, port):
                        probe_fails = 0
                    else:
                        probe_fails += 1
                        if probe_fails >= PROBE_FAIL_LIMIT:
                            _log(
                                f"外层探活：{host}:{port} 连续 {probe_fails} 次不健康"
                                f"（进程在但不服务），杀掉子进程重启"
                            )
                            killed_for_health = True
                            _terminate(child)
                            rc = child.returncode or EXIT_WATCHDOG
                            break

            uptime = time.time() - started
            if _stop_requested():
                _log("停止标记存在，退出守护")
                return 0

            if uptime > STABLE_SECONDS:
                fast_fails = 0
                backoff = 1.0

            fast_fails += 1
            why = "外层探活判死" if killed_for_health else f"退出码={rc}"
            _log(f"子进程结束（{why}，存活 {uptime:.1f}s）")

            if fast_fails >= MAX_FAST_FAILS and uptime < STABLE_SECONDS:
                _log(
                    f"连续 {fast_fails} 次快速失败，放弃重启。"
                    f"请检查：端口 {port} 是否被占用、.env 配置、"
                    f"{SERVER_LOG} 里的 traceback"
                )
                return 1

            _log(f"{backoff:.0f}s 后重启…")
            deadline = time.time() + backoff
            while time.time() < deadline:
                if _stop_requested():
                    _log("停止标记存在，放弃重启")
                    return 0
                time.sleep(0.3)
            backoff = min(backoff * 2, MAX_BACKOFF)
    finally:
        _remove(PID_FILE)
        # 标记若仍在，说明是我们自己读到停止信号后清掉的；强杀场景由下次启动兜底。
        _remove(STOP_MARKER)
    return rc if rc else 1


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if "--serve" in args:
        return serve()
    return supervise()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
