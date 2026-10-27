-- 任务1：院校-专业关联补充
-- 从 kaoyan_scorelines 反推无专业院校的专业记录，幂等插入
-- 策略：以 (school_id, major_name, degree_type) 分组，取最规范（长度最长）的 major_code

WITH target_schools AS (
    SELECT id FROM kaoyan_schools s
    WHERE s.deleted_at IS NULL
      AND NOT EXISTS (SELECT 1 FROM kaoyan_majors m WHERE m.school_id = s.id)
),
ranked AS (
    SELECT
        school_id,
        major_name,
        degree_type,
        major_code,
        ROW_NUMBER() OVER (
            PARTITION BY school_id, major_name, degree_type
            ORDER BY LENGTH(major_code) DESC, major_code ASC
        ) AS rn
    FROM kaoyan_scorelines
    WHERE school_id IN (SELECT id FROM target_schools)
      AND deleted_at IS NULL
      AND major_name IS NOT NULL AND major_name <> ''
      AND major_code IS NOT NULL AND major_code <> ''
    GROUP BY school_id, major_name, degree_type, major_code
)
INSERT INTO kaoyan_majors (school_id, code, name, degree_type, exam_subjects, reference_books)
SELECT
    r.school_id,
    r.major_code,
    r.major_name,
    CASE
        WHEN r.degree_type = '专业型' THEN 'professional'::degree_type
        WHEN r.degree_type = '学术型' THEN 'academic'::degree_type
        ELSE 'unknown'::degree_type
    END,
    '[]'::jsonb,
    '[]'::jsonb
FROM ranked r
WHERE r.rn = 1
ON CONFLICT (school_id, code, name) DO NOTHING;