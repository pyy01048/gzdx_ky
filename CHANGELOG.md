# Changelog

本文件记录每次发布的关键变更。格式参考 Keep a Changelog，版本遵循语义化。

## [Unreleased]

### Security
- 升级 fastapi 0.104.1 → 0.115.14（连带 starlette ≥0.40，修复 CVE-2024-47874 multipart DoS）
- 升级 python-multipart 0.0.6 → 0.0.20（修复 CVE-2024-53981 畸形 boundary CPU 空转、CVE-2024-24762 ReDoS）
- 升级 pypdf 4.2.0 → 5.4.0（累积解析死循环/资源耗尽修复，保护上传 PDF 解析入口）
- Pillow 统一取 ≥10.4 安全修复线

### Changed
- 40+ 数据脚本的硬编码数据库口令全部迁移到 `scripts/_conn.py`（唯一连接来源，口令只从 .env 的 PG_PASSWORD 读取）
- 两份 QA 报告中的明文 DSN 脱敏

### Added
- `scripts/_conn.py` 统一连接入口
- `requirements-dev.txt` 开发/测试依赖（本地与 CI 同源）
- pre-commit + gitleaks 提交链路密钥扫描（含大文件 >500KB 拦截）
- LICENSE (MIT + 内容版权声明) / SECURITY.md / CONTRIBUTING.md / dependabot / issue 模板

### Removed
- 解除跟踪：deploy 下 14 个部署 tar.gz、数据库 dump、备份 SQL、调试截图、第三方 vendor 整仓、临时抓取产物

## [0.x] 历史版本

- 路由域化重构 + 13 门类爬虫全量覆盖 + 记忆三层 + 枚举统一（a7f92ea）
- 0854/0855 等学科全量采集、分类归纳层、多 OCR 引擎统一层
