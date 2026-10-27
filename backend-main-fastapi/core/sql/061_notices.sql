-- =============================================================================
-- 061 研招通知：通知 / 订阅 / 提醒记录 / 提醒日志 / 采集日志 / 遗留归档表
-- 依赖：000 / 010 / 060
-- =============================================================================

-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS kaoyan_notices (
    id                BIGSERIAL      PRIMARY KEY,
    school_id         BIGINT         REFERENCES kaoyan_schools(id) ON DELETE SET NULL,
    school_name       TEXT,
    title             TEXT           NOT NULL,
    notice_type       notice_type    NOT NULL DEFAULT '公告',
    publish_date      TEXT,
    url               TEXT,
    source            TEXT,
    fetched_at        TEXT,
    importance_level  importance_level,
    importance_score  REAL,
    importance_reason TEXT,
    deadline_date     TEXT,
    events_json       TEXT,
    classified_at     TEXT,
    is_read           BOOLEAN        NOT NULL DEFAULT FALSE,
    is_starred        BOOLEAN        NOT NULL DEFAULT FALSE,
    read_at           TEXT,
    starred_at        TEXT,
    content           TEXT,
    is_noise          BOOLEAN        NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT uq_notice UNIQUE (school_name, title, publish_date)
);

COMMENT ON TABLE  kaoyan_notices IS '研招通知表：院校公告/简章/复试/调剂/录取信息';
COMMENT ON COLUMN kaoyan_notices.school_id IS '解析出的院校 ID，未匹配上为空';
COMMENT ON COLUMN kaoyan_notices.school_name IS '通知上写的院校名原文';
COMMENT ON COLUMN kaoyan_notices.notice_type IS '通知类型：公告 / 简章 / 复试 / 调剂 / 录取';
COMMENT ON COLUMN kaoyan_notices.publish_date IS '发布日期（YYYY-MM-DD）';
COMMENT ON COLUMN kaoyan_notices.importance_level IS '重要级：urgent / important / normal / low';
COMMENT ON COLUMN kaoyan_notices.importance_score IS '重要度评分 0-1';
COMMENT ON COLUMN kaoyan_notices.importance_reason IS '重要度判定理由';
COMMENT ON COLUMN kaoyan_notices.deadline_date IS '截止日期（YYYY-MM-DD）';
COMMENT ON COLUMN kaoyan_notices.events_json IS '抽取出的关键事件（JSON 数组）';
COMMENT ON COLUMN kaoyan_notices.is_noise IS '是否为噪声通知（招生宣传/无关资讯）';
COMMENT ON COLUMN kaoyan_notices.created_at IS '入库时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_notices_school   ON kaoyan_notices (school_id, publish_date DESC);
CREATE INDEX IF NOT EXISTS idx_notices_importance ON kaoyan_notices (importance_level, publish_date DESC);
CREATE INDEX IF NOT EXISTS idx_notices_deadline ON kaoyan_notices (deadline_date) WHERE deadline_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notices_title_trgm ON kaoyan_notices USING GIN (title gin_trgm_ops);

CREATE TABLE IF NOT EXISTS kaoyan_subscriptions (
    id          BIGSERIAL PRIMARY KEY,
    scope       subscription_scope NOT NULL,
    school_id   BIGINT    NOT NULL DEFAULT 0,
    school_name TEXT      NOT NULL DEFAULT '',
    major_name  TEXT      NOT NULL DEFAULT '',
    notice_type TEXT      NOT NULL DEFAULT '',
    keyword     TEXT      NOT NULL DEFAULT '',
    level_min   importance_level NOT NULL DEFAULT 'normal',
    enabled     BOOLEAN   NOT NULL DEFAULT TRUE,
    remark      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_subscription UNIQUE (scope, school_id, school_name, major_name, notice_type, keyword)
);

COMMENT ON TABLE  kaoyan_subscriptions IS '通知订阅表：按院校/专业/类型/关键词四个维度订阅';
COMMENT ON COLUMN kaoyan_subscriptions.scope IS '订阅维度：school / major / notice_type / keyword';
COMMENT ON COLUMN kaoyan_subscriptions.level_min IS '只推送不低于该重要级的通知';
COMMENT ON COLUMN kaoyan_subscriptions.enabled IS '是否启用该订阅';

CREATE INDEX IF NOT EXISTS idx_subscriptions_enabled ON kaoyan_subscriptions (enabled, scope);

CREATE TABLE IF NOT EXISTS kaoyan_alert_records (
    id               BIGSERIAL PRIMARY KEY,
    notice_id        BIGINT    NOT NULL REFERENCES kaoyan_notices(id) ON DELETE CASCADE,
    alert_kind       alert_kind NOT NULL,
    alert_date       TEXT      NOT NULL,
    title            TEXT,
    school_name      TEXT,
    notice_type      TEXT,
    importance_level TEXT,
    deadline_date    TEXT,
    days_left        INTEGER,
    message          TEXT      NOT NULL,
    acked            BOOLEAN   NOT NULL DEFAULT FALSE,
    acked_at         TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_alert UNIQUE (notice_id, alert_kind)
);

COMMENT ON TABLE  kaoyan_alert_records IS '提醒记录表：同一通知同一提醒类型只发一次';
COMMENT ON COLUMN kaoyan_alert_records.notice_id IS '关联通知 ID，通知删除时级联删除';
COMMENT ON COLUMN kaoyan_alert_records.alert_kind IS '提醒类型：deadline_soon / new_urgent / new_important / subscribed_new';
COMMENT ON COLUMN kaoyan_alert_records.alert_date IS '提醒发生日期（北京时间 YYYY-MM-DD）';
COMMENT ON COLUMN kaoyan_alert_records.days_left IS '距截止剩余天数';
COMMENT ON COLUMN kaoyan_alert_records.acked IS '用户是否已确认';
COMMENT ON COLUMN kaoyan_alert_records.acked_at IS '确认时间';

