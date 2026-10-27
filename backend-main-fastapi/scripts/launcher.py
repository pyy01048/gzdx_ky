"""考研学习平台 · 交互式启动器（批处理只做外壳，全部 UI 在这里）。

为什么要把批处理掏空
--------------------
实测确认：**UTF-8（无论有无 BOM）的 .bat 里只要有中文，cmd 就可能把这一行从
中文字节中间截断，并把下一行吞掉**。最小复现::

    @echo off
    chcp 65001 >nul
    REM  挑错了解释器，用户只会看到一堆 xxx。
    echo A-OK          <- 这一行永远不会执行

加 BOM 更糟 —— 连 ``@echo off`` 自己都被当成命令。也就是说旧的
``启动.bat`` / ``启动数据库.bat`` 里那满屏中文本身就是定时炸弹：某些机器正常，
某些机器上命令会被静默吞掉，表现为"点了没反应"。

所以规矩是：**.bat 只允许 ASCII，所有中文由 Python 输出**（Python 侧显式把
控制台切到 65001，见 _ensure_utf8_console）。

顺带修掉的旧问题
----------------
* 旧 ``停止.bat`` 用了 ``!_pid!`` 却没开 ``setlocal EnableDelayedExpansion``
  → 变量不会被求值，脚本看着正常实则一个进程都没杀掉。
* 旧 ``wait_ready`` 用 ``curl -s``（不带 ``-f``）→ HTTP 500 也返回 0，
  健康检查挂了照样打印"[OK] 服务已就绪"。
* 旧 ``启动-本机.bat`` 有一行嵌套引号写错，浏览器压根打不开。
* 最重要的：**旧启动器从不检查数据库**，库挂了照样起后端，用户看到的是一堆
  莫名其妙的接口报错。现在每个启动入口都会先 ``ensure-db``。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT.parent / "backend-main-fastapi"

DEFAULT_TITLE = "考研学习平台 · 启动器"


# --------------------------------------------------------------------------- #
# 控制台编码
# --------------------------------------------------------------------------- #
def _ensure_utf8_console() -> None:
    """把控制台切到 UTF-8。批处理侧的 chcp 不可靠，这里兜底。"""
    if os.name == "nt":
        try:  # pragma: no cover - 平台分支
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# 纯函数：可离线单测
# --------------------------------------------------------------------------- #
def parse_netstat_listen(output: str, port: str | int) -> list[int]:
    """从 netstat 输出里解析出监听该端口的 PID 列表。

    netstat 行形如::

      TCP    0.0.0.0:8000    0.0.0.0:0    LISTENING    12345

    比在 .bat 里做 findstr+fortokens 可靠得多（也终于可测了）。
    """
    port = str(port)
    pids: list[int] = []
    for raw in (output or "").splitlines():
        line = raw.split()
        if len(line) < 5 or "LISTENING" not in line:
            continue
        local = line[1]
        # IPv6 形态：[::]:8000 或 [::1]:8000
        if ":" not in local:
            continue
        host_part, _, port_part = local.rpartition(":")
        # netstat 的本地地址可能是 0.0.0.0:8000 / 127.0.0.1:8000 / [::]:8000
        if port_part != port:
            continue
        _ = host_part
        try:
            pids.append(int(line[-1]))
        except ValueError:
            continue
    return sorted(set(pids))


def build_backend_cmd(
    host: str, port: int, mode: str = "normal"
) -> list[str]:
    """拼出启动后端的命令行。

    mode: normal / background / dev
    """
    py = sys.executable
    if mode == "dev":
        return [py, "-m", "uvicorn", "main:app", "--host", host,
                "--port", str(port), "--reload"]
    if mode == "background":
        script = str(BACKEND / "run_server.py")
        return [py, script]
    script = str(BACKEND / "main.py")
    return [py, script]


# --------------------------------------------------------------------------- #
# 环境探测
# --------------------------------------------------------------------------- #
def read_env() -> dict[str, str]:
    """读后端 .env。复用 startup_manager 的解析器，避免两套口径。"""
    if str(Path(__file__).parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).parent))
    from startup_manager import parse_env_kv  # noqa: WPS433 - 兄弟模块，延迟导入

    try:
        text = (BACKEND / ".env").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return parse_env_kv(text)


def _netstat() -> str:
    try:
        proc = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            timeout=15, encoding="utf-8", errors="replace",
        )
        return proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def pids_on_port(port: int) -> list[int]:
    return parse_netstat_listen(_netstat(), port)


def backend_up(port: int) -> bool:
    return bool(pids_on_port(port))


def http_ok(url: str, timeout: float = 2.0) -> bool:
    """真实 HTTP 健康检查。httpx 不可用时降级 urllib。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 400
    except Exception:  # noqa: BLE001
        return False


