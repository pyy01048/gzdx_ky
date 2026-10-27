-- =========================================================================== --
-- 刷题会话与作答尝试（F-03 / F-04）
-- =========================================================================== --
-- 背景
-- ----
-- 此前「章节练习」与「智能组卷」只有题目返回，没有会话级追踪：用户做了几题、
-- 对了多少、花了多久、哪些题答错——全部丢失。本 DDL 建立两张新表：
--
--   quiz_sessions    —— 一次刷题会话（选定科目/教材/章/节/知识点 + 筛选条件）
--   quiz_attempts    —— 会话内单题作答记录（含自评/AI 评分）
--
-- 设计口径
-- --------
-- * quiz_sessions.mode 区分三种入口：chapter_practice / smart_paper / free_practice
-- * quiz_sessions.filters 存 JSONB 筛选条件（知识点列表、题型、难度范围等）
-- * quiz_attempts.quality 复用 SM-2 的 0-5 评分，同时映射到掌握度四态
-- * 所有时间列用 TIMESTAMPTZ，后端统一 naive UTC 写入
-- =========================================================================== --

CREATE TABLE IF NOT EXISTS quiz_sessions (
    id              BIGSERIAL    PRIMARY KEY,
    -- 会话元数据
    mode            VARCHAR(30)  NOT NULL DEFAULT 'free_practice',
                                    CONSTRAINT ck_quiz_sessions_mode CHECK (mode IN ('chapter_practice','smart_paper','free_practice')),
    subject_id      BIGINT       REFERENCES subjects(id) ON DELETE SET NULL,
    textbook_id     BIGINT       REFERENCES textbooks(id) ON DELETE SET NULL,
    chapter_id      BIGINT       REFERENCES subject_chapters(id) ON DELETE SET NULL,
    section_id      BIGINT       REFERENCES subject_chapters(id) ON DELETE SET NULL,
    knowledge_point_ids  JSONB       NOT NULL DEFAULT '[]',
    filters         JSONB        NOT NULL DEFAULT '{}',
    -- 会话统计（冗余，便于快速查询）
    total_questions INTEGER      NOT NULL DEFAULT 0,
    answered_count  INTEGER      NOT NULL DEFAULT 0,
    correct_count   INTEGER      NOT NULL DEFAULT 0,
    duration_seconds INTEGER     NOT NULL DEFAULT 0,
    -- 状态
    status          VARCHAR(20)  NOT NULL DEFAULT 'in_progress',
                                    CONSTRAINT ck_quiz_sessions_status CHECK (status IN ('in_progress','completed','abandoned')),
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  quiz_sessions IS '刷题会话：记录一次章节练习/智能组卷/自由练习的完整上下文';
COMMENT ON COLUMN quiz_sessions.mode IS '会话模式：chapter_practice 章节练习 / smart_paper 智能组卷 / free_practice 自由练习';
COMMENT ON COLUMN quiz_sessions.subject_id IS '所属科目';
COMMENT ON COLUMN quiz_sessions.textbook_id IS '所属教材（五层结构第2层）';
COMMENT ON COLUMN quiz_sessions.chapter_id IS '所属章（五层结构第3层）';
COMMENT ON COLUMN quiz_sessions.section_id IS '所属节（五层结构第4层）';
COMMENT ON COLUMN quiz_sessions.knowledge_point_ids IS '选中的知识点 ID 数组，空表示该层级下全量出题';
COMMENT ON COLUMN quiz_sessions.filters IS 'JSONB 筛选条件：{"question_types":["single","fill"],"difficulty":[2,3,4],"time_limit":1800}';
COMMENT ON COLUMN quiz_sessions.total_questions IS '会话总题数（快照，避免后续题库变动影响统计）';
COMMENT ON COLUMN quiz_sessions.answered_count IS '已作答数';
COMMENT ON COLUMN quiz_sessions.correct_count IS '答对数：客观题自动判分 + 主观题用户自评（对/半对=0.5/错=0）';
COMMENT ON COLUMN quiz_sessions.duration_seconds IS '会话耗时（秒），从 started_at 到 completed_at 或当前时刻';
COMMENT ON COLUMN quiz_sessions.status IS '会话状态：in_progress 进行中 / completed 已完成 / abandoned 已放弃';

CREATE INDEX IF NOT EXISTS idx_quiz_sessions_subject ON quiz_sessions (subject_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_sessions_textbook ON quiz_sessions (textbook_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_sessions_chapter ON quiz_sessions (chapter_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_sessions_section ON quiz_sessions (section_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_sessions_status ON quiz_sessions (status, started_at DESC);

CREATE OR REPLACE TRIGGER trg_quiz_sessions_updated BEFORE UPDATE ON quiz_sessions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- =========================================================================== --
-- 单题作答记录
-- =========================================================================== --

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id              BIGSERIAL    PRIMARY KEY,
    session_id      BIGINT       NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_id     BIGINT       NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    -- 作答内容
    user_answer     TEXT,
    is_correct      BOOLEAN,
    score           REAL,
    quality         SMALLINT     NOT NULL DEFAULT 3,
    -- 时间与反馈
    answered_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    time_spent_seconds INTEGER,
    feedback        TEXT,
    ai_comment      TEXT,
    self_rating     VARCHAR(10),
    -- 派生掌握度
    mastery_before  SMALLINT,
    mastery_after   SMALLINT
);

COMMENT ON TABLE  quiz_attempts IS '单题作答记录：关联到 quiz_sessions，记录每题的用户作答与评分';
COMMENT ON COLUMN quiz_attempts.session_id IS '所属刷题会话';
COMMENT ON COLUMN quiz_attempts.question_id IS '所答题目';
COMMENT ON COLUMN quiz_attempts.user_answer IS '用户作答内容';
COMMENT ON COLUMN quiz_attempts.is_correct IS '是否答对：客观题 = (user_answer = answer)，主观题由自评或 AI 判定';
COMMENT ON COLUMN quiz_attempts.score IS '得分：客观题满分或0分；主观题按 rubric 给分';
COMMENT ON COLUMN quiz_attempts.quality IS 'SM-2 回答质量：0=完全忘记, 1=错误, 2=困难想起, 3=正确但费力, 4=正确, 5=完美';
COMMENT ON COLUMN quiz_attempts.time_spent_seconds IS '本题作答耗时（秒）';
COMMENT ON COLUMN quiz_attempts.feedback IS '系统给出的反馈文本或标记';
COMMENT ON COLUMN quiz_attempts.ai_comment IS 'AI 对主观题作答的评语';
COMMENT ON COLUMN quiz_attempts.self_rating IS '用户自评分级：correct 对 / partial 半对 / wrong 错';
COMMENT ON COLUMN quiz_attempts.mastery_before IS '作答前知识点掌握度快照';
COMMENT ON COLUMN quiz_attempts.mastery_after IS '经调度算法更新后的掌握度';

CREATE INDEX IF NOT EXISTS idx_quiz_attempts_session ON quiz_attempts (session_id, answered_at);
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_question ON quiz_attempts (question_id, answered_at DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_quality ON quiz_attempts (quality);
