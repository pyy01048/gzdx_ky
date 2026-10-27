# -*- coding: utf-8 -*-
"""备考科目配置：让"我到底考哪几科"成为可设置、可被全局读取的事实。

### 为什么需要

各处的科目口径原本散落硬编码：
- 进度统计按 `taxonomy.CORE_SUBJECTS`（写死的 6 科）
- AI 分科路由按科目名匹配
- 资料归类按 `taxonomy` 大纲

一旦你的科目组合变了（比如换成 408、或者加考信号与系统），
就得改代码。这个模块把它变成**用户可配置**，并给出建议默认值（一键填入，不自动生效）。

### 三个层次

| 层 | 含义 | 未配置时 |
|----|------|----------|
| 考试科目 | 你实际要考的，决定进度统计口径 | 空列表（不替你假设），core_defaults 只作为建议 |
| 支撑科目 | 可能涉及、要能查资料出题的 | 空列表，major_defaults 只作为建议 |
| 全部可识别 | 上面两者 + 拓展 | taxonomy.ALL_SUBJECTS（系统已知大纲的目录，与"你考什么"无关） |
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy.orm import Session

from models import Goal
from services import taxonomy
from utils.scope import scoped


def _scoped_uid(model, user_id: Optional[int]):
    """B4：user_id 形式的行级过滤。复用 scoped() 保持 USER_ISOLATION 开关
    语义一致（开关 off 或 user_id 为 None → 恒真 = 旧行为）。"""
    return scoped(model, SimpleNamespace(id=user_id))


def _goal(db: Session, user_id: Optional[int] = None) -> Optional[Goal]:
    """当前用户的目标行；user_id 为 None 时不过滤（旧脚本兼容）。"""
    return (
        db.query(Goal)
        .filter(_scoped_uid(Goal, user_id))
        .order_by(Goal.id.asc())
        .first()
    )


def get_config(db: Session, *, user_id: Optional[int] = None) -> dict[str, Any]:
    """读取备考科目配置（B4：user_id 提供时只读该用户的 Goal）。

    未配置时**返回空列表**，不再回填 taxonomy.CORE_SUBJECTS。
    历史行为是"没配就当你是考数电/模电那一批人"：整套内置科目被当成这位用户的
    备考科目下发给前端，于是进度分母、科目筛选、AI 画像全按某个人的专业方向跑，
    换一个人用就得改代码。CORE_SUBJECTS 的真实身份是**系统已知大纲的目录**
    （all_known / core_defaults），不是"你的科目"。
    页面用 using_default 区分两种状态：True=尚未配置（给出"使用建议科目"入口），
    False=用户显式配置过（哪怕配了 0 科也是他的决定）。
    """
    goal = _goal(db, user_id)

    exam = None
    support = None
    if goal:
        # 直接读 canonical 列名。`goal.subjects` 能用只是因为 orm_aliases.install()
        # 挂了 synonym，而那个别名层按 ADR-002 Phase 2 是要整体删掉的；
        # 更重要的是**脚本/测试入口不调 install()**，届时这里就是 AttributeError。
        if isinstance(goal.subject_codes, list) and goal.subject_codes:
            exam = [taxonomy.normalize_subject(s) for s in goal.subject_codes if s]
        if isinstance(goal.support_subject_codes, list) and goal.support_subject_codes:
            support = [taxonomy.normalize_subject(s) for s in goal.support_subject_codes if s]

    using_default = exam is None and support is None
    exam = exam or []
    support = support if support is not None else []

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
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    """写入备考科目配置。

    传空列表表示"该层清空"（不再回退内置默认）；传 None 表示不改这一层。
    user_id（B4）：新建 Goal 行落该归属；None = 旧行为（NULL）。
    """
    goal = _goal(db, user_id)
    if not goal:
        goal = Goal(user_id=user_id)
        db.add(goal)

    # 合法科目集合 = 内置池 ∪ 已注册自定义科目（subject_config 表里的）。
    # 历史 bug：只认 taxonomy.ALL_SUBJECTS 内置白名单，用户通过
    # POST /api/taxonomy/subjects 注册的自定义科目在这里被静默丢弃（返回 ignored），
    # 导致「设置页加了自定义科目却保存不进去」。现已放开。
    def _is_known(s: str) -> bool:
        return s in taxonomy.ALL_SUBJECTS or s in taxonomy._CONFIGURED_SUBJECTS

    if exam_subjects is not None:
        cleaned = [taxonomy.normalize_subject(s) for s in exam_subjects if (s or "").strip()]
        unknown = [s for s in cleaned if not _is_known(s)]
        cleaned = [s for s in cleaned if _is_known(s)]
        goal.subject_codes = list(dict.fromkeys(cleaned)) or None
        if unknown:
            db.commit()
            return {
                "message": "部分科目无法识别，已忽略（可先到「科目字典」注册自定义科目）",
                "ignored": unknown,
                **get_config(db, user_id=user_id),
            }

    if support_subjects is not None:
        cleaned = [taxonomy.normalize_subject(s) for s in support_subjects if (s or "").strip()]
        cleaned = [s for s in cleaned if _is_known(s)]
        goal.support_subject_codes = list(dict.fromkeys(cleaned)) or None

    db.commit()
    return {"message": "科目配置已保存", **get_config(db, user_id=user_id)}


def active_subjects(db: Session, *, user_id: Optional[int] = None) -> list[str]:
    """当前生效的全部科目（考试 + 支撑）。供路由/统计统一调用。"""
    return get_config(db, user_id=user_id)["active_subjects"]


def exam_subjects(db: Session, *, user_id: Optional[int] = None) -> list[str]:
    """当前生效的**考试口径**科目（进度统计用）。"""
    return get_config(db, user_id=user_id)["exam_subjects"]
