# 组件规范（COMPONENT-SPEC）

> 版本 v1.0 · 设计师 颜好看 · 2026-02-19
> 令牌源：`src/design/design-tokens.json` → `src/styles/tokens.css` / `src/styles/tokens.js`
> 图标源：**仅** `src/components/Icon.jsx`（自研 SVG）。禁止引入 lucide / heroicons / ant-design-icons 等第二套图标库
> 图标尺寸：16px 行内 · 20px 按钮内 / 下拉行 · 24px 独立图标

---

## 0. 通用规则（所有组件）

### 0.1 九态矩阵（每个有状态的组件都要覆盖）

| 状态 | 必须 | 规格 |
|---|---|---|
| Default | [必] | 见各组件 |
| Hover | [必] | 背景 `var(--surface-2)` 或边框转 `var(--border-strong)`，`var(--motion-fast)` 150ms |
| Focus | [必] | `:focus-visible` → `box-shadow: var(--focus-ring-shadow)`。**禁止** `outline:none` 单独出现 |
| Active | [必] | 按下：`--accent-active` 填充 / `translateY(0)`，`var(--motion-instant)` 80ms |
| Disabled | [必] | `opacity: .5`（或 `color: var(--meta)` + `background: var(--surface-3)`），`cursor: not-allowed`，`pointer-events` 保留以便 tooltip 说明原因 |
| Loading | [必] | 骨架屏（容器级）/ Spinner + 文案（操作级），按钮 loading 时**禁用但保留原宽度**防跳动 |
| Error | [必] | 文案贴近出错字段，含「怎么修 + 重试」；禁止只在页顶弹一条汇总 |
| Empty | [必] | 一句话说明 + 一个主操作 + 可选图示（SVG，非 emoji） |
| Success | [选] | Toast 或行内短暂提示，`var(--motion-base)` 进场 |

### 0.2 三条硬约束

1. **不硬编码色值** —— 组件样式里只出现 `var(--*)`，唯一例外 `#fff` / `#000`。
2. **不用 emoji 当图标** —— 全部走 `Icon.jsx`，`strokeWidth` 统一 2（继承 IconBase 默认），不混用不同描边粗细。
3. **不用彩色左边框做强调** —— 卡片/列表项的强调走「选中态背景 + 描边转 accent」，不用 `border-left: 3px solid`。

### 0.3 动效总则

| 场景 | 时长令牌 | 值 |
|---|---|---|
| 按下 / 开关 | `--motion-instant` | 80ms |
| hover / 选中 / 下拉 | `--motion-fast` | 150ms |
| Toast / 面板进入 | `--motion-base` | 200ms |
| 模态 / 抽屉 | `--motion-slow` | 280ms |
| 路由切换 | `--motion-page` | 320ms |

缓动统一 `--ease-standard`（`cubic-bezier(.4,0,.2,1)`）。**禁止弹跳缓动**，禁止动画 `width`/`height`（用 `transform`/`opacity` 或 `max-height`）。

---

## 1. 按钮 Button

### 1.1 尺寸

| 规格 | 高度 | 水平内边距 | 字号 | 图标 | 场景 |
|---|---|---|---|---|---|
| `sm` | `--btn-h-sm` 28px | `--btn-pad-x-sm` 10px | 13px | 16px | 表格行内、chip 操作 |
| `md`（默认） | `--btn-h-md` 36px | `--btn-pad-x-md` 14px | 14px | 16px | 表单、工具栏 |
| `lg` | `--btn-h-lg` 44px | `--btn-pad-x-lg` 20px | 16px | 20px | 主 CTA、移动端全宽（= `--touch-min`） |

圆角一律 `var(--radius-md)` 8px；药丸变体用 `var(--radius-full)`。
按钮间距 ≥ `--space-2`(8px)；相邻按钮组用 `--space-2`，分组之间用 `--space-4`。

### 1.2 变体

