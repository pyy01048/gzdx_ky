#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""题目抽取（云端）：从 OCR 分页文本里识别题目，并把**原页渲染成配图**。

### 为什么必须带图

用户原话：「题目都有图片，没有图片做题库做啥都没用」。实测考研题库里，
电路图/波形图/框图题占了数电模电的相当比例——只抽文字等于把这类题全废掉。
所以本脚本对每道抽出的题目，用 pypdfium2 把**它所在的原页**渲染成 PNG，
随题目一起产出，本地入库后前端就能显示"原题页图"。

### 三份产物

| 文件 | 用途 |
|---|---|
| `quiz_questions.jsonl` | 题库记录（题干/选项/答案/题型/页码/配图路径/质量等级） |
| `quiz_questions.csv` | 同上，逗号分隔——给本地入库脚本或 Excel 核对用 |
| `vl_dataset.jsonl` | 视觉训练集：题干 + 原页图 → 答案讲解（喂 qwen2.5vl:7b） |
| `question_images/*.png` | 原页图 |

### 质量分级（对齐本地 quiz_quality_gate.py 的 A/B/C/JUNK 思路）

- **A**：题干 + 选项 + 明确答案字母 —— 可直接刷
- **B**：题干 + 答案（无选项，判断/填空/简答）—— 可刷
- **C**：题干完整但没抽到答案 —— 待补答案，本地侧走 answer_review_queue
- **JUNK**：像解析/目录/例题说明、题干过短 —— 丢弃

### 用法

    python3 extract_questions.py --ocr-dir /mnt/workspace/ocr_out \
        --img-dir /mnt/workspace/question_images \
        --out-dir /mnt/workspace/quiz_out \
        --max-images-per-doc 40 --max-docs 200
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

# --------------------------------------------------------------------------- #
# 题目识别模式
# --------------------------------------------------------------------------- #

#: 题号：1. / 1、/ 1．/ (1) / 1）
_Q_STEM = re.compile(
    r"^\s*(?:第?\s*(\d{1,3})\s*[题小]?\s*[.、．)）:：]|[（(]\s*(\d{1,3})\s*[)）])\s*(.+)$"
)
#: 选项：A. / A、/ A）/ （A）
_OPT = re.compile(r"^\s*[（(]?([A-HＡ-Ｈ])\s*[)）.、．:：]\s*(.+?)\s*$")
#: 答案标注：答案：B / 【答案】B / 正确答案: ABC / 参考答案：B
_ANS = re.compile(
    r"(?:正确答案|参考答案|标准答案|答案)\s*[：:是为]?\s*[【\[]?\s*([A-HＡ-Ｈ]{1,4}|"
    r"[对错√×]|正确|错误|.{1,60}?)\s*[】\]]?\s*$"
)
_JUDGE = re.compile(r"[（(]\s*(对|错|正确|错误|√|×)\s*[)）]\s*$")

#: 出现这些词的行是解析/说明，不是题干
_JUNK_MARK = ("答案解析", "【解析】", "解析:", "解析：", "分析:", "解:", "解答",
              "因为", "故选", "综上", "本章小结", "知识点", "考点", "【答案】")

#: 引用图示的信号 —— 命中这些的题目几乎一定配图，优先给它们渲染原页
_FIGURE_HINT = ("如图", "下图", "上图", "图所示", "图中的", "电路图", "波形",
                "框图", "示意图", "右图", "左图", "见图")

_SUBJECT_HINTS = [
    ("数字电子技术", ("数电", "数字电子", "逻辑电路", "触发器", "门电路")),
    ("模拟电子技术", ("模电", "模拟电子", "放大电路", "运放", "集成运放")),
    ("电路", ("电路", "电路分析", "节点电压", "戴维南", "诺顿")),
    ("数学", ("数学", "高数", "高等数学", "线代", "线性代数", "概率", "张宇", "同济")),
    ("政治", ("政治", "肖秀荣", "1000题", "考研政治", "马原", "毛概", "思修")),
    ("英语", ("英语", "词汇", "作文", "阅读理解")),
    ("物理", ("物理", "光学", "力学", "电磁")),
    ("通信原理", ("通信原理", "通信", "信号与系统")),
]


