-- =============================================================================
-- P1-2：回填 kaoyan_scorelines.major_id —— 方案 A1（跳过唯一键冲突行）
--
-- 决策：只回填「唯一命中 kaoyan_majors」且「回填后不违反 uq_scoreline
-- (school_id, major_id, year, line_type)」的行。
--
-- 口径：
--   1. major_id IS NULL
--   2. major_name 非空
--   3. 该 school_id + major_name 在 kaoyan_majors 中唯一命中（count = 1）
--   4. 目标 major_id 对应的 (school_id, major_id, year, line_type)
--      尚不存在任何已回填/已有行（排除 1,254 行冲突）
--
-- 预期影响：约 21,499 行（22,753 唯一命中 - 1,254 冲突行）
-- 备份：kaoyan_scorelines_backup_20261028_143740.sql（已确认可用）
-- =============================================================================

BEGIN;

UPDATE kaoyan_scorelines ks
   SET major_id = matched.target_major_id
  FROM (
    SELECT ks.id AS scoreline_id,
           (SELECT m2.id
              FROM kaoyan_majors m2
             WHERE m2.school_id = ks.school_id
               AND m2.name = ks.major_name
             LIMIT 1) AS target_major_id,
           ks.school_id,
           ks.year,
           ks.line_type
      FROM kaoyan_scorelines ks
     WHERE ks.major_id IS NULL
       AND btrim(coalesce(ks.major_name, '')) <> ''
       AND (SELECT count(*)
              FROM kaoyan_majors m2
             WHERE m2.school_id = ks.school_id
               AND m2.name = ks.major_name) = 1
  ) matched
 WHERE matched.scoreline_id = ks.id
   AND matched.target_major_id IS NOT NULL
   AND NOT EXISTS (
        SELECT 1
          FROM kaoyan_scorelines e
         WHERE e.major_id = matched.target_major_id
           AND e.school_id = matched.school_id
           AND e.year = matched.year
           AND e.line_type IS NOT DISTINCT FROM matched.line_type
   );

-- 回填后：major_id 非空总数（回填前 17,919 + 回填 ~21,499 ≈ 39,418）
SELECT count(*) AS total_nonnull_major_id_after
  FROM kaoyan_scorelines
 WHERE major_id IS NOT NULL;

COMMIT;