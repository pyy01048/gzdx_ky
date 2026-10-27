# 导航规范（NAV-SPEC）

> 版本 v1.0 · 设计师 颜好看 · 2026-02-19
> 前置阅读：`src/design/design-tokens.json`（令牌源）、`src/styles/tokens.css`
> 实施对象：`src/components/Layout.jsx`（574 行，现为左侧边栏）、`src/App.jsx`（路由表）
> 对标基准：https://gitgraduate.com/academy/pages/math-limits（研码）——纸感学术蓝、导航居中、内容优先

---

## 0. 变更总纲（一句话）

**左侧 `<aside class="sidebar">` 整块拆除 → 改为 64px 高的粘性顶栏，导航组居中排列；科目切换器从「独占一行的横条」改为「顶栏内的可收缩药丸」；33 个页面按去留表合并/降级/删除，路由全部保留重定向，零死链。**

---

## 1. 顶部导航结构

### 1.1 三区布局

```
┌────────────────────────────────────────────────────────────────────────┐
│ [品牌]         今日 ▾  学习 ▾  练习 ▾  复盘 ▾  择校 ▾  设置    [科目▾][搜索][AI][主题] │
│  左区              中间导航区（几何居中）                        右区操作区              │
└────────────────────────────────────────────────────────────────────────┘
   高 64px（桌面） / 56px（移动）  ·  sticky top:0  ·  z-index: var(--z-navbar)=1000
```

- **左区**：品牌标识（方块字标 + 中英文名）。宽度不固定，允许随名字长度伸缩。
- **中区**：6 个导航项，**几何居中**（不是 flex 两端对齐的伪居中）。
- **右区**：科目药丸 → 搜索 → AI 助手 → 主题切换。

### 1.2 导航项清单（中区 6 项，顺序固定）

| # | 标签 | 类型 | 目标 | 说明 |
|---|------|------|------|------|
| 1 | 今日 | 下拉 | `/` | 仪表盘首页。任务打卡/学习计划/学习画像全部收在这里 |
| 2 | 学习 | 下拉 | `/knowledge` | 知识图谱（合并后）为模块主页 |
| 3 | 练习 | 下拉 | `/quiz` | 刷题为主入口 |
| 4 | 复盘 | 下拉 | `/error-review` | 错题复盘 |
| 5 | 择校 | 下拉 | `/kaoyan` | 择校中心 |
| 6 | 设置 | **单列** | `/settings` | 用户明确要求单列；科目管理并入此处 |

> 用户诉求对齐记录：
> - "导航栏放在最顶上面而不是置于左边" → §1.1 三区顶栏
> - "整个网站项目的导航页做成这种放在中间上方的" → §2 居中方案（对标站同构）
> - "主要导航栏可以下拉列表的" → 1–5 全部为下拉
> - "设置单列" → 第 6 项无下拉，直接跳转
> - "仪表盘作为首页…任务打卡、学习计划、学习画像全部划归仪表盘" → 第 1 项下拉内含这三个子入口

### 1.3 下拉项明细

**今日 ▾**（模块主页 `/`）
| 路由 | 标签 | 说明 |
|---|---|---|
| `/` | 仪表盘总览 | 首页四区块：今日复习队列 / 任务打卡 / 学习计划 / 学习画像 |
| `/tasks` | 任务打卡 | 保留路由，降为仪表盘子视图 |
| `/planner` | 学习计划 | 保留路由，降为仪表盘子视图 |
| `/profile` | 学习画像 | 保留路由，降为仪表盘子视图 |

**学习 ▾**（模块主页 `/knowledge`）
| 路由 | 标签 | 说明 |
|---|---|---|
| `/knowledge` | 知识图谱 | **新路由**：合并原 /kbmap + /panorama |
| `/library` | 学习文库 | |
| `/documents` | 文档知识库 | |
| `/pan` | 网盘联动 | |

**练习 ▾**（模块主页 `/quiz`）
| 路由 | 标签 | 说明 |
|---|---|---|
| `/quiz` | 刷题中心 | |
| `/quiz-bank` | 题库管理 | |
| `/cards` | 记忆卡片 | |
| `/words` | 单词记忆 | |
| `/codebank` | 复试代码题库 | |

**复盘 ▾**（模块主页 `/error-review`）
| 路由 | 标签 |
|---|---|
| `/error-review` | 错题复盘 |
| `/notebook` | 错题本 |

