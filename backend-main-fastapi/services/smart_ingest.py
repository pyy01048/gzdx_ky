# -*- coding: utf-8 -*-
"""智能入库管线（2026-10-12 · 面向考研大学教材/讲义/真题/课件/扫描件）。

设计目标（对照参考方案，结合本项目**已有**能力，不重复造轮子）：

    图像预处理 → 版面分区 → 分流识别 → 文本清洗 → 结构化抽取 → 校验 → 入库

复用既有服务（不重写）：
  * `services.ocr_router`        三层 OCR 路由（local-gpu / paddleocr / rapidocr / chineseocr-lite）
  * `services.ocr_layout`        版面切题（blocks + 坐标 → 题号切分）
  * `services.formula_service`   公式区检测 + VLM → LaTeX + 编译校验
  * `services.circuit_analysis`  电路图 VLM 读图（qwen2.5vl:7b）
  * `services.kb_service`        学科/内容类型分类
  * `services.embedding_service` 本地 BGE 向量（去重校验）

本模块新增的部分（项目原缺口）：
  1. **图像预处理**：纠偏 / 去黑边 / 去噪 / 轻量放大 —— 原项目没有
  2. **编排**：把上面的 OCR/版面/公式/VLM 串成一条可执行管线 —— 原项目各服务孤立
  3. **结构化抽取**：教材名 / 作者 / 章节 / 小节 / 内容类型 / 知识点 —— 原项目只存裸正文
  4. **入库前校验**：乱码比例 / 长度 / 向量去重 —— 原项目无拦截，脏数据直接入库

红线：纯新增模块，不修改既有服务行为；所有既有调用点保持不变。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from collections import Counter
from services.dbapi_compat import wrap_conn
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, or_

from services import kp_extract
from services import chunk_classifier
from services.doc_naming import apply_display_name

# --- 文件格式 → doc_format 枚举归一（修复 PG 迁移 schema 漂移）---
# 历史代码写的是 Document.file_type，但 PG `documents` 表与 ORM `Document` 模型
# 都没有该列（正确列是 source_format，类型是 doc_format ENUM）。直接写 file_type
# 会在全量入库时 100% 抛 TypeError。这里把扩展名归一为合法枚举值，超出枚举的
# 图片/矢量扩展名（jpeg/bmp/webp/tif/tiff…）兜底回 'other'，避免违反枚举约束。
_DOC_FORMAT_VALUES = {
    "pdf", "txt", "doc", "docx", "md", "image", "pptx", "ppt",
    "xlsx", "html", "json", "jpg", "png", "other",
}


def _norm_doc_format(ext: str) -> str:
    """扩展名 → 合法 doc_format 枚举值；非法值兜底 'other'。"""
    val = (ext or "").lstrip(".").lower()
    return val if val in _DOC_FORMAT_VALUES else "other"


# structure_level 枚举合法值：structured(已按章节解析) / flat(扁平文本) / ocr(扫描件)。
# 历史代码用 "document" 表示「整篇文档、尚未章节解析」，PG 迁移后该值不合法，
# 语义等价于 flat，统一归一。
_STRUCTURE_LEVEL_VALUES = {"structured", "flat", "ocr"}
_STRUCTURE_LEVEL_FALLBACK = "flat"


def _norm_structure_level(val: str) -> str:
    val = (val or "").strip().lower()
    if val == "document":
        return _STRUCTURE_LEVEL_FALLBACK
    return val if val in _STRUCTURE_LEVEL_VALUES else _STRUCTURE_LEVEL_FALLBACK


logger = logging.getLogger(__name__)


def _like_escape(value: str) -> str:
    r"""转义 LIKE 的通配符，配合 `escape="\\"` 用。

    文件名里 `%`/`_`/`\` 都可能出现（`100%.pdf`、`微信图片_2026…`），不转义会让
    兜底去重把「100%.pdf」当成模式 `100<anything>.pdf`，误并别人的文档。
    """
    return re.sub(r"([\\%_])", r"\\\1", value)


def _trunc_copy_dir() -> str:
    """老导入器留下的截断副本目录（正文只存了前 5000 字，不能当去重目标）。"""
    return os.path.abspath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "storage", "documents"))


def _find_existing_doc(db, model, path: str):
    """幂等查找同一份文件已有的 Document，没有则返回 None。

    主键是绝对 `file_path`。兜底**必须按路径尾段认，绝不能按 `file_name` 认**：
    老批次行的 file_path 写成相对路径（`knowledge_base/…`）时绝对路径匹配不上，
    而 #27 的入库改名会把 `file_name` 换成正文标题 —— 按名字兜底就会漏掉自己
    刚改过名的那一行，同一份文件再长出一份 Document + 一整套重复分块
    （实测库里已有 444 组这种膨胀）。
    """
    doc = (db.query(model)
           .filter(model.file_path == os.path.abspath(path))
           .order_by(model.id).first())
    if doc is not None:
        return doc

    tail = _like_escape(os.path.basename(path))
    trunc_dir = _trunc_copy_dir()
    cands = (
        db.query(model)
        .filter(
            or_(model.file_path.like(f"%/{tail}", escape="\\"),
                model.file_path.like(f"%{_like_escape(os.sep)}{tail}", escape="\\")),
            model.index_status == "indexed",
            model.knowledge_point_count > 0,
        )
        .order_by(model.id)
        .all()
    )
    # 截断副本不算命中：把整份新正文并进它会丢内容。
    # 旧写法只取 first，副本会挡住后面真正的行。
    # 同名不同目录也绝不能认：库里 `…/数学/第一章.pdf` 和 `…/英语/第一章.pdf`
    # 都满足 `%\第一章.pdf`，只按尾段挑第一条就会把另一科的文档当成本份 ——
    # 覆盖它的 content、删掉它的分块，而 file_path 还指着原文件，
    # 结果是「预览看到的是 A、检索命中的是 B」。所以比对**目录段+文件名**。
    want = _path_tail(os.path.abspath(path))
    for c in cands:
        raw = str(getattr(c, "file_path", "") or "")
        if raw.startswith(trunc_dir):
            continue
        if raw and _path_tail(raw) == want:
            return c
    return None


def _path_tail(p: str) -> str:
    """路径最后两段（目录/文件名），统一分隔符后用于跨「相对路径 ↔ 绝对路径」比对。"""
    segs = [s for s in p.replace("\\", "/").split("/") if s]
    if not segs:
        return ""
    return "/".join(segs[-2:]) if len(segs) >= 2 else segs[-1]

# --------------------------------------------------------------------------- #
# 0. 配置
# --------------------------------------------------------------------------- #
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}

#: 是否启用 VLM 图块描述（慢，默认关；设 SMART_INGEST_VLM=1 开）
VLM_ENABLED = os.environ.get("SMART_INGEST_VLM", "0") == "1"
VLM_MODEL = os.environ.get("SMART_INGEST_VLM_MODEL", "qwen2.5vl:7b")
VLM_TIMEOUT = float(os.environ.get("SMART_INGEST_VLM_TIMEOUT", "180"))

#: 入库校验阈值
MIN_TEXT_LEN = 30              # 正文下限
MAX_MOJIBAKE_RATIO = 0.10      # 替换符占比上限
DEDUP_SIM_THRESHOLD = 0.97     # 向量去重阈值（0.97 极高，避免误杀）
DEDUP_SAMPLE_CHARS = 1200      # 去重取样长度

#: --- 二进制残留闸门（阈值按真库 2081 篇正文>=300 字的文档实测定，见下方注释）---
#: 不可读字节比例触发线：超过就至少要打复核标记。
MAX_CTRL_RATIO = 0.005
#: 连续不可读字节的最小长度，达到就是"整份二进制当文本读"的指纹（PDF 文本层
#: 的控制字符都是孤立的，实测正常文档最长连号 <=5）。
MIN_CTRL_RUN = 6
#: 判死还要正文确实不可读：中文占比上限 / 4+ 字母英文词占比上限。
#: 实测 3 篇坏文件这两项是 0.000~0.015 和 0.017~0.131，而好文档是 0.43~0.65
#: （英文真题）或 0.56~0.62（中文真题），两组之间没有重叠。
UNREADABLE_CJK_MAX = 0.05
UNREADABLE_WORD_MAX = 0.25

#: 扫描件 PDF 渲染约束
#:  * 目标 DPI：兼顾清晰度与速度（200 DPI 是中文印刷体 OCR 的经验最优）
PDF_RENDER_DPI = float(os.environ.get("SMART_INGEST_PDF_DPI", "200"))
#: 渲染后单边像素上限。资料库里存在「整册扫描长图」型 PDF
#: （实测【数电 · 系统课】单页 16.5in × 84in，@200DPI = 3306×16892 px），
#: 直接送OCR 会超出内存/检测上限并静默返回空串，必须按比例降采样。
PDF_MAX_SIDE_PX = int(os.environ.get("SMART_INGEST_PDF_MAX_SIDE", "2600"))

#: 学科 → 专业方向（3 级标签体系的第 2 级）
MAJOR_DIRECTION = {
    "数字电子技术": "电子信息（数字电路方向）",
    "模拟电子技术": "电子信息（模拟电路方向）",
    "电路": "电气工程",
    "信号与系统": "信息与通信工程",
    "通信原理": "信息与通信工程",
    "光学与工程光学": "光学工程",
    "普通物理": "物理学",
    "计算机学科专业基础408": "计算机科学与技术",
    "数学": "数学（公共课）",
    "英语": "英语（公共课）",
    "政治": "政治（公共课）",
    "真题综合": "综合",
}


# --------------------------------------------------------------------------- #
# 1. 图像预处理（纠偏 / 去黑边 / 去噪 / 轻量放大）
# --------------------------------------------------------------------------- #
def preprocess_image(src_path: str, out_dir: Optional[str] = None) -> Dict[str, Any]:
    """教材扫描件/照片的预处理。

    步骤（OpenCV，纯 CPU）：
      1. 读取 → 灰度
      2. **去黑边**：按行列亮度找到内容边界并裁剪（扫描仪常见黑边）
      3. **去噪**：中值滤波 + 轻度高斯
      4. **纠偏**：用文字像素的 minAreaRect 估计倾斜角并旋转（±20° 内）
      5. **轻量放大**：短边 < 1000px 时放大到 1600px，提升小字 OCR 命中率

    Returns:
        {ok, path, angle, cropped, scaled, error}
    """
    out = {"ok": False, "path": src_path, "angle": 0.0,
           "cropped": False, "scaled": False, "error": None}
    try:
        import cv2
        import numpy as np
    except Exception as e:  # noqa: BLE001
        out["error"] = f"OpenCV 不可用: {e}"
        return out

    try:
        # 用 imdecode 而非 imread：OpenCV 的 imread/imwrite 在 Windows 上
        # **无法处理中文路径**（本项目知识库路径含大量中文），
        # 会导致预处理被静默跳过。此处统一走 numpy buffer 读写。
        img = cv2.imdecode(np.fromfile(src_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            out["error"] = "无法读取图片"
            return out

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # --- 去黑边：二值化后找内容包围盒 ---
        _, binimg = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        coords = cv2.findNonZero(255 - binimg)  # 找暗像素（内容）
        if coords is not None:
            x, y, w, h = cv2.boundingRect(coords)
            pad = 8
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(gray.shape[1], x + w + pad), min(gray.shape[0], y + h + pad)
            # 只有裁掉明显黑边时才裁（避免误裁）
            if (x1 - x0) < gray.shape[1] * 0.995 or (y1 - y0) < gray.shape[0] * 0.995:
                gray = gray[y0:y1, x0:x1]
                out["cropped"] = True

        # --- 去噪 ---
        gray = cv2.medianBlur(gray, 3)

        # --- 纠偏 ---
        work = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        # 横向膨胀，把文字连成行，便于估计行方向
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 1))
        work = cv2.dilate(work, kernel, iterations=1)
        cnts, _ = cv2.findContours(work, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        angles: List[float] = []
        for c in cnts:
            if cv2.contourArea(c) < 500:
                continue
            rect = cv2.minAreaRect(c)
            a = rect[-1]
            if a < -45:
                a += 90
            if abs(a) <= 20:  # 只接受小角度，避免把竖排文本转歪
                angles.append(a)
        if angles:
            angle = float(np.median(angles))
            if abs(angle) > 0.3:  # 小于 0.3° 不值得旋转
                h, w = gray.shape
                M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
                gray = cv2.warpAffine(
                    gray, M, (w, h), flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE,
                )
                out["angle"] = round(angle, 3)

        # --- 轻量放大（小字提升 OCR 命中） ---
        h, w = gray.shape
        short = min(h, w)
        if short and short < 1000:
            scale = min(1600 / short, 3.0)
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)),
                              interpolation=cv2.INTER_CUBIC)
            out["scaled"] = True

        # --- 输出 ---
        if out_dir is None:
            out_dir = tempfile.mkdtemp(prefix="smart_ingest_")
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(src_path))[0]
        dst = os.path.join(out_dir, f"{base}.pre.png")
        # 同样避开中文路径问题：先编码到内存再写文件
        ok_enc, buf = cv2.imencode(".png", gray)
        if not ok_enc:
            out["error"] = "编码失败"
            return out
        buf.tofile(dst)
        out.update(ok=True, path=dst)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


# --------------------------------------------------------------------------- #
# 2. 分流识别（文字 OCR / 公式 / 图块）
# --------------------------------------------------------------------------- #
def recognize_image(path: str, *, preprocess: bool = True,
                    ocr_backend: str = "auto") -> Dict[str, Any]:
    """图片分流识别：文字块走 OCR，公式块走 formula_service，图块可选走 VLM。

    Returns:
        {text, engine, ocr_used, latex_list, formula_flags, figure_desc, blocks, error}
    """
    res: Dict[str, Any] = {
        "text": "", "engine": "", "ocr_used": "", "latex_list": [],
        "formula_flags": 0, "figure_desc": [], "blocks": [], "error": None,
    }
    src = path
    if preprocess:
        pre = preprocess_image(path)
        if pre.get("ok"):
            src = pre["path"]
        # 预处理失败则回退原图，不影响识别

    # --- 文字块 OCR ---
    try:
        from services.ocr_router import recognize_file

        ocr = recognize_file(src, prefer=ocr_backend)
        res["text"] = ocr.text or ""
        res["engine"] = ocr.engine or ""
        res["ocr_used"] = ocr.backend or ocr.engine or ""
        res["blocks"] = [b.to_dict() for b in (ocr.blocks or [])]
        if ocr.error:
            res["error"] = ocr.error
    except Exception as e:  # noqa: BLE001
        res["error"] = f"OCR 失败: {e}"
        return res

    # --- 公式块（有公式迹象才调用，避免无谓开销） ---
    try:
        from services import formula_service

        det = formula_service.detect_formula_regions(res["text"])
        if det.get("has_formula"):
            f = formula_service.recognize_formula(src)
            latex = f.get("latex") or ""
            if latex:
                res["latex_list"].append(latex)
            res["formula_flags"] = int(f.get("pending_flags") or 0)
    except Exception:
        pass  # 公式识别失败不影响主文本

    # --- 图块 VLM（可选，默认关） ---
    if VLM_ENABLED:
        try:
            d = _describe_figure(src)
            if d:
                res["figure_desc"].append(d)
        except Exception as _exc:  # noqa: BLE001
            # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
            # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
            logging.getLogger(__name__).warning(
                '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
            )

    return res


_FIGURE_PROMPT = """你是大学考研教材解析助手。分析图片，输出严格 JSON，禁止编造不存在的信息，不确定字段填 null。
{"image_type":"原理图/光路图/波形图/结构图/表格","main_subject":"所属学科方向",
 "core_content":"图内元件、参数、物理关系、坐标含义","related_knowledge_point":"关联考研知识点",
 "note":"不确定则标记待复核"}
只返回 JSON，不要额外解释。"""


def _describe_figure(image_path: str) -> Optional[str]:
    """用本地 VLM（qwen2.5vl）把教材插图描述成结构化文本。"""
    import base64
    import json as _json
    import urllib.request

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {
        "model": VLM_MODEL,
        "prompt": _FIGURE_PROMPT,
        "images": [b64],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=_json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=VLM_TIMEOUT) as r:
        body = _json.loads(r.read().decode())
    return (body.get("response") or "").strip() or None


# --------------------------------------------------------------------------- #
# 3. 文本清洗
# --------------------------------------------------------------------------- #
_IMG_REF = re.compile(r"!\[([^\]]{0,80})\]\([^)]*\)")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NOISE_LINE = re.compile(
    r"^\s*!?\[\s*(未能识别到文本内容|图片|image|img)\s*\]?\s*$", re.I)
#: **占位/错误文本**——解析器与OCR 层在失败时返回的是一句人话（如
#: `"[扫描版 PDF OCR 失败: No module named 'PIL']"`、`"[WinError 2] ..."`），
#: 而不是抛异常。旧逻辑只挡了`[解析失败`，且早期版本用「枚举错误短语 +
#: `[^\]]{0,300}`」匹配 —— 但 `[扫描版 PDF OCR 失败: [WinError -536870904]
#: Windows Error 0xe0000008]` 里 **内层 `[WinError ...]` 的 `]` 会提前闭合
#: 字符类**，导致整串匹配失败、真库残留 1 条 64 字毒化文档（id=452）。
#:
#: 现改为**不依赖内部方括号**的宽松匹配 + 长度上限：真正的正文不可能是
#: 一句 200 字以内、以方括号包裹、且含「失败/错误/error」的话。
#: 占位文本的特征词：中文（失败/错误/异常…）+ 英文（error/failed…）
#:  + 运行时异常类名/典型报错片段（WinError / ModuleNotFoundError / No module named…）
#: 注意关键词**不要求出现在 `]` 之前** —— `[WinError 2] 系统找不到指定的文件`
#: 里特征词就在方括号**内部**，用「前缀枚举」或「关键词+结尾]」都会漏。
_PLACEHOLDER_KW = re.compile(
    r"失败|错误|异常|无法|未能|未找到|不支持"
    r"|error|failed|failure|exception|traceback|winerror|modulenotfound|importerror"
    r"|no module named|cannot|unable to|not found|timeout|refused|denied",
    re.I)
#: 占位串的形态：**以 `[` 开头**（不要求 `]` 在末尾）。
#: 真实样本两种形态都有：
#:   `[扫描版 PDF OCR 失败: [WinError -536870904] Windows Error 0xe0000008]`  ← `]` 在末尾
#:   `[WinError 2] 系统找不到指定的文件`                                        ← `]` 后还有内容
#: 所以只锚定开头，结尾交给「长度上限」约束。
_BRACKETED_RE = re.compile(r"^\s*\[", re.S)
#: 占位文本长度上限：超过此长度的多半是真正文（宁可漏判也不误杀）
PLACEHOLDER_MAX_LEN = 200
# 页眉页脚 / 页码 / 水印（可配置是否保留）
_PAGE_NO = re.compile(r"^\s*[-—–\s]*第?\s*\d{1,4}\s*页?\s*(共\s*\d{1,4}\s*页)?\s*[-—–\s]*$")
_WATERMARK = re.compile(r"(扫描全能王|CamScanner|扫描王|仅供学习|请勿传播|内部资料|盗版必究)")


def clean_text(text: str, *, drop_page_no: bool = True,
               drop_watermark: bool = True) -> str:
    """文本清洗：去图片引用 / 零宽字符 / 控制字符 / 噪声行 / 页码 / 水印。"""
    if not text:
        return ""
    s = _ZERO_WIDTH.sub("", text)
    s = _CTRL.sub("", s)

    def _img(m: re.Match) -> str:
        alt = (m.group(1) or "").strip()
        if not alt or re.fullmatch(r"(未能识别到文本内容|图片|image|img)", alt, re.I):
            return ""
        return alt if len(alt) <= 40 else ""

    s = _IMG_REF.sub(_img, s)
    lines: List[str] = []
    for ln in s.split("\n"):
        if _NOISE_LINE.match(ln):
            continue
        if drop_page_no and _PAGE_NO.match(ln):
            continue
        if drop_watermark and _WATERMARK.search(ln):
            ln = _WATERMARK.sub("", ln)
        lines.append(ln.rstrip())
    s = "\n".join(lines)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def is_placeholder_text(text: str) -> bool:
    """判断文本是否为「错误提示占位串」而非真实正文。

    背景：`DocumentParser.parse()` 与 `_ocr_pdf_pages()` 在失败时**返回**一句
    方括号包裹的错误说明（如 `"[扫描版 PDF OCR 失败: No module named'PIL']"`），
    而不是抛异常。若不拦截，这句错误说明会被当成正文入库——字数少但"非空"，
    恰好绕过 `MIN_TEXT_LEN` 之外的直觉判断，形成「✓ 入库成功 39 字」的假成功。

    Returns:
        True 表示这是占位串（应判失败并把原因写进 reasons）。
    """
    if not text:
        return False
    t = text.strip()
    if not t:
        return False
    # 长度闸门：真正的正文再短也不会是「方括号包裹的失败提示」，
    # 而超过上限的方括号文本多半是正文（如 Markdown 引用/链接列表），不误杀。
    if len(t) > PLACEHOLDER_MAX_LEN:
        return False

    def _hit(s: str) -> bool:
        s = s.strip()
        return bool(s) and len(s) <= PLACEHOLDER_MAX_LEN \
            and _BRACKETED_RE.match(s) and _PLACEHOLDER_KW.search(s)

    # 整篇就是一句占位串
    if _hit(t):
        return True
    # 占位串被清洗/拼接后混在正文里：任一行整行匹配也算失败
    for ln in t.split("\n"):
        if _hit(ln):
            return True
    return False


# --------------------------------------------------------------------------- #
# 4. 结构化抽取（教材 / 章节 / 内容类型 / 知识点）
# --------------------------------------------------------------------------- #
_BOOK_RE = re.compile(r"[《【]([^》】]{2,40})[》】]")
_AUTHOR_RE = re.compile(
    r"([\u4e00-\u9fa5]{2,4})\s*(?:编著|主编|著|编)\b|"
    r"(?:主编|编著|作者)\s*[:：]?\s*([\u4e00-\u9fa5]{2,4})")
_EDITION_RE = re.compile(r"第\s*([一二三四五六七八九十\d]{1,3})\s*版")
_CHAPTER_RE = re.compile(r"第\s*([一二三四五六七八九十\d]{1,3})\s*章[\s　]*([^\n]{0,40})")
_SECTION_RE = re.compile(r"第\s*([一二三四五六七八九十\d]{1,3})\s*节[\s　]*([^\n]{0,40})")

_CONTENT_TYPE_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("考研真题", ("真题", "考研试题", "入学考试", "统考")),
    ("课后习题", ("课后", "习题", "思考题", "练习题")),
    ("例题", ("例题", "例", "【例")),
    ("讲义课件", ("讲义", "课件", "PPT", "教案", "辅导")),
    ("教材正文", ("教材", "第", "章")),
]


