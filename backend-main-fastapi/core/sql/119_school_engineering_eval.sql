-- =============================================================================
-- 119_school_engineering_eval.sql —— 08 工学学科评估与院校主档（ky_* 四表）
--
-- 来源（2026-11-21 并入 data-assets/工学院校评价库/）：
--   教育部第四轮学科评估官方公布结果（2017-12，仅公布前 70%）
--   + 第二轮双一流建设学科名单（2022-02）。
--   原始交付为 MySQL 8.0 方言 SQL + 三份 JSON；本分片是 PostgreSQL 权威
--   schema 转写（ADR-001：所有表必须在版本化迁移中可重建）。
--
-- 口径纪律（前端展示必须遵守，源 README 第三节）：
--   * 未上榜 ≠ 学科差（评估只公布前 70%），文案用「未上榜/未公布」。
--   * 0838 公安技术 / 0839 网络空间安全未列入第四轮公布（eval4_status=2）。
--   * 第五轮结果未官方公开，不得编造；未来新增 eval_round=5，不覆盖第四轮。
--   * eval_scope：normal 高校 / joint 两地联合评估 / institute 科研院所单列，
--     联合与单列不可与普通高校直接混排。
--   * heat_tag 为主观估算（heat_note 免责）；data_status=3 为待核验补充院校。
--
-- 本迁移只建表结构（幂等），不导入数据；数据由
-- scripts/import_school_eval_pg.py 从 data-assets JSON 填充。
-- =============================================================================

