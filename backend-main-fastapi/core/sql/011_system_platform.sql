-- =============================================================================
-- 011 平台配置：第三方平台对接 / 大模型供应商 / 自定义链接
-- 依赖：000 / 010
-- =============================================================================

-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS platform_configs (
    id            BIGSERIAL    PRIMARY KEY,
    platform_name VARCHAR(100) NOT NULL,
    token         TEXT,
    app_key       TEXT,
    secret_key    TEXT,
    sync_enabled  BOOLEAN      NOT NULL DEFAULT FALSE,
    sync_frequency VARCHAR(50) NOT NULL DEFAULT 'manual',
    last_sync     TIMESTAMPTZ,
    extra         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_platform_name UNIQUE (platform_name),
    CONSTRAINT ck_platform_freq CHECK (
        sync_frequency IN ('manual','hourly','daily','weekly'))
);

COMMENT ON TABLE  platform_configs IS '第三方平台对接配置（网盘/题库/研招等）';
COMMENT ON COLUMN platform_configs.platform_name IS '平台名称，唯一';
COMMENT ON COLUMN platform_configs.token IS '访问令牌；AES-256-GCM 密文（enc:v1: 前缀），加解密见 utils/secret_codec.py';
COMMENT ON COLUMN platform_configs.app_key IS '应用标识；AES-256-GCM 密文（enc:v1: 前缀）';
COMMENT ON COLUMN platform_configs.secret_key IS '应用密钥；AES-256-GCM 密文（enc:v1: 前缀）';
COMMENT ON COLUMN platform_configs.sync_enabled IS '是否启用自动同步';
COMMENT ON COLUMN platform_configs.sync_frequency IS '同步频率：manual/hourly/daily/weekly';
COMMENT ON COLUMN platform_configs.last_sync IS '上次同步时间';
COMMENT ON COLUMN platform_configs.extra IS '平台专属扩展配置';
COMMENT ON COLUMN platform_configs.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN platform_configs.updated_at IS '最后更新时间';

CREATE OR REPLACE TRIGGER trg_platform_configs_updated BEFORE UPDATE ON platform_configs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS ai_providers (
    id                BIGSERIAL    PRIMARY KEY,
    name              VARCHAR(100) NOT NULL,
    provider_type     VARCHAR(50)  NOT NULL DEFAULT 'openai_compatible',
    api_key           TEXT,
    base_url          VARCHAR(500),
    model_name        VARCHAR(200),
    temperature       REAL         NOT NULL DEFAULT 0.7,
    is_default        BOOLEAN      NOT NULL DEFAULT FALSE,
    is_enabled        BOOLEAN      NOT NULL DEFAULT TRUE,
    fallback_priority INTEGER      NOT NULL DEFAULT 100,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_ai_provider_name UNIQUE (name),
    CONSTRAINT ck_ai_temperature CHECK (temperature >= 0 AND temperature <= 2)
);

COMMENT ON TABLE  ai_providers IS '大模型供应商配置，按 fallback_priority 升序降级';
COMMENT ON COLUMN ai_providers.name IS '供应商配置名，唯一';
COMMENT ON COLUMN ai_providers.provider_type IS '接入协议类型，如 openai_compatible';
COMMENT ON COLUMN ai_providers.api_key IS 'API 密钥';
COMMENT ON COLUMN ai_providers.base_url IS '接口基地址';
COMMENT ON COLUMN ai_providers.model_name IS '默认模型名';
COMMENT ON COLUMN ai_providers.temperature IS '采样温度，取值 0-2';
COMMENT ON COLUMN ai_providers.is_default IS '是否为默认供应商';
COMMENT ON COLUMN ai_providers.is_enabled IS '是否启用';
COMMENT ON COLUMN ai_providers.fallback_priority IS '降级优先级，数字越小越优先';
COMMENT ON COLUMN ai_providers.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN ai_providers.updated_at IS '最后更新时间';

CREATE INDEX IF NOT EXISTS idx_ai_providers_enabled ON ai_providers (is_enabled, fallback_priority);

CREATE OR REPLACE TRIGGER trg_ai_providers_updated BEFORE UPDATE ON ai_providers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS custom_links (
    id         BIGSERIAL    PRIMARY KEY,
    name       VARCHAR(200) NOT NULL,
    url        VARCHAR(1000) NOT NULL,
    category   VARCHAR(100) NOT NULL DEFAULT 'general',
    sort_order INTEGER      NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  custom_links IS '用户自定义快捷链接';
COMMENT ON COLUMN custom_links.name IS '链接显示名';
COMMENT ON COLUMN custom_links.url IS '链接地址';
COMMENT ON COLUMN custom_links.category IS '分组分类';
COMMENT ON COLUMN custom_links.sort_order IS '组内排序权重，升序';
COMMENT ON COLUMN custom_links.created_at IS '创建时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_custom_links_cat ON custom_links (category, sort_order);
