-- 131_quiz_broken_option_quarantine.sql
-- 题库治理：隔离「选项文本重复」的客观题。
-- 依据：single/multiple 题的选项文本去重后数量少于选项总数，说明 OCR/解析丢字
--（例：A/B/D 都成了「当时条件收敛」，或「l、111」把 I、IV 认错），学生会看到
-- 多个一模一样的选项、无法作答，属于确定性错误。
-- 处理：移出练习池（is_available=false）+ 打 needs_review，并把原因写进 validation_errors，
--       保留题目本身可检索、可人工修复后重新上架（不物理删除、不编造内容）。
-- 幂等：仅处理当前仍在练习池中的行，重复执行无副作用。

UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = coalesce(validation_errors, '[]'::jsonb)
      || '[{"code":"duplicate_option_text","detail":"选项文本重复，疑 OCR 丢字，已移出练习池待人工修复"}]'::jsonb,
    validated_at = now(),
    updated_at = now()
WHERE is_available = true
  AND question_type IN ('single', 'multiple')
  AND options IS NOT NULL
  AND jsonb_typeof(options) = 'array'
  AND jsonb_array_length(options) > 1
  AND (SELECT count(DISTINCT o->>'text') FROM jsonb_array_elements(options) o)
      < jsonb_array_length(options);