#: 书名里的来源/营销噪声，命中即丢弃
_BOOK_NAME_NOISE = re.compile(
    r"公众号|整理自|免费分享|水印|QQ群|加群|领取|网盘|链接|淘宝|店铺")


def _pick_book_name_from_text(head: str) -> str:
    """从正文里挑书名，挑不出就返回 ""（宁缺勿错）。

    为什么不能直接取正文**首个**《》：正文里的《》绝大多数是**引用**
    （「因新版《全国硕士研究生招生考试英语（一）考试大纲》已明确…」），
    实测把 `1000题：学习打卡表（新思想）.pdf` 的书名取成了「思维导图」。
    三条闸门，过不了就留空：
      1. 同一书名出现 ≥2 次 → 是本书，不是顺带一提的引用；
      2. 出现在正文开头 300 字内 → 封面/页眉书名；
      3. 独立成行 → 标题行。
    """
    if not head:
        return ""
    matches = list(_BOOK_RE.finditer(head))
    if not matches:
        return ""
    counts = Counter(m.group(1).strip() for m in matches)
    lines = {ln.strip() for ln in head.split("\n")}
    for m in matches:
        nm = m.group(1).strip()
        if counts[nm] >= 2 or m.start() <= 300:
            return nm
    for m in matches:
        nm = m.group(1).strip()
        if f"《{nm}》" in lines or f"【{nm}】" in lines:
            return nm
    return ""


