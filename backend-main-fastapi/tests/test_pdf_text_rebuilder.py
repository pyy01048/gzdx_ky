# -*- coding: utf-8 -*-
"""PDF 文本层重建器单测。

覆盖 2026-10 实测踩坑（康华光配套题库 PDF，90% 行 ≤8 字符）：
  · 单字符碎片拼接
  · 小节标题必须独立成行（否则抽取器找不到选择题区 → 抽取 0 题）
  · 行内选项拆分（题干与选项挤在一行）
  · 选项键与内容分家的补全
"""
import unittest

from pipeline.pdf_text_rebuilder import (
    rebuild_lines,
    rebuild_stats,
    rebuild_text_with_options,
    split_inline_options,
)
from pipeline.exam_bank_extractor import SECTION_RE, extract_from_text


class TestSplitInlineOptions(unittest.TestCase):
    """行内选项拆分边界。"""

    def test_题干末尾紧跟A选项_应拆开(self):
        got = split_inline_options("[北京理工大学2008研]A．")
        self.assertEqual(got, ["[北京理工大学2008研]", "A．"])

    def test_连续选项_应逐个拆开(self):
        self.assertEqual(split_inline_options("B．C．D．"), ["B．", "C．", "D．"])

    def test_行首A且无题干_不拆(self):
        self.assertEqual(split_inline_options("A．接高电平"), ["A．接高电平"])

    def test_无选项标记_原样返回(self):
        s = "正常题干文字没有选项标记"
        self.assertEqual(split_inline_options(s), [s])

    def test_题干加多选项_正确拆分(self):
        got = split_inline_options("[北京大学2010研]A．F＝AB B．F＝BC")
        self.assertEqual(got, ["[北京大学2010研]", "A．F＝AB", "B．F＝BC"])


class TestRebuildLines(unittest.TestCase):
    """碎片行重建。"""

    def test_单字符碎片应拼接(self):
        # 真实形态：A / ． / (111001) / 2 各自成行
        src = "A\n．\n(111001)\n2\n"
        out = [ln for ln in rebuild_lines(src) if ln.strip()]
        self.assertEqual(out, ["A．(111001)2"])

    def test_小节标题不被拼进上一行(self):
        # 实测踩坑：'卡诺图二、选择题1' → 必须切成两行，否则 SECTION_RE 命中 0
        src = "卡诺图如图2-2所示。\n二、\n选择题\n1\n"
        out = [ln for ln in rebuild_lines(src) if ln.strip()]
        self.assertTrue(
            any(SECTION_RE.match(ln) for ln in out),
            f"重建后找不到小节标题，实际输出：{out}",
        )

    def test_空白行保留为段落边界(self):
        out = rebuild_lines("第一段\n\n第二段\n")
        self.assertIn("", out)

    def test_碎片率显著下降(self):
        src = "\n".join("abcdefgh"[i % 8] for i in range(40))
        st = rebuild_stats(src)
        self.assertLessEqual(st["frag_ratio_after"], st["frag_ratio_before"])
        self.assertLess(st["lines_after"], st["lines_before"])


class TestExtractPdfLayer(unittest.TestCase):
    """PDF 模式端到端抽取（标签前置格式）。"""

    PDF_SAMPLE = """一、选择题
1
．十进制数
(-6)
10
的补码是
(
　
)
。(
连符号位在内取
6
位
)[
电子科技大学
2006
研
]
A
．
(111001)
2
B
．
(110011)
2
C
．
(110100)
2
D
．
(111010)
2
【答案】
D
【解析】
-6
的原码为
100110
"""

    def test_pdf格式能抽出题目(self):
        res = extract_from_text(self.PDF_SAMPLE, is_pdf_layer=True)
        self.assertGreaterEqual(res.extracted, 1, "PDF 模式应至少抽出 1 题")

    def test_pdf格式答案正确(self):
        res = extract_from_text(self.PDF_SAMPLE, is_pdf_layer=True)
        self.assertTrue(res.questions, "应有抽出的题目")
        q = res.questions[0]
        self.assertEqual(q.answer, "D")
        keys = {o["key"] for o in q.options}
        self.assertLessEqual(set(q.answer), keys, "答案必须落在选项集合内")


class TestExtractTxtLayer(unittest.TestCase):
    """TXT 模式端到端抽取（标签后置格式）。"""

    TXT_SAMPLE = """一、选择题
（多选）在以下代码中，是无权码的有（  ）。[北京邮电大学2015研]
A．8421BCD码
B．5421BCD码
C．余三码
D．格雷码
CD
【答案】
编码可分为有权码和无权码，两者的区别在于每一位是否有权值。
【解析】
"""

    def test_txt格式能抽出题目(self):
        res = extract_from_text(self.TXT_SAMPLE, is_pdf_layer=False)
        self.assertGreaterEqual(res.extracted, 1)

    def test_txt格式答案为多选(self):
        res = extract_from_text(self.TXT_SAMPLE, is_pdf_layer=False)
        q = res.questions[0]
        self.assertEqual(q.answer, "CD")
        self.assertEqual(q.question_type, "multiple")

    def test_txt格式解析已提取(self):
        res = extract_from_text(self.TXT_SAMPLE, is_pdf_layer=False)
        self.assertIn("有权码", res.questions[0].analysis)


if __name__ == "__main__":
    unittest.main(verbosity=2)
