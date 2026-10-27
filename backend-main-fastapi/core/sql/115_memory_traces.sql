-- =============================================================================
-- 115_memory_traces.sql —— 三层可审计记忆（DeepTutor DPM/Trace Forest 借鉴）
--
-- 设计目标（55 号方案 P0-1）：
--   任何一条 AI 结论都可以一路追溯到原始证据：
--     L1 memory_traces     原始轨迹（append-only 事件流水，含上下文快照）
--     L2 memory_facts      摘要事实（LLM 定期蒸馏，带 trace_ids 引用）
--     L3 memory_synthesis  跨场景综合画像（薄弱点/偏好/进度结论）
--   用户可直接编辑纠正任意层级（前端「记忆图谱」面板）。
--
-- 与 study_events 的关系：
--   study_events 是"行为流水"（供统计/热力图），memory_traces 是"证据快照"
--   （供 AI 结论溯源）。两者互补：答疑/讲题/批改时写 memory_trace，
--   常规刷题打卡走既有 study_events 埋点。
--
-- 关键设计：
--   * trace_type 枚举：qa / tutoring / grading / study / document / feedback
--   * payload JSONB：原始上下文快照（题目、用户问题、AI 回答、引用）
--   * editable 纠错机制：L2/L3 均带 user_corrected / corrected_by 字段，
--     用户纠正后保留原值（original_value）以便审计
-- =============================================================================

-- 枚举：记忆轨迹类型（先建枚举，幂等）
DO $$ BEGIN
    CREATE TYPE memory_trace_type AS ENUM ('qa', 'tutoring', 'grading', 'study', 'document', 'feedback');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 枚举：记忆层级来源（幂等）
DO $$ BEGIN
    CREATE TYPE memory_source_layer AS ENUM ('l1_trace', 'l2_fact', 'l3_synthesis');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- =============================================================================
