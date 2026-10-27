-- =============================================================================
-- 041 试卷与模考：试卷 / 卷内题目 / 蓝图 / 场次 / 作答 / 答疑待办 / 答案候选
-- 依赖：000 / 010 / 020 / 030 / 040
-- =============================================================================

-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS papers (
    id          BIGSERIAL    PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    subject_id  BIGINT       REFERENCES subjects(id) ON DELETE SET NULL,
    subject     VARCHAR(50),
    description TEXT,
    rules       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    total_score INTEGER      NOT NULL DEFAULT 100,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_papers_score CHECK (total_score > 0)
);

COMMENT ON TABLE  papers IS '试卷表：组卷结果与规则';
COMMENT ON COLUMN papers.subject_id IS '权威科目外键';
COMMENT ON COLUMN papers.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN papers.rules IS '组卷规则（JSON 对象）：题型分布、难度分布、知识点范围';
COMMENT ON COLUMN papers.total_score IS '试卷总分';
COMMENT ON COLUMN papers.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN papers.updated_at IS '最后更新时间';

CREATE OR REPLACE TRIGGER trg_papers_updated BEFORE UPDATE ON papers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS paper_questions (
    id            BIGSERIAL PRIMARY KEY,
    paper_id      BIGINT    NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    question_id   BIGINT    REFERENCES quiz_questions(id) ON DELETE SET NULL,
    seq           INTEGER   NOT NULL DEFAULT 0,
    content       TEXT      NOT NULL,
    options       JSONB,
    answer        TEXT,
    analysis      TEXT,
    question_type question_type,
    difficulty    SMALLINT,
    score         INTEGER   NOT NULL DEFAULT 0,
    CONSTRAINT ck_paper_options CHECK (is_canonical_options(options)),
    CONSTRAINT ck_paper_score CHECK (score >= 0)
);

COMMENT ON TABLE  paper_questions IS '试卷题目关联表：快照题干与选项，题目下线不影响历史试卷';
COMMENT ON COLUMN paper_questions.paper_id IS '所属试卷 ID，试卷删除时级联删除';
COMMENT ON COLUMN paper_questions.question_id IS '源题目 ID，题目删除时置空但保留快照';
COMMENT ON COLUMN paper_questions.seq IS '卷内序号';
COMMENT ON COLUMN paper_questions.content IS '题干快照';
COMMENT ON COLUMN paper_questions.options IS '选项快照，格式同 quiz_questions.options';
COMMENT ON COLUMN paper_questions.score IS '该题分值';

CREATE INDEX IF NOT EXISTS idx_pq_paper ON paper_questions (paper_id, seq);

-- --------------------------------------------------------------------------- #
-- 模考：蓝图 / 场次 / 作答
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS exam_blueprints (
    id                  BIGSERIAL    PRIMARY KEY,
    subject_id          BIGINT       REFERENCES subjects(id) ON DELETE SET NULL,
    subject             TEXT         NOT NULL,
    paper               TEXT         NOT NULL,
    year                INTEGER,
    section             TEXT         NOT NULL,
    blueprint_question_type question_type NOT NULL,
    count               INTEGER      NOT NULL,
    score_per_question  REAL         NOT NULL,
    time_limit_minutes  INTEGER,
    sort_order          INTEGER      NOT NULL DEFAULT 0,
    kp_filters          TEXT,
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_blueprint_count  CHECK (count > 0),
    CONSTRAINT ck_blueprint_score  CHECK (score_per_question > 0)
);

COMMENT ON TABLE  exam_blueprints IS '模考试卷结构蓝图：定义各题型的题量、分值与时限';
COMMENT ON COLUMN exam_blueprints.subject_id IS '权威科目外键';
COMMENT ON COLUMN exam_blueprints.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN exam_blueprints.paper IS '试卷标识';
COMMENT ON COLUMN exam_blueprints.section IS '卷内分区，如 选择题 / 解答题';
COMMENT ON COLUMN exam_blueprints.blueprint_question_type IS '该分区的题型';
COMMENT ON COLUMN exam_blueprints.count IS '该分区题量';
COMMENT ON COLUMN exam_blueprints.score_per_question IS '单题分值';
COMMENT ON COLUMN exam_blueprints.time_limit_minutes IS '建议时限（分钟）';
COMMENT ON COLUMN exam_blueprints.kp_filters IS '知识点过滤条件';
COMMENT ON COLUMN exam_blueprints.is_active IS '是否启用';
COMMENT ON COLUMN exam_blueprints.created_at IS '创建时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_blueprints_active ON exam_blueprints (subject_id, is_active, sort_order);

