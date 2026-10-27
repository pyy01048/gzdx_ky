-- =============================================================================
-- 114_kaoyan_national_lines.sql —— 国家线表收编为规范 schema
--
-- 背景（2026-10-23 规整归一）：
--   kaoyan_national_lines 此前只由一次性脚本
--   scripts/import_school_data_aiunidata_pg.py 临时 CREATE TABLE 建立，
--   不在 core/sql 权威 schema 中。按 ADR-001，所有表都必须在版本化迁移中
--   可重建，否则测试库/新环境无法通过 conftest 的权威 schema 还原，且
--   GET /api/kaoyan/national-lines 在全新数据库上直接 500。
--
-- 本迁移只建表结构（幂等），不导入数据；数据由导入脚本填充。
-- =============================================================================

CREATE TABLE IF NOT EXISTS kaoyan_national_lines (
    id            BIGSERIAL   PRIMARY KEY,
    year          INTEGER     NOT NULL,
    discipline    VARCHAR(100) NOT NULL,
    subjects      VARCHAR(500),
    total_a       INTEGER,
    politics_a    INTEGER,
    math_a        INTEGER,
    total_b       INTEGER,
    politics_b    INTEGER,
    math_b        INTEGER,
    note          TEXT,
    source        VARCHAR(100),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_national_line UNIQUE (year, discipline, subjects)
);

COMMENT ON TABLE  kaoyan_national_lines IS '考研国家线 A/B 区（2022-2026 全学科门类）';
COMMENT ON COLUMN kaoyan_national_lines.year IS '年份';
COMMENT ON COLUMN kaoyan_national_lines.discipline IS '学科门类';
COMMENT ON COLUMN kaoyan_national_lines.subjects IS '涉及科目/方向';
COMMENT ON COLUMN kaoyan_national_lines.total_a IS 'A 区总分线';
COMMENT ON COLUMN kaoyan_national_lines.politics_a IS 'A 区政治/单科线';
COMMENT ON COLUMN kaoyan_national_lines.math_a IS 'A 区数学/业务课线';
COMMENT ON COLUMN kaoyan_national_lines.total_b IS 'B 区总分线';
COMMENT ON COLUMN kaoyan_national_lines.politics_b IS 'B 区政治/单科线';
COMMENT ON COLUMN kaoyan_national_lines.math_b IS 'B 区数学/业务课线';
COMMENT ON COLUMN kaoyan_national_lines.note IS '备注';
COMMENT ON COLUMN kaoyan_national_lines.source IS '数据来源';
COMMENT ON COLUMN kaoyan_national_lines.created_at IS '入库时间（UTC）';