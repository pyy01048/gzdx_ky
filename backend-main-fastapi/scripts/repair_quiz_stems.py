"""修复题库题干里被丢弃的公式（从**源 docx** 精准重取，不走 PDF OCR）。

背景
----
题库里有一批题干长成这样：

    设，则数列有界是数列收敛的（　　）．[数二2012研]
    ④设，并存在极限，若收敛，则.中正确的是（　　）．
    设函数，则（　　）．[数二 2013研]

公式位全是空的。实测 386 道题里 **31 道**（8%）有这个问题。

## 为什么走 docx 而不是 PDF（本脚本最关键的决定）

第一版按 `origin_document_id` + `source_page` 去找 PDF 页重解析，结果：
doc 43 的第 22 页是「第一章函数与极限」的课后习题，而题目标着 `[数二2012研]`
是真题——**归属错得离谱**。

看 `source_label` 就明白了：

    同济大学数学系《高等数学》（第7版）（下册）配套题库【考研真题＋课后习题＋…】.docx

**这些题本来就来自 docx 题库**，`origin_document_id` 指向的 PDF 是错误归属
（`source_page` 也不可靠——早前就发现「题 151 标 page=25，但该页其实是公式手册」）。

改走 docx 之后：
* 定位**精确**（`locate()` 直接命中，连前缀兜底都不用）；
* 速度**快 20 倍**（1–2 分钟 vs PDF 每页 162 秒 × 14 页）；
* 公式图就在 docx 里，裁出来直接喂 `formula_latex`。

## 方法

1. 残句 → `source_label` → 匹配 `documents.file_name`，拿 docx 路径；
2. `parse_docx_with_images` + `build_aligned` 得到「文字 + `[[F:n]]` 占位符」；
3. 用残句在 `aligned.plain` 里精确定位（残句是完整题干的子序列）；
4. 取 `aligned.marked` 对应片段，按需导出图 → 识别成 LaTeX；
5. 合成新题干，干跑打印 before/after 供核对。

**默认干跑。** 题库是用户直接看的，宁可不修，也不写错。

用法
----
```
python scripts/repair_quiz_stems.py --limit 5      # 看能修几道
python scripts/repair_quiz_stems.py --quiz-id 308  # 指定题目
python scripts/repair_quiz_stems.py --apply        # 真写
```
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_formula import (  # noqa: E402
    MARKER_RE,
    build_aligned,
    parse_docx_with_images,
)

# 题干残缺的强特征（来自实测的 31 道题）
# 解析里的公式缺口特征：「逗号 + 连词」说明中间丢了公式
#     由知在x＝0处可导 / 即 又，故 / f（x）的在上单调上升
ANALYSIS_GAP_PATTERN = re.compile(
    r"[，,]\s*(又|则|故|即|得|知|有|且|因而|因此|所以|由|据)|"
    r"[的了]\s*[，,．.]|"
    r"[，,]\s*[，,]"
)

SUSPECT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"设\s*则"), "设则"),
    (re.compile(r"则\s*在\s*[（(]"), "则在("),
    (re.compile(r"因为\s*$"), "因为结尾"),
    (re.compile(r"对于\s*[，,]"), "对于，"),
    (re.compile(r"[，,]\s*[，,]"), "连续逗号"),
    (re.compile(r"是\s*数列"), "是数列"),
    (re.compile(r"设\s*是"), "设是"),
    (re.compile(r"函数\s*[，,]"), "函数逗号"),
]

_WS_RE = re.compile(r"\s+")
_FW_SPACE = "　"
# 已渲染过的标记（重复修复时用）
_RENDERED_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RENDERED_TEX_RE = re.compile(r"\${1,2}[^$]*\${1,2}")
# 旧管线留下的公式占位符。**必须一起剥掉**：解析里有 32 道题就是带着
# `[[F:5230]]` 这种原始占位符入库的，拿它原文去 docx 里找当然找不到，
# 结果是「定位成功 218 / 写库 154」里被漏掉的那批。
_MARKER_ONLY_RE = re.compile(r"\[\[F:\d+\]\]")


def norm(text: str) -> str:
    return _WS_RE.sub("", (text or "").replace(_FW_SPACE, " "))


def strip_rendered(text: str) -> str:
    """剥掉已写入的 LaTeX/图片标记/旧占位符，还原成原文形态（支持重复修复）。"""
    t = _RENDERED_IMG_RE.sub("", text or "")
    t = _RENDERED_TEX_RE.sub("", t)
    t = _MARKER_ONLY_RE.sub("", t)
    return t


# 单符号 LaTeX 的常见误识别（实测：∞ 被认成 \otimes）
_LATEX_FIXUPS: Dict[str, str] = {
    r"\otimes": r"\infty",
    r"{\otimes}": r"\infty",
}


def sanitize_latex(tex: str) -> str:
    r"""修正常见的单符号误识别。

    实测 quiz 183/193 的区间 (－∞, +∞) 被识别成 (－\otimes, +\otimes)：
    ∞ 的两个圈在低分辨率下很像 ⊗。而真正的 ⊗ 在考研数学题里几乎不出现，
    所以把「**整个公式只有一个 ⊗**」的情况无脑换成 ∞ 是安全的
    （带别的符号的 ⊗ 不动，避免误伤张量积之类的场景）。
    """
    t = (tex or "").strip()
    return _LATEX_FIXUPS.get(t, t)


def is_suspect(content: str) -> Optional[str]:
    c = content or ""
    if not c:
        return None
    for pat, name in SUSPECT_PATTERNS:
        if pat.search(c):
            return name
    return None


def analysis_gaps(analysis: str) -> int:
    """数一下解析里「像丢了公式」的地方有多少处。"""
    return len(ANALYSIS_GAP_PATTERN.findall(analysis or ""))


def _media_root() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", "storage", "images")


# 能直接给浏览器用的位图格式。docx 里的公式图大量是 `.gif`（透明底），
# 甚至偶尔是 `.wmf`——直接把这些文件名写进 `![](...)` 有两个坑：
#   1. 透明底在深色背景上会变成「黑底黑字」，看不见；
#   2. Windows 下 `.gif` 的 MIME 映射来自注册表，不一定可靠，
#      实测 `.js` 就曾被返回成 text/plain（见 main.py 里那段 MIME 补钉）。
# 所以退图片之前统一转成**白底 PNG**，格式与 MIME 都确定。
#
# 注意 `.png` **不能**直接放行：Word 里另存出来的公式图很多就是 PNG，
# 但带 alpha 通道、底色全透明（实测 quiz_option/37 下 6 张、
# quiz_stem/88 下 3 张 alpha 最小值为 0）。这种图在浅色页面看着正常，
# 一旦用户开深色模式就是「黑底黑字」——和 GIF 是同一个坑。
_OPAQUE_EXTS = frozenset({".jpg", ".jpeg"})
# 透明底压平后的文件名后缀。加后缀而不是原地覆盖，
# 是为了保留原始字节以便回溯（原始图可能是唯一的证据）。
_FLAT_SUFFIX = "_w"


def _needs_flatten(path: str) -> bool:
    """图片是否带透明区域（存在 alpha 通道且最小 alpha < 250）。"""
    try:
        from PIL import Image

        with Image.open(path) as im:
            if im.mode not in ("RGBA", "LA", "PA") and "transparency" not in im.info:
                return False
            alpha = im.convert("RGBA").split()[-1]
            return alpha.getextrema()[0] < 250
    except Exception:  # noqa: BLE001 - 判断不了就当作不需要处理
        return False


def _ensure_web_png(path: str) -> str:
    """把公式图换成「浏览器一定能正确显示」的格式，返回可用的路径。

    * ``.jpg/.jpeg``：不透明，原样返回；
    * ``.png`` 且不透明：原样返回；
    * ``.png`` 带透明、``.gif``、其它（含 ``.wmf`` 之外的少见位图）：
      压平到白底后另存为 ``<stem>_w.png`` 并返回该路径。

    失败一律原样返回——**宁可显示一张可能有透明问题的图，也不能因为转格式
    把公式弄丢**（占位符已经是最后一道兜底，不该被格式问题提前触发）。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in _OPAQUE_EXTS:
        return path
    if ext == ".png" and not _needs_flatten(path):
        return path
    try:
        from PIL import Image

        stem, _ = os.path.splitext(path)
        out = stem + _FLAT_SUFFIX + ".png"
        if os.path.exists(out):
            return out
        with Image.open(path) as im:
            rgba = im.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[-1])
            bg.save(out, "PNG")
        return out
    except Exception:  # noqa: BLE001 - 转不了就退回原图，不能因此丢公式
        return path


