# 核验报告：导航统一 / 学生-管理 IA 分离 / 仪表盘自愈 / 指标口径

- 核验日期：2026-10-18（只读核查，未改文件、未跑构建/测试、未启动服务）
- 对象：D:\平台 frontend/（React18 + Vite + react-router6 + zustand）+ backend-main-fastapi
- 背景：2026-10-17 审计称当时导航有 3-4 份漂移来源、仪表盘冷启动误报橙条、文档计数三处口径不一
- 备注：原定落点 .zwork/plan-gap/ 为运行时保留目录不可写，改放 docs/plan-gap/ 同名文件
- 置信等级：除特别标注外均为「确定」（一手代码证据，文件:行号 + 摘录）

---

## C1. 导航单一源（P1-2）—— 已完成

navConfig.js 自声明为唯一源并导出全部导航清单：

- `frontend/src/nav/navConfig.js:1-2`：文件头注释「全站唯一导航源：顶栏下拉 / 移动端抽屉 / 面包屑 / 相关功能 / Ctrl+K 命令面板 / 设置页界面自定义 全部从这里派生。新增页面只改这一处。」
- 导出：`MODULES`(:5)、`NAV_OTHER`(:60)、`NAV_ADMIN`(:69)、`MOBILE_TABS`(:87)、`ALL_ENTRIES`(:95)、`RELATED`(:123)、`crumbParent`(:107)/`crumbName`(:117)、`visibleModules`(:146)/`visibleOther`(:154)、`KAOYAN_TABS`(:143)。

逐文件 import/使用证据：

| 使用方 | 证据 |
|---|---|
| TopNav（桌面导航） | `TopNav.jsx:10` `import { ADMIN_ROOT, visibleModules, visibleOther } from '../nav/navConfig'`；:31 `const modules = visibleModules(layout)`；:32-33 showSettings/showAssistant 由 `visibleOther` 判定；:81 下拉项 `module.items.map(...)`（无内联数组）；:87 管理入口 `{isAdmin && <NavLink to={ADMIN_ROOT}...管理后台</NavLink>}` |
| Layout（移动端 Tab + 更多抽屉 + 面包屑） | `Layout.jsx:8` `import { MOBILE_TABS, NAV_ADMIN, NAV_OTHER, RELATED, crumbName, crumbParent, visibleModules } from '../nav/navConfig'`；:23-29 「更多」抽屉 groups = `visibleModules(...)` + `{title:'系统', items:NAV_OTHER}` + 管理员追加 `{title:'管理后台', items:NAV_ADMIN}`（原 MORE_GROUPS 常量已不存在，注释 :22「分组与顶栏同源」）；:40 底部 Tab `MOBILE_TABS.map(...)`；:88-96 面包屑 `crumbParent(location.pathname)` + `crumbName(...)`；:107-111 相关功能 `RELATED[...]` + `crumbName(to)` |
| CommandPalette | `CommandPalette.jsx:4` `import { entriesFor } from '../nav/navConfig'`；:53 `const entries = entriesFor(isAdmin)`（管理员才含 NAV_ADMIN 项） |
| 面包屑/相关功能 | 同 Layout.jsx:88-111；名称全部经 navConfig `crumbName` |
| 设置-界面自定义 | `UiCustomize.jsx:10` `import { NAV_MODULES, NAV_OTHER } from '../nav/navConfig'`（NAV_MODULES = MODULES 再导出，navConfig.js:85）；挂载于 `Settings.jsx:491` `<div hidden={tab !== 'appearance'}><UiCustomize /></div>` |
| 其他派生方 | `GlobalAI.jsx:10` `import { MODULES, NAV_OTHER, crumbName } from '../nav/navConfig'`；`AdminLayout.jsx:3` `import { NAV_ADMIN } ...` |
| 测试锁定 | `test/navConfig.test.jsx:31` `describe('navConfig 单一导航源')`：断言 ALL_ENTRIES 的 to 都有路由且唯一(:34-40)、每项有 desc/kw(:42)、crumbName 各值(:46-50)、KAOYAN_TABS 等于 school 组(:65)；`test/auth.guard.test.jsx:21-22` 断言普通用户条目 = ALL_ENTRIES − NAV_ADMIN |

