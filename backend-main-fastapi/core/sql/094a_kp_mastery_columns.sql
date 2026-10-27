-- --------------------------------------------------------------------------- #
-- 094a knowledge_points 兼容列与索引（**必须先于 080/081 视图**）
-- --------------------------------------------------------------------------- #
-- 拆分背景（2026-10-14）
-- ----------------------
-- 原 093 把「加列」和「建触发器/回填」混在一个文件里，导致它既不能放在
-- 视图之前（触发器函数体引用 v_knowledge_mastery，建视图前会失败），
-- 也不能放在视图之后（081 的 knowledge_points_legacy 用 ``SELECT kp.*``，
-- 加列会让视图列数偏移，重跑报
-- "cannot change name of view column ... to next_review"；
-- 080 的 v_knowledge_mastery 输出列 mastery 还会被自动绑定到新物理列，
-- 重跑报 "cannot change data type of view column mastery"）。
--
-- 因此按「谁需要谁先建」拆开：
--   本文件（094a）：只做 ADD COLUMN / CREATE INDEX —— 纯结构，不碰视图
--        → 排在 080 / 081 之前
--   093：建触发器 + 存量回填 —— 依赖 v_knowledge_mastery
--        → 排在 080 / 081 之后
--
-- mastery 列类型固定为 INTEGER：必须与 v_knowledge_mastery 的输出列一致，
-- 否则 PG 会把视图同名输出列绑定到本列，重跑时类型冲突。
-- --------------------------------------------------------------------------- #

-- 0. 解绑派生视图（仅当它的 mastery 列类型与目标不一致时才动）
--    存量库里v_knowledge_mastery.mastery 可能已绑定到旧的 SMALLINT 物理列。
--    只要两者类型不一致，后续 CREATE OR REPLACE VIEW 必然报
--      cannot change data type of view column "mastery"
--    因此先把视图连带依赖一起卸掉，080 会紧接着用新定义重建。
--    knowledge_points_legacy 依赖本视图，故用 CASCADE；081 也会重建它。
DO $$
DECLARE
    v_view_type TEXT;
    v_col_type  TEXT;
BEGIN
    SELECT data_type INTO v_view_type
      FROM information_schema.columns
     WHERE table_name = 'v_knowledge_mastery' AND column_name = 'mastery';

    SELECT data_type INTO v_col_type
      FROM information_schema.columns
     WHERE table_name = 'knowledge_points' AND column_name = 'mastery';

    IF v_view_type IS NOT NULL AND v_col_type IS NOT NULL
       AND v_view_type <> v_col_type THEN
        EXECUTE 'DROP VIEW IF EXISTS v_knowledge_mastery CASCADE';
        RAISE NOTICE 'v_knowledge_mastery 已解绑（% vs %），将由 080 重建',
                     v_view_type, v_col_type;
    END IF;
END $$;

-- 1. mastery 兼容列（INTEGER，0-100）
--    类型必须与 v_knowledge_mastery 的输出列一致，否则 PG 会把视图同名输出列
--    绑定到本列，重跑 schema 时报
--      cannot change data type of view column "mastery"
--    新建库走 ADD COLUMN（integer）；存量库里该列可能是旧的 SMALLINT，
--    ��里用 DO 块探测后对齐到 INTEGER。
ALTER TABLE knowledge_points
    ADD COLUMN IF NOT EXISTS mastery INTEGER NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'knowledge_points' AND column_name = 'mastery'
           AND data_type = 'smallint'
    ) THEN
        ALTER TABLE knowledge_points
            ALTER COLUMN mastery TYPE INTEGER USING mastery::integer;
        RAISE NOTICE 'knowledge_points.mastery: smallint -> integer 对齐完成';
    END IF;
END $$;

COMMENT ON COLUMN knowledge_points.mastery IS
    '掌握度兼容列（0-100）：镜像 v_knowledge_mastery 派生值，权威源仍是该视图；'
    '类型须与视图输出列一致（integer），否则视图列绑定会冲突';

-- 2. next_review 兼容列
--    权威源：review_schedules（SM-2 调度表）。同为只读镜像。
ALTER TABLE knowledge_points
    ADD COLUMN IF NOT EXISTS next_review TIMESTAMPTZ;

COMMENT ON COLUMN knowledge_points.next_review IS
    '下次复习时间兼容列：镜像 review_schedules.next_review_at，权威源是 review_schedules';

-- 3. 索引
CREATE INDEX IF NOT EXISTS idx_kp_mastery ON knowledge_points (mastery);
CREATE INDEX IF NOT EXISTS idx_kp_next_review_ts ON knowledge_points (next_review);