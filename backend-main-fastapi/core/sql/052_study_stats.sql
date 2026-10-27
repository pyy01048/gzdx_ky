-- =============================================================================
-- 052 学习统计与节点：学习会话 / 每日统计 / 事件流 / 考研节点 / 错因模式库
-- 依赖：000 / 010 / 020 / 030 / 040 / 050
-- =============================================================================

-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS study_sessions (
    id         BIGSERIAL   PRIMARY KEY,
    date       DATE        NOT NULL,
    duration   INTEGER     NOT NULL DEFAULT 0,
    subject_id BIGINT      REFERENCES subjects(id) ON DELETE SET NULL,
    subject    VARCHAR(50),
    task_type  VARCHAR(50),
    remark     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  study_sessions IS '学习会话流水表';
COMMENT ON COLUMN study_sessions.subject_id IS '权威科目外键';
COMMENT ON COLUMN study_sessions.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN study_sessions.duration IS '学习时长（分钟）';

CREATE INDEX IF NOT EXISTS idx_study_sessions_date ON study_sessions (date DESC, subject_id);

CREATE TABLE IF NOT EXISTS study_stats (
    id                   BIGSERIAL PRIMARY KEY,
    date                 DATE     NOT NULL,
    total_duration       INTEGER  NOT NULL DEFAULT 0,
    subject_durations    JSONB    NOT NULL DEFAULT '{}'::jsonb,
    task_completed       INTEGER  NOT NULL DEFAULT 0,
    error_count          INTEGER  NOT NULL DEFAULT 0,
    new_knowledge_count  INTEGER  NOT NULL DEFAULT 0,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_study_stats_date UNIQUE (date)
);

COMMENT ON TABLE  study_stats IS '每日学习统计聚合表';
COMMENT ON COLUMN study_stats.subject_durations IS '各科时长（JSON 对象，key 为科目 code）';
COMMENT ON COLUMN study_stats.new_knowledge_count IS '当日新增知识点数';

CREATE TABLE IF NOT EXISTS study_events (
    id                 BIGSERIAL   PRIMARY KEY,
    event_type         VARCHAR(50) NOT NULL,
    subject_id         BIGINT      REFERENCES subjects(id) ON DELETE SET NULL,
    subject            VARCHAR(50),
    chapter_id         BIGINT      REFERENCES subject_chapters(id) ON DELETE SET NULL,
    knowledge_point_id BIGINT      REFERENCES knowledge_points(id) ON DELETE SET NULL,
    question_id        BIGINT      REFERENCES quiz_questions(id) ON DELETE SET NULL,
    session_id         BIGINT,
    is_correct         BOOLEAN,
    duration_seconds   INTEGER,
    payload            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    occurred_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_study_event_duration CHECK (duration_seconds IS NULL OR duration_seconds >= 0)
);

COMMENT ON TABLE  study_events IS '学习事件流：所有学习行为的统一事件日志，供统计与回放';
COMMENT ON COLUMN study_events.event_type IS '事件类型：answer / review / focus / plan 等';
COMMENT ON COLUMN study_events.subject_id IS '权威科目外键';
COMMENT ON COLUMN study_events.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN study_events.payload IS '事件附加数据（JSON 对象）';
COMMENT ON COLUMN study_events.occurred_at IS '事件发生时间（UTC，带时区），统计以此列为准';
COMMENT ON COLUMN study_events.created_at IS '入库时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_study_events_time ON study_events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_study_events_type ON study_events (event_type, occurred_at DESC);

-- --------------------------------------------------------------------------- #
-- 考研关键节点
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS milestones (
    id         BIGSERIAL    PRIMARY KEY,
    year       INTEGER      NOT NULL,
    name       VARCHAR(200) NOT NULL,
    category   VARCHAR(50)  NOT NULL,
    start_date DATE,
    end_date   DATE,
    importance SMALLINT     NOT NULL DEFAULT 2,
    action     TEXT,
    pitfalls   TEXT,
    is_active  BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_milestone UNIQUE (year, name),
    CONSTRAINT ck_milestone_importance CHECK (importance BETWEEN 1 AND 5)
);

COMMENT ON TABLE  milestones IS '考研关键节点表：报名/确认/打印准考证/初试/出分/复试';
COMMENT ON COLUMN milestones.year IS '考试年份';
COMMENT ON COLUMN milestones.category IS '节点分类：报名 / 考试 / 成绩 / 复试';
COMMENT ON COLUMN milestones.importance IS '重要级 1-5';
COMMENT ON COLUMN milestones.action IS '应做动作';
COMMENT ON COLUMN milestones.pitfalls IS '常见坑提示';

-- --------------------------------------------------------------------------- #
-- 错因模式库
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS misconceptions (
    id                 BIGSERIAL PRIMARY KEY,
    question_id        BIGINT    REFERENCES quiz_questions(id) ON DELETE SET NULL,
    error_record_id    BIGINT    REFERENCES error_records(id) ON DELETE SET NULL,
    knowledge_point_id BIGINT    REFERENCES knowledge_points(id) ON DELETE SET NULL,
    pattern            TEXT      NOT NULL,
    category           VARCHAR(50),
    suggestion         TEXT,
    evidence           TEXT,
    synced_at          TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  misconceptions IS '错因模式库：归纳高频错误模式并给出改进建议';
COMMENT ON COLUMN misconceptions.pattern IS '错误模式描述';
COMMENT ON COLUMN misconceptions.category IS '错误分类：概念不清 / 计算失误 / 审题偏差 / 方法不当';
COMMENT ON COLUMN misconceptions.suggestion IS '改进建议';
COMMENT ON COLUMN misconceptions.evidence IS '支撑证据（引用题目或对话片段）';
COMMENT ON COLUMN misconceptions.synced_at IS '最近一次从外部知识库同步的时间';

CREATE INDEX IF NOT EXISTS idx_misconceptions_kp ON misconceptions (knowledge_point_id);