残留内联清单（不影响 C1 判定，均为页面局部跳转矩阵，不喂给顶栏/抽屉/面板/面包屑）：
- `Dashboard.jsx:38-49` `MODULES`（首页宫格，键含 `/kbmap` 与 navConfig 的 `/knowledge` 不一致；被 UiCustomize 引用作「全部模块」显隐）——属仪表盘区块配置，建议后续观察是否与 navConfig 收敛。
- `ErrorDomainNav.jsx:9`（错题域内 chip）、`DataCenter.jsx:33/46`（数据域卡片）——页面局部。

## C2. 择校模块 Tab 一致性（P1-4）—— 已完成

- `navConfig.js:45-57` school 组共 **11 项**：择校中心(/kaoyan)、通知中心(/kaoyan/notices)、院校库(/kaoyan/schools)、院校对比(/kaoyan/compare)、智能择校(/kaoyan/recommend)、区域热力图(/kaoyan/map)、招生散点图(/kaoyan/scatter)、成长体系(/kaoyan/growth)、分数线数据(/kaoyan/analysis)、考研规划(/kaoyan/plan)、**择校 AI 问答(/kaoyan/assistant)**(:56)。
- `navConfig.js:143`：`KAOYAN_TABS = MODULES.find((m) => m.key === 'school').items.map(...)` —— KAOYAN_TABS 共 11 项，由 school 组直接派生。
- TopNav「择校」下拉：`TopNav.jsx:81` 直接渲染 `module.items`，即同一数组 → **两清单同源，天然一致（11 = 11）**。注释 `navConfig.js:59`「择校模块内 Tab：与顶栏『择校』下拉同源」。
- 择校 AI 问答指向：navConfig.js:56 → `/kaoyan/assistant`（**不再是 /assistant?scene=kaoyan**）。路由 `App.jsx:206` `<Route path="assistant" element={<KaoyanAssistant />} />`，其注释(:203-205)明确记载：此前重定向 `/assistant?scene=kaoyan`，但 Assistant.jsx 不读查询参数、scene 意图被静默丢弃，故恢复直连。
- Tab 条渲染：`App.jsx:83-91` KaoyanModuleLayout 用 `KAOYAN_TABS` 作 Segmented options（最长前缀匹配高亮，:80-82）。
- 测试：`test/navConfig.test.jsx:65` 断言 KAOYAN_TABS 与 school 组 items 相等。

## C3. 管理端 IA（P1-3）—— 已完成