| 变体 | 背景 | 文字 | 边框 | 用途 |
|---|---|---|---|---|
| Primary | `var(--accent-solid)` | `var(--accent-on)` | 无 | 每页**最多 1 个**。提交、开始练习 |
| Secondary | `var(--surface)` | `var(--accent)` | `1px solid var(--accent-border)` | 次要正动作 |
| Ghost | 透明 → hover `var(--surface-2)` | `var(--fg-2)` | 无 | 取消、收起 |
| Danger | `var(--danger)` | `#fff` | 无 | 删除、清空（需二次确认） |
| Quiet | `var(--surface-2)` | `var(--fg-2)` | 无 | 筛选 chip、批量工具 |

### 1.3 状态

```css
.btn {
  display: inline-flex; align-items: center; justify-content: center;
  gap: var(--space-1);
  height: var(--btn-h-md);
  padding-inline: var(--btn-pad-x-md);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  font-family: inherit;
  font-size: var(--text-base);
  font-weight: var(--fw-medium);
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--motion-fast) var(--ease-standard),
              border-color var(--motion-fast) var(--ease-standard),
              color var(--motion-fast) var(--ease-standard);
}
/* Primary */
.btn--primary { background: var(--accent-solid); color: var(--accent-on); }
.btn--primary:hover { background: var(--accent-hover); }
.btn--primary:active { background: var(--accent-active); }
/* Secondary */
.btn--secondary { background: var(--surface); color: var(--accent); border-color: var(--accent-border); }
.btn--secondary:hover { background: var(--accent-soft); }
/* Ghost */
.btn--ghost { background: transparent; color: var(--fg-2); }
.btn--ghost:hover { background: var(--surface-2); color: var(--fg); }
/* Danger */
.btn--danger { background: var(--danger); color: #fff; }
.btn--danger:hover { background: var(--danger-ink); }

/* Disabled：三种变体共用 */
.btn:disabled, .btn[aria-disabled='true'] {
  opacity: .5; cursor: not-allowed;
  background: var(--surface-3); color: var(--meta); border-color: transparent;
}
/* Loading：保留宽度，只换内容 */
.btn.is-loading { pointer-events: none; }
.btn.is-loading .btn-label { visibility: hidden; }
.btn.is-loading::after {
  content: ''; position: absolute; inset: 0; margin: auto;
  width: 14px; height: 14px; border-radius: var(--radius-full);
  border: 2px solid currentColor; border-top-color: transparent;
  animation: btn-spin 600ms var(--ease-linear) infinite;
}
@keyframes btn-spin { to { transform: rotate(360deg); } }
```

### 1.4 可访问性

- 图标按钮（无文字）必须 `aria-label`。
- Loading 时加 `aria-busy="true"`，并保留原 label 供屏幕阅读器（用 `visibility:hidden` 而非 `display:none`）。
- Danger 操作一律二次确认（模态或行内确认条），不做「点了就删」。
- 触摸目标：桌面 `md` 36px 合规（鼠标）；**移动端所有按钮高度提到 44px**（`--btn-h-lg`）。

---

## 2. 卡片 Card

### 2.1 规格

| 属性 | 值 |
|---|---|
| 内边距 | `--card-pad` 16px（宽松变体 `--card-pad-lg` 20px） |
| 圆角 | `--card-radius` 12px（上限 16px，**禁止 ≥24px**） |
| 背景 | `var(--surface)` |
| 描边 | `1px solid var(--border)` |
| 阴影 | **默认无**（`--shadow-flat`）。只靠 1px 描边分层，避免全站灰蒙蒙 |
| 悬浮态阴影 | `--shadow-md`（仅可点击卡片） |
| 卡片间距 | `--grid-gap` 16px |

> 反模式禁令：卡片不同时出现 `1px solid` 边框 + `blur ≥16px` 阴影（幽灵卡片）；不要用 `border-left: 3px solid var(--accent)` 做强调。

