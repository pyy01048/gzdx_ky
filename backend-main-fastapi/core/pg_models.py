"""新版 SQLAlchemy 模型统一出口（对齐 core/pg_schema.sql）。

本文件**只做数据定义与导出**，不放任何业务逻辑。真正的字段定义按领域拆在
core/models/ 下（system / documents / knowledge / questions / learning /
schools / words_misc），原因是 60 张表放在单文件会远超 300 行上限。

使用方式：
    from core.pg_models import QuizQuestion, Subject
    from core.pg_models import Base, iter_models

    # 建表（仅 SQLite 降级模式推荐；PG 请走 core/db_session.apply_schema）
    Base.metadata.create_all(bind=engine)

与旧 models.py 的关系：
    旧 models.py 继续服务存量路由，本文件是迁移目标态。两者共用同一数据库，
    但 Base 不同，禁止在同一 Session 里混用两个 Base 的模型做关联查询。
"""

from __future__ import annotations

from typing import Iterator

from sqlalchemy.orm import DeclarativeMeta

from .models import (  # noqa: F401  —— 显式重导出，保证 from core.pg_models import X 可用
    AIProvider,
    AnnotationSample,
    AnswerCandidate,
    AnswerRecord,
    Base,
    BigIntPKMixin,
    ChunkVector,
    CustomLink,
    DailyPlan,
    DateTimeUTC,
    Discipline,
    EarlyBirdRecord,
    EbbinghausItem,
    ErrorKnowledgeLink,
    ErrorRecord,
    EvalRun,
    ExamAnswer,
    ExamBlueprint,
    ExamSession,
    Flashcard,
    FocusSession,
    Goal,
    KaoyanAdmission,
    KaoyanAlertRecord,
    KaoyanAlertRun,
    KaoyanCollectionRun,
    KaoyanCollege,
    KaoyanMajor,
    KaoyanMajorKbLink,
    KaoyanNotice,
    KaoyanSchool,
    KaoyanScoreline,
    KaoyanSubscription,
    KnowledgeChunk,
    KnowledgePoint,
    KnowledgePointRelation,
    Milestone,
    Misconception,
    MonthPlan,
    NAMING_CONVENTION,
    NetdiskFile,
    Paper,
    PaperQuestion,
    PendingQuestion,
    PlatformConfig,
    QuestionKnowledgeLink,
    QuizQuestion,
    RetrievalGateLog,
    ReviewRecord,
    ReviewSchedule,
    SchoolAlias,
    SftExample,
    StudyEvent,
    StudySession,
    StudyStat,
    Subject,
    SubjectAlias,
    SubjectChapter,
    SubjectConfig,
    SubjectDisciplineLink,
    SubjectPrototype,
    Task,
    TimestampMixin,
    TimestampedBigIntPKMixin,
    UniversityLegacy,
    WeekPlan,
    Word,
    WordDeck,
    utcnow,
)


def iter_models() -> Iterator[type]:
    """按定义顺序产出全部模型类，供建表 / 校验 / 自检使用。"""
    for mapper in Base.registry.mappers:
        yield mapper.class_


def model_names() -> list[str]:
    """全部模型类名，便于日志与自检输出。"""
    return sorted(model.__name__ for model in iter_models())


#: 迁移对照：新表 → 旧表（供 ETL 阶段生成映射脚本）
LEGACY_TABLE_MAP: dict[str, str] = {
    "subjects": "subject_config + subject_prototypes + kaoyan_subjects",
    "disciplines": "kaoyan_subjects",
    "subject_configs": "subject_config",
    "subject_chapters": "subject_config.chapters",
    "chunk_vectors": "knowledge_chunks_vec",
}


__all__ = [
    "Base",
    "iter_models",
    "model_names",
    "LEGACY_TABLE_MAP",
    "BigIntPKMixin", "TimestampMixin", "TimestampedBigIntPKMixin",
    "DateTimeUTC", "NAMING_CONVENTION", "utcnow",
    "Subject", "Discipline", "SubjectDisciplineLink", "SubjectAlias",
    "SubjectChapter", "SubjectConfig", "SubjectPrototype",
    "PlatformConfig", "AIProvider", "CustomLink",
    "Document", "KnowledgeChunk", "ChunkVector",
    "KnowledgePoint", "KnowledgePointRelation",
    "QuizQuestion", "QuestionKnowledgeLink", "Paper", "PaperQuestion",
    "ExamBlueprint", "ExamSession", "ExamAnswer", "PendingQuestion",
    "AnswerCandidate", "AnswerRecord",
    "ReviewSchedule", "Goal", "Task", "ReviewRecord", "ErrorRecord",
    "ErrorKnowledgeLink", "Flashcard", "FocusSession", "EbbinghausItem",
    "EarlyBirdRecord", "MonthPlan", "WeekPlan", "DailyPlan", "PhasePlan",
    "PhaseDailyReview", "StudySession", "StudyStat", "StudyEvent",
    "Milestone", "Misconception",
    "KaoyanSchool", "SchoolAlias", "KaoyanCollege", "KaoyanMajor",
    "KaoyanAdmission", "KaoyanScoreline", "KaoyanNotice",
    "KaoyanSubscription", "KaoyanAlertRecord", "KaoyanAlertRun",
    "KaoyanCollectionRun", "KaoyanMajorKbLink", "UniversityLegacy",
    "WordDeck", "Word", "NetdiskFile", "AnnotationSample",
    "SftExample", "EvalRun", "RetrievalGateLog",
]


# --------------------------------------------------------------------------- #
# 与旧 models.py 的类名兼容别名（2026-10-14）
# --------------------------------------------------------------------------- #
# 双轨迁移期，同一张表在两套体系里有两个类名，且拼写不一致：
#     kaoyan_scorelines : KaoyanScoreLine（旧） vs KaoyanScoreline（新）
#     sft_examples      : SFTExample（旧）    vs SftExample（新）
#     study_stats       : StudyStats（旧）    vs StudyStat（新）
# 这不是 bug，但很容易让人误以为是两个不同的实体。这里补别名，
# 让迁移期两种写法都能 import，且指向**同一个类对象**。
KaoyanScoreLine = KaoyanScoreline
SFTExample = SftExample
StudyStats = StudyStat

__all__ += ["KaoyanScoreLine", "SFTExample", "StudyStats"]
