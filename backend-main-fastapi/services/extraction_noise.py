# -*- coding: utf-8 -*-
"""切题源头三处修复的判据函数（纯函数，无副作用，可单测）。

背景：`quiz_questions` 里 49 组「答案冲突」人工裁决后，31 组判为「需隔离」，
根因全部落在切题阶段，而不是入库判重阶段。本模块把这三个根因各自固化成一个
可独立测试的判据函数：

1. :func:`is_running_header_noise` —— 页眉/页脚/试卷通知白名单过滤。
   典型噪声：「第8 音拓展习题」「科目代码：834」「必须写在答题纸上否则后果自负！」。
2. :func:`split_stem_and_options` —— 选项列表必须与题干整体切出。
   现状是「只有 sec_type 属于选择/多选/判断时才拆选项」，一旦 sec_type 没识别上，
   选项就整体留进题干，答案只剩一个字母 A/B/C/D。
3. :func:`strip_cross_question_leak` —— 跨题串接检测。
   题干尾部出现「四、简答题（共4题，每题6分，共24分）」说明上一题的切块
   吃掉了下一个题型大标题，本题应判为切题失败。

设计原则（沿用本项目一贯教训）：**宁可漏判，不可误杀**。
每个判据都提供「明确证据」才返回 True 的分支；含混不清一律返回 False。
"""

from __future__ import annotations

import os
import re
from typing import Any

__all__ = [
    "is_running_header_noise",
    "is_whole_line_noise",
    "clean_answer",
    "clean_content",
    "split_stem_and_options",
    "strip_cross_question_leak",
    "find_cross_question_leak",
    "MIN_OPTION_COUNT",
    "SPLIT_OPTIONS_ENV",
    "split_options_enabled",
]


# --------------------------------------------------------------------------- #
# 1. 页眉 / 页脚 / 试卷通知噪声
# --------------------------------------------------------------------------- #

#: 试卷通知类整句。这类文本出现在试卷首页「考生注意」段落，
#: 其中「全部答案必须写在答题纸上」里的「答案」二字会被答案正则当成答案标签，
#: 从而把「必须写在答题纸上否则后果自负！）」当成答案切出来。
_NOTICE_SENTENCE_RE = re.compile(
    r"(?:必须写在答题纸|写在答题纸或答题卡上|本试题纸须随答题纸|"
    r"考生注意|注意事项：|作答无效|交回！|装入试题袋)"
)

#: 试卷/试卷册的元信息行（科目代码、科目名称、页码、水印）。
_META_LINE_RE = re.compile(
    r"^\s*(?:"
    r"科目代码\s*[:：]?|"
    r"科目名称\s*[:：]?|"
    r"考试科目代码\s*[:：]?|"
    r"考试科目\s*[:：]?|"
    r"专业代码\s*[:：]?|"
    r"考生须知|"
    r"第\s*\d+\s*页|"
    r"共\s*\d+\s*页|"
    r"试卷类型\s*[:：]?|"
    r"密封线|密封线内不要答题"
    r")"
)

#: 公众号/微信引流水印行。
_WATERMARK_RE = re.compile(
    r"(?:微信公众号|微信号|加微信|QQ\s*[:：]?\s*\d{6,}|"
    r"考研\s*qq|微信\s*[:：]|扫描二维码|扫码获取)"
)

#: 目录/章节页眉残片：「第8章 部分自测题和习题参考答案」「第8 音拓展习题及解答」。
#: 判据是「以『第N』开头 + 含习题/自测/参考/讲解 等版面包」且不含问号。
_CHAPTER_HEADER_RE = re.compile(
    r"^\s*第\s*\d+\s*[章节讲]?\s*"
    r"[^\n]{0,40}?"
    r"(?:习题|自测|参考答案|答案与解析|及解答|解析|思考题|复习题|习题集)"
    r"[^\n]{0,20}$"
)

#: 「习题 399」这种只剩页码数字的版面包。
_PAGE_NUMBER_RE = re.compile(r"^\s*(?:习题|例题|思考题)\s*\d{1,4}\s*$")

