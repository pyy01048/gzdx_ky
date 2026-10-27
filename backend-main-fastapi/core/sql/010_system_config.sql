-- =============================================================================
-- 010 系统配置域：科目权威源 / 章节 / 科目配置 / 平台配置 / AI 供应商
-- 依赖：000
--
-- 关键设计（解决问题 1「科目口径三套」）：
--   实测三张表不是同一概念的三种写法，而是**两个概念被混装**：
--     · subject_prototypes(18) + subject_config(28) → 备考科目（教学/出题口径）
--     · kaoyan_subjects(8)                          → 招生学科（0803/0812 等学科代码）
--   因此这里不合并成一张"万能科目表"，而是拆成正交的两张权威表 + 一张映射表：
--     subjects        —— 备考科目唯一权威源
--     disciplines     —— 招生学科唯一权威源（原 kaoyan_subjects 更名对齐）
--     subject_discipline_links —— 两者多对多映射（如"电路"→电气工程/电子科学与技术）
--     subject_aliases —— 收敛散落在 18 处代码里的硬编码科目字符串
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- 备考科目：全项目唯一权威源
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS subjects (
    id            BIGSERIAL    PRIMARY KEY,
    -- 权威代码：全项目唯一引用键，代码里一律用 code，禁止再写中文科目字面量
    code          VARCHAR(32)  NOT NULL,
    name          VARCHAR(100) NOT NULL,
    short_name    VARCHAR(50),
    category      subject_category NOT NULL DEFAULT 'professional',
    parent_id     BIGINT       REFERENCES subjects(id) ON DELETE SET NULL,
    exam_overlap  TEXT,
    description   TEXT,
    sort_order    INTEGER      NOT NULL DEFAULT 0,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    is_custom     BOOLEAN      NOT NULL DEFAULT FALSE,
    legacy_names  JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_subjects_code UNIQUE (code),
    CONSTRAINT ck_subjects_self_ref CHECK (id <> parent_id)
);

COMMENT ON TABLE  subjects IS '备考科目唯一权威表：取代 subject_prototypes 与 subject_config 两套口径';
COMMENT ON COLUMN subjects.code IS '权威科目代码（如 politics/english/math/circuit），代码与外键引用的唯一键';
COMMENT ON COLUMN subjects.name IS '科目中文名，仅用于展示';
COMMENT ON COLUMN subjects.short_name IS '科目简称，用于窄屏与标签展示';
COMMENT ON COLUMN subjects.category IS '科目分类：public 公共课 / professional 专业课 / retest 复试科目';
COMMENT ON COLUMN subjects.parent_id IS '父科目 ID，用于"专业课→子模块"两级结构，顶级为 NULL';
COMMENT ON COLUMN subjects.exam_overlap IS '科目间的考纲重叠说明，供跨科目去重与出题范围提示';
COMMENT ON COLUMN subjects.description IS '科目说明';
COMMENT ON COLUMN subjects.sort_order IS '展示排序权重，升序';
COMMENT ON COLUMN subjects.is_active IS '是否启用，停用的科目不参与出题与统计';
COMMENT ON COLUMN subjects.is_custom IS '是否用户自定义科目';
COMMENT ON COLUMN subjects.legacy_names IS '历史中文名数组，保留"光学/光学工程/光学与工程光学"等旧写法用于 ETL 归档';
COMMENT ON COLUMN subjects.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN subjects.updated_at IS '最后更新时间，由 set_updated_at 触发器维护';

CREATE INDEX IF NOT EXISTS idx_subjects_parent    ON subjects (parent_id);
CREATE INDEX IF NOT EXISTS idx_subjects_active    ON subjects (is_active, sort_order);
-- 历史名反查：ETL 阶段把旧中文名映射到权威 code 时的加速索引
CREATE INDEX IF NOT EXISTS idx_subjects_legacy    ON subjects USING GIN (legacy_names);

CREATE OR REPLACE TRIGGER trg_subjects_updated BEFORE UPDATE ON subjects
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 科目别名：收敛硬编码
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS subject_aliases (
    id            BIGSERIAL    PRIMARY KEY,
    alias         VARCHAR(100) NOT NULL,
    subject_id    BIGINT       NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    alias_source  VARCHAR(50)  NOT NULL DEFAULT 'legacy_code',
    is_primary    BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_subject_alias UNIQUE (alias, subject_id)
);

