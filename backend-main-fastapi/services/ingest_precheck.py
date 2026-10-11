# -*- coding: utf-8 -*-
"""入库前置校验（模块 E6）。

在 ingest_inbox / kb_ingest 入库前对文件做：
  - 格式白名单（ALLOWED_EXTS）
  - 文件尺寸（0 字节 / 超大文件）
  - 图片 / 扫描 PDF 的 DPI 质量（低 DPI 影响 OCR 识别）

不合格文件不进入解析入库，由调用方写入 invalid 清单
（knowledge_base/meta/invalid_inbox.jsonl）并在结果中返回。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

# 与 kb_ingest 保持一致的白名单
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
TEXT_EXTS = {".txt", ".md", ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".csv", ".xlsx", ".xls", ".xlsm"}
ALLOWED_EXTS = IMAGE_EXTS | TEXT_EXTS

# 阈值
MAX_FILE_BYTES = 50 * 1024 * 1024      # 单文件上限 50MB，避免超大文件拖垮解析
MIN_IMAGE_DPI = 100.0                  # 图片/扫描 PDF 最低 DPI（低于此 OCR 质量不可用）
WARN_IMAGE_DPI = 150.0                 # 低于此值给出 warning 建议
DEFAULT_DPI = 72.0                     # 图片无 dpi 元数据时按 72 计


def _image_dpi(file_path: str) -> Tuple[Optional[float], Optional[str]]:
    """读取图片 DPI；无元数据按 72 计并附 note。"""
    try:
        from PIL import Image
        with Image.open(file_path) as im:
            dpi = im.info.get("dpi")
            if isinstance(dpi, tuple) and dpi and dpi[0]:
                return float(dpi[0]), None
            if isinstance(dpi, (int, float)) and dpi:
                return float(dpi), None
            # 常见格式（png/webp/gif）不带 dpi 元数据
            return DEFAULT_DPI, "图片无 dpi 元数据，按 72 估算"
    except Exception as e:  # noqa: BLE001
        return None, f"读取图片 DPI 失败: {type(e).__name__}: {e}"


def _pdf_dpi(file_path: str) -> Tuple[Optional[float], Optional[str]]:
    """估算 PDF 扫描件 DPI：首页内嵌图 像素宽 / (mediabox 宽pt/72)。"""
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        if not reader.pages:
            return None, "PDF 无页面"
        page = reader.pages[0]
        if not hasattr(page, "images") or not page.images:
            return None, "首页无内嵌图像（纯文本/矢量 PDF，无需 DPI 校验）"
        img = page.images[0]
        if img is None or not hasattr(img, "image"):
            return None, "PDF 图像对象不可读"
        img_w = img.image.size[0]  # 像素宽
        mb_w = float(page.mediabox.width)  # pt
        if mb_w <= 0:
            return None, "PDF 页面尺寸异常"
        dpi = img_w / (mb_w / 72.0)
        return round(dpi, 1), None
    except Exception as e:  # noqa: BLE001
        return None, f"读取 PDF DPI 失败: {type(e).__name__}: {e}"


def precheck_file(file_path: str) -> Dict[str, Any]:
    """前置校验单个文件。

    Returns:
        {
          "file": 绝对路径,
          "valid": bool,
          "reasons": [不合格原因...],
          "warnings": [低危提示...],
          "ext": 后缀,
          "size": 字节,
          "dpi": DPI 或 None,
        }
    """
    fp = os.path.abspath(file_path)
    reasons: List[str] = []
    warnings: List[str] = []
    meta: Dict[str, Any] = {"file": fp, "ext": None, "size": None, "dpi": None}

    if not os.path.isfile(fp):
        return {**meta, "valid": False, "reasons": ["文件不存在"], "warnings": []}

    ext = os.path.splitext(fp)[1].lower()
    meta["ext"] = ext
    if ext not in ALLOWED_EXTS:
        return {**meta, "valid": False,
                "reasons": [f"不支持的格式 {ext or '(无后缀)'}（支持: {sorted(ALLOWED_EXTS)}）"],
                "warnings": []}

    size = os.path.getsize(fp)
    meta["size"] = size
    if size <= 0:
        reasons.append("文件大小为 0 字节（空文件）")
    if size > MAX_FILE_BYTES:
        reasons.append(f"文件过大 {size / 1024 / 1024:.1f}MB > 上限 {MAX_FILE_BYTES / 1024 / 1024:.0f}MB")

    dpi: Optional[float] = None
    if ext in IMAGE_EXTS:
        dpi, note = _image_dpi(fp)
        if note:
            warnings.append(note)
        if dpi is None:
            # 图片必须能读取出可用元数据；读不到说明文件损坏或格式异常
            reasons.append("无法读取图片 DPI（文件可能损坏或格式异常）")
        elif dpi < MIN_IMAGE_DPI:
            reasons.append(f"图片 DPI 过低 {dpi:.0f} < {MIN_IMAGE_DPI:.0f}（OCR 质量不可用）")
        elif dpi < WARN_IMAGE_DPI:
            warnings.append(f"图片 DPI 偏低 {dpi:.0f}（建议 ≥ {WARN_IMAGE_DPI:.0f}）")
    elif ext == ".pdf":
        dpi, note = _pdf_dpi(fp)
        if note:
            warnings.append(note)
        if dpi is not None and dpi < MIN_IMAGE_DPI:
            reasons.append(f"PDF 扫描件 DPI 过低 {dpi:.0f} < {MIN_IMAGE_DPI:.0f}（OCR 质量不可用）")
        elif dpi is not None and dpi < WARN_IMAGE_DPI:
            warnings.append(f"PDF 扫描件 DPI 偏低 {dpi:.0f}（建议 ≥ {WARN_IMAGE_DPI:.0f}）")
    meta["dpi"] = dpi

    return {**meta, "valid": len(reasons) == 0, "reasons": reasons, "warnings": warnings}