#: 明显的题型大标题行（本身是版面包，不是正文）。
#: 注意：这里只匹配**整行就是标题**的情形，题干中间提到「选择题」不会被误杀。
_SECTION_HEADER_LINE_RE = re.compile(
    r"^\s*[一二三四五六七八九十]+\s*[、.．]\s*"
    r"[^\n]{2,20}?"
    r"(?:题|选择|填空|判断|简答|计算|分析|设计|证明|作图|画图|论述|综合)"
    r"\s*(?:[（(][^）)]*[）)])?\s*$"
)


def is_whole_line_noise(text: str | None) -> bool:
    """判断 ``text`` **整行**都是版面噪声（可安全丢弃整行）。

    与 :func:`is_running_header_noise` 的区别：后者对「水印 / 考生须知」这类
    行内特征也返回 True，表示**该片段必须抹掉**；但真实卷面常把水印和正文
    排在同一行（如「判断反馈组态 东坡哥微信:haidongpo8 第 3 页」），
    此时整行丢弃会连题干一起丢。

    因此整行丢弃只认**结构性**版面包：试卷元信息行、章节页眉残片、
    纯页码行、整行题型大标题。水印/通知交由 :func:`clean_content` 行内抹除。

    Args:
        text: 待判定文本行。

    Returns:
        True 表示整行可丢弃。
    """
    if not text:
        return False
    t = text.strip()
    if not t:
        return False
    return bool(
        _META_LINE_RE.match(t)
        or _CHAPTER_HEADER_RE.match(t)
        or _PAGE_NUMBER_RE.match(t)
        or _SECTION_HEADER_LINE_RE.match(t)
    )


def is_running_header_noise(text: str | None) -> bool:
    """判断 ``text`` 是否为教材页眉/页脚/试卷通知等版面噪声。

    只有命中下列**明确特征**才返回 True：

    - 整行是试卷元信息（科目代码/科目名称/页码/密封线…）
    - 含公众号/微信引流水印
    - 含「必须写在答题纸上」这类考生须知整句
    - 以「第N章…习题/自测/参考答案」开头的章节页眉残片
    - 整行只剩「习题 399」这种页码

    防误杀：题干里正常提到「选择题」「参考答案」「第3题」等字样一律返回 False，
    因为本函数要求**整行匹配**版面包结构，或命中不可伪装的整句通知。

    Args:
        text: 待判定文本，允许为 ``None``。

    Returns:
        True 表示可安全丢弃；False 表示应保留。
    """
    if not text:
        return False
    t = text.strip()
    if not t:
        return False

    # 结构性版面包：整行丢弃（见 is_whole_line_noise）
    if is_whole_line_noise(t):
        return True

    # 行内包含类（这几类特征不会被题干正常措辞伪造）
    if _NOTICE_SENTENCE_RE.search(t):
        return True
    if _WATERMARK_RE.search(t):
        return True

    return False


def clean_answer(answer: str | None) -> str | None:
    """清洗答案字段：页眉/通知类答案直接置空；空值归一为 ``None``。

    典型收益：``"第8 音拓展习题"`` / ``"必须写在答题纸上否则后果自负！）"``
    / ``"四、简答题（共4题，每题6分，共24分）"`` 这三条脏答案会变为 ``None``。

    Args:
        answer: 原始答案文本。

    Returns:
        合法答案字符串，或 ``None``（表示不可用）。
    """
    if answer is None:
        return None
    t = answer.strip()
    if not t:
        return None
    if is_running_header_noise(t):
        return None
    return t


def clean_content(content: str | None) -> str:
    """清洗题干字段：剔除内嵌的页眉/通知/水印片段。

    只做**行级**剔除，不改写题干文字本身，保证正常题目内容零改动。

    Args:
        content: 原始题干文本。

    Returns:
        清洗后的题干；若整段都是噪声则返回空串。
    """
    if not content:
        return ""
    lines: list[str] = []
    for line in content.splitlines():
        # 整行丢弃只认结构性版面包；水印/通知走下面的行内抹除，
        # 否则「判断反馈组态 东坡哥微信:xxx 第3页」这类题会被整行丢掉。
        if is_whole_line_noise(line):
            continue
        # 行内噪声：真实卷面常把水印/通知和正文排在同一行（如
        # 「判断反馈组态 水木观畴，你身边的考研专家！ 东坡哥微信:haidongpo8」），
        # 只做整行过滤会漏掉这类。行内剔除仅针对不可伪造的强特征。
        for pat in (_NOTICE_SENTENCE_RE, _WATERMARK_RE):
            line = pat.sub(" ", line)
        line = re.sub(r"[ \t]{2,}", " ", line).strip()
        if line:
            lines.append(line)
    out = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", out)


