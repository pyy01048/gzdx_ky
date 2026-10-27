# A 类核验：前端 P0 两项审计结论在当前代码中的真实状态

- 核验日期：2026-10-18（只读静态调查，未启动浏览器/服务，未改任何文件）
- 原审计：2026-10-17 只读审计（P0-1 五个管理页白屏、P0-2 kb-import 假数据）
- 仓库：D:\平台（frontend/ React18+Vite）
- git 限制说明：本仓库仅有单个初始快照提交 `1764f01（初始提交：考研学习平台 V11 代码快照）`，无法用提交历史定位修复时间点；下述「已修复」判定基于当前代码静态证据 + 代码内注释。
- 存放说明：目标路径 `.zwork/plan-gap/` 为平台保留目录拒绝写入，本文件改放 `docs/plan-gap/`，内容不变。

---

## A1【P0-1 五个管理页白屏】判定：已修复（静态代码层面，高置信；未做浏览器实测）

### 1. 路由归口确认（六页现全部挂 /admin 命名空间，共享同一布局）

`frontend/src/App.jsx:186-208`：

```jsx
<Route path="/admin" element={<RequireAdmin><AdminLayout /></RequireAdmin>}>
  <Route index element={<Navigate to="overview" replace />} />
  <Route path="overview" element={<DataCenter />} />
  <Route path="users" element={<UserAdmin />} />
  <Route path="subjects" element={<SubjectManager />} />
  <Route path="quiz-bank" element={<QuizBank />} />
  <Route path="quality" element={<QualityDashboard />} />
  <Route path="schools" element={<KaoyanImport />} />
  <Route path="crawl-sources" element={<KaoyanCrawlSources />} />
  <Route path="kb-import" element={<KnowledgeBaseImport />} />
  <Route path="model" element={<ModelTraining />} />
  <Route path="*" element={<Navigate to="overview" replace />} />
</Route>
```

原审计涉及的五页 + DataCenter 现在是同一个父布局 AdminLayout 的兄弟路由（/admin/subjects、/admin/quality、/admin/crawl-sources、/admin/kb-import、/admin/model、/admin/overview）。原审计「/data-center 正常而其它五页白屏」的差异前提已不存在：六页完全同构。

### 2. 白屏根因（淡入动画 opacity:0 起点）已被移除 —— 直接证据

`frontend/src/styles/global.css:450-454`：

```css
/* 只动位移不动透明度：动画时钟不走（后台标签/截图/节流）时，opacity:0 起点会让整页 DOM 在却全白 */
@keyframes pageIn { from { transform: translateY(10px); } to { transform: none; } }

.view-enter { animation: pageIn 380ms var(--ease-out); }
@media (prefers-reduced-motion: reduce) { .view-enter { animation: none; } }
```

- 注释逐字描述了原 P0-1 症状（「DOM 在却全白」），并说明修复策略：动画只动 transform，起点无 opacity。
- `.view-enter` 正是页面容器：`frontend/src/components/Layout.jsx:82` `<div className="view-enter" key={location.pathname}>{children}</div>`。
- 全仓 CSS 已确认无其它对 `.view-enter` 或 `pageIn` 的覆盖（grep `@keyframes pageIn` 仅 global.css:451 一处定义）。

### 3. AdminLayout 与 admin.css 无内容不可见规则

`frontend/src/components/AdminLayout.jsx:10-31`：`admin-shell`（左侧 NAV_ADMIN 侧栏 + 右侧 `<section className="admin-main"><Outlet /></section>`），无条件渲染、无 style 隐藏。

`frontend/src/styles/admin.css`（全文 55 行）逐条检查：

```css
.admin-shell {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: var(--space-6);
  align-items: start;
}
...
.admin-main { min-width: 0; }

@media (max-width: 767px) {
  .admin-shell { grid-template-columns: minmax(0, 1fr); gap: var(--space-3); }
  .admin-side { position: static; padding: var(--space-2); }
  .admin-side-menu { flex-direction: row; overflow-x: auto; }
  .admin-side-item { flex: 0 0 auto; }
  .admin-side-desc { display: none; }
}
```

- 无 `height: 0`、无 `opacity: 0`、无 `visibility: hidden`；`minmax(0, 1fr)` 是防溢出惯用写法，配合 `.admin-main { min-width: 0 }`。
- 仅有的两处"藏东西"：窄屏 `.admin-side-desc { display: none }`（admin.css:54，只藏侧栏描述文字）与窄屏侧栏菜单 `overflow-x: auto`（横向滚动，非隐藏）——均不影响主内容区。

### 4. 外层容器与页面级 CSS 无隐藏规则

