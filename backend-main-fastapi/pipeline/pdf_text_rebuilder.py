# -*- coding: utf-8 -*-
"""PDF 碎片文本层重建器：把逐字符/逐片段的换行拼回可读文本。

问题定性（2026-10 实测 康华光配套题库 PDF，184977 字符 / 41102 行）
------------------------------------------------------------------
    非空行 40171 行，其中 **90% 是 ≤8 字符的碎片**，20404 行仅 1 个字符：

        1
        ．十进制数
        (-6)
        10
        的补码是
        (
        A
        ．
        (111001)
        2

    这说明提取器按"文本块"输出，把「第1章」「A．(111001)2」等词句切碎了。
    **碎片是有规律的**（标点、上下标、括号各自成行），因此可以确定性重建，
    不需要引入 OCR 或模型猜测。

重建规则（全部确定性，可单测）
------------------------------
  1. 半角/全角标点相连 → 直接拼接，不留空格
       "A" + "．" + "(111001)" + "2"  →  "A．(111001)2"
  2. 中文与中文之间 → 直接拼接
       "十进制数" + "的补码是"  →  "十进制数的补码是"
  3. 中文与英文/数字之间 → 直接拼接（PDF 中文排版本就无空格）
       "取" + "6" + "位"  →  "取6位"
  4. 上下标数字紧跟前文 → 拼接
       "(111001)" + "2"  →  "(111001)2"
  5. 纯空白行作为段落边界（保留）
  6. 题型标题 / 章标题 / 【答案】【解析】标签 → 独占一行（硬边界）

不做的事：
  · 不跨段落合并（保留空白行边界），避免把两道题粘成一道
  · 不推断标点（不擅自补全缺失的句号、括号）
  · 不处理图片（图片题保持标记，交由上层决定）
"""
from __future__ import annotations

import re

#: 硬边界：这些行必须独占，不与前后拼接
HARD_LINE_RE = re.compile(
    r"^\s*(?:"
    r"第\s*[一二三四五六七八九十\d]+\s*[部分章节]|"
    r"[一二三四五六七八九十]+\s*[、.]\s*\S{2,8}|"      # 一、选择题
    r"【答案】|【解析】|【分析】|参考答案|目\s*录"
    r")\s*$"
)

#: 行尾这些字符表示"话没说完" → 下一行必然接着
OPEN_TAIL = set("（(【[、，,：:；;＝=＋+－-×÷∑∈≤≥→→／/“\"'‘《")

#: 行首这些字符表示"承上文" → 与上一行拼接
CONT_HEAD = set("）)】]、，,。.；;：:＝=＋+－-×÷∑∈≤≥→／/”\"'’》…％%")

#: 需要与左侧紧贴（不留空格）的字符集合（中英文标点混排都用它）
NONSPACING = set("．.、，,。；;：:！!？?（）()【】[]《》“”\"‘’'’…～~％%＋+-×÷=∑/\\")

#: 小节标题片段（如 "二、选择题"）。
#: 注意：**不加 `^` 锚定** —— 该正则既用于行首判定（match），
#: 也用于行中间检测（search），加了 `^` 会导致后者永远失配
#: （实测踩坑：'卡诺图…二、选择题1' 检测不到标题）。
RE_SECTION_HEAD = re.compile(
    r"(?:[一二三四五六七八九十]+|\d+)\s*[、.．]\s*"
    r"(选择题|填空题|判断题|简答题|计算题|分析题|应用题|作图题|综合题)"
)


def _is_short_fragment(text: str) -> bool:
    """判断是否为被切碎的碎片行。

    实测阈值：≤14 字符。过大会误伤正常短句（如"二、选择题"），
    过小则拼不回 `A` + `．` 这种单字符碎片。
    """
    return len(text) <= 14


def _join_pair(left: str, right: str) -> str:
    """按中英文排版规则拼接两段文本。"""
    if not left:
        return right
    if not right:
        return left
    lc, rc = left[-1], right[0]
    # 标点贴紧：任一侧是标点 → 直接拼，不加空格
    if lc in NONSPACING or rc in NONSPACING:
        return left + right
    # 中文相邻 → 直接拼
    if _is_cjk(lc) or _is_cjk(rc):
        return left + right
    # 英文/数字相邻 → 保留一个空格（避免 "word1""word2" 粘连）
    return f"{left} {right}"


def _is_cjk(ch: str) -> bool:
    """是否中文字符。"""
    return "\u4e00" <= ch <= "\u9fff" or ch in "　"