```css
.card {
  padding: var(--card-pad);
  border: 1px solid var(--border);
  border-radius: var(--card-radius);
  background: var(--surface);
  box-shadow: var(--shadow-flat);
}
.card--interactive {
  cursor: pointer;
  transition: border-color var(--motion-fast) var(--ease-standard),
              box-shadow var(--motion-fast) var(--ease-standard),
              transform var(--motion-fast) var(--ease-standard);
}
.card--interactive:hover { border-color: var(--border-strong); box-shadow: var(--shadow-md); }
.card--selected { border-color: var(--accent); background: var(--accent-soft); }

/* 卡片头部：标题 + 右侧动作 */
.card-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.card-title { font-size: var(--text-md); font-weight: var(--fw-semibold); color: var(--fg); }
.card-sub   { font-size: var(--text-sm); color: var(--muted); margin-top: var(--space-1); }
```

### 2.2 卡片内列表行（不用嵌套卡片）

数据密集区（院校库、题库列表）**禁止**「表格外面套卡片、行里再套小卡片」。用 `divide-y` 分隔：

```css
.card-list > li + li { border-top: 1px solid var(--border-soft); }
.card-list > li { padding-block: var(--space-3); }
```

---

## 3. 表格 Table

### 3.1 规格

| 属性 | 值 |
|---|---|
| 表头行高 | `--table-head-h` 40px |
| 数据行高 | `--table-row-h` 44px（密集模式 `--table-row-h-dense` 36px） |
| 单元格水平内边距 | `--table-cell-pad-x` 12px |
| 表头背景 | `var(--surface-2)`；sticky 时 `background` 必须为**不透明**色，否则滚动穿透 |
| 表头文字 | 13px / `--fw-medium` / `var(--fg-2)` |
| 行分隔线 | `1px solid var(--border-soft)` |
| 外框 | `1px solid var(--border)` + `border-radius: var(--radius-lg)`；无阴影 |
| 数字列 | 必加 `class="tabular"`（`font-variant-numeric: tabular-nums`），防刷新跳动 |
| 行 hover | `background: var(--surface-2)` |
| 行选中 | `background: var(--accent-soft)` + 文字 `var(--accent)` |

```css
.table { width: 100%; border-collapse: separate; border-spacing: 0;
         border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden; }
.table thead th {
  position: sticky; top: var(--nav-h); z-index: var(--z-sticky);
  height: var(--table-head-h);
  padding-inline: var(--table-cell-pad-x);
  background: var(--surface-2);
  color: var(--fg-2);
  font-size: var(--text-sm); font-weight: var(--fw-medium);
  text-align: left; white-space: nowrap;
  border-bottom: 1px solid var(--border);
}
.table tbody td {
  height: var(--table-row-h);
  padding-inline: var(--table-cell-pad-x);
  border-bottom: 1px solid var(--border-soft);
  color: var(--fg); font-size: var(--text-sm);
}
.table tbody tr:hover td { background: var(--surface-2); }
.table tbody tr:last-child td { border-bottom: 0; }
.table.is-dense tbody td { height: var(--table-row-h-dense); }
```

### 3.2 响应式

- ≥1024px：全列展示。
- 768–1023px：隐藏次要列（`data-col="optional"`），保留主键 + 2 个关键指标。
- <768px：**转卡片列表**，不横向滚动（横向滚动表格在手机上无法使用）。每行渲染为一张 16px 内边距的卡片，字段用「标签: 值」两列排。

### 3.3 空态 / 加载态

表格区域必须有 3 态：骨架屏（首次加载）→ 空态（0 行）→ 数据态。骨架屏行数 = 当前页容量（如 10 行），避免内容进入时高度塌陷造成 CLS。

---

## 4. 空态 Empty

### 4.1 结构（三件套，缺一不可）

```
        [SVG 图示 64px]        ← 来自 Icon.jsx，禁止 emoji
     标题：还沒有错题
   说明：做完题后，做错的会自动收进这里，按遗忘曲线排好复习日。
        [ 主操作按钮 ]   [ 次要链接 ]
```

