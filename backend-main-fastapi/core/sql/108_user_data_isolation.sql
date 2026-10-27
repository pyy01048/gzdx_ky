-- =============================================================================
-- 108 user_data_isolation：B4 行级数据隔离
-- （docs/plan-gap/E-user-data-isolation.md §2；对应 B-auth.md B4 缺口）
--
-- 内容：
--   1) 个人学习域表统一加可空 user_id（NOT NULL 待 P2 路由全部接线后另行收紧）；
--   2) 存量数据回填主账号（最早创建且未删除的管理员，兜底最早用户）；
--   3) 唯一键按用户维度重建（review_schedules / 计划三表 / 早起 / favorites / 词库名）；
--   4) 高频查询复合索引；
--   5) 通知已读/加星 per-user 新表 notice_user_states（P5）。
--
-- 幂等，可重复执行。PG 方言（DATABASE_BACKEND=postgresql）。
-- 执行：python scripts/execute_core_sql.py core/sql/108_user_data_isolation.sql
-- =============================================================================

-- ---------------------------------------------------------------- 1) 加列 ----
ALTER TABLE goals                 ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE tasks                 ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE review_schedules      ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE review_records        ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE error_records         ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
-- 冗余列（跟随 error_records 归属），不设 FK：联动行随 error 级联，保留直查便利
ALTER TABLE error_knowledge_links ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE flashcards            ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE words                 ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE word_decks            ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE favorites             ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE study_sessions        ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE study_events          ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE study_stats           ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE answer_records        ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE quiz_sessions         ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE quiz_attempts         ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE daily_plans           ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE week_plans            ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE month_plans           ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE ebbinghaus_items      ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE early_bird_records    ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE phase_plans           ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
-- 盲区池（A4：abstain 沉淀，属个人学习缺口数据，随 blind_spot 路由接线）
ALTER TABLE pending_questions     ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);

-- ---------------------------------------------------- 2) 存量回填主账号 ----
-- 口径（清单 §2.2.2）：现库是"一家人共用"的存量，全部收编给主账号；
-- 主账号 = 最早创建且未删除的管理员，兜底最早用户。只填 NULL，幂等。
UPDATE goals              SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE tasks              SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE review_schedules   SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE review_records     SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE error_records      SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE error_knowledge_links SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE flashcards         SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE words              SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE word_decks         SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE favorites          SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE study_sessions     SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE study_events       SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE study_stats        SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE answer_records     SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE quiz_sessions      SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE quiz_attempts      SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE daily_plans        SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE week_plans         SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE month_plans        SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE ebbinghaus_items   SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE early_bird_records SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE phase_plans        SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;
UPDATE pending_questions  SET user_id = (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))) WHERE user_id IS NULL;

-- ---------------------------------------------- 3) 唯一键按用户维度重建 ----
-- 复习调度：同一对象不同用户各自一条（B4 的关键前提）
ALTER TABLE review_schedules DROP CONSTRAINT IF EXISTS uq_review_schedule;
ALTER TABLE review_schedules ADD  CONSTRAINT uq_review_schedule UNIQUE (user_id, item_type, item_id);

-- 计划三表 + 早起：原按日期全局唯一 → 每用户唯一
ALTER TABLE daily_plans        DROP CONSTRAINT IF EXISTS uq_daily_plan;
ALTER TABLE daily_plans        DROP CONSTRAINT IF EXISTS uq_daily_plan_user;
ALTER TABLE daily_plans        ADD  CONSTRAINT uq_daily_plan_user UNIQUE (user_id, date);
ALTER TABLE week_plans         DROP CONSTRAINT IF EXISTS uq_week_plan;
ALTER TABLE week_plans         DROP CONSTRAINT IF EXISTS uq_week_plan_user;
ALTER TABLE week_plans         ADD  CONSTRAINT uq_week_plan_user UNIQUE (user_id, week_start);
ALTER TABLE month_plans        DROP CONSTRAINT IF EXISTS uq_month_plan;
ALTER TABLE month_plans        DROP CONSTRAINT IF EXISTS uq_month_plan_user;
ALTER TABLE month_plans        ADD  CONSTRAINT uq_month_plan_user UNIQUE (user_id, year, month);
ALTER TABLE early_bird_records DROP CONSTRAINT IF EXISTS uq_early_bird_date;
ALTER TABLE early_bird_records DROP CONSTRAINT IF EXISTS uq_early_bird_user;
ALTER TABLE early_bird_records ADD  CONSTRAINT uq_early_bird_user UNIQUE (user_id, date);

