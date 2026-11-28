-- 204_personal_question_bank.sql
-- 个人题库：题目所有权、用户题库、题库成员与逐用户掌握状态。
-- 只扩展 schema，不回填存量题目所有者，不修改任何历史迁移或题目内容。

ALTER TABLE quiz_questions
    ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_quiz_questions_owner_user'
          AND conrelid = 'quiz_questions'::regclass
    ) THEN
        ALTER TABLE quiz_questions
            ADD CONSTRAINT fk_quiz_questions_owner_user
            FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;
END $$;

COMMENT ON COLUMN quiz_questions.owner_user_id IS
'题目所有者；NULL=公共题，非 NULL=用户私有题；用户删除时私有题级联删除';

CREATE INDEX IF NOT EXISTS idx_qq_owner_available
    ON quiz_questions (owner_user_id, is_available, is_junk);

CREATE TABLE IF NOT EXISTS quiz_question_sets (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR(200) NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_qqs_user_updated
    ON quiz_question_sets (user_id, updated_at DESC);

COMMENT ON TABLE quiz_question_sets IS '用户个人题库；删除用户或题库均级联清理成员';

CREATE TABLE IF NOT EXISTS quiz_question_set_items (
    set_id      BIGINT NOT NULL REFERENCES quiz_question_sets(id) ON DELETE CASCADE,
    question_id BIGINT NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_qqsi_set_question UNIQUE (set_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_qqsi_question ON quiz_question_set_items (question_id);
CREATE INDEX IF NOT EXISTS idx_qqsi_set_added ON quiz_question_set_items (set_id, added_at DESC);

COMMENT ON TABLE quiz_question_set_items IS
'个人题库成员；同一题可加入多个库，移除成员绝不删除公共题本体';

CREATE TABLE IF NOT EXISTS quiz_question_states (
    user_id          BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question_id      BIGINT NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    mastery_state    VARCHAR(20) NOT NULL DEFAULT 'unmastered',
    last_result      BOOLEAN,
    attempts         INTEGER NOT NULL DEFAULT 0,
    last_answered_at TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_qqs_user_question UNIQUE (user_id, question_id),
    CONSTRAINT ck_qqs_mastery_state CHECK (mastery_state IN ('unmastered', 'mastered')),
    CONSTRAINT ck_qqs_attempts_nonnegative CHECK (attempts >= 0)
);

CREATE INDEX IF NOT EXISTS idx_qqs_question ON quiz_question_states (question_id);
CREATE INDEX IF NOT EXISTS idx_qqs_user_mastery ON quiz_question_states (user_id, mastery_state);

COMMENT ON TABLE quiz_question_states IS
'逐用户题目状态；无记录按 unmastered，手动切换不伪造作答结果或次数';

DROP TRIGGER IF EXISTS trg_qqs_updated ON quiz_question_sets;
CREATE TRIGGER trg_qqs_updated BEFORE UPDATE ON quiz_question_sets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_qqstate_updated ON quiz_question_states;
CREATE TRIGGER trg_qqstate_updated BEFORE UPDATE ON quiz_question_states
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
