-- --------------------------------------------------------------------------- #
-- 096_papers_year_type.sql
-- papers 表加年份/卷种轴 + 模考报告支持
-- --------------------------------------------------------------------------- #

-- 1. papers 表加字段
ALTER TABLE papers ADD COLUMN IF NOT EXISTS year INTEGER;
ALTER TABLE papers ADD COLUMN IF NOT EXISTS paper_type VARCHAR(50);
ALTER TABLE papers ADD COLUMN IF NOT EXISTS is_mock BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN papers.year IS '真题年份（如 2024）';
COMMENT ON COLUMN papers.paper_type IS '卷种标签（如 数学一/英语二/专业课）';
COMMENT ON COLUMN papers.is_mock IS '是否为模拟试卷（true=用户自建，false=真题套卷）';

-- 2. 创建索引加速按年份/卷种筛选
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year) WHERE year IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_papers_paper_type ON papers(paper_type) WHERE paper_type IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_papers_is_mock ON papers(is_mock);

-- 3. paper_questions 加作答统计列（用于报告）
ALTER TABLE paper_questions ADD COLUMN IF NOT EXISTS avg_score REAL;
ALTER TABLE paper_questions ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN paper_questions.avg_score IS '该题历史平均得分（用于难度分析）';
COMMENT ON COLUMN paper_questions.attempt_count IS '该题被作答次数（用于热度统计）';

-- 4. 创建 paper_attempts 表记录用户对某份试卷的作答
CREATE TABLE IF NOT EXISTS paper_attempts (
    id              BIGSERIAL PRIMARY KEY,
    paper_id        BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    user_id         BIGINT,  -- 预留多用户扩展
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at    TIMESTAMPTZ,
    status          VARCHAR(20) NOT NULL DEFAULT 'ongoing',  -- ongoing/submitted/expired
    total_score     REAL,      -- 实得总分
    correct_count   INTEGER,   -- 答对题数
    duration_seconds INTEGER,  -- 作答时长（秒）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE paper_attempts IS '试卷作答记录：记录用户对某份试卷的完整作答过程';
COMMENT ON COLUMN paper_attempts.status IS '作答状态：ongoing进行中/submitted已提交/expired超时';

CREATE INDEX IF NOT EXISTS idx_paper_attempts_paper ON paper_attempts(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_attempts_user ON paper_attempts(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_paper_attempts_status ON paper_attempts(status);

-- 5. 创建 paper_answers 表记录逐题作答明细
CREATE TABLE IF NOT EXISTS paper_answers (
    id              BIGSERIAL PRIMARY KEY,
    attempt_id      BIGINT NOT NULL REFERENCES paper_attempts(id) ON DELETE CASCADE,
    question_id     BIGINT REFERENCES quiz_questions(id) ON DELETE SET NULL,
    paper_question_seq INTEGER NOT NULL,  -- 卷内题号快照
    user_answer     TEXT,
    is_correct      BOOLEAN,
    score           REAL,       -- 该题得分
    time_spent_seconds INTEGER, -- 该题耗时
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE paper_answers IS '试卷逐题作答明细';
COMMENT ON COLUMN paper_answers.paper_question_seq IS '卷内题号（快照，避免题目重排后序号变化）';

CREATE INDEX IF NOT EXISTS idx_paper_answers_attempt ON paper_answers(attempt_id);
CREATE INDEX IF NOT EXISTS idx_paper_answers_question ON paper_answers(question_id) WHERE question_id IS NOT NULL;