| 元素 | 规格 |
|---|---|
| 容器 | 最小高 240px，垂直居中，`padding: var(--space-12) var(--space-4)` |
| 图示 | 64px，`color: var(--meta)`，`opacity: .6`，来自 `Icon.jsx` |
| 标题 | 16px / `--fw-semibold` / `var(--fg)` |
| 说明 | 14px / `--fw-regular` / `var(--muted)`，最多 2 行，每行 ≤ 30 汉字 |
| 主操作 | Primary 按钮，1 个 |
| 次要 | Ghost 按钮或文字链接，最多 1 个 |

### 4.2 文案规则（禁止空洞）

- [禁] 「暂无数据」「Welcome to…」「还没有内容哦」
- [好] 说清两件事：**为什么是空的** + **下一步做什么**

| 页面 | 空态文案 |
|---|---|
| 错题本 | 标题「还没有错题」/ 说明「做完题后，做错的会自动收进这里，按遗忘曲线排好复习日。」/ 操作「去刷题」 |
| 学习计划 | 标题「还没排计划」/ 说明「先选科目和每天能学多久，我按剩余天数把任务排到考前。」/ 操作「生成计划」 |
| 知识图谱 | 标题「这个科目还没有知识点」/ 说明「导入讲义或做完一轮题后，知识点会自动挂到章节下。」/ 操作「去导入」 |
| 通知中心 | 标题「通知都看完了」/ 说明「有新公告时会在这里出现，加星的会置顶。」/ 操作「查看院校」 |

### 4.3 零结果（搜索/筛选无匹配）≠ 空态

零结果要能「退出」当前状态：
`没有匹配「线性代数」的结果` + 操作「清除筛选」（不是「去刷题」）。

---

## 5. 加载态 Loading

### 5.1 分级策略

| 级别 | 触发 | 形态 |
|---|---|---|
| 容器级 | 首屏 / 整块列表 | **骨架屏**（形状贴近真实内容） |
| 操作级 | 点击按钮后 | 按钮内 Spinner（`is-loading`），保留按钮宽度 |
| 全局级 | 路由切换 | 顶栏下方 2px 进度条（`accent`，`--ease-linear`） |
| 短延迟 | <300ms | **什么都不显示**，避免闪一下的抖动 |

### 5.2 骨架屏规格

```css
.sk {
  background: var(--skeleton);
  border-radius: var(--radius-md);
  position: relative; overflow: hidden;
}
.sk::after {   /* 微光扫过，linear 缓动，1.2s 一轮 */
  content: ''; position: absolute; inset: 0;
  transform: translateX(-100%);
  background: linear-gradient(90deg, transparent, var(--surface-2), transparent);
  animation: sk-sweep 1200ms var(--ease-linear) infinite;
}
@keyframes sk-sweep { to { transform: translateX(100%); } }

.sk--text  { height: 14px; }
.sk--title { height: 20px; width: 45%; }
.sk--row   { height: var(--table-row-h); border-radius: 0; border-bottom: 1px solid var(--border-soft); }
```

规则：
- 骨架屏**尺寸必须等于**真实内容尺寸（行数、行高、卡片数），否则产生 CLS。
- 骨架屏不加阴影、不用渐变色块（保持灰阶）。
- `prefers-reduced-motion` 下去掉扫光动画，只留静态灰块（`tokens.css` 已统一把时长降到 1ms）。

### 5.3 错误态（加载失败）

```
[AlertCircle 20px]  加载失败：网络超时
                    [ 重试 ]   [ 查看离线缓存 ]
```
- 错误文案说清 **发生了什么** + **怎么恢复**，不暴露堆栈。
- 重试按钮必须存在，且重试期间进入 Loading 态。
- 有本地缓存时给「查看离线缓存」降级入口。

---

## 6. 标签 Tag / 徽章 Badge

