-- warn 题治理回滚（2026-11-20T21:05:08）
-- 恢复被软下架的 warn 题目为可作答状态
UPDATE quiz_questions SET is_available = TRUE, updated_at = NOW()
 WHERE validation_status = 'warn';
