-- 150_quiz_options_ocr_fix_quarantine.sql
-- 题库质量（2026-11-24）：可见题库 warn 队列复核。
-- 现状：可见 warn 共 211 条，全部为 single_options_less_than_four；
-- 其中 13 条为单选仅 2 选项。逐条核对后：
--   A. #20462 选项被 OCR 合并成 2 项，可无损拆回 4 项，答案 A 仍有效 → 修复并转 pass；
--   B. #392/#400/#455 选项文本仍夹带「C．/D．」标签，选项内容缺失 → 无法作答，下架；
--   C. #19189 选项仅 2 项，且解析结论（最长滑动 5）与答案（A=3）矛盾 → 下架；
--   D. #32932 题干混入「答案∶21A 22C23D 24D 25B」与整段阅读原文，选项仅 2 项 → 下架；
--   E. #32933 阅读理解仅 2 个选项（同组其余题均 4 个）→ 下架。
-- 口径：只下架可证实无法作答的 6 条；其余 6 条双选项题（#78/#85/#99/#420/#20930/#33587）
-- 选项文本完整、答案在选项内，属真实二选一题，保留在练习池。
-- 守卫：仅处理仍上架且形态匹配的记录；重复执行不会二次生效。

-- A. 无损修复 #20462：把合并进 A 选项的 B/C 拆回独立选项，补回 4 选项
UPDATE quiz_questions
SET options = '[{"key": "A", "text": "01-00-5E-57-91-E6"},
                {"key": "B", "text": "01-00-5E-D7-91-E6"},
                {"key": "C", "text": "01-00-5E-5B-91-E6"},
                {"key": "D", "text": "01-00-5E-55-91-E6"}]'::jsonb,
    validation_status = 'pass',
    validation_errors = '[]'::jsonb,
    needs_review = false,
    validated_at = now(),
    updated_at = now()
WHERE id = 20462
  AND is_available IS TRUE
  AND question_type = 'single'
  AND jsonb_array_length(options) = 2
  AND options->0->>'text' LIKE '%C.01-00-5E-5B-91-E6%'
  AND options->1->>'text' = '01-00-5E-55-91-E6'
  AND upper(btrim(answer)) = 'A';

-- B. 选项 OCR 合并：C/D 标签与内容仍夹在 B 选项内，无法还原
UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = validation_errors || jsonb_build_array(jsonb_build_object(
        'code', 'options_ocr_merged',
        'detail', '选项文本被 OCR 合并（如「2 C．」「1 C． D．」），原选项内容缺失，无法作答，已移出练习池待补原题')),
    validated_at = now(),
    updated_at = now()
WHERE is_available IS TRUE
  AND id IN (392, 400, 455);

-- C. 答案与解析结论矛盾，且选项仅 2 项
UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = validation_errors || jsonb_build_array(jsonb_build_object(
        'code', 'answer_analysis_conflict',
        'detail', '选项仅 2 项，解析结论为「最长滑动距离 5」，与答案 A=3 矛盾，无法判定正确项，已移出练习池待核')),
    validated_at = now(),
    updated_at = now()
WHERE is_available IS TRUE
  AND id = 19189;

-- D. 题干混入答案键与整段阅读原文
UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = validation_errors || jsonb_build_array(jsonb_build_object(
        'code', 'stem_answer_key_leak',
        'detail', '题干混入「答案∶21A 22C23D 24D 25B」及整段阅读原文，选项仅 2 项，已移出练习池待重切')),
    validated_at = now(),
    updated_at = now()
WHERE is_available IS TRUE
  AND id = 32932;

-- E. 阅读理解选项数不足
UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = validation_errors || jsonb_build_array(jsonb_build_object(
        'code', 'options_incomplete_reading',
        'detail', '阅读理解题仅 2 个选项（同组其余题均 4 个），C/D 缺失，已移出练习池待补')),
    validated_at = now(),
    updated_at = now()
WHERE is_available IS TRUE
  AND id = 32933;