| 属性 | 值 |
|---|---|
| 高度 | `--tag-h` 20px（可点击 chip 用 28px，满足间距而非触摸） |
| 水平内边距 | `--tag-pad-x` 8px |
| 圆角 | `--radius-sm` 6px；药丸 chip 用 `--radius-full` |
| 字号 / 字重 | 12px / `--fw-medium` |
| 默认 | `background: var(--surface-2)` `color: var(--fg-2)` 无描边 |

### 6.1 语义变体（底 + 字，不用纯色块配白字以外的组合）

| 语义 | 背景 | 文字 |
|---|---|---|
| 成功 / 已掌握 | `--success-soft` | `--success-ink` |
| 警告 / 模糊 | `--warn-soft` | `--warn-ink` |
| 危险 / 不会 | `--danger-soft` | `--danger-ink` |
| 信息 | `--info-soft` | `--info-ink` |
| 强调 / 当前科目 | `--accent-soft` | `--accent` |
| 未学 / 中性 | `--untouched-bg` | `--untouched-ink` |

### 6.2 知识点掌握度（全站统一四态，不许各页自造色）

| 态 | 底 | 字 | 实心 | 文案 |
|---|---|---|---|---|
| 已掌握 | `--mastered-bg` | `--mastered-ink` | `--success` | 已掌握 |
| 模糊 | `--shaky-bg` | `--shaky-ink` | `--warn` | 模糊 |
| 不会 | `--unknown-bg` | `--unknown-ink` | `--danger` | 不会 |
| 未学 | `--untouched-bg` | `--untouched-ink` | `--meta` | 未学 |

> 禁止只用颜色传达含义 —— 每个色块旁必须有文字或图标（对色盲用户与黑白打印都可读）。

### 6.3 角标（未读数）

- 尺寸 `min-width: 20px; height: 18px; padding: 0 6px`，圆角 `--radius-full`，字号 11px，`--fw-semibold`，`font-variant-numeric: tabular-nums`。
- 颜色：`background: var(--danger)` `color: #fff`（未读）；`background: var(--surface-3)` `color: var(--muted)`（计数，非告警）。
- 必须有 `aria-label`（如「12 条未读通知」），不能只靠视觉。

---

## 7. 下拉 / 选择器 Dropdown

### 7.1 规格（与导航下拉同一套）

| 属性 | 值 |
|---|---|
| 触发器高度 | 36px（表单内）/ 32px（筛选区）/ 32px（科目药丸） |
| 面板宽度 | 导航 224px · 科目 240px · 表单跟随触发器宽度（`min-width: 100%`） |
| 面板内边距 | `--nav-dd-pad` 6px |
| 圆角 / 描边 / 阴影 | `--radius-lg` / `1px solid var(--border)` / `--shadow-md` |
| 行规格 | `grid-template-columns: 20px 1fr auto`，行高 40px（触屏 48px） |
| 层级 | `--z-dropdown` 1010 |
| 定位 | `top: calc(100% + 8px)`；`padding-top: 8px` 透明 hover 桥 |
| 动效 | 150ms `opacity` + `translateY(4px)`，`--ease-standard` |

### 7.2 交互与 ARIA

| 项 | 要求 |
|---|---|
| 触发 | 点击 / Enter / Space 开合；**hover 只能作为增强，不能是唯一路径** |
| 键盘 | ↓ 打开并聚焦首项；↑↓ 循环；Enter 选中；Esc 关闭并归还焦点；Tab 移出即关 |
| 搜索 | 选项 >8 个时必须带过滤输入框（院校库科目、知识点选择） |
| 多选 | 行首 20px 复选框；已选项在触发器里以 chip 展示，超 3 个折叠为「+N」 |
| ARIA | 触发器 `aria-haspopup="listbox"` `aria-expanded`；面板 `role="listbox"`；行 `role="option"` `aria-selected` |
| 分组 | 选项 >12 个时按语义分组，组标题 12px `var(--meta)` + `letter-spacing: var(--tracking-wide)`，组间 `1px solid var(--border-soft)` |
| 溢出 | 面板高度 `max-height: 320px`，超出滚动；不撑破视口，空间不足时向上翻转 |

