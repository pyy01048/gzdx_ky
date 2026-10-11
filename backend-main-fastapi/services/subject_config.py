# -*- coding: utf-8 -*-
"""备考科目配置：让"我到底考哪几科"成为可设置、可被全局读取的事实。

### 为什么需要

各处的科目口径原本散落硬编码：
- 进度统计按 `taxonomy.CORE_SUBJECTS`（写死的 6 科）
- AI 分科路由按科目名匹配
- 资料归类按 `taxonomy` 大纲

一旦你的科目组合变了（比如换成 408、或者加考信号与系统），
就得改代码。这个模块把它变成**用户可配置**，且提供安全的默认值。

### 三个层次

| 层 | 含义 | 默认 |
|----|------|------|
| 考试科目 | 你实际要考的，决定进度统计口径 | 数电/模电/数学/英语/政治/真题 |
| 支撑科目 | 可能涉及、要能查资料出题的 | 电路/信号与系统/通信原理/光学与工程光学/普通物理/408 |
| 全部可识别 | 上面两者 + 拓展 | taxonomy.ALL_SUBJECTS |
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from models import Goal
from services import taxonomy


def _goal(db: Session) -> Optional[Goal]:
    return db.query(Goal).first()


def get_config(db: Session) -> dict[str, Any]:
    """读取备考科目配置（无配置则返回默认口径）。"""
    goal = _goal(db)

    exam = None
    support = None
    if goal:
        if isinstance(goal.subjects, list) and goal.subjects:
            exam = [taxonomy.normalize_subject(s) for s in goal.subjects if s]
        if isinstance(goal.support_subjects, list) and goal.support_subjects:
            support = [taxonomy.normalize_subject(s) for s in goal.support_subjects if s]

    using_default = exam is None
    exam = exam or list(taxonomy.CORE_SUBJECTS)
    support = support if support is not None else list(taxonomy.MAJOR_SUBJECTS)

    # 去重并保持顺序
    exam = list(dict.fromkeys(exam))
    support = [s for s in dict.fromkeys(support) if s not in exam]

    return {
        "exam_subjects": exam,
        "support_subjects": support,
        "active_subjects": exam + support,
        "all_known": list(taxonomy.ALL_SUBJECTS),
        "core_defaults": list(taxonomy.CORE_SUBJECTS),
        "major_defaults": list(taxonomy.MAJOR_SUBJECTS),
        "extension_subjects": list(taxonomy.EXT_SUBJECTS),
        "using_default": using_default,
        "subject_meta": {
            s: {
                "is_core": taxonomy.is_core(s),
                "is_major": taxonomy.is_major(s),
                "chapters": taxonomy.chapters_of(s),
                "question_types": taxonomy.question_types_of(s),
            }
            for s in dict.fromkeys(exam + support + list(taxonomy.EXT_SUBJECTS))
        },
    }


def set_config(
    db: Session,
    *,
    exam_subjects: Optional[list[str]] = None,
    support_subjects: Optional[list[str]] = None,
) -> dict[str, Any]:
    """写入备考科目配置。

    传空列表视为"清空该层"（回退默认）；传 None 表示不改这一层。
    """
    goal = _goal(db)
    if not goal:
        goal = Goal()
        db.add(goal)

    if exam_subjects is not None:
        cleaned = [taxonomy.normalize_subject(s) for s in exam_subjects if (s or "").strip()]
        # 只保留 taxonomy 认识的科目，避免写入垃圾值
        unknown = [s for s in cleaned if s not in taxonomy.ALL_SUBJECTS]
        cleaned = [s for s in cleaned if s in taxonomy.ALL_SUBJECTS]
        goal.subjects = list(dict.fromkeys(cleaned)) or None
        if unknown:
            db.commit()
            return {
                "message": "部分科目无法识别，已忽略",
                "ignored": unknown,
                **get_config(db),
            }

    if support_subjects is not None:
        cleaned = [taxonomy.normalize_subject(s) for s in support_subjects if (s or "").strip()]
        cleaned = [s for s in cleaned if s in taxonomy.ALL_SUBJECTS]
        goal.support_subjects = list(dict.fromkeys(cleaned)) or None

    db.commit()
    return {"message": "科目配置已保存", **get_config(db)}


def active_subjects(db: Session) -> list[str]:
    """当前生效的全部科目（考试 + 支撑）。供路由/统计统一调用。"""
    return get_config(db)["active_subjects"]


def exam_subjects(db: Session) -> list[str]:
    """当前生效的**考试口径**科目（进度统计用）。"""
    return get_config(db)["exam_subjects"]
