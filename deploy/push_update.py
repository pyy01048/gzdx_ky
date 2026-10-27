# -*- coding: utf-8 -*-
"""华为云服务器增量部署（60.204.223.140 · /opt/kaoyan）。

流程（对齐 deploy/DEPLOY.md）：
  1. 本地打包：后端代码 + static 前端产物（排除 .venv/data/uploads/logs/tests/__pycache__/.env）
  2. 服务器预检：磁盘 / 服务状态
  3. 服务器备份：/opt/kaoyan/backups/pre-<ts>.tar.gz（可回滚）
  4. 上传 + 原地解包（.venv / data / uploads 不受影响）
  5. 幂等 QA schema（ensure_qa_schema：answer_source 等列）
  6. systemctl restart kaoyan + 健康验证（health / 首页 / 401 鉴权 / journalctl）

用法：
    python deploy/push_update.py --package-only     # 只打包不上传
    $env:SSH_PW='<密码>'; python deploy/push_update.py   # 完整部署
回滚（服务器上执行）：
    cd /opt/kaoyan && tar xzf backups/pre-<时间戳>.tar.gz && systemctl restart kaoyan
"""
from __future__ import annotations

import os
import sys
import tarfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(BASE, "backend-main-fastapi")
HOST = os.environ.get("SSH_HOST", "60.204.223.140")

EXCLUDE_DIR_NAMES = {"__pycache__", ".venv", "data", "uploads", "logs",
                     "tests", "docs", ".pytest_cache", ".ocr_tmp",
                     ".pytest_tmp_fixed", "node_modules", "_eval_text_cache"}
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


def package(out_path: str) -> str:
    entries = ["routers", "services", "utils", "core", "pipeline", "tools",
               "training", "static",
               "scripts/backfill_school_level_pg.py",
               "scripts/execute_core_sql.py",
               "main.py", "models.py", "database.py", "orm_aliases.py",
               "schemas.py", "migrate.py", "requirements.txt"]
    count = 0
    with tarfile.open(out_path, "w:gz") as tar:
        for e in entries:
            p = os.path.join(BACKEND, e)
            if not os.path.exists(p):
                print(f"[警告] 缺少 {e}，跳过")
                continue
            tar.add(p, arcname=f"backend-main-fastapi/{e}", filter=_tar_filter)
            count += 1
    size_mb = os.path.getsize(out_path) / 1 / 1024 / 1024
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


def main() -> int:
    package_only = "--package-only" in sys.argv
    bundle = os.path.join(BASE, "deploy", f"kaoyan-deploy-{TS}.tar.gz")
    package(bundle)
    if package_only:
        return 0

    import paramiko

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_key = os.path.expanduser(os.environ.get("SSH_KEY", "~/.ssh/id_ed25519"))
    cli.connect(HOST, username=os.environ.get("SSH_USER", "root"), key_filename=ssh_key,
                timeout=25, banner_timeout=25, auth_timeout=25,
                allow_agent=False, look_for_keys=False)
    try:
        # ---- 预检 ----
        remote(cli, "df -h / | tail -1 && systemctl is-active kaoyan", check=True)
        # ---- 备份 ----
        remote(cli, "mkdir -p /opt/kaoyan/backups && "
                    "tar -czf /opt/kaoyan/backups/pre-" + TS + ".tar.gz "
                    "--exclude='backend-main-fastapi/.venv' "
                    "--exclude='backend-main-fastapi/data' "
                    "--exclude='backend-main-fastapi/uploads' "
                    "--exclude='backend-main-fastapi/logs' "
                    "-C /opt/kaoyan backend-main-fastapi && "
                    "ls -lh /opt/kaoyan/backups/pre-" + TS + ".tar.gz", check=True)
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
        # ---- 本轮迁移：用户隔离列 + 通知状态表 + 题目配图列 + 院校层级回填（先于重启，避免新 ORM 读到缺列）----
        remote(cli, "cd /opt/kaoyan/backend-main-fastapi && "
                    "set -a && . /etc/kaoyan/backend.env && set +a && "
                    ".venv/bin/python scripts/execute_core_sql.py core/sql/108_user_scope_columns.sql && "
                    ".venv/bin/python scripts/execute_core_sql.py core/sql/108_user_data_isolation.sql && "
                    ".venv/bin/python scripts/execute_core_sql.py core/sql/110_question_images.sql",
               check=True)
        remote(cli, "cd /opt/kaoyan/backend-main-fastapi && "
                    "set -a && . /etc/kaoyan/backend.env && set +a && "
                    ".venv/bin/python scripts/backfill_school_level_pg.py --apply",
               check=True)
        # ---- 幂等 QA schema（先 source 服务环境文件，不回显内容）----
        remote(cli, "cd /opt/kaoyan/backend-main-fastapi && "
                    "set -a && . /etc/kaoyan/backend.env && set +a && "
                    ".venv/bin/python -c \"from database import SessionLocal; "
                    "from services.qa_foundation import ensure_qa_schema; "
                    "s=SessionLocal(); ensure_qa_schema(s); s.close(); print('qa schema ok')\"",
               check=True)
        # ---- 重启 + 验证 ----
        remote(cli, "systemctl restart kaoyan && sleep 4 && systemctl is-active kaoyan", check=True)
        remote(cli, "curl -s 127.0.0.1:8000/api/health | head -c 300", check=True)
        code_home, _ = remote(cli, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/")
        code_auth, _ = remote(cli, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/api/documents")
        print(f"首页 HTTP {code_home}（期望 200）；未带 token 访问 /api/documents HTTP {code_auth}（期望 401）")
        remote(cli, "journalctl -u kaoyan -n 12 --no-pager | tail -12")
        print("\n✅ 部署完成。回滚命令（服务器上执行）：")
        print(f"  cd /opt/kaoyan && tar xzf backups/pre-{TS}.tar.gz && systemctl restart kaoyan")
    finally:
        cli.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
