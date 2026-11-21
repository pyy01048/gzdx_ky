# 10 · AI 与 RAG 质量保障

> 覆盖问题：R16（检索/答疑无评测基线，模型变更无法量化回归）
> 优先级：P1 ｜ 预计工作量：评测集 M；评测脚本 M；常态化 S

---

## 1. 现状与证据

### 1.1 已建成的 AI 链路（保持）

| 层 | 实现 | 位置 |
|---|---|---|
| 路由 | 科目识别 → 分科选模型 → 本地 Ollama 优先 → 云端兜底 | services/ai_router.py |
| 选型 | 按本机显存判定可跑模型（8GB 口径：deepseek-r1:7b / qwen3:8b / qwen3:4b） | services/model_registry.py |
| 检索 | PG GIN（jieba BM25）+ pgvector KNN + RRF 融合；SQLite 降级 FTS5 | services/search_service.py |
| 嵌入 | bge-small-zh-v1.5（fastembed 本地，数据不出网） | requirements + kb_pipeline |
| 重排 | 独立 reranker 微服务（家庭节点 8140，Tailscale） | backend-reranker/ |
| OCR | RapidOCR 主链 + 可选 PP-OCRv5 微服务 + GPU 后端路由降级链 | services/ocr_router.py |
| 微调 | Qwen2.5-3B + LoRA 全流程脚本 + 评测脚本 | lora_finetune.py / eval_qa_model.py / training/pai_dsw |
| 体检 | OCR 噪声量化脚本 | scripts/diagnostics/check_ocr_quality.py |

### 1.2 缺口：质量是"感觉"，不是"数字"

1. **无检索评测集**：81,348 个分块、5,262 个知识点，但"查一个知识点能否命中正确分块"没有 golden 标注。换嵌入模型（bge-small→bge-m3）、调分块策略、改 RRF 权重，**无法回答"变好了还是变坏了"**。
2. **无答疑质量基线**：eval_qa_model.py 面向微调模型评测，但 RAG 端到端（检索→拼装→生成→引用）没有固定问题集与指标；README 自述 AI 讲题已回流盲点池闭环，但闭环的"讲得对不对"无量化。
3. **引用正确率未校验**：RAG 标注来源是亮点，但"标注的来源是否真的支撑答案"没有自动检查——幻觉引用是 RAG 最伤信任的失败模式。
4. **模型变更无回归闸**：Ollama 拉新模型、云端 API 换版本、微调迭代 v2→v3（training/pai_dsw/data 已有 v2/v3 train.jsonl），都没有"上线前跑一遍评测集"的机制。
5. README 引用的 `docs/答疑模型训练指南.md`、`docs/模型选型与分科路由.md` 不在仓库（12 文档处理），AI 体系的运维知识散落在报告里。

---

## 2. 完善标准

1. **两个 golden 集**：检索评测集 ≥200 条（query→应命中分块/知识点），答疑评测集 ≥100 条（问题→标准答案要点→应引用来源），覆盖 16 科且数电/模电/电路重点加权（备考主目标）。
2. **指标定义固化**：检索 Hit@5 / MRR@10；答疑要点覆盖率 / 引用正确率 / 拒答正确率（知识库没有的题应承认没有）；OCR 字准率抽样。
3. **评测脚本一键跑**：`python -m services.rag_eval --suite retrieval|qa|all`，输出 JSON + Markdown 报告入 docs/reports/。
4. **变更回归闸**：换嵌入/换模型/改分块/改 RRF 权重/微调新版本，必须先跑评测集，关键指标不得低于基线 -2%（写入 CONTRIBUTING）。
5. 评测集本身版本化（JSONL 入库），扩充有审核记录； nightly/每周定时跑，趋势可见。

---

## 3. 落地步骤

### 3.1 构建检索 golden 集（M，半自动）

数据源就在库里，不需要外部标注：
```python
# scripts/tools/build_rag_eval_set.py
# 思路：
# 1) 从 quiz_questions 抽题干（优先 is_past_exam=true 的数电/模电/电路题）
#    → query = 题干前 80 字；gold = 题目挂靠的 knowledge_point_id 及其关联分块
# 2) 从 knowledge_points 抽名称+描述 → query = "什么是<name>"；gold = 该 kp 的 source chunks
# 3) 从 documents 抽章节标题 → query = 标题；gold = 该章节分块
# 4) 人工审核 200 条（每条 1 分钟：gold 是否真的能回答 query），剔除错题挂错 kp 的噪声
# 输出：tests/eval/retrieval_golden.jsonl
#   {"id":"r001","query":"...","gold_chunk_ids":[123,456],"gold_kp_ids":[78],"subject":"数字电子技术"}
```
⚠️ 题目→知识点挂靠本身有噪声（11 文档在治理），审核步骤不可省；审核记录留 `tests/eval/README.md`。

