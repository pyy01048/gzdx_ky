# 考研学习平台前端 · 真实浏览器走查报告

> 走查时间：2026-10-12 10:44–11:15
> 方式：**真实浏览器**（Playwright headless Chromium 156，非降级；未使用 curl 模拟）
> 后端：http://127.0.0.1:8000（245 路由） · 前端：http://127.0.0.1:5173（哈希路由）
> 真库：D:\平台\database\kaoyan.db
> 证据：截图 `D:\平台\docx\_analysis\e2e-shots\`（66 张） · 原始日志 `D:\平台\docx\_analysis\_e2e\logs\` · 脚本 `D:\平台\docx\_analysis\_e2e\*.mjs`
> 说明：**未修改任何项目代码**，仅在 `_e2e\` 下新增诊断脚本。

---

## 0. 一句话结论

> **前端整体"能打开、不白屏、无控制台崩溃"，六大模块中 4 个（文库 / 题库刷题 / 错题复盘 / 院校）用的是真数据且主链路可用；但 2 个模块存在严重问题——「单词记忆」整模块跑在 20 条本地 Mock 数据上、与后端 4569 词真库完全脱节；「知识地图」你刚说要确认的"关联知识块/原文摘录"在当前前端里根本不存在（全仓无此 UI），且数电/数学/英语/政治的知识点数为 0。**

---

## 1. 环境与前置问题

| 项 | 状态 |
|---|---|
| 后端 8000 | ✅ 200 |
| 前端 5173 | ⚠️ 走查开始时**进程未运行**（返回 502），已由我重新启动 `npm run dev` 后才可访问 |
| Playwright | ✅ 项目内已装，Chromium 156 可正常启动 |
| 全局控制台 | ✅ 27 条路由扫描，**除 `/settings` 外全部 0 条 console error / 0 pageerror / 0 接口非 2xx** |

基线脚本：`shell.mjs` → `logs/shell.log`（27 路由总表）；`dump.mjs` → `logs/dump.out.txt`。

> ⚠️ **诊断可信度说明**：`vite.config.js` 里设了 `esbuild: { drop: ['console','debugger'] }`，实测**在 dev 模式下也会剥离 `console.*`**（见 §5 问题 M）。因此应用自身打的 `console.warn/error` 不会出现在控制台，本报告的控制台结论只覆盖未捕获异常与浏览器/三方报错，**不能排除"被静默吞掉的报错"**。

---

## 2. 六大模块逐项结论

| 模块 | 记录/路由 | 渲染 | 控制台 error | 数据真伪（页 vs 后端） | 核心交互 | 判定 |
|---|---|---|---|---|---|---|
| 学习文库 | `#/library` | ✅ | 0 | ✅ 264 = 后端 264；已解析正文为真 OCR 文本 | ✅ 点文档出正文 | **可用** |
| 知识地图 | `#/kbmap` | ✅ | 0 | ⚠️ 顶部 1050，树内可见仅 879；数电/数学/英语/政治=0 | ⚠️ 知识点**不可点开**，无详情面板 | **部分不可用** |
| 题库/刷题 | `#/quiz-bank` `#/quiz` | ✅ | 0 | ❌ 同屏 3465 与 5588 冲突 | ✅ 选→提交→判分→交卷全通 | **可用（口径混乱）** |
| 单词记忆 | `#/words` | ✅ | 0 | ❌ 页面 20 词 vs 后端 4569 词 | ⚠️ 翻卡/评分只动本地，后端统计不变 | **不可用（假数据）** |
| 错题复盘 | `#/error-review` | ✅ | 0 | ⚠️ 条数与后端一致，但 6 条正确答案带【草稿】 | ✅ 详情/AI/知识点关联可点 | **可用（含脏数据）** |
| 院校数据中心 | `#/kaoyan` | ✅ | 0 | ✅ 583/832/831/810 与 `/api/kaoyan/stats` 完全一致 | ✅ 搜索"邮电"出 4 校；详情简介非空 | **可用** |

---

## 3. 问题清单（按严重程度排序）

### 🔴 致命

