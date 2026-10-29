"""SQLAlchemy ORM 模型定义。"""

import datetime
from sqlalchemy import (
    BigInteger, Column, Integer, SmallInteger, String, Text, Float, Boolean, DateTime, Date, Time,
    ForeignKey, JSON, Index, LargeBinary, UniqueConstraint, text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship, synonym
from sqlalchemy.types import TypeDecorator

from database import Base
from core.pg_enum_aware import PgEnumAware
from utils.secret_codec import EncryptedText


class NullSafeJSON(TypeDecorator):
    """None 绑定为 SQL NULL（而非 JSON 标量 'null'）的 JSONB 列类型。

    背景（2026-10-15 实测）：SQLAlchemy 通用 ``JSON`` 列在 PG 方言下经
    ``dialect_impl`` 委托给 ``postgresql.JSON``，其 bind_processor 会把
    Python None 包成 ``Json(None)``，psycopg 序列化成 JSON 字面量 ``'null'``——
    一个**标量**。quiz_questions 的 BEFORE INSERT 触发器
    ``validate_question_row()`` 对 options 调 ``jsonb_array_length``，
    遇到标量直接抛 "cannot get array length of a scalar"，
    任何 options=None 的 ORM 插入必炸（潜藏 bug，前端一直传 [] 才没暴露）。
    
    2026-10-17 修正：改用 postgresql.JSONB 作为 impl，与 SQL schema (040_questions.sql)
    和 quiz_query 中的 jsonb_typeof/jsonb_array_length 等函数保持一致。
    本类型在绑定时短路 None → SQL NULL，与库里既有 NULL 语义一致。

    注意：不能靠继承 ``JSON`` 重写 bind_processor——``dialect_impl()`` 会返回
    PG 方言的专用类型对象，子类方法根本不会被调用（实测验证过）。
    """

    impl = postgresql.JSONB
    cache_ok = True

    def bind_processor(self, dialect):
        impl_processor = self.impl_instance.bind_processor(dialect)

        def process(value):
            if value is None:
                return None  # SQL NULL，不走 JSON 序列化
            # 容错：把「字符串形态的 JSON」解成真结构。
            # 历史上调用方会写 options='["A","B"]'（字符串）——直接入库会变成
            # JSON **字符串标量**，触发器 jsonb_array_length 立刻报
            # "cannot get array length of a scalar"（实测 12 例）。
            # 这里就地解析，既兼容旧调用方，也避免脏结构落库。
            if isinstance(value, (str, bytes)):
                import json as _json
                parsed = None
                try:
                    parsed = _json.loads(value)
                except Exception:  # noqa: BLE001 - 非 JSON 文本，走下面的规整
                    parsed = None
                if isinstance(parsed, (list, dict)):
                    value = parsed
                else:
                    # 纯文本选项（如 "A、甲 B、乙"）也必须落成**正典结构**，
                    # 否则入库是 JSON 字符串标量，触发器 jsonb_array_length
                    # 直接报 "cannot get array length of a scalar"。
                    # 规整逻辑收敛到 services.content_sanitizer（全站单一来源），
                    # 不在模型层另写一套。
                    try:
                        from services.content_sanitizer import normalize_options

                        opts, _issues = normalize_options(
                            value.decode("utf-8", "ignore") if isinstance(value, bytes) else value
                        )
                        if len(opts) >= 2:
                            value = opts
                    except Exception:  # noqa: BLE001 - 规整失败按原样交给 impl
                        pass
            # 容错：dict 形态的选项（{"A": "...", "B": "..."}）规整为正典数组
            # [{key,text}]。触发器 jsonb_array_elements 只认数组，dict 直接落库
            # 会报 "cannot get array length of a non-array"（实测）。生产库
            # options 100% 为 array，此处兼容历史调用方的 dict 写法。
            if isinstance(value, dict) and value:
                try:
                    value = [
                        {"key": str(k).strip().upper()[:1], "text": str(v)}
                        for k, v in value.items()
                        if str(v).strip()
                    ]
                except Exception:  # noqa: BLE001 - 规整失败按原样交给 impl
                    pass
            # 容错：**纯字符串数组**（["A、触发器", "B、译码器", ...]）也要
            # 规整为正典 [{key,text}]。DB 的 ck_quiz_questions_options CHECK 调
            # is_canonical_options()，字符串数组过不了；报错长这样：
            #   new row violates check constraint "ck_quiz_questions_options"
            # 触发场景：知识库候选题抽取（/api/kb-import/confirm）返回的就是
            # 字符串数组，导致该端点 500（实测 1 例）。
            # 同样收敛到 content_sanitizer.normalize_options，不另写一套。
            if (
                isinstance(value, (list, tuple))
                and value
                and all(isinstance(x, str) for x in value)
            ):
                try:
                    from services.content_sanitizer import normalize_options

                    opts, _issues = normalize_options(list(value))
                    if len(opts) >= 2:
                        value = opts
                except Exception:  # noqa: BLE001 - 规整失败按原样交给 impl
                    pass
            return impl_processor(value) if impl_processor else value

        return process


class RawJSON(TypeDecorator):
    """**任意** JSON 结构的 JSONB 列：None → SQL NULL，其余原样落库。

    为什么不能直接用 :class:`NullSafeJSON`
    ------------------------------------
    ``NullSafeJSON`` 是**为 quiz_questions.options 设计的**：它的 bind_processor
    会把「字符串形态的 JSON」「dict 形态的选项」「字符串数组」一律规整成
    **选项数组** ``[{"key": "A", "text": "..."}]``。于是任何**普通 dict**
    都会被改写：

        {"math_corrupted": True}  →  [{"key": "M", "text": "True"}]

    实测踩坑（2026-10-20）：``document_blocks.extra`` 用 NullSafeJSON 时，
    落库后变成 list，读取时 ``row.extra.get(...)`` 直接 AttributeError。

    本类型只做一件事：``None`` 短路成 SQL NULL（与库里既有 NULL 语义一致），
    **不对内容做任何规整**。给 bbox / layout_json / extra / payload 这类
    「结构由调用方决定」的列用。
    """

    impl = postgresql.JSONB
    cache_ok = True

    def bind_processor(self, dialect):
        impl_processor = self.impl_instance.bind_processor(dialect)

        def process(value):
            if value is None:
                return None  # SQL NULL，不走 JSON 序列化
            return impl_processor(value) if impl_processor else value

        return process


def _utcnow():
    """timezone-aware 当前 UTC 时间（替代已弃用的 datetime.utcnow）。"""
    return datetime.datetime.now(datetime.timezone.utc)


# --------------------------------------------------------------------------- #
# 考研目标
# --------------------------------------------------------------------------- #
class Goal(Base):
    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, index=True)
    # B4 行级隔离：归属用户。NULL=迁移前存量（回填后归主账号）/ 未接线写入。
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    exam_date = Column(Date, nullable=True, comment="考试日期")
    total_score_target = Column(Integer, nullable=True, comment="总分目标")
    politics_target = Column(Integer, nullable=True, comment="政治目标分")
    english_target = Column(Integer, nullable=True, comment="英语目标分")
    math_target = Column(Integer, nullable=True, comment="数学目标分")
    major_target = Column(Integer, nullable=True, comment="专业课目标分")
    university = Column(String(200), nullable=True, comment="目标院校")
    major = Column(String(200), nullable=True, comment="目标专业")
    #: 用户实际备考的科目列表（JSON 数组）。
    #: **为空 = 尚未配置**，故意不回退到 taxonomy.CORE_SUBJECTS：那是"系统已知大纲的目录"，
    #: 把它当某个人的备考科目下发，进度分母与 AI 画像就会凭空假设专业方向。
    #: 用途：进度统计口径、AI 分科路由、资料归类、出题范围。
    subject_codes = Column(JSON, nullable=True, comment="备考科目列表 JSON")
    #: 专业课支撑科目（可能涉及但未必考的，如 408/信号与系统）
    support_subject_codes = Column(JSON, nullable=True, comment="专业课支撑科目 JSON")
    # 每日学习目标（仪表盘进度环的分母）。**可空 = 未设目标**，故意不给默认值：
    # 空库新用户不该看到凭空出现的 50/20/120。DDL 与 CHECK 见 core/sql/101。
    daily_focus_minutes = Column(SmallInteger, nullable=True, comment="每日专注时长目标（分钟），NULL=未设")
    daily_new_words = Column(SmallInteger, nullable=True, comment="每日新词目标，NULL=未设")
    daily_review_words = Column(SmallInteger, nullable=True, comment="每日复习词量目标，NULL=未设")
    daily_questions = Column(SmallInteger, nullable=True, comment="每日刷题目标，NULL=未设")
    remark = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# --------------------------------------------------------------------------- #
