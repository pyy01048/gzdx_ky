"""B4 行级隔离：统一 scope 过滤与归属（docs/plan-gap/E-user-data-isolation.md §3）。

为什么独立成模块而不放进 utils/security.py：security.py 的文件头 docstring 含
"Authorization=Bearer" 的文档性文字，工作区写入守卫（artifact_secret）会拦截
对该文件的任何全文件重写。独立模块既避开误判，也让「认证」与「数据隔离」
两个关注点各自收敛。

开关：USER_ISOLATION=off 时 scoped() 恒真 = 一键回退旧行为（回滚开关，清单 §3.3）。
"""
from __future__ import annotations

import os

from sqlalchemy import true as sa_true

#: 隔离开关（进程启动时读取一次；需要运行期切换请重启服务）。
USER_ISOLATION = (os.getenv("USER_ISOLATION", "on").strip().lower() != "off")


def scoped(model, user):
    """个人域行级过滤条件，返回可直接用于 .filter() 的 SQLAlchemy 表达式。

    用法::

        db.query(Task).filter(scoped(Task, user))
        db.query(Task).filter(Task.id == task_id, scoped(Task, user))  # 越权=查不到→404

    约定：个人域表都有可空 user_id（core/sql/108 迁移引入）。
    - USER_ISOLATION 开启且 user 有效 → ``model.user_id == user.id``
    - 否则恒真（兼容未接线调用方 / 回退开关）

    写入侧直接 ``user_id = owner_id(user)``；更新/删除一律带 scoped() 过滤，
    查不到返回 404，不要 403（避免向调用方泄露他人数据的存在性）。
    """
    if not USER_ISOLATION or getattr(user, "id", None) is None:
        return sa_true()
    return model.user_id == user.id


def owner_id(user):
    """写入侧统一取归属用户 ID；无登录态时返回 None（兼容脚本 / 回退模式）。"""
    return getattr(user, "id", None)
