# AI 与模型体系

> 最后核对：2026-11-20 · commit a7f92ea · 维护人：pyy

## 1. 路由与选型

```
问题 ──► ai_router.detect_subject ──► 分科选模型
                                   ├─ 本地 Ollama（按显存判定可跑模型）
                                   └─ 云端 API（兜底，模型名记录到评测报告）
```

| 环节 | 实现 | 位置 |
|---|---|---|
| 科目识别 / 题型分类 | 规则 + 关键词 | `services/ai_router.py` |
| 本地模型清单 | 按显存判定（8GB：deepseek-r1:7b / qwen3:8b / qwen3:4b） | `services/model_registry.py` |
| 检索 | jieba BM25（GIN）+ pgvector KNN + RRF | `services/search_service.py` |
| 嵌入 | bge-small-zh-v1.5（fastembed 本地，数据不出网） | `kb_pipeline` |
| 重排 | 独立 reranker 微服务（家庭节点 8140，Tailscale） | `backend-reranker/` |
| OCR | RapidOCR 主链 + 可选 PP-OCRv5 + GPU 后端降级链 | `services/ocr_router.py` |
| 微调 | Qwen2.5-3B + LoRA + 评测 | `lora_finetune.py` / `eval_qa_model.py` / `training/pai_dsw` |

## 2. 降级链（必须保证单点故障仍可用）

| 组件 | 首选 | 降级 1 | 降级 2 |
|---|---|---|---|
| 答疑模型 | 本地 Ollama | 云端 API | 明确提示"AI 暂不可用"（不静默编答案） |
| 检索 | FTS + 向量 + RRF | 仅 FTS | 关键词提示 |
| OCR | 家庭节点 GPU 服务 | 本地 RapidOCR | PP-OCRv5（可选） |
| 重排 | 家庭节点 reranker | 跳过重排（RRF 原序） | — |

## 3. 质量保障（RAG 评测）

- 评测脚本：`python -m services.rag_eval --suite all --compare tests/eval/baseline.json`
- 指标：检索 Hit@5 / MRR@10；答疑要点覆盖率 / 引用正确率 / 拒答正确率。
- 评测集：`tests/eval/`（检索 ≥200、答疑 ≥100；当前为种子样例，需在真实库上扩充并人工审核）。
- 回归闸：嵌入模型 / Ollama tag / RRF 权重 / 分块参数 / 微调版本五类变更，PR 必附对比报告，
  关键指标低于基线 -2% → 不合并（退出码 1）。
- OCR 质量：`scripts/diagnostics/check_ocr_quality.py` 的噪声指标纳入同一报告体系。

## 4. 显存与并发口径（8GB 笔记本）

| 场景 | 建议 |
|---|---|
| 单纯答疑 | qwen3:8b（4bit）或 deepseek-r1:7b，二选一常驻 |
| 答疑 + OCR 同时 | 用 qwen3:4b，OCR 走独立进程 |
| 批量抽取/结构化 | 夜间批处理，避免与交互抢占 |

## 5. 运维要点

- Ollama 只监听 Tailscale IP（`OLLAMA_HOST=100.92.154.42:11434`），绝不 `0.0.0.0`。
- 旁路三服务（OCR/rerank/Ollama）统一校验 `SERVICE_TOKEN`，错误 token 必须 401。
- 云端兜底模型名写入评测报告（同名模型静默升级是趋势污染源）。
- 模型变更后必须跑评测并留档于 `docs/reports/rag-eval-*.md`。