# 院校信息
# --------------------------------------------------------------------------- #
# 任务
# --------------------------------------------------------------------------- #
class ReviewSchedule(Base):
    """复习调度权威表（FSRS / SM-2 共用）。

    物理表由 core/sql/050_learning.sql 建立；本类为业务侧读写入口。
    - algorithm=fsrs 时以 stability / difficulty / state 为准
    - algorithm=sm2 时继续读 ease_factor / interval_days
    """
    __tablename__ = "review_schedules"

    id = Column(Integer, primary_key=True, index=True)
    # B4 行级隔离：同一道错题/卡片/单词，不同用户各自有独立的调度行。
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    item_type = Column(String(30), nullable=False, index=True,
                       comment="复习对象：word/flashcard/error_record/knowledge_point")
    item_id = Column(Integer, nullable=False, index=True)
    algorithm = Column(String(30), nullable=False, default="sm2", server_default="sm2")
    ease_factor = Column(Float, nullable=False, default=2.5, server_default="2.5")
    interval_days = Column(Integer, nullable=False, default=0, server_default="0")
    repetitions = Column(Integer, nullable=False, default=0, server_default="0")
    lapses = Column(Integer, nullable=False, default=0, server_default="0")
    # FSRS 三要素（102 迁移新增）
    stability = Column(Float, nullable=True, comment="FSRS 稳定度（天）")
    difficulty = Column(Float, nullable=True, comment="FSRS 难度 1-10")
    retrievability = Column(Float, nullable=True, comment="本次复习时的可提取概率")
    state = Column(SmallInteger, nullable=True, default=0, server_default="0",
                   comment="0新 1学习 2复习 3重学")
    last_reviewed_at = Column(DateTime, nullable=True)
    next_review_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        # B4：唯一键从 (item_type,item_id) 放宽到含 user_id（同一路径 SQL 108 同步重建）
        UniqueConstraint("user_id", "item_type", "item_id", name="uq_review_schedule"),
    )


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    title = Column(String(300), nullable=False, comment="任务标题")
    subject = Column(String(50), nullable=True, comment="科目：政治/英语/数学/专业课")
    task_type = Column(String(50), nullable=True, comment="类型：学习/复习/刷题/背诵/模拟")
    stage = Column(PgEnumAware("prep_stage", 50), nullable=True, comment="阶段：基础/强化/冲刺")
    status = Column(PgEnumAware("task_status", 50), default="pending", comment="状态：pending/doing/done")
    due_date = Column(Date, nullable=True, comment="截止日期")
    priority = Column(Integer, default=0, comment="优先级 0-5")
    next_review = Column(DateTime, nullable=True, comment="艾宾浩斯下次复习时间")
    review_count = Column(Integer, default=0, comment="已复习次数")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# --------------------------------------------------------------------------- #
# 题目
# --------------------------------------------------------------------------- #
class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False, comment="题干")
    options = Column(NullSafeJSON, nullable=True, comment="选项 JSON")
    # 题目配图：OCR/人工录入产出的图片引用数组，元素可为 URL/相对路径/对象
    # （{url,page,bbox,kind}）。前端按数组顺序渲染；空数组表示无图。
    images = Column(NullSafeJSON, nullable=True, comment="题目配图 JSON")
    answer = Column(Text, nullable=True, comment="正确答案")
    analysis = Column(Text, nullable=True, comment="解析")
    subject = Column(String(50), nullable=True, index=True, comment="科目")
    chapter = Column(String(200), nullable=True, comment="章节")
    knowledge_point = Column(String(200), nullable=True, comment="知识点")
    difficulty = Column(Integer, default=3, comment="难度 1-5")
    source_label = Column(String(200), nullable=True, comment="来源：真题/模拟/自建/ai:variant")
    question_type = Column(PgEnumAware("question_type", 50), default="single", comment="题型：single/multiple/judge/essay")
    # —— 题库流水线升级（2026-10）：AI 生成标注 + 变式题分组 —— #
    ai_generated = Column(Boolean, default=False, comment="答案解析是否为 AI 生成")
    verified = Column(Boolean, default=False, comment="AI 生成答案是否经过人工/多角色校验确认")
    variant_group = Column(String(50), nullable=True, index=True, comment="相似题/变式题组 ID（同一组内为近似题）")
    # —— V4.0 遗留补列（2026-10）：真题来源与质量体系 —— #
    year = Column(Integer, nullable=True, index=True, comment="真题年份")
    paper = Column(String(100), nullable=True, comment="试卷标识（如 2026全国卷）")
    external_id = Column(String(100), nullable=True, unique=True, comment="外部题目唯一 ID（真题来源）")
    source_paper = Column(String(200), nullable=True, comment="来源试卷名")
    source_page = Column(Integer, nullable=True, comment="来源页码")
    question_no = Column(Integer, nullable=True, comment="题号（试卷内序号）")
    # —— 跨来源去重溯源（2026-11）——
    # 同一道题可能被多份文档承载（公共课跨考题最典型）。入库时判重命中不会丢弃，
    # 而是把新来源并入本字段（JSON 数组），供前端展示"这题也出现在 X 文档"。
    #
    # 2026-10-14 PG 迁移：canonical schema 未保留 source_ids 列（ADR-003 把来源
    # 拆成正交的 source_kind + source_label）。该属性改为**非持久化**内存字段，
    # 供尚未迁移的存量脚本读取，避免 AttributeError；新代码请用 source_label。
    source_ids = None
    confidence = Column(PgEnumAware("confidence_level", 20), default="medium", comment="置信度：high/medium/low")
    answer_type = Column(PgEnumAware("answer_type", 20), default="objective", comment="作答类型：objective/subjective")
    is_available = Column(Boolean, default=True, comment="是否可用（下线标记）")
    quality = Column(PgEnumAware("quality_grade", 20), nullable=True, comment="质量评级：A/B/C")
    # —— M1-1f：OCR 碎片题标记（2026-10）—— #
    is_junk = Column(Boolean, default=False, comment="是否 OCR 碎片/答案串（列表默认排除）")
    # —— M6-3：复试维度标记（2026-11）—— #
    # is_retest=1 表示复试题（复试面试/笔试），默认 0=初试。用于复试题库分区与过滤。
    is_retest = Column(Boolean, default=False, index=True, comment="是否复试题（0 初试 / 1 复试）")
    answer_source = Column(PgEnumAware("answer_source", 20), nullable=True, comment="答案来源：bank/source_extract/llm_generated/user_confirmed")
    answer_confidence = Column(Float, nullable=True, comment="答案置信度 0-1（<0.8 不参与自动判分）")
    # —— 识别图缺失标记（2026-10 数据治理）—— #
    # 题干引用了图/表（“如图/图1.2.12/真值表…”），但本库无任何题目图片存储 → 该题的图必然缺失。
    # 刻意**不复用 quality**：quality 已被 A/B/C 分级 + incomplete 占用，写入非分级值会毁掉分级语义。
    figure_missing = Column(Integer, nullable=False, default=0, server_default="0", comment="识别图缺失标记")
    # —— 导入自动分类可信闸门（2026-10-14）——
    # 高置信判定直接自动入库（needs_review=False）；低置信打 needs_review 进复核队列，
    # 绝不静默错标、也不丢弃。classify_confidence 为科目×题型置信下限（0~1）。
    classify_confidence = Column(Float, nullable=True, comment="导入自动分类整体置信度 0-1")
    classify_source = Column(String(30), nullable=True, comment="分类来源：keyword/vector/fusion/llm/disagree/none")
    needs_review = Column(Boolean, default=False, index=True, comment="分类低置信待人工复核（进复核队列）")
    created_at = Column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------- #
# 题目-知识点链路
# --------------------------------------------------------------------------- #
class QuestionKnowledgeLink(Base):
    """题目 ↔ 知识点多对多链路（module B / V4.0 §7.1②）。"""

    __tablename__ = "question_knowledge_links"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False, index=True, comment="题目 ID")
    knowledge_point_id = Column(Integer, ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True, comment="知识点 ID")
    role = Column(String(20), default="primary", comment="角色：primary/secondary")
    weight = Column(Float, default=1.0, comment="关联权重")
    is_verified = Column(Boolean, default=False, comment="是否人工校验")
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("question_id", "knowledge_point_id", name="uq_qkl_q_kp"),
    )


# --------------------------------------------------------------------------- #
# 错题记录
# --------------------------------------------------------------------------- #
class AnswerRecord(Base):
    """答题记录（用于统计真实正确率）。"""

    __tablename__ = "answer_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    question_id = Column(Integer, ForeignKey("quiz_questions.id"), nullable=True, index=True)
    my_answer = Column(Text, nullable=True, comment="我的答案")
    correct_answer = Column(Text, nullable=True, comment="正确答案")
    is_correct = Column(Boolean, default=False, comment="是否答对")
    subject = Column(String(50), nullable=True, index=True, comment="科目")
    mode = Column(String(50), nullable=True, comment="答题模式")
    cost_seconds = Column(Integer, default=0, comment="用时（秒）")
    created_at = Column(DateTime, default=_utcnow, index=True)

    question = relationship("QuizQuestion", backref="answer_records")


class ErrorRecord(Base):
    __tablename__ = "error_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    question_id = Column(Integer, ForeignKey("quiz_questions.id"), nullable=True)
    content = Column(Text, nullable=True, comment="错题内容（可脱离题目独立存在）")
    my_answer = Column(Text, nullable=True, comment="我的答案")
    correct_answer = Column(Text, nullable=True, comment="正确答案")
    error_reason = Column(String(200), nullable=True, comment="错误原因")
    # —— 错因分类（2026-10-15 补齐：列早已存在于 DB，ORM 缺失导致无法写入）—— #
    # 取值：概念混淆 / 审题失误 / 计算错误 / 记忆缺失 / 方法没想到 / 时间不足
    # （services.error_analyzer.CATEGORIES）；由 infer_error_category 信号驱动自动判定，
    # 用户可手改，AI 归因（analyze_error）可覆盖。
    error_category = Column(String(50), nullable=True, comment="错因分类")
    subject = Column(String(50), nullable=True, index=True)
    subject_id = Column(Integer, nullable=True, index=True, comment="科目权威 ID")
    knowledge_point_id = Column(Integer, nullable=True, index=True, comment="关联知识点 ID")
    accuracy = Column(Float, default=0, comment="正确率")
    review_count = Column(Integer, default=0, comment="复习次数")
    last_review = Column(DateTime, nullable=True, comment="上次复习时间")
    next_review = Column(DateTime, nullable=True, comment="下次复习时间")
    status = Column(String(50), default="active", comment="状态：active/graduated")
    # —— SM-2 调度状态（DB 已有列，ORM 补齐以便调度器读写一致）—— #
    mastery_level = Column(PgEnumAware("mastery_level", 50), nullable=False,
                           server_default="not_mastered", comment="掌握档位")
    ease_factor = Column(Float, nullable=False, server_default="2.5", comment="SM-2 难度因子")
    interval_days = Column(Integer, nullable=False, server_default="0", comment="当前间隔（天）")
    repetitions = Column(Integer, nullable=False, server_default="0", comment="连续通过次数")
    lapses = Column(Integer, nullable=False, server_default="0", comment="遗忘次数")
    pass_number = Column(Integer, nullable=False, server_default="1", comment="第几遍复习")
    recent_weight = Column(Float, nullable=False, server_default="1.0", comment="近期权重")
    user_note = Column(Text, nullable=True, comment="用户备注")
    interval = Column(Integer, nullable=True, server_default="0", comment="间隔（兼容列）")
    last_status = Column(Text, nullable=True, server_default="unreviewed", comment="上次复习结果")
    prev_ease_factor = Column(Float, nullable=True, comment="上一次 ease_factor 快照")
    prev_interval = Column(Integer, nullable=True, comment="上一次 interval 快照")
    prev_repetitions = Column(Integer, nullable=True, comment="上一次 repetitions 快照")
    tags = Column(JSON, nullable=True, comment="标签 JSON")
    analysis = Column(Text, nullable=True, comment="AI 分析结果")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    question = relationship("QuizQuestion", backref="error_records")


