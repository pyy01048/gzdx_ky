-- =============================================================================
-- 101 goals：每日学习目标四列（仪表盘 D-06 进度环 / D-07 KPI 的"目标值"来源）
-- 依赖：050（goals 建表）
--
-- 为什么要加：仪表盘要显示「今日完成 32/60」这类进度环与达标状态，分母（目标）
-- 必须有个权威出处。此前只有 50 行硬编码在前端页面里当"今日目标"，用户改不了、
-- 后端也算不出"今日是否达标"，打卡口径只能退化成"有没有做过"。
--
-- 四列**全部可空**：NULL = 用户还没设目标，接口据此返回 target=null，
-- 前端显示「未设目标」并给设置入口。**不给默认值**（不写 50/20/120），
-- 否则空库新用户看到的是凭空出现的数字。
-- =============================================================================

ALTER TABLE goals ADD COLUMN IF NOT EXISTS daily_focus_minutes  SMALLINT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS daily_new_words      SMALLINT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS daily_review_words   SMALLINT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS daily_questions      SMALLINT;

-- 目标值必须为正：0/负数不是"目标"，是把达标率算成除零或负数的写法错误
ALTER TABLE goals DROP CONSTRAINT IF EXISTS ck_goals_daily_focus_minutes;
ALTER TABLE goals ADD  CONSTRAINT ck_goals_daily_focus_minutes
    CHECK (daily_focus_minutes IS NULL OR daily_focus_minutes BETWEEN 1 AND 1440);
ALTER TABLE goals DROP CONSTRAINT IF EXISTS ck_goals_daily_new_words;
ALTER TABLE goals ADD  CONSTRAINT ck_goals_daily_new_words
    CHECK (daily_new_words IS NULL OR daily_new_words BETWEEN 1 AND 2000);
ALTER TABLE goals DROP CONSTRAINT IF EXISTS ck_goals_daily_review_words;
ALTER TABLE goals ADD  CONSTRAINT ck_goals_daily_review_words
    CHECK (daily_review_words IS NULL OR daily_review_words BETWEEN 1 AND 5000);
ALTER TABLE goals DROP CONSTRAINT IF EXISTS ck_goals_daily_questions;
ALTER TABLE goals ADD  CONSTRAINT ck_goals_daily_questions
    CHECK (daily_questions IS NULL OR daily_questions BETWEEN 1 AND 2000);

COMMENT ON COLUMN goals.daily_focus_minutes IS '每日专注时长目标（分钟）；NULL=未设目标，进度环显示"未设目标"';
COMMENT ON COLUMN goals.daily_new_words IS '每日新词目标；NULL=未设目标';
COMMENT ON COLUMN goals.daily_review_words IS '每日复习词量目标；NULL=未设目标';
COMMENT ON COLUMN goals.daily_questions IS '每日刷题目标；NULL=未设目标';
