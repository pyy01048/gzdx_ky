-- =============================================================================
-- 080 派生视图 / 校验门 / 兼容层
-- 依赖：000 - 070（必须最后执行）
--
-- 三个作用：
--   1. 派生视图：掌握度不再落库，改为按作答流水实时聚合（解决问题 5）；
--   2. 校验门：写库时自动体检，把脏数据挡在库层（解决问题 2）；
--   3. 兼容视图：为 37 个路由 / 80 个服务提供旧表名与旧列名的过渡入口，
--      使迁移可以增量推进，而不是一次性大爆炸切换。
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- 派生视图一：知识点掌握度
--   计算口径：按时间衰减加权正确率。
--     w = exp(-Δt / (30 天))，30 天前的作答权重约为 0.37，越近越重要。
--     掌握度 = round(100 * Σ(正确 × w) / Σw)
--   数据源：answer_records（经 question_knowledge_links 落到知识点）+ review_records。
--   attempts=0（从未练过）时返回 0，而不是历史库里那种恒 0 的假数据。
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE VIEW v_knowledge_mastery AS
WITH answered AS (
    SELECT qkl.knowledge_point_id                                   AS kp_id,
           ar.created_at                                            AS at,
           CASE WHEN ar.is_correct THEN 1 ELSE 0 END               AS ok,
           qkl.weight                                               AS kweight
      FROM answer_records ar
      JOIN question_knowledge_links qkl ON qkl.question_id = ar.question_id
     WHERE ar.is_correct IS NOT NULL
       AND ar.question_id IS NOT NULL
),
reviewed AS (
    SELECT rr.item_id                                               AS kp_id,
           rr.created_at                                            AS at,
           CASE WHEN rr.result IN ('good','easy') THEN 1
                ELSE 0 END                                          AS ok,
           1.0::real                                                AS kweight
      FROM review_records rr
     -- 口径修正（2026-10-16）：全站写入方（review_scheduler / 前端复习接口）
     -- 用的都是 item_type='knowledge'（实测 review_records 只有
     -- 'knowledge' / 'error' 两种值），而这里此前写死 'knowledge_point'
     -- —— 结果**任何复习记录都不贡献掌握度**，只有 answer_records 生效。
     -- 两种值都收（兼容历史 + 未来复数写法），口径与 LEARNED_KP_SQL 对齐。
     WHERE rr.item_type IN ('knowledge', 'knowledge_point')
       AND rr.result IS NOT NULL
),
merged AS (
    SELECT kp_id, at, ok, kweight,
           exp(-EXTRACT(EPOCH FROM (now() - at)) / (30.0 * 86400.0)) AS decay
      FROM answered
    UNION ALL
    SELECT kp_id, at, ok, kweight,
           exp(-EXTRACT(EPOCH FROM (now() - at)) / (30.0 * 86400.0))
      FROM reviewed
),
agg AS (
    SELECT kp_id,
           COUNT(*)::bigint                                          AS attempts,
           SUM(ok)::bigint                                           AS correct,
           COALESCE(SUM(ok::numeric * decay * kweight), 0)           AS weighted_correct,
           COALESCE(SUM(decay * kweight), 0)                         AS weighted_total,
           MAX(at)                                                   AS last_activity_at
      FROM merged
     GROUP BY kp_id
)
SELECT kp.id                                          AS knowledge_point_id,
       kp.subject_id                                  AS subject_id,
       COALESCE(a.attempts, 0)                        AS attempts,
       COALESCE(a.correct, 0)                         AS correct,
       CASE WHEN COALESCE(a.weighted_total, 0) = 0 THEN 0
            ELSE ROUND((100.0 * a.weighted_correct / a.weighted_total))::int
       END                                            AS mastery,
       CASE
           WHEN COALESCE(a.attempts, 0) = 0 THEN 'not_mastered'
           WHEN COALESCE(a.weighted_total, 0) = 0 THEN 'not_mastered'
           WHEN (100.0 * a.weighted_correct / a.weighted_total) >= 85
                AND COALESCE(a.attempts, 0) >= 5 THEN 'mastered'
           WHEN (100.0 * a.weighted_correct / a.weighted_total) >= 60 THEN 'reviewing'
           ELSE 'learning'
       END::mastery_level                             AS mastery_level,
       a.last_activity_at                             AS last_activity_at
  FROM knowledge_points kp
  LEFT JOIN agg a ON a.kp_id = kp.id;

COMMENT ON VIEW v_knowledge_mastery IS
    '知识点掌握度派生视图：30 天指数衰减加权正确率，取代 knowledge_points.mastery 硬编码列';

-- --------------------------------------------------------------------------- #
-- 派生视图二：向量覆盖率（对应缺陷 D3，61041 分块中 42619 无向量）
--   迁移完成后用本视图验收：SELECT * FROM v_chunk_vector_coverage;
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE VIEW v_chunk_vector_coverage AS
SELECT kc.subject_id                                        AS subject_id,
       COUNT(*)                                             AS total_chunks,
       COUNT(cv.chunk_id)                                   AS vectorized_chunks,
       COUNT(*) - COUNT(cv.chunk_id)                        AS missing_chunks,
       ROUND(100.0 * COUNT(cv.chunk_id) / NULLIF(COUNT(*), 0), 2) AS coverage_pct
  FROM knowledge_chunks kc
  LEFT JOIN chunk_vectors cv ON cv.chunk_id = kc.id
 GROUP BY kc.subject_id;

COMMENT ON VIEW v_chunk_vector_coverage IS
    '分块向量覆盖率监控视图：按科目统计有向量/无向量分块数，用于验收缺陷 D3 补齐进度';

-- --------------------------------------------------------------------------- #
-- 派生视图三：题库健康度（对应缺陷 D5 与问题 2/4）
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE VIEW v_question_health AS
SELECT subject_id,
       COUNT(*)                                                   AS total,
       COUNT(*) FILTER (WHERE options IS NULL)                    AS no_options,
       COUNT(*) FILTER (WHERE answer IS NULL OR btrim(answer) = '') AS no_answer,
       COUNT(*) FILTER (WHERE analysis IS NULL OR btrim(analysis) = '') AS no_analysis,
       COUNT(*) FILTER (WHERE is_junk)                            AS junk,
       COUNT(*) FILTER (WHERE figure_missing <> 0)                AS figure_missing,
       COUNT(*) FILTER (WHERE validation_status = 'fail')         AS failed,
       COUNT(*) FILTER (WHERE validation_status = 'warn')         AS warned
  FROM quiz_questions
 GROUP BY subject_id;

COMMENT ON VIEW v_question_health IS
    '题库健康度视图：按科目统计缺选项/缺答案/缺解析/碎片题/缺图/校验不通过的数量';

-- --------------------------------------------------------------------------- #
-- 校验门：写入 quiz_questions 时自动体检
--   硬约束（选项结构、选项数、题干洁净度）已由 CHECK 直接拒绝；
--   本触发器负责软检查，把问题写进 validation_errors 并置为 warn，
--   让脏数据可见、可统计、可批量修，而不是静默混进题库。
