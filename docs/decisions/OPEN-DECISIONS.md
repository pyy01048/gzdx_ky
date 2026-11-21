# OPEN-DECISIONS - 悬而未决登记册

> 项目：考研备考平台（gzdx_ky）
> 规范：只追加 + 就地关闭（OPEN → RESOLVED 补 Resolution）。每次阶段开始时复现未决项到工作上下文最前面。
> 最后一次集中核对：2026-11-20（代码与迁移现状逐项对照，见各条 Resolution）。

| Date | Source | Open Item | Related Constraints | Current Leaning | Blocked By | Resolves When | Status |
|------|--------|-----------|---------------------|-----------------|------------|---------------|--------|
| 2026-10-13 | 用户指令 | 数据库引擎选型：SQLite → PostgreSQL | 报告24判定 PG 是唯一真值得换的一层 | 已实施：PostgreSQL 16 + pgvector | 无 | 迁移验证通过 | RESOLVED 2026-10-14（ADR-001） |
| 2026-10-13 | 实测 | pgvector 在 Windows 便携版是否可用 | 61041 分块仅 18422 有向量 | 已实施：`VECTOR_BACKEND=pgvector`，向量随分块补全 | 无 | 探测通过 | RESOLVED 2026-10-14 |
| 2026-10-13 | 实测 | 中文全文检索方案 | PG 内置无中文分词 | 已实施：jieba 分词 + tsvector + GIN，RRF 融合 | 无 | 检索准确率验收 | RESOLVED 2026-10-14（评测见 10 文档） |
| 2026-10-13 | 实测 | 科目命名不统一 | 同一类科目多个名字 | 已实施：taxonomy 权威 + 别名表 | 无 | ADR-002 落盘 | RESOLVED 2026-10-14（ADR-002 Phase 1） |
| 2026-10-13 | 实测 | 无关科目污染（法硕/西综/管综文档） | 与目标专业无关 | 已按"标记隔离不删除"处理 | 无 | 标记完成 | RESOLVED 2026-11-20（`documents.is_junk` 隔离，未见业务引用） |
| 2026-10-13 | 实测 | 4710 题无选项的处理策略 | 刷题无法作答 | 已多轮治理；216 道 warn 题 2026-11-20 软下架（保留数据） | 无 | 处置率 100% | RESOLVED 2026-11-20（见 docs/reports/warn-governance-20261120.md） |
| 2026-10-13 | 用户诉求 | 导入准确率 99% 的验收机制 | 需可验证 | **已落地为代码**：`services/quiz_validator.py`（结构规则 + 抽样验收，<99% 整批拒绝） | 无 | 验证器上线 | RESOLVED 2026-11-20 |
| 2026-10-13 | 用户诉求 | 转格式后是否删除源文件 | 用户自认"不一定能信" | **已决策：保留归档副本，不物理删除**（数据可回溯优先；磁盘成本可控） | 无 | 用户确认 | RESOLVED 2026-11-20（用户授权决策） |
| 2026-11-20 | 架构 | code_oj 恢复条件 | 2C2G 判题子进程风险 | **已决策：维持不挂载**；恢复条件 = 服务器 ≥4C4G + 判题沙箱（nsjail/docker 资源限额）+ 评审通过 | 服务器升配 | 条件满足后另立 ADR | RESOLVED 2026-11-20（决策：暂不恢复，UI 已明示离线） |
| 2026-11-20 | 架构 | 真题单一真相源（exam / papers 双轨） | 两套 API 读不同表，导入需双写 | **已拍板**：paper_questions 为唯一存储；exam 为模考会话层、papers 为卷面浏览层 | 无 | ADR-004 Accepted | RESOLVED 2026-11-20（ADR-004 Accepted，实施另列任务） |
| 2026-11-20 | 依赖审计 | 服务器 Python 3.10 无法安装 fastapi 0.165 / starlette 1.10 / Pillow 13（均要求 `requires_python>=3.11`），导致服务器组合仍带 starlette / Pillow 系列 CVE | 服务器需重装解释器才能根治；CI runner 3.13 的 `pip-audit` 绿不代表服务器组合绿 | **倾向升级服务器解释器到 3.12**（与应用本机验证环境对齐），过渡期在部署清单里明示残余风险 | 服务器操作窗口 | 服务器 `python -V` ≥3.11 且 `pip-audit` 无告警 | **OPEN** |

## 已关闭（RESOLVED）

| 项 | Resolution | 证据 |
|---|---|---|
| SQLite → PostgreSQL | PG16 运行，`DATABASE_BACKEND=postgresql`；`core/migrations.py` 账本化结构变更 | ADR-001；`scripts/execute_core_sql.py --status` |
| pgvector 可用性 | `VECTOR_BACKEND=pgvector`，`knowledge_chunks_vec` 全量重建 | `/api/health` → `kb.vector_store` |
| 中文检索 | jieba + GIN + RRF 融合 | `services/search_service.py`；RAG 评测 |
| 科目命名 | taxonomy 权威树 + 别名映射 | ADR-002；`subject_config` 只读视图 |
| 无关科目隔离 | `documents.is_junk` 标记隔离，可恢复 | 管理端文档页 |
| 4710 题无选项 | 多轮治理 + 216 warn 题软下架 | `docs/reports/warn-governance-20261120.md` |
| 99% 准确率 | `quiz_validator` 把"结构规则 + 抽样 ≥99% + 整批拒绝"固化为代码 | `tests/test_quiz_validator.py` |

## 已升格为 ADR

| ADR | 主题 | 状态 |
|-----|------|------|
| ADR-001 | PostgreSQL 迁移决策 | Accepted（已实施） |
| ADR-002 | 科目单一数据源 | Accepted（Phase 1 已实施；Phase 2 = orm_aliases 退场） |
| ADR-003 | 题目标准 Schema | Accepted（已实施） |
| ADR-004 | 真题单一真相源 | Accepted（2026-11-20 拍板；实施另列任务） |

## 剩余 OPEN 项（1）

2026-11-20 收口：源文件保留（不删）、code_oj 暂不恢复（条件已书面化）、真题单一真相源
按 ADR-004 执行。

2026-11-20 夜间新增 1 项：**服务器解释器 3.10 → ≥3.11**（否则 fastapi/starlette/Pillow
残余 CVE 无法由依赖侧清零）。后续如出现新的未决事项，按"只追加 + 就地关闭"继续登记。
