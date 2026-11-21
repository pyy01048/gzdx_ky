-- =============================================================================
-- 117 quiz_questions 四分类筛选主键 + 来源留痕列
-- -----------------------------------------------------------------------------
-- 背景（2026-11，08 工学题库建设）：
--   08 工学题库需要按「真题 / 练习题 / 习题 / 考研题」四分类独立筛选，
--   并与既有的来源性质 source_kind 正交。旧库只有 source_kind，无法区分
--   「试卷原题」与「面向考研科目体系组织的题目」这两套口径，故新增：
--
--     question_category  ENUM('真题','练习题','习题','考研题')   筛选主键
--     exam_type          VARCHAR(50)                             考试类型
--     source_platform    VARCHAR(100)                            来源平台
--     source_url         TEXT                                     来源链接
--
-- 与 source_kind 的映射（用于存量数据回填，仅按来源性质启发式归类）：
--     past_exam        -> 真题
--     textbook / chapter_exercise -> 习题
--     mock_exam        -> 练习题
--     external_import  -> 习题（既有自建题库按章节习题口径）
--     ai_generated / user_created -> 练习题
--
-- 幂等：全部 ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS / DO 块，
--       可反复重跑。依赖 040_questions.sql 建出的 quiz_questions 与
--       000_extensions_and_enums.sql 的类型体系。
-- =============================================================================

-- 1. 四分类枚举类型（中文标签与用户口径一致）
DO $$ BEGIN CREATE TYPE question_category AS ENUM ('真题','练习题','习题','考研题');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 2. 四分类筛选主键
--    DEFAULT '习题'：存量题绝大多数来自章节习题口径；随后的 DO 块按 source_kind 回填纠正。
ALTER TABLE quiz_questions
    ADD COLUMN IF NOT EXISTS question_category question_category NOT NULL DEFAULT '习题';

COMMENT ON COLUMN quiz_questions.question_category IS
    '题目主分类（筛选主键）：真题/练习题/习题/考研题；与 source_kind 正交';

-- 3. 考试类型
ALTER TABLE quiz_questions
    ADD COLUMN IF NOT EXISTS exam_type VARCHAR(50);

COMMENT ON COLUMN quiz_questions.exam_type IS
    '考试类型：考研/期末/期中/竞赛/资格认证/教材课后/模拟/平时';

-- 4. 来源平台
ALTER TABLE quiz_questions
    ADD COLUMN IF NOT EXISTS source_platform VARCHAR(100);

COMMENT ON COLUMN quiz_questions.source_platform IS
    '来源平台：国家高等教育智慧教育平台/中科UMajor/维普/MIT OCW/考试资料网/GitHub 等';

-- 5. 来源链接
ALTER TABLE quiz_questions
    ADD COLUMN IF NOT EXISTS source_url TEXT;

COMMENT ON COLUMN quiz_questions.source_url IS '来源链接，供溯源与复核';

-- 6. 存量数据按 source_kind 启发式回填（不覆盖已显式归类的新数据）
DO $$
BEGIN
    UPDATE quiz_questions
       SET question_category = (CASE source_kind
            WHEN 'past_exam'      THEN '真题'
            WHEN 'textbook'       THEN '习题'
            WHEN 'chapter_exercise' THEN '习题'
            WHEN 'mock_exam'      THEN '练习题'
            WHEN 'external_import' THEN '习题'
            WHEN 'ai_generated'   THEN '练习题'
            WHEN 'user_created'   THEN '练习题'
            ELSE '习题'
        END)::question_category
     WHERE question_category = '习题'
       AND source_kind IN ('past_exam','textbook','chapter_exercise',
                           'mock_exam','external_import','ai_generated','user_created');
END $$;

-- 7. 四分类筛选索引（刷题页按分类抽题是最高频操作）
CREATE INDEX IF NOT EXISTS idx_qq_question_category ON quiz_questions (question_category);
CREATE INDEX IF NOT EXISTS idx_qq_source_platform   ON quiz_questions (source_platform);