COMMENT ON TABLE  subject_aliases IS '科目别名表：把散落在 18 处代码里的硬编码科目字符串收敛到权威科目';
COMMENT ON COLUMN subject_aliases.alias IS '别名原字符串，如 公共课-数学 / 408 / 数模电';
COMMENT ON COLUMN subject_aliases.subject_id IS '指向的权威备考科目 ID';
COMMENT ON COLUMN subject_aliases.alias_source IS '别名来源：legacy_code 旧代码 / import 导入 / user 用户输入';
COMMENT ON COLUMN subject_aliases.is_primary IS '一个别名命中多行时，本行是否为首选解析结果';
COMMENT ON COLUMN subject_aliases.created_at IS '创建时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_subject_aliases_lookup ON subject_aliases (alias) WHERE is_primary;

-- --------------------------------------------------------------------------- #
-- 章节：把 subject_config.chapters 的 JSON 数组升级为可关联实体
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS subject_chapters (
    id          BIGSERIAL    PRIMARY KEY,
    subject_id  BIGINT       NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    code        VARCHAR(64)  NOT NULL,
    title       VARCHAR(300) NOT NULL,
    parent_id   BIGINT       REFERENCES subject_chapters(id) ON DELETE SET NULL,
    sort_order  INTEGER      NOT NULL DEFAULT 0,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_chapter_code UNIQUE (subject_id, code),
    CONSTRAINT ck_chapter_self_ref CHECK (id <> parent_id)
);

COMMENT ON TABLE  subject_chapters IS '科目章节权威表：取代 subject_config.chapters 的 JSON 数组，支持按章节聚合统计';
COMMENT ON COLUMN subject_chapters.subject_id IS '所属备考科目 ID';
COMMENT ON COLUMN subject_chapters.code IS '章节代码，同一科目内唯一';
COMMENT ON COLUMN subject_chapters.title IS '章节标题';
COMMENT ON COLUMN subject_chapters.parent_id IS '父章节 ID，支持"章→节"两级';
COMMENT ON COLUMN subject_chapters.sort_order IS '章节内排序权重，升序';
COMMENT ON COLUMN subject_chapters.is_active IS '是否启用';
COMMENT ON COLUMN subject_chapters.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN subject_chapters.updated_at IS '最后更新时间';

