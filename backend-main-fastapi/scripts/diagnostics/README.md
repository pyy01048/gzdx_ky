---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: b229e9f4d488c81cbf8c9cf190463897_008a831dc37b11f1bc7f525400638852
    ReservedCode1: UC3iVWh3wzU+jqMIcQ5UG5f05wE+9fhxT0I/+ZU+Z5famgoTcOinx6mFb24qjUXHPC30QiId7zPBwDM0tgKLMuo75vvPopX1oBgVn5lCed0hZ0lOxZ2WQKjfKRj3bZ62CdJs6D/lNdlobZPHvlpB7ElKFJ8XzJYXMLgZ4ONTDZsxy6DAYBa4aSSDlms=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: b229e9f4d488c81cbf8c9cf190463897_008a831dc37b11f1bc7f525400638852
    ReservedCode2: UC3iVWh3wzU+jqMIcQ5UG5f05wE+9fhxT0I/+ZU+Z5famgoTcOinx6mFb24qjUXHPC30QiId7zPBwDM0tgKLMuo75vvPopX1oBgVn5lCed0hZ0lOxZ2WQKjfKRj3bZ62CdJs6D/lNdlobZPHvlpB7ElKFJ8XzJYXMLgZ4ONTDZsxy6DAYBa4aSSDlms=
---

# 诊断脚本归档说明（模块 E3）

> 归档时间：2026-10-09。本目录收纳平台**一次性诊断 / 体检 / 修复**类脚本，
> 避免根目录被一次性脚本污染。**正式服务代码、训练部署脚本不受影响**。

## 调用方式（保持兼容）

归档前脚本位于项目根目录（如 `python check_env.py`）。
归档后统一从 `backend-main-fastapi` 根目录执行：

```bash
cd backend-main-fastapi
python scripts/diagnostics/<脚本名>.py
```

若脚本依赖根目录模块（database / models / schemas），请用 `-m` 方式保证 sys.path：

```bash
python -m scripts.diagnostics.<脚本名>
```

## 原路径 → 新路径映射

| 原路径（项目根） | 新路径（scripts/diagnostics/） | 用途分类 |
| --- | --- | --- |
| audit_training_data.py | scripts/diagnostics/audit_training_data.py | 训练数据审计（QA 语料质量） |
| check_env.py | scripts/diagnostics/check_env.py | 环境自检（依赖 / 模型 / OCR 栈） |
| check_ocr_quality.py | scripts/diagnostics/check_ocr_quality.py | OCR 质量体检 |
| check_qa_sources.py | scripts/diagnostics/check_qa_sources.py | QA 语料来源核验 |
| check_train_env.py | scripts/diagnostics/check_train_env.py | 训练环境体检 |
| diagnose_missing_sources.py | scripts/diagnostics/diagnose_missing_sources.py | 缺失知识源诊断 |
| reclassify_subjects.py | scripts/diagnostics/reclassify_subjects.py | 学科标注事故修复（知识库自愈） |
| _tmp_db_check.py | scripts/diagnostics/_tmp_db_check.py | 临时数据库检查（一次性） |
| show_access.py | scripts/diagnostics/show_access.py | 接口/访问核验（一次性） |
| batch_process.py | scripts/diagnostics/batch_process.py | 批量处理辅助（一次性） |
| import_vocabulary_ocr.py | scripts/diagnostics/import_vocabulary_ocr.py | 词汇 OCR 导入（一次性） |
| eval_qa_model.py | scripts/diagnostics/eval_qa_model.py | QA 模型效果评测 |

## 未归档说明

- `services/answer_cross_check.py`：**服务模块**，被 `routers/answers.py` 引用，非诊断脚本，保留原位。
- `training/` 目录（lora_finetune.py / resume_train.py / train_with_modelscope.py / merge_lora.py /
  test_merged_model.py / setup_local_models.py / download_embedding_model.py / convert_hf_to_gguf.py /
  start_training.bat）：训练/部署脚本，2026-10-16 从后端根目录迁入 `backend-main-fastapi/training/`，
  脚本内 sys.path 与数据目录已同步改为项目根相对路径。
- 任务描述中的 `kaoyan_ai/pipeline/` 目录在本仓库不存在（已全量检索确认），
  实际诊断脚本即上述 12 个根目录一次性脚本。
*（内容由AI生成，仅供参考）*
