"""Pydantic 请求/响应模型。"""

import datetime
from typing import Any, Optional, List, Dict

from pydantic import BaseModel, ConfigDict, Field


# =========================================================================== #
# Goal
# =========================================================================== #
class GoalBase(BaseModel):
    exam_date: Optional[datetime.date] = None
    total_score_target: Optional[int] = None
    politics_target: Optional[int] = None
    english_target: Optional[int] = None
    math_target: Optional[int] = None
    major_target: Optional[int] = None
    university: Optional[str] = None
    major: Optional[str] = None
    remark: Optional[str] = None
    # 每日学习目标：仪表盘进度环的分母。None = 未设目标（进度环显示"未设目标"），
    # 不给默认值 —— 空库时前端不该看到凭空出现的数字。
    daily_focus_minutes: Optional[int] = Field(None, ge=1, le=1440)
    daily_new_words: Optional[int] = Field(None, ge=1, le=2000)
    daily_review_words: Optional[int] = Field(None, ge=1, le=5000)
    daily_questions: Optional[int] = Field(None, ge=1, le=2000)


class GoalCreate(GoalBase):
    pass


class GoalUpdate(GoalBase):
    pass


class GoalResponse(GoalBase):
    id: int
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# University
# =========================================================================== #
class UniversityBase(BaseModel):
    name: str
    type: Optional[str] = None
    city: Optional[str] = None
    major_name: Optional[str] = None
    score_lines: Optional[Dict[str, Any]] = None
    admission_ratio: Optional[str] = None
    difficulty: Optional[int] = None
    remark: Optional[str] = None


class UniversityCreate(UniversityBase):
    pass


class UniversityUpdate(UniversityBase):
    pass


class UniversityResponse(UniversityBase):
    id: int
    created_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# Task
# =========================================================================== #
class TaskBase(BaseModel):
    title: str
    subject: Optional[str] = None
    task_type: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = "pending"
    due_date: Optional[datetime.date] = None
    priority: Optional[int] = 0
    next_review: Optional[datetime.datetime] = None
    review_count: Optional[int] = 0


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    subject: Optional[str] = None
    task_type: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[datetime.date] = None
    priority: Optional[int] = None
    next_review: Optional[datetime.datetime] = None
    review_count: Optional[int] = None


class TaskResponse(TaskBase):
    id: int
    completed_at: Optional[datetime.datetime] = None
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# QuizQuestion
# =========================================================================== #
class QuizQuestionBase(BaseModel):
    content: str = Field(..., min_length=1)
    options: Optional[List[str]] = None
    images: Optional[List[Any]] = None
    answer: Optional[str] = None
    analysis: Optional[str] = None
    subject: Optional[str] = None
    chapter: Optional[str] = None
    knowledge_point: Optional[str] = None
    difficulty: Optional[int] = 3
    source: Optional[str] = None
    question_type: Optional[str] = "single"
    # —— 导入自动分类可信闸门（2026-10-14）——
    classify_confidence: Optional[float] = None
    classify_source: Optional[str] = None
    needs_review: Optional[bool] = None


class QuizQuestionCreate(QuizQuestionBase):
    pass


class QuizQuestionUpdate(BaseModel):
    content: Optional[str] = None
    options: Optional[List[str]] = None
    images: Optional[List[Any]] = None
    answer: Optional[str] = None
    analysis: Optional[str] = None
    subject: Optional[str] = None
    chapter: Optional[str] = None
    knowledge_point: Optional[str] = None
    difficulty: Optional[int] = None
    source: Optional[str] = None
    question_type: Optional[str] = None


class QuizQuestionResponse(QuizQuestionBase):
    id: int
    created_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
class QuizSubmit(BaseModel):
    question_id: int
    my_answer: str
    mode: Optional[str] = None
    cost_seconds: Optional[int] = 0
    # P0-2：主观题自评（不传时行为完全不变）
    self_score: Optional[float] = None
    max_score: Optional[float] = None


class QuizSubmitResult(BaseModel):
    question_id: int
    correct: bool
    correct_answer: Optional[str] = None
    analysis: Optional[str] = None


