-- 117: 用户管理查询侧补强（SQL 性能优化审查产出）
-- 1) 用户名大小写不敏感唯一索引：
--    登录 / 建号 / 改名的存在性判定一律 func.lower(username) = :ident，
--    104 的 UNIQUE(username) 区分大小写、服务不了该谓词 → 顺序扫描；
--    同时把「用户名不分大小写不得重复」从应用层检查下沉到 DB 层，消掉并发竞态。
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_username_lower ON users (lower(username));

-- 2) 注册时间范围过滤（管理后台账号列表 registered_from / registered_to）。
--    116 已覆盖 status / lower(email)，104 已覆盖 (role, is_active)，此处补齐时间轴。
CREATE INDEX IF NOT EXISTS ix_users_created_at ON users (created_at);
