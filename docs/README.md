# 文档中心（唯一入口）

> 分层：**guides（现行指南）** / **decisions（架构决策）** / **reports（历史报告，只增不改）** / **plan-gap & 落地方案（专项方案）**。
> 现行指南头部标「最后核对日期 + commit」，超过 90 天未核对视为 stale。
> 本索引由 `backend-main-fastapi/scripts/diagnostics/check_doc_links.py` 在 CI 校验链接有效性。

## 一、现行指南（guides/）

| 文档 | 内容 | 最后核对 |
|---|---|---|
| [quickstart](guides/quickstart.md) | 环境、依赖、五种启动方式、自检与排障 | 2026-11-20 |
| [architecture](guides/architecture.md) | 6 域路由 / 服务分层 / 数据流 / 关键约束 | 2026-11-20 |
| [ai-system](guides/ai-system.md) | 模型路由、显存口径、降级链、RAG 评测 | 2026-11-20 |
| [kb-pipeline](guides/kb-pipeline.md) | 文档入库、OCR、分块、向量、体检自愈 | 2026-11-20 |
| [data-dictionary](data-dictionary.md) | 表/列/行数/写入方（自动生成） | 生成时 |
| [data-sources](guides/data-sources.md) | 数据来源与许可证台账 | 2026-11-20 |
| [backup-restore-drill](guides/backup-restore-drill.md) | 备份恢复演练（每季度） | 2026-11-20 |
| [deployment](guides/deployment.md) | 指向唯一部署真相 `deploy/DEPLOY.md` | 2026-11-20 |

## 二、架构决策（decisions/）

| 文档 | 状态 |
|---|---|
| [ADR-001 PostgreSQL 迁移](decisions/ADR-001-postgresql-migration.md) | Accepted（已实施） |
| [ADR-002 科目单源](decisions/ADR-002-subject-single-source.md) | Accepted（Phase 1 已实施；Phase 2 = orm_aliases 退场） |
| [ADR-003 题目 canonical schema](decisions/ADR-003-question-canonical-schema.md) | Accepted（已实施） |
| [ADR-004 真题单一真相源](decisions/ADR-004-past-exam-single-source.md) | Accepted（已拍板，实施中） |
| [OPEN-DECISIONS](decisions/OPEN-DECISIONS.md) | 登记册（已落地项已关闭） |

## 三、历史报告（reports/，只增不改）

- 全线与 QA：[QA回归测试报告-20261028](QA回归测试报告-20261028.md)、[P0-P1修复报告](P0-P1修复报告-20261028.md)、[全线检查问题清单](全线检查问题清单.md)
- 本轮完善落地：[2026-11-20-完善方案落地报告](reports/2026-11-20-完善方案落地报告.md)
- 数据治理：[warn-governance-20261120](reports/warn-governance-20261120.md)、[dedup-cross-source-20261120](reports/dedup-cross-source-20261120_211707.md)、[08工学题库导入报告](reports/08工学题库导入报告-20261120.md)
- 外部资产并入 + 工学学科评估上线：[school-eval-integration-20261121](reports/school-eval-integration-20261121.md)
- 归档文档内部互引允许失效（归档不改），链接以当时仓库为准。

## 四、专项方案

- [plan-gap/](plan-gap/)：差距核查系列（含核验汇总）
- [落地方案/](落地方案/)：各模块落地设计与执行对照
- [完善方案/](完善方案/00-完善总清单与路线图.md)：外部审计方案（2026-11-21 按用户指示并入仓库，14 篇）
- 原始数据资产：`data-assets/`（题库建设 / 08工学数据包 / 工学院校评价库，gitignore 不入库；目录内有 README 说明消费状态，新克隆不含此目录属预期）

## 五、文档规范

1. 新增现行指南放 `guides/`，头部写：`> 最后核对：YYYY-MM-DD · commit <sha> · 维护人：<name>`。
2. 每轮体检/修复/QA 报告放 `docs/reports/`，命名 `<主题>-<YYYYMMDD>.md`，只增不改。
3. 决策变更走 ADR：新决策新建编号文件，旧文件只改状态与 Resolution。
4. 数据数字一律来自 `readme_counts.py`，不手填。