# =========================================================================== #
# ErrorRecord
# =========================================================================== #
class ErrorRecordBase(BaseModel):
    question_id: Optional[int] = None
    content: Optional[str] = None
    my_answer: Optional[str] = None
    correct_answer: Optional[str] = None
    error_reason: Optional[str] = None
    subject: Optional[str] = None
    accuracy: Optional[float] = 0
    review_count: Optional[int] = 0
    last_review: Optional[datetime.datetime] = None
    next_review: Optional[datetime.datetime] = None
    status: Optional[str] = "active"
    tags: Optional[List[str]] = None
    analysis: Optional[str] = None


class ErrorRecordCreate(ErrorRecordBase):
    # 空值校验（P0）：content/subject 为必填，空串直接 422，避免空错题落库。
    content: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)


class ErrorRecordUpdate(BaseModel):
    question_id: Optional[int] = None
    content: Optional[str] = None
    my_answer: Optional[str] = None
    correct_answer: Optional[str] = None
    error_reason: Optional[str] = None
    subject: Optional[str] = None
    accuracy: Optional[float] = None
    review_count: Optional[int] = None
    last_review: Optional[datetime.datetime] = None
    next_review: Optional[datetime.datetime] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None
    analysis: Optional[str] = None


class ErrorRecordResponse(ErrorRecordBase):
    id: int
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# StudySession
# =========================================================================== #
class StudySessionBase(BaseModel):
    date: datetime.date
    duration: Optional[int] = None
    subject: Optional[str] = None
    task_type: Optional[str] = None
    remark: Optional[str] = None


class StudySessionCreate(StudySessionBase):
    pass


class StudySessionResponse(StudySessionBase):
    id: int
    created_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# AIProvider
# =========================================================================== #
class AIProviderBase(BaseModel):
    name: str
    provider_type: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model_name: Optional[str] = None
    temperature: Optional[float] = 0.7
    is_default: Optional[bool] = False
    is_enabled: Optional[bool] = True
    fallback_priority: Optional[int] = 0


class AIProviderCreate(AIProviderBase):
    pass


class AIProviderUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    is_default: Optional[bool] = None
    is_enabled: Optional[bool] = None
    fallback_priority: Optional[int] = None


class AIProviderResponse(AIProviderBase):
    id: int
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# PlatformConfig
# =========================================================================== #
class PlatformConfigBase(BaseModel):
    platform_name: str
    token: Optional[str] = None
    app_key: Optional[str] = None
    secret_key: Optional[str] = None
    sync_enabled: Optional[bool] = False
    sync_frequency: Optional[str] = "daily"
    last_sync: Optional[datetime.datetime] = None
    extra: Optional[Dict[str, Any]] = None


class PlatformConfigCreate(PlatformConfigBase):
    pass


class PlatformConfigUpdate(BaseModel):
    platform_name: Optional[str] = None
    token: Optional[str] = None
    app_key: Optional[str] = None
    secret_key: Optional[str] = None
    sync_enabled: Optional[bool] = None
    sync_frequency: Optional[str] = None
    last_sync: Optional[datetime.datetime] = None
    extra: Optional[Dict[str, Any]] = None


class PlatformConfigResponse(PlatformConfigBase):
    id: int
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# NetdiskFile
# =========================================================================== #
class NetdiskFileBase(BaseModel):
    file_name: str
    path: Optional[str] = None
    file_type: Optional[str] = None
    size: Optional[int] = None
    category: Optional[str] = None
    download_link: Optional[str] = None
    play_progress: Optional[float] = 0
    fs_id: Optional[str] = None


class NetdiskFileCreate(NetdiskFileBase):
    pass


class NetdiskFileResponse(NetdiskFileBase):
    id: int
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# KnowledgePoint
# =========================================================================== #
class KnowledgePointBase(BaseModel):
    name: str
    subject: Optional[str] = None
    chapter: Optional[str] = None
    parent_id: Optional[int] = None
    mastery: Optional[int] = 0
    exam_frequency: Optional[int] = 0
    description: Optional[str] = None


class KnowledgePointCreate(KnowledgePointBase):
    pass


class KnowledgePointResponse(KnowledgePointBase):
    id: int
    created_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# Flashcard
