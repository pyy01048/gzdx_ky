# -*- coding: utf-8 -*-
"""智能入库 CLI（考研教材/讲义/真题/课件/扫描件）。

把 services.smart_ingest 的管线跑起来：
    图像预处理 → 版面/分流识别（文字 OCR / 公式 LaTeX / 图块 VLM）
    → 文本清洗 → 结构化抽取（学科/方向/教材/章节/内容类型）
    → 入库校验（乱码比例 / 长度 / 向量去重）→ 入库

用法：
    python scripts/smart_ingest.py --file <路径>              # 单文件（预演）
    python scripts/smart_ingest.py --file <路径> --apply      # 单文件（入库）
    python scripts/smart_ingest.py --scan-dir <目录> --apply  # 批量
    python scripts/smart_ingest.py --scan-dir <目录> --apply --limit 50
    python scripts/smart_ingest.py --file <路径> --vlm        # 启用 VLM 图块描述（慢）
    python scripts/smart_ingest.py --file <路径> --apply --force  # 校验不过也入库（标 need_review）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
    TimeoutError as FuturesTimeoutError,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DOC_EXT = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".md", ".txt",
           ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}

# 与 ingest_kb_bulk.py 保持一致：跳过缓存区与隔离区
SKIP_DIRS = {"documents", "chunks", "meta", "inbox", ".git", "_trash"}

# 低价值文件排除（与 ingest_kb_bulk._EXCLUDE_KW 同源）
# 注意：不含"打印"，否则会误杀《英语一真题一键打印版》等宝贵真题
EXCLUDE_KW = ("答题卡", "答题纸", "答题版", "机读卡", "填涂卡",
              "签到表", "进度表", "计划表", "倒计时",
              "课程表", "课表", "打印店", "彩印", "在线打印",
              "封面及目录", "封面.ppt")
# 硬保护：高价值词汇书
EXCLUDE_KEEP = ("红宝书", "艾宾浩斯抗遗忘打卡", "抗遗忘", "词汇闪过")


def _skip_file(name: str) -> bool:
    if any(k in name for k in EXCLUDE_KEEP):
        return False
    return any(k in name for k in EXCLUDE_KW)


def iter_files(root: str):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if os.path.splitext(f)[1].lower() in DOC_EXT and not _skip_file(f):
                yield os.path.join(dirpath, f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="单个文件路径")
    ap.add_argument("--scan-dir", help="批量扫描目录")
    ap.add_argument("--apply", action="store_true", help="真正入库（默认预演）")
    ap.add_argument("--force", action="store_true", help="校验不通过也入库并标 need_review")
    ap.add_argument("--vlm", action="store_true", help="启用 VLM 图块描述（慢）")
    ap.add_argument("--ocr-backend", default="auto")
    ap.add_argument("--no-kp", action="store_true",
                    help="入库时不抽知识点（等价 SMART_INGEST_KP=0；"
                         "默认开启，给本地模型加负载时用此关闭）")
    ap.add_argument("--kp-workers", type=int, default=None,
                    help="单文档内知识点抽取的 chunk 级并发度（默认 3）")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-size-mb", type=float, default=None,
                    help="只处理体积 ≤ 该值(MB) 的文件。大扫描件（最大 1.6GB）"
                         "解析会把内存吃到 4GB+ 触发 swap，先跑小文件保证主体入库，"
                         "大文件留到单独批次攻坚")
    ap.add_argument("--skip-ingested", action="store_true",
                    help="跳过库内已有同 stem 的文件（避免与既有导入重复）")
    ap.add_argument("--only-ocr", action="store_true",
                    help="只处理「需要 OCR」的文件（复用 ingest_kb_bulk 的预扫缓存）")
    ap.add_argument("--skip-ocr", action="store_true",
                    help="只处理「有文本层、不需 OCR」的文件")
    ap.add_argument("--workers", type=int, default=1,
                    help="并行 worker 数（OCR 是 CPU 密集，多进程/多线程可显著提速；"
                         "SQLite 写入会自动串行化，不会写坏库）")
    ap.add_argument("--timeout", type=int, default=600,
                    help="单文件处理超时（秒）。超时视为卡死并标记 error 跳过，"
                         "避免个别坏文件（OCR/LLM 调用挂死）拖垮整批 3584 篇入库")
    ap.add_argument("--json", action="store_true", help="输出 JSON 结果")
    args = ap.parse_args()

    if args.vlm:
        os.environ["SMART_INGEST_VLM"] = "1"
    if args.no_kp:
        os.environ["SMART_INGEST_KP"] = "0"
    if args.kp_workers:
        os.environ["SMART_INGEST_KP_CONCURRENCY"] = str(args.kp_workers)

    # ---- OCR 临时目录改到项目内，规避 %TEMP% 被 Defender/受控文件夹/权限策略拦截 ----
    # 扫描版 PDF 渲染出的临时 PNG、rapidocr/paddleocr 的字节临时文件默认都落在
    # C:\Users\...\AppData\Local\Temp。Windows 实时防护 / 受控文件夹访问常在此拦截
    # 写操作 → "Permission denied: tmpXXXX.png"；源文件打开偶发 "File access error"。
    # 统一改到项目内 .ocr_tmp，彻底绕开 %TEMP%（与 document_parser._ocr_pdf 的
    # mkstemp+close 修复互补：一个消除独占锁，一个把路径移出被拦的 %TEMP%）。
    _OCR_TMP = os.path.join(BASE_DIR, ".ocr_tmp")
    try:
        os.makedirs(_OCR_TMP, exist_ok=True)
        tempfile.tempdir = _OCR_TMP
        os.environ["TMPDIR"] = _OCR_TMP
    except Exception as _e:  # noqa: BLE001
        print("警告：无法设置项目内 OCR 临时目录，将沿用系统 %TEMP%:", _e)

    if not args.file and not args.scan_dir:
        ap.error("需要 --file 或 --scan-dir")

    targets = [args.file] if args.file else list(iter_files(args.scan_dir))
    if args.max_size_mb:
        _cap = args.max_size_mb * 1024 * 1024
        _before = len(targets)
        targets = [p for p in targets
                   if os.path.isfile(p) and os.path.getsize(p) <= _cap]
        print(f"体积过滤（≤{args.max_size_mb}MB）: {_before} → {len(targets)}")
    if args.skip_ingested:
        # 2026-10-18 修正：项目已切 PostgreSQL，这里却还在读遗留的 sqlite
        # database/kaoyan.db → "no such table: documents"，文件名去重彻底失效，
        # 已入库的文档会被整篇重新解析（含 1.6GB 扫描件），是整批跑不动的主因之一。
        stems = set()
        try:
            from database import SessionLocal
            from sqlalchemy import text as _sql_text

            sdb = SessionLocal()
            try:
                for (fn,) in sdb.execute(
                        _sql_text("SELECT file_name FROM documents "
                                  "WHERE file_name IS NOT NULL")):
                    s = os.path.splitext((fn or "").strip())[0]
                    if s:
                        stems.add(s)
            finally:
                sdb.close()
        except Exception as e:  # noqa: BLE001
            print("读取已入库文件名失败（跳过去重）:", e)
        before = len(targets)
        targets = [p for p in targets
                   if os.path.splitext(os.path.basename(p))[0] not in stems]
        print(f"跳过已入库: {before} → {len(targets)}")
    if args.limit:
        targets = targets[: args.limit]

    # 按预扫缓存筛「需 OCR / 不需 OCR」
    if args.only_ocr or args.skip_ocr:
        cache_path = os.path.join(BASE_DIR, "scripts", "_kb_ocr_cache.json")
        cache = {}
        if os.path.isfile(cache_path):
            try:
                cache = json.load(open(cache_path, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cache = {}
        if not cache:
            print("警告：无 OCR 预扫缓存，请先跑 ingest_kb_bulk --dry-run 生成缓存")
        KB_ROOT = r"D:\平台\knowledge_base"

        def _need(p: str):
            try:
                st = os.stat(p)
                return cache.get(f"{os.path.relpath(p, KB_ROOT)}|{st.st_size}|"
                                 f"{int(st.st_mtime)}")
            except OSError:
                return None

        before = len(targets)
        if args.only_ocr:
            targets = [p for p in targets if _need(p) is True]
        else:
            targets = [p for p in targets if _need(p) is False]
        print(f"OCR 筛选({('only' if args.only_ocr else 'skip')}): {before} → {len(targets)}")

    from database import SessionLocal
    from services.smart_ingest import smart_ingest_file

    # PG 迁移后，models 的若干列改了名 / 改了原生枚举类型。orm_aliases.install()
    # 补挂旧属性名别名（file_type→source_format、chunk_id→chunk_index 等）并对
    # PG 原生枚举列做类型适配，否则脚本里 `doc.file_type` 等属性访问会 AttributeError、
    # 枚举比较会报 `operator does not exist`，全量入库直接崩。main.py 入口已调用，
    # 这里脚本侧也要调用一次（幂等）。
    import orm_aliases
    orm_aliases.install()

    def _kp_brief(r: dict) -> str:
        """把 knowledge_points 统计压成一行可观测摘要。"""
        kp = r.get("knowledge_points") or {}
        if not kp:
            return ""
        if kp.get("skipped"):
            return f" KP跳过({kp.get('reason', '')[:40]})"
        return (f" KP+{kp.get('kept', 0)}"
                f"(块{kp.get('chunks', 0)} 抽{kp.get('extracted', 0)}"
                f" 丢{kp.get('dropped', 0)} 败{kp.get('failed', 0)}"
                f" {kp.get('seconds', 0)}s)")

    def _ingest_one(p: str):
        """在独立线程里跑 smart_ingest_file（自带 DB session）。"""
        sdb = SessionLocal()
        try:
            return smart_ingest_file(
                sdb, p,
                ocr_backend=args.ocr_backend,
                dry_run=not args.apply,
                force=args.force,
                extract_kp=False if args.no_kp else None,
            )
        except Exception as e:  # noqa: BLE001
            try:
                sdb.rollback()
            except Exception:
                pass
            return {"file": os.path.basename(p), "status": "error", "reasons": [str(e)]}
        finally:
            sdb.close()

    def _one(p: str):
        """每个文件独立 session（SQLAlchemy session 非线程安全）。

        用单线程池 + 超时兜底：个别文件若因 OCR/LLM 调用挂死，超过
        --timeout 即判为卡死并标记 error 跳过，绝不阻塞整批 3584 篇入库。
        """
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            fut = ex.submit(_ingest_one, p)
            return fut.result(timeout=args.timeout)
        except FuturesTimeoutError:
            return {"file": os.path.basename(p), "status": "error",
                    "reasons": [f"单文件超时（{args.timeout}s）疑似卡死，已跳过"]}
        finally:
            # 不能用 with（等价 shutdown(wait=True)）：一旦某个坏文件的解析线程
            # 死循环，主线程会在 __exit__ 里永久阻塞，fut.result(timeout=...)
            # 的超时兜底彻底失效 —— 这正是整批 3584 篇卡死在第 5 篇的原因。
            ex.shutdown(wait=False, cancel_futures=True)

    stats = {}
    results = []
    t0 = time.time()

    if args.workers > 1:
        # 只补 as_completed：ThreadPoolExecutor 用顶部的 import，
        # 若在此重复 import 会把它绑成本作用域局部变量，workers=1 分支里 _one() 报
        # NameError: cannot access free variable 'ThreadPoolExecutor'。
        from concurrent.futures import as_completed

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(_one, p): p for p in targets}
            for i, fu in enumerate(as_completed(futs), 1):
                p = futs[fu]
                r = fu.result()
                stats[r.get("status", "?")] = stats.get(r.get("status", "?"), 0) + 1
                results.append(r)
                if not args.json:
                    mark = {"ok": "✓", "ok-need-review": "⚠",
                            "dry-run-ok": "·"}.get(r.get("status"), "✗")
                    rs = (" | " + "; ".join(r.get("reasons") or [])) if r.get("reasons") else ""
                    print(f"[{i}/{len(targets)}] {mark} "
                          f"{os.path.basename(p)[:46]} {r.get('chars')}字 "
                          f"[{r.get('subject')}]{_kp_brief(r)}{rs}", flush=True)
    else:
        db = SessionLocal()
        for i, p in enumerate(targets, 1):
            r = _one(p)
            stats[r.get("status", "?")] = stats.get(r.get("status", "?"), 0) + 1
            results.append(r)
            if not args.json:
                mark = {"ok": "✓", "ok-need-review": "⚠",
                        "dry-run-ok": "·"}.get(r.get("status"), "✗")
                extra = f" [{r.get('subject')}] {r.get('book_name') or ''} " \
                        f"{r.get('chapter') or ''} {r.get('content_type') or ''}"
                rs = (" | " + "; ".join(r.get("reasons") or [])) if r.get("reasons") else ""
                print(f"[{i}/{len(targets)}] {mark} {os.path.basename(p)[:50]} "
                      f"{r.get('chars')}字{extra}{_kp_brief(r)}{rs}")
        db.close()

    el = time.time() - t0
    print(f"\n=== 完成 {len(targets)} 篇，{el:.0f}s（{el / max(len(targets), 1):.1f}s/篇，"
          f"workers={args.workers}）===")
    print("状态分布:", stats)
    # 知识点抽取可观测汇总
    kp_kept = sum((r.get("knowledge_points") or {}).get("kept", 0) for r in results)
    kp_drop = sum((r.get("knowledge_points") or {}).get("dropped", 0) for r in results)
    kp_fail = sum((r.get("knowledge_points") or {}).get("failed", 0) for r in results)
    kp_skip = sum(1 for r in results
                  if (r.get("knowledge_points") or {}).get("skipped"))
    if kp_kept or kp_drop or kp_fail or kp_skip:
        print(f"知识点抽取: 入库 {kp_kept} · 门禁丢弃 {kp_drop} · 失败 {kp_fail}"
              f" · 跳过 {kp_skip} 篇")
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
