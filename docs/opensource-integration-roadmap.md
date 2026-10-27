# 开源项目集成路线图（2026-10-18）

> 目标：吸收百家所长，用成熟开源项目补齐平台短板（OCR 精度 / PDF 结构化 / 水印清洗 / 复习调度）。
> 每项决策按 ADR 记录：背景 → 备选 → 决定 → 代价 → 规避。

## 一、已选定集成的项目

### ADR-001 · DeepSeek-OCR → 二遍精识别引擎（云端 DSW 部署）
- **是什么**：deepseek-ai/DeepSeek-OCR（3B MoE VLM），文档→Markdown（含表格 `<td>`、公式、版面 grounding），支持 Tiny/Small/Base/Large/Gundam 五档分辨率；2026-01 已发布 **DeepSeek-OCR2**，vLLM 官方支持。2026-10-20 发布，Apache 系研究生态活跃。
- **为什么需要**：本地 rapidocr 对扫描版教材（康华光第6版仅提出 55 字）与老真题扫描件效果差；这类「硬件」占比不高但价值最高。
- **备选**：MinerU（AGPL，布局强但需要 torch + 模型全家桶，CPU 慢）/ marker（GPL）/ PaddleOCR-VLM（已在用 Paddle）。→ 决定：**DeepSeek-OCR 做二遍精识别专用后端**，批量第一遍仍用 rapidocr（快、省）。
- **部署位置**：❌ 本地 RTX 4060 8GB（空闲仅 4GB，3B bf16 需 ~7GB）；❌ 云端 2C2G（无 GPU）；✅ **DSW A10-24G**（阿里云，训练间隙可用，ModelScope 有权重镜像，云端无外网限制）。
- **接入方式**：DSW 上起一个 FastAPI 包装（POST image/pdf → markdown/text），注册进 `services/ocr_service.py` 后端链（`OCR_SERVICE_URL` 已 env 化，符合「重算力在家/DSW、云端降级」的既定架构）。
- **代价与规避**：与 LoRA 训练抢 A10 显存 → 训练优先、识别任务排队（DSW 24G：QLoRA 训练 ~14-18G + DeepSeek-OCR bf16 ~7G 并发有 OOM 风险，默认串行）；权重 ~7GB 经 ModelScope 下载。
- **状态**：`tools/ocr/DeepSeek-OCR`（用户已下载源码）；待训练间隙部署。

### ADR-002 · watermark-remover → 入库预处理 + 清洗工具（本地，立即可用）
- **是什么**：jindaoye/watermark-remover（MIT），PyMuPDF 实现 PDF 四法去水印（覆盖/删文本/图像处理/自动检测）+ docx 页眉页脚/文本框水印，支持批量。
- **为什么需要**：知识库 3130 个 PDF 里水印污染是云端体检确认的清洗项（东坡哥/公众号水印）；正文层面的水印文本已经污染了已入库分块。
- **备选**：自研清洗正则（已有 clean_document_watermarks.py，SQLite 时代需 PG 化）→ 决定：**两层组合**——① 文件级：该工具对 `knowledge_base/` 源 PDF 批量去水印后重解析重入库（治本）；② 文本级：PG 化的 clean_document_watermarks 对已入库 content/chunks 洗文本（治标）。
- **接入方式**：作为独立批处理步骤（`tools/ocr/watermark-remover/main.py -b 入目录 出目录`，MIT 允许直接使用），产物存 `knowledge_base_clean/`，对比 hash 后仅对有变化的文件重跑 smart_ingest（--skip-ingested 需配合删除旧文档行——走清洗批次的 batch 回滚框架）。
- **代价与规避**：PyMuPDF 是 AGPL——作为独立命令行工具调用不链接进后端进程，无传染；改文件前自动备份原文件到 `_originals/`。

### ADR-003 · py-fsrs → 复习调度算法内核（候选，下一阶段）
- **是什么**：open-spaced-repetition/py-fsrs（MIT），FSRS-5 间隔重复算法的参考实现。
- **为什么**：本站 `review_schedules` 已按 FSRS 建表（102 分片），调度参数是自算的；FSRS-5 的参数优化（针对个人答题数据优化 w 权重）自研成本高。
- **决定**：暂缓——先把复习闭环数据攒起来（错题/卡片评分记录），数据够了再切换到 py-fsrs 内核 + 参数优化；切换点隔离在 review_scheduler 服务内。

### ADR-004 · go-judge → 代码 OJ 判题沙箱（既有规划，维持）
- 方案 05 既定：独立服务部署（AGPL 隔离），2C2G 云端不挂判题，本地/家节点承担。维持不变，等 OJ 模块排期。

## 二、调研过但不采用（避免过度工程）
| 项目 | 不采用原因 |
|---|---|
| MinerU / marker | 与 DeepSeek-OCR 定位重叠；AGPL/GPL 服务隔离成本；批量第一遍已有 rapidocr + 文本层通道 |
| RAGFlow / LlamaIndex | 自研 RAG 链路已通（pgvector + 重排 + 门控），框架迁移成本 > 收益 |
| Umi-OCR | 桌面 GUI 工具，无库接口，不适合服务端 |
| AnythingLLM/Open WebUI | 整站替换型项目，与自研前端冲突 |

## 三、集成时序（与当前工作线的衔接）
| 阶段 | 动作 | 依赖 |
|---|---|---|
| 现在 | watermark-remover 批量洗 `knowledge_base/` 高价值目录（数电/模电/贵大834）→ 重解析入库 | 本地导入批次结束后执行，避免写冲突 |
| DSW 训练间隙 | DeepSeek-OCR 服务化 + 注册 OCR 后端链 + 3 篇坏文档（55~93 字）试点 | A10 空闲 |
| 数据同步轮 | 服务器知识库同步时带上「已去水印 + 精识别」版本 | 本地导入+清洗完 |
| 复习数据积累后 | py-fsrs 内核评估 | 错题/卡片评分记录 ≥ 数千条 |
