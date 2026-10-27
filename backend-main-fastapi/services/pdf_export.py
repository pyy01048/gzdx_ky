"""PDF 导出服务（对标「不背单词」纸质导出体验）。

使用 reportlab 生成中文 PDF：
- 错题本：封面 + 每道错题一张卡片（题干/我的答案/正确答案/错因/解析/复习状态）
- 单词本：封面 + 单词表（单词/音标/词性/释义/词根/真题例句）

中文字体自动探测（Windows 黑体/雅黑 → Linux 文泉驿/Noto），
找不到中文字体时降级为 Helvetica（中文会变方框，但接口不报错）。
"""

import datetime
import io
import logging
import os

from utils.timeutil import local_today  # 统一「今天」按北京自然日（#19 时间口径）

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 中文字体注册（进程内只做一次）
# --------------------------------------------------------------------------- #
_FONT_CANDIDATES = [
    # Windows
    (r"C:\Windows\Fonts\msyh.ttc", "MicrosoftYaHei", 0),
    (r"C:\Windows\Fonts\simhei.ttf", "SimHei", None),
    (r"C:\Windows\Fonts\simsun.ttc", "SimSun", 0),
    (r"C:\Windows\Fonts\Deng.ttf", "DengXian", None),
    (r"C:\Windows\Fonts\simfang.ttf", "SimFang", None),
    (r"C:\Windows\Fonts\simkai.ttf", "SimKai", None),
    # Linux / macOS
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "WenQuanYiZenHei", None),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "NotoSansCJK", 0),
    ("/System/Library/Fonts/PingFang.ttc", "PingFangSC", 0),
    ("/System/Library/Fonts/STHeiti Light.ttc", "STHeiti", None),
]

_font_registered = False
_font_name = "Helvetica"


def _register_fonts() -> str:
    """注册中文字体，返回可用字体名。进程内幂等。"""
    global _font_registered, _font_name
    if _font_registered:
        return _font_name

    for path, name, subfont_index in _FONT_CANDIDATES:
        try:
            if not os.path.exists(path):
                continue
            if subfont_index is not None:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=subfont_index))
            else:
                pdfmetrics.registerFont(TTFont(name, path))
            _font_name = name
            _font_registered = True
            logger.info("PDF 中文字体已注册：%s (%s)", name, path)
            return _font_name
        except Exception as e:  # noqa: BLE001
            logger.warning("PDF 字体注册失败 %s: %s", path, e)

    _font_registered = True
    logger.warning("未找到中文字体，PDF 中文将显示为方框（降级 Helvetica）")
    return _font_name


def _font(bold: bool = False) -> str:
    """返回当前可用字体名（粗体用同一字体，reportlab 会合成）。"""
    return _font_name


def _ensure_font():
    _register_fonts()


# --------------------------------------------------------------------------- #
# 样式
# --------------------------------------------------------------------------- #
_PRIMARY = colors.HexColor("#4F46E5")   # 靛蓝
_ACCENT = colors.HexColor("#F59E0B")    # 琥珀
_SUCCESS = colors.HexColor("#10B981")
_DANGER = colors.HexColor("#EF4444")
_TEXT = colors.HexColor("#1F2937")
_MUTED = colors.HexColor("#6B7280")
_LIGHT = colors.HexColor("#F3F4F6")
_BORDER = colors.HexColor("#E5E7EB")


def _make_styles():
    _ensure_font()
    f = _font_name
    styles = getSampleStyleSheet()

    def _s(name, **kw):
        base = dict(fontName=f, fontSize=10, leading=15, textColor=_TEXT)
        base.update(kw)
        return ParagraphStyle(name, **base)

    return {
        "cover_title": _s("cover_title", fontName=f, fontSize=30, leading=38, textColor=_PRIMARY, alignment=TA_CENTER, spaceAfter=6),
        "cover_sub": _s("cover_sub", fontSize=14, leading=20, textColor=_MUTED, alignment=TA_CENTER),
        "cover_stat": _s("cover_stat", fontSize=11, leading=18, textColor=_TEXT, alignment=TA_CENTER),
        "h1": _s("h1", fontSize=18, leading=24, textColor=_PRIMARY, spaceBefore=6, spaceAfter=10),
        "h2": _s("h2", fontSize=13, leading=18, textColor=_TEXT, spaceBefore=10, spaceAfter=6),
        "section": _s("section", fontSize=11, leading=16, textColor=_MUTED, spaceAfter=8),
        "body": _s("body", fontSize=10, leading=16),
        "word": _s("word", fontSize=16, leading=22, textColor=_TEXT),
        "phonetic": _s("phonetic", fontSize=10, leading=14, textColor=_MUTED),
        "meaning": _s("meaning", fontSize=11, leading=17, textColor=_TEXT),
        "example": _s("example", fontSize=9.5, leading=15, textColor=_MUTED),
        "label": _s("label", fontSize=8.5, leading=12, textColor=_MUTED),
        "footer": _s("footer", fontSize=8, leading=10, textColor=_MUTED, alignment=TA_CENTER),
    }