# =========================================================================== #
class FlashcardBase(BaseModel):
    front: str
    back: str
    knowledge_point_id: Optional[int] = None
    next_review: Optional[datetime.datetime] = None
    review_count: Optional[int] = 0
    interval: Optional[int] = 1
    ease_factor: Optional[float] = 2.5
    mastery: Optional[str] = "new"


class FlashcardCreate(FlashcardBase):
    pass


class FlashcardBatchCreate(BaseModel):
    cards: List[FlashcardCreate]


class FlashcardReview(BaseModel):
    quality: int = Field(..., ge=0, le=5, description="复习质量评分 0-5")


class FlashcardResponse(FlashcardBase):
    id: int
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# Document
# =========================================================================== #
class DocumentBase(BaseModel):
    file_name: str
    file_path: Optional[str] = None
    file_type: Optional[str] = None
    size: Optional[int] = None
    index_status: Optional[str] = "pending"
    knowledge_point_count: Optional[int] = 0
    parse_progress: Optional[float] = 0
    content: Optional[str] = None


class DocumentResponse(DocumentBase):
    id: int
    subject: Optional[str] = None
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# CustomLink
# =========================================================================== #
class CustomLinkBase(BaseModel):
    name: str
    url: str
    category: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = 0


class CustomLinkCreate(CustomLinkBase):
    pass


class CustomLinkUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None


class CustomLinkResponse(CustomLinkBase):
    id: int
    created_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# StudyStats
# =========================================================================== #
class StudyStatsBase(BaseModel):
    date: datetime.date
    total_duration: Optional[int] = 0
    subject_durations: Optional[Dict[str, Any]] = None
    task_completed: Optional[int] = 0
    error_count: Optional[int] = 0
    new_knowledge_count: Optional[int] = 0


class StudyStatsResponse(StudyStatsBase):
    id: int
    created_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
# =========================================================================== #
# 通用响应
# =========================================================================== #
class GenericResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None
    data: Optional[Any] = None


class ChatMessage(BaseModel):
    role: str = Field(..., description="角色：user/assistant/system")
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    provider_id: Optional[int] = None
    use_rag: Optional[bool] = False
    use_routing: Optional[bool] = True  # 是否启用本地+API智能路由
    force_local: Optional[bool] = False  # 强制本地模式（绝不回退在线）
    provider_override: Optional[Dict[str, Any]] = None  # 前端直传服务商配置 {base_url, api_key, model, name, provider_type, temperature}
    # T4 电路读图通道：前端上传图片后回传的本地绝对路径（/api/ai/upload-image 返回）。
    # 由 /chat/router 注入上下文，Agentic 状态机识别后触发 circuit_analysis（qwen2.5vl 读图）
    image_path: Optional[str] = None


class RAGSearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 6
    subject: Optional[str] = None  # 学科过滤，如"数字电子技术"


class ChatResponse(BaseModel):
    content: str
    provider: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


class ExplainRequest(BaseModel):
    topic: str


class EssayGradeRequest(BaseModel):
    content: str
    type: str = Field("english", description="作文类型：english/chinese")


class SentenceAnalyzeRequest(BaseModel):
    sentence: str


class GeneratePlanRequest(BaseModel):
    goal: Optional[str] = None
    available_time: Optional[str] = None


class SummarizeTrendRequest(BaseModel):
    questions: Optional[List[str]] = None


class UniversitySearchRequest(BaseModel):
    keyword: Optional[str] = None
    city: Optional[str] = None
    type: Optional[str] = None


class AIAnalyzeErrorRequest(BaseModel):
    error_id: int


class AnalysisRequest(BaseModel):
    """通用题目分析请求（模块1：MathLens 式结构化分析 + HTML 讲义）。"""

    question: Optional[str] = None
    image_path: Optional[str] = None
    subject: Optional[str] = None
    prefer: Optional[str] = None


class LectureRequest(BaseModel):
    """生成 HTML 讲义请求。"""

    question: Optional[str] = None
    image_path: Optional[str] = None
    subject: Optional[str] = None
    prefer: Optional[str] = None
    analysis: Optional[dict] = None
