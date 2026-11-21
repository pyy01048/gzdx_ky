# ADR-004: 真题单一真相源（paper_questions canonical，exam/papers 分层）

## Status

Accepted（2026-11-20 拍板）。实施分两步：① exam 组卷改读 paper_questions；
② 专业课真题导入按本 ADR 落表并结束双写。实施进度在 OPEN-DECISIONS 之外另列任务跟踪。

## Background

两条真题链路并存，数据分叉：

| 链路 | 表 | 规模 | 消费方 | 职责 |
|---|---|---|---|---|
| `/api/papers` | `papers` + `paper_questions` | 85 卷 / 2,379 题 | 真题中心卷面浏览 | 卷面结构（year/paper/题号） |
| `/api/exam` | 组卷策略 + `exam_sessions` + `exam_answers` | 运行时生成 | 模考流程 UI | 组卷 / 限时 / 判分 |

问题：11 文档的专业课真题导入若不定表，每批都要双写；`is_past_exam` 口径也会分叉。

## Decision（推荐）

1. **`paper_questions` 是真题唯一存储**（canonical schema 对齐 ADR-003）。
   `quiz_questions` 中的真题行迁移/映射过来，`is_past_exam` / `year` / `paper` / `question_no` 统一口径。
2. `exam` API 保留为**模考会话层**（组卷策略 / 限时 / 判分），底层读 `paper_questions`；
   `papers` API 保留为**卷面浏览层**。两 API 职责分层，不再各存一份题。
3. 过渡期：专业课真题导入按 `paper_questions` 为主、`quiz_questions` 同步（同一 batch 内双写），
   迁移完成后删除双写。
4. 迁移脚本进 `scripts/migrations/`，备份 + 回滚 + 行数台账（05/11 铁律）。

## Consequences

- 正面：导入一处落库；真题筛选/组卷口径一致；`is_past_exam` 单一来源。
- 代价：过渡期双写需守住 batch_id；exam 组卷查询需改底层（一次性改造）。
- 风险：历史 `exam_*` 会话引用旧题 id，迁移时外键需改挂（`ON DELETE SET NULL` 已有）。

## Acceptance

- [ ] 导入管线按本 ADR 落表，`is_past_exam` 全量一致
- [ ] exam 组卷全部读 `paper_questions`（旧路径删除或兼容层登记）
- [ ] 双写期结束，双写代码删除
- [ ] 迁移报告与回滚 SQL 留档 `docs/reports/`
