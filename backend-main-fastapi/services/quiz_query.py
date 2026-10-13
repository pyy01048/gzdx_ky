# -*- coding: utf-8 -*-
"""题库查询口径统一（M1-1h，2026-10）。

背景：M1-1f 把 OCR 碎片题标记 `quiz_questions.is_junk=1`。刷题列表端点
`GET /api/quiz/questions` 已默认排除，但**其它统计端点**（考频/套卷索引/年份/
章节/科目题数）若不排除，会出现"各科目题数 9171 但可刷 8852"的口径漂移。

本模块提供**唯一**的"可见题目"过滤构造器，供列表与所有用户可见统计复用，
从根上避免口径再次漂移。

口径约定：
  * `is_junk = 1` 的题 = OCR 碎片/答案串，**默认不可见**；
  * `is_junk = NULL`（历史行、未标记）视为**非碎片**，可见（向后兼容）。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import and_, func, not_, or_, text

from models import QuizQuestion


# --------------------------------------------------------------------------- #
# 来源大类（真题 / 教材题 / 自建）——**唯一**派生口径（M0-103）。
#
# 库里没有 source_kind 列，来源大类由 `source` 字段前缀派生：
#   * `真题:<文档名>`    → exam（历年真题）
#   * `知识库:<文档名>`  → textbook（教材 / 讲义 / 知识库抽取题）
#   * 其余 / NULL        → custom（ai 变式题、手工录入等）
#
# 该规则被 routers/quiz.py（列表/统计口径）与 routers/ai_tutoring.py
# （真题/教材两种答疑模式）共同复用，**只此一份**，避免两处派生漂移。
# --------------------------------------------------------------------------- #
SOURCE_KIND_CHOICES = ("exam", "textbook", "custom")
EXAM_PREFIX = "真题:%"
TEXTBOOK_PREFIX = "知识库:%"


def source_kind_of(source: Optional[str]) -> str:
    """按 `source` 前缀派生来源大类，返回 exam / textbook / custom（永不返回 None）。"""
    s = (source or "").strip()
    if s.startswith("真题:"):
        return "exam"
    if s.startswith("知识库:"):
        return "textbook"
    return "custom"


def normalize_source_kind(source_kind: Optional[str]) -> Optional[str]:
    """归一 source_kind 入参：''/'all'/None → None；否则小写化（不校验合法性）。"""
    if source_kind is None:
        return None
    k = str(source_kind).strip().lower()
    if k in ("", "all"):
        return None
    return k


def source_kind_expr(source_kind: Optional[str], model: Any = QuizQuestion) -> Any:
    """返回 source_kind 对应的 SQLAlchemy 过滤表达式；''/'all'/None 返回 None。

    非法的 source_kind 不在此处抛错（由调用方决定如何失败），只返回 None 会掩盖错误，
    故对未知值直接抛 ValueError，调用方转 400。
    """
    kind = normalize_source_kind(source_kind)
    if kind is None:
        return None
    if kind not in SOURCE_KIND_CHOICES:
        raise ValueError(f"不支持的 source_kind：{source_kind}")
    if kind == "exam":
        return model.source.like(EXAM_PREFIX)
    if kind == "textbook":
        return model.source.like(TEXTBOOK_PREFIX)
    # custom：既非真题也非教材（含 source 为 NULL 的历史行），不丢数据。
    # 两个「非」之间必须是 AND——用 OR 会把 exam/textbook 行也放进来。
    return or_(
        model.source.is_(None),
        and_(
            not_(model.source.like(EXAM_PREFIX)),
            not_(model.source.like(TEXTBOOK_PREFIX)),
        ),
    )


def answerable_expr(model: Any = QuizQuestion) -> Any:
    """「可作答」判定表达式：is_available 为 True 或 NULL（NULL 视为可用，向后兼容）。

    **不要改本函数语义**：quiz / taxonomy / documents / papers 四个端点共用它。
    需要"真正能刷"的更严口径请用 ``practiceable_expr``（并列新增，不覆盖本函数）。
    """
    return or_(model.is_available.is_(True), model.is_available.is_(None))


# --------------------------------------------------------------------------- #
# 「可练习」第四档口径（M0-104）：raw ⊇ visible ⊇ answerable ⊇ practiceable
#
# 动机（真库实测，2026-10）：`answerable` 只看 is_available，于是把两类**人做不了**
# 的题也算成可作答——① 缺图题（figure_missing=1 且无选项，题干依赖图/表才能作答）；
# ② 空答案壳（answer 只有「答案：」这类壳，或串入「一、填空题」这种章节标题）。
# 这两类混进刷题池 = 用户刷到无法作答的题。故新增更严的 practiceable 口径，
# 供刷题入口默认使用；`answerable` 保持原样供审计端点使用。
# --------------------------------------------------------------------------- #

# 答案「壳」标签：剥掉后若什么都不剩即为空壳
_ANSWER_SHELL_LABELS = ("参考答案", "答案")
# 答案壳里可能夹带的括号/全角空格
_ANSWER_WRAP_CHARS = ("【", "】", "[", "]", "\u3000")
# 纯标点（去掉后若为空，说明答案只有标点，仍算空壳）
_ANSWER_PUNCT_CHARS = (
    "：", ":", "．", ".", "、", ",", "，", ";", "；", "。", "!", "！", "?",
    "？", "·", "-", "—", "－", "_", "'", "\"", "“", "”",
)
# 明显不是答案的体裁（实测 top 噪声，逐条有据）：
#   * 「一、填空题 / 二、判断题」等题型标题
#   * 「第1章 拓展习题 / 第6章 拓展习题」等章节标题
#   * 「填入空内。」等指令残留
_ANSWER_SECTION_TITLE_LIKE = ("第%章%", "%填入空内%")
_CN_NUMERALS = "一二三四五六七八九十"

# 答案栏里出现的「占位/指引语」——它们不是答案，用户拿它比对必然判错。
# 真库实测值：「见解析」「见解析。」「略」「请注意电路中IB和IC的数量级」。
_ANSWER_PLACEHOLDER_PREFIX = ("见解析", "详见", "同上", "请注意", "注意", "提示", "略")


def answer_core_expr(model: Any = QuizQuestion) -> Any:
    """把 ``answer`` 归一为「去掉壳与标点后的核心串」的 SQL 表达式（仅剩判断用）。

    处理链：trim → 去「参考答案/答案」→ 去括号/全角空格 → trim → 去标点 → trim。
    只用于判空，不用于展示；因此全局替换标点是安全的（如 ``1.5`` → ``15`` 仍有内容）。
    """
    col: Any = model.answer
    core: Any = func.trim(col)
    for lab in _ANSWER_SHELL_LABELS:
        core = func.replace(core, lab, "")
    for ch in _ANSWER_WRAP_CHARS:
        core = func.replace(core, ch, "")
    core = func.trim(core)
    for ch in _ANSWER_PUNCT_CHARS:
        core = func.replace(core, ch, "")
    return func.trim(core)


def has_real_answer_expr(model: Any = QuizQuestion) -> Any:
    """「答案是真答案」判定：核心串非空，且不是章节/题型标题等非答案体裁。"""
    core = answer_core_expr(model)
    not_empty = func.length(core) >= 1
    # 体裁黑名单（LIKE + GLOB 组合；SQLite GLOB 支持 [0-9] 字符类）
    bad_clauses = [core.like(p) for p in _ANSWER_SECTION_TITLE_LIKE]
    # 题型标题：「一、填空题」「二、判断题」等。
    # 注意 core 已剥离标点（见 answer_core_expr），故「一、填空题」在 core 里是
    # 「一填空题」——pattern 必须用**无标点**形态，否则匹配不上。实测这两种形态：
    #   带「题」字尾（122 行）、省略「题」字尾（填空/选择/判断）。
    bad_clauses += [core.like(f"{n}%题") for n in _CN_NUMERALS]
    bad_clauses += [core.like(f"{n}填%") for n in _CN_NUMERALS]
    bad_clauses += [core.like(f"{n}选%") for n in _CN_NUMERALS]
    bad_clauses += [core.like(f"{n}判%") for n in _CN_NUMERALS]
    bad_clauses += [core.like(f"{n}简%") for n in _CN_NUMERALS]
    bad_clauses += [core.like(f"{n}名%") for n in _CN_NUMERALS]
    bad_clauses += [core.like(f"{n}解%") for n in _CN_NUMERALS]
    bad_clauses += [
        # 小问标号：全角/半角括号 + 数字。**必须用 * 覆盖任意位数** ——
        # 实测真库既有「（1）」30 行，也有「（25）」1 行，只匹配一位数会漏。
        core.op("GLOB")("（[0-9]*）"),
        core.op("GLOB")("([0-9]*)"),
    ]
    # 「详见正文」类占位语：原文是「见解析」「请注意电路中IB和IC的数量级」这类
    # 提示/指引，不是可比对的答案。真库实测漏网 6 条（id=1497「略」、1707/248/566/568
    # 「见解析」、2640/2641/2643「请注意…」、7882「（10011)」畸形标号）。
    bad_clauses += [core.like(f"{p}%") for p in _ANSWER_PLACEHOLDER_PREFIX]
    # 畸形括号标号：全角左括号配半角右括号（或反之），如实测 id=7882 的「（10011)」。
    # 判据必须建在**剥离前**的原始 answer 上 —— answer_core_expr 会把全角括号当
    # 包装字符去掉，core 里只剩「10011」，而纯数字答案（填空题常见）不能一刀切。
    raw = func.trim(model.answer)
    bad_clauses += [
        raw.op("GLOB")("（[0-9]*[)]"),
        raw.op("GLOB")("([0-9]*）"),
    ]
    return and_(not_empty, not_(or_(*bad_clauses)))


def blank_options_expr(model: Any = QuizQuestion) -> Any:
    """「options 无有效内容」判定，兼容 list / dict / JSON 字符串三种存法。

    实测口径：SQL 判定与 Python 逐行 ``json.loads`` 判定**完全一致**（均 8099 行）。
    实现依赖 SQLite JSON1（``json_valid`` / ``json_type`` / ``json_each``）；本仓库
    固定 SQLite，故可接受。SQL NULL 与 JSON ``null`` 都算空；数组/对象里
    所有元素 ``trim`` 后为空也算空。
    """
    tbl = model.__tablename__
    col = f"{tbl}.options"
    # 直接写 EXISTS / NOT EXISTS 两条 text（TextClause 不能被 not_() 取反）
    has_content = text(
        f"EXISTS (SELECT 1 FROM json_each({col}) WHERE trim(json_each.value) <> '')"
    )
    no_content = text(
        f"NOT EXISTS (SELECT 1 FROM json_each({col}) WHERE trim(json_each.value) <> '')"
    )
    legacy_blank = text(
        "trim(replace(replace(replace(replace("
        f"{col},'[',''),']',''),'\"',''),' ','')) IN ('','null','{{}}')"
    )
    return or_(
        model.options.is_(None),
        # 合法 JSON（含 'null' / '[]' / 全空白数组）：没有任何非空元素即空
        and_(text(f"coalesce(json_valid({col}),0) = 1"), no_content),
        # 非 JSON 文本兜底：清掉括号引号空白后仍为空
        and_(text(f"coalesce(json_valid({col}),0) = 0"), legacy_blank),
    )


def practiceable_expr(model: Any = QuizQuestion) -> Any:
    """「可练习」口径 = answerable + 有真答案 + 未「缺图且无选项」。

    比 ``answerable`` 更严，用于刷题入口默认出题；``answerable`` 本身保持不变。
    恒等式：practiceable ⊆ answerable ⊆ visible ⊆ raw。
    """
    missing_figure_and_blind = and_(
        func.coalesce(model.figure_missing, 0) == 1,
        blank_options_expr(model),
    )
    return and_(
        answerable_expr(model),
        not_(missing_figure_and_blind),
        has_real_answer_expr(model),
    )


def visible_quiz_filter(query: Any, include_junk: bool = False) -> Any:
    """给任意 QuizQuestion 查询套上"可见题目"过滤（默认排除 is_junk=1）。

    Args:
        query: 一个以 `QuizQuestion` 为主表的 SQLAlchemy Query。
        include_junk: True 时不加过滤（查看/审计全量）。

    Returns:
        过滤后的 Query（可直接继续 filter/group_by/count）。

    用法：
        >>> base = visible_quiz_filter(db.query(QuizQuestion.subject, func.count(QuizQuestion.id)))
        >>> base.group_by(QuizQuestion.subject).all()
    """
    if include_junk:
        return query
    # NULL 视为未标记（非碎片）→ 保留；仅排除显式 is_junk=1
    return query.filter(
        or_(QuizQuestion.is_junk.is_(False), QuizQuestion.is_junk.is_(None))
    )