### 7.3 状态

- **Disabled 行**：`opacity: .5; cursor: not-allowed`，并在行尾给出原因（如「该科目暂无题目」）。
- **无匹配**：面板内直接显示「没有匹配「XX」的选项」+ 「清除筛选」按钮，不关闭面板。
- **Loading**：面板内 3 行 `--tag-h` 骨架条。

---

## 8. 模态 Modal

### 8.1 规格

| 属性 | 值 |
|---|---|
| 宽度 | `--modal-w-sm` 400px（确认）/ `--modal-w-md` 640px（表单）/ `--modal-w-lg` 880px（内容） |
| 圆角 | `--modal-radius` 16px |
| 内边距 | `--modal-pad` 20px（头部/主体/底栏各自 20px） |
| 背景 / 阴影 | `var(--surface)` / `--shadow-lg` |
| 遮罩 | `var(--overlay)`；点击遮罩关闭（**表单类例外**：有未保存改动时二次确认） |
| 层级 | `--z-modal` 1020（tooltip/命令面板在其上用 `--z-popover`） |
| 最大高度 | `max-height: calc(100vh - 96px)`，主体区 `overflow-y: auto` |
| 动效 | 遮罩 200ms opacity；面板 280ms `opacity` + `translateY(8px) scale(.98)`，`--ease-standard` |

### 8.2 结构

```
┌────────────────────────────────────┐
│ 标题                          [×]  │   ← 20px，标题 18px/600，关闭 24px 图标按钮
├────────────────────────────────────┤
│                                    │
│  主体（可滚动）                     │
│                                    │
├────────────────────────────────────┤
│               [取消] [确定]         │   ← 底栏右对齐，主操作在最右
└────────────────────────────────────┘
```

### 8.3 无障碍（必须全做）

- `role="dialog"` `aria-modal="true"` `aria-labelledby`（指向标题 id）。
- 打开时焦点移到面板内第一个可聚焦元素；关闭时焦点**还给触发它的元素**。
- 焦点陷阱：Tab / Shift+Tab 在面板内循环，不穿透到背景。
- 打开时 `body { overflow: hidden }`，并补偿滚动条宽度防布局跳动。
- Esc 关闭；表单类有未保存改动时弹「放弃修改？」二次确认。

### 8.4 移动端

<768px 一律改**底部 ActionSheet**：面板贴底、`border-radius: 16px 16px 0 0`、宽度 100%、最大高 `80vh`，按钮全宽 44px。桌面 Modal 与移动 ActionSheet 用同一组件的两个 `variant`。

### 8.5 确认框（Danger）

- 宽度用 `sm`；标题用动宾（「删除这 12 道错题？」），不用「确认」。
- 说明后果（「删除后无法恢复」）。
- 主按钮 `btn--danger`，文案具体（「删除 12 道题」而非「确定」）。

---

## 9. 输入框 Input / 表单

| 属性 | 值 |
|---|---|
| 高度 | `--input-h` 36px（筛选区 `--input-h-sm` 32px） |
| 圆角 / 描边 / 背景 | `--radius-md` / `1px solid var(--border)` / `var(--surface)` |
| 内边距 | `0 var(--space-3)` |
| 字号 | 14px；`placeholder` 用 `var(--meta)` |

状态：

| 状态 | 表现 |
|---|---|
| Default | `border-color: var(--border)` |
| Hover | `border-color: var(--border-strong)` |
| Focus | `border-color: var(--accent)` + `box-shadow: var(--focus-ring-shadow)` |
| Error | `border-color: var(--danger)`；错误文案紧贴字段下方，13px `var(--danger-ink)`，含修正指引 |
| Disabled | `background: var(--surface-3)` `color: var(--meta)` `cursor: not-allowed` |

规则：
- **可见 label 必须有**，禁止只用 placeholder 当标签。
- 错误提示贴近出错字段，禁止只在顶部汇总。
- 一组可见字段 ≤4 个（认知负荷）；更多的走分步/折叠。
- 数字/电话输入用 `type="number"` / `type="tel"` 触发移动端数字键盘。

