# -*- coding: utf-8 -*-
"""MinerU 解析器：走 CLI，把 ``*_content_list.json`` 转成 ``ParsedPage``。

为什么不 import mineru 的 python 包：MinerU 装在独立 venv 里（重依赖 torch +
模型权重），后端主环境装不上也不该装。这里一律**走命令行**。

两种 CLI 形态都支持（自动探测，也可以用环境变量强制）：

- **2.x**（``docx/34-OCR与数据采集开源方案`` §4.2 描述的形态）::

      mineru -p <pdf> -o <out_dir> --task doc

  产物里有 ``*_content_list.json`` / ``images/``，字段是页级版面块。

- **4.x**（本机 ``.venv-ocr`` 里装的就是这一代，CLI 变成子命令形态）::

      mineru parse <pdf> -o <out.md> --json --pages all

  产物是带结构标记的 Markdown（``<!-- page N of M -->``），没有 content_list。

两种形态都归一成同一套 ``ParsedBlock`` / ``ParsedPage``，下游不需要知道差别。

字段契约（content_list）按社区常见结构实现并做了容错：

- ``type``：``text`` / ``image`` / ``table`` / ``equation`` …，交给
  ``normalize_block_type()`` 归一；
- ``page_idx``：**0 基**，必须 +1 才是物理页码；同时兼容 1 基的 ``page_no``；
- ``bbox``：4 元素像素坐标；若所有值 ≤ 1.5 视为 0-1 归一化坐标，按页面尺寸换算；
- ``img_path``：相对输出目录的图片路径 → 解析成绝对路径后复制到 ``out_dir/images/``，
  ``ParsedBlock.image_path`` 只存**相对 out_dir 的相对路径**（不落机器绝对路径）；
- ``table_body``：表格的 HTML/Markdown 文本；
- ``text_level``：标题层级。

实测报告（``docx/35-MinerU实测报告-20261020.md``）出来后按真实字段校准，
但这里对缺字段一律容错，不认识的字段忽略即可。

**兼容说明**：本模块同时保留老接口 ``is_available()`` / ``parse_pdf()``，
``services/document_parser.py`` 依赖它们（老接口返回 dict，新接口返回
``ParseResult``，两者互不影响）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.parsers.base import (
    BLOCK_FORMULA,
    BLOCK_TEXT,
    BLOCK_UNKNOWN,
    PDF_KIND_DIGITAL,
    PDF_KIND_SCANNED,
    ParseResult,
    ParsedBlock,
    ParsedPage,
    normalize_block_type,
)

logger = logging.getLogger(__name__)

#: MinerU 可执行文件的查找顺序：环境变量 → PATH。
#: 绝对不许在代码里写死本机路径（``tests/test_path_binding_guard.py`` 会扫源码）。
BIN_ENV_VARS = ("MINERU_BIN", "KAOYAN_OCR_BIN")
#: CLI 形态：auto（先 2.x 再 4.x）/ 2x / 4x
FLAVOR_ENV = "KAOYAN_MINERU_FLAVOR"
#: 单文件超时（秒），可用环境变量覆盖
TIMEOUT_ENV = "KAOYAN_MINERU_TIMEOUT"
#: 4.x CLI 等待服务端解析的秒数
WAIT_ENV = "KAOYAN_MINERU_WAIT"
DEFAULT_WAIT = 600
DEFAULT_TIMEOUT = 1800.0
#: 报错时附带的 stderr 尾部长度
STDERR_TAIL = 2000
#: 4.x Markdown 里的分页结构标记
PAGE_MARK = re.compile(r"<!--\s*page\s+(\d+)\s+of\s+(\d+)\s*-->", re.I)


# --------------------------------------------------------------------------- #
# 可执行文件定位
# --------------------------------------------------------------------------- #
def resolve_mineru_bin() -> str:
    """返回 MinerU 可执行文件路径；找不到返回空串（不抛异常）。"""
    for env in BIN_ENV_VARS:
        value = (os.environ.get(env) or "").strip()
        if value and os.path.isfile(value):
            return value
    return shutil.which("mineru") or ""


def mineru_exe() -> str:
    """兼容老接口。"""
    return resolve_mineru_bin()


def is_available() -> bool:
    """兼容老接口：MinerU 能不能用。"""
    try:
        return bool(resolve_mineru_bin())
    except Exception:  # noqa: BLE001 - 探测失败等价于不可用
        return False


def _timeout() -> float:
    raw = (os.environ.get(TIMEOUT_ENV) or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            logger.warning("%s 不是合法数字，回退默认超时", TIMEOUT_ENV)
    return DEFAULT_TIMEOUT


def _wait_seconds() -> int:
    raw = (os.environ.get(WAIT_ENV) or "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning("%s 不是合法数字，回退默认等待时长", WAIT_ENV)
    return DEFAULT_WAIT


def _flavor() -> str:
    value = (os.environ.get(FLAVOR_ENV) or "auto").strip().lower()
    return value if value in ("auto", "2x", "4x") else "auto"


# --------------------------------------------------------------------------- #
# content_list → ParsedPage（纯函数，便于单测）
# --------------------------------------------------------------------------- #
def _as_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _page_no_of(item: Dict[str, Any]) -> Optional[int]:
    """从 content_list 条目里取 1 基物理页码。

    ``page_idx`` 是 0 基（MinerU 约定）→ +1；``page_no`` 是 1 基 → 直接用；
    ``page`` 语义不明，按 ``page_idx`` 同族（0 基）处理。
    """
    raw = item.get("page_idx")
    if raw is not None:
        num = _as_float(raw)
        if num is not None:
            return int(num) + 1
    raw = item.get("page_no")
    if raw is not None:
        num = _as_float(raw)
        if num is not None:
            return max(1, int(num))
    raw = item.get("page")
    if raw is not None:
        num = _as_float(raw)
        if num is not None:
            return int(num) + 1
    return None


def _collect_page_sizes(content_list: Sequence[Dict[str, Any]]) -> Dict[int, Tuple[float, float]]:
    """收集每页的物理尺寸（用于把归一化 bbox 换算成像素）。

    不同版本把尺寸放在 ``page_size``（list/dict）或 ``width``/``height``，
    也可能整页一条「只有尺寸没有内容」的条目 —— 都认。
    """
    sizes: Dict[int, Tuple[float, float]] = {}
    for item in content_list or []:
        if not isinstance(item, dict):
            continue
        page_no = _page_no_of(item)
        if page_no is None:
            continue
        width = _as_float(item.get("width"))
        height = _as_float(item.get("height"))
        size = item.get("page_size")
        if isinstance(size, dict):
            width = width if width is not None else _as_float(size.get("width"))
            height = height if height is not None else _as_float(size.get("height"))
        elif isinstance(size, (list, tuple)) and len(size) >= 2:
            width = width if width is not None else _as_float(size[0])
            height = height if height is not None else _as_float(size[1])
        if width and height:
            sizes.setdefault(page_no, (float(width), float(height)))
    return sizes


def _bbox_of(
    raw: Any, page_width: float, page_height: float
) -> Optional[Tuple[float, float, float, float]]:
    """把 content_list 的 bbox 转成 (x0,y0,x1,y1) 像素坐标。

    兼容 4 元素 list/tuple、``{"x0":..}`` 形态的 dict。**若所有值 ≤ 1.5**，
    视为 0-1 归一化坐标，按页面宽高换算；页面尺寸缺失时返回 None（宁缺勿错，
    错的 bbox 会污染下游配图绑定）。
    """
    values: List[Optional[float]] = []
    if isinstance(raw, dict):
        keys = ("x0", "y0", "x1", "y1")
        if all(k in raw for k in keys):
            values = [_as_float(raw[k]) for k in keys]
        else:
            alt = ("left", "top", "right", "bottom")
            if all(k in raw for k in alt):
                values = [_as_float(raw[k]) for k in alt]
    elif isinstance(raw, (list, tuple)) and len(raw) >= 4:
        values = [_as_float(raw[i]) for i in range(4)]

    if not values or any(v is None for v in values):
        return None
    vals = [float(v) for v in values if v is not None]
    x0, y0, x1, y1 = vals
    if max(abs(v) for v in vals) <= 1.5:
        if not page_width or not page_height:
            return None
        x0, x1 = x0 * page_width, x1 * page_width
        y0, y1 = y0 * page_height, y1 * page_height
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _unique_name(directory: str, filename: str) -> str:
    """避免同名覆盖：abc.png → abc_1.png。"""
    if not os.path.exists(os.path.join(directory, filename)):
        return filename
    stem, ext = os.path.splitext(filename)
    i = 1
    while os.path.exists(os.path.join(directory, f"{stem}_{i}{ext}")):
        i += 1
    return f"{stem}_{i}{ext}"


def _copy_image(item: Dict[str, Any], out_dir: str, images_dir: str) -> Tuple[str, bool]:
    """把 content_list 引用的图片落到 ``out_dir/images/``。

    :return: (相对 out_dir 的路径, 是否缺失)
    """
    raw = item.get("img_path") or item.get("image_path") or item.get("img")
    if not raw or not isinstance(raw, str):
        return "", False
    rel = raw.replace("\\", "/").strip()
    if not rel:
        return "", False

    if os.path.isabs(rel) or (len(rel) > 1 and rel[1] == ":"):
        src = rel
    else:
        src = os.path.join(out_dir, *rel.split("/"))

    if not os.path.isfile(src):
        return "", True

    os.makedirs(images_dir, exist_ok=True)
    name = _unique_name(images_dir, os.path.basename(src))
    dest = os.path.join(images_dir, name)
    if os.path.abspath(src) != os.path.abspath(dest):
        try:
            shutil.copy2(src, dest)
        except OSError as exc:
            logger.warning("图片复制失败 %s → %s: %s", src, dest, exc)
            return "", True
    return f"images/{name}", False


def content_list_to_pages(
    content_list: List[Dict[str, Any]], out_dir: str
) -> List[ParsedPage]:
    """把 MinerU ``content_list`` 转成 ``ParsedPage`` 列表（纯函数）。

    :param content_list: content_list.json 的原始数组
    :param out_dir: MinerU 输出目录（图片相对于它；也可能已是最终产物目录）
    :return: 按页码升序的 ``ParsedPage``
    """
    out_abs = os.path.abspath(out_dir)
    images_dir = os.path.join(out_abs, "images")
    sizes = _collect_page_sizes(content_list or [])

    pages: Dict[int, ParsedPage] = {}
    for raw_item in content_list or []:
        if not isinstance(raw_item, dict):
            continue
        page_no = _page_no_of(raw_item)
        if page_no is None:
            continue

        width, height = sizes.get(page_no, (0.0, 0.0))
        raw_type = (
            raw_item.get("type")
            or raw_item.get("block_type")
            or raw_item.get("category")
            or raw_item.get("layout_type")
        )
        btype = normalize_block_type(raw_type) if raw_type else BLOCK_UNKNOWN
        bbox = _bbox_of(raw_item.get("bbox"), width, height)

        text = str(raw_item.get("text") or "").strip()
        table_body = str(raw_item.get("table_body") or "").strip()
        if not text and table_body:
            text = table_body
        latex = str(raw_item.get("latex") or "").strip()
        if btype == BLOCK_FORMULA and not latex and text:
            latex = text

        image_rel, image_missing = _copy_image(raw_item, out_abs, images_dir)

        if btype == BLOCK_UNKNOWN and not (text or latex or image_rel):
            continue  # 既没内容也没类型 → 丢弃，避免污染块列表

        page = pages.get(page_no)
        if page is None:
            page = ParsedPage(page_no=page_no, width=width, height=height)
            pages[page_no] = page
        if not page.width and width:
            page.width = width
            page.height = height

        block = ParsedBlock(
            page_no=page_no,
            block_type=btype,
            text=text,
            bbox=bbox,
            block_id=f"p{page_no}-b{len(page.blocks)}",
            latex=latex,
            image_path=image_rel,
            reading_order=len(page.blocks),
        )
        extra: Dict[str, Any] = {}
        if raw_item.get("text_level") is not None:
            extra["text_level"] = raw_item.get("text_level")
        if image_missing:
            extra["image_missing"] = True
        if raw_item.get("img_path"):
            extra["src_img_path"] = str(raw_item.get("img_path"))
        if extra:
            block.extra = extra
        page.blocks.append(block)

    ordered = [pages[k] for k in sorted(pages)]
    for page in ordered:
        parts = []
        for b in page.body_blocks:
            payload = (b.latex or b.text).strip()
            if payload:
                parts.append(payload)
        page.text = "\n".join(parts)
    return ordered


def _pages_from_markdown(markdown: str) -> List[ParsedPage]:
    """4.x 形态：按 ``<!-- page N of M -->`` 结构标记把 Markdown 拆成页。

    没有标记时整篇当第 1 页。
    """
    text = markdown or ""
    matches = list(PAGE_MARK.finditer(text))
    pages: List[ParsedPage] = []
    if not matches:
        stripped = text.strip()
        if not stripped:
            return []
        page = ParsedPage(page_no=1, text=stripped)
        page.blocks.append(
            ParsedBlock(page_no=1, block_type=BLOCK_TEXT, text=stripped, reading_order=0)
        )
        return [page]
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        page_no = int(m.group(1))
        body = text[start:end].strip()
        page = ParsedPage(page_no=page_no, text=body)
        if body:
            page.blocks.append(
                ParsedBlock(
                    page_no=page_no,
                    block_type=BLOCK_TEXT,
                    text=body,
                    reading_order=0,
                )
            )
        pages.append(page)
    return pages


# --------------------------------------------------------------------------- #
# 解析器
# --------------------------------------------------------------------------- #
class MinerUParser:
    """MinerU CLI 适配器。"""

    name = "mineru"

    def __init__(self, bin_path: Optional[str] = None, timeout: Optional[float] = None):
        self._bin_path = bin_path
        self._timeout = timeout

    # -- 可用性 ----------------------------------------------------------- #
    def resolve_bin(self) -> str:
        if self._bin_path:
            return self._bin_path
        return resolve_mineru_bin()

    def available(self) -> bool:
        try:
            return bool(self.resolve_bin())
        except Exception:  # noqa: BLE001 - 探测失败等价于不可用
            return False

    @property
    def timeout(self) -> float:
        return float(self._timeout) if self._timeout else _timeout()

    # -- 命令构造 --------------------------------------------------------- #
    def _cmd_2x(self, binary: str, pdf: str, out_dir: str) -> List[str]:
        return [binary, "-p", os.path.abspath(pdf), "-o", out_dir, "--task", "doc"]

    def _cmd_4x(self, binary: str, pdf: str, out_dir: str) -> List[str]:
        stem = os.path.splitext(os.path.basename(pdf))[0]
        out_md = os.path.join(out_dir, f"{stem}.md")
        return [
            binary,
            "parse",
            os.path.abspath(pdf),
            "-o",
            out_md,
            "--json",
            "--pages",
            "all",
            "--wait",
            str(_wait_seconds()),
        ]

    # -- 主流程 ----------------------------------------------------------- #
    def parse(
        self,
        pdf_path: str,
        *,
        max_pages: Optional[int] = None,
        out_dir: Optional[str] = None,
        page_numbers: Optional[List[int]] = None,
    ) -> ParseResult:
        t0 = time.perf_counter()
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF 不存在: {pdf_path}")
        binary = self.resolve_bin()
        if not binary:
            raise RuntimeError(
                "未找到 MinerU 可执行文件（设置 MINERU_BIN / KAOYAN_OCR_BIN 或把 mineru 放进 PATH）"
            )

        real_out = os.path.abspath(out_dir) if out_dir else tempfile.mkdtemp(prefix="kaoyan_mineru_")
        os.makedirs(real_out, exist_ok=True)

        flavor = _flavor()
        order = ["2x", "4x"] if flavor == "auto" else [flavor]
        succeeded = False
        used_flavor = order[0]
        last_error = ""
        for fl in order:
            cmd = (
                self._cmd_2x(binary, pdf_path, real_out)
                if fl == "2x"
                else self._cmd_4x(binary, pdf_path, real_out)
            )
            logger.info("MinerU 解析(%s): %s", fl, " ".join(cmd))
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"MinerU 超时（>{self.timeout:.0f}s）: {os.path.basename(pdf_path)}"
                ) from exc
            if proc.returncode == 0:
                used_flavor = fl
                succeeded = True
                break
            last_error = f"退出码 {proc.returncode}: " + (proc.stderr or proc.stdout or "")[-STDERR_TAIL:]
            logger.warning("MinerU(%s) 失败: %s", fl, last_error)
        if not succeeded:
            raise RuntimeError(f"MinerU 解析失败（{'/'.join(order)}）: {last_error}")

        content_list_path = _find_content_list(real_out, os.path.basename(pdf_path))
        if content_list_path:
            with open(content_list_path, "r", encoding="utf-8") as fh:
                content_list = json.load(fh)
            if not isinstance(content_list, list):
                raise RuntimeError(f"content_list.json 结构异常（期望数组）: {content_list_path}")
            content_dir = os.path.dirname(content_list_path)
            pages = content_list_to_pages(content_list, content_dir)
            source = "content_list"
        else:
            markdown = _read_markdown(real_out)
            pages = _pages_from_markdown(markdown)
            content_dir = real_out
            source = "markdown"

        pages = _filter_pages(pages, max_pages, page_numbers)

        return ParseResult(
            pages=pages,
            engine=self.name,
            pdf_kind=PDF_KIND_SCANNED,
            source_path=os.path.abspath(pdf_path),
            total_pages=max((p.page_no for p in pages), default=0),
            elapsed_seconds=time.perf_counter() - t0,
            meta={
                "out_dir": real_out,
                "content_dir": content_dir,
                "source": source,
                "flavor": used_flavor,
                "parsed_pages": [p.page_no for p in pages],
                "bin": binary,
            },
        )


def _read_markdown(out_dir: str) -> str:
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if name.lower().endswith(".md"):
                try:
                    with open(os.path.join(root, name), "r", encoding="utf-8", errors="replace") as fh:
                        return fh.read()
                except OSError:
                    continue
    return ""


def _filter_pages(
    pages: List[ParsedPage],
    max_pages: Optional[int],
    page_numbers: Optional[Sequence[int]],
) -> List[ParsedPage]:
    if page_numbers is not None:
        wanted = {int(p) for p in page_numbers}
        return [p for p in pages if p.page_no in wanted]
    if max_pages is not None and int(max_pages) > 0:
        return pages[: int(max_pages)]
    return pages


def _find_content_list(out_dir: str, pdf_name: str) -> str:
    """在 MinerU 输出目录里找 ``*_content_list.json``（优先与 PDF 同名的）。"""
    stem = os.path.splitext(pdf_name)[0] if pdf_name else ""
    candidates = []
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if name.endswith("_content_list.json"):
                candidates.append(os.path.join(root, name))
    if not candidates:
        return ""
    candidates.sort(
        key=lambda p: (
            not os.path.splitext(os.path.basename(p))[0].startswith(stem) if stem else False,
            -os.path.getmtime(p),
        )
    )
    return candidates[0]


# --------------------------------------------------------------------------- #
# 兼容老接口（services/document_parser.py 依赖）
# --------------------------------------------------------------------------- #
def detect_tier(pdf_path: str) -> str:
    """数字版 → ``flash``；扫描版 → ``basic``。

    老接口语义：``basic`` 表示「走 OCR」，
    ``services/document_parser.py`` 据此给文档打 ``ocr_used`` 标记。
    """
    try:
        from services.parsers.pdf_classifier import classify_pdf

        profile = classify_pdf(pdf_path)
        return "flash" if profile.kind == PDF_KIND_DIGITAL else "basic"
    except Exception:  # noqa: BLE001 - 判不出来就按扫描件（更保守）
        return "basic"


def parse_pdf(
    pdf_path: str,
    tier: Optional[str] = None,
    pages: Optional[str] = None,
    output_dir: Optional[str] = None,
    timeout: int = 600,
) -> Dict[str, Any]:
    """兼容老接口的 dict 返回值（``ok`` / ``pages`` / ``tier``）。

    新代码请直接用 :meth:`MinerUParser.parse`（返回 ``ParseResult``）。
    """
    path = os.path.abspath(pdf_path)
    if not os.path.isfile(path):
        return {"ok": False, "error": f"PDF 不存在: {pdf_path}"}
    if not resolve_mineru_bin():
        return {"ok": False, "error": "MinerU 不可用（未配置 MINERU_BIN / KAOYAN_OCR_BIN）"}

    parser = MinerUParser(timeout=float(timeout))
    try:
        result = parser.parse(path, out_dir=output_dir)
    except Exception as exc:  # noqa: BLE001 - 老接口约定用 dict 返回错误
        logger.warning("MinerU 解析失败: %s: %s", type(exc).__name__, exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    chosen_tier = tier or detect_tier(path)
    page_items = [{"page_no": p.page_no, "text": p.join_text()} for p in result.pages]
    return {
        "ok": True,
        "engine": result.engine,
        "tier": chosen_tier,
        "pdf": path,
        "raw_path": result.meta.get("out_dir", ""),
        "pages": page_items,
        "page_count": len(page_items),
        "chars": sum(len(item["text"]) for item in page_items),
        "elapsed": round(result.elapsed_seconds, 1),
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    res = MinerUParser().parse(args.pdf, out_dir=args.out)
    print(
        json.dumps(
            {
                "engine": res.engine,
                "total_pages": res.total_pages,
                "blocks": len(res.blocks),
                "figures": len(res.figure_blocks()),
                "out_dir": res.meta.get("out_dir"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
