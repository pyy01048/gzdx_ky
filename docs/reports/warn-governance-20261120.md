# warn 题治理报告（2026-11-20）

- 明细 CSV：`D:\研途\gzdx_ky\docs\reports\warn-questions-20261120.csv`
- 备份：`D:\研途\题库建设\backup\quiz_questions_20261120_210507.jsonl`
- 回滚 SQL：`D:\研途\gzdx_ky\docs\reports\warn-governance-rollback-20261120.sql`
- 处置：`validation_status='warn'` 的 216 行置 `is_available=false`（软下架，保留数据）

## 按科目

| 科目 | warn 数 |
|---|---|
| 数据结构 | 156 |
| 数学 | 24 |
| 模拟电子技术 | 20 |
| 英语 | 5 |
| 操作系统 | 3 |
| 计算机网络 | 3 |
| 自动控制原理 | 2 |
| 政治 | 1 |
| 数字电子技术 | 1 |
| 计算机学科专业基础408 | 1 |

## 回滚

见上方回滚 SQL：将 `validation_status='warn'` 的行恢复 `is_available=true`。
