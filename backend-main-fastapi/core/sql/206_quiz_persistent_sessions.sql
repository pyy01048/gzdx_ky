-- 206：普通刷题持久会话。题目顺序使用独立快照表，避免题目后续变更影响续做。

ALTER TABLE quiz_sessions ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE quiz_attempts ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id);
ALTER TABLE quiz_sessions ADD COLUMN IF NOT EXISTS title VARCHAR(300) NOT NULL DEFAULT '普通刷题';
ALTER TABLE quiz_sessions ADD COLUMN IF NOT EXISTS no_answer BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE quiz_sessions ADD COLUMN IF NOT EXISTS basis JSONB;
ALTER TABLE quiz_sessions ADD COLUMN IF NOT EXISTS current_index INTEGER NOT NULL DEFAULT 0;
ALTER TABLE quiz_sessions ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE quiz_sessions ADD COLUMN IF NOT EXISTS drafts JSONB NOT NULL DEFAULT '{}';
ALTER TABLE quiz_sessions ADD COLUMN IF NOT EXISTS text_drafts JSONB NOT NULL DEFAULT '{}';
ALTER TABLE quiz_sessions ADD COLUMN IF NOT EXISTS self_scores JSONB NOT NULL DEFAULT '{}';
ALTER TABLE quiz_sessions ADD COLUMN IF NOT EXISTS marked JSONB NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS quiz_session_questions (
    id          BIGSERIAL PRIMARY KEY,
    session_id  BIGINT NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    user_id     BIGINT REFERENCES users(id),
    question_id INTEGER NOT NULL REFERENCES quiz_questions(id) ON DELETE RESTRICT,
    position    INTEGER NOT NULL,
    snapshot    JSONB NOT NULL,
    CONSTRAINT uq_quiz_session_question_position UNIQUE (session_id, position),
    CONSTRAINT uq_quiz_session_question UNIQUE (session_id, question_id)
);

CREATE INDEX IF NOT EXISTS ix_quiz_session_questions_user ON quiz_session_questions (user_id, session_id);
CREATE INDEX IF NOT EXISTS ix_quiz_sessions_latest ON quiz_sessions (user_id, status, updated_at DESC);

ALTER TABLE quiz_attempts ADD COLUMN IF NOT EXISTS client_attempt_id VARCHAR(100);
ALTER TABLE quiz_attempts ADD COLUMN IF NOT EXISTS answer_record_id INTEGER REFERENCES answer_records(id);
ALTER TABLE quiz_attempts ALTER COLUMN self_rating TYPE VARCHAR(20);

CREATE UNIQUE INDEX IF NOT EXISTS uq_quiz_attempt_session_question ON quiz_attempts (session_id, question_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_quiz_attempt_client ON quiz_attempts (user_id, client_attempt_id)
    WHERE client_attempt_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_quiz_attempts_answer_record ON quiz_attempts (answer_record_id);
