# 考研学习平台（gzdx_ky）

面向 **贵州大学 834 电子技术基础**（数字电子技术 + 模拟电子技术）等科目的备考系统：
扫描版真题 OCR 入库 → 章节/知识点/题型结构化 → 刷题与错题本 → 复习排程 → 本地模型优先的 AI 答疑。
**数据不出网**：本地模型 + 本地知识库；需要更强能力时可选云端 API 兜底。

[![CI](https://github.com/pyy01048/gzdx_ky/actions/workflows/ci.yml/badge.svg)](https://github.com/pyy01048/gzdx_ky/actions/workflows/ci.yml)

## 快速开始（10 行）

```bash
cd backend-main-fastapi
pip install -r requirements.txt
python scripts/diagnostics/check_env.py     # 环境自检：明确告诉你能跑/缺什么
python main.py                              # 或双击根目录「启动.bat」
# 浏览器打开 http://127.0.0.1:8000
```

> 前端产物已构建在 `backend-main-fastapi/static/`，**不改前端就不需要 npm**。
> 完整步骤（PostgreSQL / 五个启动方式 / 局域网）见 [docs/guides/quickstart.md](docs/guides/quickstart.md)。

## 功能总览

| 模块 | 内容 |
|---|---|
| 题库与刷题 | 章节练习 / 真题模式 / 组卷模考 / 交卷判分 / 错题本 / 收藏 |
| 知识库 | 文档上传 → OCR → 分块 → 向量 + 中文全文检索（jieba BM25 + pgvector + RRF） |
| AI 答疑 | 科目识别 → 分科路由 → 本地 Ollama 优先 / 云端兜底；答案带引用来源 |
| 复习 | 艾宾浩斯 / FSRS 排程、复习队列、掌握度门控 |
| 规划 | 阶段 / 月 / 周 / 日计划、任务清单、学习时长与热力图 |
| 择校数据 | 院校 / 专业 / 分数线 / 国家线 / 自划线（持续采集中） |
| 管理端 | 文档与知识库体检、题库质量、数据导入、平台配置 |

## 数据实况

<!-- COUNTS:BEGIN（自动生成，勿手改；刷新：python backend-main-fastapi/scripts/diagnostics/readme_counts.py --write-readme）-->

| 指标 | 数值 | 口径日期 |
|---|---|---|
| 可用题目 | 35,107 | 2026-11-20 |
| 其中真题 | 2,583 | 2026-11-20 |
| 单词 | 17,376 | 2026-11-20 |
| 知识分块 | 81,348 | 2026-11-20 |
| 知识点 | 26,873 | 2026-11-20 |
| 文档 | 2,666 | 2026-11-20 |
| 院校 | 1,150 | 2026-11-20 |
| 专业 | 18,596 | 2026-11-20 |
| 分数线行 | 182,748 | 2026-11-20 |
| 公告 | 1,093 | 2026-11-20 |
| 试卷 | 85 | 2026-11-20 |

<!-- COUNTS:END -->

> 数字只允许由 `scripts/diagnostics/readme_counts.py --write-readme` 生成，禁止手填（历次口径漂移的根因）。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI · SQLAlchemy · PostgreSQL 16 + pgvector |
| 前端 | React 18 · Vite 5 · Zustand · React Router 6 |
| 检索 | PostgreSQL GIN（jieba 分词）+ pgvector KNN + RRF 融合 |
| AI | Ollama（本地，按显存选型）/ 云端 API 兜底；bge-small-zh 本地嵌入 |
| OCR | RapidOCR 主链 + 可选 PP-OCRv5 微服务 + GPU 后端降级链 |
| 部署 | Nginx + systemd + Tailscale 内网；每日加密备份 |

## 文档索引

- **文档中心（唯一入口）**：[docs/README.md](docs/README.md)
- 常用：[快速开始](docs/guides/quickstart.md) · [架构总览](docs/guides/architecture.md) · [AI 体系](docs/guides/ai-system.md) · [部署 Runbook](deploy/DEPLOY.md)
- 数据字典：[docs/data-dictionary.md](docs/data-dictionary.md)（自动生成）
- 决策记录：[docs/decisions/](docs/decisions/)（ADR-001~004 + OPEN-DECISIONS）

## 已知短板（诚实清单）

| 短板 | 现状 | 对应方案 |
|---|---|---|
| 数电/模电/电路专业课真题 | 源文档已入知识库，逐题结构化尚未完成 | 11-数据内容与题库建设 |
| 分数线 major_id | 历史行大量为 NULL，二次回填脚本已就绪待跑 | 05/11 |
| 题库 warn / 重复题干 | 治理脚本与质量门已就绪，存量待批量处置 | 11 |
| RAG 评测基线 | 评测脚本与种子集已就绪，需在真实库上扩充到 200/100 条 | 10 |
| 公网入口 HTTPS | 安全配置与三套方案已备好，需在服务器执行（见部署文档 §10/§11） | 08 |

## 版权与使用边界

- **代码**：MIT（见 [LICENSE](LICENSE)）。
- **题库 / 教材 / 真题 / 词库**：版权归原权利人，本平台仅限**个人学习研究**使用，不提供公开分发。
- 来源台账见 [docs/guides/data-sources.md](docs/guides/data-sources.md)。

## 参与开发

`CONTRIBUTING.md`（提交规范 / 测试与 lint 门禁 / 覆盖率与评测 ratchet）· `SECURITY.md`（漏洞报告渠道）。