# --------------------------------------------------------------------------- #
# 2. 选项必须与题干整体切出
# --------------------------------------------------------------------------- #

#: 选项标签：A、/ A./ A．/ A) / A） —— 与 qbank_builder._OPTION_RE 同口径。
#: 前缀允许空白或中文标点，因为真实卷面常出现「（ ）A. xxx」这种紧贴写法。
_OPTION_LABEL_RE = re.compile(
    r"(?:^|[\s，,。；;：:、（()）\[\]【】])([A-F])(\s*[、.．)）]\s*)"
)

#: 触发拆分的最小连续选项数。
#: 与 quiz_content_gate.MIN_OPTIONS(=2) 对齐：真实卷面里「A、B」两项的判断题
#: 很常见，门槛若设为 3 会让这类题的选项整体留在题干里，答案退化成孤立字母。
MIN_OPTION_COUNT = 2


#: 第 2 处修复（选项整体切出）的环境变量开关名。
SPLIT_OPTIONS_ENV = "QUIZ_EXTRACT_SPLIT_OPTIONS"

#: 第 2 处修复的**默认值**。team-lead 裁定「保留代码但默认关闭」：
#: 取证显示 #7931 的选项本来就在库里，而本判据要求标签「从 A 起严格递增」，
#: 对 PDF 排版乱序（B/C/A/D）的卷面会误判为「无选项」从而清空已有 options。
#: 在 A 类 190 条回源抽样给出结论之前，一律走修复前路径。
_SPLIT_OPTIONS_DEFAULT = "0"


def split_options_enabled() -> bool:
    """第 2 处修复（选项整体切出）是否启用。**默认关闭**。

    只有环境变量 :data:`SPLIT_OPTIONS_ENV` 显式置为 ``1/true/yes`` 时才启用。
    关闭时调用方必须走 :func:`qbank_builder` 内的修复前路径（依赖 ``sec_type``）。
    """
    raw = os.environ.get(SPLIT_OPTIONS_ENV, _SPLIT_OPTIONS_DEFAULT)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def split_stem_and_options(
    body: str,
    sec_type: str | None = None,
    *,
    min_count: int = MIN_OPTION_COUNT,
) -> tuple[str, list[str]]:
    """把 ``body`` 拆成 (题干, 选项列表)，**不依赖 sec_type**。

    现状痛点：``qbank_builder.extract_questions`` 只在 ``sec_type in
    ("选择", "多选", "判断")`` 时才拆选项。sec_type 没识别上时，选项被整体
    并进题干，答案就只剩一个孤立字母 —— 这是 26 条「答案仅为 A/B/C/D」的成因。

    本函数改用**结构性判据**：选项标签必须形成 A→B→C 至少 ``min_count`` 个
    连续递增标签，才认定为选择题并整体切出。

    防误杀要点：

    - 标签序列必须**从 A 开始且严格递增**，正文里偶然出现的「A.」不会被当选项；
    - 标签之间必须都在同一段落内且总跨度合理（防止跨整页误抓）；
    - ``sec_type`` 已判定为选择类时，仍走同一套结构判据，不无条件拆分。

    Args:
        body: 待拆分的题块正文。
        sec_type: 已识别的题型（仅作为辅助信息，不强制决定是否拆分）。
        min_count: 触发拆分的最小连续选项数。

    Returns:
        ``(stem, options)``。``options`` 为空表示未识别出选项，
        此时 ``stem`` 原样返回 ``body``（仅做空白规整）。
    """
    if not body:
        return "", []

    matches = list(_OPTION_LABEL_RE.finditer("\n" + body))
    if not matches:
        return re.sub(r"\s+", " ", body).strip(), []

    # 只认从 A 开始的连续序列 A, B, C(, D, ...)
    letters = [m.group(1) for m in matches]
    start = None
    for idx, letter in enumerate(letters):
        if letter == "A":
            start = idx
            break
    if start is None:
        return re.sub(r"\s+", " ", body).strip(), []

    run: list[tuple[int, re.Match[str]]] = []
    expect = 0
    for m in matches[start:]:
        letter = m.group(1)
        if letter == chr(ord("A") + expect):
            run.append((expect, m))
            expect += 1
            if expect > 5:  # A~F 封顶
                break
        else:
            break

    if len(run) < min_count:
        return re.sub(r"\s+", " ", body).strip(), []

    # 反误杀：连续序列之后若还残留别的选项标签（如「A.x B.y X.无关」），
    # 说明这串标签不是规范选项列表而是正文里的列表项，不予拆分。
    tail_start = run[-1][1].end()
    if _OPTION_LABEL_RE.search("\n" + body[tail_start:]):
        return re.sub(r"\s+", " ", body).strip(), []

    # ``matches`` 的偏移是相对 "\n"+body 的；用 start(1) 定位标签字母本身，
    # 这样前缀标点（如「（」）仍归属题干，不会被切进第一个选项。
    # 用 start()（前缀起点）而非 start(1)，这样「（）」这类闭合标点仍归属题干
    stem = ("\n" + body)[1: run[0][1].start(1)].strip()
    options: list[str] = []
    for pos, (_rank, m) in enumerate(run):
        # matches 偏移相对 "\n"+body，切片目标是 body，故需减去前缀长度 1
        ostart = m.start(1) - 1
        oend = (run[pos + 1][1].start(1) - 1) if pos + 1 < len(run) else len(body)
        # 保留「A.」标签本体，与既有 _OPTION_RE 的行为一致
        text = body[ostart:oend].strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            options.append(text)

    stem = re.sub(r"\s+", " ", stem).strip()
    return stem, options


