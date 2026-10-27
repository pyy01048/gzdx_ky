# E · 用户数据隔离改造清单（B4 落地）

> 对应 [B-auth.md](B-auth.md) 的 B4 缺口与 [00-核验汇总与执行计划.md](00-核验汇总与执行计划.md) 剩余缺口 2。
> 决策（2026-10-19）：**按用户区分个人数据；公共内容数据继续共用。** 本文是可执行改造清单：哪些表、哪些接口、前端哪些键、分几步落。
> 现状基线：多账号登录/会话/ RBAC 已完成（B1/B2/B3/B6 ✅），但 48 个 ORM 类无一含 user_id、无行级过滤；前端 localStorage 键全部全局，切换账号不清理。

---

## 0. 数据分类定版（先定口径，再动手）

| 类别 | 判定 | 数据 | 处理 |
|---|---|---|---|
| A 公共内容 | 平台资产，人人同看 | 题库 `quiz_questions`、院校库 `kaoyan_*`、知识库 `documents/knowledge_*`、科目配置、AI 服务商配置（管理员网关）、自定义链接 | **不动**，继续共用 |
| B 个人学习数据 | 只有主人该读写 | 任务、错题本、复习调度/记录、卡片、单词/词库、目标院校与考试日期、收藏、学习时长/事件/统计、刷题会话与作答、各类计划（日/周/月/阶段/艾宾浩斯/早起）、里程碑、通知已读/加星、AI 会话 | **加 user_id + 全链路过滤**（本文主体） |
| C 设备/本地偏好 | 浏览器本地即可，但不应跨账号残留 | UI 布局、仪表盘偏好、字段显隐、专注计时、考试倒计时、院校收藏/对比（前端版）、刷题本地记录、AI 本地会话缓存 | **键按 uid 后缀隔离，登录/登出清理** |

原则：A 共用、B 隔离、C 隔离但不一定落后端（按 uid 分键即可）。C 中若未来要跨设备同步（如考试日期），升格进 B。

---

## 1. 阶段总览

| 阶段 | 内容 | 交付物 | 规模 |
|---|---|---|---|
| P1 | 后端表结构：个人域表加 user_id + 回填 + 索引 | `core/sql/108_user_data_isolation.sql` + ORM 同步 | M |
| P2 | 后端路由/服务按 current_user 过滤与写入 | 逐路由改动 + 统一 scope 依赖 | M |
| P3 | 前端 store 按账号隔离（persist 键 + 登录/登出钩子） | `useStore.js` / `AuthContext.jsx` 改造 | S |
| P4 | 前端散键按 uid 后缀 + 旧键一次性迁移 | `utils/userKeys.js` + 13 个键改造 | S |
| P5 | 通知已读/加星改 per-user 表 | 新表 + notices 路由改造 | S |
| P6 | AI 会话隔离（方案 A 本地分键，可选 B 落库） | Assistant.jsx / useStore.js | S |
| P7 | （可选）网盘按用户绑定、code_oj 隔离 | netdisk / code_oj | M |

P1→P2 依赖强（先有列再有过滤）；P3/P4 可与 P2 并行；P5 独立；P6/P7 最后。

---

## 2. P1 · 后端表结构与迁移

### 2.1 加 user_id 的表（B 类个人域）

**第一批（学习闭环核心，`routers/` 在用）：**

| 表 | ORM 位置 | 说明 |
|---|---|---|
| `goals` | `models.py:121`（Goal） | 目标院校/考试日期——影响全站倒计时，优先 |
| `tasks` | `models.py:190`（Task） | |
| `review_schedules` | `models.py:156` / `core/models/learning.py` | SRS 权威队列，错题/卡片/单词共用 |
| `review_records` | `models.py:642`（ReviewRecord） | |
| `error_records` | `models.py:309`（ErrorRecord） | 错题本 |
| `error_knowledge_links` | `models.py:614` | 冗余 user_id 便于直接过滤（归属跟随 error） |
| `flashcards` | `models.py:674`（Flashcard） | |
| `words` | `models.py:906`（Word） | |
| `word_decks` | `models.py:890`（WordDeck） | 仅用户自建词库；内置词书可 user_id NULL 视为公共 |
| `favorites` | `core/sql/099_favorites.sql` | 全站收藏（题目收藏真相源） |
| `study_sessions` | `models.py:357` | 学习时长 |
| `study_events` | `models.py:1115` | 行为事件流 |
| `study_stats` | `models.py:873` | 聚合统计 |
| `answer_records` | `models.py:291` | 作答流水 |
| `quiz_sessions` / `quiz_attempts` | `core/models/quiz_sessions.py:17/71`（对齐 095） | 刷题会话与作答 |
| `daily_plans / week_plans / month_plans / phase_plans / ebbinghaus_items / early_bird_records / milestones` | `models.py:391-484/1141`（planning 域） | 计划体系 |

