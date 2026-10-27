-- =============================================================================
-- 112 考研国家线（A/B 区）
-- 数据源：ai-for-unidata/national-lines.csv（2025/2026 全学科门类）
-- 用途：掌上考研式「国家线」查询模块（A/B 区 + 政治/数学单科线）
-- =============================================================================

CREATE TABLE IF NOT EXISTS kaoyan_national_lines (
    id            BIGSERIAL    PRIMARY KEY,
    year          INTEGER      NOT NULL,
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
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_national_line UNIQUE (year, discipline, subjects)
);

COMMENT ON TABLE  kaoyan_national_lines IS '考研国家线（A/B 区，按学科门类/年份）';
COMMENT ON COLUMN kaoyan_national_lines.year IS '年份';
COMMENT ON COLUMN kaoyan_national_lines.discipline IS '学科门类（哲学/经济学/工学/医学等）';
COMMENT ON COLUMN kaoyan_national_lines.subjects IS '适用专业（可空）';
COMMENT ON COLUMN kaoyan_national_lines.total_a IS 'A 区总分线';
COMMENT ON COLUMN kaoyan_national_lines.politics_a IS 'A 区政治/单科线（100 分科目）';
COMMENT ON COLUMN kaoyan_national_lines.math_a IS 'A 区业务课一/数学线（>100 分科目）';
COMMENT ON COLUMN kaoyan_national_lines.total_b IS 'B 区总分线';
COMMENT ON COLUMN kaoyan_national_lines.politics_b IS 'B 区政治/单科线（100 分科目）';
COMMENT ON COLUMN kaoyan_national_lines.math_b IS 'B 区业务课一/数学线（>100 分科目）';
COMMENT ON COLUMN kaoyan_national_lines.source IS '数据来源标注';