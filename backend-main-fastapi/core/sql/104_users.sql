-- =============================================================================
-- 104 users：账号与角色（doc 11 F11-01）。幂等，可重复执行。
-- 内置管理员不在这里写：密码哈希只能由应用启动时按 ADMIN_INITIAL_PASSWORD 生成，
-- SQL 里出现任何哈希/明文都等于把凭据提交进仓库。
-- =============================================================================
CREATE TABLE IF NOT EXISTS users (
    id                   SERIAL PRIMARY KEY,
    username             VARCHAR(64)  NOT NULL UNIQUE,
    password_hash        VARCHAR(255) NOT NULL,
    display_name         VARCHAR(64),
    role                 VARCHAR(16)  NOT NULL DEFAULT 'user',
    is_active            BOOLEAN      NOT NULL DEFAULT TRUE,
    must_change_password BOOLEAN      NOT NULL DEFAULT FALSE,
    token_version        INTEGER      NOT NULL DEFAULT 0,
    last_login_at        TIMESTAMPTZ,
    created_at           TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ
);

-- 早期版本建成了 naive TIMESTAMP（值本身是 UTC），按 UTC 解释原地转换
DO $$
DECLARE
    col text;
BEGIN
    FOREACH col IN ARRAY ARRAY['last_login_at', 'created_at', 'updated_at'] LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'users'
               AND column_name = col
               AND data_type = 'timestamp without time zone'
        ) THEN
            EXECUTE format(
                'ALTER TABLE users ALTER COLUMN %I TYPE TIMESTAMPTZ USING %I AT TIME ZONE ''UTC''',
                col, col
            );
        END IF;
    END LOOP;
END $$;

ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role;
ALTER TABLE users ADD  CONSTRAINT ck_users_role CHECK (role IN ('admin', 'user'));

CREATE INDEX IF NOT EXISTS ix_users_role_active ON users (role, is_active);