**P1. 单词记忆模块整模块跑在本地 Mock 数据上，与后端真库脱节**
- 模块：单词记忆 `#/words`
- 复现：打开 `http://127.0.0.1:5173/#/words`
- 实际现象：页面统计卡显示 **`20 总词数`、`20 今日待复习`、`20 学习中`、`0 已掌握`**，卡片显示 `approach 1/20`，词表只有 20 条（approach/significant/available/maintain/phenomenon/assume…）。这些词与 `frontend/src/utils/words.js` 的 `CORE_WORDS` 完全同序。
  后端实测：`/api/words/stats` = `{"total":4569,"due_today":4568}`；`/api/words?page=1&page_size=500` 返回 `{"items":[500条],"total":4569}`。
  点"记得"后：单词切换（approach→available），但**后端 `/api/words/stats` 前后无任何变化**（total/due 恒为 4569/4568）。
- 证据截图：`e2e-shots/targeted-words-truth.png`、`words-01-learn.png`、`words-05-wordlist.png`；日志 `logs/targeted2.log`、`logs/words.log`
- 期望：展示后端 4569 词真库，翻卡与评分落库、stats 随复习变化。
- 初判根因：**前端（契约不匹配）**。`Words.jsx:63` 调 `wordsApi.list({page:1,page_size:500})`，但 `/api/words` 返回的是分页对象 `{items,total,page,page_size,total_pages}`（见 `logs/targeted2.log` 的响应体），而代码按数组用：`if (backendWords && backendWords.length > 0)` —— 对象没有 `.length`，条件恒为 false → **静默跳过赋值**，页面继续用 zustand store 里持久化的 `SEED.words`（本地 20 词）。`.catch` 里那句 `console.warn` 又被 dev 的 `drop:['console']` 剥离，所以连提示都没有。

**P2. 知识地图「知识点详情 / 关联知识块·原文摘录」功能不存在（你以为是刚修好的）**
- 模块：知识地图 `#/kbmap`（另查了最接近的 `#/panorama` 知识点全景）
- 复现：打开 `#/kbmap` → 展开任一有知识点的章节 → 点击知识点名称或整行
- 实际现象：
  1. **全仓搜索 `关联知识块`、`原文摘录`、`知识块` —— 前端/后端代码 0 命中**（仅在归档文档 `docx/archive/v6.0-superseded/…md` 出现）。
  2. `#/kbmap` 页面正文中 **`原文`/`摘录`/`知识块`/`关联` 四个关键词全部不出现**（`logs/targeted2.log` A 段 `keyword` 全 false）。
  3. 用 JS 直接 `click()` 知识点名称、再点整行：**页面文本长度变化 0、hash 不变、无任何弹层/抽屉元素出现**（`面板数: 0`）。知识点行没有 onClick（只有"会/模糊/不会"三个复习按钮挂了 `submitReview`）。
  4. 最接近的"知识点详情"在 `#/panorama`，点开后只显示：`二极管 · 模拟电子技术 · 第1章 … 掌握度 0% / 关联题量 0 题 / 掌握档位 薄弱 / 考频 — / 涉及题型 …`，**同样没有原文摘录**。
  5. 后端其实**有**这块数据：`GET /api/taxonomy/knowledge-points/{id}` 返回体含 `related_chunks:[{chunk_id,document_id,doc_name,text}]`（实测 kp 428 返回了非空 `text`）；`knowledge_point_relations` 表 911 行。
- 证据截图：`e2e-shots/targeted-kbmap-kp.png`、`targeted-panorama-detail.png`、`verify-kbmap-01-kp-click.png`；日志 `logs/targeted2.log`、`logs/verify.log`
- 期望：点开知识点能看到"关联知识块/原文摘录"并**有内容**。
- 初判根因：**前端（功能缺失）**。后端 `related_chunks` 数据在，但**没有任何前端组件消费它**；`KbMap.jsx` 全文只有三级树 + 复习按钮，不存在详情面板。→ 你的修复**没有落到当前运行的这套前端上**（可能改在别的分支/文件，或只改了后端而前端从未实现该面板）。

