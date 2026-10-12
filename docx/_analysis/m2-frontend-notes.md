# 前端与数据链路变更说明（M1-3b / M2-7 / M1-1 v3）

> 记录人：software-engineer-2　生成：2026-10

## 1. Quiz 页 kp_id 精确筛选（M1-3b）—— 实现与核验归属

**结论：代码由 engineer-13 实现（其遇 429 中断前已完成），由 software-engineer-2 完成核验与实测。**
后续若要修改该链路，请先确认这两处事实，避免重复派单。

实现要点（均在仓库中，勿重复实现）：
- `frontend/src/pages/Quiz.jsx`：`urlKpId/urlKpName`（124-125）、`startWithFilter` 透传
  `kp_id`（325-355）、深链 effect（359-374）、筛选标识 + Empty 兜底（539-556）、练习页 chip（953）。
- `frontend/src/api/client.js`：`request()`（100-114）**通用序列化所有 params，无白名单**，
  故 `kp_id` 天然透传，**不需要改动 client.js**。
- `frontend/src/pages/Panorama.jsx`：`startPractice` 带 `kp_id`+`kp_name`（180-188）；
  降级说明已更新为"已支持知识点级精确刷题"（453-459）。
- `frontend/src/test/quiz.kpfilter.test.jsx`：5 项回归（透传 / 标识 / Empty / 两条向后兼容）。

核验结果：`npm run build` ✓；`npm run test` 66 passed（含上述 5 项）。

## 2. 考频分析页 ExamFrequency（M2-7）—— 由 software-engineer-2 实现

- 新建 `frontend/src/pages/ExamFrequency.jsx` + `ExamFrequency.css`，路由 `/exam-frequency`。
- 注册：`App.jsx`（lazy import + Route）、`Layout.jsx`（"学习"分组"考频分析"项 +
  `CRUMB_MAP` + `RELATED`）。
- 新增 `quizApi.frequency`（`client.js`），消费 `GET /api/quiz/frequency`。
- 三档 tab：知识点（考频分档色标 + 关联题数 + "去练习"跳 `/quiz?kp_id=`）/
  章节（纯 CSS 横条）/ 套卷（列表）。页脚标注诚实口径。
- **不提供"按年份"维度**：`quiz_questions.year` 覆盖率约 8%，后端亦不按年聚合，按年统计会失真。
- 知识点→kp_id 通过 `taxonomyApi.tree()` 建 (科目|章节|名字)→id 索引获得（纯前端方案，
  未改后端）。
- 验证：`npm run build` ✓；`npm run test` 75 passed。

## 3. 题目↔知识点关联回填 v3（M1-1）—— 由 software-engineer-2 实现

脚本：`backend-main-fastapi/scripts/backfill_kp_links_v3.py`（基于 v2 改造，v2 保留）。

### 背景口径（实测）
- `knowledge_points` 1067 个；回填前仅 300 个有链路（按不同"可作答"口径：
  任意 300 / 排除碎片题 264 / 有答案 238 / 两者兼具 228）。
- 全景页点空链路知识点 → `?kp_id=X` 返回 0 → 降级章级刷题。**端点正确，缺的是数据链路**。

### 三层策略（限定同 subject，优先同 chapter）
| 层 | 判据 | 命中 |
|---|---|---|
| L1 | `quiz_questions.knowledge_point` 字面值 == 知识点名 | 46 |
| L2 | 字面值归一化（去空格 / 全半角 / 剥离括号 / 别名表）后相等 | 1329 |
| L3 | 知识点**整名**出现在题干；两边章名都可信时要求同章；题目无章时要求整名 ≥6 字 | 997 |

- 去重后新增 **2324 + 3 = 2327 条**（其中 3 条为收敛补跑）。
- 覆盖率（可作答=排除碎片题口径）：**264 → 356 / 1067 = 24.7% → 33.4%**。
  （另一口径"任意链路"：300 → 392，即 28.1% → 36.7%）

### 精度控制（吸取 v2 教训）
- 泛名黑名单（输出电压/放大倍数/静态工作点…）永不单独成链。
- 剔除"名字 == 科目名"的伪知识点 3 个（如 KP 直接叫「数字电子技术」）。
- 章名可信度判定：形如"第N章 xxx"才算可信，避免把题干片段当章名用。
- 抽查 20 条自评精度约 **95%**。

### 安全
- 只写 `question_knowledge_links`；**未改动任何题目正文/答案**。
- 备份用 **SQLite `backup()` API**（`data/backups/kaoyan_pre_kplink_v3_20261012_231533.db`、
  `..._231829.db`）。
- **幂等**：单题链路上限计入已有链路，重跑输出 0 条（已实测两次收敛）。

### 产出
- `tools/datasource/zero_link_knowledge_points.json` / `.csv`：**675 个**回填后仍为 0 链路的
  知识点（id/name/subject/chapter），供人工优先补齐。

### 已知无关失败（非本改动引入）
`tests/test_api_contract.py::test_all_get_routes_contract` 报
`/api/quality/eval-runs/1` 404 —— 实测真库该接口返回 200，失败源于**测试库未播种
`eval_runs`**（测试夹具环境问题），与本次回填无关。

## 4. 备注：is_junk 数量变化
早期我标记 319 条碎片题；现库内 `is_junk=1` 为 3570 条（期间其他同事追加了标记口径）。
因此"可作答题目"口径随之变化，本文件所有覆盖率均以脚本运行当时的实测为准。