**择校 ▾**（模块主页 `/kaoyan`，12 → 7 项瘦身）
| 路由 | 标签 | 说明 |
|---|---|---|
| `/kaoyan` | 择校中心 | |
| `/kaoyan/schools` | 院校库 | 分数分析作为其页内 Tab 嵌入 |
| `/kaoyan/compare` | 院校对比 | |
| `/kaoyan/recommend` | 智能择校 | |
| `/kaoyan/notices` | 通知中心 | 模块标题带未读角标 |
| `/kaoyan/growth` | 成长体系 | |
| `/kaoyan/map` | 区域分布 | 合并原 scatter，页内 `?view=` 切换 |

**右区 AI 助手**：`/assistant`（带图标 + 文字按钮，非纯图标，保证可发现性）。原 `/kaoyan/assistant` 合并为 `/assistant?scene=kaoyan`。

### 1.4 可直接使用的配置对象（前端照抄）

写入 `src/components/navConfig.js`，`Layout.jsx` 与 `CommandPalette.jsx` 共用一份，避免两处漂移：

```js
// src/components/navConfig.js
// 单一导航源：Layout 顶栏、命令面板、移动端「更多」面板都从这里读，避免三处各写一份。
import { Home, Map, Book, FileText, Target, Settings, MessageSquare } from './Icon'

export const NAV_GROUPS = [
  {
    key: 'home', title: '今日', icon: Home, defaultTo: '/',
    items: [
      { to: '/', label: '仪表盘总览', exact: true },
      { to: '/tasks', label: '任务打卡' },
      { to: '/planner', label: '学习计划' },
      { to: '/profile', label: '学习画像' },
    ],
  },
  {
    key: 'learn', title: '学习', icon: Map, defaultTo: '/knowledge',
    items: [
      { to: '/knowledge', label: '知识图谱' },
      { to: '/library', label: '学习文库' },
      { to: '/documents', label: '文档知识库' },
      { to: '/pan', label: '网盘联动' },
    ],
  },
  {
    key: 'practice', title: '练习', icon: Book, defaultTo: '/quiz',
    items: [
      { to: '/quiz', label: '刷题中心' },
      { to: '/quiz-bank', label: '题库管理' },
      { to: '/cards', label: '记忆卡片' },
      { to: '/words', label: '单词记忆' },
      { to: '/codebank', label: '复试代码题库' },
    ],
  },
  {
    key: 'review', title: '复盘', icon: FileText, defaultTo: '/error-review',
    items: [
      { to: '/error-review', label: '错题复盘' },
      { to: '/notebook', label: '错题本' },
    ],
  },
  {
    key: 'kaoyan', title: '择校', icon: Target, defaultTo: '/kaoyan',
    badge: true, // 通知未读角标挂这里
    items: [
      { to: '/kaoyan', label: '择校中心', exact: true },
      { to: '/kaoyan/schools', label: '院校库' },
      { to: '/kaoyan/compare', label: '院校对比' },
      { to: '/kaoyan/recommend', label: '智能择校' },
      { to: '/kaoyan/notices', label: '通知中心' },
      { to: '/kaoyan/growth', label: '成长体系' },
      { to: '/kaoyan/map', label: '区域分布' },
    ],
  },
]

/** 单列项：直接跳转，不带下拉 */
export const NAV_SINGLE = [
  { to: '/settings', label: '设置', icon: Settings },
]

/** 右区动作 */
export const NAV_ACTIONS = [
  { key: 'assistant', to: '/assistant', label: 'AI 助手', icon: MessageSquare },
]
```

### 1.5 下拉交互规则（可访问性）

| 规则 | 规格 |
|---|---|
| 触发 | hover 进入 120ms 后展开；click / Enter / Space 也能开合（**不可只依赖 hover**） |
| 关闭 | Esc 关闭并把焦点还给触发按钮；点击面板外关闭；路由变化关闭 |
| 键盘 | ↓ 打开并聚焦首项；↑↓ 循环移动；Tab 移出即关闭 |
| ARIA | 触发按钮 `aria-expanded` `aria-haspopup="true"` `aria-controls`；面板 `role="menu"`；行 `role="menuitem"` |
| 焦点环 | 行聚焦用 `box-shadow: var(--focus-ring-shadow)`，禁止 `outline: none` 单独出现 |
| 动效 | 展开 `var(--motion-fast)`(150ms) opacity + translateY(4px)，缓动 `var(--ease-standard)`；**禁止弹跳缓动** |
| hover 桥 | 面板顶部留 8px 透明 `padding-top`，防止鼠标从按钮移到面板途中丢失 hover |

---

## 2. 居中布局 CSS 方案

### 2.1 为什么用 Grid `1fr auto 1fr` 而不是 Flex `space-between`