# --------------------------------------------------------------------------- #
# 页眉页脚
# --------------------------------------------------------------------------- #
def _on_page(canvas, doc, title: str):
    """每页绘制页眉（标题）与页脚（页码）。"""
    canvas.saveState()
    _ensure_font()
    canvas.setFont(_font_name, 8)
    canvas.setFillColor(_MUTED)
    canvas.drawString(20 * mm, A4[1] - 12 * mm, title)
    canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 12 * mm, local_today().strftime("%Y-%m-%d"))
    canvas.setStrokeColor(_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, A4[1] - 14 * mm, A4[0] - 20 * mm, A4[1] - 14 * mm)
    canvas.setFont(_font_name, 8)
    canvas.drawCentredString(A4[0] / 2, 12 * mm, f"— {doc.page} —")
    canvas.restoreState()


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _safe_text(v, max_len: int = 2000) -> str:
    """转字符串并截断，避免超长文本撑爆排版。"""
    if v is None:
        return ""
    s = str(v).strip()
    return s[:max_len] + ("…" if len(str(v)) > max_len else "")


def _tag_text(tags) -> str:
    if not tags:
        return ""
    if isinstance(tags, list):
        return " ".join(str(t) for t in tags if t)
    return str(tags)


def _status_label(status: str) -> str:
    return {
        "active": "在练",
        "graduated": "已毕业",
        "archived": "已归档",
    }.get(status or "", status or "")


def _mastery_label(state: str) -> str:
    return {
        "unlearned": "未掌握",
        "weak": "薄弱",
        "mastered": "已掌握",
    }.get(state or "", state or "")


