"""模型分片聚合：按领域拆包，避免单文件超长。

分片与 core/sql/ 一一对应：
    system.py     —— 010 系统配置与科目权威源
    documents.py  —— 020 文档与知识分块
    knowledge.py  —— 030 知识点
    questions.py  —— 040 题目主表与其直接关联
    exams.py      —— 041 试卷 / 模考场次 / 作答 / 答疑待办
    learning.py   —— 050 复习调度 / 目标 / 任务 / 复习记录
    errors.py     —— 050 错题 / 错题-知识点关联 / 卡片
    planning.py   —— 051 计划体系 / 专注 / 艾宾浩斯 / 早起
    schools.py    —— 060 院校 / 学院 / 专业 / 招生 / 分数线
    notices.py    —— 061 通知 / 订阅 / 提醒 / 采集日志
    words_misc.py —— 070 单词 / 网盘 / 标注 / 评测

所有分片共用 core.models.base.Base，因此任意模块单独导入也不会丢元数据。
"""

from .base import (
    NAMING_CONVENTION,
    Base,
    BigIntPKMixin,
    DateTimeUTC,
    TimestampedBigIntPKMixin,
    TimestampMixin,
    utcnow,
)
from .code_oj import CodeProblem, CodeProblemTag, CodeProblemTestcase, CodeSubmission, CodeSubmissionResult, CodeTag
from .documents import ChunkVector, Document, KnowledgeChunk
from .errors import ErrorKnowledgeLink, ErrorRecord, Flashcard
from .exams import (
    AnswerCandidate,
    AnswerRecord,
    ExamAnswer,
    ExamBlueprint,
    ExamSession,
    PendingQuestion,
)
from .knowledge import KnowledgePoint, KnowledgePointRelation
from .learning import Goal, ReviewRecord, ReviewSchedule, Task
from .notices import (
    KaoyanAlertRecord,
    KaoyanAlertRun,
    KaoyanCollectionRun,
    KaoyanMajorKbLink,
    KaoyanNotice,
    KaoyanSubscription,
    NoticeUserState,
    UniversityLegacy,
)
from .planning import (
    DailyPlan,
    EarlyBirdRecord,
    EbbinghausItem,
    FocusSession,
    Milestone,
    Misconception,
    MonthPlan,
    PhaseDailyReview,
    PhasePlan,
    StudyEvent,
    StudySession,
    StudyStat,
    WeekPlan,
)
from .questions import Paper, PaperAnswer, PaperAttempt, PaperQuestion, QuestionKnowledgeLink, QuizQuestion
from .quiz_sessions import QuizAttempt, QuizSession
from .schools import (
    KaoyanAdmission,
    KaoyanCollege,
    KaoyanMajor,
    KaoyanSchool,
    KaoyanScoreline,
    KaoyanSubject,
    SchoolAlias,
)
from .system import (
    AIProvider,
    CustomLink,
    Discipline,
    PlatformConfig,
    Subject,
    SubjectAlias,
    SubjectChapter,
    SubjectConfig,
    SubjectDisciplineLink,
    SubjectPrototype,
)
from .words_misc import (
    AnnotationSample,
    EvalRun,
    NetdiskFile,
    RetrievalGateLog,
    SftExample,
    Word,
    WordDeck,
)

__all__ = [
    # base
    "Base",
    "BigIntPKMixin",
    "TimestampMixin",
    "TimestampedBigIntPKMixin",
    "DateTimeUTC",
    "NAMING_CONVENTION",
    "utcnow",
    # system
    "Subject",
    "Discipline",
    "SubjectDisciplineLink",
    "SubjectAlias",
    "SubjectChapter",
    "SubjectConfig",
    "SubjectPrototype",
    "PlatformConfig",
    "AIProvider",
    "CustomLink",
    # documents
    "Document",
    "KnowledgeChunk",
    "ChunkVector",
    # knowledge
    "KnowledgePoint",
    "KnowledgePointRelation",
    # questions
    "QuizQuestion",
    "QuestionKnowledgeLink",
    "Paper",
    "PaperQuestion",
    "PaperAnswer",
    "PaperAttempt",
    "QuizSession",
    "QuizAttempt",
    "ExamBlueprint",
    "ExamSession",
    "ExamAnswer",
    "PendingQuestion",
    "AnswerCandidate",
    "AnswerRecord",
    # learning
    "ReviewSchedule",
    "Goal",
    "Task",
    "ReviewRecord",
    "ErrorRecord",
    "ErrorKnowledgeLink",
    "Flashcard",
    "FocusSession",
    "EbbinghausItem",
    "EarlyBirdRecord",
    "MonthPlan",
    "WeekPlan",
    "DailyPlan",
    "PhasePlan",
    "PhaseDailyReview",
    "StudySession",
    "StudyStat",
    "StudyEvent",
    "Milestone",
    "Misconception",
    # schools
    "KaoyanSchool",
    "SchoolAlias",
    "KaoyanCollege",
    "KaoyanMajor",
    "KaoyanAdmission",
    "KaoyanScoreline",
    "KaoyanSubject",
    "KaoyanNotice",
    "KaoyanSubscription",
    "KaoyanAlertRecord",
    "KaoyanAlertRun",
    "KaoyanCollectionRun",
    "KaoyanMajorKbLink",
    "UniversityLegacy",
    "NoticeUserState",
    # words & misc
    "WordDeck",
    "Word",
    "NetdiskFile",
    "AnnotationSample",
    "SftExample",
    "EvalRun",
    "RetrievalGateLog",
    # code_oj
    "CodeProblem",
    "CodeTag",
    "CodeProblemTag",
    "CodeProblemTestcase",
    "CodeSubmission",
    "CodeSubmissionResult",
]