CREATE TABLE IF NOT EXISTS ky_discipline (
    code         VARCHAR(4)  PRIMARY KEY,
    name         VARCHAR(60) NOT NULL,
    degree_type  SMALLINT    NOT NULL,
    eval4_status SMALLINT    NOT NULL DEFAULT 1,
    note         VARCHAR(255),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  ky_discipline IS '08工学学科与专业类别字典（学硕0801-0839 + 专硕0851-0861）';
COMMENT ON COLUMN ky_discipline.code IS '学科/类别代码';
COMMENT ON COLUMN ky_discipline.name IS '学科/类别名称';
COMMENT ON COLUMN ky_discipline.degree_type IS '1学术学位 2专业学位';
COMMENT ON COLUMN ky_discipline.eval4_status IS '1已公布第四轮结果 2未列入第四轮公布（0838/0839）';
COMMENT ON COLUMN ky_discipline.note IS '口径备注';
COMMENT ON COLUMN ky_discipline.created_at IS '入库时间';

CREATE TABLE IF NOT EXISTS ky_school (
    id              BIGSERIAL   PRIMARY KEY,
    school_code     VARCHAR(10),
    name            VARCHAR(120) NOT NULL,
    province        VARCHAR(30)  NOT NULL,
    city            VARCHAR(30)  NOT NULL,
    school_type     SMALLINT     NOT NULL,
    unit_type       SMALLINT     NOT NULL,
    is_985          SMALLINT     NOT NULL DEFAULT 0,
    is_211          SMALLINT     NOT NULL DEFAULT 0,
    is_double_first SMALLINT     NOT NULL DEFAULT 0,
    is_self_marked  SMALLINT     NOT NULL DEFAULT 0,
    intro           TEXT,
    evaluation      TEXT,
    feature         TEXT,
    tier_txt        VARCHAR(120),
    heat_tag        VARCHAR(30),
    heat_note       VARCHAR(255),
    industry_tags   JSONB,
    strengths_json  JSONB,
    eval_cnt        INTEGER      NOT NULL DEFAULT 0,
    a_cnt           INTEGER      NOT NULL DEFAULT 0,
    bp_cnt          INTEGER      NOT NULL DEFAULT 0,
    data_status     SMALLINT     NOT NULL DEFAULT 2,
    verify_note     VARCHAR(255),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ky_school_name UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS idx_ky_school_code  ON ky_school (school_code);
CREATE INDEX IF NOT EXISTS idx_ky_school_prov  ON ky_school (province);
CREATE INDEX IF NOT EXISTS idx_ky_school_flags ON ky_school (is_985, is_211, is_double_first);

COMMENT ON TABLE  ky_school IS '08工学招生院校主档（329所：985/211/双一流/自划线标志+客观评价+优势学科）';
COMMENT ON COLUMN ky_school.id IS '自增主键';
COMMENT ON COLUMN ky_school.school_code IS '招生单位代码（补充院校待核验为NULL）';
COMMENT ON COLUMN ky_school.name IS '院校名称（唯一）';
COMMENT ON COLUMN ky_school.province IS '省级行政区';
COMMENT ON COLUMN ky_school.city IS '城市';
COMMENT ON COLUMN ky_school.school_type IS '1综合2理工3师范4农林5医药6财经7政法8语言9艺术10体育11民族12军事13科研院所';
COMMENT ON COLUMN ky_school.unit_type IS '1高校 2科研院所 3军校';
COMMENT ON COLUMN ky_school.is_985 IS '985工程标志';
COMMENT ON COLUMN ky_school.is_211 IS '211工程标志';
COMMENT ON COLUMN ky_school.is_double_first IS '双一流建设高校标志';
COMMENT ON COLUMN ky_school.is_self_marked IS '34所自划线标志';
COMMENT ON COLUMN ky_school.intro IS '院校介绍';
COMMENT ON COLUMN ky_school.evaluation IS '客观评价（基于官方评估与双一流数据）';
COMMENT ON COLUMN ky_school.feature IS '特色摘要';
COMMENT ON COLUMN ky_school.tier_txt IS '层次文本（985/211/双一流组合）';
COMMENT ON COLUMN ky_school.heat_tag IS '竞争热度（主观估算，免责见heat_note）';
COMMENT ON COLUMN ky_school.heat_note IS '热度免责口径';
COMMENT ON COLUMN ky_school.industry_tags IS '优势行业方向数组';
COMMENT ON COLUMN ky_school.strengths_json IS '优势学科[{code,name,grade,double_first}]（B+及以上，不足3取前3，并入双一流工学学科）';
COMMENT ON COLUMN ky_school.eval_cnt IS '第四轮工学上榜学科数';
COMMENT ON COLUMN ky_school.a_cnt IS 'A类学科数';
COMMENT ON COLUMN ky_school.bp_cnt IS 'B+及以上学科数';
COMMENT ON COLUMN ky_school.data_status IS '2已核验(官方数据) 3待核验(补充院校)';
COMMENT ON COLUMN ky_school.verify_note IS '核验备注';
COMMENT ON COLUMN ky_school.created_at IS '入库时间';

CREATE TABLE IF NOT EXISTS ky_school_discipline_eval (
    id              BIGSERIAL   PRIMARY KEY,
    school_name     VARCHAR(120) NOT NULL,
    school_code     VARCHAR(10)  NOT NULL,
    discipline_code VARCHAR(4)   NOT NULL,
    grade           VARCHAR(2)   NOT NULL,
    eval_round      SMALLINT     NOT NULL DEFAULT 4,
    eval_scope      VARCHAR(12)  NOT NULL DEFAULT 'normal',
    source          VARCHAR(120) NOT NULL DEFAULT '教育部第四轮学科评估官方公布',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ky_eval UNIQUE (school_name, discipline_code, eval_round)
);

CREATE INDEX IF NOT EXISTS idx_ky_eval_disc   ON ky_school_discipline_eval (discipline_code, grade);
CREATE INDEX IF NOT EXISTS idx_ky_eval_school ON ky_school_discipline_eval (school_name);

COMMENT ON TABLE  ky_school_discipline_eval IS '第四轮工学学科评估全量结果（2011条，A+~C-，含联合评估与科研院所单列）';
COMMENT ON COLUMN ky_school_discipline_eval.id IS '自增主键';
COMMENT ON COLUMN ky_school_discipline_eval.school_name IS '院校名称';
COMMENT ON COLUMN ky_school_discipline_eval.school_code IS '招生单位代码';
COMMENT ON COLUMN ky_school_discipline_eval.discipline_code IS '学科代码';
COMMENT ON COLUMN ky_school_discipline_eval.grade IS '评估等级 A+/A/A-/B+/B/B-/C+/C/C-';
COMMENT ON COLUMN ky_school_discipline_eval.eval_round IS '评估轮次（当前仅4；第五轮未官方公开）';
COMMENT ON COLUMN ky_school_discipline_eval.eval_scope IS 'normal高校/joint两地联合/institute科研院所单列';
COMMENT ON COLUMN ky_school_discipline_eval.source IS '数据来源';
COMMENT ON COLUMN ky_school_discipline_eval.created_at IS '入库时间';

CREATE TABLE IF NOT EXISTS ky_school_double_first (
    id              BIGSERIAL   PRIMARY KEY,
    school_name     VARCHAR(120) NOT NULL,
    discipline_code VARCHAR(4)   NOT NULL,
    discipline_name VARCHAR(60)  NOT NULL,
    round           SMALLINT     NOT NULL DEFAULT 2,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ky_syl UNIQUE (school_name, discipline_code, round)
);

CREATE INDEX IF NOT EXISTS idx_ky_syl_disc ON ky_school_double_first (discipline_code);

COMMENT ON TABLE  ky_school_double_first IS '第二轮双一流工学建设学科（179条，75所高校）';
COMMENT ON COLUMN ky_school_double_first.id IS '自增主键';
COMMENT ON COLUMN ky_school_double_first.school_name IS '院校名称';
COMMENT ON COLUMN ky_school_double_first.discipline_code IS '学科代码';
COMMENT ON COLUMN ky_school_double_first.discipline_name IS '学科名称';
COMMENT ON COLUMN ky_school_double_first.round IS '双一流轮次（当前2）';
COMMENT ON COLUMN ky_school_double_first.created_at IS '入库时间';

-- 列表页卡片视图（对齐源交付 v_school_engineering_card）
CREATE OR REPLACE VIEW v_school_engineering_card AS
SELECT s.id, s.name, s.province, s.city, s.school_type, s.is_985, s.is_211,
       s.is_double_first, s.is_self_marked, s.eval_cnt, s.a_cnt, s.bp_cnt,
       s.heat_tag, s.industry_tags, s.intro
  FROM ky_school s;

-- 按学科选校视图（对齐源交付 v_discipline_rank）
CREATE OR REPLACE VIEW v_discipline_rank AS
SELECT e.discipline_code, d.name AS discipline_name, e.grade, e.school_name,
       e.school_code, e.eval_scope
  FROM ky_school_discipline_eval e
  JOIN ky_discipline d ON d.code = e.discipline_code;
