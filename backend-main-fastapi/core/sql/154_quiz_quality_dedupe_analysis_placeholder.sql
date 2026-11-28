-- 154_quiz_quality_dedupe_analysis_placeholder.sql
-- 题库质量（2026-11-24）：练习池只读审计后的两处可证实修复。
-- 1) 完全重复题：#19411 与 #21135 题干、选项、答案逐字相同，仅来源不同
--    （前者解析无前导噪声，后者解析以「:」开头）。保留 #19411，下架 #21135，
--    不物理删除，进入复核队列留痕。
-- 2) 解析占位：7 条上架题 analysis 仅为「无 / 时政 / 时政问题 / 由题意知」等
--    非解析片段，展示时会被当作正式解析。置空后前端统一显示「暂无解析」并提供
--    AI 生成解析入口（QuizPractice），不再出现伪解析。
--    涉及 id：459、32596、32597、32613、32614、32990、33012。
-- 守卫：全部限定仍上架 + 原文匹配，重复执行不会二次生效；不删除任何行。

-- 1) 下架完全重复题 #21135（保留 #19411）
UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = validation_errors || jsonb_build_array(jsonb_build_object(
        'code', 'duplicate_question',
        'detail', '与 #19411 题干/选项/答案逐字相同（来源不同），保留 #19411，本条移出练习池待去重')),
    validated_at = now(),
    updated_at = now()
WHERE id = 21135
  AND is_available IS TRUE
  AND btrim(content) = '对于二叉排序树，下面的说法中，（）是正确的。'
  AND btrim(answer) = 'C'
  AND coalesce(options::text, '') = (
      SELECT coalesce(options::text, '') FROM quiz_questions WHERE id = 19411
  );

-- 2) 解析占位置空（前端显示「暂无解析」+ AI 生成解析入口）
UPDATE quiz_questions
SET analysis = NULL,
    updated_at = now()
WHERE is_available IS TRUE
  AND id IN (459, 32596, 32597, 32613, 32614, 32990, 33012)
  AND btrim(coalesce(analysis, '')) IN ('无', '时政', '时政问题', '由题意知');