CREATE TABLE IF NOT EXISTS exam_sessions (
    id                BIGSERIAL   PRIMARY KEY,
    blueprint_key     VARCHAR(100),
    subject_id        BIGINT      REFERENCES subjects(id) ON DELETE SET NULL,
    subject           TEXT        NOT NULL,
    paper             TEXT,
    mode              VARCHAR(30) NOT NULL DEFAULT 'normal',
    question_source   source_kind NOT NULL DEFAULT 'external_import',
    config            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    total_count       INTEGER,
    total_score       REAL,
    correct_count     INTEGER,
    score             REAL,
    time_limit_minutes INTEGER,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at        TIMESTAMPTZ,
    submitted_at      TIMESTAMPTZ,
    status            VARCHAR(20) NOT NULL DEFAULT 'ongoing',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_exam_session_status CHECK (status IN ('ongoing','submitted','expired','abandoned')),
    CONSTRAINT ck_exam_session_time CHECK (expires_at IS NULL OR expires_at >= started_at)
);

COMMENT ON TABLE  exam_sessions IS '模考场次表：一次完整模考的生命周期';
COMMENT ON COLUMN exam_sessions.blueprint_key IS '使用的蓝图标识';
COMMENT ON COLUMN exam_sessions.subject_id IS '权威科目外键';
COMMENT ON COLUMN exam_sessions.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN exam_sessions.mode IS '模式：normal 普通 / strict 严格计时';
COMMENT ON COLUMN exam_sessions.question_source IS '抽题范围性质，复用 source_kind 枚举';
COMMENT ON COLUMN exam_sessions.config IS '场次配置快照（JSON 对象）';
COMMENT ON COLUMN exam_sessions.started_at IS '开始时间（UTC，带时区）';
COMMENT ON COLUMN exam_sessions.expires_at IS '截止时间（UTC，带时区）';
COMMENT ON COLUMN exam_sessions.status IS '场次状态：ongoing / submitted / expired / abandoned';