CREATE INDEX IF NOT EXISTS idx_alerts_unacked ON kaoyan_alert_records (acked, created_at DESC);

CREATE TABLE IF NOT EXISTS kaoyan_alert_runs (
    id             BIGSERIAL   PRIMARY KEY,
    ran_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    trigger_source VARCHAR(20) NOT NULL DEFAULT 'schedule',
    scanned        INTEGER     NOT NULL DEFAULT 0,
    created_alerts INTEGER     NOT NULL DEFAULT 0,
    skipped_dup    INTEGER     NOT NULL DEFAULT 0,
    elapsed_ms     INTEGER     NOT NULL DEFAULT 0,
    detail         TEXT,
    CONSTRAINT ck_alert_run_trigger CHECK (trigger_source IN ('schedule','manual'))
);

COMMENT ON TABLE  kaoyan_alert_runs IS '提醒任务执行日志：每次扫描的输入输出统计';
COMMENT ON COLUMN kaoyan_alert_runs.trigger_source IS '触发方式：schedule 定时 / manual 手动';
COMMENT ON COLUMN kaoyan_alert_runs.scanned IS '扫描的通知条数';
COMMENT ON COLUMN kaoyan_alert_runs.created_alerts IS '新生成的提醒条数';
COMMENT ON COLUMN kaoyan_alert_runs.skipped_dup IS '因重复跳过的条数';
COMMENT ON COLUMN kaoyan_alert_runs.elapsed_ms IS '本次扫描耗时（毫秒）';

CREATE INDEX IF NOT EXISTS idx_alert_runs_time ON kaoyan_alert_runs (ran_at DESC);

CREATE TABLE IF NOT EXISTS kaoyan_collection_runs (
    id         BIGSERIAL   PRIMARY KEY,
    source     VARCHAR(50) NOT NULL,
    scope      VARCHAR(200),
    item_type  VARCHAR(30),
    row_count  INTEGER     NOT NULL DEFAULT 0,
    detail     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    status     VARCHAR(20) NOT NULL DEFAULT 'success',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_collection_status CHECK (status IN ('success','partial','failed'))
);

COMMENT ON TABLE  kaoyan_collection_runs IS '数据采集执行日志';
COMMENT ON COLUMN kaoyan_collection_runs.source IS '采集来源';
COMMENT ON COLUMN kaoyan_collection_runs.item_type IS '采集的数据类型：school / major / notice / scoreline';
COMMENT ON COLUMN kaoyan_collection_runs.row_count IS '本次采集写入行数';
COMMENT ON COLUMN kaoyan_collection_runs.status IS '执行结果：success / partial / failed';
COMMENT ON COLUMN kaoyan_collection_runs.created_at IS '执行时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_collection_runs_time ON kaoyan_collection_runs (created_at DESC);

-- 专业课 ↔ 知识库文档 关联
CREATE TABLE IF NOT EXISTS kaoyan_major_kb_link (
    id           BIGSERIAL PRIMARY KEY,
    major_id     BIGINT    NOT NULL REFERENCES kaoyan_majors(id) ON DELETE CASCADE,
    school_id    BIGINT    NOT NULL REFERENCES kaoyan_schools(id) ON DELETE CASCADE,
    school_name  TEXT      NOT NULL DEFAULT '',
    major_name   TEXT      NOT NULL DEFAULT '',
    major_code   VARCHAR(20),
    subject_name TEXT      NOT NULL,
    match_level  VARCHAR(10) NOT NULL DEFAULT 'L1',
    match_type   VARCHAR(20) NOT NULL DEFAULT 'exact',
    kb_doc_count INTEGER   NOT NULL DEFAULT 0,
    confidence   REAL      NOT NULL DEFAULT 1.0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_major_kb UNIQUE (major_id, subject_name),
    CONSTRAINT ck_kb_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT ck_kb_match_level CHECK (match_level IN ('L1','L2','L3'))
);

COMMENT ON TABLE  kaoyan_major_kb_link IS '招生专业与知识库专业课的匹配关系，用于专业课资料推荐';
COMMENT ON COLUMN kaoyan_major_kb_link.match_level IS '匹配等级：L1 精确 / L2 高度相似 / L3 弱匹配';
COMMENT ON COLUMN kaoyan_major_kb_link.match_type IS '匹配方式：exact 精确 / fuzzy 模糊 / alias 别名';

-- --------------------------------------------------------------------------- #
-- 历史遗留院校表：仅归档保留，新代码不得写入
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS universities_legacy (
    id             BIGSERIAL    PRIMARY KEY,
    name           VARCHAR(200) NOT NULL,
    type           VARCHAR(50),
    city           VARCHAR(50),
    major_name     VARCHAR(200),
    score_lines    JSONB,
    admission_ratio VARCHAR(50),
    difficulty     SMALLINT,
    remark         TEXT,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  universities_legacy IS '历史遗留院校表（只读归档）：已被 kaoyan_schools 取代，禁止新写入';
COMMENT ON COLUMN universities_legacy.score_lines IS '历史分数线（JSON 对象）';
COMMENT ON COLUMN universities_legacy.admission_ratio IS '历史报录比文本';
COMMENT ON COLUMN universities_legacy.difficulty IS '难度评级';
