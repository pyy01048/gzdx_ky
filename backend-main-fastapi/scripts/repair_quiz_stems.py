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


def norm(text: str) -> str:
    return _WS_RE.sub("", (text or "").replace(_FW_SPACE, " "))


def strip_rendered(text: str) -> str:
    """剥掉已写入的 LaTeX/图片标记，还原成原文形态（支持重复修复）。"""
    t = _RENDERED_IMG_RE.sub("", text or "")
    t = _RENDERED_TEX_RE.sub("", t)
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


def _media_root() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", "storage", "images")


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


def collect_targets(db, *, quiz_ids: Optional[List[int]] = None, limit: int = 0) -> List[dict]:
    from sqlalchemy import text as sqltext

    rows = db.execute(sqltext("""
        select id, coalesce(subject,''), coalesce(content,''), coalesce(source_label,'')
        from quiz_questions
        where coalesce(source_label,'') <> ''
        order by source_label, id
    """)).fetchall()
    out: List[dict] = []
    for qid, subj, content, label in rows:
        if quiz_ids and qid not in quiz_ids:
            continue
        feat = is_suspect(content)
        if not feat:
            continue
        out.append({"id": qid, "subject": subj, "content": content,
                    "label": label, "feature": feat})
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
    ap.add_argument("--report", help="导出 JSON 报告")
    ap.add_argument("--show", type=int, default=15, help="最多打印多少条对比")
    args = ap.parse_args()

    from database import SessionLocal

    db = SessionLocal()
    try:
        targets = collect_targets(db, quiz_ids=args.quiz_id or None, limit=args.limit)
        print(f"[修复] 疑似残缺题 {len(targets)} 道")
        if not targets:
            return 0

        from services.formula_latex import get_recognizer

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
                span = locate(al.plain, it["content"], norm_plain, norm_idx, expected_pos=cursor)
                if not span:
                    sp = strip_rendered(it["content"])
                    if sp and sp != it["content"]:
                        span = locate(al.plain, sp, norm_plain, norm_idx, expected_pos=cursor)
                if not span:
                    sp = strip_rendered(it["content"])
                    span = locate_by_prefix(
                        al.plain, sp or it["content"], norm_plain, norm_idx,
                        expected_pos=cursor,
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
            for idx in sorted(wanted):
                img = images.get(idx)
                if not img or not img.out_path:
                    continue
                r = rec.recognize(img.out_path)
                if r.ok and r.latex:
                    latex_map[idx] = sanitize_latex(r.latex)

            for it, m_start, m_end, mids in plans:
                part = al.marked[m_start:m_end]

                def _repl(m, _latex=latex_map):
                    idx = int(m.group(1))
                    tex = (_latex.get(idx) or "").strip()
                    if tex:
                        return f"${tex}$"
                    return m.group(0)  # 识别失败保留占位符，前端显示为 ƒ

                new_text = MARKER_RE.sub(_repl, part).strip()
                it["candidate"] = new_text
                it["markers"] = len(mids)
                it["latex_ok"] = sum(1 for i in mids if i in latex_map)
                it["status"] = "ok"
                it["high_confidence"] = (
                    len(new_text) > len(it["content"]) and it["latex_ok"] > 0
                )
                results.append(it)

        ok = [r for r in results if r.get("status") == "ok"]
        high = [r for r in results if r.get("high_confidence")]
        print(f"\n[修复] 定位成功 {len(ok)}/{len(results)}，高置信度 {len(high)}")

        for r in high[: args.show]:
            print(
                f"\n--- quiz {r['id']} [{r['subject']}] {r['feature']} "
                f"公式{r['latex_ok']}/{r['markers']} ---"
            )
            print(f"  BEFORE: {r['content'][:110]!r}")
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
            n = 0
            for r in high:
                q = db.get(QuizQuestion, r["id"])
                if not q:
                    continue
                q.content = r["candidate"]
                n += 1
            db.commit()
            print(f"[修复] 已写库 {n} 道")
        elif high:
            print("[修复] 干跑结束，加 --apply 才会写库")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