def build_norm_index(plain: str) -> Tuple[str, List[int]]:
    buf: List[str] = []
    idx: List[int] = []
    for i, ch in enumerate(plain):
        if ch.isspace() or ch == _FW_SPACE:
            continue
        buf.append(ch)
        idx.append(i)
    return "".join(buf), idx


def _all_positions(haystack: str, needle: str) -> List[int]:
    out: List[int] = []
    if not needle:
        return out
    start = 0
    while True:
        p = haystack.find(needle, start)
        if p < 0:
            break
        out.append(p)
        start = p + 1
    return out


def locate(
    plain: str,
    needle: str,
    norm_plain: str,
    norm_idx: List[int],
    *,
    expected_pos: int = 0,
) -> Optional[Tuple[int, int]]:
    """在 plain 里定位 needle（先精确、后退归一化），返回 (start, end)。"""
    if not needle:
        return None
    positions = _all_positions(plain, needle)
    if positions:
        chosen = next((p for p in positions if p >= expected_pos), positions[-1])
        return chosen, chosen + len(needle)
    nn = norm(needle)
    if not nn:
        return None
    npos_list = _all_positions(norm_plain, nn)
    if not npos_list:
        return None
    best = None
    for np_ in npos_list:
        if norm_idx[np_] >= expected_pos:
            best = np_
            break
    if best is None:
        best = npos_list[-1]
    end_n = best + len(nn)
    if end_n > len(norm_idx):
        return None
    return norm_idx[best], norm_idx[end_n - 1] + 1


