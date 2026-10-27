-- 112_ocr_crawl_timestamptz.sql
-- OCR / 采集管线的 8 个时间列统一为 timestamptz（2026-10-21 体检 D9）。
--
-- 背景：day_bucket_expr 的 PG 分支以 timestamptz 为前提（先拍成 naive UTC 再偏移）。
-- timestamp without time zone 会让按日分桶依赖会话时区，某些时区下静默错一天。
-- 111 建表时用了 TIMESTAMP；这里幂等 ALTER 到 TIMESTAMPTZ。
--
-- 幂等：仅当列仍是 timestamp without time zone 时执行；重复运行不报错。
-- 数据：执行时 6 张表均为 0 行（2026-10-21 实测）；有数据时按 UTC 口径换算。

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            ('document_pages',   'created_at'),
            ('document_blocks',  'created_at'),
            ('question_images',  'created_at'),
            ('crawl_jobs',       'next_run_at'),
            ('crawl_jobs',       'created_at'),
            ('crawl_jobs',       'updated_at'),
            ('crawl_pages',      'fetched_at'),
            ('crawl_dead_letters', 'created_at')
        ) AS t(tbl, col)
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = r.tbl
              AND column_name = r.col
              AND data_type = 'timestamp without time zone'
        ) THEN
            EXECUTE format(
                'ALTER TABLE %I ALTER COLUMN %I TYPE timestamptz USING %I AT TIME ZONE ''UTC''',
                r.tbl, r.col, r.col
            );
        END IF;
    END LOOP;
END $$;
