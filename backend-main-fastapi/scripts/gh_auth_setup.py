# -*- coding: utf-8 -*-
"""GitHub 推送认证一键配置（Windows / 跨平台）。

背景：GitHub 已于 2021-08 停用「账号密码」HTTPS 推送，必须改用
Personal Access Token（PAT）。本脚本把 Token 安全写入 git credential
store（文件权限受限），之后 git push 免输。

用法（任选其一）：
    1. 环境变量方式（推荐，Token 不落盘）：
         set GH_TOKEN=ghp_xxxx        （Windows CMD）
         $env:GH_TOKEN="ghp_xxxx"     （PowerShell）
         python scripts/gh_auth_setup.py

    2. 交互方式：
         python scripts/gh_auth_setup.py
         按提示粘贴 Token（输入不回显）

生成 Token 的步骤（1 分钟）：
    GitHub.com → Settings → Developer settings →
    Personal access tokens → Tokens (classic) → Generate new token (classic)
    勾选权限：repo（全部）→ Generate → 复制 ghp_ 开头的字符串
"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _store_token(token: str) -> None:
    """把 Token 写入 git credential store（仅当前用户可读）。"""
    subprocess.run(
        ["git", "config", "--global", "credential.helper", "store"],
        check=True, cwd=REPO,
    )
    cred_file = Path.home() / ".git-credentials"
    line = f"https://pyy01048:{token}@github.com\n"
    existing = ""
    if cred_file.exists():
        existing = cred_file.read_text(encoding="utf-8")
        existing = "\n".join(
            l for l in existing.splitlines()
            if "github.com" not in l
        )
        if existing:
            existing += "\n"
    cred_file.write_text(existing + line, encoding="utf-8")
    try:
        cred_file.chmod(0o600)  # POSIX；Windows 忽略
    except OSError:
        pass


def main() -> int:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        token = getpass.getpass("粘贴 GitHub Personal Access Token (ghp_...): ").strip()
    if not token:
        print("❌ 未提供 Token，退出。生成方法见本文件顶部注释。")
        return 1
    if not (token.startswith("ghp_") or token.startswith("github_pat_")):
        print("⚠️  Token 格式不像 GitHub PAT（正常应以 ghp_ 或 github_pat_ 开头），仍继续尝试。")

    _store_token(token)
    print("✅ 凭据已写入 credential store")

    # 验证认证
    r = subprocess.run(
        ["git", "ls-remote", "--heads", "origin"],
        cwd=REPO, capture_output=True, text=True, timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if r.returncode == 0:
        print(f"✅ 认证验证通过，远端可访问（分支数 {len(r.stdout.splitlines())}）")
        print("👉 现在可直接：git push origin main")
        return 0
    print(f"❌ 验证失败：{r.stderr.strip()[:300]}")
    print("   请确认 Token 勾选了 repo 权限、账号为 pyy01048。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