**第二批（列已在、无人写入，接线即可）：**

| 表 | 现状 |
|---|---|
| `paper_attempts` | `core/models/questions.py:212` 已有 `user_id`（注释"预留多用户扩展"） |
| `code_submissions` | `core/models/code_oj.py:77` 已有可空 user_id；`code_oj` 路由以 query 参数收 user_id（`routers/code_oj.py:74`），接线时改为取登录态 |

### 2.2 迁移脚本（`core/sql/108_user_data_isolation.sql`，幂等）

1. 逐表 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id)`（SQLite 线靠 ORM `create_all` + `ensure_schema_columns` 式补列，参照 `database.py` 注释的双后端机制与 104/107 的既有做法）。
2. 回填：**存量数据全部归属主账号**（内置管理员，`core/sql/104_users.sql` 头注释口径）。用变量传入主账号 id，`UPDATE <t> SET user_id = :owner WHERE user_id IS NULL`。这是"一家人共用"现状的平滑收编。
3. 索引：每张高频表建 `(user_id, <常用过滤列>)` 复合索引，如 `tasks(user_id, status)`、`review_schedules(user_id, next_review_at)`、`error_records(user_id, status)`。
4. 约束节奏：先允许 NULL（未接线期间兼容），P2 全部路由接线完成后再统一 `SET NOT NULL`（放 109 或同脚本尾部注释掉待启用）。**不要一步到位 NOT NULL**，否则 P1 落地瞬间所有旧代码写入全挂。

### 2.3 注意

- 真库在 `<repo>/database/kaoyan.db`（`migrate.py` 头注释），别碰 `backend-main-fastapi/data/kaoyan.db` 空壳。
- 迁移前按项目铁律走 `services.backup_service` 的 SQLite backup API 备份。
- ORM 与 SQL 双定义并存（`models.py` vs `core/models`），加列两处都要同步，避免 ADR-002 Phase 2 收口时漂移。

---

## 3. P2 · 后端路由 scope 接线

### 3.1 统一做法

- 身份依赖已就绪：`utils/security.py:210` `current_user`（校验 token + token_version + 强制改密拦截），直接 `Depends(current_user)`。
- 建议在 `utils/security.py`（或新增 `utils/scope.py`）加一个薄封装：

```python
def scoped(model, user):
    """个人域查询统一入口：Model.user_id == user.id。"""
    return model.user_id == user.id