def locate_by_prefix(
    plain: str, text: str, norm_plain: str, norm_idx: List[int],
    *, expected_pos: int = 0, probe_len: int = 60,
) -> Optional[Tuple[int, int]]:
    """前缀定位 + 长度估算（全文匹配失败时的兜底）。"""
    nt = norm(text)
    if len(nt) < 10:
        return None
    for plen in (probe_len, 40, 24, 12):
        if len(nt) < plen:
            continue
        positions = _all_positions(norm_plain, nt[:plen])
        if positions:
            chosen = next((p for p in positions if norm_idx[p] >= expected_pos), positions[-1])
            start = norm_idx[chosen]
            return start, min(len(plain), start + max(1, len(text)))
    return None


def markers_in_range(marked: str, m_start: int, m_end: int) -> List[int]:
    if m_start >= m_end:
        return []
    return [int(m.group(1)) for m in MARKER_RE.finditer(marked, m_start, m_end)]


def collect_targets(
    db, *, quiz_ids: Optional[List[int]] = None, limit: int = 0,
    field: str = "both", only_marker: bool = False,
) -> List[dict]:
    """收集待修复的题。field: content=题干 / analysis=解析 / both。

    **解析比题干更严重**：实测题干残缺 31 道（8%），而解析里有公式缺口
    的有 215 道（56%）——解析读不通，题就白做了。

    ``only_marker=True`` 只收「文本里还留着 ``[[F:n]]`` 原始占位符」的题。
    这类题的公式是旧管线**原样留下**的（前端显示成醒目小标记），混在
    ``analysis_gaps`` 那上百道泛泛的「逗号+连词」里根本筛不出来，
    单独一个开关才能一次清干净。
    """
    from sqlalchemy import text as sqltext

    rows = db.execute(sqltext("""
        select id, coalesce(subject,''), coalesce(content,''),
               coalesce(analysis,''), coalesce(source_label,'')
        from quiz_questions
        where coalesce(source_label,'') <> ''
        order by source_label, id
    """)).fetchall()
    out: List[dict] = []
    for qid, subj, content, analysis, label in rows:
        if quiz_ids and qid not in quiz_ids:
            continue
        feat = None
        target_field = None
        target_text = ""
        if field in ("content", "both"):
            marker_hit = bool(_MARKER_ONLY_RE.search(content))
            if only_marker:
                if marker_hit:
                    feat = "题干含占位符"
                    target_field, target_text = "content", content
            else:
                feat = is_suspect(content)
                if not feat and marker_hit:
                    # 旧管线把占位符原样留在了题干里，前端会显示成醒目小标记
                    feat = "题干含占位符"
                if feat:
                    target_field, target_text = "content", content
        if not feat and field in ("analysis", "both"):
            marker_hit = bool(_MARKER_ONLY_RE.search(analysis))
            if marker_hit:
                feat = "解析含占位符"
                target_field, target_text = "analysis", analysis
            elif not only_marker:
                n = analysis_gaps(analysis)
                if n >= 1:
                    feat = f"解析缺口{n}"
                    target_field, target_text = "analysis", analysis
        if not feat:
            continue
        out.append({"id": qid, "subject": subj, "field": target_field,
                    "text": target_text, "label": label, "feature": feat})
    if limit:
        out = out[:limit]
    return out