- `frontend/src/styles/global.css:53-70`：`.app-shell.is-topnav { display: block; min-height: 100vh; }`、`.main-area { min-width: 0; padding: 30px clamp(18px, 4vw, 48px) 80px; max-width: 1200px; ... }` —— 无 height:0 / overflow:hidden。
- `frontend/src/styles/global.css:2610-2614`：QualityDashboard 根类 `.ky-page { max-width: 1200px; margin: 0 auto; padding: 24px 20px; }` 正常。
- `frontend/src/styles/v2-design.css:453-455`：`.container { max-width: 1080px; margin: 0 auto; }`、`.stack { display: flex; flex-direction: column; gap: 16px; }` 正常。
- `frontend/src/pages/DataCenter.css`、`frontend/src/pages/KaoyanCrawlSources.css`：grep `opacity:0|height:0|overflow:hidden|display:none|visibility|animation` 后逐条核对，命中项均为 text-overflow 截断、圆角裁切（overflow:hidden 配 border-radius）或禁用态弱化，无主内容隐藏。`KaoyanCrawlSources.css:77` `.kcs-row.is-off .kcs-main { opacity: 0.55; }` 只是"排除采集的院校"弱化显示，仍可见。
- 页面组件根节点抽查：
  - `pages/SubjectManager.jsx:140-144`：`<div className="container stack"> <div className="page-head spread"> <h1 className="page-title">科目管理</h1>`
  - `pages/ModelTraining.jsx:77-88`：loading 分支返回带标题的 page-head（非空 div）；正常分支 `<div><div className="page-head">...`
  - `pages/QualityDashboard.jsx:95-99`：`<div className="ky-page"><h1>评测与数据质量</h1>`
  - `pages/KnowledgeBaseImport.jsx:123-131`：`<div><div className="page-head">...<h1 className="page-title">知识库批量导入</h1>`
  - `pages/KaoyanCrawlSources.jsx:156-160`：`<div className="page kcs-page"> <div className="page-head">`
  - `pages/DataCenter.jsx:135-139`：`<div className="page dc-page"> <div className="page-head">`
  均无内联 opacity/display 隐藏。

### 5. 权限失败分支不会白屏

`frontend/src/auth/AuthContext.jsx:109-113`：

```jsx
export function RequireAdmin({ children }) {
  const { isAdmin } = useAuth()
  if (!isAdmin) return <Navigate to="/403" replace />
  return children ?? <Outlet />
}
```

