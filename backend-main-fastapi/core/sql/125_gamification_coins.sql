-- =============================================================================
-- 125_gamification_coins.sql —— 金币激励体系（W6）
--
-- 设计文档：docs/design/gamification-coin-strategy-v1.md
-- 数值权威源：backend-main-fastapi/services/gamification.py
--   （DEFAULT_RULES / DEFAULT_SETTINGS / DEFAULT_ITEMS —— 本分片**只建表不播种数值**，
--    避免"SQL 一份数字、代码一份数字"两头漂；服务首次访问时幂等补齐缺失行。）
--
-- 为什么没有外键（与 121_exam_sessions_user_id.sql 同风格）：
--   * 这些表的 ORM 模型住在 core.models（新 Base），而 users 在 database.Base，
--     跨 Base 声明 FK 会在 flush 时抛 NoReferencedTableError（goals.py 头注释记录过
--     这个 500 事故）；
--   * users 是软删除（107），CASCADE 反而会把已注销用户的金币流水无声抹掉，
--     审计链断掉。故一律 user_id BIGINT + 索引，不加 FK。
--
-- 幂等：全部 IF NOT EXISTS / ON CONFLICT，可重复执行。PG 与 SQLite 双兼容由
--   core/models/gamification.py 的 ORM 声明保证（BigIntKey / DateTimeUTC /
--   JSONBObject 都是带 sqlite variant 的类型），服务层
--   ensure_gamification_schema() 在缺表时用 create_all 兜底建表。
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- 1) 金币账户：一人一行，余额 = 流水累加的物化缓存
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS coin_accounts (
    id                BIGSERIAL    PRIMARY KEY,
    user_id           BIGINT       NOT NULL,
    balance           BIGINT       NOT NULL DEFAULT 0,
    total_earned      BIGINT       NOT NULL DEFAULT 0,
    total_spent       BIGINT       NOT NULL DEFAULT 0,
    makeup_cards      INTEGER      NOT NULL DEFAULT 0,
    boost_until       TIMESTAMPTZ,
    last_checkin_date DATE,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_coin_accounts_user UNIQUE (user_id),
    CONSTRAINT ck_coin_accounts_balance CHECK (balance >= 0),
    CONSTRAINT ck_coin_accounts_cards   CHECK (makeup_cards >= 0)
);

CREATE INDEX IF NOT EXISTS ix_coin_accounts_user_id ON coin_accounts (user_id);

COMMENT ON TABLE  coin_accounts IS '金币账户（W6 激励体系）：余额/累计/补签卡库存/加成到期；月度补签次数不在此计数，由 checkin_logs 现算';
COMMENT ON COLUMN coin_accounts.id IS '自增主键';
COMMENT ON COLUMN coin_accounts.user_id IS '归属用户 ID（行级隔离键；无 FK，理由见分片头注释）';
COMMENT ON COLUMN coin_accounts.balance IS '当前金币余额 = 流水累加物化缓存，恒 >= 0（ck 约束兜底）';
COMMENT ON COLUMN coin_accounts.total_earned IS '历史累计获得金币（只增，用于统计与成就）';
COMMENT ON COLUMN coin_accounts.total_spent IS '历史累计消耗金币（只增）';
COMMENT ON COLUMN coin_accounts.makeup_cards IS '补签卡库存（兑换所得，补签时扣减）';
COMMENT ON COLUMN coin_accounts.boost_until IS '金币加成卡生效截止（naive UTC；NULL=未激活）';
COMMENT ON COLUMN coin_accounts.last_checkin_date IS '最近一次签到/补签所属的北京自然日';
COMMENT ON COLUMN coin_accounts.created_at IS '创建时间（UTC）';
COMMENT ON COLUMN coin_accounts.updated_at IS '最后更新时间（UTC，onupdate 维护）';

-- --------------------------------------------------------------------------- #
-- 2) 金币流水：append-only 台账，dedup_key 唯一 = 天然幂等
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS coin_ledger (
    id         BIGSERIAL    PRIMARY KEY,
    user_id    BIGINT       NOT NULL,
    biz_date   DATE         NOT NULL,
    rule_code  VARCHAR(40)  NOT NULL,
    direction  VARCHAR(8)   NOT NULL,
    coins      INTEGER      NOT NULL,
    unit_index INTEGER      NOT NULL DEFAULT 0,
    dedup_key  VARCHAR(120) NOT NULL,
    title      VARCHAR(80),
    meta       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    actor_id   BIGINT,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_coin_ledger_dedup UNIQUE (user_id, dedup_key),
    CONSTRAINT ck_coin_ledger_direction CHECK (direction IN ('earn', 'spend', 'adjust')),
    CONSTRAINT ck_coin_ledger_meta CHECK (jsonb_typeof(meta) = 'object')
);

