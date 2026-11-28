-- 129_major_garbage_cascade.sql
-- 接续 128：清理被外键依赖挡住的残留垃圾专业（它们各挂 1 条同源错误解析的 admissions）。
-- 来源：backfill 时 OCR 页码 / ISBN / QQ 辅导班广告被误当作专业名，连同 1 条 admissions 一起入库。
-- 128 已删除无依赖的 10 条；这里级联删除剩余 29 条的 admissions 后再删专业本身。
-- 幂等：重复执行均归 0；不触碰 '3S集成与气象应用'（不命中任一谓词）。

-- A. 先删除这些垃圾专业名下的 admissions（同一次错误解析产物，无独立价值）
DELETE FROM kaoyan_admissions
WHERE major_id IN (
    SELECT id FROM kaoyan_majors
    WHERE name ~ '^[0-9]+[：:．.。，, ]*$'
       OR code ~ '^978'
       OR (name ~ '(QQ|扫码|辅导班|交流群)' AND name ~ '[0-9]')
);

-- B. 再删除残留垃圾专业（已无 admissions；仍守卫 scorelines / kb_link，避免误伤任何真实关联）
DELETE FROM kaoyan_majors
WHERE (
        name ~ '^[0-9]+[：:．.。，, ]*$'
        OR code ~ '^978'
        OR (name ~ '(QQ|扫码|辅导班|交流群)' AND name ~ '[0-9]')
      )
  AND NOT EXISTS (SELECT 1 FROM kaoyan_scorelines s WHERE s.major_id = kaoyan_majors.id)
  AND NOT EXISTS (SELECT 1 FROM kaoyan_major_kb_link k WHERE k.major_id = kaoyan_majors.id);
