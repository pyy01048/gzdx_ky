-- 127_perf_wave_indexes.sql · 性能波（2026-11-23）：检索链与首屏台账的索引补强
--
-- 背景（实测数字都来自本机真库：knowledge_chunks 81348 行 / documents 2666 行 / 64 MB 正文）
-- ------------------------------------------------------------------
-- 1) 检索链改造后主查走 `knowledge_chunks.search_vector`（GIN，020 分片已建）
--    与 `documents.file_name`（GIN trgm，已建），**不再**在 async 端点里全表
--    ILIKE `documents.content`；因此本分片刻意**不**给 content 建 trgm 索引 ——
--    实测常见中文词命中七成文档，位图索引回表 recheck 仍需把 64 MB 正文读出来
--    （GIN 0.72 s vs 全表 0.66 s），只换来磁盘与写入放大，没有收益。
-- 2) 真正缺的是学科维度的窄索引：新的文档路按 subject 过滤标题命中集，
--    而 020 只给 `subject_id` 建了索引（历史文档大量只写 `subject` 文本列）。
-- 3) 首屏 `services/study_calendar.day_ledger` 的 6 条 `GROUP BY 本地日` 聚合，
--    过滤条件全是 (user_id, 时间列 [, status/item_type])，但库里只建到
--    `(user_id)` 或 `(user_id, status)` 前缀：行数一多就退化成"按人取全量再排"。
--    这里把六条聚合的复合索引一次补齐（部分索引只覆盖实际谓词，体积最小）。
--
-- 幂等：全部 `IF NOT EXISTS`，重复执行零副作用。
-- 方言：PG-only。SQLite 侧的兜底索引由 services/db_optimizer.py 在启动时补建，
--       本文件的 GIN/部分索引语法不参与 SQLite 路径（core/migrations 只在 PG 上跑）。
--
-- 回滚（如需撤销本分片，逐条执行即可，均为独立对象、无依赖链）：
--   DROP INDEX IF EXISTS ix_documents_subject_text;
--   DROP INDEX IF EXISTS ix_tasks_user_done_at;
--   DROP INDEX IF EXISTS ix_review_records_user_created;
--   DROP INDEX IF EXISTS ix_error_records_user_created;
--   DROP INDEX IF EXISTS ix_exam_sessions_user_submitted;
--   DELETE FROM schema_migrations WHERE version = '127_perf_wave_indexes';

-- --------------------------------------------------------------------------- #
-- 1. 检索链：文档路按学科过滤（documents.subject 是历史文本列，非 subject_id）
-- --------------------------------------------------------------------------- #
CREATE INDEX IF NOT EXISTS ix_documents_subject_text ON documents (subject) WHERE subject IS NOT NULL;

-- --------------------------------------------------------------------------- #
-- 2. 首屏台账 day_ledger 的 6 条按日聚合（B4 行级隔离后一律带 user_id 过滤）
-- --------------------------------------------------------------------------- #

-- 2.1 任务完成数：status='done' AND completed_at IS NOT NULL，按 completed_at 归日
CREATE INDEX IF NOT EXISTS ix_tasks_user_done_at
    ON tasks (user_id, completed_at)
    WHERE status = 'done' AND completed_at IS NOT NULL;

-- 2.2 复习行为：review_records 按 (user_id, created_at) 取区间，再按 item_type 分流
CREATE INDEX IF NOT EXISTS ix_review_records_user_created ON review_records (user_id, created_at DESC);

-- 2.3 错题新增：error_records (user_id, created_at)
CREATE INDEX IF NOT EXISTS ix_error_records_user_created ON error_records (user_id, created_at DESC);

-- 2.4 模考场次：exam_sessions 只看已交卷的 submitted_at（121 分片补的 user_id）
CREATE INDEX IF NOT EXISTS ix_exam_sessions_user_submitted
    ON exam_sessions (user_id, submitted_at DESC)
    WHERE submitted_at IS NOT NULL;

-- 说明：study_sessions (user_id, date) 与 answer_records (user_id, created_at)
--       已分别由既有分片建好（ix_study_sessions_user / ix_answer_records_user），
--       此处不重复建（冗余索引只会拖慢写入）。