# --------------------------------------------------------------------------- #
# 3. 跨题串接检测
# --------------------------------------------------------------------------- #

#: 题干尾部出现的题型大标题 —— 说明本切块吃掉了下一个大题区的标题。
_CROSS_QUESTION_TAIL_RE = re.compile(
    r"[一二三四五六七八九十]+\s*[、.．]\s*"
    r"(?:选择题|填空题|判断题|简答题|计算题|分析题|设计题|证明题|作图题|画图题|论述题|综合题|"
    r"分析计算题|分析设计题|选择|填空|判断|简答|计算|分析|设计|证明|作图|画图|论述|综合|"
    r"大题|计算题|应用题)"
    r"\s*(?:[（(][^）)]{0,60}[）)])?"
)


def find_cross_question_leak(text: str | None) -> re.Match[str] | None:
    """在 ``text`` 中查找跨题串接的题型大标题；找到返回 match，否则 ``None``。

    防误杀要点（这是本项目吃过亏的地方，必须写死）：只在**题干尾部**查找，
    且要求大标题**位于最后一行**。题干中间出现「下列说法正确的是（　）
    A、…… B、…… C、…… D、……」这类正常内容不会被判为串接。

    Args:
        text: 待检测题干。

    Returns:
        命中时的 ``re.Match``（``None`` 表示未命中）。
    """
    if not text:
        return None
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return None
    return _CROSS_QUESTION_TAIL_RE.search(lines[-1])


def strip_cross_question_leak(text: str | None) -> tuple[str, bool]:
    """剔除题干尾部被串接进来的题型大标题。

    Args:
        text: 待清洗题干。

    Returns:
        ``(cleaned, leaked)``。``leaked`` 为 True 表示检出并剔除了串接。
    """
    if not text:
        return "", False
    m = find_cross_question_leak(text)
    if not m:
        return text.strip(), False
    # m.start() 是相对「最后一行」的偏移，必须换算回整段文本的绝对位置，
    # 否则多行题干会被从行首错误截断（实测会把整道题截成空串）。
    lines_all = text.strip().splitlines()
    tail = lines_all[-1]
    abs_start = len(tail) - len(m.group(0))
    # abs_start 之前有多少完整行，就把它们的字符数累加上去
    prefix_chars = 0
    for ln in lines_all[:-1]:
        prefix_chars += len(ln) + 1
    cut = prefix_chars + abs_start
    cleaned = text.strip()[:cut].strip()
    cleaned = re.sub(r"[\s，,、；;。.]+$", "", cleaned).strip()
    return cleaned, True