-- =============================================================================
-- 070 单词与其他辅助域
-- 依赖：000 / 010
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- 单词本与单词
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS word_decks (
    id          BIGSERIAL    PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    description VARCHAR(500),
    source      VARCHAR(100),
    word_count  INTEGER      NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_deck_name UNIQUE (name)
);

COMMENT ON TABLE  word_decks IS '单词本表';
COMMENT ON COLUMN word_decks.name IS '单词本名称，唯一';
COMMENT ON COLUMN word_decks.description IS '单词本描述';
COMMENT ON COLUMN word_decks.source IS '来源：考研大纲 / 真题词频 / 自定义';
COMMENT ON COLUMN word_decks.word_count IS '单词总数（冗余，由触发器维护）';

CREATE TABLE IF NOT EXISTS words (
    id             BIGSERIAL    PRIMARY KEY,
    deck_id        BIGINT       REFERENCES word_decks(id) ON DELETE CASCADE,
    word           VARCHAR(100) NOT NULL,
    phonetic       VARCHAR(100),
    pos            VARCHAR(50),
    meaning        TEXT         NOT NULL,
    root           VARCHAR(300),
    example        TEXT,
    example_cn     TEXT,
    tag            VARCHAR(50),
    status         mastery_level NOT NULL DEFAULT 'not_mastered',
    ease_factor    REAL         NOT NULL DEFAULT 2.5,
    interval_days  INTEGER      NOT NULL DEFAULT 0,
    reps           INTEGER      NOT NULL DEFAULT 0,
    lapses         INTEGER      NOT NULL DEFAULT 0,
    due_date       DATE,
    last_review    DATE,
    review_history JSONB        NOT NULL DEFAULT '[]'::jsonb,
    extra          JSONB,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_word_in_deck UNIQUE (deck_id, word),
    CONSTRAINT ck_word_ease CHECK (ease_factor >= 1.3 AND ease_factor <= 3.5)
);

COMMENT ON TABLE  words IS '单词表：SM-2 调度与复习历史';
COMMENT ON COLUMN words.deck_id IS '所属单词本 ID，单词本删除时级联删除';
COMMENT ON COLUMN words.word IS '单词，同一单词本内唯一';
COMMENT ON COLUMN words.phonetic IS '音标';
COMMENT ON COLUMN words.pos IS '词性';
COMMENT ON COLUMN words.meaning IS '释义';
COMMENT ON COLUMN words.root IS '词根词缀';
COMMENT ON COLUMN words.example IS '英文例句';
COMMENT ON COLUMN words.example_cn IS '例句翻译';
COMMENT ON COLUMN words.tag IS '标签：高频 / 熟词僻义 / 词组';
COMMENT ON COLUMN words.status IS '掌握状态（复用 mastery_level 枚举）';
COMMENT ON COLUMN words.due_date IS '下次到期日期';
COMMENT ON COLUMN words.review_history IS '复习历史数组（JSON）';
COMMENT ON COLUMN words.extra IS '扩展数据 JSON：同近义/短语/同根（KyleBing 等结构化词源）';
COMMENT ON COLUMN words.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN words.updated_at IS '最后更新时间';

CREATE INDEX IF NOT EXISTS idx_words_deck ON words (deck_id, due_date);

CREATE OR REPLACE TRIGGER trg_words_updated BEFORE UPDATE ON words
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 网盘文件
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS netdisk_files (
    id             BIGSERIAL     PRIMARY KEY,
    file_name      VARCHAR(500)  NOT NULL,
    path           VARCHAR(1000),
    file_type      VARCHAR(50),
    size           BIGINT,
    category       VARCHAR(100),
    download_link  VARCHAR(1000),
    play_progress  REAL          NOT NULL DEFAULT 0,
    fs_id          VARCHAR(100),
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT ck_netdisk_progress CHECK (play_progress >= 0 AND play_progress <= 1)
);

COMMENT ON TABLE  netdisk_files IS '网盘文件索引表：视频/讲义等学习资源';
COMMENT ON COLUMN netdisk_files.file_type IS '文件类型：video / pdf / doc / audio';
COMMENT ON COLUMN netdisk_files.play_progress IS '播放进度 0-1';
COMMENT ON COLUMN netdisk_files.fs_id IS '网盘侧文件 ID';
COMMENT ON COLUMN netdisk_files.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN netdisk_files.updated_at IS '最后更新时间';

CREATE INDEX IF NOT EXISTS idx_netdisk_category ON netdisk_files (category);

