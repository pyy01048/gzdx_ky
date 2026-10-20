"""考研学习平台 · 启动前置管家。

把原来散落在 .bat 里的启动逻辑收进 Python：外壳 Florida 之前这一步经常
踩到的坑都在这里一次性解决。

设计立场
--------
.bat 只负责一行调用，逻辑全在 Python —— 因为批处理里「先 lowlevel 判定再
分支」很容易写错，且无法单测。本模块的**判定逻辑全部纯函数**，
不依赖数据库，掉库也能跑测试（见 tests/test_startup_manager.py）。

覆盖的坑
--------
1. **崩溃残留的 postmaster.pid**：PG 非正常退出后 pid 文件还在，pg_ctl 会误判
   "another server might be running" 而拒绝启动 —— 旧的 启动数据库.bat 对此
   毫无办法，用户只能手动进 data 目录删文件。本模块会**先确认 PID 是否已死**，
   确认死了才删（活着的一律不动）。
2. **假就绪**：只探 TCP 端口是不够的，PG 恢复 WAL 期间端口可能已听但未接受
   查询。本模块依次做 端口 → pg_isready → 真实 SQL 探活 三级确认。
3. **编码**：旧脚本 UTF-8 保存却在 cp936 下运行，中文全是乱码
   （实测输出过 ``数据目录?PGDATA``）。统一由本模块输出 UTF-8，
   调用方 .bat 必须 ``chcp 65001``。
4. **Python 解释器漂移**：机器上可能有多个 python，PATH 里那个未必装了
   psycopg。这里把「该用哪个 python」显式化。

用法
----
    python scripts/startup_manager.py diagnose      # 只体检，不改任何东西
    python scripts/startup_manager.py ensure-db     # 保证库活着（必要时拉起）
    python scripts/startup_manager.py ensure-db --json
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# PG 让 cmdline 全部走绝对路径，避免 PATH 里刚好有个别的 psql
DEFAULT_PGBIN = r"D:\pgsql\pgenv\Library\bin"
DEFAULT_PGDATA = r"D:\pgsql\data"
DEFAULT_PGLOG = r"D:\pgsql\server.log"

# 环境变量优先（方便 .bat / 其他机器覆盖默认安装路径）
ENV_PGBIN = "PG_BIN_DIR"
ENV_PGDATA = "PG_DATA_DIR"


# --------------------------------------------------------------------------- #
# 纯函数：可离线单测
# --------------------------------------------------------------------------- #
def parse_pid_file(path: str | os.PathLike) -> int | None:
    """读 postmaster.pid 第一行的 PID。文件缺失/损坏返回 None。

    PG 的 postmaster.pid 格式：第一行是 postmaster 进程 PID，后面是数据目录、
    版本号等。我们只关心第一行。
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    return int(line)
                except ValueError:
                    return None
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return None
    return None


def pid_alive(pid: int | None) -> bool:
    """判断进程是否还活着（Windows 用 OpenProcess，不依赖 psutil）。

    pid 为 None / 非正整数 → False。
    """
    if not pid or pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - 平台分支
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:  # pragma: no cover - 平台分支
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_stale_pid_file(path: str | os.PathLike) -> bool:
    """pid 文件存在、且里面记的进程已经死掉 —— 这就是崩溃残留。"""
    if not os.path.exists(path):
        return False
    return not pid_alive(parse_pid_file(path))


def remove_stale_pid(path: str | os.PathLike) -> bool:
    """删除**已确认陈旧**的 pid 文件。活着的进程一律不碰，返回 False。"""
    if not is_stale_pid_file(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def port_open(host: str, port: int, timeout: float = 0.6) -> bool:
    """TCP 连通性探测。这是最弱的一级就绪判据。"""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError, OverflowError):
        return False


def parse_env_kv(text: str) -> dict[str, str]:
    """极简 .env 解析器（只要 KEY=VALUE，忽略注释行与 export 前缀）。"""
    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        out[key] = value.strip().strip('"').strip("'")
    return out