---

## 10. Toast

| 属性 | 值 |
|---|---|
| 位置 | 右下角（桌面）/ 底部居中偏上（移动），距边 `--space-6` |
| 尺寸 | 最小宽 280px，最大 420px，内边距 `--space-3` `--space-4`，圆角 `--radius-md` |
| 背景 / 阴影 | `var(--surface)` + `1px solid var(--border)` + `--shadow-md` |
| 层级 | `--z-toast` 1040 |
| 动效 | 进场 200ms `translateY(8px) → 0` + opacity；出场 150ms |
| 时长 | 成功 2.2s / 信息 3s / 错误 **不自动消失**（需用户关闭或重试） |

- 结构：`[状态图标 16px] 文案 [操作链接]`。成功 `--success-ink`、错误 `--danger-ink`、警告 `--warn-ink`。
- `role="status"`（成功/信息）或 `role="alert"`（错误）。
- 最多同时 3 条，超出堆叠并淡出最旧一条。
- 错误 Toast 必须带「重试」操作。

---

## 11. 进度条 / 进度环

- 高度 6px（条）/ 直径 96px（环），轨道 `var(--surface-3)`，填充 `var(--accent)`。
- 达标态：≥80% 用 `--success`，<30% 且临期用 `--warn`，超时 `--danger`。
- **必须配文字**（「掌握 428 / 1067 · 40%」），不能只靠颜色/长度传达。
- 数字用 `class="tabular"`，避免刷新时数字跳动。
- 禁止 `indeterminate` 动画超过 500ms 一轮的装饰性长动画。

---

## 12. 组件清单与归属（避免各页自造）

| 组件 | 落地位置 | 状态 |
|---|---|---|
| Button / Modal / Segmented / Empty / toast | `src/components/UI.jsx` | 已存在，按本规范**改样式**，不改 API |
| Icon（唯一图标源） | `src/components/Icon.jsx` | 已存在，**只扩充不替换**；禁止引入第二套 |
| TopNav / NavDropdown | `src/components/TopNav.jsx` | **新建**（见 NAV-SPEC §2.2） |
| navConfig | `src/components/navConfig.js` | **新建**（见 NAV-SPEC §1.4） |
| SubjectPicker | `src/components/SubjectPicker.jsx` | 由 `SubjectSwitcher.jsx` 改壳 |
| Skeleton / ErrorState / ZeroResult | `src/components/States.jsx` | 已存在，按 §5 补齐三件套 |
| Table | 新增 `src/components/Table.jsx` | **新建**（现有各页手写 table 样式碎片化） |
| Tag / Badge | 新增 `src/components/Tag.jsx` | **新建** |
| PageHeader / PageShell | 新增 `src/components/PageShell.jsx` | **新建**（见 PAGE-PATTERNS §1） |

---

## 13. 自检清单（PR 门禁）

- [ ] 无 emoji（`[\x{1F300}-\x{1F9FF}\x{2600}-\x{26FF}\x{2700}-\x{27BF}]` 零命中）
- [ ] 组件样式内无裸 hex（除 `#fff` / `#000`）
- [ ] 每个交互组件覆盖九态，至少覆盖 Loading / Empty / Error / Disabled
- [ ] 所有图标来自 `Icon.jsx`，尺寸 ∈ {16, 20, 24}
- [ ] 焦点可见（`:focus-visible` 有 `box-shadow`），无裸 `outline: none`
- [ ] 触摸目标移动端 ≥44px
- [ ] 无弹跳缓动；动效时长取自令牌
- [ ] 无 `border-left/right > 1px` 彩色强调
- [ ] 无幽灵卡片（`1px` 边框 + `blur ≥16px` 阴影同时出现）
- [ ] 对比度：正文 ≥4.5:1，大字 ≥3:1（`--meta` 仅限大字/图标）