`justify-content: space-between` 只在左右两区宽度**完全相等**时才把中间块放到几何中心。左区品牌（约 140px）和右区动作组（约 260px）宽度不等 → 导航组会明显偏左，左右两侧留白不对称，看上去像没对齐。

Grid 三列 `1fr auto 1fr` 让左右两个弹性列**强制等宽**，中间列取内容宽度，无论左右内容怎么变，导航组永远落在视口几何中心。

### 2.2 完整样式（写入 `src/styles/nav.css`，由 Layout 引入）

```css
/* ---------- 顶栏容器 ---------- */
.topbar {
  position: sticky;
  top: 0;
  z-index: var(--z-navbar);
  height: var(--nav-h);
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  /* 下滚时压到 --nav-h-scroll 并加浅阴影，滚动方向由 JS 加 .is-scrolled */
  transition: height var(--motion-fast) var(--ease-standard),
              box-shadow var(--motion-fast) var(--ease-standard);
}
.topbar.is-scrolled {
  height: var(--nav-h-scroll);
  box-shadow: var(--shadow-sm);
}

/* 三区栅格：左右两列强制等宽 → 中间列几何居中 */
.topbar-inner {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: var(--space-6);
  max-width: var(--container-max);
  height: 100%;
  margin-inline: auto;
  padding-inline: var(--container-gutter);
}

/* ---------- 左区：品牌 ---------- */
.topbar-brand {
  justify-self: start;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;              /* 允许在空间不足时被压缩，避免撑破栅格 */
  color: var(--fg);
  text-decoration: none;
}
.topbar-brand .brand-mark {
  width: 32px; height: 32px;
  display: grid; place-items: center;
  border-radius: var(--radius-md);
  background: var(--accent-solid);
  color: var(--accent-on);
  font-weight: var(--fw-semibold);
  font-size: var(--text-md);
  flex: none;
}
.topbar-brand .brand-name {
  font-size: var(--text-md);
  font-weight: var(--fw-semibold);
  letter-spacing: var(--tracking-tight);
  white-space: nowrap;
}
.topbar-brand .brand-sub {
  font-size: var(--text-xs);
  color: var(--meta);
  letter-spacing: var(--tracking-caps);   /* 全大写英文，字距必须 >=0.06em */
  white-space: nowrap;
}

/* ---------- 中区：导航（几何居中） ---------- */
.topbar-nav {
  justify-self: center;
  display: flex;
  align-items: center;
  gap: var(--nav-item-gap);
  min-width: 0;
}
.nav-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: var(--nav-item-h);
  padding-inline: var(--nav-item-pad-x);
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--fg-2);
  font-family: inherit;
  font-size: var(--text-base);
  font-weight: var(--fw-medium);
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--motion-fast) var(--ease-standard),
              color var(--motion-fast) var(--ease-standard);
}
.nav-item:hover { background: var(--surface-2); color: var(--fg); }
.nav-item.is-active { color: var(--accent); font-weight: var(--fw-semibold); }
/* 当前模块指示：2px 下划线压在栏底，不用左边框（禁用「彩色左边框」反模式） */
.nav-item.is-active::after {
  content: '';
  position: absolute;
  left: var(--nav-item-pad-x);
  right: var(--nav-item-pad-x);
  bottom: -1px;
  height: 2px;
  border-radius: 1px;
  background: var(--accent);
}
.nav-item { position: relative; }
.nav-item .caret { transition: transform var(--motion-fast) var(--ease-standard); }
.nav-item[aria-expanded='true'] .caret { transform: rotate(180deg); }

/* ---------- 右区：动作 ---------- */
.topbar-actions {
  justify-self: end;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* ---------- 下拉面板 ---------- */
.nav-dd { position: relative; display: inline-flex; }
.nav-dd-panel {
  position: absolute;
  top: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  /* 顶部 8px 透明桥：鼠标从按钮移到面板途中不丢 hover */
  padding-top: 8px;
  z-index: var(--z-dropdown);
}
.nav-dd-menu {
  width: var(--nav-dd-w);
  padding: var(--nav-dd-pad);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-md);
}
.nav-row {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;  /* 图标 | 文字 | 元信息 */
  align-items: center;
  gap: var(--nav-row-gap);
  min-height: var(--nav-row-h);
  padding-inline: var(--nav-row-pad-x);
  border-radius: var(--radius-md);
  color: var(--fg);
  font-size: var(--text-base);
  line-height: var(--lh-base);
  text-decoration: none;
}
.nav-row:hover { background: var(--surface-2); }
.nav-row.is-active { color: var(--accent); font-weight: var(--fw-semibold); }
.nav-row.is-active .nav-row-icon { color: var(--accent); }
.nav-row-icon { width: 20px; color: var(--fg-2); text-align: center; }
.nav-row-meta {
  justify-self: end;
  font-size: var(--text-sm);
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.nav-dd-sep { height: 1px; margin: var(--space-1) 0; background: var(--border-soft); }

/* ---------- 主内容：顶栏让位 ---------- */
.app-shell { min-height: 100%; }
.main-area {
  max-width: var(--container-max);
  margin-inline: auto;
  padding-inline: var(--container-gutter);
  padding-top: var(--page-top);
  padding-bottom: var(--page-bottom);
}
/* 宽表页（院校库 / 题库管理 / 知识图谱全量视图）用加宽容器 */
.main-area.is-wide { max-width: var(--container-wide); }
/* 长文阅读页（文档 / 讲义）限宽，保证 38 汉字/行 */
.main-area.is-prose { max-width: var(--container-prose); }
```