def wait_ready(url: str, timeout: int = 40) -> bool:
    deadline = time.time() + max(1, timeout)
    while time.time() < deadline:
        if http_ok(url):
            return True
        time.sleep(1)
    return False


# --------------------------------------------------------------------------- #
# 动作
# --------------------------------------------------------------------------- #
def ensure_db(timeout: int = 45) -> bool:
    """保证数据库活着。SQLite 后端时直接通过。"""
    env = read_env()
    if env.get("DATABASE_BACKEND", "").strip() == "sqlite":
        print("  [数据库] 配置为 SQLite，无需 PostgreSQL")
        return True

    port = int(env.get("PG_PORT", "5432") or 5432)
    if pids_on_port(port):
        print(f"  [数据库] PostgreSQL 已在监听 {port}")
        return True

    if not (BACKEND / "scripts" / "startup_manager.py").exists():
        print("  [数据库] 找不到 scripts/startup_manager.py，跳过检查")
        return True

    print("  [数据库] 未运行，正在拉起（含崩溃残留清理）...")
    proc = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "startup_manager.py"), "ensure-db"],
        cwd=str(BACKEND), encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        print("  [数据库] 启动失败 —— 服务先不起，起了也是一堆报错")
        subprocess.run(
            [sys.executable, str(BACKEND / "scripts" / "startup_manager.py"), "diagnose"],
            cwd=str(BACKEND), encoding="utf-8", errors="replace",
        )
        return False
    return True


def kill_pids(pids: Iterable[int]) -> None:
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True, timeout=10,
            )
            print(f"        已停止 PID={pid}")
        except (subprocess.TimeoutExpired, OSError):
            print(f"        停止 PID={pid} 失败")


def stop_backend(port: int) -> None:
    # P0-3：先写停止标记 —— 后台守护进程（run_server.py 守护模式）看到标记
    # 就知道这是**人为停止**，不会再把子进程当崩溃拉起来。
    try:
        marker = BACKEND / "data" / "server.stop"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("stop", encoding="utf-8")
    except OSError as e:
        print(f"  [warn] 写停止标记失败（守护可能重复拉起）: {e}")

    pids = pids_on_port(port)
    # 守护进程本身不占端口，得按 PID 文件单独杀，否则它会守护着端口进程复活。
    try:
        pid_text = (BACKEND / "data" / "server.pid").read_text(encoding="utf-8").strip()
        daemon_pid = int(pid_text)
        if daemon_pid and daemon_pid != os.getpid():
            pids.append(daemon_pid)
    except (OSError, ValueError):
        pass

    if not pids:
        print(f"  端口 {port} 未被占用")
        return
    kill_pids(sorted(set(pids)))


def start_backend(host: str, port: int, mode: str = "normal") -> bool:
    cmd = build_backend_cmd(host, port, mode)

    # 必须显式注入 HOST/PORT：否则后端仍会读 .env 里的 HOST=0.0.0.0，
    # 「本机模式」就名存实亡了（改 ROOT_CONFIG 不如直接给子进程 env）。
    env = os.environ.copy()
    env["HOST"] = host
    env["PORT"] = str(port)

    popen_kwargs: dict = {"cwd": str(BACKEND), "env": env}
    if mode == "background":
        log = BACKEND / "data" / "server.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        popen_kwargs["stdout"] = open(log, "a", encoding="utf-8", errors="replace")
        popen_kwargs["stderr"] = subprocess.STDOUT
        if os.name == "nt":
            popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    if os.name == "nt" and mode in ("normal", "dev"):
        # 新窗口可见日志，出错能看见（cmd /k 保证崩溃后窗口不立刻关，看得见 traceback）。
        #
        # 这里**不能**用 `cmd /c start "标题" ...`：
        #   1. Python 用 list 传参时，subprocess 只对"含空格"的参数加引号，
        #      纯中文标题「考研平台」不含空格 → 原样传给 cmd → start 把它当成
        #      要打开的文件名 → 报 "The system cannot find the file 考研平台."
        #      （用户实测就是这个报错）；
        #   2. 中文经 cmd 中转还有 chcp 编码风险，与 .bat 禁中文同理。
        # 直接 CREATE_NEW_CONSOLE 开新 console 跑 cmd /k，既省掉 start 这层
        # 引号地狱，又保留"崩溃后窗口不关"的效果。
        inner = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        popen_kwargs["creationflags"] = 0x00000010  # CREATE_NEW_CONSOLE
        subprocess.Popen(["cmd", "/k", inner], **popen_kwargs)
    else:
        subprocess.Popen(cmd, **popen_kwargs)
    return True


def lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def _pause(msg: str = "\n按回车继续...") -> None:
    try:
        input(msg)
    except (EOFError, KeyboardInterrupt):
        pass


# --------------------------------------------------------------------------- #
# 菜单
# --------------------------------------------------------------------------- #
def print_header(env: dict[str, str]) -> None:
    port = env.get("PORT", "8000")
    host = env.get("HOST", "127.0.0.1")
    _ = host
    print()
    print("  ============================================================")
    print(f"      {DEFAULT_TITLE}")
    print("  ============================================================")
    print()
    print(f"      当前配置: 监听 {host}:{port}")
    up = backend_up(int(port))
    print(f"      服务状态: {'正在运行' if up else '未运行'}")
    print(f"      访问地址: http://127.0.0.1:{port}")
    print()
    print("  ------------------------------------------------------------")
    print("     请选择启动方式:")
    print("  ------------------------------------------------------------")
    print()
    print("      [1]  本机模式     仅本机访问，最安全（推荐日常用）")
    print("      [2]  局域网模式   手机/平板可访问")
    print("      [3]  后台模式     静默启动，不占任务栏，自动开浏览器")
    print("      [4]  停止服务     关闭正在运行的服务")
    print("      [5]  打开浏览器   服务已在运行时直接用")
    print("      [6]  环境自检     检查 Python / 依赖 / 数据库")
    print("      [7]  开发模式     后端热重载")
    print()
    print("      [0]  退出")
    print()


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_console()
    args = list(argv or [])
    env = read_env()
    port = int(env.get("PORT", "8000") or 8000)
    url = f"http://127.0.0.1:{port}"

    # 非交互快捷模式：启动时直接带参数
    if args:
        action = args[0]
        if action in ("local", "lan", "background", "dev"):
            if not ensure_db():
                return 1
            host = "0.0.0.0" if action == "lan" else "127.0.0.1"
            start_backend(host, port, "background" if action == "background" else
                          ("dev" if action == "dev" else "normal"))
            print(f"  正在启动（{host}:{port}）...")
            print("  [OK] 服务已就绪" if wait_ready(f"{url}/api/health")
                  else "  [警告] 等待超时，请查看后端窗口日志")
            return 0
        if action == "stop":
            stop_backend(port)
            return 0
        if action == "diagnose":
            return subprocess.run(
                [sys.executable, str(BACKEND / "scripts" / "startup_manager.py"), "diagnose"],
                cwd=str(BACKEND), encoding="utf-8", errors="replace",
            ).returncode

    while True:
        os.system("cls" if os.name == "nt" else "clear")
        print_header(read_env())
        choice = input("  请输入编号并回车: ").strip()

        if choice == "0":
            return 0
        if choice in ("1", "2", "3", "7"):
            if not ensure_db():
                _pause()
                continue
            host = "0.0.0.0" if choice == "2" else "127.0.0.1"
            mode = {1: "normal", 2: "normal", 3: "background", 7: "dev"}[int(choice)]
            if choice == "2":
                _try_open_firewall(port)
            start_backend(host, port, mode)
            print("  正在启动后端...")
            ok = wait_ready(f"{url}/api/health")
            print("  [OK] 服务已就绪" if ok else "  [警告] 等待超时，请查看后端窗口日志")
            if ok and choice != "3":
                _open_browser(url)
            if choice == "2":
                ip = lan_ip()
                if ip:
                    print(f"  手机访问: http://{ip}:{port}  （需同一 WiFi）")
            _pause()
        elif choice == "4":
            stop_backend(port)
            ans = input("  是否同时停止数据库？(y/N): ").strip().lower()
            if ans == "y":
                subprocess.run(
                    [sys.executable, str(BACKEND / "scripts" / "startup_manager.py"), "stop-db"],
                    cwd=str(BACKEND), encoding="utf-8", errors="replace",
                )
            _pause()
        elif choice == "5":
            _open_browser(url)
        elif choice == "6":
            subprocess.run(
                [sys.executable, str(BACKEND / "scripts" / "diagnostics" / "check_env.py")],
                cwd=str(BACKEND), encoding="utf-8", errors="replace",
            )
            _pause()
        else:
            print("  无效选项")
            time.sleep(1)


def _try_open_firewall(port: int) -> None:
    try:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             "name=KaoyanPlatform", "dir=in", "action=allow",
             "protocol=TCP", f"localport={port}"],
            capture_output=True, timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


def _open_browser(url: str) -> None:
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
