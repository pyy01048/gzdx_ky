-- 144_school_score_outlier_cleanup.sql
-- 院校分数数据体检修复（2026-11-24）：清理物理不可能的聚合分与录取总分，
-- 避免污染院校库「录取均分」排序、院校详情「院线区间趋势」与「拟录取分数直方图」。
-- 守卫：每条 UPDATE 均以旧值等值为条件，可重复执行（幂等）。

-- [1] 中国民航大学 081000 信息与通信工程 2026：录取均分 3425.0 → 342.5
--     入库时小数点丢失（342.5 ×10）；同一 admission 的 2 条录取明细总分为 341 / 344，均分 342.5。
UPDATE kaoyan_admissions
SET admit_avg_score = 342.5
WHERE id = 1563 AND admit_avg_score = 3425.0;

-- [2] 厦门大学（school 415）2026：专业课均分 0.0 表示「未采集」，改 NULL 而非 0
--     聚合口径 func.avg 会忽略 NULL；0 会被当成真实分数拉低展示值。
UPDATE kaoyan_admissions
SET major_avg_score = NULL
WHERE id = 242 AND major_avg_score = 0;

-- [3] 南昌大学 6 条分数线为 PDF 合并单元格解析残行：major_name 为乱序乱码，
--     total_line 取自正文残留数字（8/14/15）。该校已有 085400/085401/085402… 正常行
--     （total_line 260/264），故这 6 行只保留单科线，总分置空并标为不可用。
UPDATE kaoyan_scorelines
SET total_line = NULL, enabled = false, deleted_at = now()
WHERE id IN (183295, 183296, 183297, 183298, 183299, 183300)
  AND total_line IS NOT NULL;

-- [4] 录取明细总分越界（<100 或 >500）：42 行西安交大记录把百分制复试成绩误写入
--     score_total（68.70 等），另有 4 行为 0 占位或列错位。总分口径为 500 分制，
--     越界值一律置 NULL（保留行与其他字段，不臆造替换值）。
UPDATE kaoyan_admission_details
SET score_total = NULL
WHERE score_total IS NOT NULL AND (score_total > 500 OR score_total < 100);
