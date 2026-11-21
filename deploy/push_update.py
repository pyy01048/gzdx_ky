# -*- coding: utf-8 -*-
"""华为云服务器增量部署（/opt/kaoyan）。

流程（对齐 deploy/DEPLOY.md 与完善方案 09）：
  1. 生成版本标识（_version.py：git SHA + 构建时间）
  2. 本地打包：后端代码 + static 前端产物（排除 .venv/data/uploads/logs/tests/__pycache__/.env）
  3. 服务器预检：磁盘 / 服务状态
  4. 服务器备份：/opt/kaoyan/backups/pre-<ts>.tar.gz（后端可回滚）
  5. 前端回滚点：当前 static → static.prev（rollback.sh 的约定，此前从不生成，回滚链断裂）
  6. 上传 + 原地解包（.venv / data / uploads 不受影响）
  7. 迁移：execute_core_sql.py --all-pending（账本化，替代手工插播 SQL）
  8. systemctl restart kaoyan + 健康验证（health 含 git_sha / 首页 / 401 鉴权 / journalctl）

用法：
    python deploy/push_update.py --package-only     # 只打包不上传
    python deploy/push_update.py --dry-run          # 打包 + 打印将执行的步骤
    $env:SSH_PW='<密码>'; python deploy/push_update.py   # 完整部署（密码仅走环境变量）

回滚（服务器上执行）：
    bash deploy/rollback.sh backend|frontend
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import time

# 服务器输出可能含 ✓/中文；Windows GBK 控制台直接 print 会 UnicodeEncodeError 崩溃
# （服务器命令其实已成功，崩溃只在本地打印阶段，易误判部署失败）。errors=replace 兜底防崩。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(BASE, "backend-main-fastapi")
HOST = os.environ.get("SSH_HOST", "60.204.223.140")
DEPLOY_USER = os.environ.get("SSH_USER", "deploy")

# deploy/artifacts 只保留最近 5 份（完善方案 09 §3.1）
KEEP_ARTIFACTS = 5
ARTIFACT_DIR = os.path.join(BASE, "deploy", "artifacts")

EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".venv",
    "data",
    "uploads",
    "logs",
    "tests",
    "docs",
    ".pytest_cache",
    ".ocr_tmp",
    ".pytest_tmp_fixed",
    "node_modules",
    "_eval_text_cache",
}
EXCLUDE_FILES = {".env", ".env.example", "kaoyan.db"}

TS = time.strftime("%Y%m%d-%H%M%S")


def _tar_filter(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = ti.name.split("/")
    if any(p in EXCLUDE_DIR_NAMES for p in parts):
        return None
    if os.path.basename(ti.name) in EXCLUDE_FILES:
        return None
    if ti.name.endswith((".pyc", ".pyo", ".log")):
        return None
    return ti


def gen_version() -> str:
    """生成 _version.py，返回短 SHA（打包名用）。"""
    out = subprocess.run(
        [sys.executable, os.path.join(BACKEND, "scripts", "gen_version.py")],
        capture_output=True,
        text=True,
        cwd=BACKEND,
    )
    if out.returncode != 0:
        print(out.stdout, out.stderr)
        raise SystemExit("[中止] 版本标识生成失败")
    sha = "unknown"
    try:
        sys.path.insert(0, BACKEND)
        from _version import GIT_SHA  # noqa: PLC0415

        sha = GIT_SHA
    except Exception:  # noqa: BLE001
        pass
    print(f"版本标识：{sha}")
    return sha


def _prune_artifacts() -> None:
    if not os.path.isdir(ARTIFACT_DIR):
        return
    files = sorted(
        (os.path.join(ARTIFACT_DIR, f) for f in os.listdir(ARTIFACT_DIR) if f.endswith(".tar.gz")),
        key=os.path.getmtime,
        reverse=True,
    )
    for old in files[KEEP_ARTIFACTS:]:
        try:
            os.remove(old)
            print(f"[清理] 旧部署包 {old}")
        except OSError:
            pass


def package(out_path: str) -> str:
    entries = [
        "routers",
        "services",
        "utils",
        "core",
        "pipeline",
        "tools",
        "training",
        "static",
        "scripts/backfill_school_level_pg.py",
        "scripts/execute_core_sql.py",
        "scripts/import_school_eval_pg.py",
        "scripts/sync_quiz_chapter_exercise.py",
        "scripts/_conn.py",
        "main.py",
        "app_lifecycle.py",
        "models.py",
        "database.py",
        "orm_aliases.py",
        "_version.py",
        "schemas.py",
        "migrate.py",
        "requirements.txt",
    ]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    count = 0
    with tarfile.open(out_path, "w:gz") as tar:
        for e in entries:
            p = os.path.join(BACKEND, e)
            if not os.path.exists(p):
                print(f"[警告] 缺少 {e}，跳过")
                continue
            tar.add(p, arcname=f"backend-main-fastapi/{e}", filter=_tar_filter)
            count += 1
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"打包完成：{out_path}（{count} 项，{size_mb:.1f} MB）")
    return out_path


def remote(ssh, cmd: str, check: bool = False) -> tuple[int, str]:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=300)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    code = stdout.channel.recv_exit_status()
    print(f"$ {cmd}\n--- exit={code}")
    if out:
        print(out[:2000])
    if err:
        print("[stderr]", err[:800])
    if check and code != 0:
        raise SystemExit(f"[中止] 服务器命令失败：{cmd}")
    return code, out


def _connect(host_key_policy: str):
    """SSH 连接：优先密钥，其次密码（均来自环境变量，不落盘）。

    host_key_policy: pin（默认，固定 known_hosts 指纹）/ auto（仅首次信任时用）
    """
    import paramiko

    cli = paramiko.SSHClient()
    cli.load_system_host_keys()
    known = os.path.expanduser("~/.ssh/known_hosts")
    if os.path.exists(known):
        cli.load_host_keys(known)
    if host_key_policy == "auto":
        print("[!] 使用 AutoAddPolicy（仅首次连接核对指纹时使用，之后请改 SSH_HOST_POLICY=pin）")
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        cli.set_missing_host_key_policy(paramiko.RejectPolicy())

    ssh_key = os.path.expanduser(os.environ.get("SSH_KEY", "~/.ssh/id_ed25519"))
    _pw = os.environ.get("SSH_PW", "").strip()
    kwargs = dict(timeout=25, banner_timeout=25, auth_timeout=25, allow_agent=False, look_for_keys=False)
    if _pw and not os.path.exists(ssh_key):
        cli.connect(HOST, username=DEPLOY_USER, password=_pw, **kwargs)
    else:
        cli.connect(HOST, username=DEPLOY_USER, key_filename=ssh_key, **kwargs)
    return cli


def main() -> int:
    package_only = "--package-only" in sys.argv
    dry_run = "--dry-run" in sys.argv
    sha = gen_version()
    bundle = os.path.join(ARTIFACT_DIR, f"kaoyan-deploy-{TS}-{sha}.tar.gz")
    package(bundle)
    _prune_artifacts()
    if package_only or dry_run:
        if dry_run:
            print("\n[dry-run] 后续将执行：")
            print("  1) 预检 df/systemctl")
            print("  2) 服务器备份 pre-%s.tar.gz" % TS)
            print("  3) static → static.prev（前端回滚点）")
            print("  4) 上传 + 原地解包")
            print("  5) execute_core_sql.py --all-pending")
            print("  6) restart + health（校验 git_sha=%s）" % sha)
        return 0

    policy = os.environ.get("SSH_HOST_POLICY", "pin").lower()
    cli = _connect(policy)
    try:
        # ---- 预检 ----
        remote(cli, "df -h / | tail -1 && systemctl is-active kaoyan", check=True)
        # ---- 后端备份 ----
        remote(
            cli,
            "mkdir -p /opt/kaoyan/backups && "
            "tar -czf /opt/kaoyan/backups/pre-" + TS + ".tar.gz "
            "--exclude='backend-main-fastapi/.venv' "
            "--exclude='backend-main-fastapi/data' "
            "--exclude='backend-main-fastapi/uploads' "
            "--exclude='backend-main-fastapi/logs' "
            "-C /opt/kaoyan backend-main-fastapi && "
            "ls -lh /opt/kaoyan/backups/pre-" + TS + ".tar.gz",
            check=True,
        )
        # ---- 前端回滚点：当前 static → static.prev（rollback.sh 约定）----
        # 必须在备份之后、解包之前：顺序错了 static.prev 就会是新产物。
        remote(
            cli,
            "cd /opt/kaoyan/backend-main-fastapi && "
            "if [ -d static ]; then rm -rf static.prev && mv static static.prev; fi && "
            "ls -d static.prev 2>/dev/null || true",
            check=True,
        )
        # ---- 上传 ----
        sftp = cli.open_sftp()
        remote_path = f"/opt/kaoyan/incoming-{TS}.tar.gz"
        print(f"上传 {bundle} → {remote_path} …")
        sftp.put(bundle, remote_path)
        sftp.close()
        print("上传完成")
        # ---- 原地解包（.venv/data/uploads 不在包内，不受影响）----
        remote(cli, f"tar xzf {remote_path} -C /opt/kaoyan && rm -f {remote_path}", check=True)
        remote(cli, "chown -R www-data:www-data /opt/kaoyan/backend-main-fastapi/static", check=True)
        # ---- 迁移：账本化一键收敛（替代手工插播 3 条 SQL）----
        remote(
            cli,
            "cd /opt/kaoyan/backend-main-fastapi && "
            "set -a && . /etc/kaoyan/backend.env && set +a && "
            "DEPLOY_TS=" + TS + " .venv/bin/python scripts/execute_core_sql.py --all-pending",
            check=True,
        )
        # ---- 120 auth_sessions：存量库无账本时 --all-pending 会 baseline 跳过新脚本，
        # 单文件补跑兜底（SQL 全部 IF NOT EXISTS，幂等，重复执行无害）----
        remote(
            cli,
            "cd /opt/kaoyan/backend-main-fastapi && "
            "set -a && . /etc/kaoyan/backend.env && set +a && "
            ".venv/bin/python scripts/execute_core_sql.py core/sql/120_auth_sessions.sql",
            check=True,
        )
        # ---- 120 school_branding：同上，cover_url 列单文件补跑（IF NOT EXISTS 幂等）----
        remote(
            cli,
            "cd /opt/kaoyan/backend-main-fastapi && "
            "set -a && . /etc/kaoyan/backend.env && set +a && "
            ".venv/bin/python scripts/execute_core_sql.py core/sql/120_school_branding.sql",
            check=True,
        )
        # ---- 幂等 QA schema（先 source 服务环境文件，不回显内容）----
        remote(
            cli,
            "cd /opt/kaoyan/backend-main-fastapi && "
            "set -a && . /etc/kaoyan/backend.env && set +a && "
            '.venv/bin/python -c "from database import SessionLocal; '
            "from services.qa_foundation import ensure_qa_schema; "
            "s=SessionLocal(); ensure_qa_schema(s); s.close(); print('qa schema ok')\"",
            check=True,
        )
        # ---- 重启 + 验证 ----
        remote(cli, "systemctl restart kaoyan && sleep 4 && systemctl is-active kaoyan", check=True)
        _, health = remote(cli, "curl -s 127.0.0.1:8000/api/health | head -c 400", check=True)
        # remote() 返回 (SSH退出码, stdout)，HTTP 码在 stdout——必须取第二个元素。
        # 此前误写成 code, _ = remote(...) 取到退出码（恒 0），校验恒打印「HTTP 0」形同虚设。
        _, code_home = remote(cli, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/")
        # 2026-11-20 访客扩容后口径：/api/documents 对访客只读开放（期望 200），
        # 个人数据 /api/tasks 仍默认拒绝（期望 401）——两条一起才证明门控没被放开过头。
        _, code_guest = remote(cli, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/api/documents")
        _, code_auth = remote(cli, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/api/tasks")
        print(f"首页 HTTP {code_home}（期望 200）；访客读 /api/documents HTTP {code_guest}（期望 200）；未登录 /api/tasks HTTP {code_auth}（期望 401）")
        for label, got, want in (
            ("首页", code_home, "200"),
            ("访客读 /api/documents", code_guest, "200"),
            ("未登录 /api/tasks", code_auth, "401"),
        ):
            if got != want:
                print(f"[警告] {label} HTTP {got} ≠ 期望 {want} —— 门控/静态可能异常，请查 journalctl 与 nginx，必要时 rollback.sh")
        # 2026-11-21 评审整改：/api/health 已脱敏（只回 status/version，零 DB 查询），
        # git_sha 移到鉴权的 /api/health/detail。这里只校验 status ok + version 存在。
        if '"ok"' not in health or '"version"' not in health:
            print("[警告] /api/health 未返回 status ok/version —— 服务可能未正常启动，请查 journalctl")
        remote(cli, "journalctl -u kaoyan -n 12 --no-pager | tail -12")
        print("\n[OK] 部署完成。回滚：bash deploy/rollback.sh backend|frontend（服务器上 /opt/kaoyan）")
    finally:
        cli.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