-- 收藏：同一实体不同用户各自收藏
ALTER TABLE favorites DROP CONSTRAINT IF EXISTS uq_favorites_item;
ALTER TABLE favorites DROP CONSTRAINT IF EXISTS uq_favorites_item_user;
ALTER TABLE favorites ADD  CONSTRAINT uq_favorites_item_user UNIQUE (user_id, item_type, item_id);

-- 词库名：内置词书(NULL)保持全局唯一；自建词书按用户唯一（partial unique index）
ALTER TABLE word_decks DROP CONSTRAINT IF EXISTS uq_deck_name;
CREATE UNIQUE INDEX IF NOT EXISTS uq_deck_name_global ON word_decks (name) WHERE user_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_deck_name_user   ON word_decks (user_id, name) WHERE user_id IS NOT NULL;

-- ------------------------------------------------------ 4) 高频查询索引 ----
CREATE INDEX IF NOT EXISTS ix_tasks_user            ON tasks (user_id, status);
CREATE INDEX IF NOT EXISTS ix_review_sched_user_due ON review_schedules (user_id, next_review_at);
CREATE INDEX IF NOT EXISTS ix_error_records_user    ON error_records (user_id, status);
CREATE INDEX IF NOT EXISTS ix_favorites_user        ON favorites (user_id, item_type);
CREATE INDEX IF NOT EXISTS ix_study_sessions_user   ON study_sessions (user_id, date);
CREATE INDEX IF NOT EXISTS ix_answer_records_user   ON answer_records (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_quiz_sessions_user    ON quiz_sessions (user_id, started_at);
CREATE INDEX IF NOT EXISTS ix_study_events_user     ON study_events (user_id, occurred_at);

-- --------------------------------- 5) 通知已读/加星 per-user（P5）----
-- 现状：is_read/is_starred 落在 kaoyan_notices 行上（B-auth.md §B4.5：全用户共享）。
-- 新表按 (user, notice) 记状态；kaoyan_notices 上两列废弃不再读写。
CREATE TABLE IF NOT EXISTS notice_user_states (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    notice_id   BIGINT NOT NULL REFERENCES kaoyan_notices(id) ON DELETE CASCADE,
    is_read     BOOLEAN NOT NULL DEFAULT FALSE,
    is_starred  BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at  TIMESTAMPTZ,
    CONSTRAINT uq_notice_user UNIQUE (user_id, notice_id)
);
CREATE INDEX IF NOT EXISTS ix_notice_user_notice ON notice_user_states (notice_id);

-- 存量共享已读态收编给主账号（幂等：ON CONFLICT 跳过）
INSERT INTO notice_user_states (user_id, notice_id, is_read, is_starred, updated_at)
SELECT (SELECT COALESCE((SELECT id FROM users WHERE role='admin' AND deleted_at IS NULL ORDER BY id LIMIT 1), (SELECT MIN(id) FROM users))),
       n.id, COALESCE(n.is_read, FALSE), COALESCE(n.is_starred, FALSE), NOW()
FROM kaoyan_notices n
WHERE COALESCE(n.is_read, FALSE) OR COALESCE(n.is_starred, FALSE)
ON CONFLICT (user_id, notice_id) DO NOTHING;
