# -*- coding: utf-8 -*-
"""账号 B 密码重置（服务器侧执行，V3.12 评审 401 整改）。

新密码从 **stdin** 读取（一行），绝不写入本文件/命令行/日志。
用法（root SSH 通道内）：
    printf '%s' "$NEW_PW" | .venv/bin/python reset_account_b.py
重置后 token_version 自增（旧会话全部失效），must_change_password 清零。
"""

import sys
from pathlib import Path

# 约定从后端目录运行（见文件头用法）：Python 默认把脚本所在目录（而非 cwd）放进
# sys.path，必须前置 cwd，否则 from database import ... 会 ModuleNotFoundError。
sys.path.insert(0, str(Path.cwd()))

from database import SessionLocal  # noqa: E402
from utils.security import hash_password  # noqa: E402

from models import User  # noqa: E402

pw = sys.stdin.readline().strip()
if len(pw) < 8:
    print("[中止] stdin 未提供有效新密码（>=8 位）")
    raise SystemExit(2)

db = SessionLocal()
try:
    u = db.query(User).filter(User.username == "15772585486").first()
    if u is None:
        print("[中止] 未找到账号 15772585486")
        raise SystemExit(3)
    u.password_hash = hash_password(pw)
    u.token_version = int(u.token_version or 0) + 1
    u.must_change_password = False
    db.commit()
    print(f"[OK] 账号 B 密码已重置（id={u.id}），旧会话已全部失效")
finally:
    db.close()