# --------------------------------------------------------------------------- #
# 学习记录
# --------------------------------------------------------------------------- #
class StudySession(Base):
    __tablename__ = "study_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    date = Column(Date, nullable=False, index=True, comment="学习日期")
    duration = Column(Integer, nullable=True, comment="时长（分钟）")
    subject = Column(String(50), nullable=True, comment="科目")
    task_type = Column(String(50), nullable=True, comment="任务类型")
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------- #
# 说明：独立的「番茄钟」模块（pomodoro_sessions 表 + 专属路由/页面）已于 2026-10 移除。
# 原因：pomodoro_sessions 长期只有 1 行数据，却占用 13.7KB 路由 +
# 32.7KB 前端页面 + 200+ 处引用。**学习时长统计保留在 study_sessions**，
# 仪表盘的「学习时长 / 本周趋势 / 连续打卡」改由 study_sessions 驱动，不受影响。
# 源码归档 _archive/removed_pomodoro/，数据备份 data/archive/pomodoro_sessions.json。
#
# 2026-10-17 补：D-04 的「专注计时」回来了，但**不再是独立模块** —— 它是仪表盘
# 上的一块面板（frontend/src/components/FocusTimer.jsx），只往本表写一行真实分钟数。
# 与旧番茄钟的区别：① 没有第二张表，② 时长取**实际经过**而不是名义档位，
# ③ 计时没跑完 / 没点记录就一行不写。入口是 POST /api/dashboard/study-session，
# 别把它当冗余删掉：study_calendar.focus_minutes 读的就是这里写的行。
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 课表系统（semesters / courses / course_adjustments）已于 2026-09 移除。
# 原因：三张表长期 0 行，属于与考研无关的本科教务功能，占用 15KB 路由 +
# 49KB 前端页面 + 8 处导航引用，属明确冗余。历史数据如需保留见 _archive/。
# --------------------------------------------------------------------------- #


class DailyPlan(Base):
    """日计划表：四科目任务 + 时间轴 + 评分总结。"""
    __tablename__ = "daily_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    # B4：唯一键 date → (user_id,date)，SQL 108 同步重建
    date = Column(Date, nullable=False, index=True, comment="日期")
    days_to_exam = Column(Integer, nullable=True, comment="距离考研天数")
    tasks = Column(JSON, nullable=True, comment="四科目任务 JSON")
    timeline = Column(JSON, nullable=True, comment="时间轴记录 JSON")
    study_duration = Column(Integer, default=0, comment="学习时长（分钟）")
    wasted_duration = Column(Integer, default=0, comment="浪费时长（分钟）")
    score = Column(Integer, default=0, comment="今日评分 1-10")
    summary = Column(Text, nullable=True, comment="今日总结")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_daily_plan_user"),
    )


class WeekPlan(Base):
    """周计划表：四科目周任务 + 每日完成记录。"""
    __tablename__ = "week_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    week_start = Column(Date, nullable=False, index=True, comment="周一日期")
    month_plan_id = Column(Integer, ForeignKey("month_plans.id"), nullable=True)
    tasks = Column(JSON, nullable=True, comment="四科目周任务 JSON")
    daily_records = Column(JSON, nullable=True, comment="每日完成记录 JSON")
    completion = Column(Text, nullable=True, comment="周任务完成情况")
    created_at = Column(DateTime, default=_utcnow)


class MonthPlan(Base):
    """月计划表：四科目月目标。"""
    __tablename__ = "month_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    year = Column(Integer, nullable=False, index=True)
    month = Column(Integer, nullable=False, index=True)
    tasks = Column(JSON, nullable=True, comment="四科目月任务 JSON")
    completion = Column(Text, nullable=True, comment="任务完成情况")
    created_at = Column(DateTime, default=_utcnow)


class EbbinghausItem(Base):
    """艾宾浩斯记忆表：默认 9 个复习周期节点，支持自定义周期（cycle_config + review_times JSONB）。

    兼容设计（2026-10-23）：
    - 默认周期仍写入 review_5min/30min/.../1m 九列（旧逻辑 get_due 依赖它们）。
    - 自定义周期（custom_cycles）时，cycle_config 保存周期定义数组，
      review_times 保存实际复习时间点数组；同时尽量回填九列（前 N 个点按列名映射，
      不足 9 个的列置 NULL），保证旧代码不崩。
    """
    __tablename__ = "ebbinghaus_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    seq = Column(Integer, nullable=True, comment="序号")
    learn_date = Column(DateTime, nullable=False, index=True, comment="学习时间")
    content = Column(Text, nullable=False, comment="学习内容")
    subject = Column(String(50), nullable=True, comment="科目")
    review_5min = Column(DateTime, nullable=True)
    review_30min = Column(DateTime, nullable=True)
    review_12h = Column(DateTime, nullable=True)
    review_1d = Column(DateTime, nullable=True)
    review_2d = Column(DateTime, nullable=True)
    review_4d = Column(DateTime, nullable=True)
    review_7d = Column(DateTime, nullable=True)
    review_15d = Column(DateTime, nullable=True)
    review_1m = Column(DateTime, nullable=True)
    cycle_config = Column(NullSafeJSON, nullable=True, comment="自定义周期定义 [{\"key\":\"1d\",\"label\":\"1天\",\"offset_days\":1}]")
    review_times = Column(NullSafeJSON, nullable=True, comment="实际复习时间点 [{\"key\":\"1d\",\"label\":\"1天\",\"time\":\"iso\",\"done\":false}]")
    mastered = Column(Boolean, default=False, comment="是否已掌握")
    created_at = Column(DateTime, default=_utcnow)


class EarlyBirdRecord(Base):
    """早起打卡记录。"""
    __tablename__ = "early_bird_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    day_num = Column(Integer, nullable=True, comment="天数（1-120）")
    # B4：唯一键 date → (user_id,date)，SQL 108 同步重建
    date = Column(Date, nullable=False, index=True, comment="日期")
    wake_time = Column(Time, nullable=True, comment="早起时间")
    sleep_time = Column(Time, nullable=True, comment="晚安时间")
    note = Column(String(200), nullable=True, comment="备注")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_early_bird_user"),
    )


class PhasePlan(Base):
    """阶段复习表（如40天专业课复习）。"""
    __tablename__ = "phase_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    name = Column(String(100), nullable=False, comment="阶段名称")
    start_date = Column(Date, nullable=False, comment="开始日期")
    end_date = Column(Date, nullable=True, comment="结束日期")
    cycle_days = Column(Integer, default=40, comment="阶段周期天数")
    tasks = Column(JSON, nullable=True, comment="任务划分 JSON")
    created_at = Column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------- #
# AI 服务商配置
# --------------------------------------------------------------------------- #
class AIProvider(Base):
    __tablename__ = "ai_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, comment="服务商名称")
    provider_type = Column(String(50), nullable=True, comment="类型：doubao/deepseek/qwen/gpt/claude")
    api_key = Column(EncryptedText, nullable=True, comment="API Key（密文落库）")
    base_url = Column(String(500), nullable=True, comment="Base URL")
    model_name = Column(String(200), nullable=True, comment="模型名")
    temperature = Column(Float, default=0.7, comment="温度")
    is_default = Column(Boolean, default=False, comment="是否默认")
    is_enabled = Column(Boolean, default=True, comment="是否启用")
    fallback_priority = Column(Integer, default=0, comment="降级优先级，数字越小越优先")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# --------------------------------------------------------------------------- #
# 平台配置
# --------------------------------------------------------------------------- #
class PlatformConfig(Base):
    __tablename__ = "platform_configs"

    id = Column(Integer, primary_key=True, index=True)
    platform_name = Column(String(100), nullable=False, comment="平台名")
    # 凭据三列写入即 AES-256-GCM 加密（utils.secret_codec），备份外流不再等于凭据外流
    token = Column(EncryptedText, nullable=True, comment="Token（密文落库）")
    app_key = Column(EncryptedText, nullable=True, comment="App Key（密文落库）")
    secret_key = Column(EncryptedText, nullable=True, comment="Secret Key（密文落库）")
    sync_enabled = Column(Boolean, default=False, comment="同步开关")
    sync_frequency = Column(String(50), default="daily", comment="同步频率")
    last_sync = Column(DateTime, nullable=True, comment="最后同步时间")
    extra = Column(JSON, nullable=True, comment="额外配置")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# --------------------------------------------------------------------------- #
# 网盘文件
# --------------------------------------------------------------------------- #
class NetdiskFile(Base):
    __tablename__ = "netdisk_files"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String(500), nullable=False, comment="文件名")
    path = Column(String(1000), nullable=True, comment="路径")
    file_type = Column(String(50), nullable=True, comment="类型：video/pdf/doc/audio")
    size = Column(Integer, nullable=True, comment="大小（字节）")
    category = Column(String(100), nullable=True, comment="分类")
    download_link = Column(String(1000), nullable=True, comment="下载链接")
    play_progress = Column(Float, default=0, comment="播放进度 0-1")
    fs_id = Column(String(100), nullable=True, comment="网盘文件 ID")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# --------------------------------------------------------------------------- #
