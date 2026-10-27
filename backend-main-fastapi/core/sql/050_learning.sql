-- =============================================================================
-- 050 学习行为域：目标 / 任务 / 计划 / 复习 / 错题 / 卡片 / 专注
-- 依赖：000 / 010 / 020 / 030 / 040
--
-- 关键设计（解决问题 6「时间口径两套」）：
--   review_schedules 是复习调度的**唯一权威**。所有下次复习时间必须由后端计算并
--   落库，前端 localStorage 只允许作为离线缓存读取，不允许反向写回判定。
--   各业务表（tasks / error_records / flashcards）保留 next_review 兼容列，
--   由触发器从 review_schedules 单向同步，保证"只有一个真值源"。
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- 复习调度权威表
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS review_schedules (
    id            BIGSERIAL   PRIMARY KEY,
    item_type     VARCHAR(30) NOT NULL,
    item_id       BIGINT      NOT NULL,
    algorithm     VARCHAR(30) NOT NULL DEFAULT 'sm2',
    ease_factor   REAL        NOT NULL DEFAULT 2.5,
    interval_days INTEGER     NOT NULL DEFAULT 0,
    repetitions   INTEGER     NOT NULL DEFAULT 0,
    lapses        INTEGER     NOT NULL DEFAULT 0,
    last_reviewed_at TIMESTAMPTZ,
    next_review_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_review_schedule UNIQUE (item_type, item_id),
    CONSTRAINT ck_schedule_interval CHECK (interval_days >= 0),
    CONSTRAINT ck_schedule_ease CHECK (ease_factor >= 1.3 AND ease_factor <= 3.5)
);

COMMENT ON TABLE  review_schedules IS '复习调度唯一权威表：前端 localStorage 只作缓存，不得反向写回';
COMMENT ON COLUMN review_schedules.item_type IS '复习对象类型：task / error_record / flashcard / knowledge_point';
COMMENT ON COLUMN review_schedules.item_id IS '复习对象 ID';
COMMENT ON COLUMN review_schedules.algorithm IS '调度算法：sm2 / ebbinghaus';
COMMENT ON COLUMN review_schedules.ease_factor IS 'SM-2 难度因子 1.3-3.5';
COMMENT ON COLUMN review_schedules.interval_days IS '当前复习间隔（天）';
COMMENT ON COLUMN review_schedules.repetitions IS '连续答对次数';
COMMENT ON COLUMN review_schedules.lapses IS '遗忘次数';
COMMENT ON COLUMN review_schedules.last_reviewed_at IS '上次复习时间（UTC）';
COMMENT ON COLUMN review_schedules.next_review_at IS '下次复习时间（UTC），到期判定以此列为准';
COMMENT ON COLUMN review_schedules.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN review_schedules.updated_at IS '最后更新时间';

-- 到期复习主查询索引
CREATE INDEX IF NOT EXISTS idx_review_schedules_due ON review_schedules (next_review_at) WHERE next_review_at IS NOT NULL;

