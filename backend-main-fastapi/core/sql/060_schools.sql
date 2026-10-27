-- =============================================================================
-- 060 院校与研招数据域
-- 依赖：000 / 010
--
-- 说明：本域数据全部来自外部采集（研招网 / 院校官网），因此保留 data_source 与
--       source 两列做采集溯源；院校主数据用 ON DELETE CASCADE，采集日志用
--       ON DELETE SET NULL，避免误删历史采集记录。
-- =============================================================================

CREATE TABLE IF NOT EXISTS kaoyan_schools (
    id           BIGSERIAL    PRIMARY KEY,
    name         VARCHAR(200) NOT NULL,
    level        VARCHAR(50),
    province     VARCHAR(50),
    city         VARCHAR(50),
    logo_url     VARCHAR(500),
    intro        TEXT,
    tags         JSONB        NOT NULL DEFAULT '[]'::jsonb,
    official_url VARCHAR(500),
    data_source  VARCHAR(50),
    type         VARCHAR(30),
    region       VARCHAR(30),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_school_name UNIQUE (name)
);

COMMENT ON TABLE  kaoyan_schools IS '院校主数据表';
COMMENT ON COLUMN kaoyan_schools.name IS '院校名称，唯一';
COMMENT ON COLUMN kaoyan_schools.level IS '院校层次：985 / 211 / 双一流 / 普通';
COMMENT ON COLUMN kaoyan_schools.province IS '所在省份';
COMMENT ON COLUMN kaoyan_schools.city IS '所在城市';
COMMENT ON COLUMN kaoyan_schools.logo_url IS '校徽地址';
COMMENT ON COLUMN kaoyan_schools.intro IS '院校简介';
COMMENT ON COLUMN kaoyan_schools.tags IS '院校标签数组，如 ["985","自主划线"]';
COMMENT ON COLUMN kaoyan_schools.official_url IS '官网地址';
COMMENT ON COLUMN kaoyan_schools.data_source IS '数据采集来源';
COMMENT ON COLUMN kaoyan_schools.type IS '院校类型：综合 / 理工 / 师范 等';
COMMENT ON COLUMN kaoyan_schools.region IS '所属地区';
COMMENT ON COLUMN kaoyan_schools.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN kaoyan_schools.updated_at IS '最后更新时间';

CREATE INDEX IF NOT EXISTS idx_schools_region ON kaoyan_schools (province, city);

CREATE OR REPLACE TRIGGER trg_schools_updated BEFORE UPDATE ON kaoyan_schools
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS school_aliases (
    id          BIGSERIAL    PRIMARY KEY,
    alias       VARCHAR(100) NOT NULL,
    school_id   BIGINT       NOT NULL REFERENCES kaoyan_schools(id) ON DELETE CASCADE,
    school_name VARCHAR(200),
    alias_type  VARCHAR(20)  NOT NULL DEFAULT 'common',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_school_alias UNIQUE (alias)
);

COMMENT ON TABLE  school_aliases IS '院校别名表：用于公告匹配与模糊院校名解析';
COMMENT ON COLUMN school_aliases.alias IS '院校别名，唯一，如 华科 / HUST';
COMMENT ON COLUMN school_aliases.school_id IS '指向的院校 ID';
COMMENT ON COLUMN school_aliases.alias_type IS '别名类型：common 俗称 / abbrev 缩写 / former 曾用名';
COMMENT ON COLUMN school_aliases.created_at IS '创建时间（UTC，带时区）';

CREATE TABLE IF NOT EXISTS kaoyan_colleges (
    id         BIGSERIAL    PRIMARY KEY,
    school_id  BIGINT       NOT NULL REFERENCES kaoyan_schools(id) ON DELETE CASCADE,
    name       VARCHAR(200) NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_college UNIQUE (school_id, name)
);

COMMENT ON TABLE  kaoyan_colleges IS '院校下属学院表';
COMMENT ON COLUMN kaoyan_colleges.school_id IS '所属院校 ID，院校删除时级联删除';
COMMENT ON COLUMN kaoyan_colleges.name IS '学院名称';

CREATE TABLE IF NOT EXISTS kaoyan_majors (
    id                 BIGSERIAL    PRIMARY KEY,
    school_id          BIGINT       NOT NULL REFERENCES kaoyan_schools(id) ON DELETE CASCADE,
    college_id         BIGINT       REFERENCES kaoyan_colleges(id) ON DELETE SET NULL,
    code               VARCHAR(20),
    name               VARCHAR(200) NOT NULL,
    research_direction VARCHAR(300),
    subject_code       VARCHAR(20),
    exam_subjects      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    reference_books    JSONB        NOT NULL DEFAULT '[]'::jsonb,
    degree_type        degree_type  NOT NULL DEFAULT 'unknown',
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_major UNIQUE (school_id, college_id, code, name)
);

COMMENT ON TABLE  kaoyan_majors IS '招生专业表';
COMMENT ON COLUMN kaoyan_majors.school_id IS '所属院校 ID，院校删除时级联删除';
COMMENT ON COLUMN kaoyan_majors.college_id IS '所属学院 ID';
COMMENT ON COLUMN kaoyan_majors.code IS '专业代码';
COMMENT ON COLUMN kaoyan_majors.research_direction IS '研究方向';
COMMENT ON COLUMN kaoyan_majors.subject_code IS '所属学科代码';
COMMENT ON COLUMN kaoyan_majors.exam_subjects IS '初试科目数组（JSON）';
COMMENT ON COLUMN kaoyan_majors.reference_books IS '参考书目数组（JSON）';
COMMENT ON COLUMN kaoyan_majors.degree_type IS '学位类型：academic 学硕 / professional 专硕 / unknown';

