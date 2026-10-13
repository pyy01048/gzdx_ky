"""批量把 knowledge_base 里未入库的文档导入真库（扩充知识库）。

背景（2026-10-12 体检）：磁盘 `D:\\平台\\knowledge_base` 有 4101 个文档类文件，
但真库 documents 只覆盖其中约 750 个 —— **3350 个文件从未解析入库**
（公共课 2170 / 专业课 597 / 真题 504 / 其他 78）。

本脚本复用既有入库管线 `services.kb_ingest.ingest_file`，只做批量调度：
  解析（PDF 文本层 → 图片直 OCR / 扫描件 OCR 回退）
  → 分块（knowledge_chunks + FTS）
  → 写 documents
  向量化**不逐文件做**（ingest_file 内置的逐文件 build_all_embeddings 会全库扫描，
  3350 次会慢到不可用），改为全部入库后统一跑一次。

特性：
  * 幂等可续跑：ingest_file 用 manifest md5 去重，已入库的自动 skipped
  * 不移动原件（move_to_documents=False），保持 knowledge_base 目录结构不变
  * 单文件异常不影响整体；结果逐条写入 JSONL 日志
  * 按优先级排序：真题 > 专业课 > 其他 > 公共课

用法：
    python scripts/ingest_kb_bulk.py --dry-run            # 只看清单
    python scripts/ingest_kb_bulk.py --limit 20           # 先试 20 个
    python scripts/ingest_kb_bulk.py                      # 全量
    python scripts/ingest_kb_bulk.py --only 真题,专业课   # 只跑指定顶层目录
    python scripts/ingest_kb_bulk.py --embed-at-end       # 全量入库后统一向量化
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import traceback
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

KB_ROOT = os.environ.get("KB_ROOT", r"D:\平台\knowledge_base")
SKIP_DIRS = {"documents", "chunks", "meta", "inbox", ".git",
             # _trash 是 cleanup_lowvalue.py 的隔离区（已判定为低价值），
             # 绝不能被重新扫描入库
             "_trash"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
TEXT_EXTS = {".txt", ".md", ".pdf", ".docx", ".doc", ".pptx", ".ppt"}
ALLOWED = IMAGE_EXTS | TEXT_EXTS

# 顶层目录优先级（越小越先跑）
PRIORITY = {"真题": 0, "专业课": 1, "其他": 2, "公共课": 3}

# 低价值/非知识内容排除（按文件名关键词）
# 注意：**不要加"打印"/"打印版"** —— 《2010-2024英语一真题一键打印版》
# 《高数刷题本（打印版）》这类是宝贵真题/题本，只是文件名带"打印"二字。
# 判定逻辑与 scripts/cleanup_lowvalue.py 的 classify() 保持一致。
_EXCLUDE_KW = (
    "答题卡", "答题纸", "答题版", "机读卡", "填涂卡",
    "签到表", "进度表", "计划表", "倒计时",
    "课程表", "课表",
    "打印店", "彩印", "在线打印",
    "封面及目录", "封面.ppt",
    "二维码", "扫码", "客服", "加微信", "公众号",
)

# 硬保护：文件名带上述词但本体是高价值词汇书，绝不能排除
_EXCLUDE_KEEP = (
    "红宝书", "艾宾浩斯抗遗忘打卡", "抗遗忘", "词汇闪过",
)


def needs_ocr(path: str) -> bool:
    """预判该文件是否需要 OCR（决定走快速通道还是 OCR 通道）。

    PDF：抽前 3 页，若总文本量 < 50 字 → 判定为扫描件，需要 OCR。
    图片：一律需要 OCR。
    其它（txt/md/docx/pptx）：不需要。

    这一步很关键：扫描件 PDF 逐页 OCR 单篇可达数分钟，
    若不做分流通吃会拖垮整个批量任务（实测 1994【00】.pdf 19 页全无文本层）。

    实现优先用 pypdfium2（比 pypdf 快一个数量级，且对损坏 PDF 更健壮），
    pypdfium2 不可用时再退回 pypdf。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return True
    if ext != ".pdf":
        return False

    # 首选 pypdfium2（快）
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(path)
        try:
            total = 0
            for i in range(min(3, len(pdf))):
                page = pdf[i]
                tp = page.get_textpage()
                total += len(tp.get_text_range() or "")
                if total >= 50:
                    return False
            return total < 50
        finally:
            pdf.close()
    except Exception:
        pass

    # 退回 pypdf
    try:
        import pypdf

        reader = pypdf.PdfReader(path)
        total = 0
        for page in reader.pages[:3]:
            try:
                total += len(page.extract_text() or "")
            except Exception:
                pass
            if total >= 50:
                return False
        return total < 50
    except Exception:
        return False  # 判断失败时按"不需 OCR"处理，交给解析器自行回退


