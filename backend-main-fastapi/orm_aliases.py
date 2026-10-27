# -*- coding: utf-8 -*-
"""ORM 旧属性名兼容别名（ADR-002 / ADR-003 迁移遗留收口）。

背景
----
PostgreSQL canonical schema 对若干列做了改名（见下），models.py 已按新列名对齐。
但业务路由仍按**旧属性名**读写（如 `q.source` / `doc.file_type` / `kp.interval`）。
本模块在模型定义完成后补挂 synonym，使旧属性名透明指向新列：

    QuizQuestion.source           → source_label
    Document.file_type            → source_format
    Document.stage                → exam_stage
    KnowledgeChunk.chunk_id       → chunk_index
    KnowledgePoint.interval       → interval_days
    Flashcard.interval            → interval_days
    Word.interval                 → interval_days
    Goal.subjects                 → subject_codes
    Goal.support_subjects         → support_subject_codes
    SFTExample.user               → user_input

为什么用 synonym 而不是改业务代码
---------------------------------
改业务代码要动 6+ 个路由文件且易漏；synonym 让读写都走新列，**不存在双写漂移**。
待 ADR-002 Phase 2（移除兼容列）时连同本模块一起删除。

为什么单独成模块
----------------
`models.py` 需要 `from database import Base`，若在 database.py 里 import models 会
形成循环导入（实测：module 'models' has no attribute 'QuizQuestion'）。
独立模块由**业务入口**（main.py / 脚本）在 import models 之后调用 `install()`。
"""
from __future__ import annotations

import logging

#: 旧属性名 → 新列名
ALIASES: dict[str, list[tuple[str, str]]] = {
    "QuizQuestion": [("source", "source_label")],
    "Document": [("file_type", "source_format"), ("stage", "exam_stage")],
    "KnowledgeChunk": [("chunk_id", "chunk_index")],
    "KnowledgePoint": [("interval", "interval_days")],
    "Flashcard": [("interval", "interval_days")],
    "Word": [("interval", "interval_days")],
    "Goal": [("subjects", "subject_codes"), ("support_subjects", "support_subject_codes")],
    "SFTExample": [("user", "user_input")],
}

#: ORM 声明为 String、但 PG 实际是原生 ENUM 的列。
#:
#: 症状（实测）：`Task.status == "doing"` 在 PG 上抛
#:   `operator does not exist: task_status = character varying`
#: 因为 PG 原生枚举不能与 varchar 直接比较，psycopg 也不会自动转换。
#:
#: 修法：把列的**类型**换成带 native_enum 的 sqlalchemy.Enum，让 SQLAlchemy
#: 在绑定时 cast 成枚举类型。值的合法集合取自 000_extensions_and_enums.sql。
ENUM_COLUMNS: dict[str, dict[str, str]] = {
    "tasks": {"status": "task_status", "stage": "prep_stage"},
    "documents": {
        "doc_type": "doc_type", "content_category": "content_category",
        "exam_stage": "exam_stage", "structure_level": "structure_level",
        "index_status": "index_status", "source_kind": "source_kind",
        "source_format": "doc_format",
    },
    "knowledge_chunks": {"l3_content_type": "l3_content_type",
                         "classify_source": "classify_source"},
    "knowledge_points": {"extract_source": "extract_source"},
    "quiz_questions": {
        "question_type": "question_type", "answer_type": "answer_type",
        "source_kind": "source_kind", "confidence": "confidence_level",
        "quality": "quality_grade", "validation_status": "question_validation_status",
        "answer_source": "answer_source",
    },
    "flashcards": {"mastery": "mastery_level"},
    "review_records": {"result": "review_result"},
    "kaoyan_majors": {"degree_type": "degree_type"},
    "kaoyan_notices": {"notice_type": "notice_type",
                       "importance_level": "importance_level"},
    "kaoyan_subscriptions": {"level_min": "importance_level",
                             "scope": "subscription_scope"},
    "kaoyan_alert_records": {"alert_kind": "alert_kind"},
    "exam_sessions": {"question_source": "source_kind"},
    "exam_blueprints": {"blueprint_question_type": "question_type"},
    "error_records": {"mastery_level": "mastery_level"},
    "knowledge_point_relations": {"relation_type": "relation_type"},
    "subjects": {"category": "subject_category"},
    "words": {"status": "mastery_level"},
    "answer_candidates": {"source": "answer_source"},
    "textbooks": {"confidence": "confidence_level"},
}

logger = logging.getLogger(__name__)


def install() -> dict[str, list[str]]:
    """给受影响模型补挂旧属性名别名 + 枚举类型适配。幂等，可重复调用。"""
    from sqlalchemy.orm import synonym
    import models as M

    done: dict[str, list[str]] = {}
    for cls_name, pairs in ALIASES.items():
        cls = getattr(M, cls_name, None)
        if cls is None:
            logger.debug("兼容别名跳过：模型 %s 不存在", cls_name)
            continue
        table = cls.__table__
        for old, new in pairs:
            if new not in table.columns:
                logger.debug("兼容别名跳过 %s.%s→%s：目标列不存在", cls_name, old, new)
                continue
            if old in table.columns:
                # 旧名仍是实体列（如 SQLite 后端），无需别名
                continue
            if hasattr(cls, old):
                continue
            # 注意：descriptor 参数传**属性名字符串**会让 SQLAlchemy 试图把它当
            # property 取 __get__，实测报 "'str' object has no attribute '__get__'"。
            # 正确用法是只传目标属性名，让 synonym 自己解析。
            setattr(cls, old, synonym(new))
            done.setdefault(cls_name, []).append(f"{old}→{new}")

    # 枚举列类型适配（PG 后端才需要）
    enum_fixed = install_enum_types(M)
    done.update(enum_fixed)

    if done:
        logger.info("ORM 兼容别名与枚举适配已生效：%s", done)
    return done