CREATE INDEX IF NOT EXISTS idx_majors_school ON kaoyan_majors (school_id);
CREATE INDEX IF NOT EXISTS idx_majors_subject_code ON kaoyan_majors (subject_code);

CREATE TABLE IF NOT EXISTS kaoyan_admissions (
    id              BIGSERIAL PRIMARY KEY,
    school_id       BIGINT    NOT NULL REFERENCES kaoyan_schools(id) ON DELETE CASCADE,
    major_id        BIGINT    REFERENCES kaoyan_majors(id) ON DELETE CASCADE,
    year            INTEGER   NOT NULL,
    enroll_count    INTEGER,
    retest_count    INTEGER,
    admit_count     INTEGER,
    admit_avg_score REAL,
    major_avg_score REAL,
    retest_ratio    REAL,
    data_source     VARCHAR(50),
    source          VARCHAR(50),
    extra           JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_admission UNIQUE (school_id, major_id, year)
);

COMMENT ON TABLE  kaoyan_admissions IS '招生录取数据表：招生人数 / 录取均分 / 复录比';
COMMENT ON COLUMN kaoyan_admissions.school_id IS '院校 ID，级联删除';
COMMENT ON COLUMN kaoyan_admissions.major_id IS '专业 ID，级联删除';
COMMENT ON COLUMN kaoyan_admissions.year IS '招生年份';
COMMENT ON COLUMN kaoyan_admissions.enroll_count IS '计划招生人数';
COMMENT ON COLUMN kaoyan_admissions.retest_count IS '进入复试人数';
COMMENT ON COLUMN kaoyan_admissions.admit_count IS '实际录取人数';
COMMENT ON COLUMN kaoyan_admissions.admit_avg_score IS '录取平均分';
COMMENT ON COLUMN kaoyan_admissions.major_avg_score IS '专业课平均分';
COMMENT ON COLUMN kaoyan_admissions.retest_ratio IS '复录比';
COMMENT ON COLUMN kaoyan_admissions.data_source IS '采集来源';
COMMENT ON COLUMN kaoyan_admissions.source IS '采集批次标识';
COMMENT ON COLUMN kaoyan_admissions.extra IS '扩展数据 JSON：最高/最低/中位分、专业课分布、数学均分等';

CREATE INDEX IF NOT EXISTS idx_admissions_year ON kaoyan_admissions (year, school_id);

CREATE TABLE IF NOT EXISTS kaoyan_scorelines (
    id             BIGSERIAL PRIMARY KEY,
    school_id      BIGINT    NOT NULL REFERENCES kaoyan_schools(id) ON DELETE CASCADE,
    major_id       BIGINT    REFERENCES kaoyan_majors(id) ON DELETE CASCADE,
    year           INTEGER   NOT NULL,
    total_line     INTEGER,
    politics_line  INTEGER,
    english_line   INTEGER,
    math_line      INTEGER,
    major_line     INTEGER,
    national_line  INTEGER,
    retest_line    INTEGER,
    line_type      VARCHAR(20),
    source         VARCHAR(50),
    major_code     VARCHAR(20),
    major_name     VARCHAR(120),
    depart_name    VARCHAR(120),
    degree_type    VARCHAR(20),
    note           TEXT,
    special_remark TEXT,
    diff_total     INTEGER,
    source_id      VARCHAR(64),
    enabled        BOOLEAN   NOT NULL DEFAULT TRUE,
    deleted_at     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_scoreline UNIQUE (school_id, major_id, year, line_type)
);

COMMENT ON TABLE  kaoyan_scorelines IS '分数线表：校线 / 院线 / 国家线 / 复试线';
COMMENT ON COLUMN kaoyan_scorelines.line_type IS '线的类型：national 国家线 / school 校线 / college 院线 / retest 复试线';
COMMENT ON COLUMN kaoyan_scorelines.total_line IS '总分线';
COMMENT ON COLUMN kaoyan_scorelines.politics_line IS '政治单科线';
COMMENT ON COLUMN kaoyan_scorelines.english_line IS '英语单科线';
COMMENT ON COLUMN kaoyan_scorelines.math_line IS '数学单科线';
COMMENT ON COLUMN kaoyan_scorelines.major_line IS '专业课单科线';
COMMENT ON COLUMN kaoyan_scorelines.national_line IS '当年国家线';
COMMENT ON COLUMN kaoyan_scorelines.retest_line IS '复试线';
COMMENT ON COLUMN kaoyan_scorelines.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN kaoyan_scorelines.major_code IS '专业代码（kaoyan.cn 逐专业分数线口径）';
COMMENT ON COLUMN kaoyan_scorelines.diff_total IS '院线总分 - 国家线（掌上考研口径）';
COMMENT ON COLUMN kaoyan_scorelines.source_id IS '数据源行 id，跨年唯一';

CREATE INDEX IF NOT EXISTS idx_scorelines_year ON kaoyan_scorelines (year, school_id);
CREATE INDEX IF NOT EXISTS idx_scorelines_source_id ON kaoyan_scorelines (source_id);

-- --------------------------------------------------------------------------- #
-- 研招通知：采集 → 分类 → 提醒