### 2.3 各断点行为

| 断点 | 顶栏高度 | 中区导航 | 右区 |
|---|---|---|---|
| ≥1200px | 64px | 6 项全展示，gap 4px，字号 14px | 科目药丸 + 搜索 + AI + 主题 |
| 900–1199px | 64px | 6 项全展示，gap 2px，导航项 `padding-inline: 8px` | 同上 |
| 768–899px | 56px | 前 4 项 + 「更多 ▾」收纳后 2 项 | 科目药丸 + 搜索 + 主题（AI 助手收进「更多」） |
| <768px | 56px | **隐藏**。品牌 + 右区；导航走底部 TabBar（≤5 项），「更多」按钮开底部 ActionSheet 展示全量 | 科目药丸 + 搜索 + 主题 |

移动端底部 TabBar（沿用现有 `BOTTOM_NAV`，裁到 5 项）：
`今日 /` · `学习 /knowledge` · `练习 /quiz` · `复盘 /error-review` · `我的 /settings`

```css
/* 移动端隐藏中区导航，桌面隐藏底部 TabBar —— 两者互斥，不重复占位 */
@media (max-width: 767px) {
  .topbar-nav { display: none; }
}
@media (min-width: 768px) {
  .bottom-nav { display: none; }
}
```

---

## 3. 页面去留决策表（pages/ 下 33 个 .jsx 逐页列全）

> 图例：**保留** = 维持独立页面 ；**合并** = 内容迁入他页、原路由重定向；**降级** = 页面还在但移出主导航；**删除** = 下线
> 实测：`src/pages/` 下共 **33 个 .jsx**（非 38；另 8 个页面级 .css）。全部 33 个均已列入下表，无一遗漏。

