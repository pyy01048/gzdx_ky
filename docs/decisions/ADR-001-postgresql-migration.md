# ADR-001: 数据库底座从 SQLite 迁移到 PostgreSQL 17

## Status

Accepted（2026-10-14）

## Background

平台当前运行在 SQLite 上：`D:\平台\database\kaoyan.db`，670MB / 67 张表 / 146 个索引。核心数据量：

| 表 | 行数 |
|---|---|
| knowledge_chunks | 61,041 |
| knowledge_chunks_vec | 18,422 |
| quiz_questions | 9,096 |
| question_knowledge_links | 8,502 |
| sft_examples | 4,670 |
| words | 4,569 |
| documents | 2,611 |
| kaoyan_notices | 1,002 |
| knowledge_points | 1,067 |

报告 24 判定了五项数据库层缺陷，其中三项必须靠换库解决：

- **D1 单写者锁**：SQLite 写操作持有全库排他锁，多人同时刷题/写错题/记录专注时互相阻塞。
- **D2 FTS 影子表**：中文全文检索靠 4 张 FTS 影子表（含 `_fts_content`/`_fts_data`/`_fts_docsize`/`_fts_idx` 共 6 张物理表）维护，数据与主表双写、易失同步。
- **D3 向量检索自研**：61,041 个分块里只有 18,422 个有向量，42,619 个空缺，且检索逻辑是 Python 侧自研，无法利用索引加速。

另有 D4（备份文件 4GB+）与 D5（脏数据）属治理范畴，不通过换库解决。

## Decision

**采用 PostgreSQL 17 免安装便携版**，装在 `D:\pgsql`，数据目录 `D:\pgsql\data`，端口 5432，库名 `kaoyan`。保留 SQLAlchemy 2.0 风格 ORM。

具体落地：

1. **建表以 SQL 为准，不以 ORM 为准。** 完整 DDL 在 `backend-main-fastapi/core/pg_schema.sql`（分片在 `core/sql/`）。原因是三类能力只存在于 SQL 里：
   - `GENERATED ALWAYS AS (...) STORED` 派生列（`option_count` / `is_past_exam` / `search_vector`）
   - 部分索引（`WHERE ...`）
   - PL/pgSQL 触发器函数（校验门）

   因此**禁止用 `Base.metadata.create_all()` 建 PG 表**，须走 `core.db_session.apply_schema()`。

2. **ORM 模型按领域拆包**（`core/models/`：system / documents / knowledge / questions / learning / schools / words_misc），统一出口 `core/pg_models.py`。拆包原因是 65 张表放单文件会远超 300 行上限。

3. **双后端开关保留**。`DATABASE_BACKEND=postgresql|sqlite` 与 `VECTOR_BACKEND=pgvector|python` 均由环境变量驱动。SQLite 分支保留 WAL / busy_timeout / foreign_keys 等 PRAGMA，等价于原 `database.py`，保证降级路径可用、可回滚。

4. **中文分词走 Python 侧 jieba，不依赖 zhparser / pg_jieba。** PG 内置无中文分词器，Windows 便携版装扩展困难。方案是：Python 用 jieba（项目已有，`services/search_service.segment()` 即 `cut_for_search`）分词后，把空格分隔的 token 串写入 `search_tokens` 列，由 PG 的 `GENERATED` 列经 `fts_build()`（`to_tsvector('simple', ...)`，双参数版是 IMMUTABLE，故可用于生成列）自动转成 `tsvector`，再建 GIN 索引。查询侧用同一套分词 + `plainto_tsquery('simple', ...)`，保证写入与查询口径一致。另建 `pg_trgm` GIN 索引做错别字/部分匹配的模糊兜底。

5. **向量双方案并存，不做二选一。** `chunk_vectors` 同时有 `embedding bytea`（float32 小端，Python 侧 numpy 余弦）和 `embedding_f32 vector(512)`（pgvector 侧 `<=>`）。后者的列与 HNSW 索引由 `DO` 块按 `pgvector_available()` 条件创建，扩展缺失时自动跳过，两张方案共用同一张表，切换开关不改结构。

6. **pgvector 当前状态：未安装。** 实测 `pg17.zip` 仅 389KB（下载未完成），`psycopg` / `pgvector` Python 包均未安装。因此**默认按"退化方案可用"设计**，pgvector 作为拿到 DLL 后的增量启用项。

## Consequences

### 正面

- D1：MVCC 让读写互不阻塞，多人并发刷题不再互相卡住。
- D2：6 张 FTS 影子表全部删除，检索列与数据同行，消除双写失同步；GIN 索引在 61k 分块上的检索显著快于自研遍历。
- D3：向量空洞可被 `v_chunk_vector_coverage` 视图量化验收，补齐进度可度量。
- 强类型落地：26 个 PG 原生 ENUM + CHECK 约束，把"枚举散落全库"与"选项数错乱"挡在库层。

### 负面 / 代价

- **存量脏数据会先被导入再治理。** 内容质量类问题（题干混入选项、缺答案/缺解析）走软校验标记 `warn`，而不是硬拒。代价是迁移后必须有一轮"warn 清零"专项，否则脏数据依旧可见。
- **双 Base 并存期有硬约束。** 旧 `models.py` 与新 `core.pg_models` 使用不同 `DeclarativeBase`，**禁止在同一 Session 里对两个 Base 的模型做关联查询**。路由迁移需逐个切换，不能混用。
- **pgvector 未到位前，向量检索仍是 Python 侧全量余弦**。复杂度 O(N·d)，数据量增长到数十万级会成为瓶颈，需盯紧 `v_chunk_vector_coverage` 与响应耗时。
- 便携版 PG 的备份仍属 D4 治理范畴，换库不自动解决。

## Related ADRs

- ADR-002: 科目口径收敛为单一权威源
- ADR-003: 题目标准 schema 与校验门