def _load_pg_enum_labels() -> dict[str, list[str]]:
    """从 PG 元数据加载每个枚举类型的合法标签。

    必须提供真实值集合：若只传 name 而不传 values，SQLAlchemy 会拿枚举类型名去
    推断成员，绑定 `'smart_ingest'` 时抛
      `LookupError: 'smart_ingest' is not among the defined enum values`。
    """
    labels: dict[str, list[str]] = {}
    try:
        from database import engine
        from sqlalchemy import text as _t
        with engine.connect() as conn:
            rows = conn.execute(_t(
                "SELECT t.typname, e.enumlabel FROM pg_type t "
                "JOIN pg_enum e ON e.enumtypid = t.oid "
                "ORDER BY t.typname, e.enumsortorder"
            )).fetchall()
        for typname, label in rows:
            labels.setdefault(typname, []).append(label)
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载 PG 枚举标签失败，跳过枚举适配：%s", exc)
    return labels


def install_enum_types(M) -> dict[str, list[str]]:
    """把 ORM 里声明为 String 但 PG 为原生 ENUM 的列改成 Enum 兼容类型。

    为什么必须在 PG 后端做：PG 原生枚举**不能与 varchar 直接比较**，
    实测 `Task.status == "doing"` 抛
      `operator does not exist: task_status = character varying`，
    只要业务代码这么写页面就 500。改成 sqlalchemy.Enum 后，SQLAlchemy 会在
    绑定时生成 `%s::task_status` 强转，比较即可正常执行。

    SQLite 后端跳过：SQLite 侧本来就是 TEXT 列，改类型反而引入 CHECK 约束。
    """
    try:
        from database import IS_POSTGRES
    except Exception:  # noqa: BLE001
        return {}
    if not IS_POSTGRES:
        return {}

    enum_labels = _load_pg_enum_labels()
    if not enum_labels:
        return {}

    from sqlalchemy import Enum as SAEnum
    from sqlalchemy.types import TypeDecorator

    class _PgEnum(TypeDecorator):
        """PG 原生枚举绑定适配。

        - 绑定字符串时生成 `%s::<enum_name>`，使枚举与字符串可比
          （PG 原生枚举不能与 varchar 直接比较）；
        - 旧枚举值自动映射：业务代码仍用 SQLite 时代的旧值字面量
          （如 words.status='new'、flashcards.mastery='new'、review_records.result='fuzzy'），
          而 PG 枚举的合法集已按 canonical schema 换名
          （mastery_level: not_mastered/learning/reviewing/mastered；
           review_result: again/hard/good/easy）。不做映射会抛
          `invalid input value for enum mastery_level: "new"`。
        """

        impl = SAEnum
        cache_ok = True

        #: 旧值 → 新枚举值（跨表共用，键是"值"，与列无关）
        LEGACY_VALUE_MAP = {
            # mastery_level 系列
            "new": "not_mastered", "weak": "learning",
            "mastered": "reviewing", "review": "reviewing",
            # review_result 系列
            "fuzzy": "hard", "forgotten": "again",
            "good": "good", "easy": "easy", "again": "again", "hard": "hard",
            # 中文残留
            "未学": "not_mastered", "薄弱": "learning", "已掌握": "reviewing",
            "模糊": "hard", "不会": "again", "会": "good",
        }

        def __init__(self, *values, enum_name="", **kw):
            self._enum_name = enum_name
            self._valid = set(values)
            super().__init__(*values, name=enum_name, native_enum=True,
                             create_type=False, validate_strings=False, **kw)

        def process_bind_param(self, value, dialect):
            """把旧值映射成当前枚举的合法值，再交给 PG。"""
            if value is None or not self._enum_name:
                return value
            if value in self._valid:
                return value
            mapped = self.LEGACY_VALUE_MAP.get(str(value))
            if mapped and mapped in self._valid:
                return mapped
            # 映射不到就原样传，让 PG 给出明确错误（不静默改写成错误值）
            return value

        def process_result_value(self, value, dialect):
            return value

    out: dict[str, list[str]] = {}
    # ENUM_COLUMNS 的 key 是**表名**，需按 __tablename__ 反查映射类
    by_table = {}
    for attr_name in dir(M):
        obj = getattr(M, attr_name, None)
        tbl = getattr(obj, "__table__", None)
        if tbl is not None:
            by_table[tbl.name] = obj

    for table_name, col_map in ENUM_COLUMNS.items():
        cls = by_table.get(table_name)
        if cls is None:
            logger.debug("枚举适配跳过：表 %s 无对应映射类", table_name)
            continue
        table = cls.__table__
        for col_name, pg_enum in col_map.items():
            col = table.columns.get(col_name)
            if col is None:
                continue
            if isinstance(col.type, SAEnum):
                continue
            values = enum_labels.get(pg_enum)
            if not values:
                logger.debug("枚举适配跳过 %s.%s：PG 无此枚举 %s",
                             table_name, col_name, pg_enum)
                continue
            old_type = col.type
            col.type = _PgEnum(*values, enum_name=pg_enum)
            out.setdefault(cls.__name__, []).append(
                f"{col_name}: {type(old_type).__name__}→enum({pg_enum})"
            )
    return out
