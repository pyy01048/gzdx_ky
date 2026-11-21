-- =============================================================================
-- 120 服务端会话登记（V3.12 评审 C5/C6：refresh 轮换 + 登出即吊销）
-- 依赖：104（users）
--
-- 设计要点：
--   * 一次登录 = 一行会话。access/refresh token 均携带 sid（本表主键），
--     refresh 另携带一次性 jti（refresh_jti 唯一列，每次刷新轮换）。
--   * 登出 → revoked_at 置位 → 该会话 access/refresh 立即 401，其他设备不受影响。
--   * 旧 jti 重放 → 应用层吊销整行并自增 users.token_version（全家族失效）。
--   * 时间列沿用 116 的 TIMESTAMPTZ 口径（库内 UTC，驱动返回 aware）。
-- 幂等：可重复执行。
-- =============================================================================

CREATE TABLE IF NOT EXISTS auth_sessions (
    id           VARCHAR(36) PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_jti  VARCHAR(36) NOT NULL UNIQUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    revoked_at   TIMESTAMPTZ,
    ip           VARCHAR(64),
    user_agent   VARCHAR(300)
);

CREATE INDEX IF NOT EXISTS ix_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_auth_sessions_expires ON auth_sessions(expires_at);