CREATE INDEX IF NOT EXISTS ix_coin_ledger_user_date ON coin_ledger (user_id, biz_date DESC);
CREATE INDEX IF NOT EXISTS ix_coin_ledger_user_rule ON coin_ledger (user_id, rule_code, biz_date DESC);
CREATE INDEX IF NOT EXISTS ix_coin_ledger_user_id  ON coin_ledger (user_id);

COMMENT ON TABLE  coin_ledger IS '金币流水（append-only）：每一行是一个最小发放单位/一次消耗，禁止 UPDATE 余额以外的改写';
COMMENT ON COLUMN coin_ledger.id IS '自增主键';
COMMENT ON COLUMN coin_ledger.user_id IS '归属用户 ID（行级隔离键）';
COMMENT ON COLUMN coin_ledger.biz_date IS '业务归属的北京自然日（与 study_calendar 台账同一日界口径）';
COMMENT ON COLUMN coin_ledger.rule_code IS '规则码：word_review/error_review/checkin/streak_bonus/redeem/admin_adjust …';
COMMENT ON COLUMN coin_ledger.direction IS '方向：earn 发放 / spend 消耗 / adjust 管理员人工调整';
COMMENT ON COLUMN coin_ledger.coins IS '金币变动量：收入为正、支出为负（adjust 可正可负）';
COMMENT ON COLUMN coin_ledger.unit_index IS '同规则同日内的第 N 个单位（幂等序号，从 1 起；非批量类规则为 0）';
COMMENT ON COLUMN coin_ledger.dedup_key IS '幂等键 {rule}:{biz_date}:{unit_index} 等，(user_id, dedup_key) 唯一 ⇒ 重放零新增';
COMMENT ON COLUMN coin_ledger.title IS '流水标题（展示用，如"背单词 10 个"）';
COMMENT ON COLUMN coin_ledger.meta IS '结构化附注 JSON：单价/倍率/上限截断/兑换交付物/调整原因等';
COMMENT ON COLUMN coin_ledger.actor_id IS '管理员操作者 user_id（仅 admin_adjust 等后台动作写入）';
COMMENT ON COLUMN coin_ledger.created_at IS '落库时间（UTC）';

-- --------------------------------------------------------------------------- #
-- 3) 签到日志：一天一行（含补签）
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS checkin_logs (
    id          BIGSERIAL   PRIMARY KEY,
    user_id     BIGINT      NOT NULL,
    biz_date    DATE        NOT NULL,
    kind        VARCHAR(12) NOT NULL,
    coins       INTEGER     NOT NULL DEFAULT 0,
    streak_days INTEGER     NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_checkin_logs_user_day UNIQUE (user_id, biz_date),
    CONSTRAINT ck_checkin_logs_kind CHECK (kind IN ('manual', 'makeup'))
);

CREATE INDEX IF NOT EXISTS ix_checkin_logs_user ON checkin_logs (user_id, biz_date DESC);
CREATE INDEX IF NOT EXISTS ix_checkin_logs_user_id ON checkin_logs (user_id);

COMMENT ON TABLE  checkin_logs IS '签到日志：一人一日一行（唯一约束挡掉重复签到），补签也落这里';
COMMENT ON COLUMN checkin_logs.id IS '自增主键';
COMMENT ON COLUMN checkin_logs.user_id IS '归属用户 ID（行级隔离键）';
COMMENT ON COLUMN checkin_logs.biz_date IS '签到所属北京自然日（补签写的是被补的那一天）';
COMMENT ON COLUMN checkin_logs.kind IS '类型：manual 当日签到 / makeup 补签（不送币，只保连续）';
COMMENT ON COLUMN checkin_logs.coins IS '该次签到发放的金币数（补签恒为 0）';
COMMENT ON COLUMN checkin_logs.streak_days IS '签到时的连续天数快照（重算历史用，展示以实时日历为准）';
COMMENT ON COLUMN checkin_logs.created_at IS '落库时间（UTC）';

-- --------------------------------------------------------------------------- #
-- 4) 规则表：单价/计量/上限全部落库，管理台可改
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS gamification_rules (
    rule_code  VARCHAR(40) PRIMARY KEY,
    label      VARCHAR(60) NOT NULL,
    kind       VARCHAR(16) NOT NULL,
    per_units  INTEGER     NOT NULL DEFAULT 1,
    unit_label VARCHAR(20),
    coins      INTEGER     NOT NULL DEFAULT 0,
    daily_cap  INTEGER     NOT NULL DEFAULT 1,
    is_active  BOOLEAN     NOT NULL DEFAULT TRUE,
    sort_order INTEGER     NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_gamification_rules_kind CHECK (kind IN ('batch', 'per_item', 'daily_fixed')),
    CONSTRAINT ck_gamification_rules_coins CHECK (coins >= 0),
    CONSTRAINT ck_gamification_rules_cap   CHECK (daily_cap >= 0),
    CONSTRAINT ck_gamification_rules_per   CHECK (per_units >= 1)
);