def rebuild_lines(content: str) -> list[str]:
    """把碎片化文本层重建为可读行列表。

    Args:
        content: 原始文本层内容。

    Returns:
        重建后的行列表（空白行保留为 ""，作为段落边界）。
    """
    src = (content or "").splitlines()
    out: list[str] = []
    buf = ""          # 正在累积的行

    def flush(keep_blank: bool = False) -> None:
        """收尾当前累积行。

        Args:
            keep_blank: 收尾后是否补一个空行作为段落边界。
                空行边界必须保留，否则相邻段落会被后续拼接逻辑连成一行。
        """
        nonlocal buf
        if buf:
            out.append(buf)
            buf = ""
        if keep_blank:
            out.append("")

    for raw in src:
        s = raw.strip()

        # 空白行 → 段落边界（必须保留，否则相邻段落会被拼接逻辑粘连）
        if not s:
            if buf:
                flush(keep_blank=True)
            elif not out or out[-1] != "":
                out.append("")
            continue

        # 硬边界行 → 先收尾，再独占一行
        if HARD_LINE_RE.match(s):
            flush()
            out.append(s)
            continue

        if not buf:
            buf = s
            continue

        # 决定是否拼接
        prev = buf[-1] if buf else ""
        # 小节标题必须独立成行：右片段若以小节标题开头 → 不拼接，先收尾
        if RE_SECTION_HEAD.match(s):
            flush()
            buf = s
            continue

        # 右片段若是「纯选项键」（单个 A-D，或 A．/B． 这种带标点但无内容的），
        # 绝不能拼到上一行末尾 —— 否则会合并出 "C．(110100)2 D" 这种
        # 一行两选项，导致 OPTION_RE 漏抓、选项丢失（实测踩坑）。
        if re.fullmatch(r"[A-D]", s) or re.fullmatch(r"[A-D]\s*[．.、)）]", s):
            out.append(buf)
            buf = s
            continue

        should_join = (
            prev in OPEN_TAIL
            or s[0] in CONT_HEAD
            or (_is_short_fragment(buf) and _is_short_fragment(s))
            or (_is_cjk(prev) and _is_cjk(s[0]))
            or (_is_cjk(prev) and not s[0].isalpha())
            or (not prev.isalpha() and _is_cjk(s[0]))
        )

        if should_join:
            merged = _join_pair(buf, s)
            # 拼接后复查：结果里若嵌着小节标题（如碎片 "二、"+"选择题"+"1"
            # 拼成 "…卡诺图二、选择题1"），必须在标题处切开，
            # 否则抽取器 SECTION_RE 命中 0 → 整个选择题区抽不到题。
            m = RE_SECTION_HEAD.search(merged)
            if m and m.start() > 0:
                head = merged[:m.start()].rstrip()
                tail = merged[m.start():].strip()
                if head:
                    out.append(head)
                buf = tail
            else:
                buf = merged
        else:
            out.append(buf)
            buf = s

    flush()
    return out


def rebuild_text(content: str) -> str:
    """重建为完整文本（行之间用 \\n 连接）。"""
    return "\n".join(rebuild_lines(content))


#: 选项起始标记：在题干行内识别 A．/ B．/ C．/ D．，需要拆行
#: 只匹配「行内某处出现 A．」且前面不是字母（避免误伤 "T A．" 之类）
INLINE_OPTION_RE = re.compile(r"(?<![A-Za-z])([ABCD])\s*[．.、)）]\s*")

#: 题干结束特征：助词/标点，其后紧跟选项即认为题干结束
STEM_END_CHARS = set("。？?）)]】:：；;，,")


def split_inline_options(line: str) -> list[str]:
    """把「题干＋选项挤在一行」拆成多行。

    实测形态（康华光配套题库 PDF 重建后）：
        [北京理工大学2008研]A．
        B．C．D．

    正确形态应为：
        [北京理工大学2008研]
        A．
        B．
        C．
        D．

    切分策略（保守）：
      · 找到行内第一个 A．/B．/C．/D． 标记，且其**前一个字符**是
        题干结束特征（]）】。？等）或行首 → 在此处切分
      · 切分点之后，按连续的选项标记再切
      · 无法确定时不切，保持原行（宁可漏切，不可切断题干正文）
    """
    if not line or not INLINE_OPTION_RE.search(line):
        return [line]

    matches = list(INLINE_OPTION_RE.finditer(line))
    if not matches:
        return [line]

    # 必须是 A 开头的连续选项序列（A→B→C→D 递增）才认为是真选项
    first = matches[0]
    # 第一个选项标记的前一个字符必须是题干结束特征或行首
    if first.start() > 0 and line[first.start() - 1] not in STEM_END_CHARS:
        # 例外：A 前面是空白也接受
        if not line[first.start() - 1].isspace():
            matches = matches[1:]
            if not matches:
                return [line]
            first = matches[0]
            if first.start() > 0 and line[first.start() - 1] not in STEM_END_CHARS \
                    and not line[first.start() - 1].isspace():
                return [line]

    parts: list[str] = []
    head = line[:first.start()].rstrip()
    if head:
        parts.append(head)

    # 按匹配位置切分后续片段，并校验键是否递增
    seq = matches
    for i, m in enumerate(seq):
        end = seq[i + 1].start() if i + 1 < len(seq) else len(line)
        seg = line[m.start():end].strip()
        if not seg:
            continue
        if parts and parts[-1] and parts[-1][-1] not in STEM_END_CHARS:
            # 上一片段是选项且本段不是新选项 → 拼回去（选项文字换行了）
            pass
        parts.append(seg)

    return parts if len(parts) >= 2 else [line]


def rebuild_text_with_options(content: str) -> str:
    """重建文本并拆分行内选项（教材题库场景推荐用这个）。"""
    lines = rebuild_lines(content)
    out: list[str] = []
    for ln in lines:
        out.extend(split_inline_options(ln))
    return "\n".join(out)


def rebuild_stats(content: str) -> dict:
    """重建前后对比统计，用于评估改善幅度。"""
    before = (content or "").splitlines()
    after = rebuild_lines(content)

    def _frag_ratio(lines: list[str]) -> float:
        ne = [ln for ln in lines if ln.strip()]
        if not ne:
            return 0.0
        return sum(1 for ln in ne if len(ln.strip()) <= 8) / len(ne)

    return {
        "lines_before": len(before),
        "lines_after": len(after),
        "frag_ratio_before": round(_frag_ratio(before), 4),
        "frag_ratio_after": round(_frag_ratio(after), 4),
    }
