# -*- coding: utf-8 -*-
"""旧模型（models.py）的 ENUM 列在 PostgreSQL 下的自动类型对齐。

问题（2026-10 实测）
--------------------
项目采用「双模型体系」：旧 ``models.py`` 与新 ``core/models/``。
新体系用 ``build_enum()``（native_enum=True）正确声明 ENUM；
但旧 ``models.py`` 把这 26 个 ENUM 类型、34 个列**一律写成 String**：

    status = Column(String(50), default="pending")   # 实际列类型是 task_status

PostgreSQL 是强类型：``status = 'pending'`` 中字面量是 ``character varying``，
无法与 ``task_status`` 比较，直接报

    operator does not exist: task_status = character varying

SQLite 无类型约束，所以这个问题**只在 PG 上暴露**——这正是「双底座迁移
未完成」里最隐蔽的一类：代码看起来对，换库就挂。

危害链（实测）
--------------
``routers/insight.py`` 的 ``today_insight`` 前三个查询包了 try/except，
第四个 study_events 查询没有。当 ``get_today_tasks`` 因类型不匹配抛错后，
PG 事务已进入 aborted 状态（``InFailedSqlTransaction``），
**后续所有查询连带失败**，最终整个 ``/api/insight/today`` 返回 500。
首页核心接口因此完全不可用。

解决方案
--------
``PgEnumAware``：一个方言感知的类型。
  · PostgreSQL → 使用原生 ENUM 类型名（生成的 SQL 带 ::type_name 转换）
  · SQLite     → 降级为 VARCHAR（保持原行为，不破坏本地开发）

用法（替换 models.py 里的 String）：
    # 前
    status = Column(String(50), default="pending")
    # 后
    status = Column(PgEnumAware("task_status", 50), default="pending")

  · 必须传**真实的 PG ENUM 类型名**（见 core/pg_types.py 的 ENUM_CATALOG）
  · 类型名写错时：PG 下会在首次查询时报 undefined_object，属快速失败，可接受
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator, VARCHAR

# 枚举值缓存：优先用权威目录，缺失时运行时从 pg_enum 反射（兜底）。
_ENUM_VALUES_CACHE: dict = {}


def _resolve_enum_values(name: str) -> tuple:
    """解析某 PG 枚举类型的合法取值（按名缓存）。

    1) 先查 core.pg_types.ENUM_CATALOG（权威值表）；
    2) 兜底：从 pg_type/pg_enum 反射真实库中的枚举值。
    返回空元组（极少）时调用方仍不报错，仅放弃客户端校验（DB 端约束兜底）。
    """
    if name in _ENUM_VALUES_CACHE:
        return _ENUM_VALUES_CACHE[name]
    try:
        from core.pg_types import enum_values as _ev
        vals = tuple(_ev(name))
        _ENUM_VALUES_CACHE[name] = vals
        return vals
    except Exception:  # noqa: BLE001
        pass
    try:
        from database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT e.enumlabel FROM pg_type t JOIN pg_enum e "
                     "ON e.enumtypid = t.oid WHERE t.typname = :n"),
                {"n": name},
            ).fetchall()
            vals = tuple(r[0] for r in rows)
            _ENUM_VALUES_CACHE[name] = vals
            return vals
    except Exception:  # noqa: BLE001
        _ENUM_VALUES_CACHE[name] = ()
        return ()


class PgEnumAware(TypeDecorator):
    """方言感知的 ENUM 列类型：PG 用原生 ENUM，SQLite 退化为 VARCHAR。

    Args:
        enum_name: PostgreSQL 中已存在的 ENUM 类型名（如 "task_status"）。
        length: SQLite 降级时的 VARCHAR 长度，默认 50。
        **kwargs: 透传给底层类型（如 default / comment 由 Column 传，不在此处）。
    """

    impl = VARCHAR
    cache_ok = True

    def __init__(self, enum_name: str, length: int = 50, **kwargs):
        self.enum_name = enum_name
        super().__init__(length=length, **kwargs)

    def load_dialect_impl(self, dialect):
        """按方言选择底层实现类型。"""
        if dialect.name == "postgresql":
            # 交给 SQLAlchemy 的 Enum（原生 ENUM 类型名用于 DDL/强制转换）。
            # 关键：用**位置参数**把合法值显式传入，强制填充读取端的 _object_lookup，
            # 否则只传 name 时 SQLAlchemy 不建查找表，会把库里合法值（如 'single'）
            # 误判为「不在枚举值内」抛 LookupError，导致全库 34 个枚举列读取全崩
            # （2026-10-14 实测复现，且 name 单独传 values= 无效）。
            # validate_strings=False：放弃写入端冗余校验，DB 原生约束仍生效。
            from sqlalchemy.dialects.postgresql import ENUM
            vals = _resolve_enum_values(self.enum_name)
            if vals:
                return dialect.type_descriptor(
                    ENUM(*vals, name=self.enum_name, validate_strings=False))
            # 兜底：未知枚举且无值可查 → 退化为 varchar（读取返回字符串；写入由 DB 约束兜底）
            return dialect.type_descriptor(String(self.length))
        return dialect.type_descriptor(String(self.length))

    def process_bind_param(self, value, dialect):
        """写入：保持原值（PG ENUM 接受字符串字面量）。"""
        return value

    def process_result_value(self, value, dialect):
        """读出：PG 驱动返回字符串，直接透传。"""
        return value


#: 旧 models.py 中所有实为 ENUM 的列 → 真实 PG 类型名。
#: 数据来源：查询 pg_type + pg_attribute 得到的「DB 列真实类型」清单（2026-10 实测）。
#: 迁移时按 (表名, 列名) 查表，避免手工写错。
ENUM_COLUMNS: dict[tuple[str, str], str] = {
    ("subjects", "category"): "subject_category",
    ("subject_prototypes", "engine"): "vector_engine",
    ("documents", "source_format"): "doc_format",
    ("documents", "doc_type"): "doc_type",
    ("documents", "content_category"): "content_category",
    ("documents", "exam_stage"): "exam_stage",
    ("documents", "structure_level"): "structure_level",
    ("documents", "index_status"): "index_status",
    ("documents", "source_kind"): "source_kind",
    ("knowledge_chunks", "l3_content_type"): "l3_content_type",
    ("knowledge_chunks", "classify_source"): "classify_source",
    ("chunk_vectors", "engine"): "vector_engine",
    ("knowledge_points", "extract_source"): "extract_source",
    ("textbooks", "confidence"): "confidence_level",
    ("knowledge_point_relations", "relation_type"): "relation_type",
    ("quiz_questions", "quality"): "quality_grade",
    ("quiz_questions", "question_type"): "question_type",
    ("quiz_questions", "confidence"): "confidence_level",
    ("quiz_questions", "source_kind"): "source_kind",
    ("paper_questions", "question_type"): "question_type",
    ("exam_blueprints", "blueprint_question_type"): "question_type",
    ("exam_sessions", "question_source"): "source_kind",
    ("tasks", "status"): "task_status",
    ("tasks", "stage"): "prep_stage",
    ("error_records", "mastery_level"): "mastery_level",
    ("flashcards", "mastery"): "mastery_level",
    ("words", "status"): "mastery_level",
    ("review_records", "result"): "review_result",
    ("kaoyan_majors", "degree_type"): "degree_type",
    ("kaoyan_notices", "importance_level"): "importance_level",
    ("kaoyan_notices", "notice_type"): "notice_type",
    ("kaoyan_subscriptions", "level_min"): "importance_level",
    ("kaoyan_subscriptions", "scope"): "subscription_scope",
    ("textbook_schools", "exam_stage"): "exam_stage",
    ("annotation_samples", "label_l3"): "l3_content_type",
}
