# -*- coding: utf-8 -*-
"""题库配图提取（Word 原图 → quiz_questions.images）· 只读干跑

背景
----
`quiz_questions` 386 道里 131 道 `images=[]`，其中 18 道题干明确引用了插图
（"如图1-3所示" / "图4-1所示电路"），但从来没生成过任何图 —— 不是文件丢失，
是 `images` 从一开始就是空数组。这 18 道的源 `source_label` 全部是 .docx
题库书，而 Word 里的插图是**以图片形式嵌在段落里**的（同公式），可以用
`services/docx_formula.parse_docx_with_images()` 原样取出。

排版规律（已逐本核对，5 本书 18 道题 100% 成立）
------------------------------------------------
    题干段落 → 选项 → **[纯图片段落]** → **`图x-x` 图注段落** → 答案/解析

图注在图片**下方**，且图注是独立段落。所以定位链是：
先按图注锚点找到图注段落，再取它**前面最近的纯图段落**里的图片。

为什么要"纯图段落"
------------------
选项（如" A．[[F:3434]]系统的闭环频率特性"）也含图片，属于"文字+图"混合段。
只有 strip 掉占位符后为空的行才是插图行，按这个判据才不会把选项公式当成插图。

前端契约（本轮已核对，结论：**不需要改前端**）
----------------------------------------------
- `frontend/src/pages/QuizPractice.jsx:266-278`：`q.images.map(...)` 直接渲染
  `<img src={mediaSrc(img)}>`，**不读 `kind`、不读 `page`、不排序、不分区**。
- `mediaSrc()`（同文件 :24-30）：取 `img.url || img.path || img.src`，非绝对路径
  时拼 `/media/images/` 前缀。所以 `{"kind":"figure","path":"question_figures/88/278_图8-1.png"}`
  可直接渲染。
- `frontend/src/utils/optionText.js:imageList()`：只取 url，其余字段（含 `kind`）原样保留。
- `frontend/src/pages/QuizBank.jsx:190,212`：后台编辑页会把 `images` 拍平成 URL 行，
  保存时回写成字符串数组（`kind` 会丢，但图仍能显示）——已知往返降级，不影响本题；
  以后若要按 `kind` 过滤，得先修这里。
- 结论：`kind="figure"` 是**安全新增**，无需任何前端改动。

用法
----
    python scripts/fetch_quiz_figures.py                 # 干跑，图落 %TEMP%
    python scripts/fetch_quiz_figures.py --auto          # 不信清单 doc/图注，自己推
    python scripts/fetch_quiz_figures.py --export        # 真写 data/storage/images/
    python scripts/fetch_quiz_figures.py --qid 278 --qid 293
    python scripts/fetch_quiz_figures.py --min-w 100     # 放宽"太小"阈值
    python scripts/fetch_quiz_figures.py --anchors my.json   # 用外部锚点清单
    python scripts/fetch_quiz_figures.py --anchors my.json --apply   # 落图 + 写库

锚点 JSON 形如：
    [{"qids": [300], "doc_id": 88, "caption": "图9", "occurrence": 1}]
`occurrence` 可选；不给就用"离题干最近的那一处"。

写库规则（--apply）
------------------
`UPDATE quiz_questions SET images = [...] WHERE id=? AND (images IS NULL OR len=0)`，
**只碰 images 一列**，不动 content/analysis/options/question_type。
落库形状固定为：

    [{"kind":"figure", "path":"question_figures/88/278_图8-1.png",
      "caption":"图8-1", "source":"docx"}]

`path` 是相对 `data/storage/images/` 的相对路径（前端 `mediaSrc()` 拼 `/media/images/`）。
写库前默认 `services.backup_service.create_backup()` 并打印路径；逐条 `commit()`，
一条失败不影响其他；`images` 已有内容的题**跳过并报告**，绝不覆盖既有配图。

`--export` 只写图片文件，**不写库**；写库请另开脚本并先备份（本脚本刻意不实现）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

IMG_ROOT = BASE / "data" / "storage" / "images"
OUT_SUBDIR = "question_figures"

#: 图注行：`图9`、`图4-1`、`图1-11`，允许后面跟极短说明（"图3-1 电路图"）
RE_CAP = re.compile(r"^\s*图\s*(\d+)(?:\s*[-－—]\s*(\d+))?\s*(.*)$")
RE_MARK = re.compile(r"\[\[F:(\d+)\]\]")
#: 图注尾巴出现这些字 → 说明是题干（"图8-1所示的是..."），不是图注
RE_CAP_TAIL_BAD = re.compile(r"所示|中|则|，|。|、|（|\(|为")
#: 题干边界：下一题 / 答案 / 解析，用于防止"串到下一题的图"
RE_BOUNDARY = re.compile(r"^\s*(?:\d{1,3}\s*[．.、]|【答案】|【解析】|解：)")

#: "像插图"的默认下限：宽>120、高>80、宽高比 0.15~8
MIN_W, MIN_H = 120, 80
MIN_RATIO, MAX_RATIO = 0.15, 8.0

#: 题号 → (doc_id, 图注)。这是 team-lead 给的批次 1 原始清单，**原样保留**，
#: 干跑会把不一致逐行打出来（DOC-MISMATCH / STEM-MISS / CAPTION-MISS），
#: 而不是替它"猜着改"。
ANCHORS: list[dict[str, Any]] = [
    {"qids": [4], "doc_id": 88, "caption": "图9-1"},
    {"qids": [5], "doc_id": 88, "caption": "图9-2"},
    {"qids": [278, 293, 297], "doc_id": 88, "caption": "图8-1"},
    {"qids": [301], "doc_id": 86, "caption": "图2"},
    {"qids": [304], "doc_id": 86, "caption": "图4"},
    {"qids": [305], "doc_id": 86, "caption": "图5"},
    {"qids": [307], "doc_id": 86, "caption": "图9"},
    {"qids": [315], "doc_id": 87, "caption": "图6"},
]


# --------------------------------------------------------------------------- #
# 文本工具
# --------------------------------------------------------------------------- #
def strip_marks(s: str) -> str:
    return RE_MARK.sub("", s or "")


def norm(s: str) -> str:
    """匹配用归一：先去公式占位符、去公式、再去空白与标点。

    必须先去 `[[F:n]]`：docx 侧带占位符、DB 侧没有，不去掉永远匹配不上
    （q278/q293/q297 的题干里公式就是图片，正是这个坑）。
    """
    s = strip_marks(s or "")
    s = re.sub(r"\$[^$]*\$", "", s)
    s = re.sub(r"[\s\u3000\u00a0]", "", s)
    return s.strip("，。、；：（）()【】[]　")


def needles(content: str) -> list[str]:
    """从题干里取几个"够独特"的匹配片段（公式先摘掉）。"""
    n = norm(content)
    out: list[str] = []
    for ln in (14, 12, 10, 8):
        if len(n) >= ln:
            out.append(n[:ln])
    if len(n) >= 20:
        out.append(n[-10:])
    return out


def cap_key(m: re.Match) -> str:
    return "图" + m.group(1) + (("-" + m.group(2)) if m.group(2) else "")


def cap_ok(m: re.Match) -> bool:
    tail = (m.group(3) or "").strip()
    if len(tail) > 8:
        return False
    return not RE_CAP_TAIL_BAD.search(tail)


def is_caption_line(line: str, caption: str) -> bool:
    m = RE_CAP.match(line or "")
    return bool(m) and cap_key(m) == caption and cap_ok(m)


def caption_lines(lines: list[str], caption: str) -> list[int]:
    return [i for i, ln in enumerate(lines) if is_caption_line(ln, caption)]


def image_line_before(lines: list[str], cap_idx: int, back: int = 3) -> int | None:
    """图注上方最近的**纯图段落**（strip 掉占位符后为空）。"""
    for step in range(1, back + 1):
        j = cap_idx - step
        if j < 0:
            return None
        t = (lines[j] or "").strip()
        if t and not strip_marks(t).strip():
            return j
    if RE_MARK.search(lines[cap_idx] or ""):   # 少数排版图注与图片同段
        return cap_idx
    return None


def find_stem(lines: list[str], content: str) -> int | None:
    for nd in needles(content):
        for i, ln in enumerate(lines):
            if nd and nd in norm(ln):
                return i
    return None


def caption_after_stem(lines: list[str], stem: int, max_fwd: int = 16):
    """题干下方第一条图注；撞到下一题/答案/解析就停（防串题）。"""
    for j in range(stem + 1, min(len(lines), stem + max_fwd + 1)):
        s = (lines[j] or "").strip()
        if not s:
            continue
        if RE_BOUNDARY.match(s):
            break
        m = RE_CAP.match(s)
        if m and cap_ok(m):
            return cap_key(m), j
    return None, None


# --------------------------------------------------------------------------- #
# docx 读取（带缓存）与二次导出
# --------------------------------------------------------------------------- #
class Docx:
    def __init__(self, doc_id: int, path: str):
        from services.docx_formula import parse_docx_with_images

        self.id = doc_id
        self.path = path
        self._parse = parse_docx_with_images
        self.res = self._parse(path)                 # 第一遍：不落盘
        self.lines = self.res.text.split("\n")
        self.images = {im.index: im for im in self.res.images}

    def export(self, indices: set[int], out_dir: Path) -> dict[int, str]:
        """第二遍：只导出指定序号（避免把整本 5000 张公式图写出来）。"""
        if not indices:
            return {}
        out_dir.mkdir(parents=True, exist_ok=True)
        res = self._parse(self.path, out_dir=str(out_dir), only_indices=set(indices))
        return {im.index: im.out_path for im in res.images if im.out_path}


def fetch_rows(qids: list[int]) -> tuple[dict[int, dict], dict[int, tuple]]:
    import psycopg

    from pipeline.config import pg_database_url

    with psycopg.connect(pg_database_url()) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, subject, source_label, content, origin_document_id,
                      jsonb_array_length(images)
               FROM quiz_questions WHERE id = ANY(%s)""",
            (qids,),
        )
        rows = {}
        for qid, subj, label, content, odid, nimg in cur.fetchall():
            rows[qid] = {"id": qid, "subject": subj, "label": label,
                         "content": content or "", "origin_document_id": odid,
                         "nimg": nimg or 0}
        labels = sorted({r["label"] for r in rows.values() if r["label"]})
        cur.execute("SELECT id, file_name, file_path FROM documents WHERE file_name = ANY(%s)",
                    (labels,))
        by_name = {fn: (did, fp) for did, fn, fp in cur.fetchall()}
        # 清单给的 doc + 各题源书 doc，都要能查到（--auto 会用到后者）
        ids = sorted({a.get("doc_id") for a in ANCHORS if a.get("doc_id")}
                     | {v[0] for v in by_name.values()})
        cur.execute("SELECT id, file_name, file_path FROM documents WHERE id = ANY(%s)", (ids,))
        by_id = {did: (fn, fp) for did, fn, fp in cur.fetchall()}
    for r in rows.values():
        did, _fp = by_name.get(r["label"], (None, None))
        r["src_doc_id"] = did
    return rows, by_id


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="题库配图提取（干跑）")
    ap.add_argument("--auto", action="store_true",
                    help="忽略清单里的 doc/图注，从每题的源 docx 自己推锚点")
    ap.add_argument("--export", action="store_true", help="真写 data/storage/images/")
    ap.add_argument("--qid", action="append", type=int, default=None, help="只处理这些题")
    ap.add_argument("--show-lines", action="store_true", help="打印命中行上下文")
    ap.add_argument("--min-w", type=int, default=MIN_W)
    ap.add_argument("--min-h", type=int, default=MIN_H)
    ap.add_argument("--anchors", default=None,
                    help="改用外部锚点 JSON：[{qids:[..],doc_id:88,caption:'图9',occurrence:1}]")
    ap.add_argument("--apply", action="store_true",
                    help="把 images 写进库（只写 images 列；非空数组跳过；默认先备份）")
    ap.add_argument("--no-backup", dest="backup", action="store_false",
                    help="跳过 create_backup()（不推荐）")
    ap.set_defaults(backup=True)
    args = ap.parse_args()
    if args.apply:
        args.export = True   # 写库必须先把图片落到正式目录

    global ANCHORS
    if args.anchors:
        with open(args.anchors, encoding="utf-8") as fh:
            ANCHORS = json.load(fh)

    all_qids = [q for a in ANCHORS for q in a["qids"]]
    if args.qid:
        all_qids = [q for q in all_qids if q in set(args.qid)]
    rows, docs_by_id = fetch_rows(all_qids)

    out_root = (IMG_ROOT / OUT_SUBDIR) if args.export else (
        Path(tempfile.gettempdir()) / "quiz_figures_preview")
    if not args.export and out_root.exists():
        # 干跑目录每次清空，避免上一轮的半成品混进本次结果（本次就踩过）
        import shutil

        shutil.rmtree(out_root, ignore_errors=True)
    import shutil as _sh

    _sh.rmtree(Path(tempfile.gettempdir()) / "quiz_figures_raw", ignore_errors=True)
    cache: dict[str, Docx] = {}
    ok_rows: list[dict] = []
    bad_rows: list[tuple] = []

    print(f"模式：{'EXPORT' if args.export else 'DRY-RUN'}   输出根：{out_root}")
    print("=" * 122)
    print(f"{'题号':<15}{'doc':<5}{'图注':<8}{'行#':<7}{'idx':<7}{'尺寸':<12}{'状态':<17}备注")
    print("-" * 122)

    for anchor in ANCHORS:
        qids = [q for q in anchor["qids"] if q in rows]
        if not qids:
            continue
        q0 = rows[qids[0]]
        caption = anchor.get("caption") or ""
        doc_id = anchor.get("doc_id")
        occ_hint = anchor.get("occurrence")
        note = ""

        # ---- ① doc 归属校验 ----
        if args.auto:
            doc_id = q0.get("src_doc_id")
            status = "AUTO"
        elif doc_id is None:
            status = "NO-DOC"
        elif q0.get("src_doc_id") and q0["src_doc_id"] != doc_id:
            status = "DOC-MISMATCH"
        else:
            status = "OK"
        if not doc_id:
            bad_rows.append((qids, "-", caption, "-", "-", "NO-DOC",
                             "source_label 在 documents 里找不到"))
            print(f"{str(qids):<15}{'-':<5}{caption:<8}{'-':<7}{'-':<7}{'-':<12}"
                  f"{'NO-DOC':<17}source_label 在 documents 里找不到")
            continue
        info = docs_by_id.get(doc_id)
        if not info or not info[1] or not os.path.exists(info[1]):
            bad_rows.append((qids, doc_id, caption, "-", "-", "DOC-FILE-MISSING", str(info)))
            print(f"{str(qids):<15}{doc_id:<5}{caption:<8}{'-':<7}{'-':<7}{'-':<12}"
                  f"{'DOC-FILE-MISSING':<17}{info}")
            continue
        doc_name, doc_path = info
        if doc_path not in cache:
            cache[doc_path] = Docx(doc_id, doc_path)
        doc = cache[doc_path]

        stem = find_stem(doc.lines, q0["content"])

        # ---- ② 定图注行 ----
        cap_line, occ = None, None
        if args.auto:
            if stem is None:
                # 题干都没定位到，不能断言"无图"，只能说无法验证
                cap2, cap_line, status = None, None, "STEM-MISS"
            else:
                cap2, cap_line = caption_after_stem(doc.lines, stem)
                if cap_line is not None:
                    caption = cap2
                    status = "AUTO"
                    note = "auto：题干下方第一条图注"
                else:
                    status = "NO-FIGURE"   # 题干找到、答案前无图注 → 确认无图
        else:
            cands = caption_lines(doc.lines, caption)
            if occ_hint and 1 <= int(occ_hint) <= len(cands):
                occ = int(occ_hint)
                note = f"锚点指定第 {occ} 处（共 {len(cands)} 处）"
            if not cands:
                # "图9-1" 这种写法可能指"图9 的第 1 处"，按出现序号兜底
                m = re.match(r"^图\s*(\d+)\s*[-－—]\s*(\d+)$", caption)
                if m:
                    base, n = "图" + m.group(1), int(m.group(2))
                    cands = caption_lines(doc.lines, base)
                    if cands:
                        note = f"清单写 {caption}，按「{base} 第{n}处」理解"
                        caption, occ = base, n
                if not cands:
                    status = "CAPTION-MISS"
                else:
                    pass
            if status not in ("OK", "AUTO"):
                pass
            elif occ and 1 <= occ <= len(cands):
                cap_line = cands[occ - 1]
                if stem is None:
                    note = (note + "；" if note else "") + "题干未在 docx 定位，按出现序号硬选"
            elif stem is None:
                status = "STEM-MISS"
            else:
                cap_line = min(cands, key=lambda i: abs(i - stem))
                if len(cands) > 1:
                    note = (note + "；" if note else "") + f"图注 {len(cands)} 处，取离题干最近 # {cap_line}"

        if status in ("DOC-MISMATCH", "STEM-MISS", "CAPTION-MISS", "NO-FIGURE") or cap_line is None:
            bad_rows.append((qids, doc_id, caption, "-", "-", status, note))
            print(f"{str(qids):<15}{doc_id:<5}{caption:<8}{'-':<7}{'-':<7}{'-':<12}"
                  f"{status:<17}{note}")
            continue

        # ---- ③ 取图注上方纯图段落 ----
        img_line = image_line_before(doc.lines, cap_line)
        if img_line is None:
            bad_rows.append((qids, doc_id, caption, cap_line, "-", "NO-IMAGE-LINE", ""))
            print(f"{str(qids):<15}{doc_id:<5}{caption:<8}{cap_line:<7}{'-':<7}{'-':<12}"
                  f"{'NO-IMAGE-LINE':<17}")
            continue
        idxs = [int(x) for x in RE_MARK.findall(doc.lines[img_line])]
        if len(idxs) > 1:
            note = (note + "；" if note else "") + f"该段含 {len(idxs)} 张图，取第 1 张"

        ok_rows.append({
            "qids": qids, "doc_id": doc_id, "doc_name": doc_name, "doc_path": doc_path,
            "caption": caption, "cap_line": cap_line, "img_line": img_line,
            "img_index": idxs[0], "status": status, "note": note, "stem_line": stem,
        })

    # ---- ④ 按 doc 聚合批量导出 ----
    by_doc: dict[str, set[int]] = {}
    for p in ok_rows:
        by_doc.setdefault(p["doc_path"], set()).add(p["img_index"])
    exported: dict[tuple[str, int], str] = {}
    raw_root = Path(tempfile.gettempdir()) / "quiz_figures_raw"
    for path, idxs in by_doc.items():
        doc = cache[path]
        # 原始字节一律落临时目录，正式目录只留最终命名的 PNG
        for i, fp in doc.export(idxs, raw_root / str(doc.id)).items():
            exported[(path, i)] = fp

    # ---- ⑤ 定名 + 尺寸校验 ----
    from PIL import Image

    print("-" * 122)
    done: list[dict] = []
    for p in ok_rows:
        raw = exported.get((p["doc_path"], p["img_index"]))
        if not raw or not os.path.exists(raw):
            p["status"] = "EXPORT-FAIL"
            print(f"{str(p['qids']):<15}{p['doc_id']:<5}{p['caption']:<8}{p['cap_line']:<7}"
                  f"{p['img_index']:<7}{'-':<12}{'EXPORT-FAIL':<17}{p['note']}")
            continue
        with Image.open(raw) as im:
            w, h = im.size
            img = im.convert("RGB")
        ratio = (w / h) if h else 0.0
        reasons = []
        if w <= args.min_w:
            reasons.append(f"宽{w}≤{args.min_w}")
        if h <= args.min_h:
            reasons.append(f"高{h}≤{args.min_h}")
        if not (MIN_RATIO <= ratio <= MAX_RATIO):
            reasons.append(f"宽高比{ratio:.2f}越界")
        suspect = bool(reasons)
        name = f"{p['qids'][0]}_{p['caption']}.png"
        dest = out_root / str(p["doc_id"]) / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, format="PNG", optimize=True)
        p.update({
            "path": f"{OUT_SUBDIR}/{p['doc_id']}/{name}",
            "size": f"{w}x{h}", "bytes": dest.stat().st_size,
            "suspect": suspect, "reasons": reasons,
            "status": "SUSPECT" if suspect else p["status"],
            # 落库形状（team-lead 定）：path 相对 data/storage/images/，source 固定 docx
            "images": [{"kind": "figure", "path": f"{OUT_SUBDIR}/{p['doc_id']}/{name}",
                        "caption": p["caption"], "source": "docx"}],
        })
        done.append(p)
        tail = "; ".join([x for x in [p["note"], ("; ".join(reasons) if reasons else "")] if x])
        print(f"{str(p['qids']):<15}{p['doc_id']:<5}{p['caption']:<8}{p['cap_line']:<7}"
              f"{p['img_index']:<7}{f'{w}x{h}':<12}{p['status']:<17}{tail}")
        if args.show_lines:
            for j in range(max(0, p["img_line"] - 2),
                           min(len(cache[p["doc_path"]].lines), p["cap_line"] + 2)):
                mk = ">>" if j in (p["img_line"], p["cap_line"]) else "  "
                print(f"      {mk}{j:5d} {cache[p['doc_path']].lines[j].strip()[:82]}")

    # ---- ⑥ 拟写入形状 ----
    print("=" * 122)
    print("拟写入 images（干跑，未写库）：")
    shared: dict[str, list[int]] = {}
    for p in done:
        for q in p["qids"]:
            shared.setdefault(p["path"], []).append(q)
            print(f"  q{q:<5} ← {json.dumps(p['images'], ensure_ascii=False)}")
    for path, qs in shared.items():
        if len(qs) > 1:
            print(f"  共享：{path} 覆盖 {qs}（只落盘一次）")

    n_ok = sum(1 for p in done if not p["suspect"])
    n_sus = sum(1 for p in done if p["suspect"])
    print(f"\n汇总：可落地 {len(done)} 行（正常 {n_ok} / suspect {n_sus}）｜"
          f"未通过 {len(bad_rows)} 行")
    for qids, did, cap, _l, _i, st, nt in bad_rows:
        print(f"  ✗ q{qids} doc{did} {cap} → {st} {nt}")

    if not args.apply:
        print(f"\n{'EXPORT' if args.export else 'DRY-RUN'}："
              f"图片落在 {out_root}，**未写库**（要写库加 --apply）。")
        return 0

    # ---- ⑦ 写库（只写 images 一列） ----
    import psycopg

    from pipeline.config import pg_database_url

    print("=" * 122)
    print("开始写库…")
    if args.backup:
        from services.backup_service import create_backup

        bp = create_backup()
        print(f"备份完成：{bp}")

    writes: list[tuple[int, list[dict]]] = []
    for p in done:
        for q in p["qids"]:
            writes.append((q, p["images"]))

    ok, skipped, failed = 0, [], []
    with psycopg.connect(pg_database_url()) as conn, conn.cursor() as cur:
        for qid, payload in writes:
            cur.execute("SELECT images FROM quiz_questions WHERE id=%s", (qid,))
            got = cur.fetchone()
            if got is None:
                failed.append((qid, "题号不存在"))
                conn.rollback()
                continue
            cur_n = len(got[0]) if isinstance(got[0], list) else 0
            if cur_n > 0:
                skipped.append((qid, f"images 已有 {cur_n} 条，拒绝覆盖"))
                conn.rollback()
                continue
            try:
                # 双保险：SQL 层再判一次空数组
                cur.execute(
                    """UPDATE quiz_questions SET images=%s::jsonb, updated_at=now()
                       WHERE id=%s AND (images IS NULL OR jsonb_array_length(images)=0)""",
                    (json.dumps(payload, ensure_ascii=False), qid),
                )
                if cur.rowcount != 1:
                    skipped.append((qid, "UPDATE 命中 0 行（并发改动？）"))
                    conn.rollback()
                    continue
                conn.commit()          # 逐条提交，单条失败不影响前面
                ok += 1
                print(f"  ✓ q{qid} ← {payload[0]['path']}")
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                failed.append((qid, str(exc)[:120]))

        cur.execute(
            """SELECT id, jsonb_array_length(images) FROM quiz_questions
               WHERE id = ANY(%s) ORDER BY id""",
            ([q for q, _ in writes],),
        )
        after = cur.fetchall()

    print(f"\n写库结果：成功 {ok}｜跳过 {len(skipped)}｜失败 {len(failed)}")
    for qid, why in skipped:
        print(f"  - q{qid} 跳过：{why}")
    for qid, why in failed:
        print(f"  ✗ q{qid} 失败：{why}")
    print("复核（id, jsonb_array_length）：", after)
    bad = [i for i, n in after if n != 1]
    print("口径校验：" + ("全部为 1 ✓" if not bad else f"异常 {bad} ✗"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