### 3.2 构建答疑 golden 集（M）

```jsonl
{"id":"q001","subject":"数字电子技术","question":"用卡诺图化简 F(A,B,C,D)=Σm(0,2,5,7,8,10,13,15)","answer_points":["BD","B'D'","最简与或式"],"gold_doc_ids":[...],"type":"计算"}
{"id":"q002","subject":"政治","question":"...","answer_points":[...],"type":"记忆"}
{"id":"q090","question":"<知识库肯定没有的偏题>","expect_refuse":true,"type":"拒答"}
```
- 100 条构成：数电/模电/电路 40、数学/英语/政治 30、408/信号/通信 20、拒答样本 10。
- 答案要点从题库解析（345 题有解析）+ 教材分块提炼，人工确认。
- 判分用**要点匹配 + LLM-as-judge 双轨**：要点命中做硬指标；judge（用云端强模型）评"答案是否覆盖要点且无事实错误"，judge prompt 固定版本化，避免 judge 漂移污染趋势。

### 3.3 评测脚本（M）

```python
# services/rag_eval.py（骨架）
def eval_retrieval(golden, top_k=10):
    hits, mrr = [], []
    for case in golden:
        results = search_service.hybrid_search(case["query"], top_k=top_k)  # 走真实生产检索链
        ids = [r.chunk_id for r in results]
        gold = set(case["gold_chunk_ids"])
        hits.append(any(i in gold for i in ids[:5]))
        rank = next((n+1 for n, i in enumerate(ids) if i in gold), None)
        mrr.append(1/rank if rank else 0.0)
    return {"hit@5": mean(hits), "mrr@10": mean(mrr), "n": len(golden)}

def eval_qa(golden):
    # 走 ai_router 真实链路（本地模型固定版本号，云端固定 model 参数）
    # 指标：answer_points 覆盖率（字符串/语义匹配）、引用正确率（答案引用 doc_id ∈ gold_doc_ids
    #       且引用片段与要点相关）、拒答正确率（expect_refuse 样本是否承认无资料）
    ...

# 输出：docs/reports/rag-eval-<date>-<model>-<embed>.json + .md
# 基线文件：tests/eval/baseline.json（首次跑定基线，此后 --compare 自动 diff）
```
运行口径：
```powershell
python -m services.rag_eval --suite all --compare tests/eval/baseline.json
# 退出码：关键指标低于基线 -2% → 非 0（可直接当 CI/部署闸）
```

### 3.4 回归闸与常态化（S）

- CONTRIBUTING / DEPLOY 增补：**嵌入模型、Ollama 模型 tag、RRF 权重、分块参数、微调版本**五类变更，PR 必须附 rag_eval 对比报告。
- 云端兜底模型在设置页选型时，记录 model 字符串到评测报告（云端"同名模型"静默升级是趋势污染源）。
- cron/CI 每周跑一次全量评测（本地模型离线可跑，数据不出网原则不破）；报告趋势表进仪表盘管理端（可选）。
- OCR 质量：check_ocr_quality.py 的噪声指标纳入同一报告体系，扫描件入库验收阈值沿用 OPEN-DECISIONS 的"99% 准确率"目标（11 文档质量门）。
- 把散落的 AI 运维知识收敛成 `docs/ai-system.md`（路由表/显存口径/降级链/评测口径），替代 README 里失效的文档链接（12 文档）。

---

## 4. 验收清单

- [ ] retrieval_golden.jsonl ≥200 条、qa_golden.jsonl ≥100 条，人工审核记录在案
- [ ] rag_eval 一键跑通，首份基线报告 + baseline.json 入库
- [ ] 指标：Hit@5、MRR@10、要点覆盖率、引用正确率、拒答正确率全部有数字
- [ ] 做一次"换嵌入模型"演练（bge-small→bge-m3 或调 RRF 权重），评测报告能明确给出优劣结论
- [ ] 回归闸写入 CONTRIBUTING；每周定时评测上线
- [ ] docs/ai-system.md 收敛完成，README 链接修复
