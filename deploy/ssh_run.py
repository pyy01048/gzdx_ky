# -*- coding: utf-8 -*-
"""SSH 命令执行助手（部署用）。密码经环境变量 SSH_PW 传入，绝不落盘。

完善方案 08 §3.4：主机指纹固定校验（RejectPolicy）——
    * 首次连接先手工核对指纹：
        ssh-keyscan -t ed25519 <HOST> >> ~/.ssh/known_hosts
      并与云控制台/服务器 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 核对。
    * 仅首次临时放行：SSH_HOST_POLICY=auto（会打印警告），之后必须回到 pin。

用法：
    python deploy/ssh_run.py "cmd1" "cmd2" ...        # 逐条执行并回显
    type commands.txt | python deploy/ssh_run.py --stdin
环境变量：SSH_USER（默认 deploy）、SSH_PORT（22）、SSH_HOST、SSH_KEY、SSH_HOST_POLICY（pin|auto）。
"""

import os
import sys

import paramiko

HOST = os.environ.get("SSH_HOST", "60.204.223.140")
USER = os.environ.get("SSH_USER", "deploy")
PORT = int(os.environ.get("SSH_PORT", "22"))


def run(cmds: list[str]) -> None:
    key = os.path.expanduser(os.environ.get("SSH_KEY", "~/.ssh/id_ed25519"))
    if not os.path.exists(key):
        print(f"错误：未找到 SSH 密钥 {key}")
        raise SystemExit(2)
    cli = paramiko.SSHClient()
    cli.load_system_host_keys()
    known = os.path.expanduser("~/.ssh/known_hosts")
    if os.path.exists(known):
        cli.load_host_keys(known)
    if os.environ.get("SSH_HOST_POLICY", "pin").lower() == "auto":
        print("[!] 使用 AutoAddPolicy（仅首次核对指纹时使用）；请随后改为 pin")
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        cli.set_missing_host_key_policy(paramiko.RejectPolicy())
    cli.connect(
        HOST,
        port=PORT,
        username=USER,
        key_filename=key,
        timeout=25,
        banner_timeout=25,
        auth_timeout=25,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        for cmd in cmds:
            _, stdout, stderr = cli.exec_command(cmd, timeout=180)
            out = stdout.read().decode("utf-8", "replace")
            err = stderr.read().decode("utf-8", "replace")
            code = stdout.channel.recv_exit_status()
            print(f"$ {cmd}")
            print(f"--- exit={code} ---")
            if out.strip():
                print(out.rstrip())
            if err.strip():
                print("[stderr]", err.rstrip()[:1500])
            print()
    finally:
        cli.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--stdin":
        cmds = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    else:
        cmds = args
    run(cmds)
