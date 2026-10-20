"""把 docx 文档里被丢弃的数学公式**回填**到知识库块。

背景
----
Word 题库里的公式是**以图片形式嵌在段落里**的（见 ``services/docx_formula.py``）。
现有 ``_parse_docx`` 只取 ``paragraph.text``，把图片全丢了，于是块文本变成
「设函数具有二阶导数，，则在上（　）」这种缺公式的形态——LLM 读到的是残句。

回填策略（两条路，按优先级）
--------------------------
1. **LaTeX 路线（首选）**：用 ``services/formula_latex.py`` 把公式图识别成 LaTeX，
   写成 ``$...$``。这是唯一让公式**进入文本链路**的形式：RAG 能检索、LLM 能读、
   前端 KaTeX 能渲染。
2. **图片兜底**：识别失败（模型判不可信）时，退回 markdown 行内图
   ``![公式](/media/images/docx_formula/<doc_id>/<file>)``。只有人眼能看，
   但至少公式不会凭空消失。

位置定位
--------
去占位符后的文本与库里已有的 ``documents.content`` **逐字符一致**（已实测），
所以每个块都能在原文中精确定位，用位置映射把它对应的公式占位符找回来。

只改 ``knowledge_chunks.text``，不动分词列：PG 侧检索主查走 ILIKE + trgm 索引
（见 ``services/search_service.py``），``search_vector`` 是空的生成列，不影响召回。

用法
----
```
# 干跑（默认，不写库）
python scripts/backfill_docx_formulas.py --all-docx

# 真写（LaTeX 优先 + 图片兜底）
python scripts/backfill_docx_formulas.py --all-docx --apply

# 只导出图片、不做公式识别（快速验证定位逻辑）
python scripts/backfill_docx_formulas.py --all-docx --no-recognize

# 只处理指定文档
python scripts/backfill_docx_formulas.py --doc-id 35 --doc-id 89 --apply
```
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_formula import (  # noqa: E402
    MARKER_RE,
    AlignedText,
    DocxImage,
    build_aligned,
    parse_docx_with_images,
)

# 归一化时忽略的空白（含全角空格）
_WS_RE = re.compile(r"\s+")
_FW_SPACE = "　"


def _media_root() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", "storage", "images")


# 已回填的块里，公式被写成了 LaTeX 或图片链接。要重新定位就得先剥掉它们，
# 还原成 docx 原文的纯文本形态——否则 locate() 一定失败（文本已经变了）。
_RENDERED_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RENDERED_TEX_RE = re.compile(r"\${1,2}[^$]*\${1,2}")


def strip_rendered(text: str) -> str:
    """把已回填的块还原成纯文本（去掉图片标记与 LaTeX），用于重新定位。

    这是「重复回填」的前提：第一次回填后块文本已变成
    ``设$\\{x_n\\}$是数列``，直接拿它去 docx 原文里找必然失败；
    剥掉 ``$...$`` / ``![..](..)`` 后就能重新对上原文。
    """
    t = _RENDERED_IMG_RE.sub("", text or "")
    t = _RENDERED_TEX_RE.sub("", t)
    return t


def _norm(text: str) -> str:
    return _WS_RE.sub("", (text or "").replace(_FW_SPACE, " "))


def build_norm_index(plain: str) -> Tuple[str, List[int]]:
    """把 plain 去掉所有空白，并记录每个保留字符在 plain 里的下标。"""
    buf: List[str] = []
    idx: List[int] = []
    for i, ch in enumerate(plain):
        if ch.isspace() or ch == _FW_SPACE:
            continue
        buf.append(ch)
        idx.append(i)
    return "".join(buf), idx


def _all_positions(haystack: str, needle: str) -> List[int]:
    """返回 needle 在 haystack 里的**所有**出现位置。"""
    out: List[int] = []
    if not needle:
        return out
    start = 0
    n = len(needle)
    while True:
        p = haystack.find(needle, start)
        if p < 0:
            break
        out.append(p)
        start = p + 1
    return out


def locate(
    aligned: AlignedText,
    needle: str,
    norm_plain: str,
    norm_idx: List[int],
    *,
    expected_pos: int = 0,
) -> Optional[Tuple[int, int]]:
    """在 plain 文本里定位 needle，返回 (start, end)。

    **为什么要 expected_pos**：教辅书里「所以方程的通解为」「故选B项」这类模板句
    反复出现，只用 ``find()`` 取首次匹配会把后面的 chunk 定位到文档开头，
    于是 chunk 之间互相重叠、公式数量算出来离谱（实测 1 个 2269 字的块被算出
    3481 处公式）。chunk 是按文档顺序切分的，所以按顺序推进定位，
    在多个候选里选**第一个不早于期望位置**的出现点。

    精确匹配失败时才退回「去空白」的归一化匹配（块文本可能被清洗过空格）。
    """
    if not needle:
        return None

    positions = _all_positions(aligned.plain, needle)
    if positions:
        chosen = None
        for p in positions:
            if p >= expected_pos:
                chosen = p
                break
        if chosen is None:
            # 全都在期望位置之前：文档结构可能和 chunk 顺序不一致，取最靠后的
            chosen = positions[-1]
        return chosen, chosen + len(needle)

    norm_needle = _norm(needle)
    if not norm_needle:
        return None
    npos_list = _all_positions(norm_plain, norm_needle)
    if not npos_list:
        return None

    # 期望位置换算到归一化坐标：用 norm_idx 近似（因去空白是单调的）
    best = None
    for npos in npos_list:
        p_start = norm_idx[npos]
        if p_start >= expected_pos:
            best = (npos, p_start)
            break
    if best is None:
        npos = npos_list[-1]
        best = (npos, norm_idx[npos])

    npos, p_start = best
    nend = npos + len(norm_needle)
    if nend > len(norm_idx):
        return None
    return p_start, norm_idx[nend - 1] + 1


def locate_by_prefix(
    aligned: AlignedText,
    text: str,
    norm_plain: str,
    norm_idx: List[int],
    *,
    expected_pos: int = 0,
    probe_len: int = 60,
) -> Optional[Tuple[int, int]]:
    """用「去空白后的前 N 个字符」定位起点，长度按原文估算。

    **为什么需要这个**：重复回填时块文本已经被写过一遍（含 ``$...$`` 和
    图片链接）。用正则剥掉标记后，只要有一个不配对的 ``$``（LaTeX 里的
    ``\\$``、OCR 残留、或块首尾截断），后半段就会错位——实测
    ``$f(-x)=f(x)$`` 剥完残留 ``f ( - x )   =   - \\ove``，
    导致全长匹配必然失败（而前 40 字符在原文里找得到）。

    所以退一步：只要**开头对得上**就认为定位成功，末尾按长度估算。
    ``markers_in`` 只是按区间取占位符，多取/少取一两个不影响整块替换。
    """
    norm_text = _norm(text)
    if len(norm_text) < 10:
        return None
    probe = norm_text[:probe_len]
    positions = _all_positions(norm_plain, probe)
    if not positions:
        # 前缀也找不到：退到更短的前缀（防止开头几个字就被污染）
        for shorter in (40, 24, 12):
            if len(norm_text) < shorter:
                continue
            positions = _all_positions(norm_plain, norm_text[:shorter])
            if positions:
                break
    if not positions:
        return None

    chosen = None
    for np_ in positions:
        if norm_idx[np_] >= expected_pos:
            chosen = np_
            break
    if chosen is None:
        chosen = positions[-1]

    start = norm_idx[chosen]
    # 长度估算：用原始（未剥离）文本长度更接近块在文档中的实际跨度
    est = max(1, len(text))
    end = min(len(aligned.plain), start + est)
    return start, end


def markers_in(aligned: AlignedText, plain_start: int, plain_end: int) -> List[int]:
    """给定 plain 区间，返回该区间覆盖的公式占位符序号。"""
    if plain_start >= plain_end:
        return []
    m_start = aligned.plain_to_marked(plain_start)
    m_end = aligned.plain_to_marked(plain_end)
    out: List[int] = []
    for m in MARKER_RE.finditer(aligned.marked, m_start, m_end):
        out.append(int(m.group(1)))
    return out


def _image_url(images: Dict[int, DocxImage], idx: int, base_url: str) -> str:
    img = images.get(idx)
    if not img or not img.out_path:
        return ""
    return f"{base_url}/{os.path.basename(img.out_path)}"


def render(
    text: str,
    images: Dict[int, DocxImage],
    base_url: str,
    *,
    latex: Optional[Dict[int, str]] = None,
    image_fallback: bool = True,
) -> Tuple[str, Dict[str, int]]:
    """把占位符替换成 LaTeX（首选）或行内图（兜底）。

    返回 ``(新文本, 统计)``，统计键：``latex`` / ``image`` / ``kept``。
    """
    stats = {"latex": 0, "image": 0, "kept": 0}
    latex = latex or {}

    def _repl(m: "re.Match") -> str:
        idx = int(m.group(1))
        tex = (latex.get(idx) or "").strip()
        if tex:
            stats["latex"] += 1
            return f"${tex}$"
        url = _image_url(images, idx, base_url)
        if url and image_fallback:
            stats["image"] += 1
            return f"![公式]({url})"
        # 保留占位符：前端渲染成可见小标记，且不膨胀文本
        stats["kept"] += 1
        return m.group(0)

    return MARKER_RE.sub(_repl, text), stats


def process_document(
    doc_row,
    chunks: List[dict],
    media_root: str,
    *,
    recognizer=None,
    image_fallback: bool = True,
    max_side_for_formula: int = 600,
    min_formula_aspect: float = 0.0,
    max_formula_height: int = 0,
    max_formula_aspect: float = 0.0,
    min_formula_side: int = 0,
    log=None,
) -> dict:
    """处理单个 docx 文档，返回统计。

    ``max_side_for_formula`` > 0 时，超过该尺寸的图不当作「单个公式」，
    直接走图片兜底——实测 Word 会把整道题的 A/B/C/D 四行选项粘成一张
    400×120 的大图，那不是公式，送去识别只会得到一堆中文垃圾。
    """
    stat = {
        "doc_id": doc_row["id"],
        "file_name": doc_row["file_name"],
        "chunks": 0,
        "repaired": 0,
        "latexs": 0,
        "images": 0,
        "kept": 0,
        "skipped_big": 0,
        "skipped_shape": 0,
        "skipped_tall": 0,
        "skipped_wide": 0,
        "skipped_tiny": 0,
        "errors": [],
    }
    path = doc_row["file_path"]
    if not path or not os.path.exists(path):
        stat["errors"].append("文件不存在")
        return stat

    try:
        res = parse_docx_with_images(path)
    except Exception as exc:  # noqa: BLE001
        stat["errors"].append(f"解析失败: {exc}")
        return stat
    if res.error:
        stat["errors"].append(res.error)
        return stat

    aligned = build_aligned(res)
    norm_plain, norm_idx = build_norm_index(aligned.plain)

    # 第一轮：定位每个块用到了哪些公式
    # 按 chunk id 升序 = 文档顺序推进，避免模板句重复导致定位到文档开头
    plans: List[Tuple[dict, Tuple[int, int], List[int]]] = []
    wanted: set = set()
    cursor = 0
    for ch in sorted(chunks, key=lambda c: c["id"]):
        span = locate(
            aligned, ch["text"] or "", norm_plain, norm_idx, expected_pos=cursor
        )
        if not span:
            # 已回填过的块：剥掉 LaTeX/图片标记再试一次（重复回填）
            stripped = strip_rendered(ch["text"] or "")
            if stripped and stripped != (ch["text"] or ""):
                span = locate(aligned, stripped, norm_plain, norm_idx, expected_pos=cursor)
                if not span:
                    # 剥离后首尾仍可能有残留（不配对的 $ 会让正则错位），
                    # 退到「前缀定位 + 长度估算」
                    span = locate_by_prefix(
                        aligned, stripped, norm_plain, norm_idx, expected_pos=cursor
                    )
        if not span:
            # 最后兜底：即使剥离不干净，原始文本的开头一般还可信
            span = locate_by_prefix(
                aligned, ch["text"] or "", norm_plain, norm_idx, expected_pos=cursor
            )
        if not span:
            continue
        mids = markers_in(aligned, span[0], span[1])
        if not mids:
            continue
        plans.append((ch, span, mids))
        wanted.update(mids)
        # 只把游标推进到本块起点：chunk 之间允许重叠（滑动窗口切分），
        # 推到 end 会让下一个重叠块找不到自己的起点。
        cursor = max(cursor, span[0])

    if not plans:
        return stat

    # 第二轮：只导出被引用的公式图
    out_dir = os.path.join(media_root, "docx_formula", str(doc_row["id"]))
    res2 = parse_docx_with_images(path, out_dir=out_dir, only_indices=wanted)
    images = {i.index: i for i in res2.images}
    base_url = f"/media/images/docx_formula/{doc_row['id']}"

    # 收集要识别的图（排除 oversized 与非公式形状）
    latex_map: Dict[int, str] = {}
    if recognizer is not None:
        from PIL import Image

        to_recognize: List[int] = []
        for idx in sorted(wanted):
            img = images.get(idx)
            if not img or not img.out_path:
                continue
            try:
                with Image.open(img.out_path) as im:
                    w, h = im.size
            except Exception:  # noqa: BLE001
                continue
            # 极小图直接丢：1×1、2×3 这种是段落装饰/空白占位，识别只会得到 \cdot
            if min_formula_side > 0 and (w < min_formula_side or h < min_formula_side):
                stat["skipped_tiny"] += 1
                continue
            if max_side_for_formula > 0 and max(w, h) > max_side_for_formula:
                stat["skipped_big"] += 1
                continue
            # 形状过滤：行内公式是「细长条」，电路图/波形图/示意图接近方形。
            # 实测一批真题 docx 里，近方形的图送去识别既慢（大图预处理+推理
            # 1.8s/张 vs 公式 0.38s/张）又必然失败，直接让图片兜底接管。
            if min_formula_aspect > 0 and h > 0 and (w / float(h)) < min_formula_aspect:
                stat["skipped_shape"] += 1
                continue
            # 高度上限：行内公式高度普遍 17–60px，多行公式到 120px 左右；
            # 电路图/波形图/示意图高度通常 200px 以上。实测这批大图送去识别
            # 要 4.5s/张（公式图 0.38s/张），且必然失败——纯浪费。
            if max_formula_height > 0 and h > max_formula_height:
                stat["skipped_tall"] += 1
                continue
            # 宽高比上限：240×15 这类单行下标图实测识别 21.8s（正常 0.3s）
            # 且结果残缺，直接让图片兜底接管，别拖死整批。
            if max_formula_aspect > 0 and h > 0 and (w / float(h)) > max_formula_aspect:
                stat["skipped_wide"] += 1
                continue
            to_recognize.append(idx)

        if to_recognize:
            t0 = time.time()
            if log:
                log(f"    待识别 {len(to_recognize)} 张（逐张）")

            # 逐张识别，不用 recognize_batch：实测单张 0.2–0.3s，
            # 而 batch=8 在部分畸形输入上会卡死数分钟（CPU EP 的已知问题）。
            # 公式图大多是小图，batch 的固定开销摊薄收益远不如风险大。
            ok_cnt = 0
            for n, idx in enumerate(to_recognize, 1):
                r = recognizer.recognize(images[idx].out_path)
                if r.ok and r.latex:
                    latex_map[idx] = r.latex
                    ok_cnt += 1
                if log and (n % 20 == 0 or n == len(to_recognize)):
                    log(
                        f"    识别 {n}/{len(to_recognize)} "
                        f"成功 {ok_cnt} {time.time() - t0:.0f}s"
                    )
            if log:
                log(
                    f"    识别完成 {ok_cnt}/{len(to_recognize)} 成功 "
                    f"{time.time() - t0:.0f}s"
                )

    updates: List[Tuple[str, int]] = []
    for ch, span, mids in plans:
        m_start = aligned.plain_to_marked(span[0])
        m_end = aligned.plain_to_marked(span[1])
        marked_part = aligned.marked[m_start:m_end]
        new_text, st = render(
            marked_part,
            images,
            base_url,
            latex=latex_map,
            image_fallback=image_fallback,
        )
        stat["latexs"] += st["latex"]
        stat["images"] += st["image"]
        stat["kept"] += st["kept"]
        new_text = new_text.strip()
        if not new_text or new_text == (ch["text"] or "").strip():
            continue
        updates.append((new_text, ch["id"]))

    stat["chunks"] = len(chunks)
    stat["repaired"] = len(updates)
    stat["_updates"] = updates  # 由调用方消费
    return stat


def main() -> int:
    ap = argparse.ArgumentParser(description="回填 docx 文档被丢弃的数学公式")
    ap.add_argument("--doc-id", type=int, action="append", default=[], help="指定文档 id，可多次")
    ap.add_argument("--all-docx", action="store_true", help="处理所有 .docx 文档")
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少篇文档（0=不限）")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认只干跑）")
    ap.add_argument("--all-docs", action="store_true", help="忽略污染过滤，处理所有 docx")
    ap.add_argument("--no-recognize", action="store_true", help="不跑公式识别，只做图片兜底")
    ap.add_argument("--no-image-fallback", action="store_true", help="识别失败时不写图片链接")
    ap.add_argument(
        "--max-formula-side",
        type=int,
        default=600,
        help="超过此边长的图不当作单个公式（0=不限，默认 600）",
    )
    ap.add_argument(
        "--min-formula-aspect",
        type=float,
        default=0.0,
        help="宽高比低于此值不当作公式（0=不过滤，默认 0）。"
             "**别再用 1.2 那种值**：短公式本身就是近方形的，实测误杀 766 个真公式",
    )
    ap.add_argument(
        "--min-formula-side",
        type=int,
        default=4,
        help="宽或高小于此值的极小图跳过（噪声，默认 4px）",
    )
    ap.add_argument(
        "--max-formula-height",
        type=int,
        default=160,
        help="高度超过此值的图不当作公式（0=不过滤，默认 160）",
    )
    ap.add_argument(
        "--max-formula-aspect",
        type=float,
        default=12.0,
        help="宽高比超过此值的极扁图跳过识别（0=不过滤，默认 12）",
    )
    args = ap.parse_args()

    from database import SessionLocal
    from models import Document, KnowledgeChunk

    recognizer = None
    if not args.no_recognize:
        from services.formula_latex import get_recognizer

        recognizer = get_recognizer()
        if not recognizer.available:
            print(f"[回填] 公式引擎不可用，降级为图片兜底：{recognizer.load_error}")
            recognizer = None
        else:
            print(f"[回填] 公式引擎就绪：{recognizer.engine_info()}")

    db = SessionLocal()
    try:
        q = db.query(Document).filter(Document.file_path.ilike("%.docx"))
        if args.doc_id:
            q = q.filter(Document.id.in_(args.doc_id))
        docs = q.all()
        if not args.all_docs:
            polluted = (
                db.query(KnowledgeChunk.document_id)
                .filter(
                    KnowledgeChunk.text.ilike("%f(α)%")
                    | KnowledgeChunk.text.ilike("%f（α）%")
                    | KnowledgeChunk.text.ilike("%f(r)%")
                    | KnowledgeChunk.text.ilike("%f（r）%")
                    | KnowledgeChunk.text.ilike("%f()%")
                    | KnowledgeChunk.text.ilike("%f（）%")
                    | KnowledgeChunk.text.ilike("%fLg%")
                    | KnowledgeChunk.text.ilike("%，，%")
                )
                .distinct()
            )
            ids = {r[0] for r in polluted.all()}
            docs = [d for d in docs if d.id in ids]
        if args.limit:
            docs = docs[: args.limit]

        print(f"[回填] 目标文档 {len(docs)} 篇")
        media_root = _media_root()
        os.makedirs(media_root, exist_ok=True)

        all_stats = []
        all_updates: List[Tuple[str, int]] = []
        for d in docs:
            t0 = time.time()
            chunks = (
                db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.document_id == d.id)
                .all()
            )
            rows = [{"id": c.id, "text": c.text or ""} for c in chunks]
            stat = process_document(
                {"id": d.id, "file_name": d.file_name, "file_path": d.file_path},
                rows,
                media_root,
                recognizer=recognizer,
                image_fallback=not args.no_image_fallback,
                max_side_for_formula=args.max_formula_side,
                min_formula_aspect=args.min_formula_aspect,
                max_formula_height=args.max_formula_height,
                max_formula_aspect=args.max_formula_aspect,
                min_formula_side=args.min_formula_side,
                log=print,
            )
            ups = stat.pop("_updates", [])
            all_updates.extend(ups)
            stat["seconds"] = round(time.time() - t0, 1)
            all_stats.append(stat)
            print(
                f"  doc={stat['doc_id']:>4} {str(stat['file_name'])[:34]:36s} "
                f"块={stat['chunks']:>4} 修复={stat['repaired']:>4} "
                f"LaTeX={stat['latexs']:>4} 图={stat['images']:>4} "
                f"略大={stat['skipped_big']:>3} 略方={stat['skipped_shape']:>3} "
                f"略高={stat['skipped_tall']:>4} 略扁={stat['skipped_wide']:>4} "
                f"极小={stat['skipped_tiny']:>4} "
                f"{stat['seconds']}s {stat['errors'] or ''}"
            )

        total = {
            k: sum(s[k] for s in all_stats)
            for k in ("repaired", "latexs", "images", "kept",
                      "skipped_big", "skipped_shape", "skipped_tall",
                      "skipped_wide", "skipped_tiny")
        }
        print(
            f"[回填] 合计：修复 {total['repaired']} 块 | "
            f"LaTeX {total['latexs']} | 图片兜底 {total['images']} | "
            f"略过大图 {total['skipped_big']} | 略过方形 {total['skipped_shape']} | "
            f"略过高图 {total['skipped_tall']} | 略过极扁 {total['skipped_wide']} | "
            f"极小 {total['skipped_tiny']} | "
            f"占位保留 {total['kept']}"
        )
        if total["latexs"] + total["images"]:
            ratio = total["latexs"] / max(1, total["latexs"] + total["images"])
            print(f"[回填] LaTeX 覆盖率：{ratio:.1%}")

        if args.apply and all_updates:
            from services.backup_service import create_backup

            backup = create_backup()
            print(f"[回填] 已备份: {backup}")
            for new_text, chunk_id in all_updates:
                db.execute(
                    KnowledgeChunk.__table__.update()
                    .where(KnowledgeChunk.__table__.c.id == chunk_id)
                    .values(text=new_text)
                )
            db.commit()
            print(f"[回填] 已写库 {len(all_updates)} 块")
        elif all_updates:
            print("[回填] 干跑结束，加 --apply 才会写库")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
