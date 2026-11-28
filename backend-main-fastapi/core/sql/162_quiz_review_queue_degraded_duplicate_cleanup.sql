-- 162_quiz_review_queue_degraded_duplicate_cleanup.sql
-- 题库质量（2026-11-24）：复核队列 212 条只读分组审计后的「无损去重」。
--
-- 背景（云端只读统计，见 backfill_local/cloud_probe_review_queue*.py）：
--   队列 212 条全部 is_available=false 且 needs_review=true，校验码分布：
--     stem_label_only 114（英语写作「写作（第N题）」占位题干，原文写作要求已丢）
--     duplicate_option_text 53、stem_truncated 19、figure_missing_unanswerable 14、
--     single_options_less_than_four 11、formula_missing 4、options_ocr_merged 3、
--     merged_questions 1、answer_analysis_conflict 1、options_incomplete_reading 1（有重叠）。
--   多数是公式/配图在 OCR 中丢失，脱离原始教材无法还原 —— 不猜、不编造，继续留在队列。
--
-- 本轮只处理可证实的「降级副本」：队列里某些题与练习池中一道仍在架的题
--   题干归一化后完全一致（去空白、去 [xxx研] 来源标签）、学科/题型相同、
--   选项数相同、答案相同，且队列副本的每个选项都等于练习池对应选项
--   「剥掉公式/图片后」的前缀（即公式被 OCR 丢弃），队列副本因选项文本重复被隔离。
--   这类记录是同一道题的残缺拷贝，保留练习池原题即可，副本下架并移出复核队列。
--   逐条证据（queue_id / keep_pool_id / 题干 / 来源文件）：
--     backfill_local/out/quiz_review_162_evidence.csv
--
-- 未采纳（写清原因，避免下轮重复调研）：
--   #461 与池 #352 同题，但池副本题干同样丢失「球面方程」，两者均不可作答，
--        等待补公式，本轮不做去重（去重会让「保留项」也答不了）；
--   #272/#279 与池 #438/#440 同题干，队列副本选项反而是带公式的较优版本，
--        但两者都缺配图不可作答，保留现状待补图；
--   #392/#400/#455 仅 2 个选项（池副本 4 个），属导入截断，非重复，留在队列。
--
-- 口径（与 134/154 一致，幂等）：
--   is_available 维持 false；is_junk=true（软隔离，仍可检索/恢复）；
--   needs_review=false（复核动作完成）；validation_status='warn'；
--   validation_errors 追加 duplicate_content 原因，写明保留的练习池题目 ID。
-- 不物理删除任何行；重复执行时 needs_review=true 守卫使本轮只生效一次。

UPDATE quiz_questions AS q
SET is_junk = true,
    needs_review = false,
    validation_status = 'warn',
    validation_errors = coalesce(q.validation_errors, '[]'::jsonb)
      || jsonb_build_array(jsonb_build_object(
           'code', 'duplicate_content',
           'detail', '练习池 #' || v.keep_id
                     || ' 的公式丢失残缺副本（题干/答案一致、选项为原题剥除公式后的前缀），保留原题，本条移出复核队列')),
    validated_at = now(),
    updated_at = now()
FROM (VALUES
    (468, 362),   -- 设有两个数列{an}，{bn}，若则（ ）           → 池 #362 选项保留完整 LaTeX
    (475, 373),   -- 级数的敛散性（ ）                        → 池 #373
    (476, 381),   -- 设、、均为大于1的常数，则级数（ ）        → 池 #381
    (398, 155),   -- 下列命题正确的是（ ）                    → 池 #155（选项含公式图片）
    (428, 205),   -- 设f(x)在[0,1]上连续…                     → 池 #205
    (467, 361),   -- 若级数收敛，则级数（ ）                  → 池 #361
    (472, 368),   -- 若级数收敛，发散，则（ ）                → 池 #368
    (397, 154),   -- 设，则在点可导的充要条件为（ ）          → 池 #154
    (456, 343),   -- 设f(x,y)在D：上连续，则（ ）             → 池 #343
    (409, 170),   -- 设f(x)处处可导，则下面命题正确的是（ ）  → 池 #170
    (444, 306),   -- 如果函数f(x,y)在点(0,0)处连续…           → 池 #306
    (464, 355),   -- 设、、均为大于1的常数，则级数（ ）        → 池 #355
    (473, 371)    -- 如果级数和都发散，则（ ）                → 池 #371
) AS v(id, keep_id)
WHERE q.id = v.id
  AND q.is_available IS FALSE
  AND q.needs_review IS TRUE
  AND (q.is_junk IS FALSE OR q.is_junk IS NULL)
  AND q.subject = '数学'
  AND q.question_type = 'single'
  AND EXISTS (
      SELECT 1 FROM quiz_questions p
      WHERE p.id = v.keep_id
        AND p.is_available IS TRUE
        AND p.answer = q.answer
  );

-- #21135：与 #19411 题干/选项/答案逐字相同（仅来源不同）；154 已下架并留痕进队列，
-- 本轮确认练习池 #19411 健在，副本正式去重，移出复核队列。
UPDATE quiz_questions
SET is_junk = true,
    needs_review = false,
    validation_status = 'warn',
    validation_errors = coalesce(validation_errors, '[]'::jsonb)
      || jsonb_build_array(jsonb_build_object(
           'code', 'duplicate_content',
           'detail', '与练习池 #19411 题干/选项/答案逐字相同，154 已下架留痕，本轮确认去重')),
    validated_at = now(),
    updated_at = now()
WHERE id = 21135
  AND is_available IS FALSE
  AND needs_review IS TRUE
  AND btrim(content) = '对于二叉排序树，下面的说法中，（）是正确的。'
  AND btrim(answer) = 'C'
  AND EXISTS (
      SELECT 1 FROM quiz_questions p
      WHERE p.id = 19411 AND p.is_available IS TRUE
  );
