-- 203_quiz_unverified_control_ocr_quarantine.sql
-- 自动控制 PDF 修复回退（2026-11-26）：隔离本轮由扫描 OCR 扁平文本导入的 266 条记录。
-- 证据：题块会跨题吞入来源/题干，128 条引用图形但无配图，另有公式残缺、页眉污染和选项乱序。
-- 扁平 OCR 缺少坐标、阅读顺序与公式识别，无法证明其余记录可靠，因此整批移出练习池，不猜写内容。
-- 仅命中精确 ID 区间、来源、批次入库时间与来源类型；保留记录及用户关联，等待带版面/公式的重新解析。
-- 幂等：validation_errors 去重追加，重复执行不重复留痕。

UPDATE quiz_questions AS q
SET is_available = false,
    is_junk = true,
    needs_review = false,
    validation_status = 'warn',
    figure_missing = CASE
        WHEN q.content ~ '(如图|下图|结构图|曲线图|相平面|示意图|图中|所示)'
         AND (q.images IS NULL OR q.images::text IN ('null', '[]')) THEN 1
        ELSE q.figure_missing
    END,
    validation_errors = CASE
        WHEN q.validation_errors @> '[{"code":"unverified_ocr_import"}]'::jsonb THEN q.validation_errors
        ELSE coalesce(q.validation_errors, '[]'::jsonb) || jsonb_build_array(jsonb_build_object(
            'code', 'unverified_ocr_import',
            'detail', '扫描 PDF 扁平 OCR 存在跨题拼接、缺图或公式损坏，整批隔离，待保留版面与公式的重新解析'))
    END,
    validated_at = now(),
    updated_at = now()
WHERE q.id BETWEEN 34741 AND 35006
  AND q.source_label = '2026考研-自动控制777题习题集自控基础300题-题目册-真橙.pdf'
  AND q.source_kind = 'external_import'
  AND q.created_at = TIMESTAMPTZ '2026-11-26 07:37:00.836462+00'
  AND q.is_junk IS FALSE;
