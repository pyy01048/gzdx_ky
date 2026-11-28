-- 135_quiz_unanswerable_quarantine.sql
-- 题库治理：隔离「客观上无法作答」的活跃题，减少误判与无效刷题。
--
-- 依据（云端只读审计 2026-11-24，活跃池 11234 条）：
--   A. 题干明确引用图/表/曲线（"如图X所示"），但 figure_missing=1 且 images 为空
--      → 学生看不到题目依赖的图形，任何作答都是猜。命中 14 条。
--   B. 题干把「上一题的选项 + 下一题的题干」拼接在一起（OCR 跨题串行）
--      → 题干与 options/answer 不属于同一道题，判分必然错。典型 #15022。
--   C. 数学题公式在 OCR 中整段丢失，题干只剩「设，则（）」「曲线（）」这类悬空残句
--      → 无公式无法作答。命中 19 条（#182 与 A 重叠）。
--
-- 处理口径（与 131/133/134 一致，幂等、不物理删除）：
--   is_available=false（移出练习池）+ needs_review=true（进入人工修复队列）
--   validation_status='warn'，validation_errors 追加可追溯的原因码
-- 保留行与历史关联（错题本/试卷引用不失效），修复后可重新上架。

-- ── A. 引用图形但库内无图 ────────────────────────────────────────────────
UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = coalesce(validation_errors, '[]'::jsonb)
      || '[{"code":"figure_missing_unanswerable","detail":"题干引用图/表/曲线但库内无图，无法作答，已移出练习池待补图"}]'::jsonb,
    validated_at = now(),
    updated_at = now()
WHERE is_available = true
  AND (is_junk IS FALSE OR is_junk IS NULL)
  AND figure_missing = 1
  AND (images IS NULL OR images::text IN ('null', '[]'))
  AND content ~ '(图|表|曲线|所示|如下图|上图)';

-- ── B. 跨题串行：题干里夹带上题选项 + 下题正文 ─────────────────────────
UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = coalesce(validation_errors, '[]'::jsonb)
      || '[{"code":"merged_questions","detail":"题干由上一题选项与下一题正文拼接而成，题干与答案不属同题，已移出练习池待拆分"}]'::jsonb,
    validated_at = now(),
    updated_at = now()
WHERE is_available = true
  AND (is_junk IS FALSE OR is_junk IS NULL)
  AND id IN (
    15022  -- 政治：职业道德题干 + 「第八章…67. 法律…」正文，options/answer 属后一题
  );

-- ── C. 公式丢失导致题干残缺（数学悬空残句）────────────────────────────
UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = coalesce(validation_errors, '[]'::jsonb)
      || '[{"code":"stem_truncated","detail":"公式在 OCR 中丢失，题干只剩悬空残句，无法作答，已移出练习池待补公式"}]'::jsonb,
    validated_at = now(),
    updated_at = now()
WHERE is_available = true
  AND (is_junk IS FALSE OR is_junk IS NULL)
  AND question_type IN ('single', 'multiple')
  AND (images IS NULL OR images::text IN ('null', '[]'))
  AND length(btrim(content)) <= 20
  AND content ~ '^(设[，,]?则|则|是|曲线|函数|极限|中正确|中错误|已知[，,]|已知则|级数|求|正确的有|若[，,]|当[，,])'
  AND content !~ '^(下列|以下|关于)';
