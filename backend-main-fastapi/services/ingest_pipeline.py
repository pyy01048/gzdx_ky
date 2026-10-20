# -*- coding: utf-8 -*-
"""块级文档入库管线（docx/34-OCR与数据采集开源方案 §10.3）。

链路：**分类 → 解析 → 落页 → 落块 → 切题 → 配图绑定 → 质量门禁 → 入库**

与既有模块的关系
----------------
* 解析层是 ``services/parsers/*``（另一条线实现）：产出 ``ParseResult``（页 + 块）。
  本模块**只消费** ``ParseResult``，不关心底下是 MinerU / PP-Structure / RapidOCR。
  路由入口 ``services.parsers.router.route_parse`` 在**函数内部延迟导入**，
  这样本模块在没有 OCR 依赖的环境里也能被 import 与测试。
* 切题复用 ``services.ocr_layout.cut_questions_from_blocks``（吃
  ``[{"text", "box", "score"}]``），本模块只做**适配**（ParsedBlock → 该入参）。
* 写库前的备份走 ``services.kb_service.ensure_write_backup``（内部调
  ``services.backup_service.create_backup``，测试沙箱库自动跳过）。

设计纪律
--------
1. **幂等**：同一份文档重复 ingest，``document_pages`` 行数不变（按
   ``(document_id, page_no)`` upsert），``document_blocks`` 先删后插、不重复。
2. **不猜**：切不出题就 ``questions=[]``，配图配不上就 ``figure_missing += 1``，
   绝不硬塞一张不相干的图，也绝不因为切题失败而抛异常。
3. **页码 1 基**：全链路（document_pages / document_blocks / 题目配图）与
   ``services/parsers/base.py`` 的 ``ParsedPage.page_no`` 同基线。
4. **不写死路径**：所有路径来自入参；图片只落相对路径。
"""
from __future__ import annotations

import hashlib
import inspect
import logging
import os
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

#: 质量门禁四档（docx/34 §4.7）
GRADE_A = "A"        # 题干 + 选项 + 答案 + 解析齐全
GRADE_B = "B"        # 题干 + 答案（主观题/判断题，或选择题缺解析）
GRADE_C = "C"        # 题干完整但缺答案（进复核队列）
GRADE_JUNK = "JUNK"  # 解析/目录/页眉页脚/题干过短 —— 丢弃但留日志

GRADE_ORDER: Tuple[str, ...] = (GRADE_A, GRADE_B, GRADE_C, GRADE_JUNK)

#: 题干过短阈值（字数，计入标点）
MIN_STEM_LENGTH = 8

#: figure 块与题干块的垂直邻近阈值（像素，渲染 DPI 下的页内坐标）
DEFAULT_MAX_VERTICAL_GAP = 200.0

#: 配图类型
IMAGE_KIND_FIGURE_CROP = "figure_crop"

# --------------------------------------------------------------------------- #
# 正则
# --------------------------------------------------------------------------- #

#: 选项前缀：A. / A、 / A） / (A)
_OPT_PREFIX_RE = re.compile(r"^\s*[（(]?\s*([A-Ha-h])\s*[）)、.．:：]\s*")

#: 答案里的字母（只认「纯字母 + 分隔符」形态，避免把主观题答案误判成选项）
_ANSWER_LETTERS_RE = re.compile(r"^\s*[A-Ha-h][A-Ha-h\s,，、;；.．]*$")

#: 答案前缀（"答案：A"）
_ANSWER_PREFIX_RE = re.compile(r"^\s*(?:正确答案|参考答案|答案)\s*[:：]?\s*")

#: 图编号：图1-3 / 图 1.3 / 图1－3
_FIG_PAIR_RE = re.compile(r"图\s*(\d{1,3})\s*[-－—.．]\s*(\d{1,3})")
#: 单号图：图3（后面不接数字或分隔符）
_FIG_SINGLE_RE = re.compile(r"图\s*(\d{1,3})(?![0-9\-－—.．])")

#: 题干/图注里的「指图」措辞：如图 / 图所示 / 下图 / 上图
_FIG_MENTION_RE = re.compile(r"如\s*图|图\s*所\s*示|下\s*图|上\s*图")