def extract_metadata(file_name: str, text: str, path: str = "") -> Dict[str, Any]:
    """从文件名 + 正文抽取结构化标签，用于知识地图与检索过滤。

    `path` 可选：给完整文件路径时，学科判定会**优先采信路径里的学科目录名**
    （`.../政治/xxx.pdf` → 政治）。此前调用方只传 `os.path.basename(path)`，
    目录里的学科信息被整段丢掉，是政治资料被判成数学的直接原因之一。
    """
    from services.kb_service import classify_subject, classify_content_category

    head = text[:4000]

    # 教材名：优先文件名里的《》，其次正文里"经得起验证"的书名（引用不算）
    book_name = ""
    m = _BOOK_RE.search(file_name)
    if m:
        book_name = m.group(1).strip()
    else:
        book_name = _pick_book_name_from_text(head)
    # 公众号/来源标注不是书名（`新思想思维导图：【公众号：学长小谭考研】.pdf`
    # 实测被取成 `公众号：学长小谭考研`），命中就丢弃。
    if book_name and _BOOK_NAME_NOISE.search(book_name):
        book_name = ""

    # 作者 / 版次
    author = ""
    ma = _AUTHOR_RE.search(file_name) or _AUTHOR_RE.search(head[:800])
    if ma:
        author = (ma.group(1) or ma.group(2) or "").strip()
    edition = ""
    me = _EDITION_RE.search(file_name) or _EDITION_RE.search(head[:800])
    if me:
        edition = f"第{me.group(1)}版"

    # 章节：取正文最早出现的「第X章」
    chapter = ""
    mc = _CHAPTER_RE.search(head)
    if mc:
        chapter = f"第{mc.group(1)}章 {mc.group(2).strip()}".strip()
    section = ""
    ms = _SECTION_RE.search(head)
    if ms:
        section = f"第{ms.group(1)}节 {ms.group(2).strip()}".strip()

    # 内容类型
    ctype = ""
    hay = file_name + head[:600]
    for label, kws in _CONTENT_TYPE_RULES:
        if any(k in hay for k in kws):
            ctype = label
            break
    if not ctype:
        ctype = classify_content_category(file_name, head) or "教材正文"

    subject = classify_subject(file_name, text, path=path or file_name)
    return {
        "subject": subject,
        "major": MAJOR_DIRECTION.get(subject, ""),
        "book_name": book_name,
        "author": author,
        "edition": edition,
        "chapter": chapter,
        "section": section,
        "content_type": ctype,
    }