/admin/* 全部子路由（`App.jsx:209-223`，整段包在 `<RequireAdmin><AdminLayout /></RequireAdmin>` 内）：

```
/admin            index → Navigate to "overview"（:210）
/admin/overview   DataCenter（:211）
/admin/users      UserAdmin（:214）
/admin/subjects   SubjectManager（:215）
/admin/quiz-bank  QuizBank（:216）
/admin/quality    QualityDashboard（:218）
/admin/schools    KaoyanImport（:220）
/admin/crawl-sources  KaoyanCrawlSources（:221）
/admin/kb-import  KnowledgeBaseImport（:222）
/admin/model      ModelTraining（:222 后 :223 前）
/admin/*          Navigate to "overview"（:223 通配）
```

旧路径重定向：`navConfig.js:69-81` NAV_ADMIN 每项带 `legacy` 字段，:83 `ADMIN_LEGACY_REDIRECTS = NAV_ADMIN.map((e) => [e.legacy, e.to])`。九条映射：

- `/data-center → /admin/overview`(:70)、`/users → /admin/users`(:73)、`/subjects → /admin/subjects`(:74)、`/quiz-bank → /admin/quiz-bank`(:75)、`/quality → /admin/quality`(:76)、`/kaoyan/import → /admin/schools`(:77)、`/crawl-sources → /admin/crawl-sources`(:78)、`/kb-import → /admin/kb-import`(:79)、`/model-training → /admin/model`(:80)

审计点名的 8 条（/data-center、/quiz-bank、/subjects、/quality、/crawl-sources、/model-training、/kb-import、/kaoyan/import）**全部在列**，另有 /users。挂载：`App.jsx:225-227` `{ADMIN_LEGACY_REDIRECTS.map(([from, to]) => <Route key={from} path={from} element={<LegacyRedirect to={to} />} />)}`；`App.jsx:69-72` LegacyRedirect 保留 search+hash（「旧书签与外链不丢参数」）。

管理端侧栏：`AdminLayout.jsx:9-20` `<aside className="admin-side">` 内 `NAV_ADMIN.map(...)` 渲染侧栏菜单（含 label+desc），头部有「返回学习端」链接(:12)。

顶栏按角色显示管理入口：`TopNav.jsx:87` `{isAdmin && <NavLink to={ADMIN_ROOT}...管理后台</NavLink>}`；守卫 `auth/AuthContext.jsx:109-112` RequireAdmin 非管理员 `<Navigate to="/403" replace />`；测试 `test/auth.guard.test.jsx:68-78`（普通用户→403、管理员可进）。

## C4. 仪表盘四态与自愈（P1-1）—— 部分完成

自愈链路已实现（`pages/Dashboard.jsx`）：

- 唯一请求：`Dashboard.jsx:170`（注释 :162-165）首屏只打 `dashboardApi.summary()` = GET /api/dashboard/summary。
- 指数退避重试：`:181-190` catch 里 `setStatus('error')`；`:184` `if (state.attempt >= 5) return`（重试上限 5 次）；`:185` `const delay = 1000 * (2 ** state.attempt)`（1/2/4/8/16s）；`:186` 首次失败 toast「实时数据加载失败，正在自动重试…」；:186-188 setTimeout 递归重载。注释 :166-168「失败自动重试（1/2/4/8/16s，最多 5 次）……恢复后自动隐藏降级提示」。
- 恢复自动清除：`:177-179` 成功 → `setStatus('ok')` + `attempt = 0`；橙条 `:1056-1061` `{status === 'error' && <div className="dash-error">…<button onClick={loadAll}>重试</button></div>}` 条件渲染，status 翻回 ok 即消失（误报橙条的「冷启动停留」已被重试+自动清除覆盖）。
- autoRefresh 默认值：`:151-153` `localStorage.getItem(DASH_AUTOREFRESH_KEY) === '1'` → **默认 false（关）**；`:196` 开启时 `setInterval(loadAll, 30000)`，与重试解耦（:168 注释）。

状态区分 —— 顶层三态而非四态：

- `:135` `const [status, setStatus] = useState('loading') // loading | ok | error`。**没有独立「部分数据缺失」顶层状态值**。
- 后端不可达 → status='error'：就地橙条 + 本地缓存降级（:1055 注释「就地提示 + 本地缓存降级」）。
- 部分数据缺失 → 在 ok 内做**字段级降级**：`:274` `queueSource = queue ? (queue.source || 'review_scheduler') : 'local'`，`:543` 副标题「后端队列不可达 · 本机估算」；kpi 缺失时 KPI 条不渲染（`kpi = live?.kpi`）；progress 环区分 no_target/not_tracked；热力图 levels 缺失降级「有活动即一级」（:371-376）。
- 真为空 → 各分区 `Empty` 组件：:1191（未配置考研目标）、:1207（暂无到期安排）、:1311（今日暂无任务）、:1341（暂无待复习内容）、:1373（暂无趋势数据）、:1392（还没有学习日历）、:1476（今天还没有学习记录）。

判定：重试/上限/恢复清除/autoRefresh 默认关均已完成；「四态」中的「部分数据缺失」以字段级降级表达、无独立顶层态，故计「部分完成」（是否达标取决于验收口径把四态定义在哪一层）。

## C5. 文档计数口径（P1-6）—— 部分完成（数值口径已一致，但仍是三个端点各自 COUNT，未收敛为单一聚合）

三处各自的链路：

1. **/api/health**：`backend-main-fastapi/main.py:309-326` → `kb = kb_health_snapshot()`，返回体含 `"kb": kb`。`services/health_service.py:238-243` `_probe_tables` 对 `KEY_TABLES`(:25-36，含 documents「文档」、knowledge_chunks「知识分块」)逐表 `_count`；:105-107 `SELECT COUNT(*) FROM "<table>"`（raw SQL，全表）。前端消费：`KbHealthPanel.jsx:73` `sys = useApiData(() => systemApi.health())`，:24 `const tables = kb.tables || {}`，:25-27 渲染 `${t.label} ${t.rows}`；面板挂载于 `Documents.jsx:450`。
2. **/documents 页**：`Documents.jsx:89-90` `documentsApi.subjects()` → GET `/api/documents/subjects`（`routers/documents.py:293-343`），:334-341 `doc_total = db.query(Document).count()`、`chunk_total = db.query(KnowledgeChunk).count()` → `total_documents`/`total_chunks`；前端徽标 `Documents.jsx:481` `共 {subjectStats.total_documents} 篇 · {subjectStats.total_chunks} 分块`。
3. **/data-center（/admin/overview）**：`DataCenter.jsx:33-43` `GET /api/kb/health`、`kbApi.health()`，summary 读 `d?.documents?.total` / `d?.chunks?.total`(:37-42)。后端 `routers/kb.py:18` prefix="/api/kb"，:27-30 `/health` → `kb_pipeline.health_report(db)`；`services/kb_pipeline.py:59-60` `total_docs = db.query(func.count(Document.id)).scalar()`、`total_chunks = db.query(func.count(KnowledgeChunk.id)).scalar()`，返回体 :171-172 `"documents": {"total": total_docs, ...}`、:181-182 `"chunks": {"total": total_chunks, ...}`。