CREATE INDEX IF NOT EXISTS idx_chapters_subject ON subject_chapters (subject_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_chapters_parent  ON subject_chapters (parent_id);

CREATE OR REPLACE TRIGGER trg_chapters_updated BEFORE UPDATE ON subject_chapters
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 科目配置：题型与章节的默认取值范围（原 subject_config 的正规化版）
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS subject_configs (
    id             BIGSERIAL PRIMARY KEY,
    subject_id     BIGINT   NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    question_types JSONB    NOT NULL DEFAULT '[]'::jsonb,
    is_custom      BOOLEAN  NOT NULL DEFAULT FALSE,
    extra          JSONB    NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_subject_config UNIQUE (subject_id),
    CONSTRAINT ck_subject_configs_types CHECK (jsonb_typeof(question_types) = 'array')
);

COMMENT ON TABLE  subject_configs IS '科目配置表：科目默认题型与扩展配置，章节改由 subject_chapters 承载';
COMMENT ON COLUMN subject_configs.subject_id IS '所属备考科目 ID，一对一';
COMMENT ON COLUMN subject_configs.question_types IS '该科目支持的题型数组，元素为 question_type 枚举值字符串';
COMMENT ON COLUMN subject_configs.is_custom IS '是否用户自定义配置';
COMMENT ON COLUMN subject_configs.extra IS '扩展配置项（JSON 对象）';
COMMENT ON COLUMN subject_configs.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN subject_configs.updated_at IS '最后更新时间';

CREATE OR REPLACE TRIGGER trg_subject_configs_updated BEFORE UPDATE ON subject_configs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 招生学科：原 kaoyan_subjects 更名对齐，与 subjects 彻底解耦
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS disciplines (
    id           BIGSERIAL    PRIMARY KEY,
    code         VARCHAR(20)  NOT NULL,
    name         VARCHAR(100) NOT NULL,
    category     VARCHAR(50),
    parent_code  VARCHAR(20),
    exam_overlap TEXT,
    description  TEXT,
    sort_order   INTEGER      NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_disciplines_code UNIQUE (code)
);

COMMENT ON TABLE  disciplines IS '招生学科权威表（原 kaoyan_subjects）：研招学科代码，如 0812 计算机科学与技术';
COMMENT ON COLUMN disciplines.code IS '学科代码，研招口径，如 0803/0808/0812';
COMMENT ON COLUMN disciplines.name IS '学科名称';
COMMENT ON COLUMN disciplines.category IS '学科门类（实测值：工学）';
COMMENT ON COLUMN disciplines.parent_code IS '上级学科代码';
COMMENT ON COLUMN disciplines.exam_overlap IS '学科间考纲重叠说明';
COMMENT ON COLUMN disciplines.description IS '学科说明';
COMMENT ON COLUMN disciplines.sort_order IS '展示排序权重，升序';
COMMENT ON COLUMN disciplines.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN disciplines.updated_at IS '最后更新时间';

CREATE OR REPLACE TRIGGER trg_disciplines_updated BEFORE UPDATE ON disciplines
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 备考科目 ↔ 招生学科 映射（多对多）
CREATE TABLE IF NOT EXISTS subject_discipline_links (
    id            BIGSERIAL PRIMARY KEY,
    subject_id    BIGINT   NOT NULL REFERENCES subjects(id)    ON DELETE CASCADE,
    discipline_id BIGINT   NOT NULL REFERENCES disciplines(id) ON DELETE CASCADE,
    is_primary    BOOLEAN  NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_subject_discipline UNIQUE (subject_id, discipline_id)
);

COMMENT ON TABLE  subject_discipline_links IS '备考科目与招生学科的多对多映射，解决两套口径无法一一对应的问题';
COMMENT ON COLUMN subject_discipline_links.subject_id IS '备考科目 ID';
COMMENT ON COLUMN subject_discipline_links.discipline_id IS '招生学科 ID';
COMMENT ON COLUMN subject_discipline_links.is_primary IS '是否为主映射（一科对多科时用于默认归类）';
COMMENT ON COLUMN subject_discipline_links.created_at IS '创建时间（UTC，带时区）';

-- --------------------------------------------------------------------------- #
-- 科目原型向量：分块学科分类的聚类中心
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS subject_prototypes (
    id         BIGSERIAL PRIMARY KEY,
    subject_id BIGINT    NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    engine     vector_engine NOT NULL DEFAULT 'unknown',
    dim        INTEGER   NOT NULL,
    -- 退化方案：float32 小端字节数组（Python 侧余弦检索）
    prototype  BYTEA     NOT NULL,
    n_samples  INTEGER   NOT NULL DEFAULT 0,
    built_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_subject_prototype UNIQUE (subject_id, engine),
    CONSTRAINT ck_prototype_dim CHECK (dim > 0 AND dim <= 4096)
);

COMMENT ON TABLE  subject_prototypes IS '科目原型向量：学科分类用的聚类中心，实测项目用 bge 512 维';
COMMENT ON COLUMN subject_prototypes.subject_id IS '所属备考科目 ID';
COMMENT ON COLUMN subject_prototypes.engine IS '生成该向量的引擎：bge / openai / unknown';
COMMENT ON COLUMN subject_prototypes.dim IS '向量维度，实测 512';
COMMENT ON COLUMN subject_prototypes.prototype IS '原型向量的 float32 小端字节数组';
COMMENT ON COLUMN subject_prototypes.n_samples IS '构建该原型使用的样本数';
COMMENT ON COLUMN subject_prototypes.built_at IS '构建时间（UTC，带时区）';

-- pgvector 可用时补一列真正的 vector，并建 HNSW 索引（退化方案下这两步自动跳过）
DO $$
BEGIN
    IF pgvector_available() THEN
        ALTER TABLE subject_prototypes ADD COLUMN IF NOT EXISTS prototype_vec vector(512);
    ELSE
        RAISE NOTICE '跳过 subject_prototypes.prototype_vec：pgvector 不可用';
    END IF;
END $$;

DO $$
BEGIN
    IF pgvector_available() THEN
        CREATE INDEX IF NOT EXISTS idx_subject_prototypes_vec
            ON subject_prototypes USING hnsw (prototype_vec vector_cosine_ops);
    END IF;
END $$;

-- --------------------------------------------------------------------------- #
-- 平台配置 / AI 供应商 / 自定义链接
