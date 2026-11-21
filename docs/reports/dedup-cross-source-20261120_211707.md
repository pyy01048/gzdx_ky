# 跨源去重合并报告（2026-11-20）

- 判重键：归一化题干 + 科目 + 章节 + 年份（年份豁免合法跨年同题）
- 重复组数：364 ｜ 需合并行：429
- 备份：`D:\研途\题库建设\backup\quiz_questions_20261120_211707.jsonl`
- 回滚脚本：`D:\研途\gzdx_ky\docs\reports\rollback_dedup_quiz_20261120_211707.py`

## 按科目（需合并行）

| 科目 | 需合并行 |
|---|---|
| 英语 | 352 |
| 数学 | 46 |
| 数据结构 | 9 |
| 自动控制原理 | 7 |
| 政治 | 4 |
| 计算机网络 | 3 |
| 操作系统 | 2 |
| 模拟电子技术 | 2 |
| 电路 | 2 |
| 数字电子技术 | 1 |
| 计算机学科专业基础408 | 1 |

## 关联行迁移

| 表 | 迁移行数 |
|---|---|
| answer_records | 1 |
| error_records | 1 |
| misconceptions | 1 |
| paper_questions | 252 |
| question_images | 36 |
| question_knowledge_links | 3 |

## 关联行去重（迁移后）

| 表 | 删除重复行 |
|---|---|
| question_knowledge_links | 71 |
| question_images | 0 |

## 删除题数：429

## 保留策略

保留优先级：真题(past_exam) > 教材(textbook) > 章节习题 > 模拟(mock_exam) > 开源导入 > 其余；同优先级取解析最全者，再按 id 升序。