COMMENT ON TABLE  gamification_rules IS '金币获取规则（W6）：kind=batch 每 per_units 个行为算一次，单次 coins，单日最多 daily_cap 次';
COMMENT ON COLUMN gamification_rules.rule_code IS '规则码（服务层 DEFAULT_RULES 的键，客户端不可指定金额）';
COMMENT ON COLUMN gamification_rules.label IS '展示名（如"背单词"）';
COMMENT ON COLUMN gamification_rules.kind IS '计量方式：batch 满 N 个计一次 / per_item 每个计一次 / daily_fixed 每日固定一次';
COMMENT ON COLUMN gamification_rules.per_units IS 'batch 口径：多少个真实行为折算一次（>=1）';
COMMENT ON COLUMN gamification_rules.unit_label IS '行为单位名（个/题/张/分钟），用于规则说明页';
COMMENT ON COLUMN gamification_rules.coins IS '一次发放的金币数（0=该规则不发币）';
COMMENT ON COLUMN gamification_rules.daily_cap IS '单日最多计次数（按 kind 折算后的"次"封顶，防刷核心闸）';
COMMENT ON COLUMN gamification_rules.is_active IS '是否启用；停用后不再发放，历史流水保留';
COMMENT ON COLUMN gamification_rules.sort_order IS '展示排序（升序）';
COMMENT ON COLUMN gamification_rules.updated_at IS '管理员最后修改时间（UTC）';

-- --------------------------------------------------------------------------- #
-- 5) 全局参数：日上限 / 签到基础币 / 里程碑 / 补签窗口 / 加成倍率
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS gamification_settings (
    setting_key VARCHAR(48) PRIMARY KEY,
    value       JSONB       NOT NULL,
    label       VARCHAR(80) NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  gamification_settings IS '激励体系全局参数（JSON 值）：daily_earn_cap / checkin_base_coins / streak_milestones / makeup_* / boost_*';
COMMENT ON COLUMN gamification_settings.setting_key IS '参数键（服务层 DEFAULT_SETTINGS 的键）';
COMMENT ON COLUMN gamification_settings.value IS '参数值 JSON（数字或 {档位:币数} 映射）';
COMMENT ON COLUMN gamification_settings.label IS '参数中文说明（管理台展示）';
COMMENT ON COLUMN gamification_settings.updated_at IS '管理员最后修改时间（UTC）';

-- --------------------------------------------------------------------------- #
-- 6) 商店商品 + 兑换流水
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS reward_items (
    code          VARCHAR(40)  PRIMARY KEY,
    name          VARCHAR(60)  NOT NULL,
    description   VARCHAR(200),
    kind          VARCHAR(20)  NOT NULL,
    cost_coins    INTEGER      NOT NULL,
    payload       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    monthly_limit INTEGER      NOT NULL DEFAULT 0,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    sort_order    INTEGER      NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_reward_items_kind CHECK (kind IN ('makeup_card', 'boost', 'avatar_frame', 'title')),
    CONSTRAINT ck_reward_items_cost CHECK (cost_coins >= 0)
);

COMMENT ON TABLE  reward_items IS '金币商店商品（W6）：只上架系统真能兑现的权益（补签卡/加成卡/头像框/称号）';
COMMENT ON COLUMN reward_items.code IS '商品码（服务层 DEFAULT_ITEMS 的键）';
COMMENT ON COLUMN reward_items.name IS '商品名';
COMMENT ON COLUMN reward_items.description IS '商品说明（含兑现方式，避免空头承诺）';
COMMENT ON COLUMN reward_items.kind IS '权益类型：makeup_card 补签卡 / boost 加成卡 / avatar_frame 头像框 / title 称号';
COMMENT ON COLUMN reward_items.cost_coins IS '兑换所需金币（>=0）';
COMMENT ON COLUMN reward_items.payload IS '类型相关参数 JSON：加成倍率与小时数、头像框样式键等';
COMMENT ON COLUMN reward_items.monthly_limit IS '每人每月兑换上限（0=不限）';
COMMENT ON COLUMN reward_items.is_active IS '是否上架；下架不影响已发放权益';
COMMENT ON COLUMN reward_items.sort_order IS '展示排序（升序）';
COMMENT ON COLUMN reward_items.updated_at IS '管理员最后修改时间（UTC）';

