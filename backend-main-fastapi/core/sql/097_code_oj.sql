-- --------------------------------------------------------------------------- #
-- 097_code_oj.sql
-- P2-M5 代码上机 OJ：题目/测试用例/提交记录/判题结果
-- --------------------------------------------------------------------------- #

-- 1. 编程题目表
CREATE TABLE IF NOT EXISTS code_problems (
    id              BIGSERIAL PRIMARY KEY,
    title           VARCHAR(200) NOT NULL,
    subject         VARCHAR(50),  -- 所属科目（如 408/数据结构）
    difficulty      SMALLINT NOT NULL DEFAULT 2,  -- 1-5 难度等级
    description     TEXT NOT NULL,  -- 题目描述（Markdown，含输入输出格式）
    input_format    TEXT,         -- 输入格式说明
    output_format   TEXT,         -- 输出格式说明
    sample_input    TEXT,         -- 样例输入
    sample_output   TEXT,         -- 样例输出
    hints           TEXT,         -- 提示
    time_limit_ms   INTEGER NOT NULL DEFAULT 1000,  -- 时限（毫秒）
    memory_limit_kb INTEGER NOT NULL DEFAULT 256000,  -- 内存限制（KB，默认 256MB）
    tags            JSONB,        -- 标签数组（如 ["动态规划","图论"]）
    is_public       BOOLEAN NOT NULL DEFAULT TRUE,  -- 是否公开
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE code_problems IS '编程题目表';
COMMENT ON COLUMN code_problems.time_limit_ms IS '单组测试数据时限（毫秒）';
COMMENT ON COLUMN code_problems.memory_limit_kb IS '内存限制（KB）';

CREATE INDEX IF NOT EXISTS idx_code_problems_subject ON code_problems(subject);
CREATE INDEX IF NOT EXISTS idx_code_problems_difficulty ON code_problems(difficulty);
CREATE INDEX IF NOT EXISTS idx_code_problems_is_public ON code_problems(is_public);

-- 2. 题目测试用例表
CREATE TABLE IF NOT EXISTS code_problem_testcases (
    id              BIGSERIAL PRIMARY KEY,
    problem_id      BIGINT NOT NULL REFERENCES code_problems(id) ON DELETE CASCADE,
    input_data      TEXT NOT NULL,  -- 输入数据（可存文件路径或 Base64）
    expected_output TEXT NOT NULL,  -- 期望输出
    is_sample       BOOLEAN NOT NULL DEFAULT FALSE,  -- 是否为样例测试点
    score_weight    REAL NOT NULL DEFAULT 1.0,  -- 该测试点分值权重
    sort_order      INTEGER NOT NULL DEFAULT 0  -- 执行顺序
);

COMMENT ON TABLE code_problem_testcases IS '编程题目测试用例表';
COMMENT ON COLUMN code_problem_testcases.input_data IS '输入数据（大文件存对象存储，此处存路径；小文本直接存）';

CREATE INDEX IF NOT EXISTS idx_code_testcases_problem ON code_problem_testcases(problem_id);
CREATE INDEX IF NOT EXISTS idx_code_testcases_sample ON code_problem_testcases(problem_id, is_sample);

-- 3. 代码提交记录表
CREATE TABLE IF NOT EXISTS code_submissions (
    id              BIGSERIAL PRIMARY KEY,
    problem_id      BIGINT NOT NULL REFERENCES code_problems(id) ON DELETE CASCADE,
    user_id         BIGINT,  -- 预留多用户扩展
    language        VARCHAR(20) NOT NULL,  -- cpp/python/c/java
    code            TEXT NOT NULL,  -- 用户提交的代码
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending/judging/ac/wa/tle/mle/ce/re/se
    score           REAL NOT NULL DEFAULT 0.0,  -- 得分（0-100）
    total_testcases INTEGER,  -- 总测试点数
    passed_testcases INTEGER,  -- 通过的测试点数
    compile_error   TEXT,  -- 编译错误信息
    error_message   TEXT,  -- 运行时错误信息
    max_time_ms     INTEGER,  -- 最大运行耗时（毫秒）
    max_memory_kb   INTEGER,  -- 峰值内存占用（KB）
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    judged_at       TIMESTAMPTZ,  -- 判题完成时间
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE code_submissions IS '代码提交记录表';
COMMENT ON COLUMN code_submissions.status IS '判题状态：pending待判/judging判题中/ac通过/wa答案错/tle超时/mle超内存/ce编译错/re运行错/se系统错';

CREATE INDEX IF NOT EXISTS idx_code_submissions_problem ON code_submissions(problem_id);
CREATE INDEX IF NOT EXISTS idx_code_submissions_user ON code_submissions(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_code_submissions_status ON code_submissions(status);
CREATE INDEX IF NOT EXISTS idx_code_submissions_submitted ON code_submissions(submitted_at DESC);

-- 4. 提交逐测试点详情表
CREATE TABLE IF NOT EXISTS code_submission_results (
    id              BIGSERIAL PRIMARY KEY,
    submission_id   BIGINT NOT NULL REFERENCES code_submissions(id) ON DELETE CASCADE,
    testcase_id     BIGINT REFERENCES code_problem_testcases(id) ON DELETE SET NULL,
    status          VARCHAR(20) NOT NULL,  -- ac/wa/tle/mle/re
    time_ms         INTEGER,  -- 该测试点耗时
    memory_kb       INTEGER,  -- 该测试点内存
    actual_output   TEXT,  -- 实际输出（WA 时用于对比）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE code_submission_results IS '提交逐测试点判题结果';

CREATE INDEX IF NOT EXISTS idx_code_results_submission ON code_submission_results(submission_id);

-- 5. 题目标签表（可选，用于多维度分类）
CREATE TABLE IF NOT EXISTS code_tags (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(50) UNIQUE NOT NULL,
    category        VARCHAR(50),  -- 标签分类（如 algorithm/data_structure）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE code_tags IS 'OJ 题目标签字典';

-- 6. 题目-标签关联表
CREATE TABLE IF NOT EXISTS code_problem_tags (
    problem_id      BIGINT REFERENCES code_problems(id) ON DELETE CASCADE,
    tag_id          INTEGER REFERENCES code_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (problem_id, tag_id)
);

COMMENT ON TABLE code_problem_tags IS '题目-标签多对多关联';

CREATE INDEX IF NOT EXISTS idx_code_problem_tags_tag ON code_problem_tags(tag_id);
