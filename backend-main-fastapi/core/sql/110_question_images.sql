-- 110_question_images.sql
-- 题目配图列：OCR/人工录入产出的图片引用数组。
-- 元素可为 URL、相对路径，或 {url,page,bbox,kind} 对象；空数组表示无图。
-- 幂等；PostgreSQL 方言。

ALTER TABLE quiz_questions
  ADD COLUMN IF NOT EXISTS images JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN quiz_questions.images IS '题目配图数组：[{url,page,bbox,kind}] 或路径字符串；空数组=无图';
