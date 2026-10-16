# -*- coding: utf-8 -*-
"""管线全局配置：路径与阈值的**唯一落点**。

各模块一律从这里取路径和阈值，禁止各自硬编码，避免「清洗用的规则」和
「验收用的规则」不是同一份，进而出现「清过了但验收仍报残留」的假故障。
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "BACKEND_DIR",
    "PIPELINE_DIR",
    "PROJECT_ROOT",
    "SQLITE_PATH",
    "ETL_OUT_DIR",
    "ARCHIVE_DIR",
    "WATERMARK_RULES_PATH",
    "SUBJECT_ALIASES_PATH",
    "DEFAULT_ACCURACY_THRESHOLD",
    "DEFAULT_SAMPLE_SIZE",
    "DEFAULT_SEED",
    "DEFAULT_LIMIT",
    "ensure_out_dirs",
    "read_only_sqlite_uri",
    "pg_database_url",
]

BACKEND_DIR = Path(__file__).resolve().parent.parent          # backend-main-fastapi
PIPELINE_DIR = Path(__file__).resolve().parent                # pipeline
PROJECT_ROOT = BACKEND_DIR.parent                             # 仓库根（由文件位置推导，不写字面量）

# SQLite 源库。本阶段一律以只读模式打开，禁止任何写入。
SQLITE_PATH = PROJECT_ROOT / "database" / "kaoyan.db"

# JSONL 中间产物目录
ETL_OUT_DIR = PROJECT_ROOT / "data" / "etl_out"

# 源文件归档目录（转换后归档，绝不删除原件）
ARCHIVE_DIR = PROJECT_ROOT / "data" / "etl_archive"

# 可配置规则文件
WATERMARK_RULES_PATH = PIPELINE_DIR / "watermark_rules.json"
SUBJECT_ALIASES_PATH = PIPELINE_DIR / "subject_aliases.json"

# 用户要求准确率 99%，作为硬门禁阈值
DEFAULT_ACCURACY_THRESHOLD = 0.99

# 正文最小实义字符数。**单一落点**：question_schema 的校验门与 verify 的内容检查
# 共用同一个值，否则会出现「已判为干净、验收却说正文太短」的自相矛盾。
MIN_CONTENT_CHARS = 10
# 默认抽样量（小批量足够，全量校验由 etl 主流程对每个样本都做规则校验）
DEFAULT_SAMPLE_SIZE = 200
# 固定随机种子：抽样必须可复现，否则两次跑出的准确率对不上，无法审计
DEFAULT_SEED = 20261013
# 默认处理上限（防止误跑全量把内存打满）
DEFAULT_LIMIT = 200

#  SQLite 只读 URI 模板。**mode=ro** 是数据安全的最后一道闸：
#  即使上层代码误写 UPDATE/DELETE，SQLite 也会直接拒绝。
_SQLITE_RO_URI = "file:{path}?mode=ro"


def read_only_sqlite_uri(path: os.PathLike[str] | str | None = None) -> str:
    """返回 SQLite 只读连接 URI。

    Args:
        path: 数据库路径，默认 :data:`SQLITE_PATH`。

    Returns:
        形如 ``file:D:/platform/database/kaoyan.db?mode=ro`` 的 URI。
    """
    target = Path(path) if path is not None else SQLITE_PATH
    # Windows 路径含盘符与反斜杠，URI 必须用正斜杠，且盘符前加一个斜杠
    posix = target.resolve().as_posix()
    if posix[1:2] == ":":
        posix = "/" + posix
    return _SQLITE_RO_URI.format(path=posix)


def pg_database_url() -> str:
    """返回 ``psycopg`` 可直接使用的 PostgreSQL 连接串。

    来源优先级：``DATABASE_URL`` > ``.env`` 里的 ``PG_*`` 分项（由 :mod:`core.db_session`
    读取）。**代码里不留任何主机与口令**——原先 4 个管线脚本各写一份同一条带口令的
    DSN，口令进了 git、换环境即失效，而且四处各改各的必然漂移。

    Raises:
        ValueError: 当前配置指向 SQLite，或完全解析不到 PG 连接串。
    """
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if not raw:
        from core.db_session import build_database_url  # 延迟导入：仅取串，不建引擎

        raw = build_database_url().strip()
    if not raw:
        raise ValueError(
            "解析不到 PostgreSQL 连接串：请设置 DATABASE_URL，或在 .env 配 PG_HOST/PG_USER/"
            "PG_PASSWORD/PG_DATABASE"
        )
    if raw.startswith("sqlite"):
        raise ValueError(f"当前后端是 SQLite（{raw}），管线 PG 步骤需要 PostgreSQL")
    # SQLAlchemy 的 ``postgresql+psycopg://`` driver 后缀 psycopg.connect() 不识别，剥掉。
    if "+psycopg" in raw.split("://", 1)[0]:
        raw = raw.replace("postgresql+psycopg", "postgresql", 1)
    return raw


def ensure_out_dirs(out_dir: os.PathLike[str] | str | None = None) -> Path:
    """确保输出目录存在并返回它。

    Args:
        out_dir: 目标目录，默认 :data:`ETL_OUT_DIR`。

    Returns:
        已创建的目录 Path。
    """
    target = Path(out_dir) if out_dir is not None else ETL_OUT_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target