---

### 🟠 严重

**P3. 错题复盘的「正确答案」仍带 `【草稿】` 前缀（浏览器已实测可见）**
- 模块：错题复盘 `#/error-review`
- 复现：打开 `#/error-review` → 点开**第 10 条**错题（题干"在以下代码中，是有权码的有（ ）。"）
- 实际现象：详情面板 **"正确答案" 直接显示 `【草稿】B查看答案`**（截图可见）。
  接口层交叉验证：`/api/errors` 里 40 条中有 **6 条** `correct_answer` 带 `【草稿】`：
  `#42 "【草稿】B查看答案"`、`#12 "【草稿】置0；置1"`、`#11 "【草稿】5个百分点"`、`#19 "【草稿】D"`、`#21 "【草稿】B"`、`#23 "【草稿】d"`。
  另：真库 `quiz_questions.analysis` 仍有 **1576 行**含 `【草稿解析】`（`answer` 字段已为 0，说明上次只清了 answer），且 `GET /api/quiz/questions/8` 会原样返回 `analysis="【草稿解析】…"`。
- 证据截图：**`e2e-shots/evidence-errorreview-caogao.png`**；日志 `logs/errcheck.log`
- 期望：任何位置的答案/解析都不出现 `【草稿】`。
- 初判根因：**数据（清洗不彻底）**。上次的 `clean_quiz_draft_marks.py` 只清了 `quiz_questions.answer`，**遗漏了 `error_records.correct_answer` 与 `quiz_questions.analysis`**。

> 补充：**刷题路径（`#/quiz`、`#/quiz-bank` 列表）的答案目前是干净的**——实测 3 道题的 reveal 原文分别是 `正确答案：错误 / 正确答案：解析 / 正确答案：D`，均无 `【草稿】`；扫全库前 1500 题 0 条命中。**问题只暴露在错题复盘。**

**P4. 知识地图里"数字电子技术 / 数学 / 英语 / 政治"知识点数全为 0**
- 模块：知识地图 `#/kbmap`
- 复现：打开 `#/kbmap`，看各科目卡
- 实际现象：`数字电子技术 知识点 0 · 8 章节`，其 8 个章节全部标"暂无资料"；`数学 知识点 0`、`英语 0`、`政治 0`。只有 `模拟电子技术 644`、`其他 230`、`真题综合 5` 有知识点 → 树内可加总 **879**，但顶部总览写 **1050 个知识点**。
- 交叉验证（真库）：`knowledge_points` 表 1050 行的 `subject` 分布是 **`数模电 644 / 公共课 219 / 408 134 / 信号与系统 37 / 专业课 5 / 真题综合 5 / 其他 4`** —— **没有一行 subject 叫"数字电子技术"**；而 `knowledge_chunks` 里数电有 9791 块、数电题库有 2335 题。
- 证据截图：`e2e-shots/kbmap-01-overview.png`；日志 `logs/kbmap.log`
- 期望：数电的知识点出现在知识地图上。
- 初判根因：**数据（学科命名映射错位）**。知识点是按"数模电/公共课/408"这类粗粒度 subject 存的，而知识地图按"数字电子技术/数学/英语"细粒度 subject 分组，映射不上 → 全部算到"模电/其他"名下。

**P5. 题库总量三处口径不一致，且在同一屏上自相矛盾**
- 模块：题库 `#/quiz-bank`、`#/quiz`
- 复现：打开 `#/quiz-bank`
- 实际现象：**同一页**页头写"共 3465 道"，右侧统计卡写"**5588 题库总量**"；分页器又写"第 1 / 174 页 · 共 3465 题"。而真库 `quiz_questions` 有 **9164** 行。
  后端：`/api/quiz/questions` total=3465；`/api/quiz/stats` total_questions=5588。
- 证据截图：`e2e-shots/quizbank-01-manage.png`；日志 `logs/quiz.log`
- 期望：统一口径，或明确标注"可浏览 3465 / 全库 5588"。
- 初判根因：**前端 + 后端（口径不统一）**。三个数各自来自不同来源（列表过滤后 3465、统计表 5588、物理行 9164），前端把前两个并排展示且无说明。

