# -*- coding: utf-8 -*-
"""V3.12 评审整改 · 服务器侧加固（2026-11-21，push_update 之后执行）。

动作：
  1. nginx 站点配置替换（快速失败/429 JSON 壳/gzip/安全头/X-Request-ID）→ nginx -t → reload
  2. monitor_kaoyan.py 探活守护 → /opt/kaoyan/ + root crontab 每分钟
  3. systemd drop-in：PYTHONFAULTHANDLER=1（worker 静默死亡留栈）→ daemon-reload + restart
  4. 账号 B（15772585486）密码重置：新密码经环境变量 ACCOUNT_B_PW → SSH stdin，
     不落任何文件/命令行/日志。未提供该环境变量时跳过此步。

用法：
    ACCOUNT_B_PW='<密码>' python deploy/harden_20261121.py
连接：root + ~/.ssh/id_ed25519（与 push_update.py 同口径）。
"""

from __future__ import annotations

import os
import time

import paramiko

HOST = os.environ.get("SSH_HOST", "60.204.223.140")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY = os.path.join(BASE, "deploy")


def run(cli, cmd, check=True):
    _, stdout, stderr = cli.exec_command(cmd, timeout=180)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    print(f"$ {cmd}\n--- exit={code} ---")
    if out.strip():
        print(out[:2000])
    if err.strip():
        print("[stderr]", err[:800])
    if check and code != 0:
        raise SystemExit(f"[中止] 服务器命令失败：{cmd}")
    return code, out


def main() -> int:
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    key = os.path.expanduser(os.environ.get("SSH_KEY", "~/.ssh/id_ed25519"))
    cli.connect(
        HOST,
        username=os.environ.get("SSH_USER", "root"),
        key_filename=key,
        timeout=25,
        banner_timeout=25,
        auth_timeout=25,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        ts = int(time.time())
        nginx_bak = f"/etc/nginx/sites-available/kaoyan.bak-{ts}"
        sftp = cli.open_sftp()
        # 1) nginx 配置：先备份现有配置，校验失败可回滚
        run(
            cli,
            f"test -f /etc/nginx/sites-available/kaoyan && cp -a /etc/nginx/sites-available/kaoyan {nginx_bak} || true",
            check=False,
        )
        sftp.put(os.path.join(DEPLOY, "nginx-kaoyan.conf"), "/etc/nginx/sites-available/kaoyan")
        # 2) 监控脚本 + 账号重置脚本（无密钥内容）
        sftp.put(os.path.join(DEPLOY, "monitor_kaoyan.py"), "/opt/kaoyan/monitor_kaoyan.py")
        try:
            sftp.mkdir("/opt/kaoyan/incoming")
        except OSError:
            pass
        sftp.put(os.path.join(DEPLOY, "reset_account_b.py"), "/opt/kaoyan/incoming/reset_account_b.py")
        sftp.close()
        print("上传完成：nginx conf / monitor / reset_account_b")

        code, _ = run(
            cli, "ln -sf /etc/nginx/sites-available/kaoyan /etc/nginx/sites-enabled/kaoyan && nginx -t", check=False
        )
        if code != 0:
            run(
                cli,
                f"test -f {nginx_bak} && cp -a {nginx_bak} /etc/nginx/sites-available/kaoyan && nginx -t && systemctl reload nginx || true",
                check=False,
            )
            raise SystemExit(f"[中止] nginx -t 校验失败，已回滚到备份 {nginx_bak}")
        run(cli, "systemctl reload nginx && systemctl is-active nginx")

        # 监控 cron（幂等：先备份再删旧条目追加）
        run(cli, f"crontab -l > /opt/kaoyan/crontab.bak-{ts} 2>/dev/null || true", check=False)
        run(
            cli,
            "mkdir -p /opt/kaoyan/logs && "
            "( crontab -l 2>/dev/null | grep -v monitor_kaoyan.py ; "
            "echo '* * * * * /usr/bin/python3 /opt/kaoyan/monitor_kaoyan.py >> /opt/kaoyan/logs/monitor-cron.log 2>&1' ) | crontab - && "
            "crontab -l | grep monitor_kaoyan",
        )
        # 立即跑一次监控验证探活通路
        run(
            cli,
            "/usr/bin/python3 /opt/kaoyan/monitor_kaoyan.py; tail -3 /opt/kaoyan/logs/monitor.log 2>/dev/null || true",
            check=False,
        )

        # 3) faulthandler drop-in（幂等：已存在则跳过重启，避免重复执行无条件 restart）
        run(
            cli,
            "mkdir -p /etc/systemd/system/kaoyan.service.d && "
            "if grep -q PYTHONFAULTHANDLER /etc/systemd/system/kaoyan.service.d/faulthandler.conf 2>/dev/null; then "
            "echo '[跳过] faulthandler drop-in 已存在，不重启 kaoyan'; "
            "else printf '[Service]\\nEnvironment=PYTHONFAULTHANDLER=1\\n' > /etc/systemd/system/kaoyan.service.d/faulthandler.conf && "
            "systemctl daemon-reload && systemctl restart kaoyan && sleep 4 && systemctl is-active kaoyan; fi",
        )
        run(cli, "curl -s -m 8 127.0.0.1:8000/api/health")

        # 4) 账号 B 重置（密码走 stdin，不落盘/不回显）
        pw = os.environ.get("ACCOUNT_B_PW")
        if pw:
            stdin, stdout, stderr = cli.exec_command(
                "cd /opt/kaoyan/backend-main-fastapi && "
                "set -a && . /etc/kaoyan/backend.env && set +a && "
                ".venv/bin/python /opt/kaoyan/incoming/reset_account_b.py",
                timeout=60,
            )
            stdin.write(pw + "\n")
            stdin.flush()
            stdin.channel.shutdown_write()
            out = stdout.read().decode("utf-8", "replace")
            err = stderr.read().decode("utf-8", "replace")
            code = stdout.channel.recv_exit_status()
            print(f"$ reset_account_b（密码经 stdin）\n--- exit={code} ---")
            print(out[:500])
            if err.strip():
                print("[stderr]", err[:500])
            if code != 0:
                raise SystemExit("[中止] 账号 B 重置失败")
            run(
                cli,
                "shred -u /opt/kaoyan/incoming/reset_account_b.py 2>/dev/null || rm -f /opt/kaoyan/incoming/reset_account_b.py",
            )
        else:
            print("[跳过] 未提供 ACCOUNT_B_PW，账号 B 重置未执行")

        print("\n[OK] 服务器加固完成")
    finally:
        cli.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