# --------------------------------------------------------------------------- #
# 5. 入库前校验（脏数据拦截）
# --------------------------------------------------------------------------- #
#: 正文全等去重的下限：短于此的（`---\nsort: 1\n---\n# ADC` 这类骨架）本来就会被
#: :data:`MIN_TEXT_LEN` 拦下，不需要指纹。
MIN_FINGERPRINT_CHARS = 200

#: 程序自己往 knowledge_base 里写的东西 —— 再被目录扫描器读回来就是**自我喂食**：
#: 上一批的 README/回收站/切块产物会变成"用户新资料"，语料越滚越多且全是重复。
_SELF_PRODUCED_DIRS = ("_trash", "chunks", "meta")
_SELF_PRODUCED_FILES = ("readme.md", ".processed_files.json", "changelog.md", "license")


def is_self_produced(path: str) -> bool:
    """这份文件是不是**本程序自己产出的**（而不是用户放进来的资料）。

    实测代价：库里有一篇 `README.md`（knowledge_base 自己的说明，2174 字）被当
    成资料入库并标 `indexed`，另有 63 篇 `inbox/**.md` 骨架卡（20–30 字）。
    """
    if not path:
        return False
    norm = str(path).replace("\\", "/").lower()
    segs = [s for s in norm.split("/") if s]
    if any(s in _SELF_PRODUCED_DIRS for s in segs):
        return True
    return bool(segs) and segs[-1] in _SELF_PRODUCED_FILES