**P6. `/settings` 目标院校候选列表静默失败（接口 422）**
- 模块：设置页 `#/settings`
- 复现：打开 `#/settings`，开控制台
- 实际现象：控制台 **`422 (Unprocessable Content) /api/kaoyan/schools?page=1&page_size=500`** ×2。后端实测 `page_size=500` → 422（`"Input should be less than or equal to 200"`），`page_size<=200` 正常。设置页根因代码 `Settings.jsx:108` 请求 500，且 `.catch(()=>{})` 把错误吞了 → **"目标院校"候选列表永远为空**（仅能手动输入）。
- 证据截图：`e2e-shots/final-settings.png`、`shell-anomaly_settings.png`；日志 `logs/final.log`、`logs/shell.log`
- 期望：候选列表能出院校。
- 初判根因：**前端**（请求 `page_size=500` 超过后端上限 200，且失败被静默忽略）。

**P7. 知识点"关联题量"恒为 0**
- 模块：知识点全景 `#/panorama`（知识地图同源数据）
- 复现：`#/panorama` → 点任一知识点
- 实际现象：详情面板"关联题量 **0 题**"、"考频 —"；实测前 5 个知识点全部"暂无题目"。但真库 `question_knowledge_links` 有 **6288** 条关联。
- 证据截图：`e2e-shots/targeted-panorama-detail.png`；日志 `logs/targeted2.log`
- 期望：显示真实关联题量。
- 初判根因：**后端/数据**（tree 接口未回填 kp 的 question_count，或关联关系未按当前 subject 口径命中）。

---

### 🟡 一般

**P8. 题库/错题里混有大量 OCR 碎片题，可读性很差**
- 现象：题库列表首题题干就是被截断的解析正文（"1.判决宣告以前一人犯数罪的…故"），并夹带"东坡哥微信：haidongpo8""水木观畴，你身边的考研专家！""[陶宝搜索]"等水印与页码标记；有的题目 `options=null` 却被当作文本题处理。
- 证据：`e2e-shots/quiz-03-question.png`、`quizbank-03-preview-modal.png`；日志 `logs/quiz.log`、`logs/quiz2.log`
- 根因：**数据**（来源为 PDF OCR，未做碎片过滤/水印清洗）。

**P9. 答案字段存在明显异常值并原样展示**
- 现象：刷题时出现 `正确答案：解析`、`正确答案：错误`（answer 字段被填成了"解析"/"错误"这类非答案文本）。
- 证据：`e2e-shots/verify-quiz-reveal-2.png`；日志 `logs/verify.log`、`logs/quiz2.log`
- 根因：**数据**。

**P10. 错题数据里混入测试脏数据**
- 现象：错题详情"我的答案"出现 `___WRONG_FOR_TEST___` 和 `\u0000`（截图可见）。
- 证据：`e2e-shots/evidence-errorreview-caogao.png`
- 根因：**数据**（测试写入未清理）。

**P11. 院校详情"院校概况"内容错位**
- 现象：重庆邮电大学详情页"院校概况"正文是校党委书记/校长的履历（"重庆邮电大学党委书记。曾任…苏森，男，汉族，1971年1月出生…"），而非学校简介。
- 证据：`e2e-shots/kaoyan-03-detail.png`；日志 `logs/kaoyan.log`
- 根因：**数据**（简介回填抓取了人物词条）。

**P12. 院校对比页体验原始**
- 现象：`#/kaoyan/compare` 只有一行"输入院校ID（逗号分隔），最多5所 + 开始对比"，无院校选择器。
- 证据：`e2e-shots/kaoyan-05-compare.png`、`final-kaoyan-compare.png`
- 根因：**前端**（UI 未完成）。