# 知识点
# --------------------------------------------------------------------------- #
class KnowledgePoint(Base):
    """知识点（三级结构中的第 2 级）。

    完整结构：章节(chapter) → 知识点(name/parent_id) → 题型(question_types)
    """

    __tablename__ = "knowledge_points"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(300), nullable=False, comment="知识点名称")
    subject = Column(String(50), nullable=True, index=True, comment="科目")
    chapter = Column(String(200), nullable=True, comment="章节")
    parent_id = Column(Integer, ForeignKey("knowledge_points.id"), nullable=True, comment="父知识点 ID")
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True, comment="来源文档 ID")
    # —— 溯源与留痕（2026-10 入库时知识点抽取，见 services/kp_extract.py）——
    source_chunk_id = Column(Integer, ForeignKey("knowledge_chunks.id"), nullable=True,
                             index=True, comment="来源知识分块 ID（可反查原文片段）")
    source_chunk_index = Column(Integer, nullable=True,
                                comment="来源分块在本篇文档内的序号")
    extract_source = Column(PgEnumAware("extract_source", 32), nullable=True,
                            comment="抽取来源：smart_ingest / batch / manual")
    subject_source = Column(String(20), nullable=True,
                            comment="学科判定来源：model / keyword / model_over_keyword / fallback")
    mastery = Column(Integer, default=0, comment="掌握度 0-100")
    exam_frequency = Column(Integer, default=0, comment="考频 1-5")
    description = Column(Text, nullable=True, comment="描述")
    # —— 三级结构：章节 → 知识点 → 题型 —— #
    question_types = Column(JSON, nullable=True, comment="该知识点考过的题型列表，如 ['选择','计算','分析']")
    difficulty = Column(Integer, default=3, comment="难度 1-5")
    # —— 复习进度追踪 —— #
    review_count = Column(Integer, default=0, comment="复习次数")
    last_review = Column(DateTime, nullable=True, comment="上次复习时间")
    next_review = Column(DateTime, nullable=True, comment="下次复习时间（SM-2 调度）")
    ease_factor = Column(Float, default=2.5, comment="SM-2 难度因子")
    interval_days = Column(Integer, default=0, comment="当前复习间隔（天）")
    lapses = Column(Integer, default=0, comment="遗忘次数")
    question_count = Column(Integer, default=0, comment="关联题目数")
    created_at = Column(DateTime, default=_utcnow)

    children = relationship("KnowledgePoint", backref="parent", remote_side="KnowledgePoint.id")
    document = relationship("Document", backref="knowledge_points")


# --------------------------------------------------------------------------- #
# 知识点关系表（2026-10 扩科新增）：前置 / 并列 / 包含
# --------------------------------------------------------------------------- #
class KnowledgePointRelation(Base):
    """知识点之间的关系（供刷题路径与知识地图使用）。

    relation_type:
      - prerequisite: source 是 target 的前置知识点
      - parallel:     source 与 target 属并列（同章并列考点）
      - contains:     source 包含 target（章节级知识点包含术语级知识点）
    """

    __tablename__ = "knowledge_point_relations"

    id = Column(Integer, primary_key=True, index=True)
    source_kp_id = Column(Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True)
    target_kp_id = Column(Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True)
    relation_type = Column(PgEnumAware("relation_type", 20), nullable=False, comment="prerequisite/parallel/contains")
    source = Column(String(100), nullable=True, comment="生成来源：syllabus_order/chapter_hierarchy/chapter_cooccurrence/manual")
    created_at = Column(DateTime, default=_utcnow)

    source_kp = relationship("KnowledgePoint", foreign_keys=[source_kp_id], backref="out_relations")
    target_kp = relationship("KnowledgePoint", foreign_keys=[target_kp_id], backref="in_relations")


# --------------------------------------------------------------------------- #
# 错题本 ↔ 知识库联动
# --------------------------------------------------------------------------- #
class ErrorKnowledgeLink(Base):
    """错题与知识点的关联（多对多）。

    由 RAG 检索命中自动建立，使"这道错题考的是哪个知识点"可反查、
    可统计高频错误考点。
    """

    __tablename__ = "error_knowledge_links"

    id = Column(Integer, primary_key=True, index=True)
    # B4：冗余归属用户（跟随 error_id 的主人），便于直接过滤不必联表
    user_id = Column(BigInteger, nullable=True, index=True,
                     comment="归属用户 ID（冗余，随 error_records）")
    # ondelete 与权威 DDL core/sql/050_learning.sql 保持一致：ORM create_all 若先于
    # pg_schema.sql 建表，缺 CASCADE 会让删除知识点/错题时撞 FK（测试库曾因此中毒）。
    error_id = Column(Integer, ForeignKey("error_records.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_point_id = Column(Integer, ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=True, index=True)
    chunk_id = Column(Integer, ForeignKey("knowledge_chunks.id", ondelete="CASCADE"), nullable=True, comment="命中的知识分块")
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, comment="命中分块所属文档")
    relevance = Column(Float, default=0, comment="关联度 0-1（检索得分）")
    source = Column(String(20), default="auto", comment="来源：auto 自动检索 / manual 手动指定")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_ekl_error_kp", "error_id", "knowledge_point_id"),
    )


# --------------------------------------------------------------------------- #
# 复习进度追踪（章节→知识点→题型 的复习记录）
# --------------------------------------------------------------------------- #
class ReviewRecord(Base):
    """一次复习记录。

    每次复习都留痕，用于统计"复习进度 / 薄弱知识点 / 遗忘曲线"。
    """

    __tablename__ = "review_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    item_type = Column(String(20), nullable=False, index=True, comment="对象类型：knowledge/error/flashcard/word")
    item_id = Column(Integer, nullable=False, index=True, comment="对象 ID")
    subject = Column(String(50), nullable=True, index=True, comment="科目")
    chapter = Column(String(200), nullable=True, comment="章节（冗余，便于按章节统计）")
    result = Column(PgEnumAware("review_result", 20), nullable=True, comment="复习结果：forgotten 忘了 / fuzzy 模糊 / mastered 掌握")
    grade = Column(Integer, default=0, comment="评分 0-5")
    mastery_before = Column(Integer, default=0, comment="复习前掌握度")
    mastery_after = Column(Integer, default=0, comment="复习后掌握度")
    duration = Column(Integer, default=0, comment="用时（秒）")
    interval_after = Column(Integer, default=0, comment="本次计算出的下次间隔（天）")
    next_review = Column(DateTime, nullable=True, comment="下次复习时间")
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)

    __table_args__ = (
        Index("ix_review_item", "item_type", "item_id"),
    )



# --------------------------------------------------------------------------- #
# 背诵卡片
# --------------------------------------------------------------------------- #
class Flashcard(Base):
    __tablename__ = "flashcards"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    front = Column(Text, nullable=False, comment="正面")
    back = Column(Text, nullable=False, comment="背面")
    knowledge_point_id = Column(Integer, ForeignKey("knowledge_points.id"), nullable=True)
    next_review = Column(DateTime, nullable=True, comment="下次复习时间")
    review_count = Column(Integer, default=0, comment="复习次数")
    interval_days = Column(Integer, default=1, comment="当前间隔天数")
    # 兼容别名：旧路由/前端一直读写 card.interval（DB 列实际叫 interval_days）
    interval = synonym("interval_days")
    ease_factor = Column(Float, default=2.5, comment="SM-2 难度因子")
    # 2026-10-14 修正：默认值曾写 "new"，但 mastery_level ENUM 的合法标签是
    # not_mastered/learning/reviewing/mastered —— "new" 不是合法值。
    # 任何不带 status/mastery 的新建 Flashcard 都会在 PG 上抛
    #   InvalidTextRepresentation: invalid input value for enum mastery_level: "new"
    # （SQLite 无类型约束所以不暴露）。生产库现存数据都是合法值，
    # 说明该默认值从未真正落库，属侥幸未爆的定时炸弹。
    mastery = Column(PgEnumAware("mastery_level", 20), default="not_mastered",
                     comment="掌握状态（mastery_level ENUM）：not_mastered/learning/reviewing/mastered")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    knowledge_point = relationship("KnowledgePoint", backref="flashcards")