| # | 文件 | 现路由 | 决策 | 新位置 / 新路由 | 理由 |
|---|---|---|---|---|---|
| 1 | `Dashboard.jsx` | `/` | **保留**（升级） | `/` 首页 | 用户要求仪表盘为首页，含今日复习队列/任务打卡/学习计划/学习画像四区块 |
| 2 | `Tasks.jsx` | `/tasks` | **降级** | `今日 ▾` 子项，路由保留 | 内容并入仪表盘「任务打卡」区块；保留路由避免死链 |
| 3 | `Planner.jsx` | `/planner` | **降级** | `今日 ▾` 子项，路由保留 | 并入仪表盘「学习计划」区块；同时承接原考研规划 |
| 4 | `LearnerProfile.jsx` | `/profile` | **降级** | `今日 ▾` 子项，路由保留 | 并入仪表盘「学习画像」区块 |
| 5 | `KbMap.jsx` | `/kbmap` | **合并**（主体） | `/knowledge` | 与 Panorama 同为 1067 知识点、掌握度全 0%，高度重复 → 合并为「知识图谱」，KbMap 的关系图为主体 |
| 6 | `Panorama.jsx` | `/panorama` | **合并** | `/knowledge?view=panorama` | 其「科目→章节→知识点一屏纵览」作为知识图谱的默认纵览视图保留 |
| 7 | `Library.jsx` | `/library` | **保留** | `学习 ▾` | 学习文库模块主页 |
| 8 | `Documents.jsx` | `/documents` | **保留** | `学习 ▾` | 文档知识库 |
| 9 | `Pan.jsx` | `/pan` | **保留** | `学习 ▾` | 网盘联动 |
| 10 | `Quiz.jsx` | `/quiz` | **保留** | `练习 ▾`（模块主页） | 刷题中心 |
| 11 | `QuizBank.jsx` | `/quiz-bank` | **保留** | `练习 ▾` | 题库管理 |
| 12 | `Cards.jsx` | `/cards` | **保留** | `练习 ▾` | 记忆卡片 |
| 13 | `Words.jsx` | `/words` | **保留** | `练习 ▾` | 单词记忆 |
| 14 | `CodeBank.jsx` | `/codebank` | **保留** | `练习 ▾` | 复试代码题库 |
| 15 | `ErrorReview.jsx` | `/error-review` | **保留** | `复盘 ▾`（模块主页） | 错题复盘 |
| 16 | `Notebook.jsx` | `/notebook` | **保留** | `复盘 ▾` | 错题本 |
| 17 | `KaoyanGuide.jsx` | `/kaoyan` | **保留** | `择校 ▾`（模块主页） | 择校中心 |
| 18 | `KaoyanSchools.jsx` | `/kaoyan/schools` | **保留**（扩容） | `择校 ▾` | 院校库；承接分数分析 Tab |
| 19 | `KaoyanSchoolDetail.jsx` | `/kaoyan/schools/:id` | **保留** | 详情页（不进导航） | 由院校库下钻，详情页不应出现在导航里 |
| 20 | `KaoyanCompare.jsx` | `/kaoyan/compare` | **保留** | `择校 ▾` | 院校对比，功能独立 |
| 21 | `KaoyanRecommend.jsx` | `/kaoyan/recommend` | **保留** | `择校 ▾` | 智能择校 |
| 22 | `NoticeCenter.jsx` | `/kaoyan/notices` | **保留** | `择校 ▾`（带未读角标） | 通知中心 |
| 23 | `GrowthPage.jsx` | `/kaoyan/growth` | **保留** | `择校 ▾` | 成长体系 |
| 24 | `KaoyanMap.jsx` | `/kaoyan/map` | **保留**（扩容） | `择校 ▾` → 标签改为「区域分布」 | 承接 scatter，页内 `?view=map/scatter` 切换 |
| 25 | `KaoyanScatter.jsx` | `/kaoyan/scatter` | **合并** | `/kaoyan/map?view=scatter` | 与区域热力图同属「招生地理/分布」图表，两页各自只能看一种图 → 合并成一页两视图 |
| 26 | `KaoyanAnalysis.jsx` | `/kaoyan/analysis` | **降级** | `/kaoyan/schools?tab=score` | 分数分析的客体就是院校，独立成页导致「先看院校再跳转看分数」的割裂 → 降为院校库页内 Tab |
| 27 | `KaoyanPlan.jsx`→`PlanPage.jsx` | `/kaoyan/plan` | **合并** | `/planner?scope=kaoyan` | 「考研规划」与「学习计划」语义重叠，都在排期 → 并入学习计划页的一个分区 |
| 28 | `KaoyanAssistant.jsx` | `/kaoyan/assistant` | **合并** | `/assistant?scene=kaoyan` | 与通用 AI 助手是同一套对话能力，只是预设了择校语料 → 用场景参数区分，不再单独占一页 |
| 29 | `KaoyanImport.jsx` | `/kaoyan/import` | **迁移** | `/settings?tab=data` | 数据导入是低频运维动作，不该占择校导航 → 迁到设置页「数据与导入」分区 |
| 30 | `QualityDashboard.jsx` | `/quality` | **迁移** | `/settings?tab=quality` | 评测与数据质量同属运维视图，日复习流程用不到 → 迁到设置页 |
| 31 | `Assistant.jsx` | `/assistant` | **保留** | 右区动作按钮 | 通用 AI 助手 |
| 32 | `Settings.jsx` | `/settings` | **保留**（扩容，单列） | 中区第 6 项，单列无下拉 | 承接科目管理 + 数据导入 + 数据质量，共 3 个新增分区 |
| 33 | `SubjectManager.jsx` | `/subjects` | **并入设置** | `/settings?tab=subjects` | 用户明确要求「科目管理并入设置页」 |

### 3.1 用户点名的三个冗余页（逐条销账）

| 用户原话 | 处置 | 落地方式 |
|---|---|---|
| 考频分析（`/exam-frequency`） | **删除** | 路由表已有 `<Navigate to="/panorama">`，随 panorama 合并改为 `<Navigate to="/knowledge" replace />`；`App.jsx` 中不再 import 任何 ExamFrequency 组件（当前已无该页面文件，只需把重定向目标改对） |
| 题目分析（`/analysis`） | **删除** | 路由表已有 `<Navigate to="/" replace />`，保留（防止历史书签 404）；确认无组件引用 |
| 历史讲义 | **删除** | 它是原 Analysis 页内的一个区块，随 `/analysis` 整体下线；无独立路由 |

### 3.2 删除清单（确认无引用后可物理删文件）

