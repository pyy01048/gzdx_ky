#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSW 批量 OCR 抽取（Linux 版，可断点续跑 + 页数封顶 + 时间预算）。

### 为什么单独写一份而不是复用本地的 smart_ingest.py

本地管线（services/document_parser.py + services/smart_ingest.py）是**入库**用的：
OCR 完还要清洗、分类、抽知识点、写 PostgreSQL。而 DSW 连不到本地数据库，
云端只能干"文件 → 文字"这一段，产物写 JSON 交给本地入库。所以这里刻意只做抽取，
不做清洗与入库——职责单一，且能被 run_everything.sh 安全地串进一条龙。

### 三个必须有的护栏（否则全量跑必被拖死）

1. **断点续跑**：已产出 JSON 的文件直接跳过。DSW 实例随时可能被回收，
   重跑只补没做完的，不从头再来。
2. **正文页封顶 + 答案区例外**（--max-pages，默认 300）：主体最多处理指定页数；
   同时探测后续页，一旦命中“参考答案/答案解析”等标题，从该页一直处理到文末，
   避免把书末答案截掉。
3. **时间预算**（--time-budget-min，默认 240）：到点就优雅收尾，
   下一轮续跑接着做，不追求单次跑完。

### 用法

    pip install rapidocr-onnxruntime pypdfium2 pillow

    python3 ocr_extract.py --src-dir /mnt/data/考研资料数据集 \
                           --out-dir /mnt/workspace/ocr_out \
                           --workers 12 --max-pages 300 --time-budget-min 240

    # 只看会处理哪些文件（不干活）
    python3 ocr_extract.py --src-dir ... --out-dir ... --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

# 容器 locale 可能是 POSIX，打印中文进度会 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DOC_EXT = {".pdf"}
#: 明显不是学习资料的扩展名，直接排除（省掉无谓的目录遍历）
SKIP_EXT = {
    ".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".zip", ".rar", ".7z",
    ".exe", ".dll", ".mp3", ".wav", ".flac", ".m4a", ".iso", ".db", ".sqlite",
}


# --------------------------------------------------------------------------- #
# 依赖检查：缺什么给什么，不要让脚本跑到一半才炸
# --------------------------------------------------------------------------- #

def check_deps() -> tuple[bool, list[str]]:
    missing = []
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        missing.append("rapidocr-onnxruntime")
    try:
        import pypdfium2  # noqa: F401
    except ImportError:
        missing.append("pypdfium2")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("pillow")
    return (not missing), missing


# --------------------------------------------------------------------------- #
# 单文件抽取（每个 worker 进程内各自持有一份 OCR 引擎）
# --------------------------------------------------------------------------- #

_ENGINE = None

#: 某页文字层少于这么多字，就认为这页是扫描图，改走 OCR
_TEXT_LAYER_MIN = 30

#: 答案区标题信号。正文页仍受 --max-pages 限制，命中后的答案区一直处理到文末。
_ANSWER_PAGE_RE = re.compile(
    r"(?:参考答案|标准答案|习题答案|试题答案|答案(?:与|及)?解析|答案索引)"
)

#: OCR 页块坐标保留的小数位，避免 JSON 产生冗长浮点数。
_BBOX_DIGITS = 2


def _get_engine():
    """惰性初始化 RapidOCR。进程内只建一次（模型加载 ~2s，多建几次纯属浪费）。"""
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def _box_to_bbox(points) -> list[float]:
    """RapidOCR 四点框转为 ``[x0,y0,x1,y1]``。"""
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return [
        round(min(xs), _BBOX_DIGITS),
        round(min(ys), _BBOX_DIGITS),
        round(max(xs), _BBOX_DIGITS),
        round(max(ys), _BBOX_DIGITS),
    ]


def _ocr_image_blocks(img) -> tuple[str, list[dict]]:
    """单张图 OCR，返回全文和带 bbox 的行级文本块。"""
    import numpy as np

    engine = _get_engine()
    result, _ = engine(np.asarray(img))
    if not result:
        return "", []
    parts: list[str] = []
    blocks: list[dict] = []
    for line in result:
        # RapidOCR 每项是 [box, text, score]
        if len(line) < 2 or not line[1]:
            continue
        text = str(line[1]).strip()
        if not text:
            continue
        parts.append(text)
        bbox = _box_to_bbox(line[0]) if line[0] else [0.0, 0.0, 0.0, 0.0]
        block = {"type": "text", "bbox": bbox, "text": text}
        if len(line) >= 3 and line[2] is not None:
            block["confidence"] = round(float(line[2]), 4)
        blocks.append(block)
    return "\n".join(parts), blocks


def _ocr_image(img) -> str:
    """兼容旧调用：只返回 OCR 文本。"""
    return _ocr_image_blocks(img)[0]


