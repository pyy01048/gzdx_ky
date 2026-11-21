# 知识库管线（建立 · 体检 · 自愈）

> 最后核对：2026-11-20 · commit a7f92ea · 维护人：pyy

## 1. 入库流程

```
上传/导入 ──► 解析（PDF/Word/图片对照表）
          ──► OCR（图片/扫描件，RapidOCR 主链 + 可选 PP-OCRv5）
          ──► 清洗（页眉页脚/水印/乱码/断行）
          ──► 分块（按章节 + 语义上限，保留标题层级）
          ──► 索引（PG GIN 全文 + pgvector 向量；SQLite 线 FTS5 降级）
          ──► 质检（覆盖率/噪声/配图完整性）
```

对应实现：`services/kb_pipeline.py`（体检 + `--heal` 自愈）、`pipeline/`（离线批处理）、
`services/search_service.py`（索引与检索）。

## 2. 体检指标

| 指标 | 含义 | 阈值 |
|---|---|---|
| chunk 覆盖率 | 文档字符数 vs 分块字符数 | ≥ 95% |
| OCR 噪声比 | 乱码/孤立符号占比 | ≤ 3% |
| 向量缺失 | 有分块无向量 | 0 |
| 空章节 | 有标题无内容 | 0 |
| 配图缺失 | 题干引用图但无存储 | 0 |

`GET /api/health` 的 `kb` 字段给出 vector_store / fts5 / tables / quiz 快照，单项独立降级，不会 500。

## 3. 自愈

```bash
python -m services.kb_pipeline --check          # 只体检，出报告
python -m services.kb_pipeline --heal            # 幂等修复（补向量/补索引/清理空块）
```

铁律：自愈只做**可逆**操作（补建索引、重算向量），不做删除；需要删数据的动作走
`services/delete_guard.py` 双闸门 + 备份表。

## 4. 常见故障

| 症状 | 原因 | 处置 |
|---|---|---|
| 检索命中率骤降 | 索引未随 chunks 更新 | `--heal` 重建 FTS/向量 |
| 文档列表有但检索不到 | 分块未生成 / 文档被标记 junk | 看 `documents.is_junk`；重跑分块 |
| 向量后端缺失 | pgvector 扩展未装 / 维度不匹配 | `CREATE EXTENSION vector`；核对嵌入维度 512 |
| OCR 全空 | 引擎初始化失败被吞 | 看日志 `ocr_router`；`check_env.py` 验证引擎 |

## 5. 数据来源合规

教材/真题/词库来源与许可证见 [data-sources.md](data-sources.md)。公开分发受限，
仅限个人学习研究。