CREATE INDEX IF NOT EXISTS idx_exam_sessions_status ON exam_sessions (status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_exam_sessions_subject ON exam_sessions (subject_id, started_at DESC);

CREATE TABLE IF NOT EXISTS exam_answers (
    id                BIGSERIAL   PRIMARY KEY,
    session_id        BIGINT      NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    question_id       BIGINT      REFERENCES quiz_questions(id) ON DELETE SET NULL,
    question_snapshot TEXT,
    section           TEXT,
    order_no          INTEGER,
    user_answer       TEXT,
    is_correct        BOOLEAN,
    time_spent        INTEGER,
    ai_score          REAL,
    self_score        REAL,
    final_score       REAL,
    scored_by         VARCHAR(30),
    error_category    VARCHAR(50),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_exam_answer_time CHECK (time_spent IS NULL OR time_spent >= 0)
);

COMMENT ON TABLE  exam_answers IS '模考作答明细：快照题干，避免题目变更影响历史成绩';
COMMENT ON COLUMN exam_answers.session_id IS '所属场次 ID，场次删除时级联删除';
COMMENT ON COLUMN exam_answers.question_snapshot IS '题干快照';
COMMENT ON COLUMN exam_answers.order_no IS '卷内作答序号';
COMMENT ON COLUMN exam_answers.ai_score IS 'AI 评分';
COMMENT ON COLUMN exam_answers.self_score IS '自评分';
COMMENT ON COLUMN exam_answers.final_score IS '最终得分';
COMMENT ON COLUMN exam_answers.scored_by IS '评分方：ai / self / teacher';
COMMENT ON COLUMN exam_answers.error_category IS '错误分类';

CREATE INDEX IF NOT EXISTS idx_exam_answers_session ON exam_answers (session_id, order_no);

-- --------------------------------------------------------------------------- #
-- 答疑待办
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS pending_questions (
    id                BIGSERIAL   PRIMARY KEY,
    question          TEXT        NOT NULL,
    subject_id        BIGINT      REFERENCES subjects(id) ON DELETE SET NULL,
    subject           VARCHAR(50),
    asked_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    have_basis        TEXT,
    have_basis_ids    TEXT,
    gap               TEXT        NOT NULL,
    gap_type          VARCHAR(50),
    suggestion        TEXT,
    suggested_action  VARCHAR(100),
    status            VARCHAR(20) NOT NULL DEFAULT 'open',
    resolved_by       VARCHAR(50),
    resolved_at       TIMESTAMPTZ,
    occurrence_count  INTEGER     NOT NULL DEFAULT 1,
    last_occurred_at  TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_pending_status CHECK (status IN ('open','resolved','ignored')),
    CONSTRAINT ck_pending_count CHECK (occurrence_count >= 1)
);

COMMENT ON TABLE  pending_questions IS '待解答问题表：AI 无据可依时登记的知识缺口';
COMMENT ON COLUMN pending_questions.subject_id IS '权威科目外键';
COMMENT ON COLUMN pending_questions.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN pending_questions.have_basis IS '现有依据描述';
COMMENT ON COLUMN pending_questions.have_basis_ids IS '依据的分块 ID 列表（逗号分隔）';
COMMENT ON COLUMN pending_questions.gap IS '缺口描述';
COMMENT ON COLUMN pending_questions.gap_type IS '缺口类型：missing_doc / outdated / conflict';
COMMENT ON COLUMN pending_questions.suggestion IS '补齐建议';
COMMENT ON COLUMN pending_questions.suggested_action IS '建议动作：import_doc / manual_answer / crawl';
COMMENT ON COLUMN pending_questions.status IS '处理状态：open / resolved / ignored';
COMMENT ON COLUMN pending_questions.occurrence_count IS '同一问题出现次数';
COMMENT ON COLUMN pending_questions.last_occurred_at IS '最近一次出现时间';
COMMENT ON COLUMN pending_questions.created_at IS '创建时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_pending_status  ON pending_questions (status, asked_at DESC);
CREATE INDEX IF NOT EXISTS idx_pending_subject ON pending_questions (subject_id);

-- --------------------------------------------------------------------------- #
-- 答案候选与作答流水
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS answer_candidates (
    id               BIGSERIAL PRIMARY KEY,
    question_id      BIGINT    NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    answer           TEXT      NOT NULL,
    explanation      TEXT,
    confidence       REAL      NOT NULL DEFAULT 0.5,
    source           answer_source NOT NULL DEFAULT 'llm_generated',
    used_for_grading BOOLEAN   NOT NULL DEFAULT FALSE,
    verified_by      VARCHAR(50),
    verified_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_candidate_confidence CHECK (confidence >= 0 AND confidence <= 1)
);

COMMENT ON TABLE  answer_candidates IS '答案候选表：同一题多个来源答案，供多角色校验与仲裁';
COMMENT ON COLUMN answer_candidates.question_id IS '题目 ID，题目删除时级联删除';
COMMENT ON COLUMN answer_candidates.confidence IS '该候选答案的置信度 0-1';
COMMENT ON COLUMN answer_candidates.source IS '答案来源：bank / source_extract / llm_generated / user_confirmed';
COMMENT ON COLUMN answer_candidates.used_for_grading IS '是否被采纳为判分依据';
COMMENT ON COLUMN answer_candidates.verified_by IS '校验人';
COMMENT ON COLUMN answer_candidates.verified_at IS '校验时间';
COMMENT ON COLUMN answer_candidates.created_at IS '创建时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_candidates_question ON answer_candidates (question_id, confidence DESC);

CREATE TABLE IF NOT EXISTS answer_records (
    id             BIGSERIAL   PRIMARY KEY,
    question_id    BIGINT      REFERENCES quiz_questions(id) ON DELETE SET NULL,
    my_answer      TEXT,
    correct_answer TEXT,
    is_correct     BOOLEAN,
    subject_id     BIGINT      REFERENCES subjects(id) ON DELETE SET NULL,
    subject        VARCHAR(50),
    mode           VARCHAR(50),
    cost_seconds   INTEGER,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_answer_cost CHECK (cost_seconds IS NULL OR cost_seconds >= 0)
);

COMMENT ON TABLE  answer_records IS '作答流水表：掌握度派生的核心数据源';
COMMENT ON COLUMN answer_records.question_id IS '题目 ID，题目删除时置空但保留答题历史';
COMMENT ON COLUMN answer_records.my_answer IS '用户作答';
COMMENT ON COLUMN answer_records.correct_answer IS '当时判定的正确答案快照';
COMMENT ON COLUMN answer_records.is_correct IS '是否答对；NULL 表示未判分（主观题待评）';
COMMENT ON COLUMN answer_records.subject_id IS '权威科目外键';
COMMENT ON COLUMN answer_records.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN answer_records.mode IS '练习模式：practice / exam / review';
COMMENT ON COLUMN answer_records.cost_seconds IS '作答耗时（秒）';
COMMENT ON COLUMN answer_records.created_at IS '作答时间（UTC，带时区），掌握度时间衰减以此为准';

-- 掌握度查询主路径：按题目反查知识点
CREATE INDEX IF NOT EXISTS idx_answer_records_question ON answer_records (question_id);
CREATE INDEX IF NOT EXISTS idx_answer_records_created  ON answer_records (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_answer_records_subject  ON answer_records (subject_id, created_at DESC);