CREATE TABLE IF NOT EXISTS redemptions (
    id         BIGSERIAL   PRIMARY KEY,
    user_id    BIGINT      NOT NULL,
    item_code  VARCHAR(40) NOT NULL,
    cost_coins INTEGER     NOT NULL,
    status     VARCHAR(12) NOT NULL DEFAULT 'ok',
    biz_month  VARCHAR(7),
    detail     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_redemptions_status CHECK (status IN ('ok', 'refunded')),
    CONSTRAINT ck_redemptions_detail CHECK (jsonb_typeof(detail) = 'object')
);

CREATE INDEX IF NOT EXISTS ix_redemptions_user ON redemptions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_redemptions_user_id ON redemptions (user_id);
CREATE INDEX IF NOT EXISTS ix_redemptions_item ON redemptions (item_code, biz_month);

COMMENT ON TABLE  redemptions IS '兑换流水：与 coin_ledger(spend) 同事务双记账，月度限购按 biz_month 计数';
COMMENT ON COLUMN redemptions.id IS '自增主键';
COMMENT ON COLUMN redemptions.user_id IS '兑换人 user_id';
COMMENT ON COLUMN redemptions.item_code IS '商品码（reward_items.code，逻辑关联不设 FK）';
COMMENT ON COLUMN redemptions.cost_coins IS '本次实扣金币（正数）';
COMMENT ON COLUMN redemptions.status IS '状态：ok 已发货 / refunded 已退（退款另写 earn 流水）';
COMMENT ON COLUMN redemptions.biz_month IS '归属月份 YYYY-MM（月度限购计数键）';
COMMENT ON COLUMN redemptions.detail IS '发货明细 JSON：库存变化、解锁项、加成到期时间等';
COMMENT ON COLUMN redemptions.created_at IS '兑换时间（UTC）';

-- --------------------------------------------------------------------------- #
-- 7) 用户档案（设置页高级化：头像/个人信息/偏好）
--    与金币同属"激励与个性化"域，故同分片建表；users 表由 auth 域拥有，不改它。
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS user_profiles (
    id           BIGSERIAL    PRIMARY KEY,
    user_id      BIGINT       NOT NULL,
    avatar_kind  VARCHAR(12)  NOT NULL DEFAULT 'initials',
    avatar_value VARCHAR(300),
    avatar_frame VARCHAR(40),
    title        VARCHAR(40),
    bio          VARCHAR(200),
    grade        VARCHAR(20),
    major        VARCHAR(60),
    prefs        JSONB        NOT NULL DEFAULT '{}'::jsonb,
    unlocked     JSONB        NOT NULL DEFAULT '{"frames":[],"titles":[]}'::jsonb,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_profiles_user UNIQUE (user_id),
    CONSTRAINT ck_user_profiles_avatar_kind CHECK (avatar_kind IN ('initials', 'preset', 'url')),
    CONSTRAINT ck_user_profiles_prefs    CHECK (jsonb_typeof(prefs) = 'object'),
    CONSTRAINT ck_user_profiles_unlocked CHECK (jsonb_typeof(unlocked) = 'object')
);

CREATE INDEX IF NOT EXISTS ix_user_profiles_user_id ON user_profiles (user_id);

COMMENT ON TABLE  user_profiles IS '用户档案扩展（W6 设置页）：头像/称号/简介/年级专业/偏好/已解锁权益；users 表不动';
COMMENT ON COLUMN user_profiles.id IS '自增主键';
COMMENT ON COLUMN user_profiles.user_id IS '归属用户 ID（唯一，一人一行；无 FK，理由见分片头注释）';
COMMENT ON COLUMN user_profiles.avatar_kind IS '头像类型：initials 首字色块 / preset 内置表情 / url 外链图片';
COMMENT ON COLUMN user_profiles.avatar_value IS '头像值：色块色名或表情键，或经协议校验的图片 URL';
COMMENT ON COLUMN user_profiles.avatar_frame IS '当前使用中的头像框商品码（必须在 unlocked.frames 内，服务层校验）';
COMMENT ON COLUMN user_profiles.title IS '当前佩戴的称号商品码（必须在 unlocked.titles 内，服务层校验）';
COMMENT ON COLUMN user_profiles.bio IS '个人简介（<=200 字，服务层清洗）';
COMMENT ON COLUMN user_profiles.grade IS '年级/届别（如 2027 届），仅展示用';
COMMENT ON COLUMN user_profiles.major IS '专业方向（自由文本；目标院校与专业课仍以 goals 为权威，不在此重复）';
COMMENT ON COLUMN user_profiles.prefs IS '偏好 JSON：reduce_motion / font_scale / compact_mode / week_start / coin_toast 等，前端逐项生效';
COMMENT ON COLUMN user_profiles.unlocked IS '已解锁权益 JSON：{frames:[code…], titles:[code…]}，由兑换发货写入';
COMMENT ON COLUMN user_profiles.created_at IS '创建时间（UTC）';
COMMENT ON COLUMN user_profiles.updated_at IS '最后更新时间（UTC）';
