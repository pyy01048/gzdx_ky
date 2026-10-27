"""PostgreSQL 数据库底座包（core）。

本包是考研备考平台从 SQLite 迁移到 PostgreSQL 16.15 后的**唯一数据底座入口**，
只负责三件事，业务逻辑一律不得下沉到这里：

  1. 类型与约束：``pg_types`` —— 全部 PG 原生 ENUM、自定义 TypeDecorator；
     ``pg_checks`` —— CHECK 约束生成器（从 pg_types 拆出，避免单文件超长）；
  2. 数据结构：``pg_models`` —— 与 ``pg_schema.sql`` 严格一一对应的 SQLAlchemy 模型；
  3. 连接与会话：``db_session`` —— 双后端（PostgreSQL / SQLite）引擎工厂与会话管理。

版本锚定（按本机实测，非 requirements.txt 的声明值）：
  Python        3.13.14
  SQLAlchemy    2.1.4      （requirements.txt 写的 2.0.23 已过期，按 2.1.4 API 写）
  FastAPI       0.104.1
  numpy         2.2.6      （退化向量方案按 float32 编解码）
  jieba         0.42.1     （中文分词，写入 tsvector 前的预分词）
  psycopg       未安装      （PG 驱动，按需加载；未安装时本包仍可导入）
  pgvector      未安装      （向量扩展，可选；缺失时自动走 Python 侧退化方案）

双后端开关由环境变量驱动，详见 ``db_session.DBBackend``：
  DATABASE_BACKEND = postgresql | sqlite
  VECTOR_BACKEND   = pgvector   | python

导入约定：
  - 本包顶层**不主动连接数据库**，也不导入 psycopg，保证离线环境可安全导入；
  - 需要建表时显式调用 ``core.db_session.apply_schema()``，不要依赖副作用。
"""

__version__ = "1.0.0"

__all__ = [
    "pg_types",
    "pg_checks",
    "pg_models",
    "db_session",
    "__version__",
]