CREATE OR REPLACE TRIGGER trg_review_schedules_updated BEFORE UPDATE ON review_schedules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 考研目标
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS goals (
    id                 BIGSERIAL    PRIMARY KEY,
    exam_date          DATE,
    total_score_target SMALLINT,
    politics_target    SMALLINT,
    english_target     SMALLINT,
    math_target        SMALLINT,
    major_target       SMALLINT,
    university         VARCHAR(200),
    major              VARCHAR(200),
    remark             TEXT,
    -- 备考科目改为外键数组风格：这里用 JSONB 存 code 列表，元素须能在 subjects.code 中找到
    subject_codes      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    support_subject_codes JSONB     NOT NULL DEFAULT '[]'::jsonb,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  goals IS '考研目标表：目标院校专业与各科分数目标';
COMMENT ON COLUMN goals.exam_date IS '考试日期';
COMMENT ON COLUMN goals.total_score_target IS '总分目标';
COMMENT ON COLUMN goals.politics_target IS '政治目标分';
COMMENT ON COLUMN goals.english_target IS '英语目标分';
COMMENT ON COLUMN goals.math_target IS '数学目标分';
COMMENT ON COLUMN goals.major_target IS '专业课目标分';
COMMENT ON COLUMN goals.university IS '目标院校';
COMMENT ON COLUMN goals.major IS '目标专业';
COMMENT ON COLUMN goals.remark IS '备注';
COMMENT ON COLUMN goals.subject_codes IS '备考科目权威代码数组，元素须存在于 subjects.code';
COMMENT ON COLUMN goals.support_subject_codes IS '专业课支撑科目代码数组（可能涉及但未必考）';
COMMENT ON COLUMN goals.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN goals.updated_at IS '最后更新时间';

CREATE OR REPLACE TRIGGER trg_goals_updated BEFORE UPDATE ON goals
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 任务
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS tasks (
    id           BIGSERIAL   PRIMARY KEY,
    title        VARCHAR(300) NOT NULL,
    subject_id   BIGINT      REFERENCES subjects(id) ON DELETE SET NULL,
    subject      VARCHAR(50),
    chapter_id   BIGINT      REFERENCES subject_chapters(id) ON DELETE SET NULL,
    task_type    VARCHAR(50),
    stage        prep_stage,
    status       task_status NOT NULL DEFAULT 'pending',
    due_date     DATE,
    priority     SMALLINT    NOT NULL DEFAULT 0,
    next_review  TIMESTAMPTZ,
    review_count INTEGER     NOT NULL DEFAULT 0,
    completed_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_tasks_priority CHECK (priority BETWEEN 0 AND 5)
);

COMMENT ON TABLE  tasks IS '学习任务表：支持艾宾浩斯复习调度';
COMMENT ON COLUMN tasks.subject_id IS '权威科目外键';
COMMENT ON COLUMN tasks.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN tasks.chapter_id IS '权威章节外键';
COMMENT ON COLUMN tasks.stage IS '备考阶段：basic 基础 / intensive 强化 / sprint 冲刺 / retest 复试';
COMMENT ON COLUMN tasks.status IS '任务状态：pending / doing / done / cancelled';
COMMENT ON COLUMN tasks.next_review IS '下次复习时间（UTC），兼容列，真值在 review_schedules';
COMMENT ON COLUMN tasks.review_count IS '已复习次数';
COMMENT ON COLUMN tasks.completed_at IS '完成时间';
COMMENT ON COLUMN tasks.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN tasks.updated_at IS '最后更新时间';

CREATE INDEX IF NOT EXISTS idx_tasks_status  ON tasks (status, due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_subject ON tasks (subject_id);
CREATE INDEX IF NOT EXISTS idx_tasks_review  ON tasks (next_review) WHERE next_review IS NOT NULL;

CREATE OR REPLACE TRIGGER trg_tasks_updated BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 复习记录：掌握度派生的另一核心数据源
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS review_records (
    id             BIGSERIAL   PRIMARY KEY,
    item_type      VARCHAR(20) NOT NULL,
    item_id        BIGINT      NOT NULL,
    subject_id     BIGINT      REFERENCES subjects(id) ON DELETE SET NULL,
    subject        VARCHAR(50),
    chapter        VARCHAR(200),
    result         review_result,
    grade          SMALLINT    NOT NULL DEFAULT 0,
    mastery_before SMALLINT    NOT NULL DEFAULT 0,
    mastery_after  SMALLINT    NOT NULL DEFAULT 0,
    duration       INTEGER     NOT NULL DEFAULT 0,
    interval_after INTEGER     NOT NULL DEFAULT 0,
    next_review    TIMESTAMPTZ,
    note           TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_review_grade CHECK (grade BETWEEN 0 AND 5),
    CONSTRAINT ck_review_mastery CHECK (
        mastery_before BETWEEN 0 AND 100 AND mastery_after BETWEEN 0 AND 100)
);

COMMENT ON TABLE  review_records IS '复习记录表：每次复习的评分与掌握度变化留痕';
COMMENT ON COLUMN review_records.item_type IS '复习对象类型：task / error_record / flashcard / knowledge_point';
COMMENT ON COLUMN review_records.item_id IS '复习对象 ID';
COMMENT ON COLUMN review_records.subject_id IS '权威科目外键';
COMMENT ON COLUMN review_records.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN review_records.result IS 'SM-2 评分档位：again / hard / good / easy';
COMMENT ON COLUMN review_records.grade IS '评分 0-5';
COMMENT ON COLUMN review_records.mastery_before IS '复习前掌握度 0-100';
COMMENT ON COLUMN review_records.mastery_after IS '复习后掌握度 0-100';
COMMENT ON COLUMN review_records.next_review IS '本次复习后计算出的下次复习时间（UTC）';
COMMENT ON COLUMN review_records.created_at IS '复习时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_review_records_item  ON review_records (item_type, item_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_records_subj  ON review_records (subject_id, created_at DESC);

-- --------------------------------------------------------------------------- #
-- 错题
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS error_records (
    id                BIGSERIAL   PRIMARY KEY,
    question_id       BIGINT      REFERENCES quiz_questions(id) ON DELETE SET NULL,
    content           TEXT,
    my_answer         TEXT,
    correct_answer    TEXT,
    error_reason      VARCHAR(200),
    error_category    VARCHAR(50),
    subject_id        BIGINT      REFERENCES subjects(id) ON DELETE SET NULL,
    subject           VARCHAR(50),
    knowledge_point_id BIGINT     REFERENCES knowledge_points(id) ON DELETE SET NULL,
    accuracy          REAL,
    review_count      INTEGER     NOT NULL DEFAULT 0,
    last_review       TIMESTAMPTZ,
    next_review       TIMESTAMPTZ,
    status            VARCHAR(50) NOT NULL DEFAULT 'unreviewed',
    mastery_level     mastery_level NOT NULL DEFAULT 'not_mastered',
    tags              JSONB       NOT NULL DEFAULT '[]'::jsonb,
    analysis          TEXT,
    -- SM-2 状态（冗余，权威在 review_schedules）
    ease_factor       REAL        NOT NULL DEFAULT 2.5,
    interval_days     INTEGER     NOT NULL DEFAULT 0,
    repetitions       INTEGER     NOT NULL DEFAULT 0,
    lapses            INTEGER     NOT NULL DEFAULT 0,
    pass_number       INTEGER     NOT NULL DEFAULT 1,
    recent_weight     REAL        NOT NULL DEFAULT 1.0,
    user_note         TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_error_accuracy CHECK (accuracy IS NULL OR (accuracy >= 0 AND accuracy <= 1))
);

COMMENT ON TABLE  error_records IS '错题表：记录错误原因、掌握状态与复习调度';
COMMENT ON COLUMN error_records.question_id IS '关联题目 ID，题目删除时置空保留错题';
COMMENT ON COLUMN error_records.subject_id IS '权威科目外键';
COMMENT ON COLUMN error_records.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN error_records.knowledge_point_id IS '关联知识点 ID';
COMMENT ON COLUMN error_records.accuracy IS '该错题的历史正确率 0-1';
COMMENT ON COLUMN error_records.status IS '处理状态：unreviewed / reviewing / mastered';
COMMENT ON COLUMN error_records.mastery_level IS '掌握等级：not_mastered / learning / reviewing / mastered';
COMMENT ON COLUMN error_records.tags IS '错题标签数组';
COMMENT ON COLUMN error_records.pass_number IS '当前轮次（第几遍刷）';
COMMENT ON COLUMN error_records.recent_weight IS '近期权重，用于掌握度时间衰减加权';
COMMENT ON COLUMN error_records.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN error_records.updated_at IS '最后更新时间';

CREATE INDEX IF NOT EXISTS idx_error_subject ON error_records (subject_id, next_review);
CREATE INDEX IF NOT EXISTS idx_error_kp      ON error_records (knowledge_point_id);
CREATE INDEX IF NOT EXISTS idx_error_due     ON error_records (next_review) WHERE next_review IS NOT NULL;

CREATE OR REPLACE TRIGGER trg_error_records_updated BEFORE UPDATE ON error_records
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS error_knowledge_links (
    id                 BIGSERIAL PRIMARY KEY,
    error_id           BIGINT    NOT NULL REFERENCES error_records(id) ON DELETE CASCADE,
    knowledge_point_id BIGINT    REFERENCES knowledge_points(id) ON DELETE CASCADE,
    chunk_id           BIGINT    REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
    document_id        BIGINT    REFERENCES documents(id) ON DELETE SET NULL,
    relevance          REAL      NOT NULL DEFAULT 0,
    source             VARCHAR(20) NOT NULL DEFAULT 'auto',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_error_kp UNIQUE (error_id, knowledge_point_id),
    CONSTRAINT ck_error_link_relevance CHECK (relevance >= 0 AND relevance <= 1)
);

COMMENT ON TABLE  error_knowledge_links IS '错题与知识点/分块/文档的关联，供错因归因与同类题推荐';
COMMENT ON COLUMN error_knowledge_links.error_id IS '错题 ID，错题删除时级联删除';
COMMENT ON COLUMN error_knowledge_links.relevance IS '相关度 0-1';
COMMENT ON COLUMN error_knowledge_links.source IS '关联来源：auto 自动 / manual 人工';
COMMENT ON COLUMN error_knowledge_links.created_at IS '创建时间（UTC，带时区）';

-- --------------------------------------------------------------------------- #
-- 记忆卡片 / 专注 / 艾宾浩斯 / 早起
