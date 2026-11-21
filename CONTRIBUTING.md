# 贡献指南

个人备考学习项目，欢迎以 issue / PR 形式参与。

## 分支命名

- 修复：`fix/简述`
- 功能：`feat/简述`

## Commit 规范

```
type(scope): 摘要
```
常用 type：feat / fix / deps / docs / refactor / test / chore。

## PR 要求（门禁）

1. 必须过 CI：`backend pytest`（真 PG）、`frontend vitest + lint + build`、`ruff（变更文件）`、
   `gitleaks + pip-audit`、`docs 链接检查`。
2. 数据变更必须附**备份表 + 回滚 SQL + 行数台账**（铁律，见 `docs/README.md` 与 05/11 文档）。
3. Schema 改动：`core/sql/` **新增编号脚本**（禁止改历史脚本，checksum 守卫会中止）；
   同步 ORM 与 `schema_migrations` 账本；更新数据字典。
4. 前端新代码：0 error（eslint）；新页面优先 `.tsx`；新增大依赖（>100KB gzip）需 PR 说明理由。
5. 业务代码必须带测试；覆盖率只升不降（ratchet）。

## 覆盖率与评测 ratchet

- 后端：`pytest --cov` 产出报告；核心域（kb_pipeline / ai_router / search / scope / security）目标 ≥80%，
  全仓基线先测量再逐月上调（只升不降）。
- RAG：嵌入模型 / Ollama 模型 tag / RRF 权重 / 分块参数 / 微调版本五类变更，
  PR 必须附
  `python -m services.rag_eval --suite all --compare tests/eval/baseline.json` 的对比报告；
  关键指标低于基线 -2% 不合并。

## 本地检查

```powershell
pip install -r backend-main-fastapi/requirements.txt -r backend-main-fastapi/requirements-dev.txt
cd backend-main-fastapi
python -m pytest tests -q --timeout=300
python scripts/execute_core_sql.py --status     # 迁移账本状态
ruff check .
pre-commit run --all-files

cd ..\frontend
npm ci
npm run lint
npm test
npm run build
```

## 数据与合规

- 采集：串行限速、仅公开接口、请求留痕；新增数据来源登记到 `docs/guides/data-sources.md`。
- 题目导入必须过 `services/quiz_validator.py` 质量门（结构规则 + 抽样 ≥99%，否则整批拒绝）。
