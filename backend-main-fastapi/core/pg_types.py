"""统一类型系统：PG 原生 ENUM 字典、SQLAlchemy 自定义类型、CHECK 约束生成器。

职责边界：只定义"数据长什么样"与"什么数据不合法"，不含任何业务流程。

三个必须存在的原因（对应报告 24 的缺陷）：
  1. 枚举散落全库（question_type / stage / content_category / doc_type / quality /
     confidence 等全是裸 String(20/50)）→ 统一收敛到 ENUM_CATALOG，一处声明到处引用；
  2. 题目 options 是无约束 JSON，184 题选项数 2/3/5/6/14 错乱 → CHECK 约束拦在库层；
  3. pgvector 的 Windows DLL 可能拿不到 → 所有 PG 专有类型必须能在 SQLite 下安全降级。
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import CheckConstraint, Text
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, TSVECTOR
from sqlalchemy.types import JSON, TypeDecorator

# --------------------------------------------------------------------------- #
# 一、ENUM 字典：全库唯一枚举权威源
# --------------------------------------------------------------------------- #
# 键 = PG 中 CREATE TYPE 的名字；值 = 合法取值元组（顺序即排序权重）。
# 新增枚举只能改这里；模型里一律用 build_enum("名字") 引用，禁止再写裸 String。
ENUM_CATALOG: dict[str, tuple[str, ...]] = {
    # 科目分类：公共课 / 专业课 / 复试科目
    "subject_category": ("public", "professional", "retest"),
    # 题型。取值以实测数据为准：essay/single/calc/fill/judge/draw 有数据，
    # 旧文档里的 multiple 当前 0 行但保留兼容位，proof/other 为扩展位。
    "question_type": (
        "single", "multiple", "judge", "fill", "calc",
        "essay", "draw", "proof", "other",
    ),
    # 作答类型：客观题（可自动判分）/ 主观题（需人工或 LLM 评分）
    "answer_type": ("objective", "subjective"),
    # 来源性质（正交独立列，取代旧的 "知识库:" / "真题:" 字符串前缀归类）
    "source_kind": (
        "past_exam", "textbook", "chapter_exercise",
        "mock_exam", "ai_generated", "user_created", "external_import",
    ),
    # 备考阶段（tasks.stage 口径）：基础 / 强化 / 冲刺 / 复试
    "prep_stage": ("basic", "intensive", "sprint", "retest"),
    # 考试阶段（documents.stage 口径）：初试 / 复试
    # 与 prep_stage 是两套不同语义（"复试" 在 prep_stage 里是阶段，在 exam_stage 里是考试轮次），
    # 因此拆成两个枚举，绝不合并。
    "exam_stage": ("初试", "复试"),
    # 内容语义分类（与 doc_type 的加工层级正交）
    "content_category": ("textbook", "example", "exam", "method", "glossary", "other"),
    # 资料加工层级：原始教材真题 / 加工笔记错题 / 索引考点清单
    "doc_type": ("raw", "note", "index"),
    # 原始文件格式（11 种混存 → 归一为 canonical_content 的 Markdown 中间态）
    "doc_format": (
        "pdf", "txt", "doc", "docx", "md", "image", "pptx", "ppt",
        "xlsx", "html", "json", "jpg", "png", "other",
    ),
    # 结构化程度：已按章节解析 / 扁平文本 / 扫描件 OCR
    "structure_level": ("structured", "flat", "ocr"),
    # 索引状态
    "index_status": ("pending", "indexing", "indexed", "failed", "skipped"),
    # 质量评级
    "quality_grade": ("A", "B", "C", "incomplete"),
    # 置信度
    "confidence_level": ("high", "medium", "low"),
    # 答案来源：题库自带 / 原文抽取 / LLM 生成 / 人工确认
    "answer_source": ("bank", "source_extract", "llm_generated", "user_confirmed"),
    # 分块分类判定来源
    "classify_source": ("vector", "keyword", "fusion", "llm", "no_bge", "fallback", "manual", "document"),
    # 知识点抽取来源
    "extract_source": ("smart_ingest", "batch", "manual"),
    # 知识点关系类型：前置 / 并列 / 包含
    "relation_type": ("prerequisite", "parallel", "contains"),
    # 任务状态
    "task_status": ("pending", "doing", "done", "cancelled"),
    # 复习反馈结果（SM-2 评分档位）
    "review_result": ("again", "hard", "good", "easy"),
    # 掌握度等级
    "mastery_level": ("not_mastered", "learning", "reviewing", "mastered"),
    # 研招通知类型
    "notice_type": ("公告", "简章", "复试", "调剂", "录取"),
    # 通知重要级
    "importance_level": ("urgent", "important", "normal", "low"),
    # 提醒类型
    "alert_kind": ("deadline_soon", "new_urgent", "new_important", "subscribed_new"),
    # 订阅维度
    "subscription_scope": ("school", "major", "notice_type", "keyword"),
    # 学位类型：学硕 / 专硕 / 未判定
    "degree_type": ("academic", "professional", "unknown"),
    # 向量引擎（退化方案留痕，知道每条向量是谁算的）
    "vector_engine": ("bge", "openai", "unknown"),
    # 分块 L3 语义类型
    "l3_content_type": (
        "定义", "定理", "理论陈述", "例题", "习题", "证明", "公式", "实验步骤", "其他",
    ),
    # 题目校验门结果：未校验 / 通过 / 有告警 / 不通过
    "question_validation_status": ("pending", "pass", "warn", "fail"),
}


def enum_values(name: str) -> tuple[str, ...]:
    """取指定 ENUM 的合法取值；名字写错直接抛错，避免静默生成空枚举。"""
    try:
        return ENUM_CATALOG[name]
    except KeyError as exc:
        raise KeyError(f"未登记的枚举名: {name}，请先在 ENUM_CATALOG 中声明") from exc


def build_enum(name: str, **kwargs: Any):
    """构造 SQLAlchemy Enum 列类型。

    native_enum=True  → PG 下生成真正的 CREATE TYPE，可被 CHECK/索引复用；
    create_constraint → SQLite 下自动降级为 VARCHAR + CHECK，双后端行为一致。
    """
    from sqlalchemy import Enum

    return Enum(
        *enum_values(name),
        name=name,
        native_enum=True,
        create_constraint=True,
        validate_strings=True,
        **kwargs,
    )


def render_enum_ddl() -> str:
    """渲染全部 CREATE TYPE 语句（供 SQL 建表脚本与迁移校验共用）。"""
    lines = []
    for name, values in ENUM_CATALOG.items():
        literal = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
        lines.append(f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({literal}); "
                     f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 二、TypeDecorator：PG 专有类型在 SQLite 下的安全降级
# --------------------------------------------------------------------------- #
class _DialectVariant(TypeDecorator):
    """按方言挑选物理类型的基类：PG 用专有类型，SQLite 回退到等价通用类型。"""

    impl = Text
    cache_ok = True

    _pg_type = None      # 子类填入 PG 下使用的类型实例
    _fallback = None     # 子类填入非 PG 下使用的类型实例

    def load_dialect_impl(self, dialect):
        target = self._pg_type if dialect.name == "postgresql" else self._fallback
        return dialect.type_descriptor(target)


class JSONBList(_DialectVariant):
    """JSON 数组列：PG 落 jsonb（可被 GIN 索引），SQLite 落 JSON。

    约束：绑定值必须是 list 或 None；字典/字符串等一律拒绝，
    避免"有的题存数组、有的题存对象"的历史问题在库层复活。
    """

    _pg_type = JSONB()
    _fallback = JSON()

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError(f"JSONBList 只接受 list 或 None，收到 {type(value).__name__}")
        return value

    def process_result_value(self, value, dialect):
        return value


class JSONBObject(_DialectVariant):
    """JSON 对象列（配置项、payload、extra 等），PG 落 jsonb。"""

    _pg_type = JSONB()
    _fallback = JSON()

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError(f"JSONBObject 只接受 dict 或 None，收到 {type(value).__name__}")
        return value


class TSVector(_DialectVariant):
    """全文检索向量列。

    PG 下是真正的 tsvector（配 GIN 索引）；SQLite 下降级为 TEXT，
    让同一份模型在两种后端都能建表，检索实现由服务层按后端分支。
    """

    _pg_type = TSVECTOR()
    _fallback = Text()


class Float32Vector(_DialectVariant):
    """退化向量列：统一按 float32 小端字节数组存取。

    - VECTOR_BACKEND=pgvector 时，由 SQL 层把本列内容转成 vector 存储（见 pg_schema.sql）；
    - VECTOR_BACKEND=python   时，直接以 bytea/BLOB 原样存储，检索在 Python 侧做余弦。
    这样两张物理表结构一致，切换后端不需要改模型。
    """

    _pg_type = BYTEA()
    _fallback = JSON()  # SQLite 无原生 BLOB 绑定时退化为 JSON 数组，便于排障

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        if isinstance(value, (list, tuple)):
            import numpy as np

            return np.asarray(value, dtype="<f4").tobytes()
        raise ValueError(f"Float32Vector 只接受 bytes / 数值序列，收到 {type(value).__name__}")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)
        if isinstance(value, list):
            import numpy as np

            return np.asarray(value, dtype="<f4").tobytes()
        return value


class MarkdownText(TypeDecorator):
    """统一 Markdown 中间态文本列。

    入库做最小归一化：统一换行符、去首尾空白、去水印残留行。只做格式归一，不改内容；
    空串一律存 NULL，便于用 CHECK 直接拒绝空正文。
    """

    impl = Text
    cache_ok = True

    #: 水印行前缀（命中整行即丢弃），用于清洗历史 PDF 抽取结果
    _WATERMARK_PREFIXES = ("本文档由", "扫描全能王", "CamScanner", "由 扫描", "本资料由")

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return None
        kept = [
            line for line in text.split("\n")
            if not any(line.strip().startswith(p) for p in self._WATERMARK_PREFIXES)
        ]
        result = "\n".join(kept).strip()
        return result or None

    def process_result_value(self, value, dialect):
        return value


# --------------------------------------------------------------------------- #
# CHECK 约束生成器：实现在 core/pg_checks.py（拆包避免单文件超长）
# 重导出后，调用方仍可 from core.pg_types import range_check
# --------------------------------------------------------------------------- #
from .pg_checks import (  # noqa: E402
    enum_check,
    imply_check,
    jsonb_array_check,
    not_blank_check,
    range_check,
)

__all__ = [
    "ENUM_CATALOG",
    "enum_values",
    "build_enum",
    "render_enum_ddl",
    "JSONBList",
    "JSONBObject",
    "TSVector",
    "Float32Vector",
    "MarkdownText",
    "enum_check",
    "range_check",
    "not_blank_check",
    "jsonb_array_check",
    "imply_check",
]