def guess_subject(name: str) -> str:
    for subj, keys in _SUBJECT_HINTS:
        if any(k in name for k in keys):
            return subj
    return "其他"


def clean_zh(s: str) -> str:
    """PDF/OCR 常在汉字中间留下换行带来的空格，抽取时要抹掉。"""
    t = re.sub(r"[ \t\u3000]+(?=[\u4e00-\u9fff])|(?<=[\u4e00-\u9fff])[ \t\u3000]+", "", s or "")
    return re.sub(r"\s+", " ", t).strip()


def looks_like_junk(stem: str) -> bool:
    return any(m in stem for m in _JUNK_MARK)


def parse_page(text: str, page_no: int, doc: str) -> list[dict]:
    """从一页文本里抽出题目块。

    题目块定义：题号行开头 → 收集后续选项行 → 就地找答案标注。
    只做**规则抽取**，不做语义判断；质量分级留给 grade_question。
    """
    lines = [l for l in (text or "").splitlines() if l.strip()]
    blocks: list[dict] = []
    cur: dict | None = None

    def close():
        nonlocal cur
        if cur:
            blocks.append(cur)
            cur = None

    for line in lines:
        ls = line.strip()
        stem_m = _Q_STEM.match(ls)
        if stem_m:
            close()
            num = stem_m.group(1) or stem_m.group(2)
            body = clean_zh(stem_m.group(3))
            # "1. 如图所示"里的 "1." 已被捕获；"第1题"这类也捕获
            if len(body) < 6 or looks_like_junk(body):
                continue
            cur = {"no": num, "content": body, "options": {},
                   "answer": "", "page": page_no, "doc": doc}
            continue

        if cur is None:
            continue

        opt_m = _OPT.match(ls)
        if opt_m and opt_m.group(1).upper() in "ABCDEFGH":
            cur["options"][opt_m.group(1).upper()] = clean_zh(opt_m.group(2))
            continue

        # 答案行：可能单独成行，也可能跟在题干/选项后面
        ans_m = None
        for seg in re.split(r"(?=[【\[]?(?:正确答案|参考答案|标准答案|答案))", ls):
            if "答案" in seg:
                m = _ANS.search(seg)
                if m:
                    # "【答案】ACD" 会把闭括号一起吃进捕获组，必须剥掉，
                    # 否则答案变成 "】ACD"，normalize 后的字母校验也会失败
                    ans_m = m.group(1).strip().strip("】】】]").strip()
                    break
        if ans_m:
            jm = _JUDGE.search(cur["content"])
            if jm and not cur["answer"]:
                cur["answer"] = "正确" if jm.group(1) in ("对", "正确", "√") else "错误"
            elif not cur["answer"]:
                cur["answer"] = ans_m
            continue

        # 段落续行：题干/解析的延续
        if len(cur["content"]) < 200 and not cur["options"]:
            cur["content"] += clean_zh(ls)

    close()
    return blocks


def grade_question(q: dict) -> str:
    """A/B/C/JUNK 四级，对齐本地门禁思路。"""
    content = q["content"]
    if len(content) < 10 or looks_like_junk(content):
        return "JUNK"
    has_opts = len(q["options"]) >= 2
    ans = (q["answer"] or "").strip()
    if not ans:
        return "C"
    # 答案必须与选项对得上，否则视为解析误抓
    if has_opts:
        letters = re.sub(r"[^A-HＡ-Ｈ]", "", ans.upper())
        if letters and not all(ch in q["options"] for ch in letters):
            return "C"
        return "A"
    if ans in ("正确", "错误", "对", "错", "√", "×"):
        return "B"
    if 2 <= len(ans) <= 80:
        return "B"
    return "C"


