-- 121_exam_sessions_user_id.sql · 模考场次用户隔离：给 exam_sessions 补 user_id 列（幂等）。
-- 背景（2026-11）：exam_sessions 自建表（041）起就没有归属列，任何用户的模考
-- 都会计入所有人的 KPI/热力图（services/study_calendar.py 的 exams_done），
-- 零数据新用户首屏因此出现他人的模考记录。本分片与 108_user_scope_columns 同风格：
-- 只加列 + 索引，不加 FK 约束（存量 NULL 行无法回填归属，保持 NULL=不计入任何个人统计）。

ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS user_id BIGINT;

-- core/models/exams.py 的 user_id 声明 index=True：补同名索引（幂等）
CREATE INDEX IF NOT EXISTS ix_exam_sessions_user_id ON exam_sessions (user_id);