- `src/pages/Panorama.jsx` → 内容迁 `KbMap.jsx` 的 `view=panorama` 分支（合并完成后删）
- `src/pages/KaoyanScatter.jsx` → 迁 `KaoyanMap.jsx` 的 `view=scatter` 分支（合并完成后删）
- `src/pages/PlanPage.jsx` → 迁 `Planner.jsx` 的 `scope=kaoyan` 分区（合并完成后删）
- `src/pages/KaoyanAssistant.jsx` → 迁 `Assistant.jsx` 的 `scene=kaoyan` 预设（合并完成后删）
- `src/pages/SubjectManager.jsx` → 迁 `Settings.jsx` 的「备考科目」Tab（合并完成后删）
- `src/pages/KaoyanImport.jsx` → 迁 `Settings.jsx` 的「数据与导入」Tab（合并完成后删）
- `src/pages/QualityDashboard.jsx` → 迁 `Settings.jsx` 的「数据质量」Tab（合并完成后删）
- `src/pages/KaoyanAnalysis.jsx` → 迁 `KaoyanSchools.jsx` 的「分数分析」Tab（合并完成后删）

> 删除前置条件（门禁）：`grep -rn "Panorama\|KaoyanScatter\|PlanPage\|KaoyanAssistant\|SubjectManager\|KaoyanImport\|QualityDashboard\|KaoyanAnalysis" src/ --include=*.jsx --include=*.js` 除重定向目标外应为 0 命中。

### 3.3 净效果

| 指标 | 改前 | 改后 |
|---|---|---|
| 独立页面文件 | 33 | **26** |
| 主导航一级入口 | 7 个分组（侧边栏，含 3 个单页分组） | **6 项中栏**（5 下拉 + 1 单列） |
| 择校模块下拉项 | 12 | **7** |
| 顶部科目切换器占高 | 约 88px（head 40 + chip 48） | **0**（并入 64px 顶栏） |
| 侧边栏占宽 | 248px | **0** |

---

## 4. 路由映射表（旧 → 新，含重定向策略）

> 全部用 `<Navigate to="..." replace />`，保证历史书签/分享链接不 404，且不污染后退栈。
> `App.jsx` 的懒加载 import 同步增删。

| 旧路由 | 新路由 | 策略 | 备注 |
|---|---|---|---|
| `/kbmap` | `/knowledge` | 主路由改名 | KbMap.jsx 保留文件，路由改名 |
| `/panorama` | `/knowledge?view=panorama` | `<Navigate replace>` | 合并 |
| `/exam-frequency` | `/knowledge` | `<Navigate replace>` | **原指向 /panorama，随合并改指** |
| `/analysis` | `/` | `<Navigate replace>` | 保留既有（冗余页下线） |
| `/errors` | `/error-review` | `<Navigate replace>` | 保留既有 |
| `/cuoti` | `/error-review` | `<Navigate replace>` | 保留既有 |
| `/subjects` | `/settings?tab=subjects` | `<Navigate replace>` | 用户要求并入设置 |
| `/quality` | `/settings?tab=quality` | `<Navigate replace>` | 运维视图迁设置 |
| `/kaoyan/import` | `/settings?tab=data` | `<Navigate replace>` | 运维视图迁设置 |
| `/kaoyan/assistant` | `/assistant?scene=kaoyan` | `<Navigate replace>` | 合并入通用 AI |
| `/kaoyan/plan` | `/planner?scope=kaoyan` | `<Navigate replace>` | 合并入学习计划 |
| `/kaoyan/scatter` | `/kaoyan/map?view=scatter` | `<Navigate replace>` | 合并入区域分布 |
| `/kaoyan/analysis` | `/kaoyan/schools?tab=score` | `<Navigate replace>` | 降级为院校库 Tab |
| `/kaoyan/guide` | `/kaoyan` | `<Navigate replace>` | 消除同页双路由 |
| `/` | `/` | 不变 | 仪表盘首页 |
| `/tasks` `/planner` `/profile` | 不变 | 不变 | 仅导航层级降级，路由保留 |
| `/library` `/documents` `/pan` | 不变 | 不变 | |
| `/quiz` `/quiz-bank` `/cards` `/words` `/codebank` | 不变 | 不变 | |
| `/error-review` `/notebook` | 不变 | 不变 | |
| `/assistant` | 不变 | 不变 | 新增 `?scene=` 参数 |
| `/settings` | 不变 | 不变 | 新增 `?tab=` 参数 |
| `/kaoyan` `/kaoyan/schools` `/kaoyan/schools/:id` `/kaoyan/compare` `/kaoyan/recommend` `/kaoyan/notices` `/kaoyan/growth` `/kaoyan/map` | 不变 | 不变 | |
| `*` | `/` | `<Navigate replace>` | 兜底 |

