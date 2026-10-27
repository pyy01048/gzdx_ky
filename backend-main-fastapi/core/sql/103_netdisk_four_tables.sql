-- #18 网盘：四表补全 + 错误码收口
-- 目标:
--   1. third_party_accounts: 凭据加密存储
--   2. netdisk_file_cache: 短期文件元数据缓存
--   3. preview_session: 预览会话进度追踪
--   4. operation_log: 操作审计日志
--   5. 错误码枚举定义

BEGIN;

-- 1. 第三方账号凭据表（AES-256-GCM加密token）
CREATE TABLE IF NOT EXISTS third_party_accounts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL, -- 关联用户ID
    provider VARCHAR(50) NOT NULL, -- baidu/quark/aliyun等
    uk_provider_uid VARCHAR(200) NOT NULL, -- 平台唯一标识（百度uk/夸克uid等）
    access_token_encrypted BYTEA, -- AES-256-GCM加密后的access_token
    refresh_token_encrypted BYTEA, -- AES-256-GCM加密后的refresh_token
    token_expires_at TIMESTAMPTZ, -- token过期时间
    account_name VARCHAR(200), -- 账号别名（用户自定义）
    is_active BOOLEAN NOT NULL DEFAULT true, -- 是否启用
    last_synced_at TIMESTAMPTZ, -- 最后同步时间
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(user_id, provider, uk_provider_uid)
);

CREATE INDEX IF NOT EXISTS idx_third_party_user ON third_party_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_third_party_provider ON third_party_accounts(provider);

COMMENT ON TABLE third_party_accounts IS '第三方网盘账号凭据（token加密存储）';
COMMENT ON COLUMN third_party_accounts.access_token_encrypted IS 'AES-256-GCM加密的access_token';
COMMENT ON COLUMN third_party_accounts.refresh_token_encrypted IS 'AES-256-GCM加密的refresh_token';

-- 2. 网盘文件元数据缓存表（5-15分钟TTL）
CREATE TABLE IF NOT EXISTS netdisk_file_cache (
    id BIGSERIAL PRIMARY KEY,
    uk_account_fs VARCHAR(200) NOT NULL, -- 账号+文件系统路径的唯一标识
    file_list JSONB NOT NULL, -- 文件列表快照 [{fs_id, path, size, ...}]
    expires_at TIMESTAMPTZ NOT NULL, -- 过期时间（5-15分钟）
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_netdisk_cache_uk ON netdisk_file_cache(uk_account_fs);
CREATE INDEX IF NOT EXISTS idx_netdisk_cache_expires ON netdisk_file_cache(expires_at);

COMMENT ON TABLE netdisk_file_cache IS '网盘文件列表缓存（短期有效，避免频繁API调用）';
COMMENT ON COLUMN netdisk_file_cache.uk_account_fs IS 'uk + provider + fs_path的组合唯一键';

-- 3. 预览会话表（记录播放进度）
CREATE TABLE IF NOT EXISTS preview_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    file_id VARCHAR(200) NOT NULL, -- 文件唯一标识（fs_id或path）
    play_position INTEGER DEFAULT 0, -- 视频/音频播放位置（秒）
    progress_percent FLOAT DEFAULT 0, -- 文档阅读进度百分比（0-100）
    page_number INTEGER, -- PDF当前页码
    session_expires_at TIMESTAMPTZ NOT NULL, -- 会话过期时间（24小时）
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(user_id, file_id)
);

CREATE INDEX IF NOT EXISTS idx_preview_user ON preview_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_preview_expires ON preview_sessions(session_expires_at);

COMMENT ON TABLE preview_sessions IS '文件预览会话（记录播放/阅读进度）';

-- 4. 网盘操作日志表
CREATE TABLE IF NOT EXISTS netdisk_operation_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    action VARCHAR(50) NOT NULL, -- netdisk.bind/unbind/preview/token_refresh/list/download
    provider VARCHAR(50), -- baidu/quark等
    resource_id VARCHAR(200), -- 涉及的文件ID或账号ID
    status VARCHAR(20) NOT NULL, -- success/failure
    error_code VARCHAR(20), -- 错误码（如40101/40110等）
    error_message TEXT, -- 错误详情
    ip_address INET, -- 客户端IP
    extra_metadata JSONB, -- 额外上下文（文件名、大小等）
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_netdisk_log_user ON netdisk_operation_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_netdisk_log_action ON netdisk_operation_logs(action);
CREATE INDEX IF NOT EXISTS idx_netdisk_log_created ON netdisk_operation_logs(created_at DESC);

COMMENT ON TABLE netdisk_operation_logs IS '网盘操作审计日志';
COMMENT ON COLUMN netdisk_operation_logs.action IS '点分式操作名：netdisk.bind/netdisk.unbind/netdisk.preview等';

-- 5. 网盘错误码枚举（供应用层使用）
-- 注意：PostgreSQL不支持直接创建应用层枚举，这里用注释记录规范
-- 
-- 错误码规范：
-- 40101: TOKEN_EXPIRED - 访问令牌已过期，需刷新
-- 40110: REFRESH_TOKEN_INVALID - 刷新令牌失效，需重新授权
-- 40310: PERMISSION_DENIED - 无权限访问该资源
-- 40410: FILE_NOT_FOUND - 文件不存在或已删除
-- 41510: UNSUPPORTED_FORMAT - 不支持的文件格式
-- 50000: INTERNAL_ERROR - 服务器内部错误

COMMIT;
