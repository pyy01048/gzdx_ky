-- 210：专业—考试科目—教材/资源显式关联。
-- 207 只负责“专业匹配科目”，本表负责“该专业该科目的教材或资源证据”。
-- 不从 textbook_schools（学校级）推导专业级关系，也不在此迁移中伪造任何资源。

CREATE TABLE IF NOT EXISTS kaoyan_major_subject_resources (
    id BIGSERIAL PRIMARY KEY,
    major_id BIGINT NOT NULL REFERENCES kaoyan_majors(id) ON DELETE CASCADE,
    subject_id BIGINT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    resource_type VARCHAR(30) NOT NULL DEFAULT 'textbook',
    textbook_id BIGINT REFERENCES textbooks(id) ON DELETE SET NULL,
    title VARCHAR(300) NOT NULL,
    url TEXT,
    description TEXT,
    source JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_url TEXT,
    verification_status VARCHAR(20) NOT NULL DEFAULT 'unverified',
    verified_at TIMESTAMPTZ,
    verified_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    owner_user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    is_public BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_major_subject_resource_type
        CHECK (resource_type IN (
            'textbook', 'syllabus', 'outline', 'notes',
            'courseware', 'past_paper', 'link', 'other'
        )),
    CONSTRAINT ck_major_subject_resource_verification
        CHECK (verification_status IN ('verified', 'unverified', 'rejected')),
    CONSTRAINT ck_major_subject_resource_title
        CHECK (char_length(btrim(title)) > 0),
    CONSTRAINT ck_major_subject_resource_textbook
        CHECK (resource_type <> 'textbook' OR textbook_id IS NOT NULL),
    CONSTRAINT ck_major_subject_resource_source
        CHECK (jsonb_typeof(source) = 'object'),
    CONSTRAINT ck_major_subject_resource_metadata
        CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT ck_major_subject_resource_private_owner
        CHECK (is_public = TRUE OR owner_user_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_major_subject_resources_major_subject
    ON kaoyan_major_subject_resources (major_id, subject_id, sort_order, id);
CREATE INDEX IF NOT EXISTS ix_major_subject_resources_subject
    ON kaoyan_major_subject_resources (subject_id, id);
CREATE INDEX IF NOT EXISTS ix_major_subject_resources_visibility
    ON kaoyan_major_subject_resources (is_public, owner_user_id, id)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS ix_major_subject_resources_active_verification
    ON kaoyan_major_subject_resources (major_id, verification_status, is_active);

CREATE UNIQUE INDEX IF NOT EXISTS uq_major_subject_resource_textbook
    ON kaoyan_major_subject_resources (major_id, subject_id, textbook_id)
    WHERE resource_type = 'textbook' AND textbook_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_major_subject_resource_link
    ON kaoyan_major_subject_resources (major_id, subject_id, url)
    WHERE resource_type = 'link' AND url IS NOT NULL;

DROP TRIGGER IF EXISTS trg_major_subject_resources_updated_at
    ON kaoyan_major_subject_resources;
CREATE TRIGGER trg_major_subject_resources_updated_at
    BEFORE UPDATE ON kaoyan_major_subject_resources
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE kaoyan_major_subject_resources IS
    '专业—科目—教材/资源显式证据；学校级 textbook_schools 不自动等于专业指定教材';
COMMENT ON COLUMN kaoyan_major_subject_resources.source IS
    '采集/人工核验来源 JSON；空对象表示尚未标注来源，API 不得伪造';
COMMENT ON COLUMN kaoyan_major_subject_resources.verification_status IS
    'verified=已核验，unverified=待核验，rejected=拒绝且默认不展示';
COMMENT ON COLUMN kaoyan_major_subject_resources.owner_user_id IS
    '私有资源所属用户；is_public=false 时必须设置，公开资源可无所有者';
COMMENT ON COLUMN kaoyan_major_subject_resources.sort_order IS
    '同一专业与科目内的展示顺序，数值越小越靠前';
COMMENT ON COLUMN kaoyan_major_subject_resources.id IS '资源关联主键';
COMMENT ON COLUMN kaoyan_major_subject_resources.major_id IS '207 专业实体外键';
COMMENT ON COLUMN kaoyan_major_subject_resources.subject_id IS '该专业已 matched 的考试科目外键';
COMMENT ON COLUMN kaoyan_major_subject_resources.resource_type IS '教材、大纲、提纲、笔记、课件、真题资料、链接或其他';
COMMENT ON COLUMN kaoyan_major_subject_resources.textbook_id IS '可选教材目录实体；textbook 类型必须提供';
COMMENT ON COLUMN kaoyan_major_subject_resources.title IS '资源展示标题';
COMMENT ON COLUMN kaoyan_major_subject_resources.url IS '资源访问地址；前端只允许 http/https';
COMMENT ON COLUMN kaoyan_major_subject_resources.description IS '资源用途或适用说明';
COMMENT ON COLUMN kaoyan_major_subject_resources.source_url IS '采集或核验依据地址';
COMMENT ON COLUMN kaoyan_major_subject_resources.verified_at IS '最近核验时间，未核验时为空';
COMMENT ON COLUMN kaoyan_major_subject_resources.verified_by IS '核验人；仅管理语义使用，不参与公开读取绕过';
COMMENT ON COLUMN kaoyan_major_subject_resources.is_active IS 'false 表示停用且默认不展示';
COMMENT ON COLUMN kaoyan_major_subject_resources.is_public IS 'true 表示所有访客可见；false 仅所有者可见';
COMMENT ON COLUMN kaoyan_major_subject_resources.metadata IS '扩展元数据 JSON，不存放鉴权凭证';
COMMENT ON COLUMN kaoyan_major_subject_resources.created_at IS '记录创建时间';
COMMENT ON COLUMN kaoyan_major_subject_resources.updated_at IS '记录更新时间，由触发器维护';