**P13. dev 模式剥离 console，故障被静默吞掉**
- 现象：`vite.config.js` 的 `esbuild: { drop: ['console','debugger'] }` 实测**在 dev 下也生效**——curl 取 `http://127.0.0.1:5173/src/pages/Words.jsx`，`console.*` 出现 **0 次**。
- 影响：像 P1、P6 这种"静默降级"没有任何控制台痕迹，排查成本高。
- 根因：**前端工程配置**（`drop` 应只在生产构建生效）。

---

### ⚪ 轻微

**P14. 全站每页 2 条 React Router v7 future-flag 警告**
- 原文：`⚠️ React Router Future Flag Warning: React Router will begin wrapping state updates in React.startTransition in v7…`
- 根因：前端（react-router-dom 版本提示，可加 future flag 消除）。

**P15. 首页"连续打卡 0 天 / 本周完成 0"等空态**：与后端一致（`week_duration=42分钟→0.7h`、`active_errors=31` 均对得上），属真实空数据，非 bug。

---

## 4. 关于你点名的两项"刚修复"的专项结论

| 你的说法 | 实测结论 |
|---|---|
| 知识地图：点开知识点有"关联知识块/原文摘录"，之前是空的 | ❌ **不成立**。前端**压根没有这个 UI**（全仓 0 命中），知识点不可点、无详情面板；后端 `related_chunks` 数据倒是有的。**修复没有体现在当前运行的前端。** |
| 题库：答案带 `【草稿】` 前缀，刚清理过 | ⚠️ **半对**。`#/quiz`、`#/quiz-bank` 里的答案**已干净**（实测无 `【草稿】`）；但 **错题复盘的"正确答案"仍显示 `【草稿】…`**（实测第 10 条 = `【草稿】B查看答案`），且库内 `analysis` 还有 1576 行残留。**清理只覆盖了 `quiz_questions.answer`，漏了 `error_records.correct_answer` 和 `quiz_questions.analysis`。** |

---

## 5. 证据索引

- 截图目录：`D:\平台\docx\_analysis\e2e-shots\`（66 张，关键：`evidence-errorreview-caogao.png`、`targeted-words-truth.png`、`targeted-kbmap-kp.png`、`targeted-panorama-detail.png`、`quizbank-01-manage.png`）
- 原始日志：`D:\平台\docx\_analysis\_e2e\logs\`（`shell.log` 27 路由基线、`library.log`、`kbmap.log`、`quiz.log`、`quiz2.log`、`words.log`、`errorreview.log`、`kaoyan.log`、`verify.log`、`targeted2.log`、`errcheck.log`、`final.log`）
- 可复跑脚本：`_e2e\` 下 `dump.mjs` / `verify.mjs` / `targeted2.mjs` / `errcheck.mjs` / `final.mjs` / `shell.mjs` / `library.mjs` / `kbmap.mjs` / `quiz.mjs` / `quiz2.mjs` / `words.mjs` / `errorreview.mjs` / `kaoyan.mjs`

---

## 6. 总体结论：这个前端现在能用吗？

**能用一半。** 六大模块里——

- ✅ **能用**：**学习文库**（264 篇真文档、点开有真 OCR 正文）、**题库/刷题**（选→提交→判分→交卷全链路通，答案已干净）、**错题复盘**（31+ 条真错题、详情/知识点关联/AI 归因可点）、**院校数据中心**（583 校、搜索与详情简介可用）。
- ❌ **不能用**：**单词记忆**——整模块展示的是 20 条本地 Mock 单词，不是后端 4569 词真库，翻卡评分不落库（P1）；**知识地图的"知识点详情/关联知识块·原文摘录"**——功能在当前前端不存在，且数电/数学/英语/政治的知识点为 0（P2、P4）。

**另有 5 个严重问题**（错题答案残留 `【草稿】`、题库总量口径自相矛盾、设置页院校候选 422 静默失败、关联题量恒 0），以及若干数据质量问题（OCR 碎片题、异常答案值、测试脏数据混入）。

**建议修复优先级**：P1（单词真库接入）→ P3（补清净 `correct_answer`/`analysis`）→ P4（知识点学科映射）→ P2（要么实现该面板，要么先确认代码是否丢失）→ P6（`page_size` 改 ≤200）。
