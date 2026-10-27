-- =============================================================================
-- 051 计划与统计：专注 / 艾宾浩斯 / 早起 / 月周计划 / 阶段计划 / 学习统计 / 节点
-- 依赖：000 / 010 / 020 / 030 / 040 / 050
-- =============================================================================

-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS flashcards (
    id                 BIGSERIAL   PRIMARY KEY,
    front              TEXT        NOT NULL,
    back               TEXT        NOT NULL,
    knowledge_point_id BIGINT      REFERENCES knowledge_points(id) ON DELETE SET NULL,
    next_review        TIMESTAMPTZ,
    review_count       INTEGER     NOT NULL DEFAULT 0,
    interval_days      INTEGER     NOT NULL DEFAULT 1,
    ease_factor        REAL        NOT NULL DEFAULT 2.5,
    -- 历史代码曾用 'new' 表示未学，现统一收敛到 mastery_level 枚举的 not_mastered
    mastery            mastery_level NOT NULL DEFAULT 'not_mastered',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  flashcards IS '记忆卡片表：SM-2 调度';
COMMENT ON COLUMN flashcards.front IS '卡片正面';
COMMENT ON COLUMN flashcards.back IS '卡片背面';
COMMENT ON COLUMN flashcards.knowledge_point_id IS '关联知识点 ID';
COMMENT ON COLUMN flashcards.next_review IS '下次复习时间（UTC），兼容列，真值在 review_schedules';
COMMENT ON COLUMN flashcards.interval_days IS '当前复习间隔（天）';
COMMENT ON COLUMN flashcards.ease_factor IS 'SM-2 难度因子';
COMMENT ON COLUMN flashcards.mastery IS '掌握状态：new / learning / review / mastered';
COMMENT ON COLUMN flashcards.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN flashcards.updated_at IS '最后更新时间';

CREATE INDEX IF NOT EXISTS idx_flashcards_due ON flashcards (next_review) WHERE next_review IS NOT NULL;

CREATE OR REPLACE TRIGGER trg_flashcards_updated BEFORE UPDATE ON flashcards
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS focus_sessions (
    id               BIGSERIAL   PRIMARY KEY,
    start_at         TIMESTAMPTZ NOT NULL,
    end_at           TIMESTAMPTZ,
    duration_minutes INTEGER,
    tag              VARCHAR(50),
    note             TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_focus_time CHECK (end_at IS NULL OR end_at >= start_at)
);

COMMENT ON TABLE  focus_sessions IS '专注计时会话表';
COMMENT ON COLUMN focus_sessions.start_at IS '开始时间（UTC，带时区）';
COMMENT ON COLUMN focus_sessions.end_at IS '结束时间（UTC，带时区）';
COMMENT ON COLUMN focus_sessions.duration_minutes IS '专注时长（分钟）';
COMMENT ON COLUMN focus_sessions.tag IS '专注标签';
COMMENT ON COLUMN focus_sessions.note IS '备注';
COMMENT ON COLUMN focus_sessions.created_at IS '记录创建时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_focus_start ON focus_sessions (start_at DESC);

CREATE TABLE IF NOT EXISTS ebbinghaus_items (
    id           BIGSERIAL   PRIMARY KEY,
    seq          INTEGER,
    learn_date   TIMESTAMPTZ NOT NULL,
    content      TEXT        NOT NULL,
    subject_id   BIGINT      REFERENCES subjects(id) ON DELETE SET NULL,
    subject      VARCHAR(50),
    review_5min  TIMESTAMPTZ,
    review_30min TIMESTAMPTZ,
    review_12h   TIMESTAMPTZ,
    review_1d    TIMESTAMPTZ,
    review_2d    TIMESTAMPTZ,
    review_4d    TIMESTAMPTZ,
    review_7d    TIMESTAMPTZ,
    review_15d   TIMESTAMPTZ,
    review_1m    TIMESTAMPTZ,
    cycle_config JSONB,
    review_times JSONB,
    mastered     BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  ebbinghaus_items IS '艾宾浩斯记忆条目表：默认 9 档复习时点，支持自定义节奏（cycle_config/review_times）';
COMMENT ON COLUMN ebbinghaus_items.learn_date IS '首次学习时间（UTC，带时区）';
COMMENT ON COLUMN ebbinghaus_items.review_5min IS '5 分钟后复习时点';
COMMENT ON COLUMN ebbinghaus_items.review_30min IS '30 分钟后复习时点';
COMMENT ON COLUMN ebbinghaus_items.review_12h IS '12 小时后复习时点';
COMMENT ON COLUMN ebbinghaus_items.review_1d IS '1 天后复习时点';
COMMENT ON COLUMN ebbinghaus_items.review_2d IS '2 天后复习时点';
COMMENT ON COLUMN ebbinghaus_items.review_4d IS '4 天后复习时点';
COMMENT ON COLUMN ebbinghaus_items.review_7d IS '7 天后复习时点';
COMMENT ON COLUMN ebbinghaus_items.review_15d IS '15 天后复习时点';
COMMENT ON COLUMN ebbinghaus_items.review_1m IS '1 个月后复习时点';
COMMENT ON COLUMN ebbinghaus_items.cycle_config IS '自定义周期定义 [{"key":"custom_1","label":"第1天","offset_minutes":1440}]';
COMMENT ON COLUMN ebbinghaus_items.review_times IS '实际复习时间点 [{"key":"custom_1","label":"第1天","time":"iso","done":false}]';
COMMENT ON COLUMN ebbinghaus_items.mastered IS '是否已掌握';

CREATE INDEX IF NOT EXISTS idx_ebbinghaus_learn ON ebbinghaus_items (learn_date DESC);

CREATE TABLE IF NOT EXISTS early_bird_records (
    id         BIGSERIAL PRIMARY KEY,
    day_num    INTEGER   NOT NULL,
    date       DATE      NOT NULL,
    wake_time  TIME,
    sleep_time TIME,
    note       VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_early_bird_date UNIQUE (date)
);

COMMENT ON TABLE  early_bird_records IS '早起打卡表：按日期唯一';
COMMENT ON COLUMN early_bird_records.day_num IS '连续打卡第几天';
COMMENT ON COLUMN early_bird_records.date IS '打卡日期';
COMMENT ON COLUMN early_bird_records.wake_time IS '起床时间';
COMMENT ON COLUMN early_bird_records.sleep_time IS '入睡时间';
COMMENT ON COLUMN early_bird_records.note IS '备注';

-- --------------------------------------------------------------------------- #
-- 计划体系：月 → 周 → 日，以及阶段计划
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS month_plans (
    id         BIGSERIAL PRIMARY KEY,
    year       INTEGER   NOT NULL,
    month      INTEGER   NOT NULL,
    tasks      JSONB     NOT NULL DEFAULT '[]'::jsonb,
    completion TEXT,
    summary    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_month_plan UNIQUE (year, month),
    CONSTRAINT ck_month_range CHECK (month BETWEEN 1 AND 12)
);

COMMENT ON TABLE  month_plans IS '月度计划表';
COMMENT ON COLUMN month_plans.year IS '年份';
COMMENT ON COLUMN month_plans.month IS '月份 1-12';
COMMENT ON COLUMN month_plans.tasks IS '月度任务列表（JSON 数组）';
COMMENT ON COLUMN month_plans.completion IS '完成情况说明';
COMMENT ON COLUMN month_plans.summary IS '月度总结';

CREATE TABLE IF NOT EXISTS week_plans (
    id            BIGSERIAL PRIMARY KEY,
    month_plan_id BIGINT    REFERENCES month_plans(id) ON DELETE SET NULL,
    week_start    DATE      NOT NULL,
    tasks         JSONB     NOT NULL DEFAULT '[]'::jsonb,
    daily_records JSONB     NOT NULL DEFAULT '{}'::jsonb,
    completion    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_week_plan UNIQUE (week_start)
);

COMMENT ON TABLE  week_plans IS '周计划表，归属月计划';
COMMENT ON COLUMN week_plans.month_plan_id IS '所属月计划 ID';
COMMENT ON COLUMN week_plans.week_start IS '周起始日期（周一）';
COMMENT ON COLUMN week_plans.daily_records IS '每日完成记录（JSON 对象，key 为日期）';

CREATE TABLE IF NOT EXISTS daily_plans (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE      NOT NULL,
    days_to_exam    INTEGER,
    tasks           JSONB     NOT NULL DEFAULT '[]'::jsonb,
    timeline        JSONB     NOT NULL DEFAULT '[]'::jsonb,
    study_duration  INTEGER   NOT NULL DEFAULT 0,
    wasted_duration INTEGER   NOT NULL DEFAULT 0,
    score           SMALLINT,
    summary         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_daily_plan UNIQUE (date)
);

COMMENT ON TABLE  daily_plans IS '每日计划表：含时间轴与自评分';
COMMENT ON COLUMN daily_plans.date IS '计划日期';
COMMENT ON COLUMN daily_plans.days_to_exam IS '距考试天数';
COMMENT ON COLUMN daily_plans.timeline IS '当日时间轴安排（JSON 数组）';
COMMENT ON COLUMN daily_plans.study_duration IS '有效学习时长（分钟）';
COMMENT ON COLUMN daily_plans.wasted_duration IS '浪费时长（分钟）';
COMMENT ON COLUMN daily_plans.score IS '当日自评分';

CREATE OR REPLACE TRIGGER trg_daily_plans_updated BEFORE UPDATE ON daily_plans
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS phase_plans (
    id         BIGSERIAL PRIMARY KEY,
    name       VARCHAR(200) NOT NULL,
    start_date DATE      NOT NULL,
    end_date   DATE      NOT NULL,
    cycle_days INTEGER,
    tasks      JSONB     NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_phase_date CHECK (start_date <= end_date)
);

COMMENT ON TABLE  phase_plans IS '阶段计划表：基础/强化/冲刺';
COMMENT ON COLUMN phase_plans.cycle_days IS '阶段内循环周期天数';

CREATE TABLE IF NOT EXISTS phase_daily_reviews (
    id              BIGSERIAL PRIMARY KEY,
    phase_plan_id   BIGINT    NOT NULL REFERENCES phase_plans(id) ON DELETE CASCADE,
    day_num         INTEGER   NOT NULL,
    date            DATE,
    morning_reviews JSONB     NOT NULL DEFAULT '[]'::jsonb,
    evening_reviews JSONB     NOT NULL DEFAULT '[]'::jsonb,
    completed       BOOLEAN   NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_phase_day UNIQUE (phase_plan_id, day_num)
);

COMMENT ON TABLE  phase_daily_reviews IS '阶段计划内的每日复习安排（早/晚各一组）';
COMMENT ON COLUMN phase_daily_reviews.morning_reviews IS '早晨复习项（JSON 数组）';
COMMENT ON COLUMN phase_daily_reviews.evening_reviews IS '晚间复习项（JSON 数组）';

-- --------------------------------------------------------------------------- #
-- 学习统计与事件流
