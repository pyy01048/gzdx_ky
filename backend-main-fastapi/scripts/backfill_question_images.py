# -*- coding: utf-8 -*-
"""题目 → 原页配图 回填（PG，幂等）。

### 背景（2026-10-20 实测）
- `quiz_questions` 386 道，`images` 全空、`origin_document_id`/`source_page` 全 NULL
- `knowledge_chunks` 中 2,367 条有 `page_start`（由 OCR 页码标记回填），且全部能
  join 到 `documents.file_path` 指向的真实 PDF

### ⚠️ 为什么不复用 chunk_vectors
实测 `chunk_vectors.embedding_f32` 虽然 `engine='bge'`、`dim=512`，但**向量不是
bge 产物**：全部分量非负、未做 L2 归一化（norm≈7.2），与真 bge 对同一段文本的
余弦仅 **0.078**（等价于随机正交）。它其实是离线哈希向量。直接拿它检索，386 道
题的相似度全部 < 0.30 —— 会产出 0 匹配。

因此本脚本**只读** `knowledge_chunks.text`，在内存里用
`services.embedding_service.generate_local_embeddings()`（BAAI/bge-small-zh-v1.5）
对「有页码的 2,367 条 chunk」现算向量；**不写 chunk_vectors**（不在本任务领地，
且重建需全库 20,676 条）。

### 链路
1. 题干（剥掉「[某某大学2011年研]」这类来源尾巴）算 embedding
2. 与 2,367 条带页码 chunk 的 bge 向量做矩阵余弦（386×2367，毫秒级）
3. 优先同科目：同科目余弦 ≥ `--threshold`（默认 0.55）即命中；
   跨科目必须 ≥ `--cross-threshold`（默认 0.75）
4. 用 pypdfium2 渲染该页（scale 1.5 ≈ 108dpi），存
   `data/storage/images/question_pages/{qid}_p{page:04d}.png`（幂等：已存在且非空即跳过）
5. 回填 `origin_document_id` / `source_page` / `images` / `figure_missing`

题干含图关键词但没拿到图 → `figure_missing=1`（前端必须提示，不能静默）。

用法：
    python scripts/backfill_question_images.py --dry-run
    python scripts/backfill_question_images.py --dry-run --threshold 0.55
    python scripts/backfill_question_images.py --apply --limit 200
    python scripts/backfill_question_images.py --apply --limit 200 --only-subject 模拟电子技术
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402

#: 图片根目录（与 data/storage/images 约定一致；库内只存相对路径）
IMG_ROOT = BASE / "data" / "storage" / "images"
OUT_SUBDIR = "question_pages"
#: 单张 PNG 上限 300KB
MAX_BYTES = 300 * 1024
#: 依次尝试的渲染倍率（1.5 ≈ 108dpi），逐步降档以压体积
SCALES = (1.5, 1.2, 1.0)
#: 每道题取前 N 个候选
TOPK = 10

#: 题目来源尾巴，形如「[北京科技大学2011年研]」——学校/年份对匹配教材页是噪声
RE_EXAM_TAG = re.compile(r"\[[^\[\]]{0,40}?(?:年)?研\]")
#: 分块里的 OCR 物理页标记
RE_PAGE_MARK = re.compile(r"-{2,}\s*第\s*\d{1,4}\s*页\s*\(OCR\)\s*-{2,}")
#: 题干依赖图的信号词
RE_FIG = re.compile(
    r"(如图|下图|上图|图所示|图示|见图|图中|电路图|波形|框图|原理图|流程图"
    r"|图\s*\d+\s*[-－—]\s*\d+)"
)
#: 目录页特征：目录行 = 「章节名 + 点线引导符 + 页码」
RE_TOC_LINE = re.compile(r"(?:[.·…．]\s*){2,}[（(]?\s*\d{1,4}\s*[)）]?\s*$")
#: 目录行另一种写法：「章节名（页码）」
RE_TOC_LINE2 = re.compile(r"[（(]\s*\d{1,4}\s*[)）]\s*$")
RE_NUM_LINE = re.compile(r"^[A-Za-z]?[\d.．]{2,}$")


def is_toc_like(text: str) -> bool:
    """判断分块是否来自目录/版权页。

    这些页语义上和题目高度接近（章节名 vs 题干关键词），但渲染出来只有一行行
    页码索引，对"看原页配图"毫无价值 —— 实测 q369 就被匹配到高数下册目录页。

    只按**行结构**判定，不用「出现 3 个省略号」这类宽松规则：数学推导里的
    ``...`` 会被误杀（实测 961/6087/6100 等真题解析页）。
    """
    t = text or ""
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if len(lines) < 5:
        return False
    if "目录" in t:
        return True
    if sum(1 for ln in lines if RE_TOC_LINE.search(ln)) >= 3:
        return True
    end_pn = sum(1 for ln in lines if RE_TOC_LINE2.search(ln))
    if end_pn >= 5 and end_pn / len(lines) >= 0.4:
        return True
    num_only = sum(1 for ln in lines if RE_NUM_LINE.match(ln))
    if len(lines) >= 6 and num_only / len(lines) >= 0.35:
        return True
    if any(k in t for k in ("ISBN", "版权所有", "印刷有限公司", "图书在版编目")):
        return True
    return False

HIST_EDGES = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90, 1.01]
HIST_LABELS = [f"{lo:.2f}-{hi:.2f}" for lo, hi in zip(HIST_EDGES, HIST_EDGES[1:])]


def log(msg: str = "") -> None:
    print(msg, flush=True)


def norm_subject(s: str | None) -> str:
    return (s or "").strip()


def clean_query_text(content: str) -> str:
    """题干清洗：去来源尾巴、去多余空白。答案/选项本来就不在 content 里。"""
    t = RE_EXAM_TAG.sub(" ", content or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:600]


def clean_chunk_text(text: str) -> str:
    t = RE_PAGE_MARK.sub(" ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:500]


def bucket(v: float) -> str:
    for lo, hi, label in zip(HIST_EDGES, HIST_EDGES[1:], HIST_LABELS):
        if lo <= v < hi:
            return label
    return "<0.20"


def fetch_questions(cur, only_subject: str | None) -> list[tuple]:
    sql = """
        SELECT id, content, subject
        FROM quiz_questions
        WHERE origin_document_id IS NULL
          AND content IS NOT NULL AND btrim(content) <> ''
    """
    params: list[Any] = []
    if only_subject:
        sql += " AND subject = %s"
        params.append(only_subject)
    sql += " ORDER BY id"
    cur.execute(sql, params)
    return cur.fetchall()


def fetch_page_chunks(cur) -> list[tuple]:
    """所有可渲染（有 page_start）的分块。"""
    cur.execute(
        """
        SELECT kc.id, kc.document_id, kc.subject, kc.page_start, kc.doc_name, kc.text
        FROM knowledge_chunks kc
        WHERE kc.page_start IS NOT NULL
          AND kc.text IS NOT NULL AND btrim(kc.text) <> ''
        ORDER BY kc.id
        """
    )
    rows = cur.fetchall()
    kept = [r for r in rows if not is_toc_like(r[5])]
    dropped = len(rows) - len(kept)
    if dropped:
        log(f"  过滤目录/版权页分块：{dropped} 条（保留 {len(kept)}）")
    return kept


def embed_all(texts: list[str]) -> np.ndarray:
    """批量 bge embedding，返回 L2 归一化矩阵（float32）。"""
    from services.embedding_service import generate_local_embeddings

    out: list[np.ndarray] = []
    BATCH = 32
    t0 = time.time()
    for i in range(0, len(texts), BATCH):
        out.extend(generate_local_embeddings(texts[i:i + BATCH]))
        if (i // BATCH) % 10 == 9 or i + BATCH >= len(texts):
            log(f"    {min(i + BATCH, len(texts))}/{len(texts)}  {time.time() - t0:.0f}s")
    mat = np.vstack([np.asarray(v, dtype=np.float32) for v in out])
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def load_documents(cur, doc_ids: set[int]) -> dict[int, dict]:
    if not doc_ids:
        return {}
    cur.execute(
        "SELECT id, file_path, file_name, subject FROM documents WHERE id = ANY(%s)",
        (list(doc_ids),),
    )
    out = {}
    for did, fp, fn, subj in cur.fetchall():
        out[did] = {"file_path": fp, "file_name": fn, "subject": subj,
                    "exists": bool(fp) and os.path.exists(fp)}
    return out


def probe_pdf_pages(path: str) -> int | None:
    """只开不渲染，取页数用于 dry-run 预估。"""
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(path)
        try:
            return len(pdf)
        finally:
            pdf.close()
    except Exception:
        return None


def render_page_to_png(pdf, page_no: int, dest: Path) -> tuple[int, float, float]:
    """渲染 1-based 页到 PNG，压到 300KB 内。返回 (字节数, scale, 灰度标准差)。"""
    from PIL import ImageStat

    page = pdf[page_no - 1]
    size = 0
    used_scale = SCALES[0]
    stddev = -1.0
    img = None
    for scale in SCALES:
        used_scale = scale
        bmp = page.render(scale=scale)
        try:
            img = bmp.to_pil()
            img.save(dest, format="PNG", optimize=True)
            size = dest.stat().st_size
            if size <= MAX_BYTES:
                break
            img = img.convert("L")
            img.save(dest, format="PNG", optimize=True)
            size = dest.stat().st_size
            if size <= MAX_BYTES:
                break
        finally:
            bmp.close()
    if img is not None:
        try:
            stddev = float(ImageStat.Stat(img.convert("L")).stddev[0])
        except Exception:
            stddev = -1.0
    return size, used_scale, stddev


def main() -> int:
    ap = argparse.ArgumentParser(description="题目→原页配图 回填")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写库不渲染")
    ap.add_argument("--apply", action="store_true", help="备份后渲染并写库")
    ap.add_argument("--threshold", type=float, default=0.65, help="同科目余弦阈值")
    ap.add_argument("--cross-threshold", type=float, default=0.80, help="跨科目余弦阈值")
    ap.add_argument("--limit", type=int, default=200, help="本次最多生成图片张数")
    ap.add_argument("--only-subject", default=None, help="只处理某科目")
    ap.add_argument("--sample", type=int, default=20, help="dry-run 打印样例条数")
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        ap.error("必须指定 --dry-run 或 --apply")

    t0 = time.time()
    dsn = pg_database_url()
    OUT_DIR = IMG_ROOT / OUT_SUBDIR
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(dsn, autocommit=False) as pg, pg.cursor() as cur:
        questions = fetch_questions(cur, args.only_subject)
        log(f"待处理题目（origin_document_id IS NULL）：{len(questions)} 道")
        if not questions:
            log("没有待处理题目，退出。")
            return 0

        chunks = fetch_page_chunks(cur)
        log(f"带页码的可渲染分块：{len(chunks)} 条（现算 bge 向量，不复用 chunk_vectors）")
        log("计算分块 embedding…")
        chunk_texts = [clean_chunk_text(c[5]) for c in chunks]
        cmat = embed_all(chunk_texts)

        log("计算题干 embedding…")
        qtexts = [clean_query_text(q[1]) for q in questions]
        qmat = embed_all(qtexts)
        log(f"向量就绪，用时 {time.time() - t0:.1f}s")

        chunk_subject = np.array([norm_subject(c[2]) for c in chunks])

        # ---- 匹配 ----
        plans: list[dict] = []
        best_sims: list[float] = []
        hist = Counter()
        hint_cnt = 0
        for qi, (q, text) in enumerate(zip(questions, qtexts)):
            qid, content, subject = q[0], q[1], q[2]
            has_hint = bool(RE_FIG.search(content or ""))
            hint_cnt += int(has_hint)

            sims = cmat @ qmat[qi]
            same_mask = chunk_subject == norm_subject(subject)
            same_sims = sims[same_mask]
            best_same = float(same_sims.max()) if same_sims.size else 0.0
            best_sims.append(best_same)
            hist[bucket(best_same)] += 1

            chosen = None
            if same_sims.size and best_same >= args.threshold:
                idx = int(np.flatnonzero(same_mask)[int(np.argmax(same_sims))])
                chosen = (idx, best_same)
            else:
                top_i = int(np.argmax(sims))
                if float(sims[top_i]) >= args.cross_threshold:
                    chosen = (top_i, float(sims[top_i]))
            if chosen:
                idx, sim = chosen
                c = chunks[idx]
                plans.append({
                    "qid": qid, "chunk_id": c[0], "document_id": c[1],
                    "subject": norm_subject(subject), "chunk_subject": norm_subject(c[2]),
                    "page": int(c[3]), "doc_name": c[4], "chunk_text": c[5] or "",
                    "sim": sim, "cross": norm_subject(c[2]) != norm_subject(subject),
                    "has_hint": has_hint, "text_preview": text[:60],
                })

        log("")
        log("=== 同科目最佳相似度分布（bge）===")
        total = len(questions)
        for label in HIST_LABELS + ["<0.20"]:
            n = hist.get(label, 0)
            if n:
                log(f"  {label:>9}  {n:>4}  {n / total:6.1%}  {'#' * min(60, n)}")

        log("")
        log("=== 阈值敏感性（同科目）===")
        for th in (0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
            n = sum(1 for s in best_sims if s >= th)
            log(f"  ≥{th:.2f}  {n:>4} 道  {n / total:6.1%}")

        docs = load_documents(cur, {p["document_id"] for p in plans})
        page_cache: dict[int, int | None] = {}
        renderable: list[dict] = []
        for p in plans:
            d = docs.get(p["document_id"]) or {}
            ok = bool(d.get("exists"))
            if ok and not str(d.get("file_path", "")).lower().endswith(".pdf"):
                ok = False
            if ok:
                if p["document_id"] not in page_cache:
                    page_cache[p["document_id"]] = probe_pdf_pages(d["file_path"])
                n_pages = page_cache[p["document_id"]]
                ok = bool(n_pages) and 1 <= p["page"] <= n_pages
            p["renderable"] = ok
            p["doc_name"] = d.get("file_name") or p.get("doc_name")
            p["file_path"] = d.get("file_path")
            if ok:
                renderable.append(p)

        log("")
        log(f"命中 chunk（阈值 {args.threshold} / 跨科目 {args.cross_threshold}）："
            f"{len(plans)}/{total}（{len(plans) / total:.1%}）")
        log(f"  其中跨科目：{sum(1 for p in plans if p['cross'])}")
        log(f"  文档存在且页码在范围内、可渲染：{len(renderable)}")
        log(f"  预计本次生成（limit={args.limit}）：{min(len(renderable), args.limit)} 张")
        log(f"  题干含图关键词：{hint_cnt} 道；其中已命中可出图："
            f"{sum(1 for p in plans if p['has_hint'] and p['renderable'])}")

        log("")
        log(f"=== 前 {min(args.sample, len(plans))} 条样例（题 id → doc / 页 / 相似度）===")
        for p in plans[: args.sample]:
            flag = "跨" if p["cross"] else "同"
            log(f"  q{p['qid']:<5} {p['sim']:.3f} [{flag}] {p['subject']} ← "
                f"{(p['doc_name'] or '')[:30]} p{p['page']} "
                f"| 题:{p['text_preview'][:24]} | 块:{clean_chunk_text(p['chunk_text'])[:34]}")

        if args.dry_run:
            log("")
            log("[DRY-RUN] 未写库、未渲染。确认阈值后加 --apply 执行。")
            return 0

        # ---- 备份（写库前必须成功）----
        from services.backup_service import create_backup

        log("")
        log("创建数据库备份…")
        backup_path = create_backup()
        log(f"备份完成：{backup_path}")

        # ---- 渲染 ----
        # 选片：按科目轮转，科目内按相似度降序 —— 保证 4 个科目都有覆盖，
        # 同时优先拿相似度最高（最可信）的页，而不是被 id 顺序锁死在模电上。
        by_subj: dict[str, list[dict]] = defaultdict(list)
        for p in renderable:
            by_subj[p["subject"]].append(p)
        for lst in by_subj.values():
            lst.sort(key=lambda x: x["sim"], reverse=True)
        sel: list[dict] = []
        cap = args.limit if args.limit > 0 else len(renderable)
        queues = sorted(by_subj.values(), key=lambda lst: lst[0]["sim"], reverse=True)
        while len(sel) < cap and any(queues):
            for lst in queues:
                if lst and len(sel) < cap:
                    sel.append(lst.pop(0))

        by_doc: dict[int, list[dict]] = defaultdict(list)
        for p in sel:
            by_doc[p["document_id"]].append(p)

        import pypdfium2 as pdfium

        rendered: list[dict] = []
        reused = 0
        failed: list[tuple[int, str]] = []
        total_bytes = 0
        new_count = 0
        blank = 0
        for did, items in by_doc.items():
            path = items[0]["file_path"]
            try:
                pdf = pdfium.PdfDocument(path)
            except Exception as e:  # noqa: BLE001
                for p in items:
                    failed.append((p["qid"], f"打开PDF失败: {e}"))
                log(f"  [PDF] {Path(path).name[:40]} 打开失败: {e}")
                continue
            try:
                n_pages = len(pdf)
                ok_n = 0
                for p in items:
                    qid, page = p["qid"], p["page"]
                    dest = OUT_DIR / f"{qid}_p{page:04d}.png"
                    if dest.exists() and dest.stat().st_size > 1024:
                        reused += 1
                        p.update({"file": f"{OUT_SUBDIR}/{dest.name}",
                                  "bytes": dest.stat().st_size, "scale": 0.0})
                        rendered.append(p)
                        ok_n += 1
                        continue
                    if page > n_pages:
                        failed.append((qid, f"页码 {page} 超出 PDF 页数 {n_pages}"))
                        continue
                    try:
                        size, scale, stddev = render_page_to_png(pdf, page, dest)
                    except Exception as e:  # noqa: BLE001
                        failed.append((qid, f"渲染失败: {e}"))
                        continue
                    if size <= 1024:
                        failed.append((qid, f"产物过小 {size}B"))
                        dest.unlink(missing_ok=True)
                        continue
                    if 0 <= stddev < 1.0:
                        blank += 1
                        log(f"  [WARN] q{qid} p{page} 近乎空白（stddev={stddev:.2f}）")
                    p.update({"file": f"{OUT_SUBDIR}/{dest.name}", "bytes": size,
                              "scale": scale, "stddev": stddev})
                    total_bytes += size
                    new_count += 1
                    rendered.append(p)
                    ok_n += 1
                log(f"  [PDF] {Path(path).name[:40]} → {ok_n}/{len(items)} 张")
            finally:
                pdf.close()

        log("")
        log(f"渲染完成：新增 {new_count} 张，复用 {reused} 张，失败 {len(failed)} 条，"
            f"疑似空白 {blank} 张")
        if new_count:
            log(f"  平均大小：{total_bytes / new_count / 1024:.1f} KB")
        for qid, why in failed[:10]:
            log(f"  [FAIL] q{qid}: {why}")

        # ---- 写库 ----
        upd = [
            (
                p["document_id"], p["page"],
                json.dumps([{
                    "path": p["file"],
                    "page": p["page"],
                    "kind": "page_thumb",
                    "source": "matched_chunk",
                }], ensure_ascii=False),
                0, p["qid"],
            )
            for p in rendered
        ]
        got_img = {p["qid"] for p in rendered}
        miss = [q[0] for q in questions
                if RE_FIG.search(q[1] or "") and q[0] not in got_img]
        with pg.transaction():
            if upd:
                cur.executemany(
                    """UPDATE quiz_questions
                       SET origin_document_id=%s, source_page=%s, images=%s::jsonb,
                           figure_missing=%s, updated_at=now()
                       WHERE id=%s""",
                    upd,
                )
            # 题干要图却没有图 → 明确标缺失（不静默）
            if miss:
                cur.executemany(
                    "UPDATE quiz_questions SET figure_missing=1, updated_at=now() WHERE id=%s",
                    [(qid,) for qid in miss],
                )
            # 出图成功的题，figure_missing 必须是 0（覆写历史误标）
            if got_img:
                cur.execute(
                    "UPDATE quiz_questions SET figure_missing=0 WHERE id = ANY(%s)",
                    (list(got_img),),
                )
        log(f"写库完成：images {len(upd)} 道，figure_missing=1 新增 {len(miss)} 道")

        cur.execute(
            """SELECT count(*) FILTER (WHERE images IS NOT NULL
                                        AND images::text NOT IN ('[]','null','{}')),
                      count(*) FILTER (WHERE origin_document_id IS NOT NULL),
                      count(*) FILTER (WHERE figure_missing=1), count(*)
               FROM quiz_questions"""
        )
        wi, wd, fm, alln = cur.fetchone()
        log(f"[OK] 图片覆盖 {wi}/{alln}｜来源回填 {wd}/{alln}｜figure_missing {fm}")
        log(f"总用时 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
