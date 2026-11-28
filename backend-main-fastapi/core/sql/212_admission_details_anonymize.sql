-- 212：存量官方录取名单匿名化。
-- 只处理院校官方 notice: 来源，保留 data_source 幂等键；不修改第三方样本。
-- 姓名统一匿名，考号只保留后四位；空考号保持 NULL。可重复执行。
-- 依赖 109。

UPDATE kaoyan_admission_details
SET name = '匿名考生',
    exam_no = CASE
        WHEN exam_no IS NULL OR btrim(exam_no) = '' THEN NULL
        ELSE '***' || right(btrim(exam_no), 4)
    END
WHERE data_source LIKE 'notice:%'
  AND (
      name IS DISTINCT FROM '匿名考生'
      OR exam_no IS DISTINCT FROM CASE
          WHEN exam_no IS NULL OR btrim(exam_no) = '' THEN NULL
          ELSE '***' || right(btrim(exam_no), 4)
      END
  );

COMMENT ON COLUMN kaoyan_admission_details.name IS '公开名单姓名统一存储为匿名考生';
COMMENT ON COLUMN kaoyan_admission_details.exam_no IS '考生编号只存储掩码及后四位，空值保持 NULL';
