-- 108_user_scope_columns.sql · B4 用户隔离：给个人数据表补 user_id 列（幂等）。
-- 背景（2026-10-19）：models.py 的 B4 改造给个人学习数据表声明了 user_id
-- （注释引用「SQL 108 同步重建」），本分片是该引用的落地——只加列，不改约束、
-- 不动唯一键（唯一键重建涉及存量数据判定，由 B4 完成时决定）。
-- 全部为 ADD COLUMN IF NOT EXISTS：新库/旧库均可重复执行。

ALTER TABLE answer_records        ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE daily_plans           ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE early_bird_records    ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE ebbinghaus_items      ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE error_knowledge_links ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE error_records         ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE flashcards            ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE goals                 ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE month_plans           ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE phase_plans           ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE review_records        ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE review_schedules      ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE study_events          ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE study_sessions        ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE study_stats           ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE tasks                 ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE week_plans            ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE word_decks            ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE words                 ADD COLUMN IF NOT EXISTS user_id BIGINT;

-- models.py 对个人数据表的 user_id 声明 index=True：补同名索引（幂等）
CREATE INDEX IF NOT EXISTS ix_answer_records_user_id        ON answer_records (user_id);
CREATE INDEX IF NOT EXISTS ix_daily_plans_user_id           ON daily_plans (user_id);
CREATE INDEX IF NOT EXISTS ix_early_bird_records_user_id    ON early_bird_records (user_id);
CREATE INDEX IF NOT EXISTS ix_ebbinghaus_items_user_id      ON ebbinghaus_items (user_id);
CREATE INDEX IF NOT EXISTS ix_error_knowledge_links_user_id ON error_knowledge_links (user_id);
CREATE INDEX IF NOT EXISTS ix_error_records_user_id         ON error_records (user_id);
CREATE INDEX IF NOT EXISTS ix_flashcards_user_id            ON flashcards (user_id);
CREATE INDEX IF NOT EXISTS ix_goals_user_id                 ON goals (user_id);
CREATE INDEX IF NOT EXISTS ix_month_plans_user_id           ON month_plans (user_id);
CREATE INDEX IF NOT EXISTS ix_phase_plans_user_id           ON phase_plans (user_id);
CREATE INDEX IF NOT EXISTS ix_review_records_user_id        ON review_records (user_id);
CREATE INDEX IF NOT EXISTS ix_review_schedules_user_id      ON review_schedules (user_id);
CREATE INDEX IF NOT EXISTS ix_study_events_user_id          ON study_events (user_id);
CREATE INDEX IF NOT EXISTS ix_study_sessions_user_id        ON study_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_study_stats_user_id           ON study_stats (user_id);
CREATE INDEX IF NOT EXISTS ix_tasks_user_id                 ON tasks (user_id);
CREATE INDEX IF NOT EXISTS ix_week_plans_user_id            ON week_plans (user_id);
CREATE INDEX IF NOT EXISTS ix_word_decks_user_id            ON word_decks (user_id);
CREATE INDEX IF NOT EXISTS ix_words_user_id                 ON words (user_id);