# --------------------------------------------------------------------------- #
# 文档记录
# --------------------------------------------------------------------------- #
class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String(500), nullable=False, comment="文件名")
    file_path = Column(String(1000), nullable=True, comment="服务器存储路径")
    # DB 正典：NOT NULL DEFAULT 'other'::doc_format。ORM 之前写 nullable=True
    # 且无 Python 侧默认，显式传 None 时会把 NULL 发到库，直接违反 NOT NULL
    # （实测 47 例 NotNullViolation）。此处与 DB 对齐。
    source_format = Column(PgEnumAware("doc_format", 50), nullable=False,
                           default="other", server_default="other", comment="类型：pdf/docx/txt")
    size = Column(Integer, nullable=True, comment="大小（字节）")
    index_status = Column(PgEnumAware("index_status", 50), default="pending", comment="索引状态：pending/indexing/indexed/failed")
    knowledge_point_count = Column(Integer, default=0, server_default="0", comment="提取知识点数量")
    # 此前只有 core.models.documents.Document 映射了 chunk_count，业务实际用的是本类，
    # 于是 smart_ingest 的赋值落在 Python 属性上、从未落库（705/705 恒为 0）。
    chunk_count = Column(Integer, default=0, server_default="0", comment="已产生的分块数")
    parse_progress = Column(Float, default=0, comment="解析进度 0-1")
    # 解析失败原因（对齐 core/sql/020_documents.sql：index_status=failed 时必填）
    parse_error = Column(Text, nullable=True, comment="解析失败原因")
    content = Column(Text, nullable=True, comment="解析后文本内容")
    subject = Column(String(50), nullable=True, index=True, comment="学科分类")
    # —— 结构化文档组织：# 原始层 / 加工层 / 索引层 —— #
    doc_type = Column(PgEnumAware("doc_type", 20), nullable=True, index=True, comment="资料层级：raw 原始教材真题 / note 加工笔记错题 / index 索引考点清单")
    structure_level = Column(PgEnumAware("structure_level", 20), nullable=True, comment="结构化程度：structured 已按章节解析 / flat 扁平文本 / ocr 扫描件")
    ocr_used = Column(Boolean, default=False, comment="是否经 OCR 识别（扫描版真题）")
    # —— V11 模块5：内容语义分层（与 doc_type 加工层级正交）—— #
    # textbook 教材知识点 / example 典型例题 / exam 历年真题 / method 解题方法
    content_category = Column(PgEnumAware("content_category", 20), nullable=True, index=True, comment="内容语义分类：textbook 教材 / example 例题 / exam 真题 / method 方法")
    # —— IMA 知识库导入：阶段 / 内容性质 / 溯源 —— #
    # 三个维度彼此正交，且都**不复用 doc_type**（doc_type 是加工层级 raw/note/index），
    # 避免两套语义挤在同一列破坏既有筛选。
    subject_source = Column(String(50), nullable=True, index=True, comment="资料来源：ima=IMA知识库导入 / 空=本地上传")
    exam_stage = Column(PgEnumAware("exam_stage", 20), nullable=True, index=True, comment="备考阶段：初试 / 复试")
    content_type = Column(String(20), nullable=True, index=True, comment="内容性质：知识 / 试题 / 单词")
    ima_media_id = Column(String(200), nullable=True, index=True, comment="IMA 侧条目 ID，正文按需 fetch，不落库")
    folder_path = Column(String(500), nullable=True, comment="IMA 内文件夹路径，保留原始组织结构")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    # —— 违禁/废弃标记（2026-10-15，分片 096_documents_junk_flag.sql）—— #
    # 红线 3：内容仅限 0854 学科；非相关（法硕/西医/管综/教育…）标 True，
    # 查询侧统一过滤 `is_junk IS NOT TRUE`，不物理删除。
    is_junk = Column(Boolean, nullable=False, default=False, index=True,
                     server_default="false", comment="违禁/废弃文档标记")


# --------------------------------------------------------------------------- #
# RAG 知识分块（knowledge_chunks）
# --------------------------------------------------------------------------- #
class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True, comment="来源文档 ID")
    doc_name = Column(String(500), nullable=True, index=True, comment="来源文档名")
    chunk_index = Column(Integer, nullable=True, comment="分块序号")
    subject = Column(String(50), nullable=True, index=True, comment="学科分类")
    text = Column(Text, nullable=True, comment="分块文本")
    # —— V4.0 遗留补列（2026-10）：页码与摘要（在线 ALTER 已同步） —— #
    page_start = Column(Integer, nullable=True, comment="起始页码")
    page_end = Column(Integer, nullable=True, comment="结束页码")
    summary = Column(Text, nullable=True, comment="分块摘要")
    # —— chunk 级三层标签（docx/14 方案，幂等 ALTER 见 chunk_classifier） —— #
    l2_chapter = Column(String(200), nullable=True, comment="L2 章节/模块，如：连续时间系统的时域分析")
    l3_content_type = Column(PgEnumAware("l3_content_type", 30), nullable=True, index=True,
                             comment="L3 内容语义类型：定义/定理/理论陈述/例题/习题/证明/公式/实验步骤/其他")
    classify_confidence = Column(Float, nullable=True, comment="三路融合置信度 0~1")
    classify_source = Column(PgEnumAware("classify_source", 30), nullable=True,
                             comment="判定来源留痕：vector/keyword/fusion/llm/no_bge/fallback")
    created_at = Column(DateTime, default=_utcnow)

    document = relationship("Document", backref="knowledge_chunks")


# --------------------------------------------------------------------------- #
# 学科原型质心（subject_prototypes）—— chunk 分类路1 的种子向量库
# --------------------------------------------------------------------------- #
class SubjectPrototype(Base):
    """学科原型质心向量。主键含 engine：**不同引擎的向量绝不允许混用**。

    背景：knowledge_chunks_vec 里 bge 与离线哈希向量同为 512 维、dim 列不区分引擎，
    哈希向量做相似度=噪声。质心分类对引擎一致性极其敏感，所以这里用
    (subject, engine) 联合主键把口径锁死（docx/14 第一节问题 6）。
    """
    __tablename__ = "subject_prototypes"

    subject = Column(String(50), primary_key=True, comment="学科（taxonomy 归一后的叶子科）")
    engine = Column(String(30), primary_key=True, default="bge", comment="向量引擎标识（bge）")
    dim = Column(Integer, nullable=False, comment="向量维度")
    vector = Column(LargeBinary, nullable=False, comment="质心向量 bytes（float32，L2 归一化后）")
    n_samples = Column(Integer, default=0, comment="参与求质的样本块数")
    built_at = Column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------- #
# 分类标注样本（annotation_samples）—— 评估闭环 / 人工修正回流
# --------------------------------------------------------------------------- #
class AnnotationSample(Base):
    """人工标注/修正的分类样本。eval 集 + 未来小模型训练集共用。"""
    __tablename__ = "annotation_samples"

    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(Integer, nullable=True, index=True, comment="来源 chunk（可为空：外部样本）")
    chunk_text = Column(Text, nullable=False, comment="标注时的块文本快照")
    label_l1 = Column(String(50), nullable=True, comment="人工学科标签")
    label_l2 = Column(String(200), nullable=True, comment="人工章节标签")
    label_l3 = Column(PgEnumAware("l3_content_type", 30), nullable=True, comment="人工内容类型标签")
    annotate_user = Column(String(50), nullable=True, comment="标注人")
    source = Column(String(20), default="manual_fix",
                    comment="来源：eval_seed=评估集抽样 / manual_fix=线上人工修正")
    created_at = Column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------- #
# 评测/体检运行历史（eval_runs）
# --------------------------------------------------------------------------- #
class EvalRun(Base):
    """一次评测或语料体检的落库记录，供趋势页和回溯用。

    metrics 原样存脚本的 report dict，不改结构；primary_metric 单独拉一列，
    前端画趋势不必解析 JSON。
    """
    __tablename__ = "eval_runs"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(24), nullable=False, index=True,
                  comment="qa=答疑模型评测 / recognition=识别策略评测 / corpus_probe=语料体检")
    arm = Column(String(120), nullable=True, comment="被测对象：模型名列表或策略名")
    dataset_fingerprint = Column(String(64), nullable=True, index=True,
                                 comment="数据集指纹 sha1（训练集内容+样本数+holdout 口径）")
    n_samples = Column(Integer, nullable=True, comment="评测样本数")
    primary_metric = Column(Float, nullable=True,
                            comment="主指标：qa=held-out 准确率, recognition=学科池精确率, corpus_probe=域内可检索率")
    metrics = Column(JSON, nullable=True, comment="脚本 report 原文 JSON")
    report_path = Column(String(300), nullable=True, comment="导出的 markdown/JSON 报告路径")
    notes = Column(Text, nullable=True, comment="口径说明、否决结论等")
    created_at = Column(DateTime, default=_utcnow, index=True)


# --------------------------------------------------------------------------- #
# SFT 训练对话样例（sft_examples）
# --------------------------------------------------------------------------- #
class SFTExample(Base):
    __tablename__ = "sft_examples"

    id = Column(Integer, primary_key=True, index=True)
    split = Column(String(20), nullable=True, index=True, comment="train/val")
    system = Column(Text, nullable=True, comment="system 提示")
    user_input = Column(Text, nullable=True, comment="用户输入")
    assistant = Column(Text, nullable=True, comment="助手回答")
    subject = Column(String(50), nullable=True, index=True, comment="学科分类")
    created_at = Column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------- #
# 自定义快捷链接
# --------------------------------------------------------------------------- #
class CustomLink(Base):
    __tablename__ = "custom_links"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, comment="名称")
    url = Column(String(1000), nullable=False, comment="链接")
    category = Column(String(100), nullable=True, comment="分类")
    # 2026-10-14 PG 迁移：canonical schema 未保留 custom_links.icon 列，
    # 改为非持久化字段，避免 ORM 查询拼出该列导致 PG 报错。
    icon = None
    sort_order = Column(Integer, default=0, comment="排序")
    created_at = Column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------- #
# 学习统计
# --------------------------------------------------------------------------- #
class StudyStats(Base):
    __tablename__ = "study_stats"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    date = Column(Date, nullable=False, index=True, comment="日期")
    total_duration = Column(Integer, default=0, comment="总时长（分钟）")
    subject_durations = Column(JSON, nullable=True, comment="各科时长 JSON")
    task_completed = Column(Integer, default=0, comment="完成任务数")
    error_count = Column(Integer, default=0, comment="错题数")
    new_knowledge_count = Column(Integer, default=0, comment="新学知识点数")
    created_at = Column(DateTime, default=_utcnow)



# --------------------------------------------------------------------------- #
# 单词词库
# --------------------------------------------------------------------------- #
class WordDeck(Base):
    """词库分类（如：考研核心词、高频词、熟词僻义等）。"""
    __tablename__ = "word_decks"

    id = Column(Integer, primary_key=True, index=True)
    # B4：NULL=内置公共词书（人人可见）；非 NULL=用户自建词库
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID；NULL=内置公共词书")
    name = Column(String(200), nullable=False, comment="词库名称")
    description = Column(String(500), nullable=True, comment="词库描述")
    source = Column(String(100), nullable=True, comment="来源：词汇闪过/红宝书/自建等")
    word_count = Column(Integer, default=0, comment="单词数量")
    # 2026-10-14 PG 迁移：canonical schema 未保留 word_decks.color 列
    # （主题色属前端展示偏好，不进权威数据层）。改为**非持久化**字段，
    # 避免 ORM 查询拼出 `word_decks.color` 导致 PG 报 column does not exist。
    color = None
    created_at = Column(DateTime, default=_utcnow)


