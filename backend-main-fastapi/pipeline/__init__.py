# -*- coding: utf-8 -*-
"""数据治理 ETL 管线：把 SQLite 脏数据洗净成 PG 可用的 JSONL 中间产物。

模块分工（严格分层，禁止跨层反向依赖）
--------------------------------------
config                路径与阈值的唯一落点
watermark             水印 / 页眉页脚清洗（规则外置到 watermark_rules.json）
question_schema       题目 canonical 结构与校验门
classifier            来源分类（教材/真题/习题/模拟）与科目归一
document_normalizer   多格式文档统一为 Markdown 中间态
verify                抽样验收与准确率门禁
etl_sqlite_to_pg      抽取 SQLite → 转换 → 输出 JSONL
run_pipeline          CLI 入口

铁律
----
1. 本阶段**只读** SQLite，任何写库行为都不得出现在这些模块里；
   所有产物落到 ``config.ETL_OUT_DIR`` 下的 JSONL。
2. 每个清洗动作必须留证据（命中规则 id + 原文片段），便于用户抽查。
3. 校验不达标的数据进 repaired/repair 队列，不得直接混进干净产物。
"""
