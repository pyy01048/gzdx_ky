-- 209：存量 auth_sessions 时间列补齐 TIMESTAMPTZ 与非空默认值。
-- 120 的 CREATE TABLE IF NOT EXISTS 不会改建表前的列；旧库因此仍是无时区时间。
-- 既有 naive 值按 UTC 解释，重复执行只处理尚未转换的列。

UPDATE auth_sessions
   SET created_at = COALESCE(created_at, expires_at, now()),
       last_used_at = COALESCE(last_used_at, created_at, expires_at, now())
 WHERE created_at IS NULL OR last_used_at IS NULL;

DO $$
DECLARE
    col text;
BEGIN
    FOREACH col IN ARRAY ARRAY['created_at', 'last_used_at', 'expires_at', 'revoked_at'] LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'auth_sessions'
               AND column_name = col
               AND data_type = 'timestamp without time zone'
        ) THEN
            EXECUTE format(
                'ALTER TABLE auth_sessions ALTER COLUMN %I TYPE TIMESTAMPTZ USING %I AT TIME ZONE ''UTC''',
                col, col
            );
        END IF;
    END LOOP;
END $$;

ALTER TABLE auth_sessions ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE auth_sessions ALTER COLUMN last_used_at SET DEFAULT now();
ALTER TABLE auth_sessions ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE auth_sessions ALTER COLUMN last_used_at SET NOT NULL;

COMMENT ON COLUMN auth_sessions.created_at IS '会话创建时间（TIMESTAMPTZ，UTC）';
COMMENT ON COLUMN auth_sessions.last_used_at IS '最近刷新时间（TIMESTAMPTZ，UTC）';
COMMENT ON COLUMN auth_sessions.expires_at IS '会话过期时间（TIMESTAMPTZ，UTC）';
COMMENT ON COLUMN auth_sessions.revoked_at IS '会话吊销时间（TIMESTAMPTZ，UTC；NULL=未吊销）';