class Word(Base):
    """单词条目（含释义、音标、词根、例句、SM-2调度状态）。"""
    __tablename__ = "words"

    id = Column(Integer, primary_key=True, index=True)
    # B4：NULL=内置公共词书的词条（内容共用）；个人 SM-2 进度隔离在 review_schedules。
    # 非 NULL=用户自建词库导入的词条（内容本身即个人数据）。
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID；NULL=公共词书词条")
    deck_id = Column(Integer, ForeignKey("word_decks.id"), nullable=True, index=True)
    word = Column(String(100), nullable=False, index=True, comment="单词")
    phonetic = Column(String(100), nullable=True, comment="音标")
    pos = Column(String(50), nullable=True, comment="词性")
    meaning = Column(Text, nullable=False, comment="释义")
    root = Column(String(300), nullable=True, comment="词根词缀/助记")
    example = Column(Text, nullable=True, comment="英文例句")
    example_cn = Column(Text, nullable=True, comment="例句中文翻译")
    tag = Column(String(50), nullable=True, comment="标签：高频/中频/低频等")
    # SM-2 间隔重复调度
    # 同Flashcard.mastery：默认值必须是 mastery_level 的合法标签，"new" 会让PG 报错
    status = Column(PgEnumAware("mastery_level", 20), default="not_mastered",
                    comment="状态（mastery_level ENUM）：not_mastered/learning/reviewing/mastered")
    ease_factor = Column(Float, default=2.5, comment="难度系数 EF")
    interval_days = Column(Integer, default=0, comment="复习间隔（天）")
    # 兼容别名：旧路由/前端一直读写 word.interval（DB 列实际叫 interval_days）
    interval = synonym("interval_days")
    reps = Column(Integer, default=0, comment="复习次数")
    lapses = Column(Integer, default=0, comment="遗忘次数")
    due_date = Column(Date, nullable=True, comment="下次复习日期")
    last_review = Column(Date, nullable=True, comment="上次复习日期")
    review_history = Column(JSON, nullable=True, comment="复习历史 JSON")
    extra = Column(JSON, nullable=True, comment="扩展数据 JSON：同近义/短语/同根（KyleBing 等结构化词源）")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_words_word_deck", "word", "deck_id"),
    )


# --------------------------------------------------------------------------- #
# 组题网：试卷与试卷题目（纯新增，不改动既有表）
# --------------------------------------------------------------------------- #
class Paper(Base):
    """组题网：保存的试卷。"""

    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, comment="试卷标题")
    subject = Column(String(50), nullable=True, index=True, comment="科目")
    description = Column(Text, nullable=True, comment="试卷说明")
    rules = Column(JSON, nullable=True, comment="组卷规则快照")
    total_score = Column(Integer, default=0, comment="总分")
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    questions = relationship("PaperQuestion", backref="paper", cascade="all, delete-orphan")


class PaperQuestion(Base):
    """试卷题目关联（快照题目内容，试卷独立于题库）。"""

    __tablename__ = "paper_questions"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("quiz_questions.id"), nullable=True, comment="来源题目 ID")
    seq = Column(Integer, default=0, comment="题号")
    content = Column(Text, nullable=False, comment="题干快照")
    options = Column(NullSafeJSON, nullable=True, comment="选项快照")
    answer = Column(Text, nullable=True, comment="答案快照")
    analysis = Column(Text, nullable=True, comment="解析快照")
    question_type = Column(PgEnumAware("question_type", 50), nullable=True, comment="题型")
    difficulty = Column(Integer, default=3, comment="难度")
    score = Column(Integer, default=5, comment="本题分值")

    __table_args__ = (
        Index("ix_paper_questions_paper_seq", "paper_id", "seq"),
    )


# --------------------------------------------------------------------------- #
# 考研择校数据中心
# --------------------------------------------------------------------------- #
class KaoyanSchool(Base):
    """择校数据中心·院校主表"""
    __tablename__ = "kaoyan_schools"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True, comment="院校名称")
    level = Column(String(50), nullable=True, index=True, comment="层级：985/211/双一流/双非；空=未分类（非985/211/双一流）")
    province = Column(String(50), nullable=True, index=True, comment="省份")
    city = Column(String(50), nullable=True, comment="城市")
    # M3-1：大区（教育部国家线分区 A区/B区）+ 院校类型（公办/科研院所/军队院校）
    region = Column(String(30), nullable=True, index=True, comment="大区：A区/B区")
    type = Column(String(30), nullable=True, index=True, comment="院校类型：公办/科研院所/军队院校")
    logo_url = Column(String(500), nullable=True, comment="校徽URL")
    intro = Column(Text, nullable=True, comment="院校简介")
    tags = Column(JSON, nullable=True, comment="标签JSON")
    official_url = Column(String(500), nullable=True, comment="研究生院官网")
    data_source = Column(String(50), nullable=True, index=True, comment="来源标记：yz.chsi.com.cn / school_official / seed_txkyer / unverified")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    colleges = relationship("KaoyanCollege", backref="school", cascade="all, delete-orphan")


class KaoyanCrawlTarget(Base):
    """院校采集开关。

    该表只记录"被显式修改过"的院校：
      - 没有记录 = 跟随默认（参与采集）
      - enabled=False = 用户明确排除，采集任务跳过
      - enabled=True  = 用户明确保留（用于审计/后续优先级）
    """
    __tablename__ = "kaoyan_crawl_targets"
    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(Integer, ForeignKey("kaoyan_schools.id"), nullable=False, unique=True, index=True)
    enabled = Column(Boolean, nullable=False, default=True, comment="是否参与采集")
    priority = Column(Integer, default=0, comment="采集优先级，数字越大越优先")
    note = Column(String(200), nullable=True, comment="备注")
    last_crawled_at = Column(DateTime, nullable=True, comment="最近一次采集时间")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class KaoyanCollege(Base):
    """择校数据中心·学院"""
    __tablename__ = "kaoyan_colleges"
    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(Integer, ForeignKey("kaoyan_schools.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False, comment="学院名称")
    created_at = Column(DateTime, default=_utcnow)
    majors = relationship("KaoyanMajor", backref="college", cascade="all, delete-orphan")


class KaoyanMajor(Base):
    """择校数据中心·专业方向"""
    __tablename__ = "kaoyan_majors"
    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(Integer, ForeignKey("kaoyan_schools.id"), nullable=False, index=True)
    college_id = Column(Integer, ForeignKey("kaoyan_colleges.id"), nullable=True, index=True)
    code = Column(String(20), nullable=True, index=True, comment="专业代码")
    name = Column(String(200), nullable=False, comment="专业名称")
    research_direction = Column(String(300), nullable=True, comment="研究方向")
    subject_code = Column(String(20), nullable=True, index=True, comment="所属学科代码")
    exam_subjects = Column(JSON, nullable=True, comment="考试科目JSON")
    reference_books = Column(JSON, nullable=True, comment="参考书目JSON")
    # DB 正典：NOT NULL DEFAULT 'unknown'::degree_type（对齐同上，修 30 例 NotNullViolation）
    degree_type = Column(PgEnumAware("degree_type", 20), nullable=False,
                         default="unknown", server_default="unknown", comment="学硕/专硕")
    created_at = Column(DateTime, default=_utcnow)


class KaoyanAdmission(Base):
    """择校数据中心·年度招生数据"""
    __tablename__ = "kaoyan_admissions"
    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(Integer, ForeignKey("kaoyan_schools.id"), nullable=False, index=True)
    major_id = Column(Integer, ForeignKey("kaoyan_majors.id"), nullable=True, index=True)
    year = Column(Integer, nullable=False, index=True, comment="招生年度")
    enroll_count = Column(Integer, nullable=True, comment="拟招生人数")
    retest_count = Column(Integer, nullable=True, comment="进复试人数")
    admit_count = Column(Integer, nullable=True, comment="拟录取人数")
    admit_avg_score = Column(Float, nullable=True, comment="录取均分")
    major_avg_score = Column(Float, nullable=True, comment="专业课均分")
    retest_ratio = Column(Float, nullable=True, comment="复录比")
    data_source = Column(String(50), nullable=True, comment="数据来源")
    extra = Column(JSON, nullable=True, comment="扩展数据 JSON：最高/最低/中位分、专业课分布等")
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_kaoyan_adm_school_year", "school_id", "year"),
        Index("ix_kaoyan_adm_major_year", "major_id", "year"),
    )


class KaoyanAdmissionDetail(Base):
    """择校数据中心·拟录取/复试名单逐人明细（采集深度·详情页）

    由 pipeline/admission_batch_ocr.py 写入（DeepSeek-OCR 扫描件兜底）。
    data_source 唯一：`<聚合行 data_source>:d<序号>`，断点续跑幂等。
    """
    __tablename__ = "kaoyan_admission_details"
    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("kaoyan_admissions.id"), nullable=True, index=True)
    school_id = Column(Integer, ForeignKey("kaoyan_schools.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True, comment="招生年度")
    exam_no = Column(String(40), nullable=True, comment="考生编号")
    name = Column(String(60), nullable=False, comment="姓名")
    major_name = Column(String(120), nullable=True, comment="录取专业/学院")
    score_initial = Column(Float, nullable=True, comment="初试成绩")
    score_retest = Column(Float, nullable=True, comment="复试成绩")
    score_total = Column(Float, nullable=True, comment="总成绩")
    remark = Column(String(200), nullable=True, comment="备注")
    data_source = Column(String(80), nullable=False, unique=True, index=True, comment="数据来源（幂等）")
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_kaoyan_adm_detail_sy", "school_id", "year"),
        Index("ix_kaoyan_adm_detail_name", "name"),
    )


class KaoyanScoreLine(Base):
    """择校数据中心·年度分数线"""
    __tablename__ = "kaoyan_scorelines"
    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(Integer, ForeignKey("kaoyan_schools.id"), nullable=False, index=True)
    major_id = Column(Integer, ForeignKey("kaoyan_majors.id"), nullable=True, index=True)
    year = Column(Integer, nullable=False, index=True, comment="年度")
    total_line = Column(Integer, nullable=True, comment="总分线")
    politics_line = Column(Integer, nullable=True, comment="政治线")
    english_line = Column(Integer, nullable=True, comment="英语线")
    math_line = Column(Integer, nullable=True, comment="数学线")
    major_line = Column(Integer, nullable=True, comment="专业课线")
    national_line = Column(Integer, nullable=True, comment="国家线")
    retest_line = Column(Integer, nullable=True, comment="校复试线")
    line_type = Column(String(20), nullable=True, comment="类型")
    source = Column(String(50), nullable=True, index=True, comment="来源标记：yz.chsi.com.cn / school_official / csv_sample / txkyer.cn / unverified")
    major_code = Column(String(20), nullable=True, comment="专业代码（kaoyan.cn 逐专业分数线口径）")
    major_name = Column(String(120), nullable=True)
    depart_name = Column(String(120), nullable=True, comment="招生院系")
    degree_type = Column(String(20), nullable=True, comment="专业型/学术型")
    note = Column(Text, nullable=True, comment="接口备注（如 EMBA 特殊线）")
    special_remark = Column(Text, nullable=True)
    diff_total = Column(Integer, nullable=True, comment="院线总分 - 国家线（掌上考研口径）")
    source_id = Column(String(64), nullable=True, index=True, comment="数据源行 id，跨年唯一")
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_kaoyan_sl_school_year", "school_id", "year"),
        Index("ix_kaoyan_sl_major_year", "major_id", "year"),
    )


