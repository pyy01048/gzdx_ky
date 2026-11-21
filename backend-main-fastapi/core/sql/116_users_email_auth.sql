-- =============================================================================
-- 116 邮箱注册 / 邮箱找回密码 / RBAC 权限表 / 认证审计（《用户管理界面.md》邮箱版）
-- 依赖：104（users）、107（deleted_at）
--
-- 设计要点（对应方案文档）：
--   * users 增加 email / email_verified_at / status 状态机列。
--     status: unverified | active | disabled | pending_deletion | deleted
--     旧数据回填：deleted_at 非空→deleted；is_active=false→disabled；其余→active。
--   * email_tokens：验证/重置 token 只存 SHA-256 哈希，不存明文；
--     重置 token 额外绑定当时密码哈希指纹（pwd_fingerprint），改密即失效。
--   * roles / role_permission：角色→操作级权限映射存表，不硬编码（§2.2）。
--   * auth_events：认证与账号状态变更审计（actor/action/target/时间/结果/IP）。
--   * 邮箱唯一性用 lower(email) 部分唯一索引（NULL 不参与，兼容无邮箱旧账号）。
-- 幂等：可重复执行。
-- =============================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS email               VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at   TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS status              VARCHAR(20) NOT NULL DEFAULT 'active';
ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled_reason     TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled_at         TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS deletion_requested_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_ip       VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS login_count         INTEGER NOT NULL DEFAULT 0;

-- 旧数据回填（只回填一次：仅当 status 仍是默认值且与旧标志不一致时）
UPDATE users SET status = 'deleted'
 WHERE deleted_at IS NOT NULL AND status <> 'deleted';
UPDATE users SET status = 'disabled'
 WHERE deleted_at IS NULL AND is_active = FALSE AND status = 'active';

ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_status;
ALTER TABLE users ADD  CONSTRAINT ck_users_status
    CHECK (status IN ('unverified','active','disabled','pending_deletion','deleted'));

-- 角色约束放开 doc_admin（文档资料管理员：审核/文档操作，无用户管理权）
ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role;
ALTER TABLE users ADD  CONSTRAINT ck_users_role CHECK (role IN ('admin','doc_admin','user'));

CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email_lower
    ON users (lower(email)) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_users_status ON users (status);

-- ---------------------------------------------------------------------------
-- 邮箱 token（验证 24h / 重置 60min，只存哈希）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS email_tokens (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind            VARCHAR(16) NOT NULL CHECK (kind IN ('verify','reset')),
    token_hash      VARCHAR(64) NOT NULL,
    pwd_fingerprint VARCHAR(64),
    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    request_ip      VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS ix_email_tokens_hash ON email_tokens (token_hash);
CREATE INDEX IF NOT EXISTS ix_email_tokens_user_kind ON email_tokens (user_id, kind, created_at);

-- ---------------------------------------------------------------------------
-- RBAC：角色与操作级权限（§2.2，映射存表不硬编码）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
    role        VARCHAR(16) PRIMARY KEY,
    label       VARCHAR(64) NOT NULL,
    description TEXT
);
CREATE TABLE IF NOT EXISTS role_permission (
    role       VARCHAR(16) NOT NULL REFERENCES roles(role) ON DELETE CASCADE,
    permission VARCHAR(64) NOT NULL,
    PRIMARY KEY (role, permission)
);

INSERT INTO roles (role, label, description) VALUES
    ('admin',     '管理员',         '全站用户管理、角色任命、审计、系统配置'),
    ('doc_admin', '文档资料管理员', '资料审核/文档元数据/下架/资料统计；无用户账号管理权'),
    ('user',      '普通用户',       '浏览下载公开资料、上传待审、个人资料与学习记录')
ON CONFLICT (role) DO UPDATE SET label = EXCLUDED.label, description = EXCLUDED.description;

INSERT INTO role_permission (role, permission) VALUES
    ('admin','user:list'), ('admin','user:disable'), ('admin','user:enable'),
    ('admin','user:assign_role'), ('admin','user:force_reset_password'),
    ('admin','doc:review'), ('admin','doc:unpublish'), ('admin','doc:edit_metadata'), ('admin','doc:view_stats'),
    ('admin','doc:upload'), ('admin','doc:download'), ('admin','profile:edit_self'),
    ('admin','audit:view'), ('admin','system:config'),
    ('doc_admin','doc:review'), ('doc_admin','doc:unpublish'), ('doc_admin','doc:edit_metadata'),
    ('doc_admin','doc:view_stats'), ('doc_admin','doc:upload'), ('doc_admin','doc:download'),
    ('doc_admin','profile:edit_self'),
    ('user','doc:upload'), ('user','doc:download'), ('user','profile:edit_self')
ON CONFLICT (role, permission) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 认证审计（只读；管理端不可篡改删除——不提供 UPDATE/DELETE 端点）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auth_events (
    id          SERIAL PRIMARY KEY,
    event_type  VARCHAR(64) NOT NULL,
    user_id     INTEGER,
    email       VARCHAR(255),
    actor_id    INTEGER,
    success     BOOLEAN NOT NULL DEFAULT TRUE,
    ip          VARCHAR(64),
    user_agent  VARCHAR(255),
    detail      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_auth_events_user ON auth_events (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_auth_events_type_time ON auth_events (event_type, created_at);
