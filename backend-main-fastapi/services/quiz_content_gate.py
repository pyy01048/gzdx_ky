# -*- coding: utf-8 -*-
"""题目入库内容闸门（quiz content admission gate）。

### 为什么需要
``quiz_questions`` 存量 9164 条里有约 3576 条 JUNK，**绝大部分不是"题"**，
而是讲义正文 / PPT 条目 / 教材段落被文本切分器当成了题目：

  * 实测无答案题 5349 条，其中 ``source like '知识库:%'`` 占 4097 条、
    ``课件`` 495 条、``讲义`` 486 条 —— 全部来自
    ``services/qbank_builder.extract_questions`` 的裸编号切分。

``extract_questions`` 的原实现只有两道防线（题号 <4 位、必须先出现
"一、填空题"这类大标题），**完全没有"这段文字像不像一道可回答的考试题"的校验**：

  1. ``_SECTION_RE`` 会把讲义里的"一、设计步骤：…"当成"设计"题型大标题，
     于是整篇讲义进入切题状态；
  2. ``_QNUM_RE`` 看到讲义里任意一行以"1. / 2、"开头就切一刀，
     于是"设计关键：…"这种说明文字成了题干；
  3. 切出来的块没有最小长度之外的任何语义校验。

本模块提供**唯一一份**"像不像题"的判定逻辑，供两处共用，避免逻辑漂移：

  * ``scripts/quiz_quality_gate.py`` —— 存量体检/分级（历史数据）
  * ``services/qbank_builder.extract_questions`` 等抽取管线 —— **入库前闸门**

### 开关
环境变量 ``QUIZ_CONTENT_GATE``：
  * 未设置 / ``1`` / ``true`` / ``on`` / ``yes`` → **开启（默认）**
  * ``0`` / ``false`` / ``off`` / ``no`` → 关闭（回退到旧行为，仅供应急排障）

计数器 ``GATE_STATS`` 为进程级累计量，配合 ``gate_log_summary()`` 打日志。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from collections import Counter
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Set, Tuple

logger = logging.getLogger("quiz_content_gate")

# --------------------------------------------------------------------------- #
# 一、正则与词表（自 quiz_quality_gate.py 迁移而来，此处为唯一真源）
# --------------------------------------------------------------------------- #
#: 来源分类
LECTURE_SRC = re.compile(r"课件|讲义|教案|培训|辅导|精讲|复习|考点|笔记|手册|指南|攻略")
REAL_SRC = re.compile(r"真题|试题|试卷|联考|题库|月考|期末|期中")

#: 题干像题的特征词
Q_MARK: Tuple[str, ...] = (
    "？", "?", "____", "（ ）", "（）", "( )", "()", "（  ", "求：", "试：", "简述", "设计",
    "计算", "画出", "写出", "说明", "选择", "判断", "填空", "已知",
    "分析", "证明", "列举", "论述", "为什么", "如何", "哪些",
)
#: 答案体特征（题干位置却是答案）
ANS_START: Tuple[str, ...] = (
    "解：", "答：", "答案", "解析", "解:", "答:", "参考答", "【解】",
)
ANS_MID: Tuple[str, ...] = (
    "故选", "故答案", "因此答案", "所以答案", "答案为", "答案：", "故选择",
)
#: PPT / 讲义结构残留
PPT_RESIDUE: Tuple[str, ...] = (
    "返回", "下页", "上页", "内容盛要", "内容提要", "放映", "幻灯片",
    "点击", "页 共", "第 页", "共页",
)
#: 乱码（U+FFFD REPLACEMENT CHARACTER）
MOJIBAKE = "\ufffd"

#: 中文字符区间（用于"是否含中文"判定）
_CJK_RE = re.compile(r"[\u4e00-\u9fa5]")

# --------------------------------------------------------------------------- #
# 二、阈值
# --------------------------------------------------------------------------- #
#: 考试题型（section_type 命中这些值时允许"陈述式"题目，见 admit 第 3.5 步）
EXAM_SECTIONS = frozenset({
    "选择", "多选", "判断", "填空", "简答", "计算", "分析",
    "设计", "证明", "画图", "论述", "综合",
})
#: 陈述式题目（判断题）的长度上限
MAX_LEN_DECLARATIVE = 150
#: 讲义/课件来源的无选项题干长度上限
LECTURE_MAX_LEN = 300

MIN_LEN = 15                # 题干最小长度
MIN_LEN_ANSWERED = 10      # 有答案时的最小长度
MAX_LEN_NO_ANSWER = 400    # 无答案题干长度上限（超过即视为讲义长段落）
MAX_LEN_ANSWERED = 1200    # 有答案题干长度上限
MIN_OPTIONS = 2            # 选项数下限（有选项本身就是强"像题"信号）

#: 选项切出后允许「题干+选项」合计长度参与过短判定的最小选项数。
#:
#: **这里刻意与 :data:`MIN_OPTIONS`(=2) 不同，是有意的，不是笔误**：
#:
#: - ``MIN_OPTIONS = 2`` 用在第 4 层「是不是选择题」的判定上。只要有 2 个选项
#:   就承认它是选择题 —— 真实卷面里「A、对  B、错」两项判断题很常见。
#: - ``MIN_OPTIONS_FOR_SHORT_STEM = 3`` 用在第 1 层「题干是否过短」的豁免上。
#:   豁免一道题的长度门槛是**降低标准**，代价更高，因此要求更强的证据：
#:   至少 3 个选项，才认为「题干短但选项长」是可信的真题形态。
#:   若这里也放成 2，则「A、x  B、y」这类两碎片即可绕过 15 字门槛，
#:   正是3570 条 JUNK 里那类碎片题的成因。
#:
#: 另注：原先此处的注释写作「与 extraction_noise.MIN_OPTION_COUNT 同值」，
#: 但 :data:`MIN_OPTION_COUNT` 实为 2，**注释与实现不符**（本周已因此出过两次误判），
#: 故改为上面这段说明真实意图的文字。extraction_noise 侧与本常量无关，
#: 它管的是「要不要切选项」，本常量管的是「切完要不要豁免长度」，两者目的不同。
MIN_OPTIONS_FOR_SHORT_STEM = 3

#: 声称是真题时，额外要求的证据数（更严格，见模块 docstring）
REAL_SOURCE_STRICT = True

# --------------------------------------------------------------------------- #
# 二之二、第 6 层：判重签名 + 同题干答案冲突检测
#
# 事故背景（quiz-answer-gap 定位，2026-10-12）：
#   1) ``qbank_builder.content_hash`` 只对 content 做 MD5，**不含 answer**，
#      于是"同题干不同答案"的一对题指纹不同 → 判重器认为它们不是重复，
#      两条都入库。实测恢复后仍有 31 组同题干重复，其中 19 组答案互相矛盾。
#   2) 判重器在清理时也只看 content，于是"删重复"会随机留下错误的那一条。
#   两个事故同源：**判重只看 content 不看 answer**。
#
# 本层提供两个能力：
#   - ``question_signature()``：判重签名 = 归一化(content) + 归一化(answer) 一起哈希。
#   - ``detect_answer_conflict()``：同一归一化题干下已有**不同**答案 → 拒绝入库。
# --------------------------------------------------------------------------- #

#: 归一化时剥除的 OCR 乱码（U+FFFD 等私有区/控制字符）
OCR_JUNK_RE = re.compile(r"[\ufffd\ufffe\u001a-\u001f\ue000-\uf8ff]+")
#: 填空位统一（`____` / `＿＿` / `（ ）` / `……` 都视为同一个占位）
BLANK_RE = re.compile(r"[_＿﹍﹏]{2,}|[（(]\s*[）)]|…+|\.{3,}")
#: 归一化时剥除的标点/空白（中英文）
PUNCT_WS_RE = re.compile(r"[\s，。、；：？！“”‘’（）()【】\[\]{}<>《》·.,;:?!\"'/\\|~`@#\$%\^&\*\+=_\-－]+")

#: 低于此归一化长度的题干跳过冲突检测（太短易误报，且无判定价值）
MIN_CONFLICT_STEM_LEN = 12
#: 冲突索引构造时的归一化题干长度上限（超长段落本就不是题，省内存）
MAX_INDEX_STEM_LEN = 400


def normalize_dedup(text: Any) -> str:
    """判重归一化：剥 OCR 乱码 → 填空位归一 → 去标点空白 → 小写。

    这是本模块判重与冲突检测的唯一归一化口径，**不要**与
    ``qbank_builder.normalize_text`` 混用（后者不剥乱码、不归一填空位，
    正是重复题检测失效的根因之一）。
    """
    s = str(text or "")
    s = OCR_JUNK_RE.sub("", s)
    s = BLANK_RE.sub("　", s)
    s = PUNCT_WS_RE.sub("", s)
    return s.strip().lower()


def question_signature(content: Any, answer: Any = None) -> str:
    """判重签名：**content 与 answer 归一化后一起**哈希（16 位十六进制）。

    与 ``qbank_builder.content_hash`` 的区别是本函数必须带 answer，
    否则"同题干不同答案"的一对题会得到相同签名而被误判为同一条。
    答案为空时以哨兵 ``<noans>`` 占位，保证"无答案"与"有答案"不同签。
    """
    c = normalize_dedup(content)
    a = normalize_dedup(answer) or "<noans>"
    return hashlib.md5(f"{c}\x1f{a}".encode("utf-8")).hexdigest()[:16]


def stem_signature(content: Any) -> str:
    """题干签名（不含答案），专供同题干冲突检测使用。"""
    return normalize_dedup(content)


def build_stem_answer_index(
    rows: Iterable[Tuple[Any, Any]],
) -> Dict[str, Set[str]]:
    """由存量 ``(content, answer)`` 行构造 "归一化题干 → 该题干下已见答案集合"。

    - 题干归一化后长度 < ``MIN_CONFLICT_STEM_LEN`` 的行不入索引（检测时跳过）；
    - 只收录答案非空的行 —— 空答案不构成"冲突"证据（存量大量无答案题）；
    - 过长的段落不入索引（本就不是题，建索引纯属浪费）。
    """
    index: Dict[str, Set[str]] = {}
    for content, answer in rows:
        ans = normalize_dedup(answer)
        if not ans:
            continue
        stem = stem_signature(content)
        if len(stem) < MIN_CONFLICT_STEM_LEN or len(stem) > MAX_INDEX_STEM_LEN:
            continue
        index.setdefault(stem, set()).add(ans)
    return index


def build_stem_text_list(
    rows: Iterable[Tuple[Any, Any]],
) -> list[str]:
    """L2 相似层用：返回所有可参与相似比对的"归一化题干"列表。

    过滤规则与 :func:`build_stem_answer_index` 一致（长度区间），
    但**不按题干去重**（L2 的目的正是找出"相似但不完全相同"的题干对）。
    """
    out: list[str] = []
    for content, _answer in rows:
        stem = stem_signature(content)
        if MIN_CONFLICT_STEM_LEN <= len(stem) <= MAX_INDEX_STEM_LEN:
            out.append(stem)
    return out


def stem_similarity_alert_enabled() -> bool:
    """L2 相似告警层开关（环境变量 ``QUIZ_STEM_SIMILARITY_ALERT``）。

    **默认 0（关闭）** —— L2 要对每条候选与全库题干算相似度，开销显著，
    不能默认挂在切题主链路上。开启方式：``QUIZ_STEM_SIMILARITY_ALERT=1``。
    """
    raw = os.getenv("QUIZ_STEM_SIMILARITY_ALERT")
    if raw is None:
        return False
    v = raw.strip().lower()
    if v in _FALSY:
        return False
    if v in _TRUTHY:
        return True
    logger.warning("QUIZ_STEM_SIMILARITY_ALERT=%r 无法识别，按默认关闭处理", raw)
    return False


def detect_answer_conflict(
    content: Any,
    answer: Any,
    existing: Optional[Mapping[str, Set[str]]],
) -> Tuple[bool, str]:
    """同题干答案冲突检测。

    返回 ``(是否冲突, 详情)``。冲突判定：归一化题干在 ``existing`` 中已存在，
    且已有答案与本条归一化答案**不相同**。

    以下情况一律判为不冲突（宁可放过，不可错杀）：
      - ``existing`` 为空/未提供（调用方未接索引）；
      - 本条无答案（空答案不能与任何答案冲突）；
      - 归一化题干短于 ``MIN_CONFLICT_STEM_LEN``（短文本碰撞率高）；
      - 该题干下已有多个不同答案（历史遗留冲突，非本条责任，仍拒绝以免加深）。
    """
    if not existing:
        return False, ""
    new_ans = normalize_dedup(answer)
    if not new_ans:
        return False, ""
    stem = stem_signature(content)
    if len(stem) < MIN_CONFLICT_STEM_LEN:
        return False, ""
    seen = existing.get(stem)
    if not seen:
        return False, ""
    if new_ans in seen:
        return False, ""
    prev = sorted(seen)[0][:40]
    return True, f"同题干已有答案「{prev}」，本条为「{new_ans[:40]}」"


#: L2 相似层阈值（与 qbank_builder.is_duplicate / kb_import.SIMILARITY_THRESHOLD 一致）
STEM_SIMILARITY_THRESHOLD = 0.86


def detect_stem_similarity_alert(
    content: Any,
    answer: Any,
    stems: Optional[Sequence[str]],
    *,
    threshold: float = STEM_SIMILARITY_THRESHOLD,
) -> Tuple[bool, str]:
    """**L2 相似层：仅告警，绝不拒收。**

    与 L1 :func:`detect_answer_conflict` 的分工：
      - L1（精确层）：归一化题干**完全相同** + 答案不同 → **硬拒收**；
      - L2（本函数）：题干**相似但不完全相同**（相似度 >= threshold）+ 答案不同
        → **不拒收**，只产出告警文案交由调用方写日志。

    为什么 L2 不拒收：0.86 相似度在短文本上会把「下列说法正确的是」这类
    模板化题干判成同题干，硬拒收等于批量误杀。本周已有 158 条误删的账，
    不能再开新口子。L2 的成本只是日志行数，收益是人工复核时有线索。

    相似度算法**复用** ``qbank_builder.similarity_ratio``（不另写一套），
    但比较的是**本模块归一化后**的题干（``normalize_dedup``），因为
    ``similarity_ratio`` 内部的旧归一化不剥 OCR 乱码、不归一填空位。

    返回 ``(是否告警, 详情)``。以下情况一律不告警：
      - ``stems`` 为空/未提供；
      - 归一化题干短于 ``MIN_CONFLICT_STEM_LEN``；
      - 本条无答案；
      - 没有题干相似度达到 ``threshold``；
      - 最相似的那条题干恰好就是本条自己（L1 已处理的精确同题干）。
    """
    if not stems:
        return False, ""
    new_ans = normalize_dedup(answer)
    if not new_ans:
        return False, ""
    stem = stem_signature(content)
    if len(stem) < MIN_CONFLICT_STEM_LEN:
        return False, ""

    # 延迟导入：避免模块级耦合，similarity_ratio 是唯一算法来源
    from services import qbank_builder as _qb

    lo, hi = int(len(stem) * 0.6), int(len(stem) / 0.6) + 1
    best, best_other = 0.0, ""
    for other in stems:
        if other == stem:            # 精确同题干归 L1，不在 L2 告警
            continue
        if not (lo <= len(other) <= hi):
            continue                  # 长度差过大必不相似，粗筛
        r = _qb.similarity_ratio(stem, other)
        if r > best:
            best, best_other = r, other
    if best < threshold:
        return False, ""
    return True, (f"相似题干告警(非精确冲突, 不拒收)：库中有一条相似度 "
                  f"{best:.3f} 的题干「{best_other[:40]}」")


# --------------------------------------------------------------------------- #
# 三、开关与计数器
# --------------------------------------------------------------------------- #
_TRUTHY = {"1", "true", "on", "yes", "y", "t"}
_FALSY = {"0", "false", "off", "no", "n", "f"}

GATE_STATS: "Counter[str]" = Counter()
_STATS_LOCK = threading.Lock()


def gate_enabled() -> bool:
    """闸门总开关，默认开启。"""
    raw = os.getenv("QUIZ_CONTENT_GATE")
    if raw is None:
        return True
    v = raw.strip().lower()
    if v in _FALSY:
        return False
    if v in _TRUTHY:
        return True
    logger.warning("QUIZ_CONTENT_GATE=%r 无法识别，按默认开启处理", raw)
    return True


def gate_stats_snapshot() -> Dict[str, int]:
    with _STATS_LOCK:
        return dict(GATE_STATS)


def gate_reset_stats() -> None:
    with _STATS_LOCK:
        GATE_STATS.clear()


def gate_log_summary(logger_: Optional[logging.Logger] = None) -> Dict[str, int]:
    """打印并返回闸门计数摘要。"""
    lg = logger_ or logger
    snap = gate_stats_snapshot()
    admitted = snap.get("admitted", 0)
    rejected = sum(v for k, v in snap.items() if k.startswith("reject:"))
    lg.info(
        "[quiz_content_gate] 候选=%d 通过=%d 拦截=%d 明细=%s",
        admitted + rejected, admitted, rejected,
        {k[7:]: v for k, v in sorted(snap.items()) if k.startswith("reject:")},
    )
    return snap


def _bump(reason: str) -> None:
    with _STATS_LOCK:
        GATE_STATS[reason] += 1


# --------------------------------------------------------------------------- #
# 四、基础启发式（可单独复用）
# --------------------------------------------------------------------------- #
def has_answer(a: Any) -> bool:
    """答案是否非空。"""
    return a is not None and str(a).strip() != ""


def looks_like_question(c: str) -> bool:
    """题干是否含"可回答"特征词。

    先做空白归一化再匹配 —— OCR/课件文本里"（ ）"常变成"（  ）"（多空格），
    不归一化会漏判判断题/填空题。
    """
    if any(k in c for k in Q_MARK):
        return True
    flat = re.sub(r"[ \t　]+", "", c)
    return any(k in flat for k in Q_MARK)


def looks_like_answer_body(c: str) -> bool:
    """题干位置放的其实是答案/解析。

    注意一个陷阱：不能只用 ``ANS_MID and not looks_like_question(s)`` 判定 ——
    "因此答案：因为场效应管…设计时通常选择…" 里含"设计"（Q_MARK 词），
    于是 looks_like_question 为真，答案体就能混过去。所以额外要求
    答案信号出现在**句首 12 字内**（真正的答案体一定以它开头）。
    """
    s = c.strip()
    if any(s.startswith(k) for k in ANS_START):
        return True
    head = s[:12]
    if any(k in head for k in ANS_MID):
        return True
    # 含明显答案信号且没有任何题目特征
    if any(k in s for k in ANS_MID) and not looks_like_question(s):
        return True
    return False


def has_ppt_residue(c: str) -> bool:
    """PPT/讲义版式残留（命中 >=2 个才算）。"""
    return sum(1 for k in PPT_RESIDUE if k in c) >= 2


def is_mojibake(c: str) -> bool:
    return MOJIBAKE in c


def mostly_symbol(c: str) -> bool:
    """无中文且短、无英文单词 → 符号噪声。"""
    if not _CJK_RE.search(c):
        if len(c.strip()) < 25 and not re.search(r"[a-zA-Z]{3,}", c):
            return True
    return False


def _looks_like_prose(c: str) -> bool:
    """讲义/教材叙述体特征：出现"…是…"的定义句、包含/因此/所谓等叙述连接词。"""
    markers = (
        "所谓", "因此", "从而", "综上", "也就是说", "换言之", "需要注意",
        "设计步骤", "设计关键", "比较：", "特点：", "优点：", "缺点：",
        "小结：", "重点：", "难点：", "结论：", "引出", "下面看", "接下来",
    )
    hits = sum(1 for m in markers if m in c)
    # 句号/分号密集也是叙述体
    punct = c.count("。") + c.count("；")
    return hits >= 1 or punct >= 3


# --------------------------------------------------------------------------- #
# 五、闸门主体
# --------------------------------------------------------------------------- #
def admit(
    content: str,
    *,
    options: Any = None,
    answer: Any = None,
    source: str = "",
    section_type: str = "",
    stem_answer_index: Optional[Mapping[str, Set[str]]] = None,
    stem_text_list: Optional[Sequence[str]] = None,
) -> Tuple[bool, str]:
    """判定一条候选题是否允许入库。

    返回 ``(是否放行, 原因)``。原因在放行时为 ``"admitted"``，
    拦截时为 ``"reject:<简述>"``（同时计入 ``GATE_STATS``）。

    ``source`` 声称是真题/试卷时**更严格**：仅靠长度和"有选项"不足以放行，
    必须同时具备明确的题目特征词，否则视为"挂着真题名的讲义正文"。

    ``stem_answer_index``：可选的"归一化题干 → 已见答案集合"索引（由
    ``build_stem_answer_index`` 从存量构造）。传入后启用**第 7 层**同题干
    答案冲突检测：同题干已有不同答案则拒绝入库，并写 warning 日志。

    ``stem_text_list``：可选的全库归一化题干列表（``build_stem_text_list``）。
    仅在环境变量 ``QUIZ_STEM_SIMILARITY_ALERT`` 打开时用于**第 8 层**相似告警；
    本层**只写日志、绝不拒收**。
    """
    if not gate_enabled():
        _bump("admitted")
        return True, "admitted(gate-off)"

    c = (content or "").strip()
    src = source or ""
    opts = options if isinstance(options, (list, tuple)) else []
    opts = [str(o).strip() for o in opts if str(o).strip()]
    ans_ok = has_answer(answer)

    def _reject(reason: str) -> Tuple[bool, str]:
        _bump("reject:" + reason)
        return False, "reject:" + reason

    # —— 1. 硬性垃圾（无论来源、无无论否有答案）——
    # 长度判据需计入选项：切题源头修复后选项被整体切出，题干本身会显著变短
    # （如「N 型半导体的多子是（ ）」仅 15 字但配4 个完整选项，是合法题）。
    # 只有选项数达到结构下限（3个）时才允许用「题干+选项」合计长度，
    # 避免放宽后放进「A. x B. y」这种碎片。
    measured = c
    if len(opts) >= MIN_OPTIONS_FOR_SHORT_STEM:
        measured = c + "".join(opts)
    min_len = MIN_LEN_ANSWERED if ans_ok else MIN_LEN
    if len(measured) < min_len:
        return _reject("内容过短")
    if is_mojibake(c):
        return _reject("OCR乱码")
    if mostly_symbol(c):
        return _reject("纯符号噪声")
    if looks_like_answer_body(c):
        return _reject("答案体当题干")
    if has_ppt_residue(c):
        return _reject("PPT/讲义结构残留")
    if re.fullmatch(r"[\d\s.\-]+", c):
        return _reject("纯数字")
    if re.fullmatch(r"[\W_]+", c):
        return _reject("纯标点")

    # —— 2. 篇幅闸门：讲义长段落不是题 ——
    max_len = MAX_LEN_ANSWERED if ans_ok else MAX_LEN_NO_ANSWER
    if len(c) > max_len:
        return _reject("超长段落(疑似讲义正文)")

    # —— 3. 核心闸门：像不像一道"可回答的考试题"——
    #    注意：本层**只做"宽松基线"判定**（三选一即可），把来源相关的差异
    #    全部留给第 4/5 层，避免本层提前拦掉后面才用得上的判据。
    has_qmark = looks_like_question(c)
    has_opts = len(opts) >= MIN_OPTIONS
    # 判断题的"（ ）"已被 Q_MARK 的"（ ）"覆盖；填空题的"____"同理
    declarative_ok = False
    if not (has_qmark or has_opts):
        # 3.5 陈述式豁免：判断题/简答题常写成一句陈述 + 有标准答案，
        #      不带问号也不带括号（例："译码器在工作时不存在竞争冒险现象，
        #      输出是唯一确定的逻辑电平。" 答案：错）。
        #      仅在「题型属于考试题型 + 有答案 + 单句 + 不超长 + 非叙述体」时放行。
        if (
            ans_ok
            and section_type in EXAM_SECTIONS
            and len(c) <= MAX_LEN_DECLARATIVE
            and c.count("。") + c.count("；") <= 1
            and not _looks_like_prose(c)
        ):
            declarative_ok = True
    if not (has_qmark or has_opts or declarative_ok):
        return _reject("无题目特征(不像可回答的题)")

    # —— 4. 叙述体检测（仅对"非真题来源"作为基线拦截）——
    # 有选项的题天然带特征词，故只在无选项时收紧。
    # 真题来源不在此拦：它的叙述体判定要连同长度一起在第 5 层做（更精细）。
    if not REAL_SRC.search(src) and not has_opts and _looks_like_prose(c):
        return _reject("叙述体段落(知识点讲解)")

    # —— 5. 声称真题/试卷 → 加严 ——
    # 讲义正文最典型的伪造形态就是 source 写着"真题"但内容是课件段落。
    # 这一层**必须比第 3/4 层更严**才有意义，因此它的判据不能是
    # "有没有特征词"（第 3 层已保证），而是第 3/4 层放过的**灰区**：
    #   (a) 靠 declarative_ok 勉强过关、但既无问号也无选项的陈述句；
    #   (b) 带问号却仍是叙述体的段落（不论长度）。
    # 这两条都无法被第 3/4 层拦下，所以本层可达。
    if REAL_SOURCE_STRICT and REAL_SRC.search(src):
        # (a) 声称真题却只有陈述句兜底、没有问号也没有选项 → 放宽容忍度降低
        if declarative_ok and not has_qmark and not has_opts:
            return _reject("声称真题但无题目特征词")
        # (b) 带问号的叙述体 → 典型"挂着真题名的讲义页"。
        #     不设长度门槛：讲义段落往往只有几十字（"因此…；综上…"），
        #     长度门槛反而给了它逃逸通道；真正的真题判断/简答题干不含这些叙述连接词。
        if not has_opts and _looks_like_prose(c):
            return _reject("声称真题但为长段讲义")

    # —— 6. 讲义/课件来源 → 略微加严：无选项且缺特征词已在上方拦掉，
    #         这里再要求"不能是纯定义句" ——
    if LECTURE_SRC.search(src) and not has_opts and len(c) > LECTURE_MAX_LEN:
        return _reject("讲义来源长段落")

    # —— 7. 同题干答案冲突检测（须显式传入 stem_answer_index 才生效）——
    #    放在最后：前面的硬垃圾/篇幅/像题判定已排除"根本不是题"的候选，
    #    到这里才有意义（一条不是题的候选没有资格引发答案冲突告警）。
    conflicted, detail = detect_answer_conflict(c, answer, stem_answer_index)
    if conflicted:
        logger.warning(
            "[quiz_content_gate] 拒绝入库：同题干答案冲突。题干=%r 详情=%s",
            c[:60], detail,
        )
        return _reject("同题干答案冲突")

    # —— 8. L2 相似层：**仅告警，不拒收** ——
    #    默认关闭（QUIZ_STEM_SIMILARITY_ALERT=1 才开），因为要对全库题干算相似度。
    #    即使开启，本层也只写日志、绝不改变 admit 的返回值 —— 这是它与 L1 的
    #    根本区别：L1 拒收是因为"确定冲突"，L2 只因为"看起来像"。
    if stem_similarity_alert_enabled():
        alerted, alert_detail = detect_stem_similarity_alert(c, answer, stem_text_list)
        if alerted:
            logger.warning(
                "[quiz_content_gate] %s。题干=%r", alert_detail, c[:60],
            )
            _bump("alert:stem_similarity")

    _bump("admitted")
    return True, "admitted"


def admit_or_raise(*args: Any, **kwargs: Any) -> bool:
    """``admit`` 的断言式封装：拦截时抛 ``ValueError``（含原因）。"""
    ok, reason = admit(*args, **kwargs)
    if not ok:
        raise ValueError(reason)
    return True