class KaoyanSubject(Base):
    """择校数据中心·学科分类"""
    __tablename__ = "kaoyan_subjects"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), nullable=False, unique=True, index=True, comment="学科代码")
    name = Column(String(100), nullable=False, comment="学科名称")
    category = Column(String(50), nullable=True, comment="门类")
    parent_code = Column(String(20), nullable=True, comment="上级学科代码")
    exam_overlap = Column(String(300), nullable=True, comment="考试科目交叉")
    description = Column(Text, nullable=True, comment="学科简介")
    sort_order = Column(Integer, default=0, comment="排序")
    created_at = Column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------- #
# 学习行为事件埋点（module B / V4.0 §7.2）
# --------------------------------------------------------------------------- #
class StudyEvent(Base):
    """学习行为事件埋点表（答题/学习动作流水）。"""

    __tablename__ = "study_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True,
                     comment="归属用户 ID（个人数据隔离）")
    event_type = Column(String(50), nullable=False, index=True, comment="事件类型：answer/submit/review/study 等")
    subject = Column(String(50), nullable=True, index=True, comment="科目")
    chapter_id = Column(Integer, nullable=True, comment="章节 ID")
    knowledge_point_id = Column(Integer, nullable=True, comment="知识点 ID")
    question_id = Column(Integer, nullable=True, comment="题目 ID")
    session_id = Column(Integer, nullable=True, comment="会话 ID")
    is_correct = Column(Boolean, nullable=True, comment="是否答对")
    duration_seconds = Column(Integer, nullable=True, comment="耗时（秒）")
    payload = Column(JSON, nullable=True, comment="扩展载荷 JSON")
    occurred_at = Column(DateTime, nullable=False, index=True, comment="事件发生时间")
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_study_events_type_time", "event_type", "occurred_at"),
        Index("ix_study_events_question", "question_id"),
    )


# --------------------------------------------------------------------------- #
# 三层可审计记忆（55 号方案 P0-1，DeepTutor DPM/Trace Forest 借鉴）
# --------------------------------------------------------------------------- #
class MemoryTrace(Base):
    """L1 原始轨迹：AI 交互/学习行为的证据快照（append-only）。"""

    __tablename__ = "memory_traces"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True,
                     comment="归属用户 ID")
    trace_type = Column(PgEnumAware("memory_trace_type", 20), nullable=False, default="qa",
                        comment="qa/tutoring/grading/study/document/feedback")
    subject = Column(String(50), nullable=True, comment="科目")
    question_id = Column(BigInteger, ForeignKey("quiz_questions.id", ondelete="SET NULL"), nullable=True,
                         comment="题目 ID")
    document_id = Column(BigInteger, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True,
                         comment="文档 ID")
    session_id = Column(BigInteger, nullable=True, comment="AI 对话/模考会话 ID（逻辑关联）")
    title = Column(String(200), nullable=False, comment="人类可读摘要")
    payload = Column(RawJSON, nullable=False, default=dict, comment="原始上下文快照 JSON")
    occurred_at = Column(DateTime, nullable=False, index=True, comment="事件发生时间")
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_memory_traces_user_time", "user_id", "occurred_at"),
        Index("ix_memory_traces_user_type", "user_id", "trace_type", "occurred_at"),
        Index("ix_memory_traces_question", "question_id"),
        Index("ix_memory_traces_document", "document_id"),
    )


class MemoryFact(Base):
    """L2 摘要事实：LLM 从 L1 轨迹蒸馏出的可溯源结论，可用户纠错。"""

    __tablename__ = "memory_facts"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True,
                     comment="归属用户 ID")
    fact_type = Column(String(50), nullable=False, default="weakness",
                       comment="weakness/strength/preference/progress")
    subject = Column(String(50), nullable=True, comment="科目")
    knowledge_point_id = Column(BigInteger, ForeignKey("knowledge_points.id", ondelete="SET NULL"),
                              nullable=True, comment="知识点 ID")
    kp_name = Column(String(100), nullable=True, comment="知识点名称快照")
    claim = Column(Text, nullable=False, comment="事实陈述")
    confidence = Column(Float, default=0.5, comment="0~1 置信度")
    evidence = Column(RawJSON, nullable=False, default=list, comment="[{trace_id, kind, snippet}]")
    source_layer = Column(PgEnumAware("memory_source_layer", 20), nullable=False, default="l2_fact")
    user_corrected = Column(Boolean, nullable=False, default=False, comment="用户是否已纠正")
    corrected_claim = Column(Text, nullable=True, comment="用户纠正后的事实陈述")
    corrected_at = Column(DateTime, nullable=True, comment="纠正时间")
    original_claim = Column(Text, nullable=True, comment="原始 claim 快照")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        Index("ix_memory_facts_user_type", "user_id", "fact_type", "updated_at"),
        Index("ix_memory_facts_user_kp", "user_id", "knowledge_point_id"),
        Index("ix_memory_facts_user_corrected", "user_id", "user_corrected"),
    )


class MemorySynthesis(Base):
    """L3 综合画像：跨场景聚合的学习结论，可用户纠错。"""

    __tablename__ = "memory_synthesis"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True,
                     comment="归属用户 ID")
    synth_type = Column(String(50), nullable=False, default="profile",
                        comment="profile/weakness_map/study_plan")
    title = Column(String(200), nullable=False, comment="综合结论标题")
    summary = Column(Text, nullable=False, comment="综合结论")
    detail = Column(RawJSON, nullable=False, default=dict, comment="结构化明细")
    fact_ids = Column(RawJSON, nullable=False, default=list, comment="引用的 L2 fact id 数组")
    source_layer = Column(PgEnumAware("memory_source_layer", 20), nullable=False, default="l3_synthesis")
    user_corrected = Column(Boolean, nullable=False, default=False, comment="用户是否已纠正")
    corrected_summary = Column(Text, nullable=True, comment="用户纠正后的结论文本")
    corrected_at = Column(DateTime, nullable=True, comment="纠正时间")
    original_summary = Column(Text, nullable=True, comment="原始结论快照")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        Index("ix_memory_synthesis_user", "user_id", "updated_at"),
    )


# --------------------------------------------------------------------------- #
# 规划体系里程碑（module B / V4.0 §8.1）
# --------------------------------------------------------------------------- #
class Milestone(Base):
    """考研规划 18 节点里程碑表。"""

    __tablename__ = "milestones"

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False, index=True, comment="考研年份（如 2027）")
    name = Column(String(100), nullable=False, comment="节点名称（如 预报名/初试）")
    category = Column(String(50), nullable=False, comment="类型：招生/大纲/报名/确认/命题/准考证/初试/阅卷/查分/院校线/国家线/复试/调剂/体检/政审/录取")
    start_date = Column(Date, nullable=True, comment="起始日期")
    end_date = Column(Date, nullable=True, comment="结束日期")
    importance = Column(Integer, default=2, comment="重要度 1-5")
    action = Column(Text, nullable=True, comment="该做什么")
    pitfalls = Column(Text, nullable=True, comment="不这么做会吃亏")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("year", "name", name="uq_milestone_year_name"),
    )


# --------------------------------------------------------------------------- #
class KaoyanCollectionRun(Base):
    """C5: 数据采集版本记录（一次爬取/导入/补全 = 一个版本）。"""

    __tablename__ = "kaoyan_collection_runs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), nullable=False, comment="来源：spider_yz / spider_school / csv / supplement / manual")
    scope = Column(String(200), nullable=True, comment="采集范围（省份代码/院校/文件名）")
    item_type = Column(String(30), nullable=True, comment="数据类型：school / scoreline / admission / question / all")
    row_count = Column(Integer, default=0, comment="本次新增/处理条数")
    detail = Column(JSON, nullable=True, comment="附加明细 JSON")
    status = Column(String(20), default="success", comment="success / failed / partial")
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_kaoyan_cr_source_time", "source", "created_at"),
    )


class SchoolAlias(Base):
    """院校名称别名归一化表（动态数据源 D4）。

    用于"清华→清华大学、贵大→贵州大学"等简称/别名到标准校名的映射，
    支持 keyword 搜索命中别名、推荐结果展示归一化名称。
    """

    __tablename__ = "school_aliases"

    id = Column(Integer, primary_key=True, index=True)
    alias = Column(String(100), nullable=False, unique=True, index=True, comment="别名/简称")
    school_id = Column(Integer, ForeignKey("kaoyan_schools.id"), nullable=False, index=True, comment="标准院校ID")
    school_name = Column(String(200), nullable=True, comment="标准院校名称（冗余，便于展示）")
    alias_type = Column(String(20), default="common", comment="common(常用简称) / abbr(缩写) / old(旧称)")
    created_at = Column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------- #
