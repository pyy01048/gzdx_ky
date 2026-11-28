-- 208：普通刷题会话兼容 V3 前端模式。

ALTER TABLE quiz_sessions DROP CONSTRAINT IF EXISTS ck_quiz_sessions_mode;
ALTER TABLE quiz_sessions ADD CONSTRAINT ck_quiz_sessions_mode
    CHECK (mode IN ('chapter_practice', 'smart_paper', 'free_practice', 'practice', 'memorize'));

COMMENT ON COLUMN quiz_sessions.mode IS
    '会话模式：chapter_practice 章节练习 / smart_paper 智能组卷 / free_practice 自由练习 / practice 普通练习 / memorize 背题模式';
