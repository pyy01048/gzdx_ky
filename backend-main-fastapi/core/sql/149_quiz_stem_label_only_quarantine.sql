-- 149_quiz_stem_label_only_quarantine.sql
-- 题库质量（2026-11-24）：英语「新题型」七选五/排序题在 OCR 后仅剩
-- 「新题型（第N题）」标签，原文段落与 7 个选项全部缺失，题干无法作答；
-- 且同标签多条答案不一，无法自动补全。按既有 quarantine 约定下架：
-- is_available=false、needs_review=true、validation_status=warn，并写入原因留痕。
-- 守卫：仅处理仍在上架且题干仍为纯标签的 50 条，幂等。
-- 涉及 id：23181-23185, 23281-23285, 23581-23585, 23881-23885,
--          23981-23985, 24081-24085, 24381-24385, 24481-24485,
--          24581-24585, 24681-24685。

UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = validation_errors || jsonb_build_array(jsonb_build_object(
        'code', 'stem_label_only',
        'detail', '英语新题型题干仅「新题型（第N题）」标签，原文段落与选项缺失，无法作答，已移出练习池待补原题')),
    validated_at = now(),
    updated_at = now()
WHERE is_available IS TRUE
  AND content ~ '^[^，。；：,.!?]{0,12}[（(]第\s*[0-9]+\s*题[)）]$'
  AND id IN (23181, 23182, 23183, 23184, 23185,
             23281, 23282, 23283, 23284, 23285,
             23581, 23582, 23583, 23584, 23585,
             23881, 23882, 23883, 23884, 23885,
             23981, 23982, 23983, 23984, 23985,
             24081, 24082, 24083, 24084, 24085,
             24381, 24382, 24383, 24384, 24385,
             24481, 24482, 24483, 24484, 24485,
             24581, 24582, 24583, 24584, 24585,
             24681, 24682, 24683, 24684, 24685);