-- L1：原始轨迹表（append-only）
-- =============================================================================
CREATE TABLE IF NOT EXISTS memory_traces (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT REFERENCES users(id) ON DELETE CASCADE,
    trace_type     memory_trace_type NOT NULL DEFAULT 'qa',
    subject        VARCHAR(50),
    question_id    BIGINT REFERENCES quiz_questions(id) ON DELETE SET NULL,
    document_id    BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    session_id     BIGINT,               -- AI 对话/模考会话 ID（逻辑关联）
    title          VARCHAR(200) NOT NULL, -- 人类可读摘要（列表展示用）
    payload        JSONB NOT NULL DEFAULT '{}'::jsonb, -- 原始上下文快照
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_memory_trace_payload CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX IF NOT EXISTS ix_memory_traces_user_time
    ON memory_traces (user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_memory_traces_user_type
    ON memory_traces (user_id, trace_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_memory_traces_question
    ON memory_traces (question_id);
CREATE INDEX IF NOT EXISTS ix_memory_traces_document
    ON memory_traces (document_id);

COMMENT ON TABLE  memory_traces IS 'L1 原始轨迹：所有 AI 交互/学习行为的证据快照（append-only），供 L2/L3 溯源';
COMMENT ON COLUMN memory_traces.trace_type IS '轨迹类型：qa 答疑 / tutoring 讲题 / grading 批改 / study 学习 / document 资料 / feedback 用户反馈';
COMMENT ON COLUMN memory_traces.payload IS '原始上下文快照 JSON：题目、用户问题、AI 回答、检索引用、评分等';
COMMENT ON COLUMN memory_traces.title IS '人类可读摘要，用于记忆图谱列表展示';
COMMENT ON COLUMN memory_traces.occurred_at IS '事件发生时间（UTC）';
COMMENT ON COLUMN memory_traces.session_id IS 'AI 对话会话或模考会话 ID（逻辑关联，不设 FK）';

-- =============================================================================
-- L2：摘要事实表（LLM 定期蒸馏，带 trace 引用，可用户纠错）
-- =============================================================================
CREATE TABLE IF NOT EXISTS memory_facts (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT REFERENCES users(id) ON DELETE CASCADE,
    fact_type        VARCHAR(50) NOT NULL DEFAULT 'weakness', -- weakness/strength/preference/progress
    subject          VARCHAR(50),
    knowledge_point_id BIGINT REFERENCES knowledge_points(id) ON DELETE SET NULL,
    kp_name          VARCHAR(100),        -- 知识点名称快照（kp 可能被删）
    claim            TEXT NOT NULL,        -- 事实陈述（AI 认为你 xx 薄弱）
    confidence       REAL DEFAULT 0.5,     -- 0~1 置信度
    evidence         JSONB NOT NULL DEFAULT '[]'::jsonb, -- [{trace_id, kind, snippet}]
    source_layer     memory_source_layer NOT NULL DEFAULT 'l2_fact',
    -- 用户纠错字段：纠正后保留原值
    user_corrected    BOOLEAN NOT NULL DEFAULT FALSE,
    corrected_claim   TEXT,                 -- 用户纠正后的事实陈述
    corrected_at      TIMESTAMPTZ,
    original_claim    TEXT,                 -- 原始 claim（纠正前快照）
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_memory_fact_evidence CHECK (jsonb_typeof(evidence) = 'array')
);

CREATE INDEX IF NOT EXISTS ix_memory_facts_user_type
    ON memory_facts (user_id, fact_type, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_memory_facts_user_kp
    ON memory_facts (user_id, knowledge_point_id);
CREATE INDEX IF NOT EXISTS ix_memory_facts_user_corrected
    ON memory_facts (user_id, user_corrected);

COMMENT ON TABLE  memory_facts IS 'L2 摘要事实：LLM 从 L1 轨迹定期蒸馏出的可溯源结论，支持用户纠错';
COMMENT ON COLUMN memory_facts.claim IS '事实陈述（AI 认为你某知识点薄弱/擅长等）';
COMMENT ON COLUMN memory_facts.evidence IS '证据引用数组：[{trace_id, kind, snippet}]';
COMMENT ON COLUMN memory_facts.user_corrected IS '用户是否已纠正该事实';
COMMENT ON COLUMN memory_facts.corrected_claim IS '用户纠正后的事实陈述（权威）';
COMMENT ON COLUMN memory_facts.original_claim IS '纠正前的原始 claim（审计保留）';

-- =============================================================================
-- L3：综合画像表（跨场景结论）
-- =============================================================================
CREATE TABLE IF NOT EXISTS memory_synthesis (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT REFERENCES users(id) ON DELETE CASCADE,
    synth_type       VARCHAR(50) NOT NULL DEFAULT 'profile', -- profile/weakness_map/study_plan
    title            VARCHAR(200) NOT NULL,
    summary          TEXT NOT NULL,        -- 综合结论
    detail           JSONB NOT NULL DEFAULT '{}'::jsonb, -- 结构化明细
    fact_ids         JSONB NOT NULL DEFAULT '[]'::jsonb, -- 引用的 L2 fact id 数组
    source_layer     memory_source_layer NOT NULL DEFAULT 'l3_synthesis',
    user_corrected   BOOLEAN NOT NULL DEFAULT FALSE,
    corrected_summary TEXT,
    corrected_at   TIMESTAMPTZ,
    original_summary TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_memory_synthesis_user
    ON memory_synthesis (user_id, updated_at DESC);

COMMENT ON TABLE  memory_synthesis IS 'L3 综合画像：跨场景聚合出的学习结论（薄弱图谱/画像/计划），可用户纠错';
COMMENT ON COLUMN memory_synthesis.fact_ids IS '引用的 L2 事实 id 数组（溯源链）';
COMMENT ON COLUMN memory_synthesis.user_corrected IS '用户是否已纠正该综合结论';
COMMENT ON COLUMN memory_synthesis.corrected_summary IS '用户纠正后的结论文本';
COMMENT ON COLUMN memory_synthesis.original_summary IS '纠正前的原始结论（审计保留）';