### 4.1 App.jsx 片段（照抄）

```jsx
{/* —— 新增：知识图谱（合并原 /kbmap + /panorama）—— */}
<Route path="/knowledge" element={<Knowledge />} />
{/* —— 旧路由全部保留重定向，零死链 —— */}
<Route path="/kbmap" element={<Navigate to="/knowledge" replace />} />
<Route path="/panorama" element={<Navigate to="/knowledge?view=panorama" replace />} />
<Route path="/exam-frequency" element={<Navigate to="/knowledge" replace />} />
<Route path="/analysis" element={<Navigate to="/" replace />} />
<Route path="/errors" element={<Navigate to="/error-review" replace />} />
<Route path="/cuoti" element={<Navigate to="/error-review" replace />} />
<Route path="/subjects" element={<Navigate to="/settings?tab=subjects" replace />} />
<Route path="/quality" element={<Navigate to="/settings?tab=quality" replace />} />
<Route path="/kaoyan/import" element={<Navigate to="/settings?tab=data" replace />} />
<Route path="/kaoyan/assistant" element={<Navigate to="/assistant?scene=kaoyan" replace />} />
<Route path="/kaoyan/plan" element={<Navigate to="/planner?scope=kaoyan" replace />} />
<Route path="/kaoyan/scatter" element={<Navigate to="/kaoyan/map?view=scatter" replace />} />
<Route path="/kaoyan/analysis" element={<Navigate to="/kaoyan/schools?tab=score" replace />} />
<Route path="/kaoyan/guide" element={<Navigate to="/kaoyan" replace />} />
```

> `?view=` / `?tab=` / `?scene=` / `?scope=` 由页面用 `useSearchParams()` 读取，
> 不新增路由层级——这样合并后的页面仍是一个组件、一个懒加载块，首屏体积不增。

---

## 5. 科目切换器规范（收缩态 / 展开态）

### 5.1 核心改动：从「占一行的横条」改为「顶栏内的药丸」

用户原话："顶部的科目选择就不能收缩按钮这样就不会占用空间了"。
现有实现（`SubjectSwitcher.jsx`）即便 `collapsed`，头部 `sb-head` 仍占约 40px 高的一整行——**收了等于没收**。

新方案：把控件本体塞进 64px 顶栏的右区，垂直占用 **0px**。

| 维度 | 旧 | 新 |
|---|---|---|
| 位置 | 主内容区顶部，独占一行 | 顶栏右区第一个 |
| 收缩态占高 | ~40px | **0**（与顶栏共用 64px） |
| 展开态占高 | +48px（撑开主内容） | **0**（浮层，不推挤内容） |
| 触达路径 | 需先滚动到顶部 | 顶栏 sticky，任何滚动位置都在 |

### 5.2 收缩态（默认）

```
┌──────────────────────┐
│ ◎ 高等数学        ⌄ │   ← 32px 高药丸
└──────────────────────┘
```

| 属性 | 值 |
|---|---|
| 高度 | `var(--subject-pill-h)` = 32px |
| 最大宽度 | `var(--subject-pill-maxw)` = 176px，超出 `text-overflow: ellipsis` |
| 圆角 | `var(--radius-full)` |
| 背景 / 描边 | `var(--surface-2)` / `1px solid var(--border)` |
| 内边距 | `0 var(--space-3)`（12px） |
| 间隙 | 图标 ↔ 文字 → 文字 ↔ 箭头 各 `var(--space-1)`(4px) |
| 图标 | `Target`，`size={16}`（取自 `Icon.jsx`，**不引入第二套图标库**） |
| 箭头 | `ChevronDown`，`size={16}`，展开时 `rotate(180deg)`，150ms |
| 无科目时文案 | 「全部科目」（不是空占位） |
| 无障碍 | `aria-haspopup="listbox"` `aria-expanded` `aria-label="切换科目，当前：高等数学"` |
| 未配置科目时 | 显示「未设置科目」并给「去设置」入口（跳 `/settings?tab=subjects`），**不显示空洞占位** |

### 5.3 展开态（浮层）

```
                    ┌────────────────────────────┐
                    │ 切换科目                    │  ← 标题行，13px muted
                    ├────────────────────────────┤
                    │ [Check] 全部科目            │
                    │ ◎ 高等数学                  │  ← 当前项 accent + 勾选
                    │ ◎ 线性代数                  │
                    │ ◎ 概率论与数理统计           │
                    │ ◎ 英语（一）                │
                    │ ◎ 政治                      │
                    ├────────────────────────────┤
                    │ [Settings] 管理科目         │  → /settings?tab=subjects
                    └────────────────────────────┘
```