结论：三处最终都数同一对表 `documents` / `knowledge_chunks` 的**全表行数（无过滤条件）**，数值口径当前一致（确定，基于上述三段实现）；但它们是**三个独立端点、三条代码路径**（raw SQL text() / ORM `.count()` / ORM `func.count()`），不存在共享的后端聚合函数或字段——「同源（同一聚合/字段）」未实现。风险：任一端点未来加过滤（如只数 index_status='indexed'），三处将再次漂移。2026-10-17 审计所称「三处口径不一」在数值层面已被抹平，在结构层面（单一来源）未收敛。

---

## 待证项 / 建议

1. Dashboard.jsx:38-49 首页宫格 MODULES 与 navConfig MODULES 键不一致（/kbmap vs /knowledge、含 /codebank）：属仪表盘区块而非站点导航，但 UiCustomize 把它列进「全部模块」配置——若目标是「一切入口单一源」，这是最后一个未收敛点。
2. C5 结构性收敛：让 /api/health、/api/documents/subjects、/api/kb/health 复用同一个 count 聚合（如 subject_registry 或新 stats 服务），消掉三条 COUNT 路径。
3. C4 若验收要求「四态」为顶层状态（loading/ok/partial/error），需在 Dashboard 增加 partial 态；当前字段级降级在功能上已覆盖该场景。
4. 未逐条运行测试（只读约束）；`test/navConfig.test.jsx`、`test/auth.guard.test.jsx`、`test/dashboard*` 的断言文本已作为佐证引用，实际通过与否待跑测确认。
