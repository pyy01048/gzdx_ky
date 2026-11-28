-- 205_exam_question_source_text.sql
-- 抽题范围是 all/error/ai_generated，不是题目来源枚举；恢复为文本并保留存量值。

ALTER TABLE exam_sessions
    ALTER COLUMN question_source TYPE VARCHAR(30)
    USING question_source::text;

ALTER TABLE exam_sessions
    ALTER COLUMN question_source SET DEFAULT 'all';

COMMENT ON COLUMN exam_sessions.question_source IS
'抽题范围：all 全部 / error 本人错题 / ai_generated AI 生成题；与 quiz_questions.source_kind 正交';
