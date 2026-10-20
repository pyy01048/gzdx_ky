"""文档解析层的公共数据结构与解析器注册表。

这一层是所有 PDF/DOCX 解析器的唯一出口：不管底层是 PyMuPDF 文字层、MinerU、
PP-StructureV3 还是 RapidOCR，最终都必须归一化成 ``ParsedBlock`` / ``ParsedPage``，
再交给 ``services/ingest_pipeline.py`` 入库。

设计约束
--------
1. **不猜引擎**：每个块必须带 ``block_type``，未知类型统一落到 ``text``。
2. **页码从 1 开始**：全链路（chunks.page_start/page_end、题目配图）都用物理页码，
   这里不做 0 基/1 基转换，避免下游再减一次。
3. **bbox 用 (x0, y0, x1, y1)，单位为页内像素（渲染 DPI 下的坐标）**。
   如果要跨 PDF 比较，必须先统一 DPI，本层不负责换算。
4. **图片只存相对路径**：完整路径由配置的 storage 根目录拼出来，
   避免把机器绝对路径写进数据库（``test_path_binding_guard`` 会扫描这一点）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

# ---------------------------------------------------------------------------
# 枚举常量（用字符串而不是 Enum，方便直接 JSON / SQL 存）
# ---------------------------------------------------------------------------

#: PDF 类型
PDF_KIND_DIGITAL = "digital"  #: 有完整文字层，直接取文字，不 OCR
PDF_KIND_SCANNED = "scanned"  #: 纯扫描件，必须 OCR
PDF_KIND_HYBRID = "hybrid"  #: 混合，逐页判断

PDF_KINDS = frozenset({PDF_KIND_DIGITAL, PDF_KIND_SCANNED, PDF_KIND_HYBRID})

#: 块类型（对齐 MinerU content_list / PP-DocLayoutV3 的标签体系）
BLOCK_TEXT = "text"
BLOCK_TITLE = "title"
BLOCK_TABLE = "table"
BLOCK_FIGURE = "figure"
BLOCK_FORMULA = "formula"
BLOCK_LIST = "list"
BLOCK_HEADER = "header"
BLOCK_FOOTER = "footer"
BLOCK_PAGE_NO = "page_no"
BLOCK_UNKNOWN = "unknown"

#: 会被 ``ingest_pipeline`` 丢弃的块类型（页眉页脚页码不参与切题与检索）
DROP_BLOCK_TYPES = frozenset({BLOCK_HEADER, BLOCK_FOOTER, BLOCK_PAGE_NO, BLOCK_UNKNOWN})

BLOCK_TYPES = frozenset(
    {
        BLOCK_TEXT,
        BLOCK_TITLE,
        BLOCK_TABLE,
        BLOCK_FIGURE,
        BLOCK_FORMULA,
        BLOCK_LIST,
        BLOCK_HEADER,
        BLOCK_FOOTER,
        BLOCK_PAGE_NO,
        BLOCK_UNKNOWN,
    }
)

#: 章节/正文里视为「正文」的块类型（切题时按阅读顺序拼接）
BODY_BLOCK_TYPES = frozenset({BLOCK_TEXT, BLOCK_LIST, BLOCK_FORMULA})


def normalize_block_type(raw: Optional[str]) -> str:
    """把各引擎的原始标签归一到本层的 block_type。"""
    if not raw:
        return BLOCK_UNKNOWN
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        # MinerU content_list type
        "text": BLOCK_TEXT,
        "paragraph": BLOCK_TEXT,
        "plain_text": BLOCK_TEXT,
        "title": BLOCK_TITLE,
        "heading": BLOCK_TITLE,
        "table": BLOCK_TABLE,
        "image": BLOCK_FIGURE,
        "figure": BLOCK_FIGURE,
        "picture": BLOCK_FIGURE,
        "chart": BLOCK_FIGURE,
        "equation": BLOCK_FORMULA,
        "formula": BLOCK_FORMULA,
        "interline_equation": BLOCK_FORMULA,
        "inline_equation": BLOCK_FORMULA,
        "list": BLOCK_LIST,
        "list_item": BLOCK_LIST,
        "header": BLOCK_HEADER,
        "page_header": BLOCK_HEADER,
        "footer": BLOCK_FOOTER,
        "page_footer": BLOCK_FOOTER,
        "page_number": BLOCK_PAGE_NO,
        "page_no": BLOCK_PAGE_NO,
        "footnote": BLOCK_TEXT,
        "caption": BLOCK_TEXT,
        "reference": BLOCK_TEXT,
        "abstract": BLOCK_TEXT,
        "content": BLOCK_TEXT,
    }
    return mapping.get(key, BLOCK_UNKNOWN)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class ParsedBlock:
    """一个版面块。题干、选项、图片、公式都落在这里。"""

    page_no: int
    block_type: str = BLOCK_TEXT
    text: str = ""
    bbox: Optional[Tuple[float, float, float, float]] = None
    block_id: str = ""
    latex: str = ""
    image_path: str = ""
    reading_order: int = 0
    confidence: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.block_type = normalize_block_type(self.block_type)
        if self.page_no is None or int(self.page_no) < 1:
            raise ValueError(f"page_no 必须从 1 开始，收到 {self.page_no!r}")
        self.page_no = int(self.page_no)

    @property
    def is_dropped(self) -> bool:
        return self.block_type in DROP_BLOCK_TYPES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_no": self.page_no,
            "block_type": self.block_type,
            "text": self.text,
            "bbox": list(self.bbox) if self.bbox else None,
            "block_id": self.block_id,
            "latex": self.latex,
            "image_path": self.image_path,
            "reading_order": self.reading_order,
            "confidence": self.confidence,
            "extra": self.extra or {},
        }


@dataclass
class ParsedPage:
    """一页的解析结果：页级文字 + 块列表。"""

    page_no: int
    width: float = 0.0
    height: float = 0.0
    text: str = ""
    layout_json: Optional[Dict[str, Any]] = None
    image_path: str = ""
    ocr_engine: str = ""
    ocr_confidence: Optional[float] = None
    blocks: List[ParsedBlock] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.page_no is None or int(self.page_no) < 1:
            raise ValueError(f"page_no 必须从 1 开始，收到 {self.page_no!r}")
        self.page_no = int(self.page_no)

    @property
    def body_blocks(self) -> List[ParsedBlock]:
        """按阅读顺序返回参与切题的正文块。"""
        rows = [b for b in self.blocks if not b.is_dropped]
        return sorted(rows, key=lambda b: (b.reading_order, b.bbox[1] if b.bbox else 0.0))

    def join_text(self) -> str:
        """把块按阅读顺序拼成该页正文；``text`` 为空时用它兜底。"""
        if self.text.strip():
            return self.text
        parts: List[str] = []
        for b in self.body_blocks:
            payload = b.latex or b.text
            if payload.strip():
                parts.append(payload.strip())
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_no": self.page_no,
            "width": self.width,
            "height": self.height,
            "text": self.text,
            "layout_json": self.layout_json,
            "image_path": self.image_path,
            "ocr_engine": self.ocr_engine,
            "ocr_confidence": self.ocr_confidence,
            "blocks": [b.to_dict() for b in self.blocks],
        }


@dataclass
class ParseResult:
    """一次完整解析的产物。"""

    pages: List[ParsedPage] = field(default_factory=list)
    engine: str = ""
    pdf_kind: str = PDF_KIND_DIGITAL
    source_path: str = ""
    total_pages: int = 0
    elapsed_seconds: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.pdf_kind not in PDF_KINDS:
            self.pdf_kind = PDF_KIND_DIGITAL
        if not self.total_pages:
            self.total_pages = len(self.pages)

    @property
    def blocks(self) -> List[ParsedBlock]:
        out: List[ParsedBlock] = []
        for page in self.pages:
            out.extend(page.blocks)
        return out

    @property
    def text(self) -> str:
        return "\n".join(p.join_text() for p in self.pages if p.join_text().strip())

    def figure_blocks(self) -> List[ParsedBlock]:
        return [b for b in self.blocks if b.block_type == BLOCK_FIGURE]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "pdf_kind": self.pdf_kind,
            "source_path": self.source_path,
            "total_pages": self.total_pages,
            "elapsed_seconds": self.elapsed_seconds,
            "meta": self.meta,
            "pages": [p.to_dict() for p in self.pages],
        }


# ---------------------------------------------------------------------------
# 解析器协议与注册表
# ---------------------------------------------------------------------------


@runtime_checkable
class DocumentParserProtocol(Protocol):
    """所有解析器必须实现的最小接口。"""

    name: str

    def available(self) -> bool:  # pragma: no cover - 协议声明
        """依赖是否就绪（例如 CLI 是否在 PATH 里、模型是否下载完）。"""
        ...

    def parse(  # pragma: no cover - 协议声明
        self,
        pdf_path: str,
        *,
        max_pages: Optional[int] = None,
        out_dir: Optional[str] = None,
        page_numbers: Optional[List[int]] = None,
    ) -> ParseResult:
        """解析 PDF，返回归一化结果。"""
        ...


ParserFactory = Callable[[], Any]

_PARSER_REGISTRY: Dict[str, ParserFactory] = {}


def register_parser(name: str, factory: ParserFactory) -> None:
    """注册解析器工厂（延迟实例化，避免 import 时就加载模型）。"""
    if not name:
        raise ValueError("parser name 不能为空")
    _PARSER_REGISTRY[name] = factory


def get_parser(name: str) -> Any:
    """按名取解析器实例；未注册抛 KeyError 并列出可用项。"""
    factory = _PARSER_REGISTRY.get(name)
    if factory is None:
        raise KeyError(f"未注册的解析器 {name!r}，可用：{sorted(_PARSER_REGISTRY)}")
    return factory()


def registered_parsers() -> List[str]:
    return sorted(_PARSER_REGISTRY)


def available_parsers() -> List[str]:
    """返回当前环境真正可用的解析器名（依赖缺失的会被跳过）。"""
    out: List[str] = []
    for name in registered_parsers():
        try:
            if get_parser(name).available():
                out.append(name)
        except Exception:  # noqa: BLE001 - 探测失败等价于不可用
            continue
    return out


def clear_registry() -> None:
    """仅供测试使用。"""
    _PARSER_REGISTRY.clear()
