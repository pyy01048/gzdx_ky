-- =============================================================================
-- 102 review_schedules：FSRS 三要素 + 状态
--
-- 依赖：050（review_schedules 建表）
-- 目的：让单词 / 卡片 / 错题 / 知识点共用同一套 FSRS 调度。
--   algorithm='fsrs' 时读 stability / difficulty / state；SM-2 仍保留为回退。
-- 全部可空：历史 SM-2 记录无需回填，第一次 FSRS 复习时自动初始化。
-- =============================================================================

ALTER TABLE review_schedules ADD COLUMN IF NOT EXISTS stability REAL;
ALTER TABLE review_schedules ADD COLUMN IF NOT EXISTS difficulty REAL;
ALTER TABLE review_schedules ADD COLUMN IF NOT EXISTS retrievability REAL;
ALTER TABLE review_schedules ADD COLUMN IF NOT EXISTS state SMALLINT DEFAULT 0;

-- 到期队列：按类型 + 到期时间查询
CREATE INDEX IF NOT EXISTS ix_review_schedules_due_type
    ON review_schedules (item_type, next_review_at)
    WHERE next_review_at IS NOT NULL;

COMMENT ON COLUMN review_schedules.stability IS 'FSRS 稳定度（天），R(t) 曲线参数';
COMMENT ON COLUMN review_schedules.difficulty IS 'FSRS 难度 1-10';
COMMENT ON COLUMN review_schedules.retrievability IS '本次复习时的可提取概率 0-1';
COMMENT ON COLUMN review_schedules.state IS '0新 1学习 2复习 3重学';
COMMENT ON COLUMN review_schedules.algorithm IS '调度算法：sm2 / fsrs / ebbinghaus';
