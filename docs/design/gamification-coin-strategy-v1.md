# 金币激励体系 V1（W6）—— 一页策略设计

> 落地位置：后端 `services/gamification.py`（唯一数值权威源 `DEFAULT_RULES` / `DEFAULT_SETTINGS` / `DEFAULT_ITEMS`）
> + `core/sql/125_gamification_coins.sql`（表结构）+ `routers/study/gamification.py`（`/api/gamification/*`）
> + 前端 `src/v3/pages/Settings.jsx`「我的金币」分区 与 `UserAdmin.jsx`「激励运营」子页。
> 本文档只写"为什么是这些数字"，数字本身以代码为准（避免文档与库内配置两头漂）。

## 1. 双币种：等级看积分，花钱用金币

| 币种 | 是否可减 | 用途 | 唯一来源 |
| --- | --- | --- | --- |
| 成长积分（既有） | 只由行为聚合推导 | 等级 / 徽章 / 成就 | `routers/study/growth.py` 从 `study_events` 聚合，**本次不动它** |
| 金币（新增） | 可赚可花 | 商店兑换（补签卡 / 加成卡 / 头像框 / 称号） | `coin_ledger` 流水累加出的余额 |

刻意**不再造第二套等级/经验**：同屏出现两个"积分"必然打架（本项目已因两个 streak 口径吃过教训）。
金币只做一件事——把"今天的学习痕迹"变成可支配的额度，让"连续"有即期回报。

## 2. 唯一时间口径

- 自然日 = 北京日（`utils/timeutil.local_today`），**不额外给跨零点宽限**。
- "今天学没学 / 连续几天" 一律取 `services/study_calendar.day_ledger(user_id=…)` +
  `streak_summary`，与首页 KPI、热力图、成长页**同一个数字**。
- 金币发放同样按 `day_ledger` 的当日计数折算 ⇒ 客户端报不出任何数值，也就刷不出币。

## 3. 获取途径与单价（每类都有单日上限）

| 规则码 | 行为 | 一次的定义 | 单价 | 单日上限 |
| --- | --- | --- | --- | --- |
| `word_review` | 背单词（`review_records.item_type='word'`） | 每 10 个词 = 1 轮 | +10 | 3 轮（30） |
| `error_review` | 复习错题（`item_type='error'`） | 每 5 题 = 1 批 | +20 | 2 批（40） |
| `card_review` | 卡片复习 | 每 10 张 = 1 组 | +8 | 2 组（16） |
| `knowledge_review` | 知识点复习 | 每 5 个 = 1 组 | +6 | 2 组（12） |
| `quiz_correct` | 答题**答对**（只认对，不认错） | 每 10 题 = 1 组 | +12 | 3 组（36） |
| `focus_pomodoro` | 专注计时（真实分钟） | 每 25 分钟 = 1 番茄 | +6 | 4 个（24） |
| `task_done` | 完成计划任务 | 1 个任务 = 1 次 | +6 | 5 个（30） |
| `exam_submit` | 模考交卷 | 1 场 = 1 次 | +50 | 1 场（50） |
| `checkin` | 每日签到（需当日有学习痕迹） | 1 天 1 次 | +5 | 1 次（5） |
| `streak_bonus` | 连续打卡里程碑 | 3 / 7 / 14 / 30 天 | +10 / +25 / +60 / +150 | 当日各档只发一次 |

- 全勤一天（背词 30 + 错题 10 + 专注 100 分钟 + 签到 + 每周一次 7 天里程碑）≈ **100~120 币/天**；
- 全局单日发放上限 `daily_earn_cap = 260`（含里程碑），命中即截断并在响应里如实返回 `capped=true`，不静默吞掉；
- 定价基准：补签卡 80 币 ⇒ **全勤 1 天可买 1 张**；头像框 200~400 币 ⇒ 2~4 天真实投入。奖励"到场"而不是奖励"刷量"。
- 断签**不扣币**、不降级：只做正向激励（对齐 W1「去恐慌」原则）。

## 4. 消耗与补签规则

| 商品码 | 名称 | 价格 | 交付物 | 限购 |
| --- | --- | --- | --- | --- |
| `makeup_card` | 补签卡 | 80 | `coin_accounts.makeup_cards` +1 | 每月 2 张 |
| `coin_boost` | 金币加成卡（×1.5 / 24 小时） | 200 | `coin_accounts.boost_until` | 每月 2 张 |
| `frame_flame` / `frame_scholar` / `frame_star` | 头像框 | 200 / 300 / 400 | 永久解锁（`user_profiles.unlocked`） | 一次性 |
| `title_persist` / `title_master` | 称号「七日不辍」「百题斩将」 | 250 / 500 | 永久解锁，可在设置选用 | 一次性 |

补签（`POST /api/gamification/checkin/makeup`）：
1. 消耗 1 张补签卡，**不送金币**（只保连续，避免"补签套利"）；
2. 窗口 ≤ 7 天（`makeup_window_days`），且那天必须**有学习痕迹**（`day_ledger.is_active`）—— 完全没学的日子补不了，这是事实而不是惩罚；
3. 每月最多 3 次（`makeup_monthly_limit`），跨月自动重新计数；
4. 补签后连续天数按合并日历重算，里程碑不因补签重复发放。

## 5. 防刷（服务端硬闸，客户端无法报价）

| 风险 | 拦法 |
| --- | --- |
| 前端自报金额 / 自报次数 | 发币只从 `day_ledger` 服务端折算；`/award` 类接口一律不存在，客户端只能调 `/sync` |
| 重复调用刷币 | `coin_ledger (user_id, dedup_key)` 唯一索引；`dedup_key = {规则}:{日期}:{序号}`，重放 = 0 新增 |
| 单条行为无限计 | 每规则 `daily_cap`（按"次"封顶）+ 全局 `daily_earn_cap`（按币封顶） |
| 反复签到 | `checkin_logs (user_id, biz_date)` 唯一；无学习痕迹不能签到 |
| 补签洗连续 | 需卡 + 7 天窗口 + 当月 3 次 + 当天真实活跃 |
| 兑换白拿 | 扣款与发货同事务，余额不足 400 拒绝；`redemptions` + `coin_ledger(spend)` 双记账 |
| 管理员随手发币 | `POST /api/gamification/admin/adjust` 必填 `reason`，流水记 `actor_id`，可在审计页回溯 |
| 阈值被放宽导致通胀 | 规则/全局参数存库（`gamification_rules` / `gamification_settings`），改动留 `updated_at`，只走管理员接口 |
| 零数据新号看到假奖励 | 所有读接口无数据即 0 / 空列表 + `state=empty`，不播种假流水 |

## 6. 可配置性与扩展位

- 默认值只在 `services/gamification.py` 声明一次；首次访问把缺失行幂等播种进库，
  **管理员改过的值永不被代码覆盖**（只补新增规则码）。
- 管理台「激励运营」可改：单价、每 N 行为算一次、单日上限、启用开关、商品价格与限购，
  以及全局参数（日上限 / 签到基础币 / 里程碑表 / 补签窗口与月限 / 加成倍率与时长）。
- 下一步（本次**未做**，避免空头承诺）：金币兑换真实权益（模考卷、打印券）需对应业务侧先有兑现能力；
  排行榜需要隐私评审后才开。