#: PDF/Word 文本层正常存在的排版/分隔符，**不能**当二进制残留：
#: \t \n \v \f \r 和 0x1C-0x1F（文件/分组分隔符）、0x85（NEL）。
#: 实测正常文档里这几类各有几千处（占正文 2%+），计入就会误杀 9% 的好文档。
_CTRL_IS_WHITESPACE = frozenset({0x09, 0x0A, 0x0B, 0x0C, 0x0D,
                                 0x1C, 0x1D, 0x1E, 0x1F, 0x85})


def _is_unreadable(ch: str) -> bool:
    """真正无法渲染的控制字节（C0 去掉排版空白 + DEL + C1 控制区）。"""
    o = ord(ch)
    return (o <= 0x1F or o == 0x7F or 0x80 <= o <= 0x9F) and o not in _CTRL_IS_WHITESPACE


def ctrl_stats(text: str):
    """返回 (不可读字节数, 最长连续不可读字节数)。

    连号长度是关键：PDF 文本层里的坏字节都是**孤立**的（水印、字体表残留），
    而"把整份 .doc/.ole 当文本解码"会产出连续几十个字节的控制流。只按比例
    筛分不开两类 —— 中文占 57% 的真真题实测也有 7.8% 的不可读字节。
    """
    cnt = run = mx = 0
    for ch in text:
        if _is_unreadable(ch):
            cnt += 1
            run += 1
            if run > mx:
                mx = run
        else:
            run = 0
    return cnt, mx


def find_content_duplicate(db, model, text: str, *, exclude_id: Optional[int] = None,
                           head_chars: int = 64):
    """按**正文全等**找已有的 Document，返回 ``(id, file_path)`` 或 None。

    为什么必须有它：所有入库入口原本只按 `file_path` 认同一份文件，而同一本讲义
    被复制进 `knowledge_base/公共课/英语/…` 和 `data/storage/…` 两个位置时，路径
    不同 → 各自长出完整一份 Document + 整套分块。实测 Python 侧按正文全等分组，
    库里这种同文重复有 95 组、多算出 150 行。

    预筛用 `SUBSTR(content,1,64)` 而不是 `LENGTH(content)`：实测 72 篇正文含裸
    NUL/不可读字节的行，SQLite 的 `LENGTH()` 只数到第一个坏字节（`length=45` 而
    Python 看到 13954 字），按长度筛会**永远筛不到**这些最需要去重的行；
    `SUBSTR` 与绑定参数比对实测正常（全表扫 126 ms）。命中的少量候选再在
    Python 里 strip 后全等确认。
    """
    t = (text or "").strip()
    if len(t) < MIN_FINGERPRINT_CHARS:
        return None
    # PG 的 text 类型禁止绑定含 NUL 的参数（DataError）。库内已存内容必然无 NUL
    # （PG 存不进去），故比对前把 NUL 从样本里剥掉不影响正确性；SQLite 无影响。
    t = t.replace("\x00", "")
    q = (db.query(model.id, model.file_path, model.content)
         .filter(func.substr(model.content, 1, head_chars) == t[:head_chars]))
    if exclude_id is not None:
        q = q.filter(model.id != exclude_id)
    for cid, cpath, ccontent in q.all():
        if (ccontent or "").strip() == t:
            return int(cid), (cpath or "")
    return None


def validate_for_ingest(text: str, subject: str = "", db=None,
                        *, check_dedup: bool = True,
                        path: str = "", exclude_doc_id: Optional[int] = None) -> Dict[str, Any]:
    """入库前质量校验 + 向量去重。

    Returns:
        {ok, reasons, review_flag, dedup_hit, dedup_doc_id, dedup_sim, stats}
    """
    out: Dict[str, Any] = {
        "ok": True, "reasons": [], "review_flag": "auto_pass",
        "dedup_hit": False, "dedup_doc_id": None, "dedup_sim": 0.0,
        "stats": {},
    }
    t = (text or "").strip()
    n = len(t)
    out["stats"]["chars"] = n

    # 自产文件不入库（放在最前：它正文可以很长很"干净"，后面几条拦不住）
    if path and is_self_produced(path):
        out["ok"] = False
        out["review_flag"] = "auto_reject"
        out["reasons"].append(f"程序自产文件，不入库：{os.path.basename(str(path))}")
        return out

    if n < MIN_TEXT_LEN:
        out["ok"] = False
        out["reasons"].append(f"正文过短({n}字)")

    # **占位文本兜底闸门**（与is_placeholder_text 同源，但独立于调用链）：
    # 任何解析/OCR 后端将来返回「方括号包裹的失败提示」时，都在这里被拦下，
    # 不依赖上游是否记得调用拦截。宁可漏一篇好文档，也绝不放错误文本进库。
    if n and is_placeholder_text(t):
        out["ok"] = False
        out["review_flag"] = "auto_reject"
        out["stats"]["placeholder"] = True
        out["reasons"].append(f"占位错误文本，非真实正文({n}字): {t[:100]}")

    if n:
        moji = t.count("\ufffd")
        ratio = moji / n
        out["stats"]["mojibake_ratio"] = round(ratio, 4)
        if ratio > MAX_MOJIBAKE_RATIO:
            out["ok"] = False
            out["reasons"].append(f"乱码比例过高({ratio:.1%})")

        # 控制字符 / 二进制残留：只统计，判定放到读完中文占比之后
        # （errors="ignore" 会**丢字节**而不产生 U+FFFD，乱码比例拦不住
        #  "整份 .doc/.ole 当文本解码"的产物）。
        hard_ctrl, hard_run = ctrl_stats(t)
        out["stats"]["ctrl_ratio"] = round(hard_ctrl / n, 4)
        out["stats"]["ctrl_maxrun"] = hard_run

        cjk = len(re.findall(r"[\u4e00-\u9fa5]", t))
        out["stats"]["cjk_ratio"] = round(cjk / n, 4)
        if cjk / n < 0.02 and not re.search(r"[a-zA-Z]{30,}", t):
            out["review_flag"] = "need_review"
            out["reasons"].append("中文占比过低（可能是公式/图表为主或识别失败）")

        # 二进制残留定档（2081 篇实测校准，阈值理由见上方常量注释）：
        #  * 只看比例会误杀 —— 中文占 57% 的真真题也有 7.8% 的不可读字节；
        #  * 判死必须**同时**满足"控制字节成串"和"正文既没中文也没成型英文"。
        #    实测本规则拦下 #2909 #2343 #2322 三篇坏文件，误杀 0 篇。
        #  * 只超标但正文可读 -> need_review，交人工而不是静默丢掉真正文。
        if hard_ctrl / n > MAX_CTRL_RATIO or hard_run >= MIN_CTRL_RUN:
            cjk_share = cjk / n
            word_share = sum(len(w) for w in re.findall("[A-Za-z]{4,}", t)) / n
            out["stats"]["word_ratio"] = round(word_share, 4)
            unusable = (cjk_share < UNREADABLE_CJK_MAX and word_share < UNREADABLE_WORD_MAX)
            if unusable and hard_run >= MIN_CTRL_RUN and hard_ctrl / n > MAX_CTRL_RATIO:
                out["ok"] = False
                out["review_flag"] = "auto_reject"
                out["reasons"].append(
                    f"二进制残留(不可读字节 {hard_ctrl}/{n}={hard_ctrl / n:.1%}，最长连号 {hard_run}；"
                    f"中文 {cjk_share:.1%}、英文词 {word_share:.1%})，正文不可读")
            elif out["review_flag"] == "auto_pass":
                out["review_flag"] = "need_review"
                out["reasons"].append(
                    f"含 {hard_ctrl} 个不可读字节（最长连号 {hard_run}），正文可读，建议复核")

    # **正文全等去重**：确定性、无需模型服务，是各入口都能用的那道闸。
    if db is not None and n >= MIN_FINGERPRINT_CHARS:
        from models import Document
        hit = find_content_duplicate(db, Document, t, exclude_id=exclude_doc_id)
        if hit:
            out["dedup_hit"] = True
            out["ok"] = False
            out["reasons"].append(f"正文与文档#{hit[0]} 完全相同（重复导入）")

    # 向量去重
    if check_dedup and db is not None and n >= 200:
        try:
            hit = _dedup_check(db, t[:DEDUP_SAMPLE_CHARS], subject)
            if hit:
                out["dedup_hit"] = True
                out["dedup_doc_id"], out["dedup_sim"] = hit
                if hit[1] >= DEDUP_SIM_THRESHOLD:
                    out["ok"] = False
                    out["reasons"].append(f"疑似重复（与文档#{hit[0]} 相似度 {hit[1]:.3f}）")
                elif hit[1] >= 0.90:
                    out["review_flag"] = "need_review"
                    out["reasons"].append(f"与文档#{hit[0]} 高度相似（{hit[1]:.3f}），建议复核")
        except Exception:
            pass  # 去重失败不阻断入库

    return out


