-- =============================================================================
-- 107 users 软删除：deleted_at 列（用户「生成无法删除」的落地）
-- 依赖：104（users 表）
--
-- 问题（2026-10-19 WebCraftBench 基准体检实测）
-- --------------------------------------------------
-- DELETE /api/admin/users/{id} → **405 Method Not Allowed**：
-- 后端根本没有删除端点。管理后台只能 PATCH {is_active:false}「停用」，
-- 但停用 ≠ 删除：用户名仍被 UNIQUE 占用、列表仍显示、关联学习数据仍在，
-- 用户「建了删不掉」的核心诉求没被满足。
--
-- 方案（软删除，可恢复）
-- ----------------------
-- 不做物理删除：users 无外键但用户往往带着目标 / 复习计划 / 学习轨迹等
-- 关联数据，物理删除会留下孤儿行且不可逆。改为 deleted_at 时间戳标记：
--   - 删除  = 写 deleted_at（列表默认隐藏、登录拒绝、用户名不再可复用）
--   - 恢复  = 清空 deleted_at（数据原样回来）
-- 与项目既有软删除口径一致（kaoyan_schools / documents 同样用 deleted_at）。
--
-- 幂等：可重复执行。ADD COLUMN IF NOT EXISTS + 部分索引 IF NOT EXISTS。
-- =============================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- 活跃（未软删）用户的部分索引：列表默认按 deleted_at IS NULL 过滤，
-- 用户表虽小，但让「活跃用户」走索引而非全表扫，且语义清晰。
CREATE INDEX IF NOT EXISTS ix_users_live
    ON users (id) WHERE deleted_at IS NULL;

COMMENT ON COLUMN users.deleted_at IS
    '软删除时间戳：非空表示该用户已被删除（列表隐藏 / 登录拒绝 / 用户名被占用）；清空即恢复';
