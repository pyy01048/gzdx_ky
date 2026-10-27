-- =============================================================================
-- 103 历史调度数据回填：业务表 → review_schedules
--
-- 依赖：050（review_schedules）、102（FSRS 四列）
-- 目的：单词 / 卡片 / 错题 / 知识点此前各自维护 next_review/interval，
--       统一调度表的历史是空的。这里把**已复习过**的记录回填成 SM-2 快照，
--       后续第一次 FSRS 复习会在这条记录上继续迭代，而不是从零开始。
--
-- 口径：
--   * 仅回填"学过"的数据（review_count/reps > 0 或 last_review 非空）；
--     新内容（not_mastered / 从未复习）不预先占用调度行。
--   * algorithm='sm2'：历史状态来自 SM-2，FSRS 三要素留空。
--   * item_type 与 093 / 后端保持一致：
--       word / flashcard / error_record / knowledge_point
--   * 幂等：ON CONFLICT (item_type, item_id) DO NOTHING，可重复执行。
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- 1. 单词
-- --------------------------------------------------------------------------- #
INSERT INTO review_schedules (
    item_type, item_id, algorithm, ease_factor, interval_days,
    repetitions, lapses, last_reviewed_at, next_review_at
)
SELECT
    'word', w.id, 'sm2',
    GREATEST(1.3, LEAST(3.5, COALESCE(w.ease_factor, 2.5))),
    GREATEST(0, COALESCE(w.interval_days, 0)),
    GREATEST(0, COALESCE(w.reps, 0)),
    GREATEST(0, COALESCE(w.lapses, 0)),
    w.last_review::timestamp,
    w.due_date::timestamp
FROM words w
WHERE COALESCE(w.reps, 0) > 0 OR w.last_review IS NOT NULL
ON CONFLICT (item_type, item_id) DO NOTHING;

-- --------------------------------------------------------------------------- #
-- 2. 背诵卡片
-- --------------------------------------------------------------------------- #
INSERT INTO review_schedules (
    item_type, item_id, algorithm, ease_factor, interval_days,
    repetitions, lapses, last_reviewed_at, next_review_at
)
SELECT
    'flashcard', f.id, 'sm2',
    GREATEST(1.3, LEAST(3.5, COALESCE(f.ease_factor, 2.5))),
    GREATEST(0, COALESCE(f.interval_days, 0)),
    GREATEST(0, COALESCE(f.review_count, 0)),
    0,
    NULL,
    f.next_review
FROM flashcards f
WHERE COALESCE(f.review_count, 0) > 0
ON CONFLICT (item_type, item_id) DO NOTHING;

-- --------------------------------------------------------------------------- #
-- 3. 错题
-- --------------------------------------------------------------------------- #
INSERT INTO review_schedules (
    item_type, item_id, algorithm, ease_factor, interval_days,
    repetitions, lapses, last_reviewed_at, next_review_at
)
SELECT
    'error_record', e.id, 'sm2',
    GREATEST(1.3, LEAST(3.5, COALESCE(e.ease_factor, 2.5))),
    GREATEST(0, COALESCE(e.interval_days, 0)),
    GREATEST(0, COALESCE(e.review_count, 0)),
    GREATEST(0, COALESCE(e.lapses, 0)),
    e.last_review,
    e.next_review
FROM error_records e
WHERE COALESCE(e.review_count, 0) > 0 OR e.last_review IS NOT NULL
ON CONFLICT (item_type, item_id) DO NOTHING;

-- --------------------------------------------------------------------------- #
-- 4. 知识点
-- --------------------------------------------------------------------------- #
INSERT INTO review_schedules (
    item_type, item_id, algorithm, ease_factor, interval_days,
    repetitions, lapses, last_reviewed_at, next_review_at
)
SELECT
    'knowledge_point', kp.id, 'sm2',
    GREATEST(1.3, LEAST(3.5, COALESCE(kp.ease_factor, 2.5))),
    GREATEST(0, COALESCE(kp.interval_days, 0)),
    GREATEST(0, COALESCE(kp.review_count, 0)),
    GREATEST(0, COALESCE(kp.lapses, 0)),
    kp.last_review,
    kp.next_review
FROM knowledge_points kp
WHERE COALESCE(kp.review_count, 0) > 0 OR kp.last_review IS NOT NULL
ON CONFLICT (item_type, item_id) DO NOTHING;

-- --------------------------------------------------------------------------- #
-- 5. 清理/归一化历史错键
--    早期 /api/review/submit 使用 knowledge / error 作为 item_type，
--    与全库口径（knowledge_point / error_record）不一致。
-- --------------------------------------------------------------------------- #
UPDATE review_schedules rs
   SET item_type = 'knowledge_point'
 WHERE rs.item_type = 'knowledge'
   AND NOT EXISTS (
       SELECT 1 FROM review_schedules o
        WHERE o.item_type = 'knowledge_point' AND o.item_id = rs.item_id
   );

DELETE FROM review_schedules rs
 WHERE rs.item_type = 'knowledge'
   AND EXISTS (
       SELECT 1 FROM review_schedules o
        WHERE o.item_type = 'knowledge_point' AND o.item_id = rs.item_id
   );

UPDATE review_schedules rs
   SET item_type = 'error_record'
 WHERE rs.item_type = 'error'
   AND NOT EXISTS (
       SELECT 1 FROM review_schedules o
        WHERE o.item_type = 'error_record' AND o.item_id = rs.item_id
   );

DELETE FROM review_schedules rs
 WHERE rs.item_type = 'error'
   AND EXISTS (
       SELECT 1 FROM review_schedules o
        WHERE o.item_type = 'error_record' AND o.item_id = rs.item_id
   );
