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
2. **页数封顶**（--max-pages，默认 300）：红宝书 1655MB、张宇高数 909MB 这类
   全页 OCR 必然超时；教材前 300 页已覆盖主体考点，够训练用了。
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


def _get_engine():
    """惰性初始化 RapidOCR。进程内只建一次（模型加载 ~2s，多建几次纯属浪费）。"""
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def _ocr_image(img) -> str:
    """单张图 OCR，返回文本。识别失败不抛异常——返回空串由上层判长度。"""
    import numpy as np
    engine = _get_engine()
    result, _ = engine(img)
    if not result:
        return ""
    parts = []
    for line in result:
        # result 每项是 [box, text, score]
        if len(line) >= 2 and line[1]:
            parts.append(str(line[1]))
    return "\n".join(parts)


def extract_one(path: Path, max_pages: int, min_chars: int, mode: str = "auto") -> dict:
    """抽取单个文件。返回结果 dict，任何异常都收进 err 字段而不是抛出。

    ### PDF 走"文字层优先 + OCR 兜底"的混合模式（关键性能设计）

    知识库里 PDF 占绝大多数，来源只有两类：
      - **数字版**（PPT 导出、讲义、题库 PDF、教材排版稿）——带文字层，
        pypdfium2 直接 `get_text_range()` 取字，**毫秒级**，比逐页渲染 OCR 快两个量级；
      - **扫描版**（拍照教材、影印真题）——没有文字层，只能渲染成图再 OCR。

    若不分流一律 OCR，数字版那批会被白白拖慢几十倍。所以 `auto` 模式先试文字层：
    整篇取字够长就判定为数字版直接收工；不够则逐页判断——某页文字层不足 30 字
    才渲染该页做 OCR（混合型 PDF，实测最常见）。
    """
    t0 = time.time()
    rec = {"src": str(path), "chars": 0, "pages": 0, "ocr_used": False,
           "kind": "", "text": "", "pages_text": [], "err": ""}
    try:
        suffix = path.suffix.lower()
        page_texts: list[str] = []   # 逐页文本，下游题目抽取靠它把题目映射回原页图片

        if suffix in IMAGE_EXT:
            from PIL import Image
            with Image.open(path) as im:
                im = im.convert("RGB")
                page_texts.append(_ocr_image(im))
            rec["pages"] = 1
            rec["ocr_used"] = True
            rec["kind"] = "image"

        elif suffix in DOC_EXT:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(str(path))
            try:
                n = len(pdf)
                rec["pages"] = min(n, max_pages)
                scanned_pages = 0

                for i in range(rec["pages"]):
                    page = pdf[i]
                    try:
                        layer_text = ""
                        if mode in ("auto", "text"):
                            try:
                                tp = page.get_textpage()
                                try:
                                    layer_text = (tp.get_text_range() or "").strip()
                                finally:
                                    tp.close()
                            except Exception:
                                # 文字层解析失败的页，按无文字层处理
                                layer_text = ""

                        if len(layer_text) >= _TEXT_LAYER_MIN:
                            page_texts.append(layer_text)
                            continue

                        # 先占位，保持 pages_text 与页码严格一一对应
                        page_texts.append("")
                        if mode == "text":
                            continue
                        # 文字层不足 → 渲染该页 OCR（扫描版 / 混合版）
                        scanned_pages += 1
                        bitmap = page.render(scale=2.0)   # ~144dpi，兼顾精度与速度
                        pil = bitmap.to_pil().convert("RGB")
                        t = _ocr_image(pil)
                        if t:
                            page_texts[i] = t
                    finally:
                        # page 也要显式释放，否则大文件会耗尽内存
                        try:
                            page.close()
                        except Exception:
                            pass

                rec["kind"] = ("scanned" if scanned_pages >= rec["pages"] * 0.8
                               else "hybrid" if scanned_pages else "digital")
                rec["ocr_used"] = scanned_pages > 0
                rec["scanned_pages"] = scanned_pages
            finally:
                # 必须显式 close：文档对象不关会一直持有文件句柄，
                # 同一 worker 后面再开别的 PDF 会报 "PDFium: File access error"。
                pdf.close()

        # pages_text 与页码严格一一对应（含空串占位）：题目抽取要靠它把
        # 第 N 页的题目映射回原 PDF 第 N 页，去渲染该页作为题目配图。
        rec["pages_text"] = page_texts
        # text 供人看 / 供合成数据当种子，带页标记便于溯源
        rec["text"] = "\n\n".join(
            f"【第{i + 1}页】{t}" for i, t in enumerate(page_texts) if t and t.strip()
        ).strip()
        rec["chars"] = sum(len(t) for t in page_texts)
        if rec["chars"] < min_chars:
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
    ap.add_argument("--max-pages", type=int, default=300, help="单文件页数封顶")
    ap.add_argument("--max-files", type=int, default=0, help="最多处理多少文件（0=不限）")
    ap.add_argument("--time-budget-min", type=int, default=240,
                    help="时间预算（分钟），到点优雅收尾，下轮续跑")
    ap.add_argument("--min-chars", type=int, default=200,
                    help="低于此字数视为抽取失败（会写 err，便于人工排查）")
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
            stats["pages"] += rec["pages"]

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