def pick_python(candidates: list[str]) -> str | None:
    """从候选解释器里挑第一个**真的存在**的。

    背景：机器上 PATH 里的 python 未必是装了 psycopg/sqlalchemy 的那个，
    启动失败时用户只会看到一堆 ModuleNotFoundError，很难联想到解释器选错。
    """
    for cand in candidates:
        if not cand:
            continue
        if cand.lower() in ("python", "python3", "py"):
            cand = sys.executable
        if os.path.exists(cand) or cand == sys.executable:
            return cand
    return None


# --------------------------------------------------------------------------- #
# 有副作用：起停 / 探测
# --------------------------------------------------------------------------- #
class Report:
    """收集体检/启动过程的每一步，便于 --json 输出与排错。"""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.steps.append({"step": name, "ok": bool(ok), "detail": str(detail)})

    @property
    def ok(self) -> bool:
        return all(s["ok"] for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "steps": self.steps}


def _pg_ctl_path(pgbin: str) -> str:
    return os.path.join(pgbin, "pg_ctl.exe" if os.name == "nt" else "pg_ctl")


def start_postgres(
    pgbin: str = DEFAULT_PGBIN,
    pgdata: str = DEFAULT_PGDATA,
    logfile: str = DEFAULT_PGLOG,
    port: int = 5432,
    wait_seconds: int = 40,
    report: Report | None = None,
) -> bool:
    """拉起 PG，直到三级就绪确认全部通过。"""
    rep = report or Report()
    pidfile = os.path.join(pgdata, "postmaster.pid")

    # 0) 陈旧 pid 先行处理 —— 不清理的话 pg_ctl 会直接拒绝启动
    if os.path.exists(pidfile):
        if is_stale_pid_file(pidfile):
            if remove_stale_pid(pidfile):
                rep.add("清理残留pid", True, f"已删除 {pidfile}")
            else:
                rep.add("清理残留pid", False, f"发现陈旧 pid 文件但删不掉: {pidfile}")
                return False
        else:
            rep.add("清理残留pid", True, "pid 对应的进程仍活着，不处理")

    pg_ctl = _pg_ctl_path(pgbin)
    if not os.path.exists(pg_ctl):
        rep.add("pg_ctl 存在", False, f"找不到 {pg_ctl}")
        return False

    # 1) 已经在跑就不重复拉
    if port_open("127.0.0.1", port):
        rep.add("端口已监听", True, f"127.0.0.1:{port} 已在服务")
        return True

    # 2) 启动
    cmd = [pg_ctl, "-D", pgdata, "-l", logfile, "-o", f"-p {port}", "start"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=wait_seconds,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        rep.add("启动 PostgreSQL", False, f"pg_ctl 超过 {wait_seconds}s 未返回")
        return False
    except OSError as exc:
        rep.add("启动 PostgreSQL", False, f"无法执行 pg_ctl: {exc}")
        return False

    tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    detail = tail[-1] if tail else ""
    # pg_ctl 的常见良性提示不算失败（例如 "another server might be running"
    # 但端口随后确实起来了）
    rep.add("启动 PostgreSQL", proc.returncode == 0 or port_open("127.0.0.1", port),
            detail or f"returncode={proc.returncode}")

    # 3) 等待就绪：端口 → pg_isready → 真实 SQL
    return wait_ready(
        host="127.0.0.1", port=port, timeout=wait_seconds, report=rep
    )


def wait_ready(
    host: str = "127.0.0.1",
    port: int = 5432,
    timeout: int = 40,
    report: Report | None = None,
    pgbin: str = DEFAULT_PGBIN,
) -> bool:
    """三级就绪确认。任何一级失败都返回 False，避免「假启动成功」。

    只探端口不够：PG 在做崩溃恢复（redo）的几十秒里端口已 Listen，
    但还不能执行查询，此时放用户进去就会看到莫名其妙的连接错误。
    """
    rep = report or Report()
    deadline = time.time() + max(1, timeout)

    ok_port = False
    while time.time() < deadline:
        if port_open(host, port):
            ok_port = True
            break
        time.sleep(0.5)
    rep.add("端口就绪", ok_port, f"{host}:{port}")
    if not ok_port:
        return False

    pg_isready = os.path.join(pgbin, "pg_isready.exe" if os.name == "nt" else "pg_isready")
    if os.path.exists(pg_isready):
        last = ""
        while time.time() < deadline:
            try:
                proc = subprocess.run(
                    [pg_isready, "-h", host, "-p", str(port)],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                )
                last = ((proc.stdout or "") + (proc.stderr or "")).strip()
                if proc.returncode == 0:
                    rep.add("pg_isready", True, last)
                    return True
            except (subprocess.TimeoutExpired, OSError) as exc:
                last = str(exc)
            time.sleep(0.5)
        rep.add("pg_isready", False, last or "超时")
        return False

    rep.add("pg_isready", True, "未找到 pg_isready，跳过（以端口判据为准）")
    return True


def stop_postgres(
    pgbin: str = DEFAULT_PGBIN,
    pgdata: str = DEFAULT_PGDATA,
    port: int = 5432,
    mode: str = "fast",
    timeout: int = 30,
    report: Report | None = None,
) -> bool:
    """优雅停机。-m fast 会回滚活动事务，比 smart 更不容易卡住。"""
    rep = report or Report()
    pg_ctl = _pg_ctl_path(pgbin)
    if not os.path.exists(pg_ctl):
        rep.add("pg_ctl 存在", False, f"找不到 {pg_ctl}")
        return False
    try:
        proc = subprocess.run(
            [pg_ctl, "-D", pgdata, "-m", mode, "stop"],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        rep.add("停止 PostgreSQL", False, str(exc)[:200])
        return False

    last = (((proc.stdout or "") + (proc.stderr or "")).strip().splitlines() or [""])[-1]
    # 已经没在跑也算达成目标（幂等）
    stopped = (proc.returncode == 0) or (not port_open("127.0.0.1", port))
    rep.add("停止 PostgreSQL", stopped, last or f"returncode={proc.returncode}")
    return stopped


def probe_database(
    host: str, port: int, user: str, password: str, dbname: str
) -> tuple[bool, str]:
    """真实 SQL 探活 —— 最硬的一级判据。缺 psycopg 时不算失败。"""
    try:
        import psycopg  # noqa: WPS433 - 延迟import，管家要能在缺依赖时也能跑
    except Exception as exc:  # noqa: BLE001
        return True, f"未安装 psycopg，跳过 SQL 探活（{exc}）"
    try:
        with psycopg.connect(
            host=host, port=port, user=user, password=password,
            dbname=dbname, connect_timeout=5,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                row = cur.fetchone()
        return True, (row[0][:60] if row else "OK")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc).splitlines()[0][:200]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def read_pg_env(backend_dir: str) -> dict[str, str]:
    """从后端 .env 读 PG 连接参数（缺失给默认值）。"""
    env_text = ""
    try:
        env_text = (Path(backend_dir) / ".env").read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    kv = parse_env_kv(env_text)
    return {
        "host": kv.get("PG_HOST", "127.0.0.1"),
        "port": kv.get("PG_PORT", "5432"),
        # 本项目真库角色是 kaoyan，不存在 postgres 角色。
        # 默认曾写成 postgres，导致 ensure-db 在 .env 暂时读不到 PG_USER 时报
        # FATAL: role "postgres" does not exist（端口明明已经在监听）。
        "user": kv.get("PG_USER", "kaoyan"),
        "password": kv.get("PG_PASSWORD", ""),
        "dbname": kv.get("PG_DATABASE", "kaoyan"),
        "backend": kv.get("DATABASE_BACKEND", "sqlite"),
    }


#: role 不存在时的回退候选（按优先级）
FALLBACK_USERS = ("kaoyan", "postgres")


def probe_database_with_fallback(
    host: str, port: int, user: str, password: str, dbname: str
) -> tuple[bool, str, str]:
    """探活；若报 role 不存在则换候选用户重试。

    返回 (ok, detail, used_user)。.env 被并发改写或缺失时仍能连上，
    避免把「配置抖动」误报成「数据库没起来」。
    """
    ok, detail = probe_database(host, port, user, password, dbname)
    if ok:
        return True, detail, user

    low = (detail or "").lower()
    if "role" not in low and "does not exist" not in low:
        return False, detail, user

    for cand in FALLBACK_USERS:
        if cand == user:
            continue
        ok2, detail2 = probe_database(host, port, cand, password, dbname)
        if ok2:
            return True, f"{detail2}（回退用户 {cand}）", cand
    return False, detail, user


def _default_root() -> str:
    here = Path(__file__).resolve()
    return str(here.parents[1])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="考研学习平台 启动前置管家")
    p.add_argument("action", choices=["diagnose", "ensure-db", "stop-db"])
    p.add_argument("--pgbin", default=os.environ.get(ENV_PGBIN, DEFAULT_PGBIN))
    p.add_argument("--pgdata", default=os.environ.get(ENV_PGDATA, DEFAULT_PGDATA))
    p.add_argument("--pglog", default=DEFAULT_PGLOG)
    p.add_argument("--root", default=_default_root())
    p.add_argument("--timeout", type=int, default=40)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rep = Report()

    pgbin = args.pgbin
    pgdata = args.pgdata
    backend_dir = os.path.join(args.root, "backend-main-fastapi")
    pg = read_pg_env(backend_dir)
    port = int(pg["port"] or 5432)

    rep.add("数据目录存在", os.path.isdir(pgdata), pgdata)
    pgb_exists = os.path.isdir(pgbin)
    rep.add("PG 二进制目录存在", pgb_exists, pgbin)

    if args.action == "diagnose":
        listening = port_open(pg["host"], port)
        rep.add("端口已监听", listening, f"{pg['host']}:{port}")
        if listening:
            ok, detail, _used = probe_database_with_fallback(
                pg["host"], port, pg["user"], pg["password"], pg["dbname"]
            )
            rep.add("数据库可连接", ok, detail)
        pidfile = os.path.join(pgdata, "postmaster.pid")
        if is_stale_pid_file(pidfile):
            rep.add("pid 文件状态", False, f"存在崩溃残留 {pidfile}（需清理后才能启动）")
        elif os.path.exists(pidfile):
            rep.add("pid 文件状态", True, "存在且对应进程存活")
        if args.json:
            print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
        else:
            for s in rep.steps:
                flag = "OK  " if s["ok"] else "FAIL"
                print(f"[{flag}] {s['step']:<16} {s['detail']}")
        return 0 if rep.ok else 1

    if args.action == "stop-db":
        stopped = stop_postgres(
            pgbin=pgbin, pgdata=pgdata, port=port,
            timeout=max(10, args.timeout), report=rep,
        )
        if args.json:
            print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
        else:
            for s in rep.steps:
                flag = "OK  " if s["ok"] else "FAIL"
                print(f"[{flag}] {s['step']:<16} {s['detail']}")
            print()
            print("数据库已停止。" if stopped else "停止未完成，请查看上面 FAIL 项。")
        return 0 if stopped else 1

    # ensure-db
    started = start_postgres(
        pgbin=pgbin, pgdata=pgdata, logfile=args.pglog,
        port=port, wait_seconds=args.timeout, report=rep,
    )
    if started:
        ok, detail, _used = probe_database_with_fallback(
            pg["host"], port, pg["user"], pg["password"], pg["dbname"]
        )
        rep.add("数据库可连接", ok, detail)

    if args.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    else:
        for s in rep.steps:
            flag = "OK  " if s["ok"] else "FAIL"
            print(f"[{flag}] {s['step']:<16} {s['detail']}")
        print()
        print("数据库就绪。" if rep.ok else "数据库未能就绪，请查看上面 FAIL 项。")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