def scan(only: List[str] | None) -> List[str]:
    out: List[str] = []
    for root, dirs, files in os.walk(KB_ROOT):
        rel = os.path.relpath(root, KB_ROOT)
        top = rel.split(os.sep)[0]
        if top in SKIP_DIRS:
            dirs[:] = []
            continue
        if rel == ".":
            top = "."
        if only and top not in only and top != ".":
            continue
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in ALLOWED:
                continue
            # 硬保护优先：高价值词汇书即使命中排除词也放行
            if any(k in f for k in _EXCLUDE_KEEP):
                out.append(os.path.join(root, f))
                continue
            if not any(k in f for k in _EXCLUDE_KW):
                out.append(os.path.join(root, f))

    def key(p: str):
        rel = os.path.relpath(p, KB_ROOT)
        top = rel.split(os.sep)[0]
        return (PRIORITY.get(top, 9), rel)

    out.sort(key=key)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default=None, help="逗号分隔顶层目录名，如 真题,专业课")
    ap.add_argument("--embed-at-end", action="store_true")
    ap.add_argument("--mode", default="fast", choices=["fast", "ocr", "all"],
                    help="fast=只处理有文本层的文件（默认）；ocr=只处理需要 OCR 的扫描件/图片；all=全部")
    ap.add_argument("--limit-scan", type=int, default=None,
                    help="只对前 N 个候选文件做 OCR 预判（加速起跑）")
    ap.add_argument("--log", default=os.path.join(BASE_DIR, "scripts", "_kb_bulk.jsonl"))
    args = ap.parse_args()

    only = [s.strip() for s in args.only.split(",")] if args.only else None
    files = scan(only)
    print(f"待处理候选文件: {len(files)}（仅统计磁盘，未判断是否已入库）")

    # 已入库过滤（用 manifest md5 + 路径双重判断）
    from services.kb_ingest import _load_manifest_hashes, ingest_file
    from database import SessionLocal

    # 去重：库里已有同 stem 的文档（如 xxx.txt 是 xxx.pdf 的解析产物），
    # 或同 stem 已入库过任何格式，则跳过，避免重复内容占用向量与检索
    existing_stems = set()
    try:
        _con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        for (fn,) in _con.execute("SELECT file_name FROM documents WHERE file_name IS NOT NULL"):
            stem = os.path.splitext(fn.strip())[0]
            if stem:
                existing_stems.add(stem)
        _con.close()
    except Exception as e:  # noqa: BLE001
        print("读取已入库文件名失败（跳过去重）:", e)
    print(f"库内已有文件名 stem: {len(existing_stems)}")

    before = len(files)
    files = [p for p in files
             if os.path.splitext(os.path.basename(p))[0] not in existing_stems]
    print(f"按 stem 去重: {before} → {len(files)}")

    known = _load_manifest_hashes()
    if os.path.isfile(args.log):
        with open(args.log, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("md5"):
                        known.setdefault(r["md5"], r.get("file", ""))
                except json.JSONDecodeError:
                    pass
    print(f"manifest 已知 md5: {len(known)}")

    # 按 mode 分流（OCR 预判）
    if args.mode != "all":
        scan_n = args.limit_scan or len(files)
        head, tail = files[:scan_n], files[scan_n:]
        _cache_path = os.path.join(BASE_DIR, "scripts", "_kb_ocr_cache.json")
        _cache: Dict[str, bool] = {}
        if os.path.isfile(_cache_path):
            try:
                _cache = json.load(open(_cache_path, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                _cache = {}

        def _flag(p: str) -> bool:
            try:
                st = os.stat(p)
                key = f"{os.path.relpath(p, KB_ROOT)}|{st.st_size}|{int(st.st_mtime)}"
            except OSError:
                return False
            if key not in _cache:
                _cache[key] = needs_ocr(p)
            return _cache[key]

        ocr_flags = []
        for _i, _p in enumerate(head, 1):
            ocr_flags.append(_flag(_p))
            if _i % 200 == 0:
                print(f"  预扫 {_i}/{len(head)} ...", flush=True)
                with open(_cache_path, "w", encoding="utf-8") as _f:
                    json.dump(_cache, _f)
        with open(_cache_path, "w", encoding="utf-8") as _f:
            json.dump(_cache, _f)
        if args.mode == "fast":
            files = [p for p, o in zip(head, ocr_flags) if not o] + []
        else:  # ocr
            files = [p for p, o in zip(head, ocr_flags) if o] + []
        print(f"OCR 预判完成（扫描 {len(head)} 个）：mode={args.mode} → {len(files)} 个"
              + (f"（另有 {len(tail)} 个未预判）" if tail else ""))

    if args.limit:
        files = files[: args.limit]

    if args.dry_run:
        print("\n=== 前 25 个 ===")
        for p in files[:25]:
            print("  ", os.path.relpath(p, KB_ROOT))
        return 0

    db = SessionLocal()
    log_f = open(args.log, "a", encoding="utf-8")
    stats: Dict[str, int] = {}
    done = 0
    t0 = time.time()

    for i, path in enumerate(files, 1):
        rel = os.path.relpath(path, KB_ROOT)
        try:
            res = ingest_file(
                db, path,
                ocr_backend="auto",
                do_embeddings=False,
                move_to_documents=False,
            )
        except Exception as e:  # noqa: BLE001
            res = {"file": os.path.basename(path), "status": "error",
                   "detail": f"{type(e).__name__}: {e}"}
            traceback.print_exc()
            try:
                db.rollback()
            except Exception:
                pass

        st = res.get("status", "?")
        stats[st] = stats.get(st, 0) + 1
        if st in ("ok", "dry-run-ok"):
            done += 1
        rec = {"rel": rel, **{k: v for k, v in res.items() if k != "file"}}
        log_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log_f.flush()

        if st == "ok":
            print(f"[{i}/{len(files)}] ✓ {rel} → {res.get('subject')} "
                  f"{res.get('chunks')}块 {res.get('ocr_used') or 'parser'}")
        elif st == "skipped":
            if i % 200 == 0:
                print(f"[{i}/{len(files)}] · 已入库跳过（累计）")
        else:
            print(f"[{i}/{len(files)}] ✗ {rel} → {res.get('detail')}")

        if i % 50 == 0:
            el = time.time() - t0
            print(f"--- 进度 {i}/{len(files)} | 成功{done} | {stats} | "
                  f"耗时{el:.0f}s | 均{el / i:.1f}s/篇 ---")

    log_f.close()
    print(f"\n=== 完成 === 处理 {len(files)} | 成功 {done} | 状态分布 {stats}")

    if args.embed_at_end:
        print("\n=== 统一向量化 ===")
        import asyncio
        from services import embedding_service

        r = asyncio.run(embedding_service.build_all_embeddings(db, force=False))
        print("向量化:", r)

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
