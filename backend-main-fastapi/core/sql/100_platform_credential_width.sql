-- =============================================================================
-- 100 系统凭据列改宽：VARCHAR(500) → text
-- 依赖：011
--
-- 为什么要改宽：``platform_configs`` 的 token / app_key / secret_key 与
-- ``ai_providers.api_key`` 从明文改为 AES-256-GCM 密文落库
-- （``utils/secret_codec.py``），存储格式变成
-- ``enc:v1:<base64(nonce(12) || ciphertext || tag(16))>``。同样 70 字符的
-- access_token 封装后是 132 字符，而百度的 refresh_token、OpenAI 形态的
-- sk- 密钥、以及任何 JWT 形态的凭据都可能逼近 500 —— 超长时 PG 直接报
-- "value too long"，表现是「重新授权失败」这种和长度毫无关系的错，排查成本极高。
-- PG 里 text 与 varchar 存取性能相同，长度上限只是元数据约束，去掉它没有代价。
--
-- 幂等：ALTER COLUMN TYPE 重复执行是 no-op；已建库（VARCHAR(500)）与
-- 新建库（011 里已改成 TEXT）都能安全跑过本文件。
-- =============================================================================

ALTER TABLE platform_configs ALTER COLUMN token      TYPE text;
ALTER TABLE platform_configs ALTER COLUMN app_key    TYPE text;
ALTER TABLE platform_configs ALTER COLUMN secret_key TYPE text;
ALTER TABLE ai_providers     ALTER COLUMN api_key    TYPE text;

COMMENT ON COLUMN platform_configs.token IS '访问令牌；AES-256-GCM 密文（enc:v1: 前缀），加解密见 utils/secret_codec.py';
COMMENT ON COLUMN platform_configs.app_key IS '应用标识；AES-256-GCM 密文（enc:v1: 前缀）';
COMMENT ON COLUMN platform_configs.secret_key IS '应用密钥；AES-256-GCM 密文（enc:v1: 前缀）';
COMMENT ON COLUMN ai_providers.api_key IS '服务商密钥；AES-256-GCM 密文（enc:v1: 前缀）';
