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

## PR 要求

1. 必须过 CI（pytest、ruff、gitleaks）
2. 数据变更必须附备份与回滚 SQL
3. 涉及 schema 改动时：`core/sql/` 走编号序列，并同步 ORM 与别名层

## 本地检查

```powershell
pip install -r backend-main-fastapi/requirements.txt -r backend-main-fastapi/requirements-dev.txt
cd backend-main-fastapi
python -m pytest tests -q --timeout=300
ruff check .
pre-commit run --all-files
```
