# -*- coding: utf-8 -*-
"""DeepSeek-OCR 开源模型扫描件名单 OCR 后端（本机 GPU，4bit 量化）。

背景：DeepSeek-OCR（3.3B，deepseek-ai/DeepSeek-OCR 官方权重）对中文表格
名单识别质量远高于 RapidOCR CPU 版，且直接输出结构化 HTML 表格，可精确
得到「考生编号/姓名/学院/专业/学制/初试/复试/总成绩/备注」逐行数据。
本机 RTX 4060 8GB 显存被系统占用约 5GB，bf16 全量（6.3GB）会触发显存
换页（单页 15+ 分钟无输出）；4bit NF4 量化后参数显存约 2GB，单页实测
约 115s，可批量处理扫描版拟录取名单。

用法：
    from pipeline.dsocr_backend import ocr_pdf_admission_ds
    res = ocr_pdf_admission_ds(blob)   # 返回 {"students","totals","majors","rows"}

模型位置（环境变量 DSOCR_MODEL_DIR，默认）：
    C:/Users/{user}/AppData/Local/DeepSeek-OCR

合规：仅处理公开公示名单；模型按需懒加载；进程复用单例。
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 模型根目录（本地已验证 4bit 加载）
MODEL_DIR = os.environ.get(
    "DSOCR_MODEL_DIR",
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "DeepSeek-OCR"),
)

#: HTML 表格行解析
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
#: 数字清洗（去掉千分位/空格等 OCR 非语义字符）
_NUM = re.compile(r"[^\d.+-]")

_MODEL = None
_TOKENIZER = None
_LOAD_ERR: Optional[str] = None


def _load_model():
    """懒加载 4bit 量化模型（进程内单例；失败只记一次）。"""
    global _MODEL, _TOKENIZER, _LOAD_ERR
    if _MODEL is not None or _LOAD_ERR is not None:
        return _MODEL, _TOKENIZER
    t0 = time.time()
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer, BitsAndBytesConfig

        tok = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )
        model = AutoModel.from_pretrained(
            MODEL_DIR,
            trust_remote_code=True,
            use_safetensors=True,
            quantization_config=bnb,
            device_map="auto",
        )
        model = model.eval()
        _TOKENIZER, _MODEL = tok, model
        logger.info("DeepSeek-OCR 4bit 加载完成 %.1fs（%s）", time.time() - t0, MODEL_DIR)
        return _MODEL, _TOKENIZER
    except Exception as exc:  # noqa: BLE001
        _LOAD_ERR = f"{type(exc).__name__}: {exc}"
        logger.warning("DeepSeek-OCR 加载失败（回退 RapidOCR）: %s", _LOAD_ERR)
        return None, None


def _clean_cell(raw: str) -> str:
    txt = _TAG.sub("", raw or "")
    return txt.strip()


def _to_float(s: str) -> Optional[float]:
    s = _NUM.sub("", (s or "").replace(",", ""))
    if not s or s in ("-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_table_rows(html: str) -> List[List[str]]:
    """把模型输出的 HTML 表格解析成行数据（已有表头时首行被调用方跳过）。"""
    out = []
    for m in _TR.finditer(html):
        cells = [_clean_cell(t) for t in _TD.findall(m.group(1))]
        if len(cells) >= 3 and any(cells):
            out.append(cells)
    return out


def _norm_total(v):
    """按校名习惯规范化「总成绩」单元格为 float 或原始串。"""
    return v


def ocr_pdf_page_to_html(image_path: str, prompt: str = "<image>\nFree OCR. ") -> str:
    """对单页图片执行 DeepSeek-OCR，返回识别文本（通常为 HTML 表格）。"""
    model, tok = _load_model()
    if model is None or tok is None:
        return ""
    import tempfile

    out_dir = os.path.join(tempfile.gettempdir(), "dsocr_runs", str(int(time.time() * 1000)))
    text = model.infer(
        tok,
        prompt=prompt,
        image_file=image_path,
        output_path=out_dir,
        base_size=1024,
        image_size=640,
        crop_mode=True,
        eval_mode=True,
    )
    return text or ""


def ocr_pdf_admission_ds(
    blob: bytes,
    max_pages: int = 200,
    dpi: int = 150,
    prompt: str = "<image>\nFree OCR. ",
    start_page: int = 0,
) -> Optional[dict]:
    """扫描 PDF → {"students","totals","majors","rows"}（DeepSeek-OCR 路径）。

    - pypdfium2 渲染每页位图（临时文件，供模型读取）；
    - DeepSeek-OCR 单页推理输出 HTML 表格；
    - 解析表头（首行出现「姓名|考生编号」即表头）与数据行；
    - 统计：学生数 = 数据行数；总成绩 = 含「总成绩/初试总分/复试成绩」列数字；
      若只有人数无成绩（表格列不匹配）仍返回 students 计数。
    - start_page：从第 N 页（0 基）开始处理，配合外部状态文件断点续跑；
      rec 内记录 page 与清洗后全部 cells，供批量脚本逐行落库。
    """
    import tempfile

    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(blob)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pypdfium2 打开 PDF 失败: %s: %s", type(exc).__name__, exc)
        return None

    n_pages = min(len(doc), max_pages)
    students = 0
    totals: List[float] = []
    rows: List[dict] = []
    unknown = 0
    t0 = time.time()
    tmp_root = tempfile.gettempdir()

    try:
        for pi in range(start_page, n_pages):
            try:
                img = doc[pi].render(scale=dpi / 72.0).to_pil().convert("RGB")
                png_path = os.path.join(tmp_root, f"dsocr_p{pi + 1:03d}.png")
                img.save(png_path, "PNG")
            except Exception as exc:  # noqa: BLE001
                logger.debug("第 %d 页渲染失败: %s", pi + 1, exc)
                continue
            try:
                text = ocr_pdf_page_to_html(png_path, prompt=prompt)
            except Exception as exc:  # noqa: BLE001
                logger.debug("第 %d 页 DeepSeek-OCR 失败: %s", pi + 1, exc)
                continue
            if not text:
                continue
            table_rows = _parse_table_rows(text)
            if not table_rows:
                continue
            # 表头检测：首行含「姓名/考生编号/准考证号/录取学院」
            head_hit = any(
                k in "".join(table_rows[0]) for k in ("姓名", "考生编号", "准考证号", "录取学院", "专业")
            )
            data_rows = table_rows[1:] if head_hit else table_rows
            # 定位成绩列（列名越长越靠前，倒序找）
            col_total_idx = None
            col_retest_idx = None
            col_initial_idx = None
            col_major_idx = None
            if head_hit:
                head = table_rows[0]
                for key in ("总成绩", "初试总分", "复试成绩", "初试成绩", "分数"):
                    for ci, cell in enumerate(head):
                        if key in cell:
                            col_total_idx = ci
                            break
                    if col_total_idx is not None:
                        break
                for key in ("复试成绩", "复试"):
                    for ci, cell in enumerate(head):
                        if key in cell and ci != col_total_idx:
                            col_retest_idx = ci
                            break
                    if col_retest_idx is not None:
                        break
                for key in ("初试总分", "初试成绩", "初试", "政治理论"):
                    for ci, cell in enumerate(head):
                        if key in cell and ci not in (col_total_idx, col_retest_idx):
                            col_initial_idx = ci
                            break
                    if col_initial_idx is not None:
                        break
                for key in ("录取专业", "专业", "学院", "院系", "方向", "领域"):
                    for ci, cell in enumerate(head):
                        if key in cell:
                            col_major_idx = ci
                            break
                    if col_major_idx is not None:
                        break
            for c in data_rows:
                name = c[1] if len(c) > 1 else (c[0] if c else "")
                if len(name.strip()) < 2 or not re.match(r"^[\u4e00-\u9fff·]{2,12}$", name.strip()):
                    # 姓名列不像是中文名 → 可能表头残留/条带行，跳过但计数为 unknown
                    if any(re.match(r"^[\u4e00-\u9fff·]{2,12}$", cc.strip()) for cc in c):
                        pass  # 姓名在非第 1 列，仍按数据行处理
                    else:
                        unknown += 1
                        continue
                students += 1
                rec: dict[str, object] = {"name": name.strip(), "page": pi + 1, "cells": [cc.strip() for cc in c]}
                if len(c) > 0:
                    rec["exam_no"] = c[0].strip()
                if col_total_idx is not None and col_total_idx < len(c):
                    val = _to_float(c[col_total_idx])
                    if val is not None:
                        if 150 <= val <= 500:
                            totals.append(val)
                        rec["total"] = val
                if col_initial_idx is not None and col_initial_idx < len(c):
                    val = _to_float(c[col_initial_idx])
                    if val is not None and 150 <= val <= 500:
                        rec["initial"] = val
                if col_retest_idx is not None and col_retest_idx < len(c):
                    val = _to_float(c[col_retest_idx])
                    if val is not None and 0 <= val <= 500:
                        rec["retest"] = val
                if col_major_idx is not None and col_major_idx < len(c) and c[col_major_idx].strip():
                    rec["major"] = c[col_major_idx].strip()
                rows.append(rec)
            if pi % 10 == 9:
                logger.info("DeepSeek-OCR 进度 %d/%d 页, %d 人, %.0fs",
                            pi + 1, n_pages, students, time.time() - t0)
    finally:
        doc.close()

    if students == 0:
        return None
    logger.info("DeepSeek-OCR 名单完成: %d 页, %d 人, 成绩 %d 条, %.0fs",
                n_pages, students, len(totals), time.time() - t0)
    return {"students": students, "totals": totals, "majors": {}, "rows": rows}


# --------------------------------------------------------------------------- #
# 兼容入口：给 pdf_scan_ocr.py / notice_admission_crawler.parse_pdf 复用
# --------------------------------------------------------------------------- #
def ocr_pdf_admission(blob: bytes, **kwargs) -> Optional[dict]:
    """DeepSeek-OCR 优先；模型不可用时返回 None（由调用方回退 RapidOCR）。"""
    model, _ = _load_model()
    if model is None:
        return None
    return ocr_pdf_admission_ds(blob, **kwargs)