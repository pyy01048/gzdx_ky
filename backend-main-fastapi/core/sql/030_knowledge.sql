-- =============================================================================
-- 030 知识点域
-- 依赖：000 / 010 / 020
--
-- 关键设计（解决问题 5「掌握度全 0% + 关联硬编码」）：
--   本表**不再有 mastery 硬编码列**。掌握度改为从 review_records / answer_records
--   实时聚合的派生值，见 080 的视图 v_knowledge_mastery（含时间衰减加权）。
--   历史代码读 knowledge_points.mastery 的，由 080 的同名兼容视图兜底。
-- =============================================================================

CREATE TABLE IF NOT EXISTS knowledge_points (
    id                 BIGSERIAL    PRIMARY KEY,
    name               VARCHAR(300) NOT NULL,
    -- 归属：权威外键 + 兼容文本
    subject_id         BIGINT       REFERENCES subjects(id) ON DELETE SET NULL,
    subject            VARCHAR(50),
    chapter_id         BIGINT       REFERENCES subject_chapters(id) ON DELETE SET NULL,
    chapter            VARCHAR(200),
    parent_id          BIGINT       REFERENCES knowledge_points(id) ON DELETE SET NULL,
    -- 溯源
    document_id        BIGINT       REFERENCES documents(id) ON DELETE SET NULL,
    source_chunk_id    BIGINT       REFERENCES knowledge_chunks(id) ON DELETE SET NULL,
    source_chunk_index INTEGER,
    extract_source     extract_source,
    subject_source     VARCHAR(20),
    -- 考情属性
    exam_frequency     SMALLINT     NOT NULL DEFAULT 0,
    difficulty         SMALLINT     NOT NULL DEFAULT 3,
    question_types     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    description        TEXT,
    -- SM-2 调度状态（唯一权威，见 review_schedules）
    review_count       INTEGER      NOT NULL DEFAULT 0,
    last_review        TIMESTAMPTZ,
    ease_factor        REAL         NOT NULL DEFAULT 2.5,
    interval_days      INTEGER      NOT NULL DEFAULT 0,
    lapses             INTEGER      NOT NULL DEFAULT 0,
    question_count     INTEGER      NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_kp_self_ref CHECK (id <> parent_id),
    CONSTRAINT ck_kp_exam_freq CHECK (exam_frequency BETWEEN 0 AND 5),
    CONSTRAINT ck_kp_difficulty CHECK (difficulty BETWEEN 1 AND 5),
    CONSTRAINT ck_kp_ease CHECK (ease_factor >= 1.3 AND ease_factor <= 3.5),
    CONSTRAINT ck_kp_types CHECK (jsonb_typeof(question_types) = 'array')
);

COMMENT ON TABLE  knowledge_points IS '知识点表（章节→知识点→题型 三级结构中的第 2 级），掌握度为派生值不落库';
COMMENT ON COLUMN knowledge_points.id IS '主键，BIGSERIAL';
COMMENT ON COLUMN knowledge_points.name IS '知识点名称';
COMMENT ON COLUMN knowledge_points.subject_id IS '权威科目外键';
COMMENT ON COLUMN knowledge_points.subject IS '兼容列：科目中文名，由 ETL 回填';
COMMENT ON COLUMN knowledge_points.chapter_id IS '权威章节外键';
COMMENT ON COLUMN knowledge_points.chapter IS '兼容列：章节名';
COMMENT ON COLUMN knowledge_points.parent_id IS '父知识点 ID，顶级为 NULL';
COMMENT ON COLUMN knowledge_points.document_id IS '来源文档 ID，文档删除时置空保留知识点';
COMMENT ON COLUMN knowledge_points.source_chunk_id IS '来源分块 ID，可反查原文片段';
COMMENT ON COLUMN knowledge_points.source_chunk_index IS '来源分块在篇内序号';
COMMENT ON COLUMN knowledge_points.extract_source IS '抽取来源：smart_ingest / batch / manual';
COMMENT ON COLUMN knowledge_points.subject_source IS '学科判定来源：model / keyword / fallback';
COMMENT ON COLUMN knowledge_points.exam_frequency IS '考频 0-5，0 表示未统计';
COMMENT ON COLUMN knowledge_points.difficulty IS '难度 1-5';
COMMENT ON COLUMN knowledge_points.question_types IS '该知识点考过的题型数组，如 ["选择","计算"]';
COMMENT ON COLUMN knowledge_points.description IS '知识点描述';
COMMENT ON COLUMN knowledge_points.review_count IS '累计复习次数';
COMMENT ON COLUMN knowledge_points.last_review IS '上次复习时间（UTC，带时区）';
COMMENT ON COLUMN knowledge_points.ease_factor IS 'SM-2 难度因子，取值 1.3-3.5';
COMMENT ON COLUMN knowledge_points.interval_days IS '当前复习间隔（天）';
COMMENT ON COLUMN knowledge_points.lapses IS '遗忘次数';
COMMENT ON COLUMN knowledge_points.question_count IS '关联题目数（冗余，由触发器维护）';
COMMENT ON COLUMN knowledge_points.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN knowledge_points.updated_at IS '最后更新时间';

CREATE INDEX IF NOT EXISTS idx_kp_subject    ON knowledge_points (subject_id, chapter_id);
CREATE INDEX IF NOT EXISTS idx_kp_parent     ON knowledge_points (parent_id);
CREATE INDEX IF NOT EXISTS idx_kp_document   ON knowledge_points (document_id);
CREATE INDEX IF NOT EXISTS idx_kp_next_review ON knowledge_points (last_review);
CREATE INDEX IF NOT EXISTS idx_kp_name_trgm  ON knowledge_points USING GIN (name gin_trgm_ops);

CREATE OR REPLACE TRIGGER trg_kp_updated BEFORE UPDATE ON knowledge_points
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 知识点关系：前置 / 并列 / 包含
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS knowledge_point_relations (
    id            BIGSERIAL   PRIMARY KEY,
    source_kp_id  BIGINT      NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
    target_kp_id  BIGINT      NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
    relation_type relation_type NOT NULL,
    source        VARCHAR(100),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_kp_relation UNIQUE (source_kp_id, target_kp_id, relation_type),
    CONSTRAINT ck_kp_relation_self CHECK (source_kp_id <> target_kp_id)
);

COMMENT ON TABLE  knowledge_point_relations IS '知识点关系表，供刷题路径推荐与知识地图渲染';
COMMENT ON COLUMN knowledge_point_relations.source_kp_id IS '源知识点 ID';
COMMENT ON COLUMN knowledge_point_relations.target_kp_id IS '目标知识点 ID（由本表关系指向）';
COMMENT ON COLUMN knowledge_point_relations.relation_type IS '关系类型：prerequisite 前置 / parallel 并列 / contains 包含';
COMMENT ON COLUMN knowledge_point_relations.source IS '关系来源留痕：model / manual / import';
COMMENT ON COLUMN knowledge_point_relations.created_at IS '创建时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_kp_rel_target ON knowledge_point_relations (target_kp_id, relation_type);
