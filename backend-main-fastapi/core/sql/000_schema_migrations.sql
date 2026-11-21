-- 000 · 迁移版本账本（完善方案 05 §3.1）
--
-- 目的：core/sql 的编号脚本此前"靠人工按序执行"，没有任何账本，
--       导致 memory 三表 / 枚举在 PG 中整体缺失却无人察觉（8 个接口 500）。
-- 约定：
--   * 结构变更一律新增编号脚本，禁止修改已登记的历史脚本（checksum 守卫会中止）。
--   * create_all 只负责全新库兜底；账本记录的是"SQL 脚本"的执行事实。
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,          -- 脚本文件名去扩展名，如 '108_user_data_isolation'
    checksum    TEXT NOT NULL,             -- 脚本文件 SHA256，防"执行后被偷改"
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms INTEGER,
    applied_by  TEXT                       -- 'startup' / 'push_update' / 'manual'
);

COMMENT ON TABLE schema_migrations IS 'core/sql 编号脚本执行账本（完善方案 05）';