def _scale_blocks(blocks: list[dict], scale_x: float, scale_y: float) -> list[dict]:
    """把渲染像素坐标换算成 PDF 页坐标。"""
    out: list[dict] = []
    for block in blocks:
        x0, y0, x1, y1 = block["bbox"]
        item = dict(block)
        item["bbox"] = [
            round(x0 * scale_x, _BBOX_DIGITS),
            round(y0 * scale_y, _BBOX_DIGITS),
            round(x1 * scale_x, _BBOX_DIGITS),
            round(y1 * scale_y, _BBOX_DIGITS),
        ]
        out.append(item)
    return out


def _answer_page(text: str) -> bool:
    return bool(_ANSWER_PAGE_RE.search(text or ""))


def _extract_pdf_page(pdf, page_index: int, mode: str, render_scale: float = 2.0) -> dict:
    """抽取一页，统一返回页尺寸、文本、OCR 标记与版面块。"""
    page = pdf[page_index]
    try:
        width, height = (float(v) for v in page.get_size())
        layer_text = ""
        if mode in ("auto", "text"):
            try:
                tp = page.get_textpage()
                try:
                    layer_text = (tp.get_text_range() or "").strip()
                finally:
                    tp.close()
            except Exception:
                layer_text = ""

        if len(layer_text) >= _TEXT_LAYER_MIN:
            return {
                "page_no": page_index + 1,
                "width": round(width, _BBOX_DIGITS),
                "height": round(height, _BBOX_DIGITS),
                "blocks": [{
                    "type": "text",
                    "bbox": [0.0, 0.0, round(width, _BBOX_DIGITS), round(height, _BBOX_DIGITS)],
                    "text": layer_text,
                }],
                "text": layer_text,
                "ocr_used": False,
                "has_page_image": False,
            }

        full_page_image = {
            "type": "image",
            "bbox": [0.0, 0.0, round(width, _BBOX_DIGITS), round(height, _BBOX_DIGITS)],
            "text": "",
        }
        if mode == "text":
            blocks = [full_page_image]
            if layer_text:
                blocks.append({
                    "type": "text",
                    "bbox": [0.0, 0.0, round(width, _BBOX_DIGITS), round(height, _BBOX_DIGITS)],
                    "text": layer_text,
                })
            return {
                "page_no": page_index + 1,
                "width": round(width, _BBOX_DIGITS),
                "height": round(height, _BBOX_DIGITS),
                "blocks": blocks,
                "text": layer_text,
                "ocr_used": False,
                "has_page_image": True,
            }

        bitmap = page.render(scale=render_scale)
        try:
            pil = bitmap.to_pil().convert("RGB")
            text_value, pixel_blocks = _ocr_image_blocks(pil)
            scale_x = width / max(1, pil.width)
            scale_y = height / max(1, pil.height)
        finally:
            try:
                bitmap.close()
            except Exception:
                pass
        return {
            "page_no": page_index + 1,
            "width": round(width, _BBOX_DIGITS),
            "height": round(height, _BBOX_DIGITS),
            "blocks": [full_page_image, *_scale_blocks(pixel_blocks, scale_x, scale_y)],
            "text": text_value,
            "ocr_used": True,
            "has_page_image": True,
        }
    finally:
        try:
            page.close()
        except Exception:
            pass


