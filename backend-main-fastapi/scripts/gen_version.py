# -*- coding: utf-8 -*-
"""生成 backend-main-fastapi/_version.py（完善方案 09 §3.1）。

线上版本可追溯：git_sha + built_at 由管理员鉴权的 /api/health/detail 返回
（公开 /api/health 已脱敏只回 status/version），回答"线上跑的是哪个 commit"。
由 deploy/push_update.py 在打包前调用；_version.py 不入库（.gitignore）。

用法：
    python scripts/gen_version.py            # 写入 _version.py
    python scripts/gen_version.py --print    # 只打印，不落盘
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
TARGET = BACKEND / "_version.py"


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(BACKEND), *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001 —— 非 git 环境（源码包）返回空
        return ""


def build_version_module() -> str:
    sha = _git("rev-parse", "--short", "HEAD") or "unknown"
    dirty = ""
    if sha != "unknown" and _git("status", "--porcelain", "--untracked-files=no"):
        dirty = "-dirty"
    built_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    return (
        "# -*- coding: utf-8 -*-\n"
        '"""构建期自动生成，勿手工编辑（scripts/gen_version.py）。"""\n'
        f'GIT_SHA = "{sha}{dirty}"\n'
        f'GIT_BRANCH = "{branch}"\n'
        f'BUILT_AT = "{built_at}"\n'
        'VERSION = "3.0.0"\n'
    )


def main() -> int:
    content = build_version_module()
    if "--print" in sys.argv:
        print(content, end="")
        return 0
    TARGET.write_text(content, encoding="utf-8", newline="\n")
    print(f"已生成 {TARGET}")
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
