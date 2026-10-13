# -*- coding: utf-8 -*-
"""英语考研真题专用切题器（english_question_extractor）。

### 为什么需要独立一个模块
``services/qbank_builder.extract_questions`` 是为电子类（选择题 / 计算题 /
填空题）设计的裸编号切分：见到 ``1.`` / ``2、`` 就切一刀。它对英语是**灾难性
不适用**的：

* 英语卷的编号是 ``21.`` ~ ``52.`` 连续跨节的，且完形 20 个空嵌在**一整篇
  文章内部**（``... others, 1 ,some of us...``），裸切会把文章切成 20 段碎片；
* 英语卷有 5 种结构完全不同的题型（完形 / 阅读 A / 新题型 / 翻译 / 写作），
  每种的存储形态都不一样；
* 英语题干是英文，`quiz_content_gate.admit` 的 Q_MARK 词表全是中文特征词，
  对英文题干几乎全部失效，需要英语专用判定。

因此本模块**不复用也不修改** qbank_builder（那条路径在服务数模电切题）。

### 五类题型的存储设计（决策 + 理由）
======================  ======================================================
题型                    存储形态
======================  ======================================================
完形 Use of English    切成 **20 道独立题**。每道题``content`` =
                        "（第 N 空）" + **完整原文文章**（保留其余空的编号
                        与空格原样）。``options`` = A/B/C/D 四选项。
                        **理由**：答对错必须能逐空判定，而 ``quiz_questions``
                        一行只有一个 ``answer`` 字段；若只存 1 道题，20 个
                        答案无处安放，用户也无法逐空刷。代价是文章重复 20
                        次（每卷约 +60KB），换来的是可刷性 —— 这是正确的
                        取舍。
阅读 A Reading A4篇×5 题 20 道选择题。``content`` = **文章全文 + 题干**
                        （考研英语阅读的题必须带文章，脱离文章不可答）。
                        ``options`` = A/B/C/D。
新题型 Part B        5 道。英二为"七选五"（A-G 七个长句选项），英一为
                        "排序"。``content`` = 完整文章 + "第 N 空" 标记，
                        ``options`` = 该题型实际给出的选项列表（英二 A-G /
                        英一 排序题不给独立选项时留空列表）。
翻译                英一 = 5 道（46-50 划线部分），每道带完整段落上下文；
                        英二 = 1 道（整段英译汉）。
写作                小作文 1 道 + 大作文 1 道。``answer`` 一律留空
                        （作文没有唯一答案），有范文时才填入 ``analysis``。
======================  ======================================================

### 答案策略（底线）
答案**只**来自同一 (year, paper) 的解析文档中的显式答案区
（``【答案】``/ ``【参考答案】``/ ``1.B 2.C`` 形式）。取不到就是 ``None``。
**任何情况下都不从上下文"推断"答案** —— 错答案比没答案危害大得多。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# 一、噪声清洗
# --------------------------------------------------------------------------- #

#: PDF 页眉页脚 / 公众号水印 / OCR 分页标记
_NOISE_LINE_PATTERNS: Tuple[re.Pattern, ...] = tuple(re.compile(p) for p in (
    r"^-+\s*第?\s*\d+\s*页?\s*\(?OCR\)?\s*-+$",
    r"^公众号[：:]",
    r"研池大叔",
    r"免费分享考研",
    r"^\s*英语[（(]?[一二]\s*[)）]?\s*试题\s*[.．]?\s*\d+\s*[（(]共\s*\d+\s*页[)）]",
    r"^关注公众号",
    r"^\s*红宝书\s*[·・]?\s*考研英语\s*$",
    r"^\s*绝密[★☆☆]?\s*启用前?\s*$",
    r"^\s*更多考研资料\s*$",
    r"^\s*【?考研真题】?\s*$",
))

#: PDF 抽取产生的乱码水印行（如 ``QlOS÷ÿxl`Y'SÔ QM9RN«xþzÿNf|M``）。
#: 判定条件刻意收紧：必须含 U+FFFD 或 Latin-1 符号区字符，且**不含任何
#: 连续 3 个字母的英文词** —— 否则正常英文正文会被误删。
_MOJIBAKE_CHARS = re.compile(r"[\ufffd\u00ff\u0160\u0161\u017d\u017e\u0178\u0152\u0153\u0178\u00c0-\u00ff]")
#: 连续 3 个字母的英文词。
#: 用小写而非任意字母：``QlOS``水印里的 ``QlO`` 是乱码产物，若按任意字母
#: 判定会把整条水印误判为正文。
_ENGLISH_WORD = re.compile(r"[a-z]{3}")


def is_garbled_line(line: str) -> bool:
    """判断一行是否是 PDF 抽取产生的乱码水印（而非正文）。

    判定：含 mojibake 字符（U+FFFD / Latin-1 符号区），且**不含长度 >=4 的
    小写英文单词**。用 4 而不是 3，是因为水印串 ``QlOS÷ÿxl`Y'SÔ QM9RN«...``
    里恰好含"QlO"这种 3 字母片段。
    """
    if not _MOJIBAKE_CHARS.search(line):
        return False
    if _ENGLISH_WORD.search(line) is not None:
        return False
    # 追加安全阀：乱码字符至少 3 个才算水印行，避免把含个别特殊符号的正常
    # 英文行（如 ``C÷2``、``[A]``）误删。
    return len(_MOJIBAKE_CHARS.findall(line)) >= 3


#: 试卷页码残留（OCR 把页码混进正文，如 ``...hold back the sorts of projects.5.``）
_PAGE_NUM_ONLY = re.compile(r"^\s*\d{1,2}\s*$")

#: 零宽/控制字符（部分 PDF 抽取带 NUL，会让 SQLite 的 length() 在此处截断）
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f﻿]")

#: 行内被OCR 拆出的多余空格：``1 ,some`` / ``2 i\nt.`` 拼接时的安全处理
_INLINE_SPACE = re.compile(r"[ \t]{2,}")

#: U+FFFD 出现率超过此值 -> 整份文档判为乱码，不切题
MAX_DOC_FFFD_RATE = 0.002
#: 单个文档允许的 U+FFFD 绝对数量（PDF 抽取偶尔丢一两个字形，属正常）
MAX_DOC_FFFD_ABS = 8


def doc_mojibake_rate(raw: Optional[str]) -> Tuple[float, int]:
    """返回 ``(U+FFFD 占比, U+FFFD 个数)``，用于整卷级乱码判定。

    个别 U+FFFD 是可容忍的（PDF 抽取丢了 ``d``/``e`` 这一个字形，
    如 ``New Englan<?>``）；但成片的 U+FFFD 意味着整份文档不可用。
    """
    if not raw:
        return 1.0, 0
    n = raw.count("\ufffd")
    return n / max(len(raw), 1), n


def is_doc_too_mojibake(raw: Optional[str]) -> bool:
    """整卷乱码判定：占比或绝对数量超阈值就整份弃用。"""
    rate, n = doc_mojibake_rate(raw)
    return rate > MAX_DOC_FFFD_RATE or n > MAX_DOC_FFFD_ABS


def clean_content(raw: Optional[str], *, drop_fffd: bool = True) -> str:
    """清洗文档正文：去控制字符、去页眉水印行、规整空白、剔除 U+FFFD。

    ``drop_fffd=True``（默认）会把 U+FFFD 直接删掉：它是"此处原本有一个
    字形但抽取失败"的占位符，留在题干里只会污染显示，删掉后句子仍可读。
    若某个字形是关键内容（极少数），宁可少一个字也不能让整题显示成乱码。

    注意：**不做** OCR 字符纠错（如 ``Al`` -> ``AI``、``karv:an`` -> ``karvan``），
    那是另一类问题，且任何自动纠正都可能改错正文内容。脏文本由下游质量检查
    拦截，而不是靠"猜着改"。
    """
    if not raw:
        return ""
    text = _CTRL.sub("", raw)
    if drop_fffd:
        text = text.replace("\ufffd", "")
    out_lines: List[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = line.strip()
        if not s:
            out_lines.append("")
            continue
        if any(p.search(s) for p in _NOISE_LINE_PATTERNS) or is_garbled_line(s):
            continue
        out_lines.append(s)
    text = "\n".join(out_lines)
    # OCR 常把完形题号与选项组拆成两行（实测2020 英语一 doc=2126：
    # ``1`` 换行 ``. [A] In [B] Towards ...``）。这里把 ``N`` + ``. [A] x``
    # 重新粘成一行，让后续按行解析的逻辑统一。
    text = re.sub(r"(?m)^(\s{0,4}\d{1,2})\s*\n\s*([.、．]\s*\[\s*[A-G]\s*\])", r"\1 \2", text)
    text = _INLINE_SPACE.sub(" ", text)
    # 修复被换行/ OCR 打断的小节标题（实测 2020 英语一 doc=2126 的
    # ``Se\nction Ⅰ Use of English``、2023 英语一 doc=2503 的 ``Se1:tion I``）。
    # 只针对 "Section" 这一个确定词，不做通用 OCR 纠错。
    text = re.sub(r"\bSe[0-9:：'’\s]*?(?:ction|tion|ction)\b", "Section", text)
    # OCR 把选项右方括号``]`` 认成字母 ``J``：``[B] promote`` -> ``[BJ promote``。
    # 只在**行首的选项位置**修复（``[BJ``/``[CJ``/``[DJ``），不影响正文里的 ``[J``。
    text = re.sub(r"(?m)^(\s*)\[([A-G])J(?=\s)", r"\1[\2] ", text)
    # 折叠 3 个以上连续空行为1 个空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def page_boilerplate_ratio(raw: Optional[str]) -> float:
    """页眉/水印行占比，用于判定文档是否被垃圾内容淹没。"""
    if not raw:
        return 1.0
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    if not lines:
        return 1.0
    noise = sum(1 for ln in lines if any(p.search(ln) for p in _NOISE_LINE_PATTERNS))
    return noise / len(lines)


# --------------------------------------------------------------------------- #
# 二、卷种 / 年份 / 小标题识别
# --------------------------------------------------------------------------- #

_ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧ"          # 常见 Unicode 罗马数字
_ROMAN_MAP = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V"}

#: ``Section I`` / ``Section Ⅰ`` / ``Section IUse of English``（OCR 会吞空格）。
#: **必须**带罗马数字或紧跟英文小节名之一；否则正文里 "Section 5 of the FTC Act"
#: 这类引用会被误当成小节边界（实测导致阅读 Text 4 的题目被腰斩成 0 题）。
_SECTION_RE = re.compile(
    r"Section\s*(?=(?:[" + _ROMAN + r"]|[IVX]{1,4})(?![A-Za-z]))(?:[" + _ROMAN + r"]|[IVX]{1,4})"
    r"(?:\s*(?=(?:Use|Reading|Translation|Writing)\b)"
    r"(?P<name>Use\s*of\s*English|Reading\s*[Cc]omprehens\w*|Translation|Writing))?",
    re.IGNORECASE,
)

_PART_RE = re.compile(r"^\s*Part\s*([ABC])\b", re.IGNORECASE | re.MULTILINE)

#: **带英文小节名**的 Section 标题 —— 小节名是强信号，可以容忍罗马数字被OCR
#: 认错（实测 ``Section Il Reading Comprehension``（Il=l）、``Section m Writing``
#: （m=lll）、``Section Ⅲ Writing``）。正文里的 "Section 5 of the FTC Act"
#: 不带英文小节名，所以不会被误判。
_SECTION_NAMED_RE = re.compile(
    r"Section\s*[\S]{0,4}?\s*"
    r"(?P<name>Use\s*of\s*English|Reading\s*[Cc]omprehens\w*|Translat\w*|Writ\w*)"
    r"[^\n]{0,24}",
    re.IGNORECASE,
)

#: OCR 把罗马数字认错的常见形态 -> 正确罗马数字
_ROMAN_OCR_FIX = {
    "l": "I", "ll": "II", "lll": "III", "lV": "IV", "iV": "IV", "i": "I",
    "ii": "II", "iii": "III", "iv": "IV", "v": "V", "Ill": "III", "Il": "II",
}


def _normalize_roman(token: str) -> str:
    """把 OCR 认错的罗马数字 token 归一化（``Il`` -> ``II``）。"""
    t = token.strip()
    for uni, asc in _ROMAN_MAP.items():
        t = t.replace(uni, asc)
    t = re.sub(r"[^A-Za-z]", "", t)
    if not t:
        return ""
    if t in _ROMAN_OCR_FIX:
        return _ROMAN_OCR_FIX[t]
    if re.fullmatch(r"[IVX]{1,4}", t):
        return t.upper()
    return ""


@dataclass
class PaperMeta:
    """一份真题文档的元信息。"""

    year: Optional[int] = None
    #: ``"英语一"`` / ``"英语二"`` / ``None``（判断不了就None，绝不瞎猜）
    paper: Optional[str] = None
    has_answer_block: bool = False
    sections: List[str] = field(default_factory=list)


_YEAR_RE = re.compile(r"(19[89]\d|20[0-2]\d)\s*年?")


def detect_year(text: str, file_name: str = "") -> Optional[int]:
    """从文件名优先、正文兜底识别年份。"""
    for src in (file_name, text[:400]):
        m = _YEAR_RE.search(src or "")
        if m:
            return int(m.group(1))
    return None


def detect_paper(text: str, file_name: str = "") -> Optional[str]:
    """识别英语一 / 英语二。

    判定不了返回 ``None``（入库写NULL），**不允许**用"默认英语一"兜底。

    依据优先级：
      1. 文件名中的"英语一/英语二/英语（一）/英语（二）"；
      2. 正文中的"英语（一）（科目代码：201）" / "（二）...204）"；
      3. 科目代码 201 -> 英语一，204 -> 英语二。
    """
    for src in (file_name, text[:600]):
        if not src:
            continue
        s = src.replace(" ", "")
        if re.search(r"英语[（(]?[一1][)）]", s) or "英语一" in s:
            return "英语一"
        if re.search(r"英语[（(]?[二2][)）]", s) or "英语二" in s:
            return "英语二"
        if "201" in s and re.search(r"科目代码[：:]?\s*201", s):
            return "英语一"
        if "204" in s and re.search(r"科目代码[：:]?\s*204", s):
            return "英语二"
    return None


def split_sections(text: str) -> List[Tuple[str, str]]:
    """按 Section 标题切块，返回 ``[(标题归一化, 正文), ...]``。

    归一化标题取 ``"Section I Use of English"`` 这种稳定形式，便于下游匹配。
    无法识别的小节标题统一为 ``"Section ?"``。
    """
    marks: List[Tuple[int, str]] = []
    for m in _SECTION_RE.finditer(text):
        # 归一化罗马数字
        norm = re.sub(r"\s+", " ", m.group(0)).strip()
        for uni, asc in _ROMAN_MAP.items():
            norm = norm.replace(uni, asc)
        name = re.sub(r"\s+", " ", (m.group("name") or "").strip())
        low = name.lower()
        if "use" in low and "english" in low:
            kind = "Use of English"
        elif "reading" in low or "comprehens" in low:
            kind = "Reading Comprehension"
        elif "translat" in low:
            kind = "Translation"
        elif "writ" in low:
            kind = "Writing"
        else:
            kind = "?"
        num = ""
        r = re.search(r"Section\s*(?:[" + _ROMAN + r"]|[IVX]{1,4})", norm, re.IGNORECASE)
        if r:
            num = _normalize_roman(r.group(0)[len("Section"):])
        marks.append((m.start(), f"Section {num} {kind}".strip()))

    # 补充：只带英文小节名、罗马数字被 OCR 认错的标题
    covered = {pos for pos, _ in marks}
    for m2 in _SECTION_NAMED_RE.finditer(text):
        if any(abs(m2.start() - p) <= 2 for p in covered):
            continue
        head = m2.group(0)
        name = re.sub(r"\s+", " ", m2.group("name").strip())
        low = name.lower()
        if "use" in low:
            kind = "Use of English"
        elif "reading" in low or "comprehens" in low:
            kind = "Reading Comprehension"
        elif "translat" in low:
            kind = "Translation"
        else:
            kind = "Writing"
        tok = re.match(r"Section\s*(\S{0,4}?)\s*$|Section\s*(\S{0,4}?)\s+" + re.escape(name[:6]),
                       head, re.IGNORECASE)
        num = ""
        if tok:
            num = _normalize_roman(tok.group(1) or tok.group(2) or "")
        marks.append((m2.start(), f"Section {num} {kind}".strip()))

    marks.sort(key=lambda x: x[0])

    if not marks:
        return []
    out: List[Tuple[str, str]] = []
    for idx, (pos, title) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(text)
        out.append((title, text[pos:end]))
    return out


# --------------------------------------------------------------------------- #
# 三、题目数据结构
# --------------------------------------------------------------------------- #

#: question_type 枚举
QT_CLOZE = "完形填空"
QT_READING = "阅读理解"
QT_NEW_TYPE = "新题型"
QT_TRANSLATION = "翻译"
QT_WRITING = "写作"


@dataclass
class EnglishQuestion:
    """一条待入库的英语题。"""

    content: str
    options: List[str] = field(default_factory=list)
    answer: Optional[str] = None
    analysis: Optional[str] = None
    section_type: str = ""
    question_type: str = ""
    year: Optional[int] = None
    paper: Optional[str] = None
    question_no: Optional[int] = None
    source_paper: str = ""
    source_doc_id: Optional[int] = None
    external_id: str = ""
    answer_type: str = "objective"
    confidence: str = "medium"
    chapter: str = ""

    def to_row(self, *, extra_source: str = "") -> Dict[str, Any]:
        """转成 ``quiz_questions`` 的插入字典。"""
        return {
            "content": self.content,
            "options": json.dumps(self.options, ensure_ascii=False),
            "answer": self.answer if (self.answer or "").strip() else None,
            "analysis": self.analysis,
            "subject": "英语",
            "chapter": self.chapter or (self.question_type or ""),
            "knowledge_point": self.question_type or None,
            "difficulty": None,
            "source": extra_source or self.source_paper,
            "question_type": self.question_type,
            "year": self.year,
            "paper": self.paper,
            "external_id": self.external_id,
            "source_paper": self.source_paper,
            "question_no": self.question_no,
            "answer_type": self.answer_type,
            "confidence": self.confidence,
            "is_available": 1,
            "ai_generated": 0,
            "verified": 0,
        }


# --------------------------------------------------------------------------- #
# 四、答案区解析（只认显式答案，绝不推断）
# --------------------------------------------------------------------------- #

#: ``【答案】`` / ``【参考答案】`` / ``【答案与解析】``
_ANS_BLOCK_RE = re.compile(r"【\s*(?:参考)?答案[^】]{0,8}】\s*")
#: ``1-5：CBADA`` / ``1-5: CBADA``
_ANS_RANGE_RE = re.compile(r"(\d{1,2})\s*[-—~至]\s*(\d{1,2})\s*[：:]\s*([A-Ga-g]{1,10})")
#: ``1.B 2.C 3.A`` / ``1．B``
_ANS_PAIR_RE = re.compile(r"(\d{1,2})\s*[.、．,，]?\s*([A-Ga-g])(?![A-Za-z])")
#: 独立字母串（Part B 新题型答案，通常紧跟答案标记）
_ANS_BARE_RE = re.compile(r"^[A-G](?:\s*[A-G]){1,9}$")
#: ``答案速查`` / ``答案速查表`` / ``参考答案速查`` —— 试卷尾部整卷答案表，
#: 里面是 ``1.D 2.C 3. B 4.A ...`` 的逐题编号+字母形式（实测 2024 英语一 doc=3359）。
_ANS_TABLE_HEAD_RE = re.compile(r"【?\s*(?:参考)?答案\s*速\s*查\s*(?:表)?\s*】?")
#: 答案表终止：出现``Section`` / ``Part`` / 中文段落标题即结束
_ANS_TABLE_STOP_RE = re.compile(r"^\s*(?:Section|Part\s*[AB]|PartC|写作|翻译)", re.IGNORECASE)


def _parse_answer_table(text: str) -> Dict[int, str]:
    """解析试卷尾部的 ``答案速查`` 整卷答案表。

    表格形如::

        答案速查
        Section I Use of English
        1.D 2.C 3. B 4.A 5.B
        ...
        Section Ⅱ Reading Comprehension
        Part A
        21. D 22.D 23.A ...
        Part B
        41.E 42.C ...

    只取 ``数字+字母`` 的配对；``Part C`` 之后是汉译英参考译文（不是 A-D 字母），
    自然不会被误采信。

    Args:
        text: 试卷全文（已清洗）。

    Returns:
        ``{题号: 答案字母}``。
    """
    out: Dict[int, str] = {}
    for hm in _ANS_TABLE_HEAD_RE.finditer(text):
        tail = text[hm.end():]
        lines = tail.split("\n")
        for ln in lines[:120]:
            #终止信号：出现书信/范文正文（如 ``Dear Paul,``）或中文章落
            if re.match(r"^\s*(?:Dear|Sincerely|The drawing|I have just)", ln):
                break
            for pm in _ANS_PAIR_RE.finditer(ln):
                no, ch = int(pm.group(1)), pm.group(2).upper()
                if 1 <= no <= 55:
                    out.setdefault(no, ch)
    return out
#: 逐题内联答案：``41.【答案】A`` / ``12. 【答案】B 【精解】`` / ``41．[答案]D``
#: /``1.【答案】[A] Still``（答案文档常用「字母+原文」形式，实测 2026 英语一 doc=1643）
_INLINE_ANS_RE = re.compile(
    r"(\d{1,2})\s*[.、．]?\s*[【\[]\s*(?:参考)?答案[^】\]]{0,6}[】\]]"
    r"\s*[:：]?\s*[\[［]?\s*([A-G])(?![A-Za-z])"
)


def _expand(lo: int, hi: int, letters: str) -> Dict[int, str]:
    """把 ``1-5：CBADA`` 展开成 ``{1:'C', 2:'B', ...}``。"""
    out: Dict[int, str] = {}
    letters = letters.strip()
    for i, ch in enumerate(letters):
        n = lo + i
        if n > hi:
            break
        out[n] = ch.upper()
    return out


#: 解析文档里出现过的题号（按出现顺序），用于给「裸字母串」定位题号
_ANS_QNO_SCAN_RE = re.compile(r"^\s{0,6}(\d{1,2})\s*[.、．]\s*\S", re.MULTILINE)


def _map_bare_group_by_preceding_qnos(
    text: str, groups_with_pos: List[Tuple[int, str]]
) -> Dict[int, str]:
    """把 ``【参考答案】CCDAD`` 这类裸字母串映射到具体题号。

    解析文档的排版规律是：**先完整重复 5 道题的题干与选项，紧接着给出这5 题的
    答案字母串**。因此对每个字母串，取它之前出现过的最后 ``len(letters)`` 个
    题号，按顺序一一对应。

    安全阀（宁可不填也不填错）：

    * 题号必须严格递增且连续（``21,22,23,24,25``），否则拒绝；
    * 题号必须落在 1..55 的合法题目区间；
    * 若字母串出现在文档开头（前面没有任何题号），拒绝。

    Args:
        text: 解析文档全文。
        groups_with_pos: ``(字母串起始位置, 字母串)`` 列表。

    Returns:
        ``{题号: 答案字母}``；无法可靠映射时返回空 dict。
    """
    out: Dict[int, str] = {}
    qnos = [(m.start(), int(m.group(1))) for m in _ANS_QNO_SCAN_RE.finditer(text)]
    if not qnos:
        return out
    pos_list = [p for p, _ in qnos]
    no_list = [n for _, n in qnos]

    for gpos, letters in groups_with_pos:
        prev_idx = [i for i, p in enumerate(pos_list) if p < gpos]
        n_need = len(letters)
        if len(prev_idx) < n_need:
            continue
        window = no_list[prev_idx[-n_need]:prev_idx[-1] + 1]
        if any(b - a != 1 for a, b in zip(window, window[1:])):
            continue
        if not (1 <= window[0] and window[-1] <= 55):
            continue
        if any(n < 1 or n > 55 for n in window):
            continue
        out.update(_expand(window[0], window[-1], letters))
    return out


def parse_answer_sections(text: str) -> Tuple[Dict[int, str], Dict[str, List[str]]]:
    """从解析文档里抽取答案。

    返回 ``(题号->答案字母, 分组答案原文列表)``。分组原文用于新题型
    （其答案是字母串但需要保留原始出处）。

    **只解析显式答案标记后的内容**；任何没有标记的字母串一律不采信。
    """
    by_no: Dict[int, str] = {}
    groups: List[str] = []
    bare_with_pos: List[Tuple[int, str]] = []
    if not text:
        return by_no, groups

    # —— 形态 1（最主要的解析格式）：``41.【答案】A 【精解】...`` 逐题内联 ——
    # 实测 2019 英语二 doc=3296 就是这种，题号紧贴答案标记，可靠性最高。
    for im in _INLINE_ANS_RE.finditer(text):
        no = int(im.group(1))
        if 1 <= no <= 60:
            by_no[no] = im.group(2).upper()

    for m in _ANS_BLOCK_RE.finditer(text):
        tail = text[m.end():]
        #答案区到下一个 Section / 【标记】 为止
        cut = len(tail)
        for stop in ("【", "Section"):
            p = tail.find(stop, 5)
            if p != -1:
                cut = min(cut, p)
        seg = tail[:cut]
        seg_lines = [ln.strip() for ln in seg.split("\n")[:4]]
        got = False
        for ln in seg_lines:
            for rm in _ANS_RANGE_RE.finditer(ln):
                lo, hi, letters = int(rm.group(1)), int(rm.group(2)), rm.group(3)
                if 1 <= lo <= hi <= 60 and hi - lo + 1 >= len(letters):
                    by_no.update(_expand(lo, hi, letters))
                    got = True
            for pm in _ANS_PAIR_RE.finditer(ln):
                n, ch = int(pm.group(1)), pm.group(2).upper()
                if 1 <= n <= 60:
                    by_no[n] = ch
                    got = True
        if not got:
            joined = " ".join(seg_lines)
            bm = re.search(r"\b([A-G](?:\s*[A-G]){1,9})\b", joined)
            if bm:
                letters = re.sub(r"\s+", "", bm.group(1))
                groups.append(letters)
                bare_with_pos.append((m.start(), letters))

    # —— 形态 3（阅读 A 的答案区）：``【参考答案】CCDAD`` 紧跟在某篇 Text 的 5 题之后——
    # 字母串本身不带题号，用「前文最近 5 个题号」定位，安全阀见
    # :func:`_map_bare_group_by_preceding_qnos`。
    if bare_with_pos:
        for k, v in _map_bare_group_by_preceding_qnos(text, bare_with_pos).items():
            by_no.setdefault(k, v)

    # —— 形态 4：试卷尾部``答案速查`` 整卷答案表（自带答案的试卷）——
    for k, v in _parse_answer_table(text).items():
        by_no.setdefault(k, v)
    return by_no, groups


def group_letters_to_map(group: str, lo: int) -> Dict[int, str]:
    """把 ``CCDAD`` / ``GBEACD`` 这样的字母串映射到起始题号。"""
    return {lo + i: ch for i, ch in enumerate(group) if ch.isalpha()}


# --------------------------------------------------------------------------- #
# 五、题号 / 选项 / 题干切分
# --------------------------------------------------------------------------- #

#: 行首题号：``21.`` ``21.`` ``36.``；允许 OCR 把 ``22.According`` 粘连
_QNO_LINE_RE = re.compile(r"^\s{0,6}(\d{1,2})\s*[.、．]\s*(.*)$")
#: 行内题号（同一行前面有正文，题号被吸进来）——仅在明确以题号+大写开头的行使用
_OPT_RE = re.compile(r"^\s*\[\s*([A-G])\s*\]\s*(.+)$")
#: 完形选项组起始行：``1. [A] because`` 或 ``5. [A] contribute to [B] rely on``
_QNO_OPT_START_RE = re.compile(r"^\s*(\d{1,2})\s*[.、．]\s*(\[\s*[A-G]\s*\])")
#: 无方括号的选项：``A. xxx``
_OPT_DOT_RE = re.compile(r"^\s*([A-G])\s*[.、．]\s+(.+)$")


def _split_inline_bracket_options(line: str) -> List[str]:
    """把一行里挤在一起的 ``[A] x [B] y [C] z`` 拆成 ``["[A] x", ...]``。

    （2020 英语一 doc=2126 就是一行四个选项；这里只做切分，不做内容纠错。）
    行首的题号片段（``"1."``）会被丢掉 —— 它已经在题号分支里消费过了，
    留着会挤掉真正的第 4 个选项。
    """
    parts = [p.strip() for p in re.split(r"(?=\[\s*[A-G]\s*\])", line) if p.strip()]
    return [p for p in parts if _OPT_RE.match(p)]


def _keep_unique_letters(opts: Sequence[str]) -> List[str]:
    """保序去重选项字母（同一个字母出现两次时保留第一次）。

    双栏/粘连排版常导致 ``[A] x[A] y`` 这类重复，重复字母会让刷题界面
    出现两个" A"，必须去掉。
    """
    seen = set()
    out: List[str] = []
    for o in opts:
        letter = o.split(".", 1)[0].strip().upper()
        if not letter or letter in seen:
            continue
        seen.add(letter)
        out.append(o)
    return out


def parse_option_block(lines: Sequence[str]) -> List[str]:
    """把若干行解析成 ``["A. xxx", "B. xxx", ...]``（保序、去空）。"""
    opts: List[str] = []
    for ln in lines:
        m = _OPT_RE.match(ln) or _OPT_DOT_RE.match(ln)
        if m:
            opts.append(f"{m.group(1)}. {m.group(2).strip()}")
    return opts


def split_numbered(text: str, *, lo: int, hi: int) -> List[Tuple[int, List[str]]]:
    """把一段文本按 ``^N.`` 行首切分为 ``[(题号, 行列表), ...]``。

    题号不在 ``[lo, hi]`` 的行不切（避免把选项里的 ``1.`` 误当题号），
    这样即使一份文档里混进多个 Section 也不会串号。
    """
    blocks: List[Tuple[int, List[str]]] = []
    cur_no: Optional[int] = None
    cur: List[str] = []
    for ln in text.split("\n"):
        m = _QNO_LINE_RE.match(ln)
        no = int(m.group(1)) if m else None
        if no is not None and lo <= no <= hi:
            if cur_no is not None:
                blocks.append((cur_no, cur))
            cur_no = no
            rest = m.group(2).strip()
            cur = [rest] if rest else []
        else:
            if cur_no is not None:
                cur.append(ln)
    if cur_no is not None:
        blocks.append((cur_no, cur))
    return blocks


def _dedup_blocks(blocks: Sequence[Tuple[int, List[str]]]) -> List[Tuple[int, List[str]]]:
    """去掉重复题号的块（保留第一个）——同一页 OCR 常把题重复一遍。"""
    seen = set()
    out = []
    for no, lines in blocks:
        if no in seen:
            continue
        seen.add(no)
        out.append((no, lines))
    return out


def trim_trailing_noize(lines: List[str]) -> List[str]:
    """砍掉块尾部的页码 / 水印 / **下一个小节起始**残留行。

    最后一条尤其重要：阅读 Text 4 第 5 题的块会一直延伸到 ``Part B`` 的
    ``A. ...`` / ``B. ...`` 长选项，于是把新题型的选项当成阅读题的第 5、6 个
    选项（实测 2024 英语二第 40 题就是这样多出 A/F 两个"选项"）。
    """
    out = list(lines)
    for i, ln in enumerate(out):
        if re.match(r"^\s*Part\s*[ABC]\b", ln) or re.match(r"^\s*\d{1,2}\s*[.、．]\s*Directions",
                                                          ln):
            out = out[:i]
            break
    while out and (not out[-1].strip() or _PAGE_NUM_ONLY.match(out[-1])
                   or any(p.search(out[-1]) for p in _NOISE_LINE_PATTERNS)):
        out.pop()
    while out and not out[-1].strip():
        out.pop()
    return out


def block_to_question(no: int, lines: List[str]) -> Tuple[str, List[str]]:
    """把一个题号块拆成 ``(题干, 选项列表)``。"""
    lines = trim_trailing_noize(lines)
    opt_start = None
    for i, ln in enumerate(lines):
        if _OPT_RE.match(ln) or _OPT_DOT_RE.match(ln):
            opt_start = i
            break
    if opt_start is None:
        return "\n".join(lines).strip(), []
    stem = "\n".join(lines[:opt_start]).strip()
    opts = parse_option_block(lines[opt_start:])
    return stem, opts


# --------------------------------------------------------------------------- #
# 六、各题型解析
# --------------------------------------------------------------------------- #

#: 完形 20 空在正文里的形态：``1 ,``/ ``1,`` / ``_1_`` / ``(1)``
_CLOZE_BLANK = re.compile(r"(?<![\w])(\d{1,2})\s*(?=[,.\s])")


def _cloze_article(text: str) -> Tuple[str, List[int]]:
    """提取完形文章正文 + 出现的空号列表。

    完形的正文是一整篇带编号的文章，编号后紧跟标点或空格（``others, 1 ,some``）。
    这里从 Directions 之后开始取，到正文里出现第 2 个连续题号块（阅读题）为止。
    """
    # 定位 Directions 之后的正文起点
    m = re.search(r"Directions\s*:?[\s\S]{0,400}?ANSWER\s*SHEET[^\n]*", text, re.IGNORECASE)
    body = text[m.end():] if m else text
    # 结束于「连续出现>=4 个题号行」（说明进入阅读部分）
    lines = body.split("\n")
    keep: List[str] = []
    consecutive = 0
    for ln in lines:
        qm = _QNO_LINE_RE.match(ln)
        if qm and 21 <= int(qm.group(1)) <= 45:
            consecutive += 1
            if consecutive >= 4:
                break
        else:
            consecutive = 0
        # 进入选项区/ 答案区即截断：文章正文到第一个 ``1. [A] xxxx`` 为止。
        # 否则每道完形题的 content 会把 20 组选项 + 答案表全带进去
        # （实测 2024 英语二 doc=73 自带 ``【答案】1-5：CBADA``）。
        if _QNO_OPT_START_RE.match(ln) or _ANS_BLOCK_RE.match(ln):
            if sum(len(x) for x in keep) >= 200:
                break
        keep.append(ln)
    body = "\n".join(keep).strip()
    numbers = sorted({int(n) for n in re.findall(r"(?<![\w])(\d{1,2})(?=\s*[,.]?\s)", body)
                      if 1 <= int(n) <= 20})
    return body, numbers


def parse_cloze(text: str, answers: Dict[int, str], meta: PaperMeta,
                full_text: Optional[str] = None) -> List[EnglishQuestion]:
    """完形：切成 20 道，每道带完整文章。

    ``full_text`` 是整卷原文。选项区可能落在 Section I 之外（双栏排版时PDF
    抽取器会把选项栏放到"阅读"那一段里），所以选项查找以整卷为准。
    """
    article, numbers = _cloze_article(text)
    opt_src = full_text or text
    if not article:
        return []
    if len(numbers) < 5:
        # 退化：很多年份把空号写成 ``1`` 独占一行，用 ``\\n\\d{1,2}\\n`` 兜底
        numbers = sorted({int(n) for n in re.findall(r"^\s*(\d{1,2})\s*$", article,
                                                     re.MULTILINE) if 1 <= int(n) <= 20})
    if not numbers:
        return []
    # 选项块：形如 ``1. [A] xxx`` 连续 20 组。
    # 逐行扫描（而不是正则跳窗），因为 OCR 会把 ``[A] x[B] y`` 粘在一行，
    # 也可能把某个空号单独占一行（``3``）。
    opt_map: Dict[int, List[str]] = {}
    cur_no: Optional[int] = None
    cur: List[str] = []
    for ln in opt_src.split("\n"):
        m = _QNO_OPT_START_RE.match(ln)
        if m and 1 <= int(m.group(1)) <= 20:
            if cur_no is not None and cur:
                opt_map[cur_no] = cur[:4]
            cur_no = int(m.group(1))
            # 一行里可能挤了 4 个选项（``1. [A] In [B] Towards [C] On [D] Till``），
            # 先就地拆开，跨行的 ``[B] xxx`` 会在下面的分支里追加。
            cur = _split_inline_bracket_options(ln)
            continue
        # 独占一行的空号（``3`` 后紧跟 ``3. [A] ...``）
        if re.fullmatch(r"\s*(\d{1,2})\s*", ln) and 1 <= int(ln.strip()) <= 20:
            lone = int(ln.strip())
            if cur_no is not None and len(cur) >= MIN_OPTS:
                opt_map[cur_no] = cur[:4]
            cur_no, cur = lone, []
            continue
        if cur_no is not None and _OPT_RE.match(ln):
            cur.append(ln)
    if cur_no is not None and cur:
        opt_map[cur_no] = cur[:4]

    # 归一化：把可能残留的未拆开行再拆一次，并保证恰好 4 个选项
    for no, opts in list(opt_map.items()):
        norm: List[str] = []
        for o in opts:
            for piece in re.split(r"(?=\[\s*[A-G]\s*\])", o):
                mm = _OPT_RE.match(piece.strip())
                if mm:
                    norm.append(f"{mm.group(1)}. {mm.group(2).strip()}")
        norm = _keep_unique_letters(norm)
        if len(norm) >= MIN_OPTS:
            opt_map[no] = norm[:4]
        else:
            opt_map.pop(no, None)

    # 双栏排版（实测 2023 英语一 doc=2503）：A/B/C 在 ``1. A. x B. y C. z``
    # 同一行里，而 D 选项被 PDF 抽取器甩到另一栏，变成一串独立的 ``D. xxx`` 行，
    # **顺序与题号一一对应**。这里按出现顺序把 D 补回去。
    if re.search(r"^\s*\d{1,2}\s*[.、．]\s*A\s*[.、．]", opt_src, re.MULTILINE):
        inline_map: Dict[int, List[str]] = {}
        for ln in opt_src.split("\n"):
            # 允许 OCR 把题号写成 ``1'3.`` / ``13'.``（引号插在数字中间）
            m3 = re.match(r"^\s*(\d{1,2}(?:['’‘]\d)?)['’‘]?\s*[.、．]\s*(.+)$", ln)
            if not m3:
                continue
            no = int(re.sub(r"\D", "", m3.group(1)))
            if not 1 <= no <= 20:
                continue
            parts = re.split(r"(?=(?:^|\s)[A-G]\s*[.、．]\s*[,.]?\s*)", m3.group(2))
            opts2 = []
            for p in parts:
                # 允许 ``A., By the way`` 这种选项文字被前置逗号污染
                mm = re.match(r"^([A-G])\s*[.、．]\s*[,.]?\s*(.+)$", p.strip())
                if mm:
                    opts2.append(f"{mm.group(1)}. {mm.group(2).strip()}")
            if len(opts2) >= 2:
                inline_map[no] = opts2[:4]
        # **只有当1..20 每一空都恰好解析出 A/B/C 三个选项时**，才敢用另一栏的
        # D 选项按顺序补全。任何一空缺失都会让"顺序对应"关系失效，
        # 补出来的D 就是错的 —— 错选项比缺选项危害大得多，宁可留空。
        complete = all(len(inline_map.get(n, [])) == 3 for n in range(1, 21))
        if complete:
            d_col = [ln.strip() for ln in opt_src.split("\n")
                     if re.match(r"^\s*D\s*[.、．]", ln)]
            if len(d_col) >= 20:
                for no in range(1, 21):
                    dm = _OPT_DOT_RE.match(d_col[no - 1])
                    if not dm:
                        continue
                    merged4 = inline_map[no] + [f"D. {dm.group(2).strip()}"]
                    if len({o[0] for o in merged4}) == 4:
                        opt_map[no] = merged4
            else:
                # D 栏不足 20 行：只补前 len(d_col) 空
                for no in range(1, min(len(d_col), 20) + 1):
                    dm = _OPT_DOT_RE.match(d_col[no - 1])
                    if not dm:
                        continue
                    merged4 = inline_map[no] + [f"D. {dm.group(2).strip()}"]
                    if len({o[0] for o in merged4}) == 4:
                        opt_map[no] = merged4

    out: List[EnglishQuestion] = []
    # OCR 会把空号写成 ``l0`` / ``lo``（字母 l 代替数字 1），导致正文里扫不到
    # 第 10 空（实测 2024 英语二 doc=73 的 ``it can feel overwhelming l0 .``）。
    # 此时用**选项区的空号**补齐 —— 选项区是 ``10. [A] at first`` 这样明确的
    # 编号+选项结构，比正文里孤零零的 ``l0`` 可靠得多。
    for no in sorted(opt_map):
        if no not in numbers:
            numbers.append(no)
    numbers = sorted(set(numbers))
    for no in numbers:
        opts = opt_map.get(no, [])
        head = f"（完形填空 第 {no} 空）\n以下短文的第 {no} 空应填入哪个最恰当的选项？\n\n{article}"
        out.append(EnglishQuestion(
            content=head,
            options=opts,
            answer=answers.get(no),
            section_type="完形",
            question_type=QT_CLOZE,
            year=meta.year, paper=meta.paper, question_no=no,
            source_paper=meta_src(meta),
            external_id=f"en:{meta.year}:{meta.paper}:cloze:{no}",
            chapter="完形填空",
        ))
    return out


def parse_reading_a(text: str, answers: Dict[int, str], meta: PaperMeta,
                    source_paper: str) -> List[EnglishQuestion]:
    """阅读 A：4篇 Text，每篇 5 题，题干带完整文章。"""
    # 切成 Text 1..4
    text_marks = [(m.start(), int(m.group(1))) for m in re.finditer(r"^\s*Text\s*(\d)\s*$", text, re.MULTILINE)]
    if not text_marks:
        text_marks = [(m.start(), int(m.group(1))) for m in
                      re.finditer(r"^\s*Text\s*(\d)\b[^\n]*$", text, re.MULTILINE)]
    if len(text_marks) < 4:
        return []

    qs: List[EnglishQuestion] = []
    for i in range(4):
        start = text_marks[i][0]
        end = text_marks[i + 1][0] if i + 1 < len(text_marks) else len(text)
        passage = text[start:end]
        blocks = _dedup_blocks(split_numbered(passage, lo=21 + i * 5, hi=25 + i * 5))
        if not blocks:
            continue
        # 文章正文 = 第一题题号之前的部分。
        # 必须按**行首** ``^N.`` 定位题号，不能用 `str.find("21.")` —— 正文里
        # 出现 ``Coventry for 2021.`` 这类年份时，子串匹配会命中 "2021." 里的
        # "21."，把文章从中间截断（实测 2020 英语一 doc=2126Text 1 全文被腰斩）。
        first_no = blocks[0][0]
        fm = re.search(rf"(?m)^\s*{first_no}\s*[.、．]", passage)
        art = passage[: fm.start()] if fm else ""
        #清掉 Part B / Directions 尾巴
        art = re.split(r"Part\s*B|Directions\s*:", art)[-1] if re.search(r"Part\s*B|Directions\s*:", art) else art
        art_lines = trim_trailing_noize(art.split("\n"))
        art_text = "\n".join(art_lines).strip()
        art_text = re.sub(r"^(Text\s*\d.*|Directions\s*:.*)$", "", art_text, flags=re.MULTILINE).strip()
        if len(art_text) < 120:
            continue
        for no, lines in blocks:
            stem, opts = block_to_question(no, lines)
            if not stem or len(opts) < 2:
                continue
            qs.append(EnglishQuestion(
                content=f"{art_text}\n\n{no}. {stem}",
                options=opts,
                answer=answers.get(no),
                section_type="选择",
                question_type=QT_READING,
                year=meta.year, paper=meta.paper, question_no=no,
                source_paper=source_paper,
                external_id=f"en:{meta.year}:{meta.paper}:readingA:{no}",
                chapter=f"阅读理解Text{i + 1}",
            ))
    return qs


def parse_new_type(text: str, answers: Dict[int, str], meta: PaperMeta,
                   source_paper: str) -> List[EnglishQuestion]:
    """新题型（Part B）：5 道。英二= 七选五（A-G 长句），英一= 排序。"""
    # 取 Part B 到下一个 Part C / Section 之间
    m = re.search(r"Part\s*B\s*(?:Directions)?", text, re.IGNORECASE)
    if not m:
        return []
    tail = text[m.end():]
    stop = re.search(r"Part\s*C|Section\s*[ⅠI]?\s*[ⅣV]?\s*Translation", tail, re.IGNORECASE)
    seg = tail[: stop.start()] if stop else tail

    # 文章主体（用于上下文）：`(41)` / `( 41) ` 标记的空
    blanks = sorted({int(n) for n in re.findall(r"\(\s*(\d{2})\s*\)", seg)
                     if 41 <= int(n) <= 45})
    body_lines: List[str] = []
    for ln in seg.split("\n"):
        if re.match(r"^\s*\[\s*[A-G]\s*\]", ln) or _OPT_DOT_RE.match(ln):
            continue
        if re.search(r"^\s*\d{1,2}\s*[.、．]\s*Directions", ln):
            continue
        body_lines.append(ln)
    body = "\n".join(trim_trailing_noize(body_lines)).strip()

    # 候选项 A-G（英二）；英一为长句A-G 也可能是排序题（选项为整句）
    cand: List[str] = []
    cand_map: Dict[str, str] = {}
    for m2 in re.finditer(r"^\s*(\[\s*[A-G]\s*\]|[A-G]\s*[.、．])\s*(.+)$", seg, re.MULTILINE):
        key = re.sub(r"[^\w]", "", m2.group(1))[-1].upper()
        cand_map[key] = m2.group(2).strip()
    cand = [f"{k}. {v}" for k, v in sorted(cand_map.items())]
    is_order = len(cand) <= 2 and "order" in seg.lower()

    qs: List[EnglishQuestion] = []
    targets = blanks or [41, 42, 43, 44, 45]
    for no in targets:
        body_q = body.replace(f"({no})", f"（第 {no} 空）____").replace(f"( {no} )", f"（第 {no} 空）____")
        if f"（第 {no} 空）" not in body_q:
            body_q = body_q.replace(f"({no} )", f"（第 {no} 空）____")
        stem = (f"（新题型 第 {no} 空）\n"
                f"以下段落第 {no} 空应填入最恰当的一项：\n\n{body_q}")
        qs.append(EnglishQuestion(
            content=stem,
            options=[] if is_order else cand,
            answer=answers.get(no),
            section_type="选择" if cand else "排序",
            question_type=QT_NEW_TYPE,
            year=meta.year, paper=meta.paper, question_no=no,
            source_paper=source_paper,
            external_id=f"en:{meta.year}:{meta.paper}:newtype:{no}",
            chapter="新题型",
        ))
    return qs


#: 英语一 Part C 划线段题号：内联括号形式 ``(46)`` / ``（47）`` / ``(4 8)``
#:（2020 英语一 doc=3315 的 OCR 把 ``48`` 写成 ``4 8``，需容忍内部空格）
_INLINE_PART_C_NO_RE = re.compile(r"[(（]\s*(4\s*[6-9]|50)\s*[)）]")


def _split_inline_part_c(seg: str) -> List[Tuple[int, str]]:
    """把英语一 Part C 的整段文章按内联 ``(46)``...``(50)`` 切成 5 段。

    英语一翻译的题号**不是行首数字**，而是嵌在段落中间的 ``(46)``：
    ``...more logical disposition. (46) with the Church's teachings...``
    因此每一段的正文 = 从自己的 ``(4x)`` 之后到下一个 ``(4y)`` 之前。

    Args:
        seg: Part C 区段全文。

    Returns:
        ``[(题号, 该段正文), ...]``，题号升序；找不到标记时返回空 list。
    """
    marks: List[Tuple[int, int]] = []  # (起始位置, 题号)
    for m in _INLINE_PART_C_NO_RE.finditer(seg):
        no = int(re.sub(r"\s+", "", m.group(1)))
        if 46 <= no <= 50:
            marks.append((m.start(), no))
    # 同一题号重复出现（OCR 重复抽取）时只保留第一次
    seen = set()
    uniq: List[Tuple[int, int]] = []
    for pos, no in marks:
        if no in seen:
            continue
        seen.add(no)
        uniq.append((pos, no))
    uniq.sort()
    out: List[Tuple[int, str]] = []
    for i, (pos, no) in enumerate(uniq):
        end = uniq[i + 1][0] if i + 1 < len(uniq) else len(seg)
        body = seg[pos:end]
        # 去掉紧跟题号的右括号，只留正文
        body = _INLINE_PART_C_NO_RE.sub("", body, count=1).strip()
        out.append((no, body))
    return out


def parse_translation(text: str, answers: Dict[int, str], meta: PaperMeta,
                      source_paper: str) -> List[EnglishQuestion]:
    """翻译：英一 = Part C 5 道（划线部分），英二 = 整段 1 道。"""
    out: List[EnglishQuestion] = []

    if meta.paper == "英语一":
        m = re.search(r"Part\s*C\s*(?:Directions)?", text, re.IGNORECASE)
        if m:
            tail = text[m.end():]
            stop = re.search(r"Section\s*(?:[ⅠI]{1,3}|[IVX]{1,4})\s*Writing", tail, re.IGNORECASE)
            seg = tail[: stop.start()] if stop else tail
            paras: List[str] = []
            for ln in trim_trailing_noize(seg.split("\n")):
                if re.match(r"^\s*Directions", ln) or "translate" in ln.lower():
                    continue
                paras.append(ln)
            ctx = "\n".join(paras).strip()
            # 英语一翻译题号是**内联括号**形式（``...(46) with the Church's...``），
            # 不是行首 ``46.``，因此不能复用 split_numbered，必须按 ``(46)`` 切。
            for no, piece in _split_inline_part_c(seg):
                piece = "\n".join(trim_trailing_noize(piece.split("\n"))).strip()
                if len(piece) < 40:
                    continue
                out.append(EnglishQuestion(
                    content=(f"（英一翻译 第 {no} 段）\n请把下面划线部分译成中文：\n\n{piece}\n\n"
                             f"【全文语境】\n{ctx}"),
                    options=[],
                    answer=None,  # 翻译答案必须来自解析文档的人工译文，否则留空
                    section_type="翻译",
                    question_type=QT_TRANSLATION,
                    year=meta.year, paper=meta.paper, question_no=no,
                    source_paper=source_paper,
                    external_id=f"en:{meta.year}:{meta.paper}:trans:{no}",
                    answer_type="subjective",
                    chapter="翻译",
                ))
            if out:
                return out

    # 英语二：整段英译汉（题号 46）
    blocks = _dedup_blocks(split_numbered(text, lo=41, hi=46))
    target = next((b for b in blocks if b[0] == 46), None)
    if target:
        stem = "\n".join(trim_trailing_noize(target[1])).strip()
        stem = re.sub(r"^Directions?:?[\s\S]{0,300}?ANSWER\s*SHEET[^\n]*\n?", "", stem,
                      flags=re.IGNORECASE)
        if len(stem) > 80:
            out.append(EnglishQuestion(
                content=f"（英二翻译）\n请把下面英文段落译成中文：\n\n{stem}",
                options=[],
                answer=None,
                section_type="翻译",
                question_type=QT_TRANSLATION,
                year=meta.year, paper=meta.paper, question_no=46,
                source_paper=source_paper,
                external_id=f"en:{meta.year}:{meta.paper}:trans:46",
                answer_type="subjective",
                chapter="翻译",
            ))
    return out


def parse_writing(text: str, answers: Dict[int, str], meta: PaperMeta,
                  source_paper: str) -> List[EnglishQuestion]:
    """写作：小作文 1 道 + 大作文 1 道。答案一律留空。"""
    out: List[EnglishQuestion] = []
    for m in re.finditer(r"Part\s*([AB])\s*(?:\n\s*)?(\d{1,2})\s*[.、．]?\s*Directions\s*:?",
                         text, re.IGNORECASE):
        part = m.group(1).upper()
        no = int(m.group(2))
        tail = text[m.end():]
        nxt = re.search(r"Part\s*[ABC]\b|\n\s*\d{1,2}\s*[.、．]\s*Directions", tail, re.IGNORECASE)
        body = tail[: nxt.start()] if nxt else tail
        body = trim_trailing_noize(body.split("\n"))
        body = [ln for ln in body if "ANSWER" not in ln.upper() or "write" in ln.lower()]
        content = "\n".join(body).strip()
        if len(content) < 40:
            continue
        label = "小作文" if part == "A" else "大作文"
        out.append(EnglishQuestion(
            content=f"（{label}）\n{content}",
            options=[],
            answer=None,
            section_type="写作",
            question_type=QT_WRITING,
            year=meta.year, paper=meta.paper, question_no=no,
            source_paper=source_paper,
            external_id=f"en:{meta.year}:{meta.paper}:writing:{part}",
            answer_type="subjective",
            chapter=label,
        ))
    return out


def meta_src(meta: PaperMeta) -> str:
    return f"{meta.year or 'NA'}年{meta.paper or '考研英语'}真题"


# --------------------------------------------------------------------------- #
# 七、入口：切一份试卷
# --------------------------------------------------------------------------- #

@dataclass
class PaperResult:
    """一份试卷的切题结果 + 统计。"""

    meta: PaperMeta
    questions: List[EnglishQuestion] = field(default_factory=list)
    gate_pass: int = 0
    gate_reject: Dict[str, int] = field(default_factory=dict)
    #: 整卷级弃用原因（非空表示该卷一切不出题）
    doc_reject: str = ""

    def by_type(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for q in self.questions:
            out[q.question_type] = out.get(q.question_type, 0) + 1
        return out

    def answered(self) -> int:
        return sum(1 for q in self.questions if (q.answer or "").strip())


def extract_paper(raw: str, file_name: str, *, doc_id: Optional[int] = None,
                  answer_raw: Optional[str] = None,
                  answer_file_name: str = "") -> PaperResult:
    """切一份英语试卷。

    Args:
        raw: 真题文档 ``documents.content``原文。
        file_name: 真题文档文件名（用于年份/卷种识别）。
        doc_id: 真题文档 id（写进 external_id 便于溯源）。
        answer_raw: **解析文档**原文（可含真题+答案）。提供时优先从它取答案与
            选项（解析文档的选项更完整）。
        answer_file_name: 解析文档文件名。
    """
    # 选主文档：默认用真题文档本身。只有当"解析文档"确实**自带答案区**、
    # 且长度与真题文档相当（>=60%，排除多卷合并/超长合集）时，才改用解析文档
    # 作为切题源 —— 解析文档的选项通常更完整。
    primary_raw, primary_name = raw, file_name
    if answer_raw:
        ans_by_no, ans_groups = parse_answer_sections(clean_content(answer_raw))
        if (ans_by_no or ans_groups) and len(answer_raw) >= len(raw) * 0.6:
            primary_raw, primary_name = answer_raw, answer_file_name

    # 整卷乱码闸门：成片 U+FFFD 的文档直接弃用，不切出"半可读"的题
    if is_doc_too_mojibake(primary_raw):
        ffr, ffn = doc_mojibake_rate(primary_raw)
        return PaperResult(meta=PaperMeta(year=detect_year(raw, file_name),
                                          paper=detect_paper(raw, file_name)),
                           doc_reject=f"整卷乱码：U+FFFD {ffn} 个（占比 {ffr:.4%}）")

    text = clean_content(primary_raw)
    meta = PaperMeta(
        year=detect_year(text, primary_name) or detect_year(raw, file_name),
        paper=detect_paper(text, primary_name) or detect_paper(raw, file_name),
    )
    answers, groups = parse_answer_sections(text)
    meta.has_answer_block = bool(answers or groups)

    src = f"{meta.year or 'NA'}年{meta.paper or '考研英语'}真题"
    if doc_id:
        src += f"(doc:{doc_id})"

    qs: List[EnglishQuestion] = []
    sections = split_sections(text)
    if not sections:
        #整卷文档里连一个 Section 标题都没有（实测 2023 英语一 doc=2503 就是
        # 这种：直接从 "Section I Use of English" 的正文/ "Text 1" 开始）。
        # 此时按全文 + 题号区间兜底切分。
        sections = [("Section ? 全卷", text)]
    for title, seg in sections:
        kind = title.split(" ", 2)[2] if title.count(" ") >= 2 else "?"
        if kind == "Use of English":
            qs.extend(parse_cloze(seg, answers, meta, full_text=text))
        elif kind == "Reading Comprehension":
            # Part A 只取 Part A 区段
            pa = re.search(r"Part\s*A", seg, re.IGNORECASE)
            seg_a = seg[pa.end():] if pa else seg
            qs.extend(parse_reading_a(seg_a, answers, meta, src))
            qs.extend(parse_new_type(seg, answers, meta, src))
            # 英语一的 Part C（英译汉 5 段）排在 Reading Comprehension 的 Part B
            # 之后、Section Writing 之前，属于本区段，不能漏。
            if re.search(r"Part\s*C", seg, re.IGNORECASE):
                qs.extend(parse_translation(seg, answers, meta, src))
        elif kind == "Translation":
            qs.extend(parse_translation(seg, answers, meta, src))
        elif kind == "Writing":
            qs.extend(parse_writing(seg, answers, meta, src))
        elif kind == "" and re.search(r"Write an essay|Write a notice|Write him/her an email",
                                      seg, re.IGNORECASE):
            # OCR 丢了 Section 罗马数字，只剩 ``Section  Writing``
            qs.extend(parse_writing(seg, answers, meta, src))
        else:
            # 少数 OCR 会丢标题：按题号兜底
            qs.extend(_fallback_by_numbers(seg, answers, meta, src))

    for q in qs:
        q.source_paper = q.source_paper or src
        if doc_id and not q.external_id.endswith(f":{doc_id}"):
            pass
        q.source_paper = src
    return PaperResult(meta=meta, questions=qs)


def _fallback_by_numbers(seg: str, answers: Dict[int, str], meta: PaperMeta,
                         src: str) -> List[EnglishQuestion]:
    """标题丢失时的兜底：按题号区间 + Directions 特征切分。

    注意 ``PartA`` 只吃 Part A 区段（否则会把新题型的 A-G 长句选项当成阅读题）。
    """
    out: List[EnglishQuestion] = []
    if re.search(r"Read the following text", seg[:800], re.IGNORECASE):
        out.extend(parse_cloze(seg, answers, meta, full_text=seg))
    #阅读 A：需要 4 个 Text 标记
    if len(re.findall(r"^\s*Text\s*\d", seg, re.MULTILINE)) >= 4:
        pa = re.search(r"^\s*Part\s*A", seg, re.MULTILINE)
        seg_a = seg[pa.end():] if pa else seg
        #若Part A 之后紧跟 Part B，则在 Part B 处截断
        pb = re.search(r"^\s*Part\s*B", seg_a, re.MULTILINE)
        if pb:
            seg_a = seg_a[: pb.start()]
        out.extend(parse_reading_a(seg_a, answers, meta, src))
    elif re.search(r"following four passages", seg[:800], re.IGNORECASE):
        out.extend(parse_reading_a(seg, answers, meta, src))
    if re.search(r"most suitable one from the list|numbered blanks?[\s\S]{0,80}extra choices",
                 seg, re.IGNORECASE):
        out.extend(parse_new_type(seg, answers, meta, src))
    if re.search(r"translate", seg[:800], re.IGNORECASE):
        out.extend(parse_translation(seg, answers, meta, src))
    if re.search(r"Write an essay|write an email|Write him/her an email", seg, re.IGNORECASE):
        out.extend(parse_writing(seg, answers, meta, src))
    return out


# --------------------------------------------------------------------------- #
# 八、英语专用质量检查 + 闸门
# --------------------------------------------------------------------------- #

#: 允许入库的题型
VALID_TYPES = frozenset({QT_CLOZE, QT_READING, QT_NEW_TYPE, QT_TRANSLATION, QT_WRITING})

#: 客观题最小英文词数
MIN_WORDS_OBJECTIVE = 8
#: 主观题最小字符数
MIN_CHARS_SUBJECTIVE = 80
#: 选项数下限
MIN_OPTS = 2

_ASCII_WORD = re.compile(r"[A-Za-z]{2,}")


def english_quality_check(q: EnglishQuestion) -> Tuple[bool, str]:
    """英语专用质量检查（在 ``quiz_content_gate`` 之外再加一层更严的）。

    闸门 ``admit()`` 的 Q_MARK 词表全中文，英文题只能靠"有选项"过闸；
    主观题（翻译/写作）会被闸门误杀，所以这里必须自己有一套判定，
    并且**只对英语题收紧，绝不放宽全局闸门**。
    """
    c = q.content or ""
    if len(c) < 40:
        return False, "reject:内容过短"
    if "\ufffd" in c:
        return False, "reject:OCR乱码"
    if q.question_type not in VALID_TYPES:
        return False, "reject:题型非法"
    words = _ASCII_WORD.findall(c)
    if len(words) < MIN_WORDS_OBJECTIVE:
        return False, "reject:英文词数不足"
    # 乱码：控制字符噪声（换行/制表是正常排版，必须排除）
    bad = sum(1 for ch in c
              if ch not in "\n\r\t" and unicodedata.category(ch).startswith("C"))
    if bad / max(len(c), 1) > 0.01:
        return False, "reject:控制字符噪声"

    if q.question_type in (QT_CLOZE, QT_READING, QT_NEW_TYPE):
        if len(q.options) < MIN_OPTS:
            return False, "reject:选项不足"
        letters = [o.split(".", 1)[0].strip().upper() for o in q.options]
        if len(set(letters)) != len(letters):
            return False, "reject:选项字母重复"
        if any(len(l) != 1 or not l.isalpha() for l in letters):
            return False, "reject:选项字母非法"
        ans = (q.answer or "").strip().upper()
        if ans and ans not in letters:
            return False, "reject:答案不在选项内"
        if q.question_type == QT_READING and len(words) < 120:
            return False, "reject:阅读文章过短"
    else:
        if len(c) < MIN_CHARS_SUBJECTIVE:
            return False, "reject:主观题内容过短"
    return True, "admitted"


#: 全局闸门判定中，**对英语同样成立**的硬拦截项（"根本不是题"的信号，与语言无关）
GATE_HARD_REJECTS = frozenset({
    "reject:内容过短", "reject:OCR乱码", "reject:纯符号噪声",
    "reject:答案体当题干", "reject:纯数字", "reject:纯标点",
})


def gate_and_filter(result: PaperResult, *,
                    use_global_gate: bool = True) -> PaperResult:
    """跑两道闸门：全局 ``quiz_content_gate.admit`` + 英语专用检查。

    全局闸门对英语主观题会误杀，所以：客观题（阅读/完形/新题型）**必须**
    两道都过；主观题（翻译/写作）只在英语专用检查通过后放行，并在
    ``confidence`` 上标记为 ``low``，让前端提示"无标准答案"。

    ### 为什么**不放宽**全局闸门的篇幅阈值
    ``admit()`` 的 ``MAX_LEN_NO_ANSWER=400`` / ``MAX_LEN_ANSWERED=1200`` 是为
    电子类设计的：题干超 400 字就判"疑似讲义正文"。而考研阅读题的题干**必然**
    带整篇文章（1200~3500 字符），完形更是 20 空共用一篇 3000 字符文章 ——
    放宽这个阈值会污染数模电切题。

    因此：全局闸门只用来抓"根本不是题"的**硬信号**（见 ``GATE_HARD_REJECTS``：
    过短/ 乱码 / 纯符号 / 答案体当题干 / 纯数字 / 纯标点），
    篇幅类判定交给英语专用的 :func:`english_quality_check` ——
    后者对英语反而更严（题型白名单 + 选项字母唯一 + 答案必须在选项内 +
    阅读文章至少 120 个英文词 + 客观题必须有选项）。
    """
    if use_global_gate:
        from .quiz_content_gate import admit  # type: ignore
    else:  # pragma: no cover
        admit = None

    kept: List[EnglishQuestion] = []
    for q in result.questions:
        g_ok, g_reason = (True, "admitted")
        if admit is not None:
            g_ok, g_reason = admit(q.content, options=q.options, answer=q.answer,
                                   source="考研英语真题", section_type=q.section_type)
        e_ok, e_reason = english_quality_check(q)
        hard_ok = g_reason not in GATE_HARD_REJECTS
        ok = e_ok and hard_ok
        if ok and q.question_type in (QT_TRANSLATION, QT_WRITING):
            # 主观题无唯一标准答案：置信度降级，前端提示"无标准答案"
            q.confidence = "low"
        if ok:
            kept.append(q)
            result.gate_pass += 1
        else:
            key = e_reason if not e_ok else f"gate_hard({g_reason})"
            result.gate_reject[key] = result.gate_reject.get(key, 0) + 1
    result.questions = kept
    return result