def resolve_doc(db, label: str):
    """按 source_label 找对应的 docx 文档（精确名 → 去扩展名 → 包含匹配）。"""
    from models import Document

    d = db.query(Document).filter(Document.file_name == label).first()
    if not d and label.lower().endswith(".docx"):
        d = db.query(Document).filter(Document.file_name == label[:-5]).first()
    if not d:
        stem = os.path.splitext(label)[0]
        d = db.query(Document).filter(Document.file_name.ilike(f"%{stem[:40]}%")).first()
    if d and d.file_path and os.path.exists(d.file_path):
        return d
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="从源 docx 精准重取题库题干里丢失的公式")
    ap.add_argument("--quiz-id", type=int, action="append", default=[])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true", help="真写库（默认干跑）")
    ap.add_argument(
        "--field", choices=["content", "analysis", "both"], default="both",
        help="修哪个字段：content=题干 / analysis=解析 / both（默认）。"
             "解析里公式缺口实测有 215 道，比题干严重得多",
    )
    ap.add_argument(
        "--only-marker", action="store_true",
        help="只处理文本里还留着 [[F:n]] 原始占位符的题（旧管线漏渲染的那批）",
    )
    ap.add_argument(
        "--no-image-fallback", action="store_true",
        help="识别失败时不要退回公式图片，只保留 [[F:n]] 占位符",
    )
    ap.add_argument("--report", help="导出 JSON 报告")
    ap.add_argument("--show", type=int, default=15, help="最多打印多少条对比")
    args = ap.parse_args()

    from database import SessionLocal

    db = SessionLocal()
    try:
        targets = collect_targets(
            db, quiz_ids=args.quiz_id or None, limit=args.limit,
            field=args.field, only_marker=args.only_marker,
        )
        print(f"[修复] 疑似残缺题 {len(targets)} 道")
        if not targets:
            return 0

        from services.formula_latex import get_recognizer, latex_suspect

        rec = get_recognizer()
        if not rec.available:
            print(f"[修复] 公式引擎不可用：{rec.load_error}")
            return 1

        groups: Dict[str, List[dict]] = {}
        for t in targets:
            groups.setdefault(t["label"], []).append(t)
        print(f"[修复] 涉及源文档 {len(groups)} 篇")

        media = _media_root()
        results: List[dict] = []
        gi = 0
        for label, items in groups.items():
            gi += 1
            d = resolve_doc(db, label)
            if not d:
                for it in items:
                    it["status"] = "doc_not_found"
                    results.append(it)
                print(f"\n[{gi}/{len(groups)}] 未找到文档: {label[:50]}")
                continue

            t0 = time.time()
            try:
                res = parse_docx_with_images(d.file_path)
            except Exception as exc:  # noqa: BLE001
                for it in items:
                    it["status"] = f"parse_failed: {exc}"
                    results.append(it)
                continue
            al = build_aligned(res)
            norm_plain, norm_idx = build_norm_index(al.plain)
            print(
                f"\n[{gi}/{len(groups)}] doc={d.id} 「{d.file_name[:40]}」 "
                f"plain={len(al.plain)} 公式={al.marked.count('[[F:')} "
                f"解析 {time.time() - t0:.1f}s"
            )

            plans: List[Tuple[dict, int, int, List[int]]] = []
            wanted: set = set()
            cursor = 0
            for it in sorted(items, key=lambda x: x["id"]):
                raw = it.get("text") or ""
                span = locate(al.plain, raw, norm_plain, norm_idx, expected_pos=cursor)
                if not span:
                    sp = strip_rendered(raw)
                    if sp and sp != raw:
                        span = locate(al.plain, sp, norm_plain, norm_idx, expected_pos=cursor)
                if not span:
                    sp = strip_rendered(raw)
                    span = locate_by_prefix(
                        al.plain, sp or raw, norm_plain, norm_idx, expected_pos=cursor,
                    )
                if not span:
                    it["status"] = "locate_failed"
                    results.append(it)
                    continue
                m_start = al.plain_to_marked(span[0])
                m_end = al.plain_to_marked(span[1])
                mids = markers_in_range(al.marked, m_start, m_end)
                plans.append((it, m_start, m_end, mids))
                wanted.update(mids)
                cursor = max(cursor, span[0])

            if not plans:
                continue

            out_dir = os.path.join(media, "quiz_stem", str(d.id))
            res2 = parse_docx_with_images(d.file_path, out_dir=out_dir, only_indices=wanted)
            images = {i.index: i for i in res2.images}
            latex_map: Dict[int, str] = {}
            img_url: Dict[int, str] = {}
            for idx in sorted(wanted):
                img = images.get(idx)
                if not img or not img.out_path:
                    continue
                # 图片 URL 对**每个**导出成功的公式都建：识别不出来时要能退回图片，
                # 不能等到那时才发现没 URL
                if not args.no_image_fallback:
                    usable = _ensure_web_png(img.out_path)
                    img_url[idx] = (
                        f"/media/images/quiz_stem/{d.id}/"
                        f"{os.path.basename(usable)}"
                    )
                r = rec.recognize(img.out_path)
                if r.ok and r.latex:
                    tex = sanitize_latex(r.latex)
                    # 语义级门：结构合法但意思已经错了（实测 ∬ 被认成 \prod、
                    # 微分元被多加上标）。这类**不能**写进库——识别失败会留下
                    # [[F:n]] 占位符，人一眼看得出「这里缺东西」；错误 LaTeX
                    # 却渲染成一个看起来正常的公式，读者不会怀疑。
                    if latex_suspect(tex):
                        continue
                    latex_map[idx] = tex

            for it, m_start, m_end, mids in plans:
                part = al.marked[m_start:m_end]

                def _repl(m, _latex=latex_map, _img=img_url):
                    idx = int(m.group(1))
                    tex = (_latex.get(idx) or "").strip()
                    if tex:
                        return f"${tex}$"
                    url = _img.get(idx)
                    if url:
                        # 识别不出来但图在：退回**图片**。前端 MathText 支持
                        # `![alt](url)`，公式照样看得见，而且一定与原题一致。
                        # 比留一个 `[[F:n]]` 标记（前端渲染成 ƒ）好得多。
                        return f"![公式]({url})"
                    return m.group(0)  # 连图都没有：保留占位符，不静默丢掉

                new_text = MARKER_RE.sub(_repl, part).strip()
                it["candidate"] = new_text
                it["markers"] = len(mids)
                it["latex_ok"] = sum(1 for i in mids if i in latex_map)
                it["img_ok"] = sum(1 for i in mids if i in img_url and i not in latex_map)
                it["status"] = "ok"
                # 高置信度：**定位到的公式基本都识别出来了**。
                #
                # 原来这里写的是「新文本比旧的长」，那是给「题干/解析里公式整块缺失」
                # 那条路用的（加进去的 LaTeX 必然更长）。修占位符时这条判据是错的：
                # 旧文本里的 `[[F:5216]]` 有 10 个字符，识别成功会变成 `$x$` 只有 3 个
                # 字符，**修得越准反而越短**，于是 33 道里 30 道被误杀。
                #
                # 改按「解决率」判：剩下没识别出来的保留 `[[F:n]]` 原样
                # （前端渲染成醒目小标记，对人可见），不假装修好，也不整篇丢弃。
                #
                # 修占位符时门槛可以低到 0.5：旧文本本来就是一堆占位符，
                # 修掉一半、留一半，对读者也是**严格变好**——没有任何损失可能。
                # 修「公式整块缺失」的题干/解析则必须 0.9，因为那种文本原本
                # 是通顺的散文，塞错东西会把句子搞坏。
                #
                # 退图片也算「解决」：图片一定与原题一致，只是不可检索。
                min_rate = 0.5 if args.only_marker else 0.9
                solved = it["latex_ok"] + it["img_ok"]
                rate = (solved / it["markers"]) if it["markers"] else 0.0
                it["high_confidence"] = (
                    it["markers"] > 0
                    and rate >= min_rate
                    and norm(new_text) != norm(it.get("text") or "")
                )
                results.append(it)

        ok = [r for r in results if r.get("status") == "ok"]
        high = [r for r in results if r.get("high_confidence")]
        print(f"\n[修复] 定位成功 {len(ok)}/{len(results)}，高置信度 {len(high)}")

        for r in high[: args.show]:
            print(
                f"\n--- quiz {r['id']} [{r['subject']}] {r['field']} {r['feature']} "
                f"公式{r['latex_ok']}/{r['markers']} ---"
            )
            print(f"  BEFORE: {(r.get('text') or '')[:110]!r}")
            print(f"  AFTER : {r['candidate'][:170]!r}")

        if args.report:
            with open(args.report, "w", encoding="utf-8") as fh:
                json.dump(results, fh, ensure_ascii=False, indent=2)
            print(f"\n[修复] 报告已写 {args.report}")

        if args.apply and high:
            from models import QuizQuestion
            from services.backup_service import create_backup

            backup = create_backup()
            print(f"[修复] 已备份: {backup}")
            n_c = n_a = 0
            for r in high:
                q = db.get(QuizQuestion, r["id"])
                if not q:
                    continue
                if r["field"] == "analysis":
                    q.analysis = r["candidate"]
                    n_a += 1
                else:
                    q.content = r["candidate"]
                    n_c += 1
            db.commit()
            print(f"[修复] 已写库 题干 {n_c} 道 / 解析 {n_a} 道")
        elif high:
            print("[修复] 干跑结束，加 --apply 才会写库")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