def extract_one(path: Path, max_pages: int, min_chars: int, mode: str = "auto") -> dict:
    """抽取单个文件；正文页封顶，但检测到的答案区始终处理到文末。"""
    t0 = time.time()
    rec = {
        "src": str(path),
        "chars": 0,
        "pages": 0,
        "total_pages": 0,
        "ocr_used": False,
        "kind": "",
        "text": "",
        "pages_text": [],
        "answer_page_start": None,
        "visual_only_pages": 0,
        "warnings": [],
        "err": "",
    }
    try:
        suffix = path.suffix.lower()
        page_records: dict[int, dict] = {}

        if suffix in IMAGE_EXT:
            from PIL import Image

            with Image.open(path) as im:
                im = im.convert("RGB")
                text_value, blocks = _ocr_image_blocks(im)
                width, height = im.size
            page_records[0] = {
                "page_no": 1,
                "width": width,
                "height": height,
                "blocks": [
                    {"type": "image", "bbox": [0, 0, width, height], "text": ""},
                    *blocks,
                ],
                "text": text_value,
                "ocr_used": True,
                "has_page_image": True,
            }
            rec["total_pages"] = 1
            rec["kind"] = "image"

        elif suffix in DOC_EXT:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(path))
            try:
                total_pages = len(pdf)
                rec["total_pages"] = total_pages
                base_limit = total_pages if max_pages <= 0 else min(total_pages, max_pages)
                answer_start: int | None = None

                # 主体区按上限处理，同时留意答案标题是否已在上限内出现。
                for i in range(base_limit):
                    page_rec = _extract_pdf_page(pdf, i, mode)
                    page_records[i] = page_rec
                    if answer_start is None and _answer_page(page_rec["text"]):
                        answer_start = i

                # 若上限内还没见答案区，以低分辨率探测剩余页；一旦命中，
                # 从答案标题页起恢复正常精度并一直处理到文末，避免丢书末答案。
                if base_limit < total_pages and answer_start is None:
                    for i in range(base_limit, total_pages):
                        probe = _extract_pdf_page(pdf, i, mode, render_scale=1.0)
                        if _answer_page(probe["text"]):
                            answer_start = i
                            break

                if base_limit < total_pages and answer_start is not None:
                    for i in range(max(base_limit, answer_start), total_pages):
                        page_records[i] = _extract_pdf_page(pdf, i, mode)

                rec["answer_page_start"] = answer_start + 1 if answer_start is not None else None
                rec["truncated"] = len(page_records) < total_pages
                scanned_pages = sum(1 for p in page_records.values() if p["ocr_used"])
                rec["kind"] = (
                    "scanned" if page_records and scanned_pages >= len(page_records) * 0.8
                    else "hybrid" if scanned_pages else "digital"
                )
                rec["scanned_pages"] = scanned_pages
            finally:
                pdf.close()

        ordered_pages = [page_records[i] for i in sorted(page_records)]
        rec["pages"] = len(ordered_pages)
        rec["ocr_used"] = any(p["ocr_used"] for p in ordered_pages)
        rec["visual_only_pages"] = sum(
            1 for p in ordered_pages if p["has_page_image"] and not p["text"].strip()
        )
        visual_pages = sum(1 for p in ordered_pages if p["has_page_image"])

        # 新契约：页尺寸 + 行级 OCR bbox；内部辅助字段不泄漏到 JSON。
        rec["pages"] = [
            {k: p[k] for k in ("page_no", "width", "height", "blocks")}
            for p in ordered_pages
        ]
        rec["processed_pages"] = len(ordered_pages)

        # 兼容旧下游：pages_text 下标仍等于原 PDF 页码 - 1；若书末答案越过
        # max_pages，中间未处理页用空串占位，不能把第 500 页误当第 301 页。
        last_page_no = ordered_pages[-1]["page_no"] if ordered_pages else 0
        page_texts = [""] * last_page_no
        for page_rec in ordered_pages:
            page_texts[page_rec["page_no"] - 1] = page_rec["text"]
        rec["pages_text"] = page_texts
        rec["text"] = "\n\n".join(
            f"【第{p['page_no']}页】{p['text']}" for p in ordered_pages if p["text"].strip()
        ).strip()
        rec["chars"] = sum(len(p["text"]) for p in ordered_pages)
        if rec["chars"] < min_chars:
            if visual_pages:
                rec["warnings"].append(
                    f"few_chars_but_visual({rec['chars']}<{min_chars},visual_pages={visual_pages})"
                )
            else:
                rec["err"] = f"too_few_chars({rec['chars']}<{min_chars})"
    except Exception as e:  # noqa: BLE001
        rec["err"] = f"{type(e).__name__}: {e}"
        rec["trace"] = traceback.format_exc(limit=2)
    rec["secs"] = round(time.time() - t0, 1)
    return rec


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def scan_files(src_dir: Path, limit: int | None) -> list[Path]:
    files = []
    for root, dirs, names in os.walk(src_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for n in names:
            p = Path(root) / n
            if p.suffix.lower() in IMAGE_EXT or p.suffix.lower() in DOC_EXT:
                files.append(p)
            elif p.suffix.lower() in SKIP_EXT:
                continue
    files.sort()
    if limit:
        files = files[:limit]
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="DSW 批量 OCR 抽取（可断点续跑）")
    ap.add_argument("--src-dir", default="/mnt/data/考研资料数据集",
                    help="资料目录（OSS 挂载点下）")
    ap.add_argument("--out-dir", default="/mnt/workspace/ocr_out",
                    help="产物目录：每文件一个 json")
    ap.add_argument("--workers", type=int, default=8,
                    help="并行进程数（OCR 是 CPU 密集，12-16 通常比 GPU 更划算）")
    ap.add_argument("--max-pages", type=int, default=300,
                    help="正文页数封顶；答案区命中后不封顶（0=全文）")
    ap.add_argument("--max-files", type=int, default=0, help="最多处理多少文件（0=不限）")
    ap.add_argument("--time-budget-min", type=int, default=240,
                    help="时间预算（分钟），到点优雅收尾，下轮续跑")
    ap.add_argument("--min-chars", type=int, default=200,
                    help="纯文本产物低于此字数视为失败；含图页仅告警、不丢弃")
    ap.add_argument("--mode", choices=["auto", "text", "ocr"], default="auto",
                    help="auto=文字层优先、扫描页才 OCR（推荐，快两个量级）；"
                         "text=只取文字层（纯数字版 PDF，抽样对比用）；"
                         "ocr=全部逐页 OCR（最慢，文字层质量差时兜底）")
    ap.add_argument("--dry-run", action="store_true", help="只列清单不干活")
    args = ap.parse_args()

    print("=" * 70)
    print("DSW 批量 OCR 抽取")
    print("=" * 70)
    print(f"源目录: {args.src_dir}")
    print(f"产物:   {args.out_dir}")
    print(f"并行:   {args.workers} | 页数封顶: {args.max_pages} | "
          f"时间预算: {args.time_budget_min} 分钟")

    ok_deps, missing = check_deps()
    if not ok_deps:
        print(f"\n✗ 缺依赖: {', '.join(missing)}")
        print(f"  安装: pip install {' '.join(missing)}")
        return 2

    src_dir = Path(args.src_dir)
    if not src_dir.is_dir():
        print(f"✗ 源目录不存在: {src_dir}")
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_files = scan_files(src_dir, args.max_files or None)
    # 断点续跑：已产出 json 的直接剔除
    todo = [p for p in all_files if not (out_dir / (p.stem + ".json")).exists()]
    print(f"\n共发现 {len(all_files)} 个可处理文件，"
          f"已完成 {len(all_files) - len(todo)}，本轮待处理 {len(todo)}")

    if args.dry_run:
        for p in todo[:30]:
            print(f"  {p}")
        if len(todo) > 30:
            print(f"  ... 还有 {len(todo) - 30} 个")
        return 0
    if not todo:
        print("✓ 没有待处理文件，全部已完成")
        return 0

    import multiprocessing as mp

    t_start = time.time()
    deadline = t_start + args.time_budget_min * 60
    stats = {"ok": 0, "fail": 0, "chars": 0, "pages": 0}
    kinds: dict[str, int] = {}
    fail_reasons: dict[str, int] = {}

    ctx = mp.get_context("spawn")   # OCR 引擎不能跨 fork 继承
    with ctx.Pool(processes=args.workers) as pool:
        done = 0
        for rec in pool.imap_unordered(
                _worker, ((p, args.max_pages, args.min_chars, args.mode) for p in todo),
                chunksize=1):
            done += 1
            dest = out_dir / (Path(rec["src"]).stem + ".json")
            try:
                with open(dest, "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False)
            except OSError as e:
                print(f"  [!] 写产物失败 {dest}: {e}")

            if rec["err"]:
                stats["fail"] += 1
                key = rec["err"].split("(")[0][:40]
                fail_reasons[key] = fail_reasons.get(key, 0) + 1
            else:
                stats["ok"] += 1
            if rec.get("kind"):
                kinds[rec["kind"]] = kinds.get(rec["kind"], 0) + 1
            stats["chars"] += rec["chars"]
            stats["pages"] += rec.get("processed_pages", len(rec.get("pages") or []))

            elapsed = time.time() - t_start
            if done % 20 == 0 or done == len(todo):
                rate = done / max(1e-6, elapsed / 60)
                eta = (len(todo) - done) / max(1e-6, rate) if rate else 0
                print(f"  [{done}/{len(todo)}] 成功 {stats['ok']} 失败 {stats['fail']} "
                      f"累计 {stats['chars']/10000:.1f}万字 "
                      f"| {rate:.1f} 文件/分 | 已用 {elapsed/60:.0f} 分钟 | 预计剩余 {eta:.0f} 分钟",
                      flush=True)

            if time.time() > deadline:
                print(f"\n! 已达时间预算（{args.time_budget_min} 分钟），"
                      f"优雅收尾。剩余 {len(todo) - done} 个文件下次续跑。")
                pool.terminate()
                break

    print("\n" + "=" * 70)
    print(f"完成 {done}/{len(todo)}：成功 {stats['ok']}，失败 {stats['fail']}，"
          f"抽出 {stats['chars']/10000:.1f} 万字 / {stats['pages']} 页")
    if kinds:
        print("PDF 类型分布（digital=数字版最快 / hybrid=部分扫描 / scanned=纯扫描）:")
        for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]):
            print(f"   {k:<10} {v}")
    if fail_reasons:
        print("失败原因分布:")
        for k, v in sorted(fail_reasons.items(), key=lambda kv: -kv[1])[:8]:
            print(f"   {k}: {v}")
    print(f"\n产物目录: {out_dir}")
    print("下一步：把这里的 json 拉回本地，走 smart_ingest 入库（本地才连得上 PG）")
    return 0


def _worker(args_tuple):
    p, max_pages, min_chars, mode = args_tuple
    return extract_one(Path(p), max_pages, min_chars, mode)


if __name__ == "__main__":
    raise SystemExit(main())