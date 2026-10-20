"""Word（.docx）公式图片提取：把「文字 + 公式图」按原排版还原。

为什么需要它
------------
考研题库类 .docx 里，数学公式**不是 OMML 方程对象，而是以图片形式嵌在段落里**。
实测某《高等数学（第7版）配套题库》.docx：``word/document.xml`` 里
``<m:oMath>`` 数量为 **0**，而 ``<w:drawing>`` 数量为 **11,108**，
``word/media/`` 下有 9,508 个图片文件，内容就是 ``lim_{x→1/2} (1-4x²)/(2x+1) = 2``
这类排版好的公式图。

而现有 ``services/document_parser.py::_parse_docx`` 只取 ``paragraph.text``
——python-docx 的 ``paragraph.text`` **不包含任何图片**，于是这些公式被静默丢弃，
最终在题库里表现为「设函数具有二阶导数，，则在上（　）」这种题干残缺。

本模块的定位
------------
1. 按**文档顺序**遍历 body（段落与表格混排的真实顺序）；
2. 遇到图片 run 就导出一份二进制，并插入 ``[[F:<序号>]]`` 占位符；
3. 文本 run 照常拼接。

这样得到的文本既能定位公式位置（占位符），又能拿到像素级保真的公式图，
**不需要任何 OCR 或公式识别模型**。

与 PDF 侧的分工：扫描版 PDF 的公式是渲染在页面上的，仍然需要
MinerU / PP-Structure 的公式模型（见 ``services/parsers/``）；而 Word 侧
公式是独立图片，直接复用即可。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# 占位符格式：[[F:12]]
MARKER_RE = re.compile(r"\[\[F:(\d+)\]\]")

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf", ".webp"})

#: Word 里常见的装饰性图片尺寸下限（像素）：小于它多半是分隔线/项目符号/图标
MIN_FORMULA_SIDE = 8


def formula_marker(index: int) -> str:
    """生成公式占位符。``index`` 是文档内的图片序号（0 基）。"""
    return f"[[F:{index}]]"


@dataclass
class DocxImage:
    """一张从 docx 里抽出的图片（绝大多数情况下是一道公式）。"""

    index: int
    rel_id: str
    source_name: str
    out_path: str = ""
    byte_size: int = 0
    width_px: int = 0
    height_px: int = 0

    @property
    def marker(self) -> str:
        return formula_marker(self.index)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "rel_id": self.rel_id,
            "source_name": self.source_name,
            "out_path": self.out_path,
            "byte_size": self.byte_size,
            "width_px": self.width_px,
            "height_px": self.height_px,
        }


@dataclass
class DocxParseResult:
    """解析结果：还原后的文本 + 抽出的图片清单。"""

    text: str = ""
    images: List[DocxImage] = field(default_factory=list)
    paragraph_count: int = 0
    table_count: int = 0
    error: str = ""

    @property
    def markers(self) -> List[int]:
        """文本中出现的公式占位符序号。"""
        return [int(m) for m in MARKER_RE.findall(self.text)]

    def image_by_index(self, index: int) -> Optional[DocxImage]:
        for img in self.images:
            if img.index == index:
                return img
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "images": [i.to_dict() for i in self.images],
            "paragraph_count": self.paragraph_count,
            "table_count": self.table_count,
            "error": self.error,
        }


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #


def _qn(tag: str) -> str:
    from docx.oxml.ns import qn

    return qn(tag)


def _iter_paragraph_runs(p_el: Any):
    """按文档顺序产出段落的 run 元素。"""
    for r_el in p_el.iter(_qn("w:r")):
        yield r_el


def _run_text(r_el: Any) -> str:
    """把一个 run 里的文字取出来（tab / 换行也处理）。"""
    parts: List[str] = []
    for node in r_el.iter():
        tag = node.tag
        if tag == _qn("w:t"):
            parts.append(node.text or "")
        elif tag == _qn("w:tab"):
            parts.append("\t")
        elif tag in (_qn("w:br"), _qn("w:cr")):
            parts.append("\n")
    return "".join(parts)


def _run_image_rel_ids(r_el: Any) -> List[str]:
    """取出一个 run 里所有图片的关系 id（DrawingML 与旧版 VML 都支持）。"""
    rel_ids: List[str] = []
    for node in r_el.iter():
        tag = node.tag
        if tag.endswith("}blip"):  # a:blip @r:embed
            rid = node.get(_qn("r:embed")) or node.get(_qn("r:link"))
            if rid:
                rel_ids.append(rid)
        elif tag.endswith("}imagedata"):  # v:imagedata @r:id
            rid = node.get(_qn("r:id"))
            if rid:
                rel_ids.append(rid)
    return rel_ids


def _iter_cell_paragraphs(tc_el: Any):
    """表格单元格里的段落元素。"""
    for p_el in tc_el.findall(_qn("w:p")):
        yield p_el


def _measure(path: str) -> Tuple[int, int]:
    """读图片尺寸；失败返回 (0, 0)。"""
    try:
        from PIL import Image

        with Image.open(path) as im:
            return int(im.size[0]), int(im.size[1])
    except Exception:  # noqa: BLE001 - 尺寸拿不到不影响主流程
        return 0, 0


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def parse_docx_with_images(
    file_path: str,
    *,
    out_dir: Optional[str] = None,
    max_images: Optional[int] = None,
    keep_all: bool = True,
    table_position: str = "after",
) -> DocxParseResult:
    """解析 .docx，按文档顺序还原「文字 + 公式占位符」。

    参数
    ----
    file_path:
        .docx 路径。
    out_dir:
        图片导出目录。不给则不导出二进制（``DocxImage.out_path`` 为空，
        ``byte_size`` 仍然有值），可用于只做结构探测。
    max_images:
        最多导出多少张图片；``None`` 表示不限制。超出的图片仍会在文本里留占位符，
        但 ``DocxImage.out_path`` 为空——**不要**据此认为公式不存在。
    keep_all:
        True 时连装饰性小图也导出；False 时跳过宽或高小于 ``MIN_FORMULA_SIDE``
        的图片（分隔线、项目符号），这类图不是公式。
    table_position:
        ``"after"``（默认）复刻旧管线 ``_parse_docx`` 的顺序——**先所有段落、再所有表格**。
        这样去掉占位符后的文本与库里已有的 ``documents.content`` **逐字符一致**，
        可以直接用位置映射把公式插回原题。
        ``"inline"`` 用真实文档顺序（段落与表格交错），可读性更好，但与旧入库文本不再逐字对齐。

    返回
    ----
    :class:`DocxParseResult`
    """
    result = DocxParseResult()
    try:
        import docx
    except ImportError as exc:  # pragma: no cover
        result.error = f"python-docx 未安装: {exc}"
        return result

    try:
        doc = docx.Document(file_path)
    except Exception as exc:  # noqa: BLE001
        result.error = f"无法打开 docx: {exc}"
        return result

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    part = doc.part
    image_index = 0
    exported = 0
    text_parts: List[str] = []
    seen_rel: Dict[str, DocxImage] = {}

    def _handle_paragraph(p_el: Any) -> str:
        nonlocal image_index, exported
        buf: List[str] = []
        for r_el in _iter_paragraph_runs(p_el):
            txt = _run_text(r_el)
            if txt:
                buf.append(txt)
            for rid in _run_image_rel_ids(r_el):
                img = seen_rel.get(rid)
                if img is None:
                    img = DocxImage(index=image_index, rel_id=rid, source_name=rid)
                    image_index += 1
                    seen_rel[rid] = img
                    result.images.append(img)
                    try:
                        blob = part.related_parts[rid].blob
                        img.byte_size = len(blob)
                        img.source_name = getattr(
                            part.related_parts[rid], "partname", rid
                        )
                        img.source_name = os.path.basename(str(img.source_name))
                        if out_dir and (max_images is None or exported < max_images):
                            ext = os.path.splitext(img.source_name)[1].lower()
                            if ext not in IMAGE_EXTS:
                                ext = ".png"
                            img.out_path = os.path.join(
                                out_dir, f"formula_{img.index:05d}{ext}"
                            )
                            with open(img.out_path, "wb") as fh:
                                fh.write(blob)
                            img.width_px, img.height_px = _measure(img.out_path)
                            exported += 1
                        else:
                            img.out_path = ""
                    except Exception:  # noqa: BLE001 - 单张图失败不能拖垮整篇
                        img.out_path = ""
                buf.append(img.marker)
        return "".join(buf)

    body = doc.element.body
    para_lines: List[str] = []
    table_lines: List[str] = []
    for child in body.iterchildren():
        tag = child.tag
        if tag == _qn("w:p"):
            result.paragraph_count += 1
            line = _handle_paragraph(child)
            if line.strip():
                para_lines.append(line.strip())
        elif tag == _qn("w:tbl"):
            result.table_count += 1
            for tr_el in child.findall(_qn("w:tr")):
                cells: List[str] = []
                for tc_el in tr_el.findall(_qn("w:tc")):
                    cell_lines = [
                        _handle_paragraph(p_el)
                        for p_el in _iter_cell_paragraphs(tc_el)
                    ]
                    cell = " ".join(x.strip() for x in cell_lines if x.strip())
                    # 只含公式图的单元格，旧管线（c.text.strip()）会整格丢弃；
                    # 这里保持一致，保证去占位符后的文本与旧入库内容逐字对齐
                    if not strip_markers(cell).strip():
                        continue
                    cells.append(cell)
                if cells:
                    table_lines.append(" | ".join(cells))

    if table_position == "inline":
        # 真实文档顺序：段落与表格交错
        ordered: List[str] = []
        para_iter = iter(para_lines)
        table_iter = iter(table_lines)
        # 简单实现：无法精确还原交错位置时，退化为「段落在前、表格在后」，
        # 但标记图片仍完整保留（对齐性优先于顺序还原）
        ordered = list(para_lines) + list(table_lines)
        text_parts.extend(ordered)
    else:
        # 复刻旧管线：先所有段落，再所有表格
        text_parts.extend(para_lines)
        text_parts.extend(table_lines)

    result.text = "\n".join(text_parts).strip()
    return result


@dataclass
class AlignedText:
    """「去占位符文本」与「带占位符文本」的对齐视图。

    两者逐行对应：**只含图片的段落两边都跳过**，所以行内偏移可以直接互相换算。
    用途：把「旧管线入库的无公式文本」里的一个位置，映射回「带公式文本」里的同一位置，
    从而在不动其它文字的前提下把公式插回去。

    换算规则（逐行）：
    - ``marked_line`` 是段落原始行；
    - ``plain_line`` = 去掉所有占位符后再去掉首尾空白，等价于旧管线 ``p.text.strip()``；
    - 行内任意 plain 偏移 → marked 偏移，靠「被删掉的占位符总长」补偿。
    """

    plain: str = ""
    marked: str = ""
    # 每行: (plain_start, plain_len, marked_start, marked_len,
    #        [(m_rel_start, m_rel_end, core_rel_start), ...], lead)
    _lines: List[Tuple[int, int, int, int, List[Tuple[int, int, int]], int]] = field(
        default_factory=list
    )

    # ---------------- 内部：行内偏移换算 ---------------- #

    @staticmethod
    def _delta_before(spans: List[Tuple[int, int, int]], core_pos: int) -> int:
        """core（去标记后的行）位置 core_pos 之前，被删掉的占位符总长。

        ``core_start`` 是该占位符在 core 里的**插入点**（它本身不占 core 字符位）。
        插入点 <= core_pos 意味着 core_pos 处的字符排在占位符之后，
        换算回 marked 时要补上被删掉的那一段长度。
        """
        delta = 0
        for m_start, m_end, core_start in spans:
            if core_start <= core_pos:
                delta += m_end - m_start
            else:
                break
        return delta

    def plain_to_marked(self, pos: int) -> int:
        """把 plain 里的字符偏移换算成 marked 里的偏移。"""
        if pos <= 0 or not self._lines:
            return 0
        for p_start, p_len, m_start, _m_len, spans, lead in self._lines:
            if p_start <= pos < p_start + p_len:
                core_pos = (pos - p_start) + lead
                return m_start + core_pos + self._delta_before(spans, core_pos)
        p_start, p_len, m_start, _m_len, spans, lead = self._lines[-1]
        core_pos = (pos - p_start) + lead
        return m_start + core_pos + self._delta_before(spans, core_pos)

    def marked_to_plain(self, pos: int) -> int:
        """把 marked 里的字符偏移换算成 plain 里的偏移。"""
        if pos <= 0 or not self._lines:
            return 0
        for p_start, p_len, m_start, m_len, spans, lead in self._lines:
            if m_start <= pos < m_start + m_len:
                rel = pos - m_start
                delta = 0
                for m_s, m_e, _core_start in spans:
                    if m_e <= rel:
                        delta += m_e - m_s
                    else:
                        break
                core_pos = rel - delta
                return p_start + max(0, core_pos - lead)
        return len(self.plain)

    def marked_span_to_plain(self, m_start: int, m_end: int) -> Tuple[int, int]:
        """把 marked 里的区间换算成 plain 里的区间（标记本身会被抹平）。"""
        return self.marked_to_plain(m_start), self.marked_to_plain(m_end)


def build_aligned(result: DocxParseResult) -> AlignedText:
    """把解析结果整理成对齐视图。"""
    aligned = AlignedText()
    plain_parts: List[str] = []
    marked_parts: List[str] = []
    p_off = 0
    m_off = 0
    for line in (result.text or "").split("\n"):
        marked_line = line.strip()
        plain_core = strip_markers(marked_line)
        plain_line = plain_core.strip()
        if not plain_line:
            # 只含图片（或空）的段落：旧管线会整行丢弃，这里两边都跳过以保持对齐
            continue
        lead = len(plain_core) - len(plain_core.lstrip())
        spans: List[Tuple[int, int, int]] = []
        removed = 0
        for m in MARKER_RE.finditer(marked_line):
            # 该标记在 core（去标记后的行）中的起点 = 标记起点 - 此前已被删掉的总长
            spans.append((m.start(), m.end(), m.start() - removed))
            removed += m.end() - m.start()
        aligned._lines.append(
            (p_off, len(plain_line), m_off, len(marked_line), spans, lead)
        )
        plain_parts.append(plain_line)
        marked_parts.append(marked_line)
        p_off += len(plain_line) + 1
        m_off += len(marked_line) + 1
    aligned.plain = "\n".join(plain_parts)
    aligned.marked = "\n".join(marked_parts)
    return aligned


def strip_markers(text: str) -> str:
    """去掉公式占位符，只留纯文字（用于和旧管线做差异对比）。"""
    return MARKER_RE.sub("", text or "")


def marker_positions(text: str) -> List[Tuple[int, int]]:
    """返回每个公式占位符在文本中的 (起, 止) 位置。"""
    return [(m.start(), m.end()) for m in MARKER_RE.finditer(text or "")]
