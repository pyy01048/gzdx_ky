# 学术深青绿 v3 换肤实施规范（Academic Teal Reskin）

> 来源：用户《高级感网页设计提示词 · 考研学习平台》（2026-11-21）。
> 本文是该通用提示词的**项目落地深化版**：所有令牌映射到现有 v3 单源
> `frontend/src/v3/styles/tokens.css`，冲突点已实测裁决，模块顺序对齐真实页面。
> 决策（用户授权按推荐执行）：①令牌级换肤，不迁 Tailwind/shadcn/TS/recharts；
> ②采用新字阶并同步更新验收门禁 FONT_SET；③动效按规范收敛；④深层修复
> （WP-A/B/D/C）完成提交后实施，避免文件冲突。

## 1. 身份变更

现身份 Google M3 × Gemini（蓝 #1A73E8 + 操作紫 #6D5AE6 + 蓝紫粉渐变）→
**干净、克制、有秩序感的效率型学习产品**：Apple/Linear 式留白与细线，
学术深青绿主色 + 琥珀点缀。gemini 蓝紫粉能量层全部移除（踩规范黑名单第 1 条）。

## 2. 令牌映射（浅色 :root）

| v3 变量 | 现值 | 新值 | 备注 |
|---|---|---|---|
| --v3-bg | #F6F8FC | **#F7F8F7** | 暖调灰白，禁纯白 |
| --v3-bg-alt | #EEF2F9 | #EFF2F0 | |
| --v3-surface | #FFFFFF | #FFFFFF | 卡片底 |
| --v3-surface-1 | #F2F5FA | **#F1F4F2** | 次级面板/输入框底 |
| --v3-surface-2 | #E9EEF7 | #E7ECE9 | |
| --v3-surface-3 | #DEE5F2 | #DCE3DF | |
| --v3-text | #1F2023 | **#14201B** | 墨绿黑，禁纯黑 |
| --v3-text-2 | #474B55 | **#42544C** | 7.57:1 ✓ |
| --v3-text-3 | #5A6270 | **#5F7067** | 规范原值 #6B7C73 仅 4.15:1 不过 AA，加深一档至 4.93:1 ✓（规范自身要求 AA） |
| --v3-outline | #E1E6EF | **#E3E8E5** | 1px 细线 |
| --v3-outline-strong | #C8D0DD | #C9D2CD | |
| --v3-primary | #1A73E8 | **#0F766E** | 浅底文字 5.14:1 ✓ |
| --v3-primary-hover | #1765CC | **#0B5F59** | |
| --v3-primary-container | #DCEBFF | **#E2F2F0** | soft 底标签文字 4.74:1 ✓ |
| --v3-on-primary | #FFFFFF | #FFFFFF | 白字压青绿 5.47:1 ✓ |
| --v3-on-primary-container | #0B3D91 | #0B4A44 | |
| --v3-action / -hover | #6D5AE6 / #5B48D6 | **并入主色** #0F766E / #0B5F59 | 操作紫移除；关键操作唯一强调 |
| --v3-focus / outline-focus | #1A73E8 | #0F766E | focus ring 主色 |
| --v3-secondary | #7A5AF8 | #3D8A80 | 青绿次阶（图表/分组），禁紫 |
| --v3-tertiary | #E05B73 | **#E8A33D** | 琥珀点缀：仅非文字强调（进度条/圆点/描边）或深墨字 CTA（#14201B 压琥珀 ≈7.6:1 ✓）。琥珀当浅底文字 2.03:1 ✗、白字压琥珀 ✗ |
| --v3-success | #188038 | #16A34A | 容器浅底同步调，落地时跑对比度脚本 |
| --v3-warning | #925C00 | #D97706 | 文字用深档 #B45309 保 AA |
| --v3-danger | #C5221F | #DC2626 | |
| --v3-info | #1769AA | #2563EB | |
| --v3-state-doing | #1A73E8 | #0F766E | 数据态跟随主色 |
| --v3-gemini-1..4 | 蓝/紫/粉/橙 | #0F766E / #3D8A80 / #E8A33D / #14201B | 变量名保留（消费方多），值换学术色 |
| --v3-gemini-gradient | 蓝→紫→粉 | linear-gradient(115deg, #0F766E, #3D8A80 55%, #E8A33D) | 仅 Login 标题/beam 等既有单点使用，克制 |
| --v3-gemini-gradient-soft / conic / glow-* | 蓝紫粉光晕 | 青绿琥珀同构低透明版 | |
| --v3-shadow-1 | 冷调 | **0 1px 2px rgba(16,24,20,.06)** | 静止 |
| --v3-shadow-2 | 冷调 | **0 8px 24px rgba(16,24,20,.08)** | 悬停 |
| --v3-shadow-3/4/glow | 冷调 | 墨绿调同构加深；glow → rgba(15,118,110,.25) | |
| --v3-r-sm（控件） | 12px | **新增 --v3-r-control:10px**，按钮/输入框/选择器改用 | 卡片 16（--v3-r-md）不动，胶囊 999 不动 |
| --v3-content-max | 1480px | **1280px** | |
| --v3-gutter | 28px | **24px** | 12 栏槽距 24 |
| --v3-ease-* | M3 | **新增 --v3-ease-expo-out: cubic-bezier(0.16,1,0.3,1)**；弹性 (0.34,1.56,0.64,1) 替换现 bounce 1.36 档 | 进场 expo-out，禁 linear/默认 ease |

深色 [data-theme="dark"]（已逐值实测 AA）：
bg #0C1211 / surface #141C1B / surface-1 #1A2422 / surface-2 #222E2B /
outline #26332E / text #E8EDEA(15.97:1) / text-2 #B4C2BB(10.25:1) / text-3 #8FA096(6.88:1) /
primary #2DD4BF（文字 10.16:1；on-primary #062E2B 压按钮 7.87:1）/
primary-container #0B3B36（容器文字 #7FDFD2 7.91:1）/ accent #F0B45C(10.26:1) /
gemini 渐变青绿→琥珀暗色版。禁冷蓝黑。
细线 outline 对底 1.44:1 属装饰性豁免；交互控件边界靠 surface-2 底色差 +
focus ring（主色 10:1）满足 WCAG 1.4.11，输入框必须有可辨填充。

## 3. 字体（自托管，大陆可用）

已下载入 `frontend/public/fonts/`：
- `inter-tight-latin-var.woff2`（43KB，wght 400..700 可变）
- `jetbrains-mono-latin-var.woff2`（30KB，wght 400..600 可变）

@font-face 走 font-display:swap + unicode-range latin；**中文不进 webfont**
（Noto Sans SC 全量数 MB），栈：
- --v3-font-sans / display: `"Inter Tight","Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif`
- --v3-font-mono: `"JetBrains Mono","IBM Plex Mono",ui-monospace,Consolas,monospace`
数字统计/倒计时/公式/编号一律 mono。标题字距 -0.01~-0.02em（--v3-tracking-tight 已有）。

## 4. 字阶与门禁

新阶梯（角色 → px）：caption 12 / sm 13 / 密集表格 14 / **body 15** / UI 基准 16 /
**h3 18** / h2 20·24 / h1 28·36 / **display 40·48**（Login/Hero 单焦点）。
tokens.css 补 --v3-fs-15；lh：body 1.7、标题 1.1~1.35。
**门禁同步**：scripts/acceptance_hub.mjs FONT_SET →
`{12,13,14,15,16,18,20,24,28,36,40,48}`；Hub 主数字仍 36 全页唯一。
存量 14px 正文逐步迁 15（密集列表/表格保留 14），每模块换肤时一并处理。

## 5. 动效收敛（规范：每个动画回答「为什么动」）

- beam：**仅 Hub 倒计时**一处（重着色青绿→琥珀）；spotlight：**仅 Login 面板**一处。
- 院校卡：移除逐卡 v3-spotlight，保留 tilt(≤2°)+hover-lift 4px+阴影加深。
- Login 极光视差背景 → **低透明度点阵（3-6%）+ 单层极淡青绿径向柔光**（规范 A 允许）。
- reveal：480ms → **320ms expo-out**，上移 16px → **12px**；错峰 40ms → **70ms**。
- 微交互 120/200ms、面板 200-320ms、页面进场 320ms（dur-1/2/3 已对齐）。
- 保留：CountUp、Typewriter（Login 引导语）、Shimmer 骨架、Marquee（院校热榜）、
  ReadingProgress（功能性）、Spring 按压回弹。全部 transform/opacity only，
  prefers-reduced-motion 降级已有基建（motion.jsx useReducedMotion）。
- hover 放大 ≤1.03；禁动画 width/height/top/left/margin。

## 6. 模块实施顺序（规范分模块 → 真实页面）

| 序 | 规范模块 | 页面 | 要点 |
|---|---|---|---|
| R1 | 令牌层 | tokens.css/base.css/components.css/motion.css/index.html(字体)/acceptance_hub.mjs | 全站自动生效；门禁 88/88 复跑 |
| R2-A | 首页概览 | Hub.jsx | 问候+今日任务+倒计时(mono count-up)、KPI 卡、科目入口进度条、单主 CTA、首跑引导面板（WP-D 产物）按新令牌复核 |
| R2-B | 知识体系 | KbMap/Library/KnowledgeArticle | 左目录右卡片网格 3/2/1 栏、掌握态浅底徽章、箭头右移 hover、长文行距 |
| R2-C | 刷题 | QuizHome/QuizPractice | 选项四态（默认/悬停/选中 soft/对错功能色浅底）、解析 200-320ms expo-out 展开、数字键+Enter、反馈措辞「掌握/需复习」 |
| R2-D | 错题本 | ErrorReview/QuizReview | 筛选栏、错误次数徽章、重做/解析、知识点分组折叠、空态线性图标+CTA、骨架 shimmer |
| R2-E | 学习计划 | Planner/PlanPage/Tasks | 周/月日历色点、当日任务勾选、新建弹窗校验、移动端横向日期条；**与 WP-B 可编辑改造合并验收** |
| R2-F | 数据概览 | Dashboard/GrowthPage/LearningTimeline/LearnerProfile | KPI count-up、近 14 天趋势+科目正确率（ECharts 配色取令牌，不迁 recharts）、掌握分组列表、禁排行榜/他人对比 |
| R2-G | 导航/个人中心 | shell/Settings | **保留方案 1 折叠侧栏**（248px/76px 导轨，门禁已断言）；选中态浅底+主色文字+指示条；backdrop-filter 全 none（毛玻璃方案 3 不采用）；Settings 分组对齐规范表单规范 |

每页交付：桌面/平板/移动三档说明 + focus/hover/disabled/loading/empty/error 六态核查 + 截图证据。

## 7. 自检清单（上线前逐项核对，规范第 5 节）

视觉：颜色全走令牌无散落硬编码；同层级字号/字重/间距/圆角一致；一屏单焦点；
无紫蓝渐变/emoji 图标/重背景特效。
内容：文案真实规范无 Lorem ipsum；无积分商城/金币/排行榜（本项目既有边界一致）。
动效性能：transform/opacity only；时长达标；错峰/回弹克制；reduced-motion 适配；
图片 aspect-ratio 预留；font-display:swap。
无障碍响应式：AA 对比度（逐值脚本验证）；全键盘可达 focus ring 可见；三档断点；六态齐全。

## 8. 执行前置依赖

WP-A（后端隔离）→ WP-B（计划可编辑）∥ WP-D（串号+首跑）→ WP-C（旅程复验+提交）
→ **R1 → R2-A..G → R3 自检+报告+提交**。换肤期间验收门禁每模块复跑，
截图存 frontend/acceptance/shots/。生产部署仍按用户决定暂缓，攒齐一次上线。