def normalize_answer(q: dict) -> str:
    """把答案归一成"字母 + 选项文字"，本地入库时前端能直接显示。"""
    ans = (q["answer"] or "").strip()
    if not q["options"]:
        return ans
    up = re.sub(r"[^A-H]", "", ans.upper())
    if not up:
        return ans
    texts = [q["options"].get(ch, "") for ch in up]
    joined = "、".join(t for t in texts if t)
    return f"{up}（{joined}）" if joined else up


def guess_type(q: dict) -> str:
    if len(q["options"]) >= 2:
        up = re.sub(r"[^A-H]", "", (q["answer"] or "").upper())
        return "multiple" if len(up) > 1 else "single"
    if (q["answer"] or "") in ("正确", "错误", "对", "错", "√", "×"):
        return "judge"
    if "____" in q["content"] or "＿＿" in q["content"]:
        return "blank"
    return "short_answer"


# --------------------------------------------------------------------------- #
# 原页渲染（题目配图）
# --------------------------------------------------------------------------- #

def render_page_images(src_pdf: str, pages: list[int], img_dir: Path,
                       stem: str, cap: int, scale: float = 1.6) -> dict[int, str]:
    """把指定页渲染成 PNG，返回 {页码: 相对路径}。

    只渲染**抽到题目的页**，且每篇封顶 cap 张——79GB 语料全渲染会把磁盘写爆，
    而真正需要配图的只是题目页。
    """
    out: dict[int, str] = {}
    pages = sorted(set(pages))[:cap]
    if not pages or Path(src_pdf).suffix.lower() != ".pdf":
        return out
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(src_pdf)
        try:
            for p in pages:
                if p < 1 or p > len(pdf):
                    continue
                page = pdf[p - 1]
                try:
                    name = f"{stem}_p{p:04d}.png"
                    dest = img_dir / name
                    if not dest.exists():
                        page.render(scale=scale).to_pil().convert("RGB").save(
                            dest, "PNG", optimize=True)
                    out[p] = f"question_images/{name}"
                except Exception:  # noqa: BLE001
                    continue
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
        finally:
            pdf.close()
    except Exception:  # noqa: BLE001
        return out
    return out


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="题目抽取（含原页配图）")
    ap.add_argument("--ocr-dir", default="/mnt/workspace/ocr_out")
    ap.add_argument("--out-dir", default="/mnt/workspace/quiz_out")
    ap.add_argument("--img-dir", default="/mnt/workspace/question_images")
    ap.add_argument("--max-docs", type=int, default=0, help="最多处理多少篇（0=不限）")
    ap.add_argument("--max-images-per-doc", type=int, default=40)
    ap.add_argument("--min-grade", choices=["A", "B", "C"], default="C",
                    help="低于此等级不入库（C 级也要，答案留给本地补）")
    ap.add_argument("--no-images", action="store_true", help="不渲染配图（只抽文字）")
    ap.add_argument("--limit-per-page", type=int, default=12,
                    help="单页最多抽几道题，防目录页把整页编号当题号")
    args = ap.parse_args()

    print("=" * 70)
    print("题目抽取（云端）")
    print("=" * 70)
    ocr_dir = Path(args.ocr_dir)
    if not ocr_dir.is_dir():
        print(f"✗ OCR 产物目录不存在: {ocr_dir}（先跑 ocr_extract.py）")
        return 2

    files = sorted(ocr_dir.glob("*.json"))
    if args.max_docs:
        files = files[:args.max_docs]
    print(f"待处理 OCR 产物: {len(files)} 篇")

    out_dir = Path(args.out_dir)
    img_dir = Path(args.img_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    grade_rank = {"A": 3, "B": 2, "C": 1}
    min_rank = grade_rank[args.min_grade]

    rows: list[dict] = []
    vl_rows: list[dict] = []
    stats = Counter()
    t0 = time.time()

    for i, p in enumerate(files, 1):
        try:
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if rec.get("err") or not rec.get("pages_text"):
            continue
        src = rec.get("src", "")
        stem = Path(src).stem or p.stem
        subject = guess_subject(src)
        pages_text = rec["pages_text"]

        # 逐页抽题
        doc_blocks: list[dict] = []
        for pi, ptxt in enumerate(pages_text, 1):
            if not ptxt:
                continue
            blocks = parse_page(ptxt, pi, src)
            for b in blocks[:args.limit_per_page]:
                doc_blocks.append(b)

        if not doc_blocks:
            stats["无题"] += 1
            continue

        # 配图渲染：题目页 + 命中图示信号的题目优先
        img_map: dict[int, str] = {}
        if not args.no_images:
            need = sorted({b["page"] for b in doc_blocks})
            img_map = render_page_images(src, need, img_dir, stem,
                                        args.max_images_per_doc)

        for b in doc_blocks:
            g = grade_question(b)
            stats[f"grade_{g}"] += 1
            if g == "JUNK" or grade_rank[g] < min_rank:
                continue
            content = b["content"]
            opts = b["options"]
            qtype = guess_type(b)
            image = img_map.get(b["page"], "")
            has_fig = any(h in content for h in _FIGURE_HINT) or bool(image)
            rows.append({
                "doc": src, "doc_stem": stem, "page": b["page"],
                "subject": subject, "chapter": "",
                "question_no": b["no"], "question_type": qtype,
                "content": content,
                "options": [f"{k}. {v}" for k, v in sorted(opts.items())],
                "answer": normalize_answer(b),
                "grade": g,
                "has_figure": has_fig,
                "image": image,
                "source": f"cloud_extract:{Path(src).name}",
            })
            # 视觉训练集：只收"有图"的题（纯文字题对视觉模型没训练价值）
            if has_fig and image:
                vl_rows.append({
                    "image": image,
                    "question": content,
                    "options": [f"{k}. {v}" for k, v in sorted(opts.items())],
                    "answer": normalize_answer(b),
                    "doc": src, "page": b["page"],
                })

        if i % 20 == 0 or i == len(files):
            print(f"  [{i}/{len(files)}] 累计题目 {len(rows)}（A{stats['grade_A']} "
                  f"B{stats['grade_B']} C{stats['grade_C']}）| "
                  f"配图 {len(img_map) and sum(1 for v in img_map.values())} | "
                  f"用时 {(time.time()-t0)/60:.1f} 分钟", flush=True)

    # —— 写出 ——
    jl = out_dir / "quiz_questions.jsonl"
    with open(jl, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    csv_p = out_dir / "quiz_questions.csv"
    with open(csv_p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["subject", "chapter", "question_type", "content", "options",
                    "answer", "grade", "doc", "page", "image", "source"])
        for r in rows:
            w.writerow([r["subject"], r["chapter"], r["question_type"], r["content"],
                        " | ".join(r["options"]), r["answer"], r["grade"],
                        r["doc"], r["page"], r["image"], r["source"]])

    vlp = out_dir / "vl_dataset.jsonl"
    with open(vlp, "w", encoding="utf-8") as f:
        for r in vl_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with_image = sum(1 for r in rows if r["image"])
    print("\n" + "=" * 70)
    print(f"题目总数 {len(rows)}：A {stats['grade_A']} / B {stats['grade_B']} / "
          f"C {stats['grade_C']}（JUNK {stats['grade_JUNK']} 已丢弃）")
    print(f"带配图 {with_image} 张 | 视觉训练样本 {len(vl_rows)} 条 | "
          f"图片文件 {len(list(img_dir.glob('*.png')))} 张")
    print(f"科目分布: {dict(Counter(r['subject'] for r in rows).most_common(8))}")
    print(f"\n产物:")
    print(f"  {jl}")
    print(f"  {csv_p}")
    print(f"  {vlp}")
    print(f"  {img_dir}/*.png")
    print("\n下一步：把 quiz_out + question_images 传回本地，")
    print("        走 smart_ingest 入题库 + vision 数据集喂 qwen2.5vl:7b")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())