# --------------------------------------------------------------------------- #
# 错题本 PDF
# --------------------------------------------------------------------------- #
def build_errors_pdf(
    errors,
    *,
    title: str = "考研错题本",
    subtitle: str = "按艾宾浩斯遗忘曲线自动排期复习",
) -> bytes:
    """把错题列表渲染成 PDF 字节流。

    errors: 列表，每项含 content / my_answer / correct_answer / error_reason /
            error_category / subject / accuracy / review_count / status /
            mastery_label / tags / analysis / created_at。
    """
    _ensure_font()
    styles = _make_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=title,
        author="考研备考平台",
    )

    story = []
    # ---- 封面 ----
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph("📚", styles["cover_title"]))
    story.append(Paragraph(title, styles["cover_title"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(subtitle, styles["cover_sub"]))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        f"共 {len(errors)} 道错题 · 生成于 {local_today().strftime('%Y-%m-%d')}",
        styles["cover_stat"],
    ))
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="60%", thickness=1, color=_PRIMARY, hAlign="CENTER"))
    story.append(PageBreak())

    # ---- 错题卡片 ----
    for i, e in enumerate(errors, 1):
        subject = _safe_text(e.get("subject"), 50) or "未分类"
        status = _status_label(e.get("status"))
        mastery = _mastery_label(e.get("mastery_label"))
        tags = _tag_text(e.get("tags"))

        head_style = ParagraphStyle(
            "err_head", fontName=_font_name, fontSize=12, leading=16,
            textColor=_PRIMARY, spaceAfter=2,
        )
        story.append(Paragraph(
            f"第 {i} 题 · {subject}",
            head_style,
        ))
        story.append(Paragraph(
            f"状态：{status} · 掌握度：{mastery} · 复习 {e.get('review_count', 0)} 次"
            + (f" · 标签：{tags}" if tags else ""),
            styles["label"],
        ))
        story.append(Spacer(1, 3 * mm))

        rows = []
        if e.get("content"):
            rows.append([Paragraph(f"<b>题干</b>", styles["label"]), Paragraph(_safe_text(e["content"], 3000), styles["body"])])
        if e.get("my_answer"):
            rows.append([Paragraph("<b>我的答案</b>", styles["label"]), Paragraph(_safe_text(e["my_answer"], 2000), styles["body"])])
        if e.get("correct_answer"):
            rows.append([Paragraph("<b>正确答案</b>", styles["label"]), Paragraph(_safe_text(e["correct_answer"], 2000), styles["body"])])
        if e.get("error_reason") or e.get("error_category"):
            reason = " / ".join(filter(None, [_safe_text(e.get("error_category"), 50), _safe_text(e.get("error_reason"), 100)]))
            if reason:
                rows.append([Paragraph("<b>错因</b>", styles["label"]), Paragraph(reason, styles["body"])])
        if e.get("analysis"):
            rows.append([Paragraph("<b>解析</b>", styles["label"]), Paragraph(_safe_text(e["analysis"], 3000), styles["body"])])

        if rows:
            table = Table(rows, colWidths=[28 * mm, 124 * mm])
            table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), _LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.75, _BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, _BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(table)
        else:
            story.append(Paragraph(_safe_text(e.get("content"), 3000) or "（无内容）", styles["body"]))

        if i < len(errors):
            story.append(Spacer(1, 5 * mm))
            story.append(HRFlowable(width="100%", thickness=0.5, color=_BORDER))
            story.append(Spacer(1, 5 * mm))

    def _decorate(canvas, doc_):
        _on_page(canvas, doc_, title)

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# 单词本 PDF
# --------------------------------------------------------------------------- #
def build_words_pdf(
    words,
    *,
    title: str = "考研核心词汇",
    subtitle: str = "FSRS 间隔重复 · 真题例句",
    truncated: bool = False,
) -> bytes:
    """把单词列表渲染成 PDF 字节流。

    words: 列表，每项含 word / phonetic / pos / meaning / root / example /
           example_cn / tag / status / reps，可选 extra（{synonyms, phrases}）。
    truncated: 导出被截断时在封面提示。
    """
    _ensure_font()
    styles = _make_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=title,
        author="考研备考平台",
    )

    story = []
    # ---- 封面 ----
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph("📖", styles["cover_title"]))
    story.append(Paragraph(title, styles["cover_title"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(subtitle, styles["cover_sub"]))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        f"共 {len(words)} 词 · 生成于 {local_today().strftime('%Y-%m-%d')}"
        + (" · 已按 5000 词上限截断，可加筛选后再导出" if truncated else ""),
        styles["cover_stat"],
    ))
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="60%", thickness=1, color=_PRIMARY, hAlign="CENTER"))
    story.append(PageBreak())

    # ---- 单词条目 ----
    for i, w in enumerate(words, 1):
        word = _safe_text(w.get("word"), 100)
        phonetic = _safe_text(w.get("phonetic"), 100)
        pos = _safe_text(w.get("pos"), 50)
        meaning = _safe_text(w.get("meaning"), 2000)
        root = _safe_text(w.get("root"), 300)
        example = _safe_text(w.get("example"), 1000)
        example_cn = _safe_text(w.get("example_cn"), 1000)
        tag = _safe_text(w.get("tag"), 50)
        status = {
            "new": "新词",
            "learning": "学习中",
            "reviewing": "复习中",
            "mastered": "已掌握",
        }.get(w.get("status"), _safe_text(w.get("status"), 20) or "新词")

        # 单词行：序号 + 单词 + 音标 + 状态徽标
        head = ParagraphStyle(
            "w_head", fontName=_font_name, fontSize=14, leading=20, textColor=_TEXT,
        )
        story.append(Paragraph(
            f"{i}. {word}"
            + (f"  <font color='#6B7280' size=10>{phonetic}</font>" if phonetic else "")
            + (f"  <font color='#4F46E5' size=9>[{tag}]</font>" if tag else "")
            + f"  <font color='#9CA3AF' size=8>（{status}）</font>",
            head,
        ))
        story.append(Spacer(1, 1.5 * mm))

        # 释义行
        meaning_text = f"{pos} {meaning}".strip()
        if meaning_text:
            story.append(Paragraph(meaning_text, styles["meaning"]))
        if root:
            story.append(Paragraph(f"词根：{root}", styles["example"]))
        # 同近义/短语（words.extra，KyleBing 结构化数据）
        extra = w.get("extra")
        if isinstance(extra, dict):
            synos = extra.get("synonyms") or []
            syno_texts = []
            for s in synos[:6]:
                words_list = s.get("words") or []
                if words_list:
                    syno_texts.append(f"{s.get('pos','')} {' / '.join(words_list)}")
            if syno_texts:
                story.append(Paragraph(
                    f"同近义：{'；'.join(syno_texts)}",
                    styles["example"],
                ))
            phrases = extra.get("phrases") or []
            if phrases:
                ph_texts = [f"{p.get('phrase','')}（{p.get('cn','')}）" for p in phrases[:4] if p.get("phrase")]
                if ph_texts:
                    story.append(Paragraph(
                        f"短语：{'；'.join(ph_texts)}",
                        styles["example"],
                    ))
        if example:
            story.append(Paragraph(
                f"例：{example}" + (f"　{example_cn}" if example_cn else ""),
                styles["example"],
            ))

        if i < len(words):
            story.append(Spacer(1, 3.5 * mm))
            story.append(HRFlowable(width="100%", thickness=0.4, color=_BORDER))
            story.append(Spacer(1, 3.5 * mm))

    def _decorate(canvas, doc_):
        _on_page(canvas, doc_, title)

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    return buf.getvalue()