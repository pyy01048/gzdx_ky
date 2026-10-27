# -*- coding: utf-8 -*-
"""学科统一注册器（M0-4 学科统一收口）。

### 为什么需要

科目字典 ``subject_config`` 表本应是**唯一权威**，但历史上 5 个 ``/subjects``
端点各查各的业务表（``quiz_questions`` / ``documents`` / ``knowledge_chunks``），
导致：

- 同一个"科目集合"在不同页面看到的不一样；
- 字典里配好、但还没录入数据的科目（如 0854 电子信息）在题库/资料页看不到；
- 业务表里出现过、但字典里没有的科目（如历史脏数据 "专业课"）会被静默漏掉。

本模块把这些口径收敛为**唯一聚合器**：以 ``subject_config`` 字典为骨架
（唯一权威，决定科目集合），叠加业务表实际出现的数据（计数），
不新增数据库列、不迁移数据（方案 A：零数据迁移）。

### 口径约定

- **科目集合** = ``subject_config`` 全部行
  + "业务表里出现过但字典里没有"的科目（以 ``unregistered=True`` 带出，**不漏数据**）。
- ``question_count``：``quiz_questions.subject`` 原值 group by 计数。
- ``error_count``：``error_records.subject`` 原值 group by 计数，仅 ``status='active'``。
- ``document_count``：``documents.subject`` 原值 group by 计数。

### 调用方

- ``routers/taxonomy.py``  GET /api/taxonomy/subjects
- ``routers/quiz.py``      GET /api/quiz/subjects
- ``routers/papers.py``    GET /api/papers/subjects
- ``routers/documents.py`` GET /api/documents/subjects
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Document, ErrorRecord, KnowledgeChunk, QuizQuestion, SubjectConfig
from services import taxonomy

# --------------------------------------------------------------------------- #
# 0854 / 工科学科兜底：确保工科（尤其 0854 电子信息）都在可选池。
#
# 说明：这些名字已加入 ``taxonomy.EXT_SUBJECTS``，因此**空库首建**时会由
# ``taxonomy.ensure_subject_config_seeds`` 一并播种。但存量真库
# （``subject_config`` 已非空、且建表时早于 M0-4）不会自动补进这 4 行，
# 故此处做一次**定向补种**：仅当表中"确实没有该名"时新增，
# 绝不覆盖、也不复活用户手动删过的其它内置科目。
# --------------------------------------------------------------------------- #
ENGINEERING_SUBJECTS: list[str] = [
    "电子信息",              # 0854 电子信息（专硕）—— 工科最常考的专业学位
    "信息与通信工程",        # 0810
    "计算机科学与技术",      # 0812
    "光学工程",              # 0803
    # 0808 电气工程 / 0809 电子科学与技术 / 0811 控制科学与工程 / 0835 软件工程
    # 已在 taxonomy.EXT_SUBJECTS / 真库 subject_config 中存在，无需补种。
]


def _count_by_subject(db: Session, column, exclude_junk: bool = True) -> dict[str, int]:
    """按科目列 group by 计数，过滤 NULL，返回 ``{subject: count}``。

    Args:
        db: SQLAlchemy 会话。
        column: 待分组的科目标签列（如 ``QuizQuestion.subject``）。
        exclude_junk: 当列为 ``QuizQuestion.subject`` 时，是否排除 OCR 碎片题
            （``is_junk = TRUE``）。默认 True——"各科目题数"与刷题列表口径一致。
            对非 QuizQuestion 列（Document/KnowledgeChunk）该参数无影响。

    Returns:
        科目名 → 记录数 的映射；NULL 科目不计入。
    """
    query = db.query(column, func.count()).filter(column.isnot(None))
    # M1-1h：题目科目计数排除碎片题（保持与列表/统计口径一致）
    if exclude_junk and getattr(column, "table", None) is QuizQuestion.__table__:
        from services.quiz_query import visible_quiz_filter

        query = visible_quiz_filter(query, include_junk=False)
    rows = query.group_by(column).all()
    return {name: int(cnt or 0) for name, cnt in rows}


def _active_error_counts(db: Session) -> dict[str, int]:
    """统计各科目**活跃**错题数（``error_records.status == 'active'``）。

    Args:
        db: SQLAlchemy 会话。

    Returns:
        科目名 → 活跃错题数 的映射。
    """
    rows = (
        db.query(ErrorRecord.subject, func.count(ErrorRecord.id))
        .filter(ErrorRecord.subject.isnot(None), ErrorRecord.status == "active")
        .group_by(ErrorRecord.subject)
        .all()
    )
    return {name: int(cnt or 0) for name, cnt in rows}


def ensure_subject_registry_seeds(db: Session) -> int:
    """幂等播种内置默认科目（含 0854 工科学科），确保可选池完整。

    两步：
    1. ``taxonomy.ensure_subject_config_seeds``：**仅空库**首建，播种
       ``taxonomy.ALL_SUBJECTS``（已含 0854 电子信息等 4 个新增工科）。
    2. ``_seed_missing_engineering_subjects``：对**存量非空库**定向补种
       M0-4 新增的 4 个工科科目（仅当表中确实没有该名时），不复活其它
       用户已删行。

    Args:
        db: SQLAlchemy 会话。

    Returns:
        本次新插入的种子行数。
    """
    # 先走 taxonomy 的标准播种（CORE + MAJOR + EXT 合并去重，仅空库生效）
    inserted = taxonomy.ensure_subject_config_seeds(db)
    # 存量非空库：定向补种 M0-4 新增工科（幂等，只补"名不存在"的项）
    inserted += _seed_missing_engineering_subjects(db)
    return inserted


def _seed_missing_engineering_subjects(db: Session) -> int:
    """在表已非空时，补播种**缺失的 M0-4 新增工科科目**。

    幂等且安全：只新增"字典里不存在"的工科科目名；已存在的不覆盖。
    复活防护由 subject_removals 墓碑表保证：用户删掉的工科科目记墓碑后，
    本函数跳过，不再复活（显式重建时清墓碑）。
    仅用于把 0854 电子信息等新科目纳入存量库的可选池。

    Args:
        db: SQLAlchemy 会话。

    Returns:
        新增行数。
    """
    existing = {row[0] for row in db.query(SubjectConfig.subject).all() if row[0]}
    # 删除墓碑：用户显式删掉的工科科目同样不复活（与 taxonomy 主播种同一口径）
    removed = taxonomy.load_subject_removals(db)
    added = 0
    for name in ENGINEERING_SUBJECTS:
        if name in existing or name in removed:
            continue
        db.add(SubjectConfig(
            subject=name,
            chapters=taxonomy.CHAPTERS.get(name, []),
            question_types=taxonomy.QUESTION_TYPES.get(name, taxonomy.DEFAULT_QUESTION_TYPES),
            is_custom=False,
        ))
        added += 1
    if added:
        db.commit()
        taxonomy.load_configured_subjects(db)
    return added


def list_subjects(db: Session, *, include_unregistered: bool = True) -> dict[str, Any]:
    """**唯一科目聚合器**：合并字典权威 + 业务表实际计数。

    Args:
        db: SQLAlchemy 会话。
        include_unregistered: 是否把"业务表里出现过但字典里没有"的科目
            以 ``unregistered=True`` 形式带出（默认 True，避免漏数据）。

    Returns:
        形如::

            {
              "subjects": [
                {
                  "subject": "数字电子技术",
                  "chapters": [...],
                  "question_types": [...],
                  "is_custom": False,
                  "unregistered": False,
                  "question_count": 3608,
                  "error_count": 22,
                  "document_count": 878,
                },
                ...
              ]
            }

        排序：内置默认（``is_custom=False``）在前，其次自定义，最后未登记项；
        组内按 subject 名称升序，保证各端点顺序一致。
    """
    # 1) 幂等播种（空库首建；存量非空库定向补 M0-4 新增工科，不复活其它已删行）
    ensure_subject_registry_seeds(db)

    # 2) 读字典全量行
    rows = (
        db.query(SubjectConfig)
        .order_by(SubjectConfig.is_custom.asc(), SubjectConfig.subject.asc())
        .all()
    )
    # 3) 刷新 normalize_subject 的"已配置科目"缓存
    taxonomy.load_configured_subjects(db)

    # 4) 业务表实际计数
    q_counts = _count_by_subject(db, QuizQuestion.subject)
    e_counts = _active_error_counts(db)
    d_counts = _count_by_subject(db, Document.subject)
    chunk_counts = _count_by_subject(db, KnowledgeChunk.subject)

    subjects: list[dict[str, Any]] = []
    known: set[str] = set()

    for r in rows:
        name = r.subject
        if not name:
            continue
        known.add(name)
        subjects.append({
            "subject": name,
            "chapters": r.chapters or [],
            "question_types": r.question_types or [],
            "is_custom": bool(r.is_custom),
            "unregistered": False,
            "question_count": q_counts.get(name, 0),
            "error_count": e_counts.get(name, 0),
            "document_count": d_counts.get(name, 0),
            "chunk_count": chunk_counts.get(name, 0),
        })

    # 5) 带出"业务表出现过但字典没有"的科目（不漏数据）
    if include_unregistered:
        extra: set[str] = set()
        extra.update(q_counts.keys())
        extra.update(e_counts.keys())
        extra.update(d_counts.keys())
        extra.update(chunk_counts.keys())
        extra -= known
        for name in sorted(extra):
            subjects.append({
                "subject": name,
                "chapters": taxonomy.chapters_of(name),
                "question_types": taxonomy.question_types_of(name),
                "is_custom": False,
                "unregistered": True,
                "question_count": q_counts.get(name, 0),
                "error_count": e_counts.get(name, 0),
                "document_count": d_counts.get(name, 0),
                "chunk_count": chunk_counts.get(name, 0),
            })

    return {"subjects": subjects}


def subject_filter_list(db: Session) -> list[str]:
    """返回"有实际数据"的科目名列表（供组卷/刷题筛选下拉，口径与注册器一致）。

    与 ``list_subjects`` 的科目集合一致，但只保留题目数 > 0 的科目，
    避免把空的字典项塞进筛选下拉。

    Args:
        db: SQLAlchemy 会话。

    Returns:
        科目名列表（按题目数降序）。
    """
    data = list_subjects(db)["subjects"]
    with_data = [s for s in data if s["question_count"] > 0]
    with_data.sort(key=lambda s: (-s["question_count"], s["subject"]))
    return [s["subject"] for s in with_data]


def unregistered_subjects(db: Session) -> list[str]:
    """返回业务表里出现过、但未登记进 subject_config 的科目名。

    供运维/前端提示"有数据但字典缺项"的可观测性用。

    Args:
        db: SQLAlchemy 会话。

    Returns:
        未登记科目名列表（升序）。
    """
    data = list_subjects(db)["subjects"]
    return sorted(s["subject"] for s in data if s.get("unregistered"))