# 科目体系配置（V8 阶段1）：内置默认 + 用户自定义科目字典
# --------------------------------------------------------------------------- #
class SubjectConfig(Base):
    """科目配置表：科目的唯一字典（章节 / 题型 / 是否自定义）。

    - 内置默认行（is_custom=False）：由 services.taxonomy.ensure_subject_config_seeds
      从 CORE+MAJOR+EXT 合并去重后幂等播种；
    - 用户自定义行（is_custom=True）：由 POST /api/taxonomy/subjects 新增。

    本表只是"科目字典 / 配置"：删除配置行**不影响** quiz_questions /
    error_records 等业务表里既有的科目标签字符串（那些列保持原值不动）。
    全新增表，不改动任何既有表结构。
    """

    __tablename__ = "subject_config"

    #: 科目名（主键）。用户自定义科目**原样保留**，不归一到内置科目池。
    subject = Column(String(100), primary_key=True, index=True, comment="科目名（主键，自定义科目原样保留）")
    #: 章节列表 JSON（任意字符串数组）
    chapters = Column(JSON, nullable=True, comment="章节列表 JSON")
    #: 题型列表 JSON（建议枚举 single/judge/fill/essay/calc/draw）
    question_types = Column(JSON, nullable=True, comment="题型列表 JSON")
    #: 是否用户自定义（False=内置默认种子）
    is_custom = Column(Boolean, default=False, nullable=False, comment="是否用户自定义")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)



# --------------------------------------------------------------------------- #
# 用户与角色（doc 11 F11-01）
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), nullable=False, unique=True, comment="登录名")
    password_hash = Column(String(255), nullable=False, comment="PBKDF2 哈希，库内无明文")
    display_name = Column(String(64), nullable=True, comment="显示名")
    role = Column(String(16), nullable=False, default="user", comment="admin | user")
    is_active = Column(Boolean, nullable=False, default=True, comment="禁用即会话失效")
    must_change_password = Column(Boolean, nullable=False, default=False, comment="首登/重置后强制改密")
    # 改密/重置/禁用时自增，旧 token 里的版本号对不上即失效（无需维护黑名单）
    token_version = Column(Integer, nullable=False, default=0, comment="会话版本号")
    last_login_at = Column(DateTime, nullable=True, comment="最近登录（UTC）")
    # 软删除时间戳：非空=已删除（列表隐藏/登录拒绝/用户名仍占用）。清空即恢复。
    # 用户不能物理删除的原因见 core/sql/107 头注释（关联学习数据不可逆丢失）。
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间戳（NULL=正常）")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_users_role_active", "role", "is_active"),
        Index("ix_users_live", "id", postgresql_where=text("deleted_at IS NULL")),
    )


# --------------------------------------------------------------------------- #
# OCR / 采集管线数据模型（docx/34-OCR与数据采集开源方案 §6）
#
# 这一层是「块级文档数据模型」：documents 存整篇，document_pages 存页，
# document_blocks 存版面块，question_images 存题目配图；crawl_* 是采集侧的任务表。
# 写入方是 services/ingest_pipeline.py（页/块/配图）与采集 worker（crawl_*）。
# 约定：页码一律 1 基（与 services/parsers/base.py 的 ParsedPage.page_no 同基线）。
# --------------------------------------------------------------------------- #
class DocumentPage(Base):
    """文档页级数据（docx/34 §6 document_pages）。"""

    __tablename__ = "document_pages"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False,
                         index=True, comment="来源文档 ID")
    page_no = Column(Integer, nullable=False, comment="物理页码（1 基）")
    width = Column(Float, nullable=True, comment="页宽（渲染像素）")
    height = Column(Float, nullable=True, comment="页高（渲染像素）")
    text = Column(Text, nullable=True, comment="整页文本")
    layout_json = Column(RawJSON, nullable=True, comment="版面结构 JSON")
    image_path = Column(String(1000), nullable=True, comment="整页图相对路径")
    ocr_engine = Column(String(50), nullable=True, comment="解析引擎：mineru/paddle/rapidocr/digital")
    ocr_confidence = Column(Float, nullable=True, comment="页级置信度 0-1")
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("document_id", "page_no", name="uq_document_pages_doc_page"),
        Index("ix_document_pages_doc_page", "document_id", "page_no"),
    )


class DocumentBlock(Base):
    """文档版面块级数据（docx/34 §6 document_blocks）。"""

    __tablename__ = "document_blocks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False,
                         index=True, comment="来源文档 ID")
    page_no = Column(Integer, nullable=False, comment="物理页码（1 基）")
    block_id = Column(String(64), nullable=True, comment="解析引擎给出的块 ID")
    block_type = Column(String(32), nullable=True, index=True,
                        comment="块类型：text/title/table/figure/formula/list/header/footer/page_no/unknown")
    bbox = Column(RawJSON, nullable=True, comment="bbox JSON：[x0,y0,x1,y1]")
    text = Column(Text, nullable=True, comment="块文本")
    latex = Column(Text, nullable=True, comment="块内公式 LaTeX")
    image_path = Column(String(1000), nullable=True, comment="块图相对路径（figure 块）")
    reading_order = Column(Integer, nullable=True, comment="阅读顺序")
    confidence = Column(Float, nullable=True, comment="块级置信度 0-1")
    # 块级质检留痕：math_corrupted（公式被 OCR 读坏）/ math_suspect /
    # ocr_confidence_missing（后端没给置信度）等标记。用于把坏块挑出来重解析：
    #   SELECT * FROM document_blocks WHERE extra->>'math_corrupted' = 'true'
    extra = Column(RawJSON, nullable=True, comment="块级附加信息 JSON（质检标记等）")
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_document_blocks_doc_page", "document_id", "page_no"),
    )


class QuestionImage(Base):
    """题目配图（docx/34 §6 question_images）：quiz_questions.images 的规范化多图表。

    与 ``quiz_questions.images`` 的分工：JSON 列是**渲染用的快路径**（前端直接读），
    本表是**可追溯的明细**：谁裁的、哪一页、bbox 多大、是不是主图。
    """

    __tablename__ = "question_images"

    id = Column(Integer, primary_key=True, index=True)
    # 题目入库前先落图（题目还没写进 quiz_questions），故允许为空，入库后回填。
    question_id = Column(Integer, ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=True,
                         index=True, comment="题目 ID（题目入库后回填）")
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True,
                         index=True, comment="来源文档 ID")
    page_no = Column(Integer, nullable=True, comment="物理页码（1 基）")
    image_path = Column(String(1000), nullable=True, comment="图片相对路径")
    image_hash = Column(String(64), nullable=True, index=True, comment="图片内容 sha256")
    phash = Column(String(32), nullable=True, index=True, comment="感知哈希（去重用）")
    bbox = Column(RawJSON, nullable=True, comment="bbox JSON：[x0,y0,x1,y1]")
    image_kind = Column(String(32), nullable=True, comment="figure_crop/page_thumb/equation/table")
    caption = Column(String(1000), nullable=True, comment="图注文本")
    width = Column(Integer, nullable=True, comment="图宽（像素）")
    height = Column(Integer, nullable=True, comment="图高（像素）")
    is_primary = Column(Boolean, nullable=False, default=False, server_default="false",
                        comment="是否主图（同一题中面积最大者）")
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class CrawlJob(Base):
    """采集任务（docx/34 §6 crawl_jobs）。"""

    __tablename__ = "crawl_jobs"

    id = Column(Integer, primary_key=True, index=True)
    source_key = Column(String(64), nullable=False, index=True, comment="来源键（站点/栏目标识）")
    school_id = Column(Integer, ForeignKey("kaoyan_schools.id", ondelete="SET NULL"), nullable=True,
                       index=True, comment="关联院校 ID")
    url = Column(String(1024), nullable=True, comment="任务 URL")
    job_type = Column(String(32), nullable=True, comment="任务类型：list/detail/schedule")
    status = Column(String(16), nullable=False, default="pending", index=True,
                    comment="状态：pending/running/done/failed")
    attempts = Column(Integer, nullable=False, default=0, server_default="0", comment="已尝试次数")
    next_run_at = Column(DateTime(timezone=True), nullable=True, index=True, comment="下次执行时间")
    last_error = Column(Text, nullable=True, comment="最近一次错误")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class CrawlPage(Base):
    """采集到的页面（docx/34 §6 crawl_pages）。"""

    __tablename__ = "crawl_pages"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("crawl_jobs.id", ondelete="SET NULL"), nullable=True,
                    index=True, comment="来源任务 ID")
    url = Column(String(1024), nullable=True, comment="原始 URL")
    canonical_url = Column(String(1024), nullable=True, unique=True, index=True, comment="规范化 URL（去重用）")
    title = Column(String(512), nullable=True, comment="页面标题")
    publish_date = Column(Date, nullable=True, comment="发布日期")
    html_path = Column(String(1000), nullable=True, comment="HTML 落盘相对路径")
    text = Column(Text, nullable=True, comment="抽取正文")
    content_hash = Column(String(64), nullable=True, index=True, comment="正文 sha256（增量去重用）")
    simhash = Column(String(32), nullable=True, index=True, comment="正文 simhash（近似去重用）")
    fetched_at = Column(DateTime(timezone=True), nullable=True, comment="抓取时间")


class CrawlDeadLetter(Base):
    """采集死信（docx/34 §6 crawl_dead_letters）：超过重试次数的任务留档。"""

    __tablename__ = "crawl_dead_letters"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("crawl_jobs.id", ondelete="SET NULL"), nullable=True,
                    index=True, comment="来源任务 ID")
    url = Column(String(1024), nullable=True, comment="失败 URL")
    source_key = Column(String(64), nullable=True, index=True, comment="来源键")
    error = Column(Text, nullable=True, comment="错误详情")
    attempts = Column(Integer, nullable=False, default=0, server_default="0", comment="已尝试次数")
    payload = Column(RawJSON, nullable=True, comment="失败时的任务负载 JSON")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