CREATE OR REPLACE TRIGGER trg_netdisk_updated BEFORE UPDATE ON netdisk_files
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 训练与评测：标注样本 / SFT 样例 / 评测批次 / 检索门日志
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS annotation_samples (
    id            BIGSERIAL   PRIMARY KEY,
    chunk_id      BIGINT      REFERENCES knowledge_chunks(id) ON DELETE SET NULL,
    chunk_text    TEXT        NOT NULL,
    label_l1      VARCHAR(50),
    label_l2      VARCHAR(200),
    label_l3      l3_content_type,
    annotate_user VARCHAR(50),
    source        VARCHAR(20) NOT NULL DEFAULT 'manual',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  annotation_samples IS '人工标注样本表：用于训练与评估分块分类器';
COMMENT ON COLUMN annotation_samples.chunk_id IS '被标注的分块 ID';
COMMENT ON COLUMN annotation_samples.chunk_text IS '标注时的分块正文快照';
COMMENT ON COLUMN annotation_samples.label_l3 IS 'L3 标注结果';
COMMENT ON COLUMN annotation_samples.source IS '样本来源：manual / auto_generated / imported';

CREATE INDEX IF NOT EXISTS idx_annotation_chunk ON annotation_samples (chunk_id);

CREATE TABLE IF NOT EXISTS sft_examples (
    id         BIGSERIAL PRIMARY KEY,
    split      VARCHAR(20) NOT NULL DEFAULT 'train',
    system     TEXT,
    user_input TEXT,
    assistant  TEXT,
    subject_id BIGINT      REFERENCES subjects(id) ON DELETE SET NULL,
    subject    VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sft_split CHECK (split IN ('train','valid','test'))
);

COMMENT ON TABLE  sft_examples IS '微调样例表：指令微调数据（system/user/assistant 三段式）';
COMMENT ON COLUMN sft_examples.split IS '数据划分：train / valid / test';
COMMENT ON COLUMN sft_examples.system IS '系统提示词';
COMMENT ON COLUMN sft_examples.user_input IS '用户输入';
COMMENT ON COLUMN sft_examples.assistant IS '期望回复';
COMMENT ON COLUMN sft_examples.subject_id IS '权威科目外键';
COMMENT ON COLUMN sft_examples.subject IS '兼容列：科目中文名';

CREATE INDEX IF NOT EXISTS idx_sft_split ON sft_examples (split, subject_id);

CREATE TABLE IF NOT EXISTS eval_runs (
    id                 BIGSERIAL    PRIMARY KEY,
    kind               VARCHAR(24)  NOT NULL,
    arm                VARCHAR(120),
    dataset_fingerprint VARCHAR(64),
    n_samples          INTEGER      NOT NULL DEFAULT 0,
    primary_metric     REAL,
    metrics            JSONB        NOT NULL DEFAULT '{}'::jsonb,
    report_path        VARCHAR(300),
    notes              TEXT,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  eval_runs IS '评测运行记录表：对比不同策略（arm）的效果';
COMMENT ON COLUMN eval_runs.kind IS '评测类型：retrieval / generation / grading';
COMMENT ON COLUMN eval_runs.arm IS '对比臂名称，如 baseline / hybrid_rerank';
COMMENT ON COLUMN eval_runs.dataset_fingerprint IS '评测集指纹，保证可复现';
COMMENT ON COLUMN eval_runs.primary_metric IS '主指标数值';
COMMENT ON COLUMN eval_runs.metrics IS '全部指标（JSON 对象）';
COMMENT ON COLUMN eval_runs.report_path IS '报告文件路径';

CREATE INDEX IF NOT EXISTS idx_eval_runs_time ON eval_runs (created_at DESC);

CREATE TABLE IF NOT EXISTS retrieval_gate_logs (
    id                 BIGSERIAL   PRIMARY KEY,
    query              TEXT        NOT NULL,
    is_complex         BOOLEAN     NOT NULL DEFAULT FALSE,
    decision           VARCHAR(30) NOT NULL,
    reason_codes       TEXT,
    top1_score         REAL,
    topk_mean          REAL,
    top1_margin        REAL,
    distinct_doc_count INTEGER,
    gate_mode          VARCHAR(30),
    would_abstain      BOOLEAN     NOT NULL DEFAULT FALSE,
    latency_ms         INTEGER,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  retrieval_gate_logs IS '检索门决策日志：记录每次检索是否放行/拒答及其依据';
COMMENT ON COLUMN retrieval_gate_logs.query IS '用户查询原文';
COMMENT ON COLUMN retrieval_gate_logs.is_complex IS '是否被判为复杂查询';
COMMENT ON COLUMN retrieval_gate_logs.decision IS '门决策：answer / abstain / clarify';
COMMENT ON COLUMN retrieval_gate_logs.reason_codes IS '决策理由码（逗号分隔）';
COMMENT ON COLUMN retrieval_gate_logs.top1_score IS '最高相似度';
COMMENT ON COLUMN retrieval_gate_logs.topk_mean IS 'TopK 平均相似度';
COMMENT ON COLUMN retrieval_gate_logs.top1_margin IS 'Top1 与第二名的分差';
COMMENT ON COLUMN retrieval_gate_logs.distinct_doc_count IS '命中结果覆盖的文档数';
COMMENT ON COLUMN retrieval_gate_logs.gate_mode IS '门模式：off / soft / strict';
COMMENT ON COLUMN retrieval_gate_logs.would_abstain IS '在对照模式下是否会拒答（用于灰度评估）';
COMMENT ON COLUMN retrieval_gate_logs.latency_ms IS '检索耗时（毫秒）';

CREATE INDEX IF NOT EXISTS idx_gate_logs_time   ON retrieval_gate_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gate_logs_decision ON retrieval_gate_logs (decision, created_at DESC);
