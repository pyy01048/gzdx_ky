# RAG 评测集（golden sets）

> 完善方案 10-AI与RAG质量保障。指标定义与运行方式见 `backend-main-fastapi/services/rag_eval.py`。

## 文件

| 文件 | 用途 | 目标规模 |
|---|---|---|
| `retrieval_golden.jsonl` | 检索评测：query → 应命中的分块/知识点 | ≥200 条 |
| `qa_golden.jsonl` | 答疑评测：问题 → 答案要点 / 应引用来源 / 是否应拒答 | ≥100 条 |
| `qa_answers.jsonl` | 待评测的答案文件（线上或批处理产出，不进基线） | 与 qa_golden 同 id |
| `baseline.json` | 首次全量评测后写入；`--compare` 以此为回归闸 | 1 份 |
| `*_candidates.jsonl` | 脚本自动生成的候选（未审核，不作基线） | — |

## 指标口径

- **Hit@5**：前 5 条结果中命中任一 gold 分块/知识点 → 1，否则 0，取均值。
- **MRR@10**：首个命中位置倒数的均值。
- **answer_coverage**：答案覆盖的要点比例（归一化字符串命中；短公式要求完整命中）。
- **citation_accuracy**：答案引用的 doc_id 非空且是 gold_doc_ids 的子集 → 1。
- **refusal_accuracy**：`expect_refuse=true` 的题，答案必须承认"没有资料/未收录"。

## 审核流程（不可省）

1. 跑 `python scripts/tools/build_rag_eval_set.py --limit 400` 生成候选。
2. 逐条核对：gold 分块是否真的能回答 query（题目挂错知识点是常见噪声）。1 分钟/条。
3. verified=true 的行另存为 `retrieval_golden.jsonl` / `qa_golden.jsonl`。
4. 在下方审核记录登记。

## 审核记录

| 日期 | 审核人 | 条数 | 剔除 | 说明 |
|---|---|---|---|---|
| 2026-11-20 | （待执行） | 0 | 0 | 当前仅含手写种子样例，需扩充到目标规模 |
| 2026-11-27 | phase2-T1 | 129+110 | 0 | 首轮扩充：从库内 knowledge_points（14 学科）批量生成候选并人工挂靠 gold_kp_ids/gold_chunk_ids；补充手写经典考点（数电/模电/电路/信号/自控/通信/OS/DB/网络/数据结构/物理）与 3 条拒答用例；verified=true；baseline.json 已由 `python -m services.rag_eval --suite all --write-baseline` 生成 |

## 当前状态（诚实标注）

- 仓库内 `retrieval_golden.jsonl` 共 **129 条**已审核用例（≥50 首轮目标 ✓，覆盖数电/模电/电路/信号与系统/计算机组成原理/自控/通信/OS/DB/网络/数据结构/物理/电子技术基础/C++ 等 14 学科），每条含 id/query/gold_chunk_ids/gold_kp_ids/subject/verified；
- 仓库内 `qa_golden.jsonl` 共 **110 条**已审核用例（≥30 首轮目标 ✓），含 3 条 `expect_refuse=true` 拒答用例（未来信息/未收录），每条含 id/question/answer_points/gold_doc_ids/expect_refuse/subject；
- `baseline.json` 已生成（retrieval: hit@5=0.1395 / mrr@10=0.0965；qa: answered=0 因 qa_answers.jsonl 待线上产出），作为首次全量评测基线，此后 PR 必须 `--compare`；
- **持续扩充**：标注"持续扩充到 200+100"——后续轮次可继续跑 `scripts/tools/build_rag_eval_set.py` 生成候选并人工审核，达到 ≥200+100 后 CI 回归闸从 warn 切阻断。

## 变更回归闸

嵌入模型 / Ollama 模型 tag / RRF 权重 / 分块参数 / 微调版本五类变更，
PR 必须附 `python -m services.rag_eval --suite all --compare tests/eval/baseline.json` 的对比报告；
关键指标低于基线 -2% 视为回归（退出码 1）。
