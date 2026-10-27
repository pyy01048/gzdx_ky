# -*- coding: utf-8 -*-
"""扫描版 PDF 名单的 OCR 兜底（pypdfium2 渲染 + RapidOCR 识别 + 名单重构）。

背景：部分高校（如华南理工）把拟录取/复试名单做成「无文字层扫描 PDF」，
pdfplumber 抽不到任何文本/表格。本模块作为 notice_admission_crawler.parse_pdf
的文字层失败兜底：

  1. pypdfium2 把每页渲染成位图（默认 150dpi，CPU 实测约 30-50s/页）；
  2. RapidOCR（services.ocr_service._get_engine，纯本地 ONNX）识别文本块，
     每个块带 (box, text, score)，box 提供坐标；
  3. 根据名单表固定版式重构数据行：
       表头（第一页）定位「姓名」「初试|总成绩」两列 x 坐标；
       之后逐页按「姓名列出现中文名」为行锚点，在行带内取成绩列数字；
  4. 输出与 _extract_table 同构的 {"students", "totals", "majors"}，
     直接复用深度采集器的质量门与入库逻辑。

依赖：pypdfium2（渲染）、rapidocr-onnxruntime（识别），均已含于项目 .venv。
合规：仅处理公开公示名单；逐页顺序识别按批次释放；允许中途页失败继续。
"""

from __future__ import annotations

import logging
import re
import statistics
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

#: OCR 行内数字清洗：RapidOCR 常把 "87. 52" 识别成带空格数字
_NUM_CLEAN = re.compile(r"\s+")
#: 姓名列以外的排他词（表头/脚注/合计行，不算数据行）
_NAME_NO = re.compile(r"姓名|考生编号|准考证号|序号|注[:：]|备注|合计|平均|小计|全日制|非全日制|报考|院系|专业|方向|学习方式")
#: 姓名单元格形态：纯中文 2-4 字（名单数据行姓名列；学院/专业列含数字代码，天然排除）
_NAME_CELL = re.compile(r"^[\u4e00-\u9fff]{2,4}$")
#: 成绩列表头优先序：初试总分 > 总成绩 > 初试成绩 > 复试成绩 > 成绩
_SCORE_HEAD_PRIOR = ["初试总分", "初试", "总成绩", "初试成绩", "复试", "成绩"]


def _blocks_from_ocr(result) -> List[Tuple[float, float, str]]:
    """把 RapidOCR 原始返回 (box, text, score) 转成 (y_center, x_center, text)。"""
    out = []
    for box, text, _score in result or []:
        txt = str(text or "").strip()
        if not txt:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append((sum(ys) / len(ys), sum(xs) / len(xs), txt))
    return out


def _cluster_x(xs, tol):
    """一维贪心聚类：相邻差 ≤ tol 归同簇。返回簇列表（每簇为坐标列表）。"""
    if not xs:
        return []
    xs = sorted(xs)
    clusters = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] <= tol:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return clusters


def _detect_columns(page_blocks, dpi: int):
    """定位姓名列与成绩列 x 坐标。

    姓名列不能用表头「姓名」的 x（合并单元格居中和数据列不对齐），
    改为统计整页「纯中文姓名单元格」的 x 聚类，取块数最多的簇中心；
    成绩列按表头词优先级取表头块 x。
    """
    x_score, score_kind = None, None
    for kw in _SCORE_HEAD_PRIOR:
        for _y, x, txt in page_blocks:
            if txt == kw:
                x_score, score_kind = x, kw
                break
        if x_score is not None:
            break

    name_xs = [x for _y, x, txt in page_blocks if _NAME_CELL.match(txt) and not _NAME_NO.search(txt)]
    clusters = _cluster_x(name_xs, dpi * 0.35)
    if not clusters:
        return None, x_score, score_kind
    best = max(clusters, key=len)
    x_name = sum(best) / len(best)
    return x_name, x_score, score_kind