def gate_for_write(db, text: str, *, path: str = "", subject: str = "",
                   doc_id=None) -> Dict[str, Any]:
    """所有入库入口在写 `Document.content` / 切分分块**之前**必须过的一道闸。

    和 :func:`validate_for_ingest` 的区别只在固定参数：
    `check_dedup=False` —— 向量去重要调本地嵌入模型（单次 1~3 秒，Ollama 没起
    就整批导入卡死），绝不能放进批量扫描的串行循环。正文全等去重是纯 SQL
    （实测单次 ~130 ms），保留。

    返回 verdict dict：`ok=False` 时调用方必须**跳过写入**并把 `reasons` 透给
    用户/日志，不允许"照样入库"。`doc_id` 传正在重新解析的那篇自己，避免
    它跟自己判重。
    """
    return validate_for_ingest(text, subject, db, check_dedup=False,
                               path=path, exclude_doc_id=doc_id)


def _dedup_check(db, text: str, subject: str) -> Optional[Tuple[int, float]]:
    """用本地 BGE 向量在 knowledge_chunks_vec 里找最相似分块。

    Returns: (document_id, cosine_similarity) 或 None
    """
    import numpy as np
    from services.embedding_service import generate_local_embeddings

    vecs = generate_local_embeddings([text])
    if not vecs:
        return None
    q = np.asarray(vecs[0], dtype=np.float32)
    qn = float(np.linalg.norm(q))
    if qn == 0:
        return None
    q = q / qn

    conn = wrap_conn(db.connection().connection)
    sql = ("SELECT document_id, embedding, dim FROM knowledge_chunks_vec "
           "WHERE embedding IS NOT NULL AND dim = ?")
    params: List[Any] = [len(q)]
    if subject:
        sql += " AND subject = ?"
        params.append(subject)
    sql += " LIMIT 20000"

    best_doc, best_sim = None, 0.0
    for doc_id, blob, dim in conn.execute(sql, params):
        try:
            v = np.frombuffer(blob, dtype=np.float32)
        except Exception:
            continue
        if v.size != q.size:
            continue
        vn = float(np.linalg.norm(v))
        if vn == 0:
            continue
        sim = float(np.dot(q, v / vn))
        if sim > best_sim:
            best_sim, best_doc = sim, doc_id
    if best_doc is None:
        return None
    return (best_doc, best_sim)


