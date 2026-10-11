---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: b229e9f4d488c81cbf8c9cf190463897_429b1d18c32e11f1bc7f525400638852
    ReservedCode1: 5Vq5RBb/5bUHbVOeILOLvj9K5/v9r/BZC6x1Y5SRl2IY2zNOEmL30+P0NtIo5jet5+UpbFGxrhXkL6Uek7c6pX3Ir8NhCPusg722fz8n/vnaPzRRJ43inLV2kVlrIVU4jz+bXcteRjcd+NvRRM0MT0shR6STZpCn09lpfvgVF2D3BaMhdWHBocX03aY=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: b229e9f4d488c81cbf8c9cf190463897_429b1d18c32e11f1bc7f525400638852
    ReservedCode2: 5Vq5RBb/5bUHbVOeILOLvj9K5/v9r/BZC6x1Y5SRl2IY2zNOEmL30+P0NtIo5jet5+UpbFGxrhXkL6Uek7c6pX3Ir8NhCPusg722fz8n/vnaPzRRJ43inLV2kVlrIVU4jz+bXcteRjcd+NvRRM0MT0shR6STZpCn09lpfvgVF2D3BaMhdWHBocX03aY=
---

# 模块 A 部署执行报告（六大核心能力 + 真题双引擎 + 错因分析）

- 日期：2026-10-08
- 范围：D:\平台\backend-main-fastapi
- 依据：【深度报告】开源源码级借鉴与优化 V4.0.md 等 docs 报告
- 结论：**8 项能力全部落地并通过冒烟验证，pytest 149 passed 无回归**

---

## 一、落地清单

| 编号 | 能力 | 服务文件 | 状态 |
|---|---|---|---|
| A1 | 跨科目分析引擎 | services/analysis_engine.py | ✅ 冒烟通过 |
| A2 | 公式识别服务 | services/formula_service.py | ✅ 冒烟通过 |
| A3 | RAG 门控 | services/retrieval_gate.py + routers/gate.py | ✅ 冒烟通过 |
| A4 | 盲区池 | services/blind_spot_pool.py + routers/blind_spot.py | ✅ 冒烟通过 |
| A5 | 组卷-模考引擎 | services/exam_builder.py | ✅ 冒烟通过（修复 1 处连接失效 bug） |
| A6 | 答案交叉校验 | services/answer_cross_check.py | ✅ 冒烟通过 |
| A7 | 真题双引擎 | services/exam_engine.py（exam.py 新增 /search） | ✅ 冒烟通过 |
| A8 | 错题四段式错因分析 | services/error_analyzer.py（errors.py 接入） | ✅ 冒烟通过（修复 1 处列名 bug） |

## 二、路由注册（新增接口，现有 186 接口不变）

- main.py 新增注册 `gate.router`（/api/gate/*）、`blind_spot.router`（/api/blind-spot/*）
- routers/exam.py 新增 `POST /api/exam/search`（A7 融合检索暴露）
- routers/errors.py `/{error_id}/ai-analyze` 已接入 error_analyzer（A8）
- 原有 analysis/formula/exam/answers 等路由保持不变

## 三、冒烟验证结果

| 项目 | 关键逻辑与结果 |
|---|---|
| A1 analyze_problem | 题目→步骤分解→知识点归因→四段式讲解，结构完整；LLM 不可用时自动降级，返回含归因知识点 |
| A2 公式识别 | 图片公式→LaTeX→编译校验链路可用，LaTeX 校验通过 |
| A3 门控 | 双阈值门控 accept/retry(HyDE 重写)/abstain 决策正常（live 决策 retry） |
| A4 盲区池 | record_abstain/get_gaps/top 正常，gap_id 与 weakest 统计正确；接 study_events 联动 |
| A5 组卷-模考 | build_paper 建卷成功（session_id=2，math2 蓝图，3 题/15 分）；submit_session 判分闭环：correct_count=1 / wrong_count=2，错题回流 error_records + 盲区池联动 |
| A6 交叉校验 | 多来源答案比对、置信度标注正常（样例无第二来源时 checked=false / insufficient_sources 合理拒绝） |
| A7 真题双引擎 | 2-gram 第 4 路 + FTS5 + vec0 + RRF 融合检索正常（命中 5 条） |
| A8 错因分析 | 四段式（考点定位→大纲依据→思路拆解→干扰项解析）+ 错因分类 + 复练推荐正常，写入 misconceptions，stats 统计正确 |

## 四、修复的 Bug（共 2 处，均已备份原文件）

### Bug 1：exam_builder.py — commit 后底层连接失效（A5）
- 现象：`build_paper` 报 `'NoneType' object has no attribute 'execute'`（pool/base.py __getattr__）
- 根因：`conn = db.connection().connection` 获取底层连接后，`load_blueprints` 内部调用 `ensure_module_a_schema/ensure_blueprints` 会 `db.commit()`，使已持有的连接对象失效
- 修复：`conn` 获取移到 `load_blueprints` 之后（其内部 commit 完成后）
- 连带修复：`submit_session` 中错题回流调用的 `record_abstain`（内部 commit）改为延后到最终 `db.commit()` 之后批量执行，避免中途连接失效

### Bug 2：error_analyzer.py — 错误列名（A8）
- 现象：`no such column: error_record_id`
- 根因：第 120 行查询 `error_knowledge_links` 时误用 `error_record_id`，实际表列为 `error_id`
- 修复：改为 `error_id`

## 五、数据与复用

- 复用模块 B 新表：question_knowledge_links / study_events / milestones / knowledge_chunks 新列
- module_a_schema.py 幂等建表：quiz_questions / error_records 增补列、exam_blueprints 预置 4 科 8 蓝图
- 实际数据库：D:\平台\database\kaoyan.db

## 六、回归测试

- `pytest -q`：**149 passed**，29 个既有 DeprecationWarning，无失败、无回归

## 七、备份

- 待改文件 11 个备份于 `temp\backup_20261008_moduleA\`（main.py、errors.py、exam_builder.py、error_analyzer.py 及 7 个服务文件）
- 修改文件：main.py（新增路由注册）、routers/gate.py（新建）、routers/blind_spot.py（新建）、routers/exam.py（新增 /search）、routers/errors.py（接入 A8）、services/exam_builder.py（Bug 修复）、services/error_analyzer.py（Bug 修复）
*（内容由AI生成，仅供参考）*