| 属性 | 值 |
|---|---|
| 面板宽度 | `var(--subject-panel-w)` = 240px |
| 定位 | `position: absolute; top: calc(100% + 8px); right: 0;`（右对齐，防溢出视口） |
| 圆角 / 描边 / 阴影 | `var(--radius-lg)` / `1px solid var(--border)` / `var(--shadow-md)` |
| 内边距 | `var(--nav-dd-pad)` = 6px |
| 行规格 | 与导航下拉 `.nav-row` 完全一致：`grid-template-columns: 20px 1fr auto`，行高 `var(--nav-row-h)` |
| 顶部 hover 桥 | `padding-top: 8px` 透明区 |
| 层级 | `var(--z-dropdown)` = 1010 |
| 动效 | `var(--motion-fast)` 150ms，`opacity` + `translateY(4px)`，`var(--ease-standard)` |
| 科目来源 | 仍走 `useSubjectConfig()`（后端 `/api/goals/subjects`），**不硬编码科目** |
| 持久化 | `localStorage['subject_bar_collapsed']`，`'1'` = 收缩（沿用现有 key，用户升级不丢偏好） |

### 5.4 键盘与焦点

| 键 | 行为 |
|---|---|
| Enter / Space | 开合面板；打开时聚焦当前选中项 |
| ↑ / ↓ | 在科目间循环移动 |
| Enter（面板内） | 选中并关闭，焦点回到触发药丸 |
| Esc | 关闭面板，焦点回到触发药丸 |
| Tab | 移出面板即关闭 |

焦点可见性统一用 `box-shadow: var(--focus-ring-shadow)`，**禁止** `outline: none` 单独出现。

### 5.5 实现要点

- 组件名建议 `SubjectPicker.jsx`（`variant="navbar"`），保留原 `SubjectSwitcher.jsx` 的 `COLLAPSE_KEY` 与 `useSubjectConfig` 消费逻辑，只换壳。
- 当前科目被设置页删除时，仍沿用现有回落逻辑：`setCurrentSubject('')` → 显示「全部科目」。
- 选中即写全局 store（`s.currentSubject`），刷题/错题/文档/知识图谱全部联动刷新——这是 `docx/25` 中「科目全局 Store」治理线的落点。

---

## 6. 面包屑与相关功能（保留但降级）

- **面包屑**：顶栏之下保留一行，`首页 / 择校中心 / 当前页`，字号 13px，色 `var(--muted)`，分隔符 `var(--meta)`。首页不显示。
- **相关功能 chips**：用户抱怨页面太杂 → **移除**。相关跳转改由命令面板（Ctrl/⌘+K）承担，减少每页底部固定噪音。
- **后端连接指示**：移到顶栏右区最末（`--z-raised`，4px 圆点，绿=已连/灰=未连，`aria-label` 说明），不再每页底部重复一行。

---

## 7. 实施门禁（Checklist）

- [ ] `src/styles/tokens.css` 在 `main.jsx` 中**最后**导入（在现有 7 个 css 之后）
- [ ] `Layout.jsx` 的 `<aside className="sidebar">` 整块移除，替换为 `.topbar`
- [ ] `global.css:161` 的 `.app-shell { grid-template-columns: 248px 1fr }` 改为 `1fr`
      （该值是**硬编码**的，没有引用 `--side-w`；不改会在左侧留下 248px 空列）
      已备好 `.app-shell.is-topnav { grid-template-columns: 1fr }`（`styles/nav.css`），
      Layout 加 `is-topnav` 类即可，不必直接改 global.css
- [ ] `navConfig.js` 成为单一导航源，CommandPalette 与顶栏共用
- [ ] 33 个页面的路由映射表 100% 落地，旧路由全部 `<Navigate replace>`
- [ ] `grep -rn "sidebar\|side-nav\|nav-mod" src/` 除兼容层外为 0
- [ ] 科目切换器收缩态垂直占用 = 0px（实测 `.subject-bar` 高度不包含在文档流）
- [ ] 键盘可达：Tab 走通 顶栏 6 项 → 右区 4 项 → 主内容；每处焦点可见
- [ ] 顶栏在 1440 / 1024 / 768 / 375 四档实测导航组居中（左区右区留白对称）
- [ ] 无 emoji 图标（正则 `[\x{1F300}-\x{1F9FF}\x{2600}-\x{26FF}\x{2700}-\x{27BF}]` 零命中）
- [ ] 无紫→粉渐变；无弹跳缓动