#: 解析/目录/页眉页脚等噪声前缀（JUNK 判定）
_JUNK_PREFIX_RE = re.compile(
    r"^\s*(?:参考)?(?:答案解析|答案与解析|参考答案|答案|解析|目\s*录|页眉|页脚|试卷答案)"
)
#: 纯页码行：第 3 页 / 3 / 共 5 页
_JUNK_PAGE_LINE_RE = re.compile(r"^\s*(?:第\s*)?\d{1,4}\s*(?:页|/|\|)?\s*(?:共\s*\d{1,4}\s*页)?\s*$")


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _get(obj: Any, key: str, default: Any = None) -> Any:
    """同时兼容 dataclass/对象与 dict 的取值。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bbox(box: Any) -> Optional[Tuple[float, float, float, float]]:
    """把各种 bbox 形态归一成 ``(x0, y0, x1, y1)``。

    支持：``(x0,y0,x1,y1)`` 四元组、``[x0,y0,x1,y1]`` 列表、4 点多边形
    ``[[x,y],...]``、``[x, y, w, h]``。返回 None 表示不可用。
    """
    if not box:
        return None
    if isinstance(box, dict):
        x0, y0 = box.get("x0"), box.get("y0")
        x1, y1 = box.get("x1"), box.get("y1")
        if None not in (x0, y0, x1, y1):
            return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        return None
    try:
        items = list(box)
    except TypeError:
        return None
    if not items:
        return None
    if all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in items):
        xs = [float(p[0]) for p in items]
        ys = [float(p[1]) for p in items]
        return (min(xs), min(ys), max(xs), max(ys))
    if len(items) >= 4 and all(isinstance(v, (int, float)) for v in items[:4]):
        x0, y0, a, b = (float(v) for v in items[:4])
        # 判定是 [x0,y0,x1,y1] 还是 [x,y,w,h]：宽高都远大于 0 时按 xyxy 解释，
        # 否则按 xywh 解释（两者在 x1<x0 / y1<y0 时必然是 xywh）。
        if a < x0 or b < y0:
            return (x0, y0, x0 + a, y0 + b)
        return (x0, y0, a, b)
    if len(items) >= 2 and all(isinstance(v, (int, float)) for v in items[:2]):
        return (float(items[0]), float(items[1]), float(items[0]), float(items[1]))
    return None


def _bbox_area(bbox: Optional[Tuple[float, float, float, float]]) -> float:
    if not bbox:
        return 0.0
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _vertical_gap(
    span: Optional[Tuple[float, float]],
    bbox: Optional[Tuple[float, float, float, float]],
) -> float:
    """两个纵向区间的距离（重叠算 0）。"""
    if not span or not bbox:
        return float("inf")
    top, bottom = span
    f_top, f_bottom = bbox[1], bbox[3]
    if f_bottom < top:
        return top - f_bottom
    if f_top > bottom:
        return f_top - bottom
    return 0.0


def _vspan(boxes: Iterable[Any]) -> Optional[Tuple[float, float]]:
    tops: List[float] = []
    bottoms: List[float] = []
    for box in boxes:
        bb = _as_bbox(box)
        if not bb:
            continue
        tops.append(bb[1])
        bottoms.append(bb[3])
    if not tops:
        return None
    return (min(tops), max(bottoms))


# --------------------------------------------------------------------------- #
# 质量门禁（docx/34 §4.7）
# --------------------------------------------------------------------------- #
def normalize_options(options: Any) -> Dict[str, str]:
    """把多种写法的选项归一成 ``{key: text}``。

    支持：``["A. xxx", "B. yyy"]``、``[{"key": "A", "text": "xxx"}]``、
    ``{"A": "xxx"}``、``"A. xxx"``。
    """
    out: Dict[str, str] = {}
    if not options:
        return out
    if isinstance(options, dict):
        for key, value in options.items():
            k = str(key).strip().upper()[:1]
            v = str(value or "").strip()
            if k and v:
                out[k] = v
        return out
    if isinstance(options, str):
        options = [options]
    for item in options:
        if isinstance(item, dict):
            key = str(item.get("key") or "").strip().upper()[:1]
            text = str(item.get("text") or "").strip()
        else:
            text = str(item or "").strip()
            m = _OPT_PREFIX_RE.match(text)
            key = m.group(1).upper() if m else ""
            if m:
                text = text[m.end():].strip()
        if key and text:
            out[key] = text
    return out


def _answer_letters(answer: str) -> str:
    """从答案里抽出选项字母（非「纯字母」形态返回空串）。"""
    if not answer:
        return ""
    text = _ANSWER_PREFIX_RE.sub("", answer.strip())
    if not _ANSWER_LETTERS_RE.match(text):
        return ""
    return "".join(ch for ch in text if ch.isalpha()).upper()


def check_question(q: Dict[str, Any]) -> Tuple[str, List[str]]:
    """给一道题定级。返回 ``(等级, 问题列表)``。

    规则（docx/34 §4.7）：
    * JUNK：题干过短（< 8 字）/ 空题干 / 解析、目录、页眉页脚等噪声段。
    * A：题干 + 选项 + 答案 + 解析齐全。
    * B：题干 + 答案（主观题/判断题；选择题缺解析也只到 B）。
    * C：题干完整但缺答案（或答案字母不在选项里 → 强制降级 C）。
    """
    issues: List[str] = []
    stem = str(q.get("stem") or q.get("content") or "").strip()
    options = normalize_options(q.get("options"))
    answer = str(q.get("answer") or "").strip()
    analysis = str(q.get("analysis") or "").strip()

    if not stem:
        return GRADE_JUNK, ["empty_stem"]
    if len(stem) < MIN_STEM_LENGTH:
        return GRADE_JUNK, ["stem_too_short"]
    if _JUNK_PREFIX_RE.match(stem) or _JUNK_PAGE_LINE_RE.match(stem):
        return GRADE_JUNK, ["junk_section_marker"]

    if not answer:
        issues.append("missing_answer")
        return GRADE_C, issues

    if options:
        letters = _answer_letters(answer)
        if letters and not set(letters).issubset(set(options)):
            # 答案字母不在选项 key 里 —— 直接降级 C，题不可用
            issues.append("answer_not_in_options")
            return GRADE_C, issues

    if not options:
        # 主观题/判断题：题干 + 答案即 B
        return GRADE_B, issues
    if not analysis:
        issues.append("missing_analysis")
        return GRADE_B, issues
    return GRADE_A, issues


def grade_question(q: Dict[str, Any]) -> str:
    """质量门禁：返回 'A' / 'B' / 'C' / 'JUNK'。"""
    return check_question(q)[0]


# --------------------------------------------------------------------------- #
# 配图绑定（docx/34 §4.5 第 7 条：三信号）
# --------------------------------------------------------------------------- #
def _figure_refs(text: str) -> Tuple[set, set]:
    """抽出文本里的图编号。返回 ``(带小节的编号集合, 单号集合)``。

    ``"如图1-3所示"`` → ``({"1-3"}, set())``；``"见图3"`` → ``(set(), {"3"})``。
    """
    if not text:
        return set(), set()
    pairs = {f"{m.group(1)}-{m.group(2)}" for m in _FIG_PAIR_RE.finditer(text)}
    singles = {m.group(1) for m in _FIG_SINGLE_RE.finditer(text)}
    singles -= {p.split("-")[0] for p in pairs}
    return pairs, singles


def _mentions_figure(text: str) -> bool:
    """题干/图注是否在「指图」（如图 / 图所示 / 下图 / 上图）。"""
    if not text:
        return False
    return bool(_FIG_MENTION_RE.search(text))


def bind_question_images(
    questions: Sequence[Dict[str, Any]],
    figures: Sequence[Dict[str, Any]],
    *,
    max_vertical_gap: float = DEFAULT_MAX_VERTICAL_GAP,
) -> Dict[str, Any]:
    """三信号配图绑定。纯函数（不碰数据库），便于单测。

    参数
    ----
    questions: 切题产物，形如
        ``{"qno": 1, "stem": "...", "page": 3, "blocks": [{"text":..., "box": [...]}]}``
    figures: figure 块，形如
        ``{"page_no": 3, "block_id": "f1", "text": "图1-3 ...", "image_path": "...",
           "bbox": [x0, y0, x1, y1]}``

    绑定策略（宁缺毋滥，绝不硬塞）
    ------------------------------
    * **信号1 图注匹配**：题干里的图编号（图1-3）与图注文本里的编号一致 → 绑，
      不看距离（编号是显式引用）。题干带编号时**只**认编号一致的图，
      不走邻近兜底 —— 否则「图1-3」的题会被旁边那张「图2-1」误绑。
    * **信号2+3 措辞 + 邻近**：题干只说「如图」没有编号 → 必须**同页**且
      figure 块与题干块的垂直距离 < ``max_vertical_gap`` 才绑。
    * 都没命中但题干确实提了图 → 记 ``figure_missing``（宁可标记缺图，
      也不绑一张不相干的图）。

    返回
    ----
    ``{"bindings": [...], "missing": [...], "figures_bound": n, "figure_missing": m}``
    """
    by_page: Dict[int, List[Dict[str, Any]]] = {}
    for fig in figures or []:
        page_no = int(_get(fig, "page_no", 0) or 0)
        by_page.setdefault(page_no, []).append(fig)

    bindings: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []

    for q_index, q in enumerate(questions or []):
        page_no = int(_get(q, "page", 0) or _get(q, "page_no", 0) or 0)
        stem = str(_get(q, "stem", "") or "")
        page_figs = by_page.get(page_no, [])

        stem_pairs, stem_singles = _figure_refs(stem)
        mentions = _mentions_figure(stem) or bool(stem_pairs or stem_singles)

        matched: List[Dict[str, Any]] = []
        signals: List[str] = []

        # —— 信号1：图注编号匹配 ——
        if stem_pairs or stem_singles:
            for fig in page_figs:
                fig_pairs, fig_singles = _figure_refs(str(_get(fig, "text", "") or ""))
                hit = False
                if stem_pairs and (stem_pairs & fig_pairs):
                    hit = True
                elif not stem_pairs and stem_singles and (stem_singles & fig_singles):
                    hit = True
                if hit:
                    matched.append(fig)
                    if "caption" not in signals:
                        signals.append("caption")

        # —— 信号2 + 信号3：题干「如图」+ 同页邻近 ——
        # 题干带**编号**时只认编号一致的图（编号是显式引用，宁缺毋滥），
        # 不走邻近兜底 —— 否则「图1-3」的题会被旁边的「图2-1」误绑。
        if not matched and mentions and not stem_pairs and not stem_singles:
            span = _vspan([_get(b, "box", None) for b in (_get(q, "blocks", None) or [])])
            if span:
                cands: List[Tuple[float, Dict[str, Any]]] = []
                for fig in page_figs:
                    bb = _as_bbox(_get(fig, "bbox", None))
                    if not bb:
                        continue
                    gap = _vertical_gap(span, bb)
                    if gap <= max_vertical_gap:
                        cands.append((gap, fig))
                cands.sort(key=lambda item: item[0])
                if cands:
                    matched = [fig for _gap, fig in cands]
                    signals.extend(["stem_mentions_figure", "bbox_proximity"])

        if matched:
            # 主图 = 面积最大的那个
            sized = [(fig, _bbox_area(_as_bbox(_get(fig, "bbox", None)))) for fig in matched]
            primary = max(sized, key=lambda item: item[1])[0] if sized else matched[0]
            for fig in matched:
                bbox = _as_bbox(_get(fig, "bbox", None))
                bindings.append({
                    "question_index": q_index,
                    "qno": _get(q, "qno", None),
                    "page_no": page_no,
                    "block_id": str(_get(fig, "block_id", "") or ""),
                    "image_path": str(_get(fig, "image_path", "") or ""),
                    "caption": str(_get(fig, "text", "") or ""),
                    "bbox": list(bbox) if bbox else None,
                    "area": _bbox_area(bbox),
                    "width": int(bbox[2] - bbox[0]) if bbox else None,
                    "height": int(bbox[3] - bbox[1]) if bbox else None,
                    "signals": list(signals),
                    "is_primary": fig is primary,
                })
        elif mentions:
            missing.append({
                "question_index": q_index,
                "qno": _get(q, "qno", None),
                "page_no": page_no,
                "reason": "figure_referenced_but_not_bound",
            })

    return {
        "bindings": bindings,
        "missing": missing,
        "figures_bound": len(bindings),
        "figure_missing": len(missing),
    }


# --------------------------------------------------------------------------- #
# 解析结果的归一化
# --------------------------------------------------------------------------- #
def _default_parse_fn() -> Callable[..., Any]:
    """延迟导入路由入口（没装 OCR 依赖时也能 import 本模块）。"""
    from services.parsers.router import route_parse

    return route_parse


def _call_parse(
    fn: Callable[..., Any],
    pdf_path: str,
    *,
    max_pages: Optional[int] = None,
    out_dir: Optional[str] = None,
) -> Any:
    """按被调函数**实际签名**传参，兼容只吃 ``(pdf_path)`` 的假实现。"""
    try:
        sig = inspect.signature(fn)
        params = sig.parameters
        has_var_kw = any(p.kind == p.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):  # pragma: no cover - 不可 introspect 的 callable
        return fn(pdf_path)
    kwargs: Dict[str, Any] = {}
    if max_pages is not None and (has_var_kw or "max_pages" in params):
        kwargs["max_pages"] = max_pages
    if out_dir is not None and (has_var_kw or "out_dir" in params):
        kwargs["out_dir"] = out_dir
    return fn(pdf_path, **kwargs)


def _pages_of(result: Any) -> List[Any]:
    pages = _get(result, "pages", None) or []
    return list(pages)


def _blocks_of(result: Any) -> List[Any]:
    blocks = _get(result, "blocks", None)
    if blocks is None:
        blocks = []
        for page in _pages_of(result):
            blocks.extend(_get(page, "blocks", None) or [])
    return list(blocks)


def _figure_payloads(blocks: Sequence[Any]) -> List[Dict[str, Any]]:
    """挑出 figure 块，整理成配图绑定用的载荷。"""
    out: List[Dict[str, Any]] = []
    for block in blocks or []:
        if str(_get(block, "block_type", "") or "") != "figure":
            continue
        bbox = _as_bbox(_get(block, "bbox", None))
        out.append({
            "page_no": int(_get(block, "page_no", 0) or 0),
            "block_id": str(_get(block, "block_id", "") or ""),
            "text": str(_get(block, "text", "") or ""),
            "image_path": str(_get(block, "image_path", "") or ""),
            "bbox": list(bbox) if bbox else None,
        })
    return out


# --------------------------------------------------------------------------- #
# 落库
# --------------------------------------------------------------------------- #
def _ensure_backup() -> Optional[str]:
    """写库前备份。测试沙箱库内部自动跳过；备份失败直接抛（不降级）。"""
    from services.kb_service import ensure_write_backup

    return ensure_write_backup()


def _resolve_document_id(db, pdf_path: str, document_id: Optional[int], subject: str) -> int:
    """定位（或新建）documents 行，返回 document_id。"""
    from models import Document

    if document_id is not None:
        row = db.get(Document, document_id)
        if row is None:
            raise ValueError(f"document_id={document_id} 在 documents 表里不存在")
        return int(document_id)

    doc = Document(
        file_name=os.path.basename(pdf_path),
        file_path=pdf_path,
        source_format="pdf",
        subject=(subject or None) and str(subject)[:50],
    )
    db.add(doc)
    db.flush()
    return int(doc.id)


def _upsert_pages(db, document_id: int, pages: Sequence[Any], engine: str = "") -> int:
    """按 ``(document_id, page_no)`` upsert 页。重复跑不产生重复行。"""
    from models import DocumentPage

    existing = {
        int(row.page_no): row
        for row in db.query(DocumentPage).filter(DocumentPage.document_id == document_id).all()
    }
    count = 0
    for page in pages or []:
        page_no = int(_get(page, "page_no", 0) or 0)
        if page_no < 1:
            continue
        row = existing.get(page_no)
        if row is None:
            row = DocumentPage(document_id=document_id, page_no=page_no)
            db.add(row)
        row.width = _as_float(_get(page, "width", None))
        row.height = _as_float(_get(page, "height", None))
        row.text = _get(page, "text", None)
        row.layout_json = _get(page, "layout_json", None)
        row.image_path = _get(page, "image_path", None) or None
        row.ocr_engine = (_get(page, "ocr_engine", None) or engine or None)
        row.ocr_confidence = _as_float(_get(page, "ocr_confidence", None))
        count += 1
    db.flush()
    return count


def _replace_blocks(db, document_id: int, blocks: Sequence[Any], page_nos: Sequence[int]) -> int:
    """先按 ``(document_id, page_no)`` 删旧块再插新块（幂等）。"""
    from models import DocumentBlock

    if page_nos:
        db.query(DocumentBlock).filter(
            DocumentBlock.document_id == document_id,
            DocumentBlock.page_no.in_(list(page_nos)),
        ).delete(synchronize_session=False)
        db.flush()

    rows: List[DocumentBlock] = []
    for block in blocks or []:
        page_no = int(_get(block, "page_no", 0) or 0)
        if page_no < 1:
            continue
        bbox = _as_bbox(_get(block, "bbox", None))
        rows.append(DocumentBlock(
            document_id=document_id,
            page_no=page_no,
            block_id=(str(_get(block, "block_id", "") or "") or None),
            block_type=(str(_get(block, "block_type", "") or "") or None),
            bbox=list(bbox) if bbox else None,
            text=_get(block, "text", None),
            latex=_get(block, "latex", None) or None,
            image_path=_get(block, "image_path", None) or None,
            reading_order=_get(block, "reading_order", None),
            confidence=_as_float(_get(block, "confidence", None)),
        ))
    if rows:
        db.bulk_save_objects(rows)
    db.flush()
    return len(rows)


def _write_question_images(db, document_id: int, bindings: Sequence[Dict[str, Any]]) -> int:
    """落题目配图。先删本文档的旧配图，保证重复 ingest 不产生重复行。"""
    from models import QuestionImage

    db.query(QuestionImage).filter(QuestionImage.document_id == document_id).delete(
        synchronize_session=False
    )
    db.flush()

    rows: List[QuestionImage] = []
    for item in bindings or []:
        bbox = item.get("bbox")
        rows.append(QuestionImage(
            question_id=item.get("question_id"),
            document_id=document_id,
            page_no=item.get("page_no"),
            image_path=item.get("image_path") or None,
            image_hash=_file_sha256(item.get("image_path")),
            phash=item.get("phash") or None,
            bbox=bbox,
            image_kind=IMAGE_KIND_FIGURE_CROP,
            caption=(item.get("caption") or None) and str(item["caption"])[:1000],
            width=item.get("width"),
            height=item.get("height"),
            is_primary=bool(item.get("is_primary")),
        ))
    if rows:
        db.bulk_save_objects(rows)
    db.flush()
    return len(rows)


def _file_sha256(path: Optional[str]) -> Optional[str]:
    """文件 sha256（算不出就返回 None，不阻塞入库）。"""
    if not path or not os.path.isfile(path):
        return None
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:  # pragma: no cover - 读不动就跳过
        return None


# --------------------------------------------------------------------------- #
# 切题适配
# --------------------------------------------------------------------------- #
def _cut_questions(pages: Sequence[Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """把解析块适配成 ``cut_questions_from_blocks`` 的入参并切题。

    返回 ``(questions, issues)``；切题失败不抛，只记 issue 并返回空列表。
    """
    from services.ocr_layout import cut_questions_from_blocks

    questions: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    for page in pages or []:
        page_no = int(_get(page, "page_no", 0) or 0)
        if page_no < 1:
            continue
        blocks_in: List[Dict[str, Any]] = []
        for block in _get(page, "blocks", None) or []:
            block_type = str(_get(block, "block_type", "") or "")
            if block_type in ("header", "footer", "page_no", "unknown", "figure"):
                # 页眉页脚页码不参与切题；figure 块的图注留给配图信号1
                continue
            text = str(_get(block, "latex", "") or "") or str(_get(block, "text", "") or "")
            if not text.strip():
                continue
            bbox = _as_bbox(_get(block, "bbox", None))
            blocks_in.append({
                "text": text.strip(),
                "box": list(bbox) if bbox else None,
                "score": _as_float(_get(block, "confidence", None)),
            })
        if not blocks_in:
            continue
        try:
            page_questions = cut_questions_from_blocks(blocks_in, page=page_no)
        except Exception as exc:  # noqa: BLE001 - 切题失败不拖垮整条管线
            issues.append({"code": "cut_questions_failed", "page_no": page_no, "detail": str(exc)[:200]})
            continue
        for q in page_questions or []:
            q["page"] = page_no
            questions.append(q)
    return questions, issues


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def ingest_pdf(
    db,
    pdf_path: str,
    *,
    document_id: Optional[int] = None,
    subject: str = "",
    max_pages: Optional[int] = None,
    out_dir: Optional[str] = None,
    parse_fn: Optional[Callable[..., Any]] = None,
    write: bool = True,
    cut_questions: bool = True,
) -> Dict[str, Any]:
    """把一份 PDF 走完「解析 → 落页 → 落块 → 切题 → 配图 → 质检 → 入库」。

    参数
    ----
    db: 调用方传入的 SQLAlchemy Session。本函数内部 **commit 一次**；
        出错时 rollback 后把异常抛给调用方。
    pdf_path: PDF 路径（不写死任何机器路径）。
    document_id: 已有文档 ID；为 None 时新建一条 ``documents`` 记录。
    subject: 科目（新建文档时写进 ``documents.subject``）。
    max_pages / out_dir: 透传给解析器。
    parse_fn: 解析函数注入点；默认延迟 import ``services.parsers.router.route_parse``。
    write: False = 干跑，只统计不写库。
    cut_questions: False = 不切题（只落页/块）。

    返回
    ----
    ``{"document_id", "engine", "pdf_kind", "pages", "blocks", "questions",
      "figures_bound", "figure_missing", "grades", "issues", "elapsed_seconds"}``
    """
    started = time.time()
    issues: List[Dict[str, Any]] = []
    grades: Dict[str, int] = {g: 0 for g in GRADE_ORDER}

    fn = parse_fn if parse_fn is not None else _default_parse_fn()
    try:
        result = _call_parse(fn, pdf_path, max_pages=max_pages, out_dir=out_dir)
    except Exception:
        db.rollback()
        raise

    pages = _pages_of(result)
    blocks = _blocks_of(result)
    engine = str(_get(result, "engine", "") or "")
    pdf_kind = str(_get(result, "pdf_kind", "") or "")

    # —— 切题 ——
    questions: List[Dict[str, Any]] = []
    if cut_questions:
        questions, cut_issues = _cut_questions(pages)
        issues.extend(cut_issues)

    # —— 质量门禁 ——
    for q in questions:
        grade, q_issues = check_question(q)
        grades[grade] = grades.get(grade, 0) + 1
        for code in q_issues:
            issues.append({
                "code": code,
                "qno": q.get("qno"),
                "page_no": q.get("page"),
                "grade": grade,
            })

    # —— 配图绑定（三信号）——
    binding = bind_question_images(questions, _figure_payloads(blocks))
    bindings = binding["bindings"]
    for item in binding["missing"]:
        issues.append({
            "code": "figure_missing",
            "qno": item.get("qno"),
            "page_no": item.get("page_no"),
        })

    resolved_document_id = document_id
    pages_written = 0
    blocks_written = 0
    images_written = 0

    if write:
        try:
            resolved_document_id = _resolve_document_id(db, pdf_path, document_id, subject)
            page_nos = [int(_get(p, "page_no", 0) or 0) for p in pages]
            page_nos = [n for n in page_nos if n >= 1]

            # 有旧数据要覆盖 → 先备份（写前备份是红线）
            from models import DocumentBlock, DocumentPage

            has_old = False
            if page_nos:
                has_old = db.query(DocumentBlock.id).filter(
                    DocumentBlock.document_id == resolved_document_id,
                    DocumentBlock.page_no.in_(page_nos),
                ).first() is not None
                has_old = has_old or db.query(DocumentPage.id).filter(
                    DocumentPage.document_id == resolved_document_id,
                    DocumentPage.page_no.in_(page_nos),
                ).first() is not None
            if has_old:
                _ensure_backup()

            pages_written = _upsert_pages(db, resolved_document_id, pages, engine=engine)
            blocks_written = _replace_blocks(db, resolved_document_id, blocks, page_nos)
            if bindings:
                images_written = _write_question_images(db, resolved_document_id, bindings)
            db.commit()
        except Exception:
            db.rollback()
            raise

    return {
        "document_id": resolved_document_id,
        "engine": engine,
        "pdf_kind": pdf_kind,
        "pages": len(pages),
        "blocks": len(blocks),
        "questions": len(questions),
        "figures_bound": binding["figures_bound"],
        "figure_missing": binding["figure_missing"],
        "grades": grades,
        "issues": issues,
        "elapsed_seconds": round(time.time() - started, 3),
        "written": bool(write),
        "pages_written": pages_written,
        "blocks_written": blocks_written,
        "images_written": images_written,
    }