非管理员访问 /admin/* 落 /403 页（App.jsx:170 `<Route path="/403" element={<Forbidden />} />`），不是白屏。

### 6. 体系性防白屏整改佐证（二手线索级，佐证时间线）

- `components/ErrorBoundary.jsx:5`：「V3.1 变更（白屏整改）」
- `hooks/useApiData.js:6`：「走查发现多个页面在接口异常/空数据时直接白屏，而各页面…」
- `components/States.jsx:29`：「统一错误态：就地提示 + 重试按钮（白屏克星…）」
- `styles/global.css:63`：「P0 清理 2026-10-14：旧侧边栏体系…死代码删除」—— 2026-10-14 前后有系统性 CSS 清理活动。

### A1 结论

原审计描述的白屏机制（opacity:0 起点的入场动画 + 共享布局回归）在当前代码中已不存在：动画起点只含 transform（global.css:451），六个管理页共用无隐藏规则的 AdminLayout/admin.css（admin.css 全文已查），各页面根节点渲染结构正常。静态判定「已修复」；因未启动浏览器，运行时验证留待建议项。

---

## A2【P0-2 kb-import 假数据】判定：已修复

### 1. KnowledgeBaseImport.jsx 现状：统计全部来自真实接口

`frontend/src/pages/KnowledgeBaseImport.jsx:14-28`：

```jsx
  /* 统计全部来自真实接口：
       /api/kb/health      → 文档数 / 分块数 / 待修问题
       /api/documents      → 文件类型、学科分布、最后导入时间
       /api/quiz/stats     → 已入库题数
     任一失败只在对应区块留空，不再用「4081 篇」这类演示数字冒充结果。 */
  const loadStats = async () => {
    setLoading(true)
    setStatsError('')
    const [kbR, docsR, quizR] = await Promise.allSettled([
      kbApi.health(),
      documentsApi.list({ page_size: 200 }),
      quizApi.stats(),
    ])
```

- 文档总数：`stats?.totalDocs ?? 0`，取自 `kb?.documents?.total ?? items.length`（jsx:58），无字面量。
- 已导入题目：`stats?.importedQuestions ?? 0`，取自 `quiz?.total_questions ?? quiz?.visible_total ?? 0`（jsx:64）。
- 学科分布：遍历真实文档列表按 `d.subject` 聚合（jsx:44-54），空时渲染 `<Empty title="暂无学科分类">`（jsx:169-172）——原「数学1200/英语800/政治600/贵大834 900」类硬编码分布已不存在。
- 接口失败口径：两主接口皆 rejected 时 `setStats(null)` + 错误提示（jsx:30-35）；部分失败显示「部分统计接口不可用，缺失的区块显示为 0」（jsx:66-68）。宁可 0/留空不造假。

### 2. 全仓残留搜索

- `4081|1523|贵大`（frontend/src 全部 .jsx/.js/.css）：唯一命中 `pages/KnowledgeBaseImport.jsx:21` 的修复注释本身，无任何演示数字残留。
- `Math\.random|mockData|fakeData|演示数据|假数据`：命中均为功能用途或修复注释，无演示数据：
  - `pages/KaoyanSchools.jsx:346`（随机推荐一所院校的功能）
  - `pages/Planner.jsx:464`、`pages/QuizHome.jsx:230`、`utils/date.js:70`（id 生成/选项洗牌）
  - `mocks/seed.js:5-9`（修复说明注释）、`pages/ErrorReview.jsx:31`、`pages/Words.jsx:107`（「不再回退本地假数据」注释）
- store 种子已清空并有测试锁定：`mocks/seed.js:24-35` SEED 中 `tasks/notebook/pan/words/decks/cards/packs` 全为 `[]`；`test/store.seed.empty.test.js:7`「已批口径：宁可空也不要假数据」。

### A2 结论

KnowledgeBaseImport.jsx 的演示数字已全部替换为真实接口聚合，失败时显示 0/空态/错误提示；4081/1523/贵大 等特征值在 frontend/src 无残留。判定「已修复」。

---

## A3【/admin 命名空间当前结构】

### 路由清单（App.jsx:186-208，外层包 `<RequireAdmin><AdminLayout /></RequireAdmin>`）

| 路径 | 组件 | 说明 |
|---|---|---|
| /admin（index） | Navigate → overview | |
| /admin/overview | DataCenter | 数据中心（原 /data-center） |
| /admin/users | UserAdmin | 用户管理（components/UserAdmin.jsx） |
| /admin/subjects | SubjectManager | 科目管理 |
| /admin/quiz-bank | QuizBank | 题库管理 |
| /admin/quality | QualityDashboard | 评测与数据质量 |
| /admin/schools | KaoyanImport | 院校数据管理（采集中心） |
| /admin/crawl-sources | KaoyanCrawlSources | 院校采集源 |
| /admin/kb-import | KnowledgeBaseImport | 知识库导入 |
| /admin/model | ModelTraining | 模型训练 |
| /admin/*（未匹配） | Navigate → overview | 兜底 |

### 旧路径重定向

- 生成机制：`App.jsx:209-211` `{ADMIN_LEGACY_REDIRECTS.map(([from, to]) => (<Route key={from} path={from} element={<LegacyRedirect to={to} />} />))}`；`App.jsx:59-62` `LegacyRedirect` 保留 `search` 与 `hash` 再 `replace` 跳转。
- 映射来源：`navConfig.js:92` `export const ADMIN_LEGACY_REDIRECTS = NAV_ADMIN.map((e) => [e.legacy, e.to])`，即 NAV_ADMIN 每项的 `legacy` 字段（navConfig.js:69-90），共 9 条：
  - /data-center → /admin/overview
  - /users → /admin/users
  - /subjects → /admin/subjects
  - /quiz-bank → /admin/quiz-bank
  - /quality → /admin/quality
  - /kaoyan/import → /admin/schools
  - /crawl-sources → /admin/crawl-sources
  - /kb-import → /admin/kb-import
  - /model-training → /admin/model
- 学生端隔离：`navConfig.js:96-98` `isAdminPath` / `entriesFor(isAdmin)` 把 /admin/* 从学生端导航与命令面板过滤掉（`entriesFor = (isAdmin) => (isAdmin ? ALL_ENTRIES : ALL_ENTRIES.filter((e) => !isAdminPath(e.to)))`）；面包屑父级固定为「管理后台」（navConfig.js:100-105 crumbParent）。
- 布局组件：`components/AdminLayout.jsx:10-31` admin-shell 网格（220px 侧栏 + 主区 Outlet），侧栏条目直接渲染 NAV_ADMIN（含 roles:['admin'] 标记，navConfig.js:91 `.map((e) => ({ ...e, roles: ['admin'] }))`）。

---

## 待证项 / 建议下一步

1. 运行时验证（本任务约束为静态）：在浏览器以管理员登录后逐页访问 /admin/subjects、/admin/quality、/admin/crawl-sources、/admin/kb-import、/admin/model，并把标签页切到后台 >30s 再切回（复现原审计「动画时钟不走」场景），确认内容可见。
2. 提交历史缺失：仓库只有单快照提交，若需确认修复发生时间与责任人，需比对仓库外的开发过程记录（docx/ 编号文档，如 docx/25 §D 被注释引用）。
3. 范围外备注（不在本次核验点内）：styles/Textbooks.css:270 仍存在 `@keyframes tb-fade { from { opacity: 0 } to { opacity: 1 } }` 的 opacity 起点动画（Textbooks 页），与 pageIn 修复模式不一致，若同场景（后台标签切回）可能复现同类问题，建议按同口径整改。