def ocr_pdf_admission(
    blob: bytes,
    dpi: int = 150,
    max_pages: int = 200,
    page_lookahead: int = 3,
) -> Optional[dict]:
    """扫描 PDF → {"students", "totals", "majors"}；失败/无名单返回 None。

    - 前 page_lookahead 页用于定位姓名列/成绩列；
    - 逐页累加名单行：姓名列中文名即一个学生，行带内取成绩列数字；
    - 全程不抛异常：任何一页失败只记日志继续。
    """
    import io

    import pypdfium2 as pdfium

    from services.ocr_service import _get_engine, _reserve_project_utils

    _reserve_project_utils()
    try:
        engine = _get_engine("cpu")
    except Exception as e:  # noqa: BLE001
        logger.warning("OCR 引擎不可用（跳过扫描件兜底）: %s: %s", type(e).__name__, e)
        return None

    try:
        doc = pdfium.PdfDocument(blob)
    except Exception as e:  # noqa: BLE001
        logger.warning("pypdfium2 打开 PDF 失败: %s: %s", type(e).__name__, e)
        return None

    n_pages = min(len(doc), max_pages)
    x_name = x_score = score_kind = None
    students = 0
    totals: List[float] = []
    unknown_rows = 0
    t0 = time.time()
    try:
        for pi in range(n_pages):
            try:
                img = doc[pi].render(scale=dpi / 72.0).to_pil().convert("RGB")
            except Exception as e:  # noqa: BLE001
                logger.debug("第 %d 页渲染失败: %s", pi + 1, e)
                continue
            try:
                # RapidOCR 只接受 str/numpy.ndarray/bytes/Path，PIL 需转 ndarray
                import numpy as np

                result, _ = engine(np.asarray(img))
            except Exception as e:  # noqa: BLE001
                logger.debug("第 %d 页 OCR 失败: %s", pi + 1, e)
                continue
            blocks = _blocks_from_ocr(result)
            if not blocks:
                continue
            blocks.sort(key=lambda b: (b[0], b[1]))

            if x_name is None:
                x_name, x_score, score_kind = _detect_columns(blocks, dpi)
                if x_name is not None:
                    logger.info("扫描名单列定位: 姓名x=%.0f 成绩x=%.0f(%s)（第 %d 页）",
                                x_name, x_score or 0, score_kind or "-", pi + 1)

            # 行锚点：姓名单元格（纯中文 2-4 字）出现在姓名列附近 → 一个学生
            name_tol = dpi * 0.30
            for y, x, txt in blocks:
                if x_name is not None and abs(x - x_name) > name_tol:
                    continue
                if _NAME_NO.search(txt):
                    continue
                if not _NAME_CELL.match(txt):
                    continue
                # 命中一行：姓名（txt）即行锚，拆成绩列数字
                students += 1
                if x_score is not None:
                    score_tol = dpi * 0.18
                    for ny, nx, ntxt in blocks:
                        if abs(ny - y) > dpi * 0.16:
                            continue
                        if abs(nx - x_score) > score_tol:
                            continue
                        num = _NUM_CLEAN.sub("", ntxt)
                        if not re.fullmatch(r"\d+(?:\.\d+)?", num):
                            continue
                        try:
                            val = float(num)
                        except ValueError:
                            continue
                        if 100 <= val <= 700:
                            totals.append(val)
                break  # 一个块只认一行，避免同一行多块重复计数
            if pi % 10 == 0 and pi:
                logger.info("扫描 OCR 进度 %d/%d 页, 已识别 %d 人, 耗时 %.0fs",
                            pi + 1, n_pages, students, time.time() - t0)
    finally:
        doc.close()

    if students == 0:
        return None
    # 与 _extract_table 同构：中位数不在硕士总分区间 → 只记人数不记均分
    if totals and not (150 <= statistics.median(totals) <= 500):
        totals = []
    logger.info("扫描名单 OCR 完成: %d 页, %d 人, 成绩 %d 条, 耗时 %.0fs",
                n_pages, students, len(totals), time.time() - t0)
    return {"students": students, "totals": totals, "majors": {}}