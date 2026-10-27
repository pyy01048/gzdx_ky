-- --------------------------------------------------------------------------- #
-- 096 documents 违禁/废弃标记列（is_junk）
-- --------------------------------------------------------------------------- #
-- 背景（2026-10-15）
-- ----------------------
-- 红线 3 规定：内容仅限 0854 相关学科（数学/英语/政治/数电/模电/信号/408/光学/复试），
-- 禁止混入法硕/西医/管综/教育等。实测 documents 表存在 196 篇违禁科目文档
-- （法律硕士 42 / 西医综合 41 / 经济类联考 35 / 管理类联考 30 / 教育学 29 / 心理学 19）。
--
-- 但 documents 表**没有任何软删/废弃标记**（stage 全 NULL、无 is_junk），
-- 于是"清违禁"只能物理 DELETE —— 破坏性且不可回滚。
-- 本分片补一个 `is_junk` 列，对齐 quiz_questions 的既有约定，
-- 让"标脏 → 人工确认 → 再清理"成为可能，查询侧只需加 `is_junk IS NOT TRUE`。
--
-- 幂等：ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS，可反复重跑。
-- 顺序：依赖 documents 建表分片，故排在序列末尾（紧随 095）。
-- --------------------------------------------------------------------------- #

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS is_junk BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN documents.is_junk IS
    '违禁/废弃文档标记（红线3：非 0854 学科内容）；列表与检索应过滤 is_junk IS NOT TRUE';

-- 查询侧高频过滤（文档列表/检索默认排除 junk）
CREATE INDEX IF NOT EXISTS idx_documents_is_junk ON documents (is_junk);