# --------------------------------------------------------------------------- #
# 6. 主管线：预处理 → 分流识别 → 清洗 → 抽取 → 校验 → 入库
# --------------------------------------------------------------------------- #
def smart_ingest_file(
    db,
    path: str,
    *,
    ocr_backend: str = "auto",
    do_embeddings: bool = False,
    dry_run: bool = False,
    force: bool = False,
    extract_kp: Optional[bool] = None,
    classify_chunks: Optional[bool] = None,
    use_llm_labels: bool = True,
) -> Dict[str, Any]:
    """跑完整智能入库管线（教材/讲义/真题/课件/扫描件通用）。

    Args:
        force: True 时即使校验不通过也入库（并标 need_review）
        extract_kp: 入库成功后是否抽知识点。None = 读环境变量
            `SMART_INGEST_KP`（默认开）。见 `services.kp_extract`。
        classify_chunks: 是否做 chunk 三层标签。None = 读
            `CHUNK_CLASSIFY_ENABLED`（默认开）。见 `services.chunk_classifier`。
        use_llm_labels: False 时打标只跑向量+关键词两路（省钱/离线批跑）。

    Returns:
        {file, status, subject, book_name, chapter, content_type, chars,
         dedup_hit, review_flag, reasons, engine, ocr_used, doc_id,
         knowledge_points: {chunks, kept, dropped, failed, subject_mix, ...}}
    """
    path = os.path.abspath(path)
    ext = os.path.splitext(path)[1].lower()
    out: Dict[str, Any] = {
        "file": os.path.basename(path), "status": "failed", "chars": 0,
        "subject": "", "book_name": "", "chapter": "", "content_type": "",
        "dedup_hit": False, "review_flag": "auto_pass", "reasons": [],
        "engine": "", "ocr_used": "", "doc_id": None,
        "knowledge_points": {},
        "chunk_labels": {},
    }
    if not os.path.isfile(path):
        out["reasons"].append("文件不存在")
        return out

    # --- 分流识别 ---
    if ext in IMAGE_EXTS:
        r = recognize_image(path, ocr_backend=ocr_backend)
        text = r["text"]
        out["engine"], out["ocr_used"] = r["engine"], r["ocr_used"]
        latex_list, fig_desc = r["latex_list"], r["figure_desc"]
        # 图片路径的 OCR 失败原因原先被丢弃（只看字数），这里显式透出
        if r.get("error") and not text:
            out["reasons"].append(f"OCR 失败({r.get('ocr_used') or '无后端'}): "
                                  f"{str(r['error'])[:150]}")
    else:
        # PDF / Office：优先文本层；无文本层（扫描件）走 OCR
        from services.document_parser import DocumentParser

        parser = DocumentParser()
        try:
            text = parser.parse(path) or ""
        except Exception as e:  # noqa: BLE001
            text = ""
            out["reasons"].append(f"解析异常: {e}")
        out["engine"] = "parser"
        # 解析器失败时返回的是方括号错误串而非抛异常；必须整类识别，
        # 旧逻辑只判 "[解析失败"，漏掉 "[扫描版 PDF OCR 失败: ...]"，
        # 导致这句错误提示被当成正文（39 字）继续走后面的清洗/入库。
        if is_placeholder_text(text):
            out["reasons"].append(f"解析器返回占位错误文本: {text.strip()[:120]}")
            text = ""
        latex_list, fig_desc = [], []
        if ext == ".pdf" and len(text.strip()) < MIN_TEXT_LEN:
            # 扫描件 PDF：逐页转图 → 图片分流识别
            text, latex_list, fig_desc, eng = _ocr_pdf_pages(path, ocr_backend)
            if eng:
                out["engine"], out["ocr_used"] = "pdf-ocr", eng

    # --- 清洗 ---
    text = clean_text(text)

    # **占位串拦截**：错误提示不是正文。必须在清洗后、入库前判定，
    # 否则「[扫描版 PDF OCR 失败: ...]」会被当成 39 字正文成功入库。
    if is_placeholder_text(text):
        out["reasons"].append(f"解析/OCR 返回占位错误文本，非真实正文: {text.strip()[:120]}")
        out["placeholder"] = True
        out["chars"] = 0
        out["status"] = "rejected"
        return out

    out["chars"] = len(text)

    # 公式与图描述并入正文（作为结构化补充段）
    if latex_list:
        text += "\n\n## 公式（LaTeX）\n" + "\n".join(f"- ${x}$" for x in latex_list)
    if fig_desc:
        text += "\n\n## 图表解析\n" + "\n".join(f"- {x}" for x in fig_desc)

    # --- 结构化抽取 ---
    # ⚠️ 必须传**完整路径**而不是 basename：路径里的学科目录（`.../政治/xxx.pdf`）
    # 是最准的学科信号。只传 basename 时，`1000题：学习打卡表（新思想）.pdf`
    # 这类文件名不含科目词的资料只能靠正文兜底，实测被判成数学。
    meta = extract_metadata(os.path.basename(path), text, path=path)
    out.update({k: meta.get(k, "") for k in
                ("subject", "book_name", "chapter", "content_type")})
    out["major"] = meta.get("major", "")
    out["section"] = meta.get("section", "")

    # --- 校验 ---
    v = validate_for_ingest(text, subject=meta.get("subject", ""), db=db)
    out["dedup_hit"] = v["dedup_hit"]
    out["review_flag"] = v["review_flag"]
    out["reasons"].extend(v["reasons"])
    out["stats"] = v["stats"]

    if not v["ok"] and not force:
        out["status"] = "rejected"
        return out

    if dry_run:
        out["status"] = "dry-run-ok"
        return out

    # --- 入库 ---
    try:
        from models import Document
        from services import kb_service

        # --- 幂等保护：同一文件路径已入库则复用旧 Document，不再新建 ---
        # 背景：这里原先无条件 db.add(Document(...))，而 ingest_document(replace=True)
        # 只能清理「该 document_id 名下的旧分块」——新建的 doc 根本没有旧块，于是
        # 每跑一次入库管线就多一份 documents 行 + 一整套重复 knowledge_chunks。
        # 实测库里因此有 444 组同名 documents（4 个日期批次 08-31/09-01/10-08/10-12
        # 各跑了一遍），knowledge_chunks 75122 行里唯一 text 只有 68915。
        # 管道式跑批（--scan-dir）尤其致命：同一份知识库反复扫就会自我膨胀。
        file_path_abs = os.path.abspath(path)
        doc = None
        try:
            doc = _find_existing_doc(db, Document, path)
        except Exception as e:  # noqa: BLE001
            # 旧库可能缺 file_path 列，退回无条件新建（不因幂等检查失败而阻断入库）
            logger.warning("幂等检查失败，退回新建 Document: %s", e)

        if doc is not None:
            out["doc_id"] = doc.id
            out["dedup_reused"] = True
            # 刷新文档级字段
            doc.content = text
            doc.source_format = _norm_doc_format(ext)
            doc.subject = meta.get("subject", "") or doc.subject
            doc.doc_type = kb_service.classify_doc_type(
                os.path.basename(path), ext.lstrip(".")
            )
            doc.index_status = "indexed"
            doc.ocr_used = bool(out["ocr_used"])
            doc.structure_level = _norm_structure_level("document")
        else:
            doc = Document(
                file_name=os.path.basename(path),
                file_path=file_path_abs,
                source_format=_norm_doc_format(ext),
                content=text,
                subject=meta.get("subject", ""),
                doc_type=kb_service.classify_doc_type(os.path.basename(path),
                                                      ext.lstrip(".")),
                index_status="indexed",
                ocr_used=bool(out["ocr_used"]),
                structure_level=_norm_structure_level("document"),
            )
            db.add(doc)
        db.flush()
        # #27 按内容定显示名：必须在分块前改，chunk.doc_name 才会带上新名
        apply_display_name(db, doc, text)
        # 幂等增强（2026-10-17）：已成功入库（库里已有分块）的复用文档不再重切分。
        # ingest_document(replace=True) 会先物理删除旧块，被 KAOYAN_ALLOW_PHYSICAL_DELETE
        # 闸门拦截，导致整篇入库失败——而重切分对「已Indexed」的文档既无必要也危险，
        # 直接复用既有分块即可。仅当复用文档还没有任何分块（上次入库被中断/失败）时才重切。
        if doc is not None and kb_service.has_searchable_chunks(db, doc.id):
            from models import KnowledgeChunk
            n_chunks = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.document_id == doc.id).count()
            out["reused_skip_ingest"] = True
        else:
            n_chunks = kb_service.ingest_document(db, doc, replace=True)
        # 分块是「可被 RAG 检索」的唯一凭据：库里一块都没有就不许标 indexed，
        # 否则又会多一篇「UI 说已入库、检索搜不到」的文档。
        doc.index_status = "indexed" if kb_service.has_searchable_chunks(
            db, doc.id) else "failed"
        db.commit()
        out["doc_id"] = doc.id
        out["chunks"] = n_chunks
        out["status"] = "ok" if v["ok"] else "ok-need-review"

        # --- 知识点抽取钩子（入库即长出结构化节点，而非事后补） ---
        # 独立 try：抽取失败绝不能回滚已成功的文档入库
        if extract_kp is None:
            extract_kp = kp_extract.KP_EXTRACT_ENABLED
        if extract_kp:
            try:
                out["knowledge_points"] = kp_extract.extract_kps_for_document(
                    db,
                    doc_id=doc.id,
                    text=text,
                    file_name=doc.file_name,
                    doc_subject=meta.get("subject", ""),
                    chapter=meta.get("chapter", ""),
                )
            except Exception as e:  # noqa: BLE001
                out["knowledge_points"] = {
                    "skipped": True, "reason": f"知识点抽取异常: {e}"[:200],
                    "kept": 0, "dropped": 0, "failed": 1,
                }
                logger.warning("知识点抽取失败 doc#%s: %s", doc.id, e)

        # --- chunk 三层标签钩子（docx/14 阶段 A：三路融合打标 + 文档聚合） ---
        # 独立 try：打标失败绝不能回滚已成功的文档入库（同知识点钩子的口径）。
        if classify_chunks is None:
            classify_chunks = chunk_classifier.CLASSIFY_ENABLED
        if classify_chunks:
            try:
                out["chunk_labels"] = chunk_classifier.classify_document(
                    db, doc.id, use_llm=use_llm_labels,
                )
            except Exception as e:  # noqa: BLE001
                out["chunk_labels"] = {"ok": False, "message": f"打标异常: {e}"[:200]}
                logger.warning("chunk 打标失败 doc#%s: %s", doc.id, e)

        if do_embeddings:
            import asyncio
            from services import embedding_service

            asyncio.run(embedding_service.build_all_embeddings(db, force=False))
    except Exception as e:  # noqa: BLE001
        try:
            db.rollback()
        except Exception as _exc:  # noqa: BLE001
            # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
            # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
            logging.getLogger(__name__).warning(
                '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
            )
        out["status"] = "error"
        out["reasons"].append(f"入库失败: {type(e).__name__}: {e}")
    return out


