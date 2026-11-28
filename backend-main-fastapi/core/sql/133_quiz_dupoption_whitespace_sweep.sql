-- 133_quiz_dupoption_whitespace_sweep.sql
-- 题库治理（补 131 的盲区）：131 用 count(DISTINCT o->>'text') 判重复，但 PG 文本比较
-- 对空白敏感——"仅 II" 与 "仅II"（仅多一个空格）被判为不同，导致 6 道「仅空白差异」的
-- 重复选项题漏网，仍留在练习池里，学生看到两个一模一样的选项无法作答。
--
-- 本迁移：
--   1) 高置信修复 2 道（OCR 丢字符/下标，可从标准题意唯一确定），直接回归练习池；
--   2) 用「去除全部空白后」的文本判重，隔离其余所有仅空白差异的重复选项客观题
--      （字段与 131 一致：is_available=false / needs_review=true / validation_status='warn'
--       / validation_errors 追加原因 / validated_at / updated_at）。
-- 幂等：修复按 ID；sweep 仅处理当前仍在练习池且去空白后仍重复的行，重复执行无副作用。
-- 不物理删除、不编造内容：隔离题保留可检索、可经复核页人工修复后重新上架。

-- ── 修复 1：id=20591（计算机网络）SMTP/POP3 基于的传输层协议 ──
-- 原题四选项为 (SMTP,POP3) 的 2×2 组合：A TCP,TCP / B TCP,UDP / C UDP,TCP / D UDP,UDP。
-- OCR 把 C 的 "TCP" 误读成 "UDP"，致 C、D 完全相同；正确答案为 A（两者均 TCP），不受影响，
-- 但 C/D 重复属确定性缺陷，修回 C = "UDP, TCP"。
UPDATE quiz_questions
SET options = (
      SELECT jsonb_agg(
               CASE WHEN elem->>'key' = 'C'
                    THEN jsonb_set(elem, '{text}', '"UDP, TCP"')
                    ELSE elem END
               ORDER BY ord)
      FROM jsonb_array_elements(options) WITH ORDINALITY AS t(elem, ord)
    ),
    updated_at = now()
WHERE id = 20591;

-- ── 修复 2：id=19062（数据结构）冒泡排序最坏频度 ──
-- 标准答案 O(n²)，选项应为 A O(n) / B O(nlog₂n) / C O(n³) / D O(n²)。
-- OCR 丢了下标/上标：B 的 ₂→z、C 的 ³→3、D 的 ² 整体丢失（留一个尾随空格，
-- 使 D 退化成 "O（n ）" 与 A "O（n）" 去空白后相同，且答案选项 D 显示错误）。
-- 按原题意唯一确定，修回 B/C/D。
UPDATE quiz_questions
SET options = (
      SELECT jsonb_agg(
               CASE elem->>'key'
                 WHEN 'B' THEN jsonb_set(elem, '{text}', '"O（nlog₂n）"')
                 WHEN 'C' THEN jsonb_set(elem, '{text}', '"O（n³）"')
                 WHEN 'D' THEN jsonb_set(elem, '{text}', '"O（n²）"')
                 ELSE elem END
               ORDER BY ord)
      FROM jsonb_array_elements(options) WITH ORDINALITY AS t(elem, ord)
    ),
    updated_at = now()
WHERE id = 19062;

-- ── sweep：隔离所有「去空白后选项文本重复」的客观题（含 131 漏网的 4 道 + 未来新增）──
-- 判重口径：去掉选项文本中所有空白字符后再比对，避免空白差异漏网；
-- 同时要求至少有一个非空文本，避免把空选项题误判为重复。
UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = coalesce(validation_errors, '[]'::jsonb)
      || '[{"code":"duplicate_option_text","detail":"选项文本仅空白差异即重复，疑 OCR 错乱，已移出练习池待人工修复"}]'::jsonb,
    validated_at = now(),
    updated_at = now()
WHERE is_available = true
  AND question_type IN ('single', 'multiple')
  AND options IS NOT NULL
  AND jsonb_typeof(options) = 'array'
  AND jsonb_array_length(options) > 1
  AND (SELECT count(*) FROM jsonb_array_elements(options) o WHERE o->>'text' IS NOT NULL) > 1
  AND (
        SELECT count(DISTINCT regexp_replace(coalesce(o->>'text',''), '\s', '', 'g'))
        FROM jsonb_array_elements(options) o
        WHERE o->>'text' IS NOT NULL
      )
      < (
        SELECT count(*)
        FROM jsonb_array_elements(options) o
        WHERE o->>'text' IS NOT NULL
      );
