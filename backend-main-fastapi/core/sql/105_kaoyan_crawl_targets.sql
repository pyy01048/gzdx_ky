-- =============================================================================
-- 105 kaoyan_crawl_targets：院校采集开关（models.KaoyanCrawlTarget）。幂等，可重复执行。
--
-- 此前该表只存在于 ORM，由 create_all() 按 SQLAlchemy ``DateTime`` 建成
-- ``timestamp without time zone``，违反全库「时间列一律 TIMESTAMPTZ」口径
-- （tests/test_timeutil_local_day.py::test_pg_time_columns_are_all_timestamptz；
-- naive 列会让 day_bucket_expr 依赖会话时区）。
--
-- 1) 新库：按权威口径直接建表；
-- 2) 旧库（已被 create_all 建成 naive）：原地改为 TIMESTAMPTZ。
--    应用写入的是 naive UTC（utils/timeutil.utcnow），故按 'UTC' 解释旧值。
-- =============================================================================

CREATE TABLE IF NOT EXISTS kaoyan_crawl_targets (
    id              SERIAL PRIMARY KEY,
    school_id       INTEGER      NOT NULL UNIQUE REFERENCES kaoyan_schools(id),
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    priority        INTEGER      DEFAULT 0,
    note            VARCHAR(200),
    last_crawled_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_kaoyan_crawl_targets_id ON kaoyan_crawl_targets (id);
CREATE INDEX IF NOT EXISTS ix_kaoyan_crawl_targets_school_id ON kaoyan_crawl_targets (school_id);

COMMENT ON TABLE  kaoyan_crawl_targets IS '院校采集开关：只记录被显式修改过的院校（无记录=跟随默认参与采集）';
COMMENT ON COLUMN kaoyan_crawl_targets.enabled IS '是否参与采集';
COMMENT ON COLUMN kaoyan_crawl_targets.priority IS '采集优先级，数字越大越优先';
COMMENT ON COLUMN kaoyan_crawl_targets.note IS '备注';
COMMENT ON COLUMN kaoyan_crawl_targets.last_crawled_at IS '最近一次采集时间';

DO $$
DECLARE
    col text;
BEGIN
    FOREACH col IN ARRAY ARRAY['last_crawled_at', 'created_at', 'updated_at'] LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'kaoyan_crawl_targets'
               AND column_name = col
               AND data_type = 'timestamp without time zone'
        ) THEN
            EXECUTE format(
                'ALTER TABLE kaoyan_crawl_targets ALTER COLUMN %I TYPE TIMESTAMPTZ USING %I AT TIME ZONE ''UTC''',
                col, col
            );
        END IF;
    END LOOP;
END $$;
