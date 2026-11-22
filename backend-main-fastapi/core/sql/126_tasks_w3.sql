-- =============================================================================
-- 126_tasks_w3.sql —— W3 任务/计划体验重做（多科目/子科目模块/起止/循环/提醒/进度条）
--
-- 变更清单（全部幂等，可重复执行；仅 PG 线跑本分片，SQLite 由 ORM create_all/
-- migrate.py 通道兜底 —— 模型列类型全部用通用 JSON/Date/Boolean/Integer，两方言兼容）：
--   1) tasks 加 9 列：subjects/modules/start_date/end_date/recurrence/remind/
--      show_progress/progress_total/progress_done
--   2) task_checkins：循环任务按日打卡（一任务一天一行，唯一约束=天然幂等）
--   3) task_modules：个人「子科目模块」字典（英语→真题/单词/语法，可增删）
--
-- 老数据零破坏：新增列全部可空/带默认；非循环任务沿用 due_date + status 旧口径，
-- 回退只需忽略新列（代码读 NULL 即回落旧行为）。
-- =============================================================================

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS subjects       JSONB;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS modules        JSONB;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS start_date     DATE;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS end_date       DATE;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence     JSONB;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS remind         JSONB;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS show_progress  BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS progress_total INTEGER;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS progress_done  INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN tasks.subjects       IS '多选科目 JSON 数组；subject 保留为兼容列=首元素';
COMMENT ON COLUMN tasks.modules        IS '子科目模块标签 JSON 字符串数组（如 ["真题","单词"]）';
COMMENT ON COLUMN tasks.start_date     IS '开始日期（循环锚点）';
COMMENT ON COLUMN tasks.end_date       IS '结束日期（循环截止；NULL=不限）';
COMMENT ON COLUMN tasks.recurrence     IS '循环规则 {freq,weekdays,interval,dates,until}，口径见 services/task_recurrence.py';
COMMENT ON COLUMN tasks.remind         IS '提醒 {type:point|range,time,start,end}（仅存储展示，未接系统推送）';
COMMENT ON COLUMN tasks.show_progress  IS '是否展示进度条';
COMMENT ON COLUMN tasks.progress_total IS '进度条分母（目标量）';
COMMENT ON COLUMN tasks.progress_done  IS '进度条分子（完成量）';

-- --------------------------------------------------------------------------- #
-- 循环任务按日打卡：完成状态落在"某一天"，非循环任务不写本表（旧口径不动）
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS task_checkins (
    id           BIGSERIAL   PRIMARY KEY,
    user_id      BIGINT      REFERENCES users(id) ON DELETE CASCADE,
    task_id      BIGINT      NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    checkin_date DATE        NOT NULL,
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_task_checkins UNIQUE (task_id, checkin_date)
);

CREATE INDEX IF NOT EXISTS ix_task_checkins_user_id ON task_checkins (user_id);
CREATE INDEX IF NOT EXISTS ix_task_checkins_task_id ON task_checkins (task_id);
CREATE INDEX IF NOT EXISTS ix_task_checkins_date    ON task_checkins (checkin_date);

COMMENT ON TABLE  task_checkins IS 'W3 循环任务按日打卡（一任务一天一行）；非循环任务仍用 tasks.status';
COMMENT ON COLUMN task_checkins.user_id IS '归属用户 ID（行级隔离键，与 tasks.user_id 同 FK 风格）';
COMMENT ON COLUMN task_checkins.checkin_date IS '打卡日期（本地日历日）';
COMMENT ON COLUMN task_checkins.completed_at IS '打卡时刻（UTC）';

-- --------------------------------------------------------------------------- #
-- 个人子科目模块字典（任务新建器的"可增删"落点；删字典行不影响存量任务快照）
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS task_modules (
    id         BIGSERIAL   PRIMARY KEY,
    user_id    BIGINT      REFERENCES users(id) ON DELETE CASCADE,
    subject    VARCHAR(50) NOT NULL,
    name       VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_task_module_dict UNIQUE (user_id, subject, name)
);

CREATE INDEX IF NOT EXISTS ix_task_modules_user_id ON task_modules (user_id);

COMMENT ON TABLE  task_modules IS '个人子科目模块字典：科目→自定义模块（英语→真题/单词/语法）';
COMMENT ON COLUMN task_modules.subject IS '所属科目（与 goals 科目配置同名单）';
COMMENT ON COLUMN task_modules.name    IS '模块名';