```

- 查询侧：所有列表/详情/统计查询追加 `.filter(scoped(Model, user))`；**写入侧**：create/update 一律 `user_id=user.id`，杜绝"前端传谁的 id 就写谁的"。
- 更新/删除的越权防护：`db.query(Task).filter(Task.id == id, scoped(Task, user))` 查不到即 404（不要返回 403 泄露存在性）。

### 3.2 逐文件清单

| 路由/服务 | 改动 |
|---|---|
| `routers/tasks.py` | 全部端点挂 current_user；list/create/update/delete/complete 过滤 + 写入 |
| `routers/errors.py` + `stats_export.errors_router`（批量删除） | 同上；batch-delete 顺带补管理守卫口径（B3 漏网项） |
| `routers/flashcards.py` | 同上 |
| `routers/words.py` | 同上；内置词书（user_id NULL）按公共读处理 |
| `routers/goals.py` | 目标读写按用户；`dashboard.countdown` 跟随当前用户目标 |
| `routers/favorites.py` | 列表/check/toggle/删除全部按用户（题目收藏真相源，重点回归） |
| `routers/quiz.py` | submit 落 `answer_records/quiz_sessions/quiz_attempts` 带 user_id；`/api/quiz/review/{id}` 补 scope（B3 漏网项）；错因/年份统计按用户聚合 |
| `routers/review.py` | SRS 到期队列/评分按用户 |
| `routers/dashboard.py`、`analytics.py`、`growth.py`、`insight.py` | 所有 study_* 聚合加 `user_id ==` 过滤；否则仪表盘/趋势会跨用户混算 |
| `routers/plan.py`、`planner.py` | planning 域各表同上 |
| `routers/blind_spot.py` | 盲区池属个人学习数据，同上（若定位为公共池需在文档声明） |
| `routers/notices.py` + `services/kaoyan/notice_read.py` | 见 P5；顺带删除 `notices.py:5-9`、`notice_read.py:9-13` 的"无 users 表"过期注释 |
| `routers/stats_export.py` | CSV 导出按用户过滤，防止导出他人数据 |
| `routers/documents.py`、`kaoyan.py`、`codebank.py`、`taxonomy.py` 等 | **不动**（A 类公共内容） |
| `routers/ai.py` | 服务商配置是管理员公共配置，不动；但对话类端点若落库见 P6 |

### 3.3 兼容与开关

- 加环境开关 `USER_ISOLATION=on|off`（默认 on）：off 时 `scoped()` 恒真，出问题可一键回退旧行为；稳定一个迭代后删除。
- 前端 `api/client.js` 无需知道 user_id——身份全靠 httpOnly cookie，后端自己取。**禁止**让前端传 user_id 参数（那等于没隔离）。

---

## 4. P3 · 前端 store 按账号隔离

- 现状：zustand persist 固定键 `kaoyan-archive-v1`（`store/useStore.js` `partialize` 段），登录/登出只改内存态（`auth/AuthContext.jsx`），本地缓存跨账号串号。
- 改法：
  1. `useStore.js` 改用自定义 storage：`createJSONStorage(() => userStorage)`，读写键为 `kaoyan-archive-v1:{uid}`；uid 未设置（未登录）时不落盘。
  2. `AuthContext.login()` 成功后：设置全局 uid → `useStore.persist.rehydrate()` → 触发 `hydrate()`（AppShell 重挂载已有，`App.jsx:98-103` 注释即此设计，补 uid 键即可）。
  3. `AuthContext.logout()` 成功后：`resetAll()`（`useStore.js` 已有，重建种子态）→ 清掉 `kaoyan-archive-v1:{uid}` → 重置 uid。防止下一个账号读到上一个账号的内存态与磁盘态。
  4. `stripApiKeys`（partialize 剔除 apiKey）逻辑保持不变。
- `api/sync.js` 的 LOADERS 无需改动（数据按登录态从后端来）；`adoptId`、失败队列在 rehydrate 时随内存清空即可。

---

## 5. P4 · 前端散键隔离（13 键清单）

新增 `utils/userKeys.js`：

```js
let uid = null
export const setUser = (id) => { uid = id }
export const ukey = (base) => (uid ? `${base}:${uid}` : base)
```

各键改造（读/写两端都换 `ukey()`；首读若新键为空且旧键存在 → **一次性迁移给当前登录用户**（单机场景原主人大概率就是当前登录者），迁完删旧键）：

| 键 | 位置 | 类别 | 处理 |
|---|---|---|---|
| `quiz_favorites_v9` / `quiz_favorites_v9_synced` | `api/quizFavSync.js:25/32` | B 缓存 | 加后缀；真相源已是后端 favorites（P2 后天然按用户） |
| `quiz_wrong` | `pages/quizShared.js:31` | B | 加后缀 |
| `quiz_records_v10` | `pages/quizShared.js:54` | B | 加后缀 |
| `ky_fav_school_ids` | `pages/KaoyanSchools.jsx:44` | B | 加后缀；中期可并入后端 favorites(item_type='school') |
| `kaoyan-fav-schools` | `pages/KaoyanSchoolDetail.jsx:52` | B | 同上（与上一行是两套收藏实现，顺带收敛） |
| `ky_compare_school_ids` | `pages/KaoyanSchools.jsx:45`、`KaoyanCompare.jsx:26` | B | 加后缀 |
| `ky_exam_list` | `pages/KaoyanSchools.jsx:46` | B | 考试倒计时日期，个人数据，加后缀 |
| `focus_timer_v1` | `components/FocusTimer.jsx:36` | C | 加后缀 |
| `ui_layout_v1` | `hooks/useUiLayout.js:16` | C | 加后缀 |
| `dash_range_v1` / `dash_autorefresh_v1` | `pages/Dashboard.jsx:114/115` | C | 加后缀 |
| `er_field_visibility` | `pages/ErrorReview.jsx:74` | C | 加后缀 |
| `words_daily_quota` | `pages/Words.jsx:105/342` | B | 加后缀（中期并入 goals.daily_*_words，方案02 F2-04 已有此规划） |
| `kaoyan_pan_token` | `utils/pan.js:31` | C | **不迁移**，登出时清除（网盘授权凭据不应跨账号残留） |

登录钩子里 `setUser(user.id)`（AuthContext.login 成功处），登出钩子里清除本 uid 全部 `*:uid` 键 + `kaoyan_pan_token`。`localStorage.clear()` 只出现在测试里，生产代码保持无全清（避免误伤同域其他数据）。

---

## 6. P5 · 通知已读/加星 per-user

- 现状：`is_read/is_starred` 落在 `kaoyan_notices` 行上（`core/sql/061_notices.sql`），全用户共享状态（B-auth.md §B4.5）。
- 改法：新表 `notice_user_states(user_id, notice_id, is_read, is_starred, updated_at, UNIQUE(user_id, notice_id))`（进 108 或独立 110）；`kaoyan_notices` 上两列废弃或仅作兼容读。
- `routers/notices.py` 与 `services/kaoyan/notice_read.py` 读写改走新表，接口响应形状不变（前端零改动）。

---

## 7. P6 · AI 会话隔离

现状：会话列表/消息只存本地 `ai.localSessions`（`pages/Assistant.jsx:130/162` → store persist），后端无对应表。

- **方案 A（推荐先行）**：随 P3 的按 uid persist 键自动隔离，零后端改动。缺点：换设备不同步——与现状一致，不算回退。
- **方案 B（可选）**：落库 `ai_conversations / ai_messages`（加 user_id），`sync.js` 增 loader；注意 token 体积与流式写库时机，另立专项评估。

---

## 8. P7 · 可选项

- **网盘按用户绑定**：per-user 表已备好（`third_party_accounts.user_id` 等，`core/sql/103_netdisk_four_tables.sql`，管理端 `routers/admin_netdisk.py` 已按 user_id 增删查），但用户态 `/api/netdisk/*` 用共享凭据 `PlatformConfig("baidu_netdisk")`（`services/netdisk_service.py:416-421`，见 B-auth.md §B4.4）。接线：用户态取当前用户绑定的账号，未绑定则引导授权；`kaoyan_pan_token` 移入后端会话。
- **code_oj**：恢复挂载时把 query 参数 user_id 改为登录态注入（`routers/code_oj.py:74`）。

---

## 9. 验收清单（双账号切换用例）

同一浏览器先后登录 A、B（B 建议用管理员另建的测试号）：

1. A 建任务 → B 登录看不到该任务；B 建任务 A 也看不到。
2. A 刷题提交 → 错题本/作答记录/掌握度只进 A 的账号。
3. A 收藏题目 → B 的题库收藏态为未收藏；B 收藏后两账号互不影响。
4. A 设置目标院校/考试日期 → B 的倒计时不受影响。
5. 单词/卡片复习进度两账号各自独立，仪表盘待复习数各自计算。
6. 通知：A 标记已读，B 仍显示未读。
7. AI 会话：A 的会话列表在 B 登录后不可见（P6 方案 A）。
8. 刷题本地记录/院校收藏/倒计时：B 登录后不出现 A 的数据（P4 迁移后新写入不再串）。
9. 登出 → 再登 A：A 的数据完整回来（迁移与持久化不丢数据）。
10. 直接用 API 调 `/api/tasks/{B的任务id}`（带 A 的 cookie）→ 404。
11. `USER_ISOLATION=off` 冒烟：旧行为可复现（回退开关有效）。

## 10. 测试影响面

- 前端：`test/quizFavSync.test.jsx`、`test/focusTimer.test.jsx` 等大量 `localStorage.clear()` + 旧键直写的用例需换 `ukey()` 口径；`test/auth.guard.test.jsx` 补"登录/登出清理"断言。
- 后端：`tests/` 里个人域路由用例补双用户越权（404）断言；`conftest` 需提供两个测试用户与独立会话。
- 回归重点：quizFavSync 并集语义（`test/quizFavSync.test.jsx:7` 锁定的三条）在加 user 维度后不破坏。

## 11. 风险与回滚

| 风险 | 缓解 |
|---|---|
| P1 落地瞬间旧代码写入 NULL user_id | 先 NULL 兼容，P2 全量接线后再 NOT NULL（2.2.4） |
| 存量数据归属争议 | 统一归主账号（2.2.2），需要再手工划转 |
| 聚合/统计遗漏过滤 → 跨用户混算 | 3.2 表逐项打钩 + 验收 5/6/10 |
| 前端迁移丢数据 | P4 一次性迁移"读空才迁、迁完删旧"，且 persist 键版本化（store 已有 version/migrate 机制） |
| 需要紧急回退 | `USER_ISOLATION=off` 开关 + 备份（2.3） |

工作量粗估：P1+P2 后端约 M（3~5 天），P3+P4 前端约 S~M（2~3 天），P5 半天，P6 方案 A 半天；P7 另议。
