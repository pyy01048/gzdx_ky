# -*- coding: utf-8 -*-
"""「配套题库」类文档的选择题抽取器。

目标格式（阎石/康华光配套题库 PDF 文本层，实测样本）
------------------------------------------------------
    <章节>
    一、选择题
    （多选）在以下代码中，是无权码的有（  ）。[北京邮电大学2015研]
    A．8421BCD码
    B．5421BCD码
    C．余三码
    D．格雷码
    CD
    【答案】
    编码可分为有权码和无权码……
    【解析】

抽取规则：
    · 只在「一、选择题」小节内抽取，遇到下一个小节标题即停止
    · 题干 = 选项块之前的最后一行非空文本（可能含 （多选） 前缀）
    · 选项 = 连续的 A．/B．/C．/D． 行，至少 2 项
    · 答案 = 选项块之后第一行形如 ABCD 的子集
    · 解析 = 【解析】 之后到下一个题目前的所有行
    · 院校年份从题干 [XX大学2015研] 提取，写入 source_paper / year

安全设计：
    · 纯函数，不写库；调用方决定是否落库
    · 抽不到答案的题一律丢弃（不可刷的题入库只会污染题库）
    · 抽到的题在返回前做完整性自检
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 小节标题：一、二、三… 或 1. 2. 3. 开头的题型名
#: 允许行尾紧跟题号（PDF 重建后常见 "二、选择题1．xxx" 形态），
#: 也允许标题后直接接题干（"二、选择题1．十进制数(-6)"）。
#: 2026-10-19：PG 语料实测补充「分析计算题 / 计算分析题 / 解答题」三个非选择题
#: 小节名（圣才配套题库实测词频 35/16/14 处）——缺失时选择题区不会在这些
#: 小节处闭合，后续小节的解答正文会漏进选择题缓冲区形成垃圾块。
SECTION_RE = re.compile(
    r"^\s*(?:[一二三四五六七八九十]+|\d+)\s*[、.．]\s*"
    r"(选择题|填空题|判断题|简答题|分析计算题|计算分析题|计算题|分析题|解答题|应用题|作图题|综合题)"
    r"\s*\d*\s*[．.]?\s*(.*)$"
)
#: 选项行：A．/ A. / A、 / A) / A）
OPTION_RE = re.compile(r"^\s*([A-D])\s*[．.、)）]\s*(.+?)\s*$")
#: 答案行：仅由 A-D 字母组成（2-8 个字符），如 "CD"、"ABD"
ANSWER_RE = re.compile(r"^\s*([A-D]{1,8})\s*$")
#: 院校年份标注：[北京邮电大学2015研]
TAG_RE = re.compile(r"\[([^\[\]]{2,40}?)(\d{4})\s*研\]")


@dataclass
class ExtractedQuestion:
    """抽取出的一道选择题。"""

    stem: str
    options: list[dict]
    answer: str
    analysis: str = ""
    question_type: str = "single"
    source_paper: str = ""
    year: int | None = None
    chapter: str = ""

    def is_valid(self) -> bool:
        """完整性自检：题干够长、选项≥2、答案落在选项集合内。"""
        if len(self.stem.strip()) < 6:
            return False
        if len(self.options) < 2:
            return False
        keys = {o["key"] for o in self.options}
        return bool(self.answer) and set(self.answer) <= keys


@dataclass
class ExtractStats:
    """抽取统计，用于报告准确率。"""

    sections_found: int = 0
    blocks_seen: int = 0
    extracted: int = 0
    rejected_no_answer: int = 0
    rejected_invalid: int = 0
    questions: list[ExtractedQuestion] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sections_found": self.sections_found,
            "blocks_seen": self.blocks_seen,
            "extracted": self.extracted,
            "rejected_no_answer": self.rejected_no_answer,
            "rejected_invalid": self.rejected_invalid,
        }


def _parse_tag(text: str) -> tuple[str, int | None]:
    """从题干提取 [院校年份研] → (院校名, 年份)。"""
    m = TAG_RE.search(text or "")
    if not m:
        return "", None
    return m.group(1).strip(), int(m.group(2))


def _merge_fragmented_lines(content: str) -> str:
    """把 PDF 逐片段换行的文本层拼回自然行。

    实测形态（康华光配套题库 PDF）——每个片段独占一行：
        （\\n10100011.11\\n）\\n2\\n＝（\\u3000\\u3000）\\n10\\n＝
    正确形态应为：
        （10100011.11）2＝（　　）10＝

    合并规则（保守，只拼明显属于同一句的碎片）：
      · 片段很短（≤14 字符）且不是选项行/答案行/题型标题 → 拼到上一行
      · 行尾是开括号/等号/连接词，或下一行以闭括号/运算符开头 → 拼接
      · 空白行与题型标题行作为硬边界，绝不跨越

    对已经规整的 TXT 文本层，本函数近乎无操作（长行不会被合并）。
    """
    src = (content or "").splitlines()
    out: list[str] = []

    #: 这些行必须独占，不参与拼接
    hard_prefix = ("【答案】", "【解析】")
    for raw in src:
        s = raw.strip()
        if not s:
            out.append("")
            continue
        if SECTION_RE.match(s) or s.startswith(hard_prefix):
            out.append(s)
            continue
        if OPTION_RE.match(s) or ANSWER_RE.match(s) or re.match(r"^\d+$", s):
            out.append(s)
            continue
        if re.match(r"^第\s*\d+\s*章|^第[一二三四五六七八九十]+部分", s):
            out.append(s)
            continue

        if out and out[-1] and _should_join(out[-1], s):
            out[-1] = out[-1] + s
        else:
            out.append(s)
    return "\n".join(out)


def _should_join(prev: str, cur: str) -> bool:
    """判断 cur 是否应拼接到 prev 后面。"""
    p, c = prev.strip(), cur.strip()
    if not p:
        return False
    # 上一行以这些字符结尾 → 句子未结束
    if p.endswith(("（", "(", "＝", "=", "，", "、", "。", "的", "是", "为",
                   "在", "和", "与", "或", "及", "：", ":", "×", "＋", "+")):
        return True
    # 当前行以这些字符开头 → 承接上文
    if c.startswith(("）", ")", "＝", "=", "×", "＋", "+", "－", "-", "；", "，",
                     "、", "。", "。", "，", "研", "年")):
        return True
    # 双方都很短 → 视为被拆碎的片段
    return len(p) <= 14 and len(c) <= 14


def extract_from_text(
    content: str, *, chapter_hint: str = "", is_pdf_layer: bool = False
) -> ExtractStats:
    """从文档正文抽取所有选择题。

    Args:
        content: 文档文本层内容。
        chapter_hint: 兜底章节名（正文未标章节时使用）。
        is_pdf_layer: PDF 文本层开关。开启时先用 pdf_text_rebuilder 把
            碎片行（实测 90% 行 ≤8 字符）重建为可读行，并拆分行内选项；
            关闭时走轻量合并（适配规整的 TXT 文本层）。

    Returns:
        :class:`ExtractStats`，含抽取成功与拒绝计数。
    """
    stats = ExtractStats()
    if is_pdf_layer:
        from pipeline.pdf_text_rebuilder import rebuild_text_with_options
        lines = rebuild_text_with_options(content).splitlines()
    else:
        lines = _merge_fragmented_lines(content).splitlines()
    # 状态机：in_choice_section 表示当前处于「选择题」小节
    in_choice = False
    current_chapter = chapter_hint
    buf: list[str] = []  # 当前题目缓冲（题干行 + 选项行 + 答案行）

    def flush() -> None:
        """把缓冲解析成一道题。"""
        nonlocal buf
        if not buf:
            return
        stats.blocks_seen += 1
        q = _parse_block(buf, current_chapter)
        buf = []
        if q is None:
            stats.rejected_no_answer += 1
            return
        if not q.is_valid():
            stats.rejected_invalid += 1
            return
        stats.extracted += 1
        stats.questions.append(q)

    for raw in lines:
        line = raw.rstrip()

        m = SECTION_RE.match(line)
        if m:
            kind = m.group(1)
            rest = (m.group(2) or "").strip()   # 标题后紧跟的题干（PDF 重建后常见）
            if kind == "选择题":
                flush()
                in_choice = True
                stats.sections_found += 1
                # 标题后面粘着的题干要保留，否则首题会丢题干
                if rest:
                    buf.append(rest)
            else:
                # 进入其他题型小节 → 选择题区结束
                flush()
                in_choice = False
            continue

        # 章节标题（如 "第2章 逻辑代数基础"）
        if re.match(r"^\s*第\s*\d+\s*章", line):
            flush()
            current_chapter = line.strip()
            in_choice = False
            continue

        if not in_choice:
            continue

        # 遇到题号（单独成行的数字）→ 上一题结束
        if re.match(r"^\s*\d+\s*$", line):
            flush()
            buf.append(line)
            continue

        buf.append(line)

    flush()
    return stats


def _parse_block(block: list[str], chapter: str) -> ExtractedQuestion | None:
    """解析单个题目块：题干 + 选项 + 答案 + 解析。"""
    # 定位选项行区间
    opt_idx = [i for i, ln in enumerate(block) if OPTION_RE.match(ln)]
    if len(opt_idx) < 2:
        return None

    start, end = opt_idx[0], opt_idx[-1]

    # 题干 = 选项之前最像题干的那些行
    #
    # 合并预清洗可能把题干与上一题的解析尾句粘在一起，也可能把长题干拆成多行。
    # 判定顺序：
    #   1. 优先取含疑问标记（？/（　　））的最后一行——选择题题干几乎必含
    #   2. 退而取最长的非题号行
    cand = [ln.strip() for ln in block[:start]
            if ln.strip() and not re.match(r"^\d+$", ln.strip())
            and ln.strip() not in ("【答案】", "【解析】")]
    if not cand:
        return None

    marked = [ln for ln in cand if "？" in ln or "?" in ln
              or "（ " in ln or "（  ）" in ln or "（　　）" in ln or "(" in ln]
    stem_raw = (marked[-1] if marked else max(cand, key=len)).strip()

    # 多选标记
    is_multi = "多选" in stem_raw
    stem = re.sub(r"^[（(]\s*多选\s*[）)]\s*", "", stem_raw).strip()

    # 选项
    #
    # PDF 重建后可能出现「选项键与内容分家」：B． 独占一行、内容在下一行。
    # 因此解析到空文本的选项时，继续向下取行补全（取到下一个选项键或硬边界为止）。
    options: list[dict] = []
    i = start
    while i <= end:
        m = OPTION_RE.match(block[i])
        if not m:
            i += 1
            continue
        key, text = m.group(1), m.group(2).strip()
        # 文本为空 → 从后续行补
        if not text:
            j = i + 1
            extra: list[str] = []
            while j <= len(block) - 1 and not OPTION_RE.match(block[j]) \
                    and block[j].strip() not in ("【答案】", "【解析】") \
                    and not re.match(r"^\d+\s*[．.]\s*\S", block[j].strip()):
                if block[j].strip():
                    extra.append(block[j].strip())
                j += 1
            text = " ".join(extra)
            i = j
        else:
            # 内容可能延续到下一行（下一行不是新选项/新题/标签）
            j = i + 1
            while j <= len(block) - 1 and not OPTION_RE.match(block[j]) \
                    and block[j].strip() not in ("【答案】", "【解析】") \
                    and not re.match(r"^\d+\s*[．.]\s*\S", block[j].strip()):
                nxt = block[j].strip()
                if nxt and not nxt.startswith(("【", "图")):
                    text = f"{text} {nxt}"
                j += 1
            i = j
        if text.strip():
            options.append({"key": key, "text": text.strip()})

    # 只保留键连续递增的最长段（防止跨题粘连）
    options = _longest_ascending(options)
    if len(options) < 2:
        return None

    # ---- 答案与解析提取：同时兼容两种实测格式 ----
    #
    # 格式 A（TXT 文本层，答案在前、标签在后）：
    #     D．格雷码
    #     CD          ← 答案
    #     【答案】     ← 标签跟在答案后面
    #     编码可分为有权码……
    #     【解析】     ← 标签跟在解析后面
    #
    # 格式 B（PDF 文本层，标签在前、答案在后）：
    #     D．(111010)2
    #     【答案】     ← 标签在前
    #     D           ← 答案
    #     【解析】
    #     -6 的原码为 100110……
    #
    # 判定方式：找 【答案】 位置，看它**前一行**和**后一行**哪个是纯字母答案。
    answer = ""
    analysis = ""
    ans_idx = next((i for i, ln in enumerate(block)
                    if ln.strip() == "【答案】"), None)
    exp_idx = next((i for i, ln in enumerate(block)
                    if ln.strip() == "【解析】"), None)

    if ans_idx is not None:
        # 格式 A：答案在标签前
        if ans_idx > 0 and ANSWER_RE.match(block[ans_idx - 1].strip()):
            answer = block[ans_idx - 1].strip()
        # 格式 B：答案在标签后
        elif ans_idx + 1 < len(block) and ANSWER_RE.match(block[ans_idx + 1].strip()):
            answer = block[ans_idx + 1].strip()

    # 兜底：取选项块之后第一个纯字母行（两种格式都覆盖不到的罕见情况）
    if not answer:
        for ln in block[end + 1:]:
            s = ln.strip()
            if s in ("【答案】", "【解析】"):
                continue
            if ANSWER_RE.match(s):
                answer = s
                break

    # 解析：按格式 B → 【解析】之后；格式 A → 【答案】与【解析】之间
    if exp_idx is not None and answer and ans_idx is not None \
            and ans_idx < exp_idx and block[ans_idx + 1].strip() == answer:
        # 格式 B：【解析】标签之后才是正文
        body = [ln.strip() for ln in block[exp_idx + 1:] if ln.strip()]
        analysis = " ".join(body)
    elif ans_idx is not None and exp_idx is not None and ans_idx < exp_idx:
        # 格式 A：【答案】与【解析】之间是正文
        body = [ln.strip() for ln in block[ans_idx + 1:exp_idx] if ln.strip()]
        analysis = " ".join(body)
    elif exp_idx is not None:
        body = [ln.strip() for ln in block[exp_idx + 1:] if ln.strip()]
        analysis = " ".join(body)

    paper, year = _parse_tag(stem_raw)

    return ExtractedQuestion(
        stem=stem,
        options=options,
        answer=answer,
        analysis=analysis[:2000],
        question_type="multiple" if is_multi or len(answer) > 1 else "single",
        source_paper=paper,
        year=year,
        chapter=chapter,
    )


def _longest_ascending(options: list[dict]) -> list[dict]:
    """取键连续递增的最长段，避免把两道题的选项粘连成一道。"""
    if not options:
        return []
    best: list[dict] = []
    cur: list[dict] = [options[0]]
    for prev, now in zip(options, options[1:]):
        if ord(now["key"]) == ord(prev["key"]) + 1:
            cur.append(now)
        else:
            if len(cur) > len(best):
                best = cur
            cur = [now]
    if len(cur) > len(best):
        best = cur
    return best
