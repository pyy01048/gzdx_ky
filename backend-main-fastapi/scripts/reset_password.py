# -*- coding: utf-8 -*-
"""本机重置账号密码（锁死自救）。只在服务器 shell 里跑，不经网络。

    python scripts/reset_password.py pyy            # 生成随机临时密码
    python scripts/reset_password.py pyy --admin    # 账号不存在时建成管理员

重置后该账号所有已登录会话失效，下次登录强制改密。
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND, ".env"))

from database import Base, SessionLocal, engine  # noqa: E402
from models import User  # noqa: E402
from utils.security import ROLE_ADMIN, hash_password  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("username")
    ap.add_argument("--admin", action="store_true", help="账号不存在时以管理员身份创建")
    args = ap.parse_args()

    Base.metadata.create_all(bind=engine, tables=[User.__table__])
    temp = secrets.token_urlsafe(12)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == args.username).first()
        if user is None:
            if not args.admin:
                print(f"用户 {args.username} 不存在；要新建管理员请加 --admin", file=sys.stderr)
                return 1
            user = User(username=args.username, role=ROLE_ADMIN, display_name="管理员",
                        password_hash="", is_active=True, token_version=0)
            db.add(user)
        user.password_hash = hash_password(temp)
        user.must_change_password = True
        user.is_active = True
        user.token_version = int(user.token_version or 0) + 1
        if args.admin and user.role != ROLE_ADMIN:
            user.role = ROLE_ADMIN
        db.commit()
        role = user.role
    finally:
        db.close()
    print(f"{args.username}（{role}）临时密码：{temp}\n登录后会被要求立即修改。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
