"""文档解析服务。

支持 PDF / DOCX / PPT / PPTX / TXT 的文本提取；
**扫描版真题 PDF（无文本层）自动渲染页面走本地 OCR**。

对考研场景的意义：贵大 834 真题、空白版真题卷大多是扫描件，
没有文本层，直接上传进知识库会是一堆空内容。本解析器会自动识别
这类文件并逐页渲染 OCR，识别结果带上 `--- 第N页(OCR) ---` 标记，
便于追溯哪些内容来自 OCR（OCR 有噪声，检索时要区别对待）。
"""

import logging
import os
import re
import tempfile
from typing import Optional


_MINERU_AVAILABLE = None


def _mineru_enabled() -> bool:
    """环境变量可关闭 MinerU；默认 auto（装了就用）。"""
    global _MINERU_AVAILABLE
    if os.environ.get("USE_MINERU", "auto").lower() in ("0", "false", "no", "off"):
        return False
    if _MINERU_AVAILABLE is None:
        try:
            from services.parsers.mineru_parser import is_available

            _MINERU_AVAILABLE = bool(is_available())
        except Exception:
            _MINERU_AVAILABLE = False
    return bool(_MINERU_AVAILABLE)


class DocumentParser:
    """本地文档解析器，纯本地运行，数据不出本机。"""

    # 支持的扩展名 -> 文件类型
    EXT_MAP = {
        ".pdf": "pdf",
        ".docx": "docx",
        ".doc": "doc",
        ".pptx": "pptx",
        ".ppt": "ppt",
        ".txt": "txt",
        ".md": "txt",
    }

    def __init__(self, ocr_device: str = "cpu"):
        self.ocr_device = ocr_device
        self._ocr = None
        # 本次解析是否真的用了 OCR（扫描版真题标记）
        self.used_ocr = False

    def _get_ocr(self):
        """懒加载 OCR 服务。"""
        if self._ocr is None:
            from services.ocr_service import OCRService

            self._ocr = OCRService(device=self.ocr_device)
        return self._ocr

    @staticmethod
    def file_type(file_name: str) -> str:
        ext = os.path.splitext(file_name)[1].lower()
        return DocumentParser.EXT_MAP.get(ext, "other")

    def parse(self, file_path: str) -> str:
        """解析文档为纯文本。"""
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".pdf":
                if _mineru_enabled():
                    try:
                        from services.parsers.mineru_parser import parse_pdf

                        max_pages = int(os.environ.get("MINERU_MAX_PAGES", "300"))
                        result = parse_pdf(
                            file_path,
                            pages=f"1-{max_pages}" if max_pages > 0 else None,
                        )
                        if result.get("ok") and result.get("pages"):
                            self.used_ocr = result.get("tier") == "basic"
                            parts = []
                            for page in result["pages"]:
                                parts.append(f"--- 第{page['page_no']}页 ({result['tier']}) ---")
                                parts.append(page.get("text") or "")
                            return "\n".join(parts).strip()
                    except Exception as exc:  # noqa: BLE001 - 失败必须回退
                        logging.getLogger(__name__).warning(
                            "MinerU 解析失败，回退旧 PDF 管线: %s", str(exc)[:200]
                        )
                return self._parse_pdf(file_path)
            if ext in (".docx",):
                return self._parse_docx(file_path)
            if ext in (".pptx", ".ppt"):
                return self._parse_pptx(file_path)
            if ext in (".txt", ".md"):
                return self._parse_text(file_path)
            if ext == ".doc":
                return self._parse_doc_legacy(file_path)
        except Exception as e:
            return f"[解析失败 {ext}: {e}]"

        return ""

    # ------------------------------------------------------------------ #
    # TXT
    # ------------------------------------------------------------------ #
    def _parse_text(self, file_path: str) -> str:
        for enc in ("utf-8", "gbk", "gb18030", "utf-16"):
            try:
                with open(file_path, "r", encoding=enc, errors="ignore") as f:
                    return f.read()
            except Exception:
                continue
        return ""

    # ------------------------------------------------------------------ #
    # DOCX
    # ------------------------------------------------------------------ #
    def _parse_docx(self, file_path: str) -> str:
        import docx

        d = docx.Document(file_path)
        parts = []
        for p in d.paragraphs:
            if p.text.strip():
                parts.append(p.text.strip())
        for table in d.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # PPT / PPTX
    # ------------------------------------------------------------------ #
    def _parse_pptx(self, file_path: str) -> str:
        from pptx import Presentation

        prs = Presentation(file_path)
        parts = []
        for idx, slide in enumerate(prs.slides, start=1):
            slide_texts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        t = "".join(run.text for run in para.runs).strip()
                        if t:
                            slide_texts.append(t)
                if shape.shape_type == 13 and hasattr(shape, "image"):  # picture
                    try:
                        image = shape.image
                        slide_texts.append(f"[图片:{image.filename or 'image'}]")
                    except Exception as _exc:  # noqa: BLE001
                        # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
                        # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
                        logging.getLogger(__name__).warning(
                            '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
                        )
            if slide_texts:
                parts.append(f"--- 第{idx}页 ---")
                parts.extend(slide_texts)
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # DOC（旧版二进制，仅尝试提取可读文本）
    # ------------------------------------------------------------------ #
    def _parse_doc_legacy(self, file_path: str) -> str:
        with open(file_path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8", errors="ignore")
        text = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9\s.,;:!?，。；：！？、（）()【】\[\]%]+", "", text)
        return text.strip()

    # ------------------------------------------------------------------ #
    # PDF（先文本层，后 OCR 兜底）
    # ------------------------------------------------------------------ #
    def _parse_pdf(self, file_path: str, use_ocr_fallback: bool = True) -> str:
        text = self._extract_pdf_text(file_path)

        # 有文本层：直接返回（限制长度，避免超大文档）
        # 注意：部分 PDF 文本层为无效乱码（压缩流按文本解码），须识别并转 OCR
        if text and self._is_valid_text(text) and len(text.strip()) > 50:
            return text[:200000]

        # 无文本层 / 文本过少 / 文本层为乱码：扫描版，走 OCR 渲染页面
        if use_ocr_fallback:
            return self._ocr_pdf(file_path)

        return text

    @staticmethod
    def _is_valid_text(text: str) -> bool:
        """判断提取出的文本层是否可用（过滤二进制乱码）。

        乱码特征：控制字符 / 不可打印字符占比过高，或可读中英文占比过低。
        """
        if not text:
            return False
        total = len(text)
        if total == 0:
            return False
        bad = 0
        readable = 0
        for ch in text:
            code = ord(ch)
            # 控制字符（除常见空白）
            if (code < 32 and ch not in ("\n", "\t", "\r")) or code == 0x7F:
                bad += 1
            elif 0x80 <= code <= 0x9F:  # C1 控制区
                bad += 1
            if "\u4e00" <= ch <= "\u9fff" or "a" <= ch.lower() <= "z" or "0" <= ch <= "9":
                readable += 1
        bad_ratio = bad / total
        readable_ratio = readable / total
        return bad_ratio < 0.15 and readable_ratio > 0.2

    def _extract_pdf_text(self, file_path: str) -> str:
        """多引擎提取 PDF 文本层。"""
        parts = []
        # 引擎1：pypdf
        try:
            from pypdf import PdfReader

            reader = PdfReader(file_path)
            for page in reader.pages:
                try:
                    t = page.extract_text() or ""
                    if t.strip():
                        parts.append(t)
                except Exception:
                    continue
            if parts:
                return "\n".join(parts)
        except Exception as _exc:  # noqa: BLE001
            # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
            # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
            logging.getLogger(__name__).warning(
                '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
            )

        # 引擎2：pdfplumber
        try:
            import pdfplumber

            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    if t.strip():
                        parts.append(t)
            return "\n".join(parts)
        except Exception:
            return ""

    def _ocr_pdf(self, file_path: str, max_pages: int = 30) -> str:
        """渲染 PDF 页面为图片并 OCR（扫描版真题）。

        成功后把 self.used_ocr 置为 True，调用方可据此在 documents.ocr_used
        上打标记 —— 扫描件 OCR 文本有识别噪声，RAG 引用时需要区别对待。
        """
        import pypdfium2 as pdfium

        ocr = self._get_ocr()
        pdf = None
        try:
            pdf = pdfium.PdfDocument(file_path)
            n_pages = min(len(pdf), max_pages)
            parts = []
            for i in range(n_pages):
                page = pdf[i]
                try:
                    bitmap = page.render(scale=2.0)
                    img = bitmap.to_pil()
                    # 用 mkstemp 先拿到路径并立即关闭 fd，避免 Windows 下
                    # NamedTemporaryFile 独占句柄导致 PIL 写入时 Permission denied
                    fd, tmp_path = tempfile.mkstemp(suffix=".png")
                    os.close(fd)
                    try:
                        img.save(tmp_path)
                        text = ocr.recognize(tmp_path)
                        if text.strip():
                            parts.append(f"--- 第{i+1}页(OCR) ---")
                            parts.append(text)
                    finally:
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                finally:
                    # 及时释放每页位图，避免句柄/内存堆积
                    try:
                        page.close()
                    except Exception:  # noqa: BLE001
                        pass
            if parts:
                self.used_ocr = True
            return "\n".join(parts)
        except Exception as e:
            return f"[扫描版 PDF OCR 失败: {e}]"
        finally:
            # 关键：无论如何都要关闭 pypdfium 文档，否则 PDFium 文件句柄泄漏，
            # 后续同文件再次打开会报 "PDFium: File access error" -> 0 字符
            if pdf is not None:
                try:
                    pdf.close()
                except Exception:  # noqa: BLE001
                    pass