def _ocr_pdf_pages(path: str, ocr_backend: str,
                   max_pages: Optional[int] = None) -> Tuple[str, List[str], List[str], str]:
    """扫描件 PDF：逐页渲染成图 → 走图片分流识别 → 汇总。

    逐页处理可避免大 PDF 一次性渲染导致内存溢出（参考方案的"按页切片"）。

    渲染策略（修复点）：
      * 目标 DPI 默认 200，但**按页面物理尺寸自适应降采样**。
        资料库存在「整册扫描长图」PDF（实测单页 16.5in×84in），
        固定 200DPI 会渲染出 3306×16892 的巨图，OCR 侧直接静默返回空串。
      * 单页渲染失败不再中断整篇：记录该页错误后继续下一页，
        避免「第 1 页挂了→ 整篇 0 字」。

    Returns:
        (text, latex_list, figure_desc, engine)
        text 为空串表示**没有任何一页识别成功**（调用方须判失败，
        绝不能把错误信息当正文）。
    """
    texts: List[str] = []
    latex_all: List[str] = []
    figs: List[str] = []
    engine = ""
    page_errors: List[str] = []
    n_pages = 0
    n_ok = 0
    try:
        import pypdfium2 as pdfium
    except Exception as e:  # noqa: BLE001
        logger.error("pypdfium2 不可用，扫描件 PDF 无法渲染: %s", e)
        return "", [], [], ""

    tmpdir = None
    pdf = None
    try:
        pdf = pdfium.PdfDocument(path)
    except Exception as e:  # noqa: BLE001
        logger.error("PDF 打开失败 %s: %s", path, e)
        return "", [], [], ""

    try:
        n = len(pdf)
        if max_pages:
            n = min(n, max_pages)
        tmpdir = tempfile.mkdtemp(prefix="smart_pdf_")
        for i in range(n):
            page = None
            try:
                page = pdf[i]
                # --- 自适应渲染 scale：不超过 PDF_MAX_SIDE_PX ---
                try:
                    pw, ph = page.get_size()          # 单位 pt(1/72in)
                except Exception:
                    pw = ph = 0.0
                scale = PDF_RENDER_DPI / 72.0
                if pw > 0 and ph > 0:
                    longest_in = max(pw, ph) / 72.0
                    if longest_in * scale > PDF_MAX_SIDE_PX:
                        scale = PDF_MAX_SIDE_PX / longest_in
                if scale <= 0:
                    scale = PDF_RENDER_DPI / 72.0
                bitmap = page.render(scale=scale)
                # to_pil() 需要 Pillow；缺失时给出明确原因而非含糊的
                # "No module named 'PIL'"
                try:
                    pil = bitmap.to_pil()
                except Exception as e_pil:  # noqa: BLE001
                    raise RuntimeError(
                        f"PDF 渲染需要 Pillow(pillow)，当前不可用: {e_pil}。"
                        f"请执行 pip install pillow") from e_pil
                p = os.path.join(tmpdir, f"p{i:04d}.png")
                pil.save(p)
                page = None  # 及时释放上一页位图
                r = recognize_image(p, preprocess=False, ocr_backend=ocr_backend)
                if r["text"]:
                    texts.append(r["text"])
                    n_ok += 1
                else:
                    # 单页识别为空：记录后端与原因，继续下一页
                    page_errors.append(
                        f"第{i + 1}页无文字({r.get('ocr_used') or '无后端'}"
                        f": {(r.get('error') or '未识别到文字')[:60]})")
                latex_all.extend(r["latex_list"])
                figs.extend(r["figure_desc"])
                if not engine and r["ocr_used"]:
                    engine = r["ocr_used"]
            except Exception as e:  # noqa: BLE001
                # 单页异常不中断整篇
                page_errors.append(f"第{i + 1}页渲染/识别异常: {type(e).__name__}: {e}"[:160])
                logger.warning("PDF 第 %d 页失败(%s): %s", i + 1, os.path.basename(path), e)
    finally:
        try:
            pdf.close()
        except Exception as _exc:  # noqa: BLE001
            # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
            # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
            logging.getLogger(__name__).warning(
                '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
            )
        # 清理渲染出的页面 PNG 临时目录：原先 mkdtemp 后从不删除，
        # 全量入库（数千篇 × 每篇上百页）会在临时目录堆积数十 GB。
        if tmpdir:
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception as _exc2:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    '清理 PDF 渲染临时目录失败 %s: %s', tmpdir, str(_exc2)[:200]
                )

    n_pages = n
    if not texts:
        logger.error("扫描件 PDF 全部 %d 页均未识别到文字: %s | 前几条: %s",
                     n_pages, os.path.basename(path), page_errors[:3])
    else:
        logger.info("扫描件 PDF %s: %d/%d 页识别成功, engine=%s, 共 %d 字",
                    os.path.basename(path), n_ok, n_pages, engine,
                    sum(len(t) for t in texts))
    # 关键：**不再**把错误信息拼进正文。失败就是失败，返回空串。
    return "\n".join(texts), latex_all, figs, engine
