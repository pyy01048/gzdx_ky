# -*- coding: utf-8 -*-
"""文档152《电子技术基础-模拟部分》康华光 第6版 扫描版 PDF 重新解析（OCR）。

599 页 / 143MB 无文字层扫描版。策略：
  1. 逐页渲染（200dpi 自适应降采样）+ RapidOCR 识别，文本追加到 checkpoint 文件
     （支持断点续跑，中途崩溃不丢进度）。
  2. 全部页完成后，把全文写回 documents.content，并 ingest_text 切块入库。
  3. 回填新块的 token_count（项目算法：汉字1、连续字母数字1）。
  4. 调用 pipeline.build_vectors 为文档152的块补向量（增量）。
"""
from __future__ import annotations

import os
import sys
import time
import tempfile
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DOC_ID = 152
PDF_PATH = r"D:/平台/knowledge_base/模拟电子技术/教材/【电子技术基础-模拟部分】康华光 第6版.pdf"
DOC_NAME = "【电子技术基础-模拟部分】康华光 第6版.pdf"
CKPT_PATH = os.path.join(BASE_DIR, "data", "ocr_152_checkpoint.txt")
LOG_PATH = os.path.join(BASE_DIR, "data", "ocr_152_progress.log")
SUBJECT = "模拟电子技术"

DB_CONFIG = dict(
    host="127.0.0.1", port=5432, user="kaoyan",
    password="kaoyan_dev_2026", dbname="kaoyan",
)

RENDER_DPI = 200
PDF_MAX_SIDE_PX = 4000  # 与 services/smart_ingest 的 PDF_MAX_SIDE_PX 保持一致


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def token_count(text: str) -> int:
    """与 scripts/fill_kb_docs_and_kps.py 保持一致。"""
    n = 0
    word = False
    for ch in text or "":
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:
            n += 1
            word = False
        elif ch.isalnum() or ch in "_-":
            word = True
        else:
            if word:
                n += 1
                word = False
    if word:
        n += 1
    return max(n, 1)


def load_checkpoint() -> tuple[int, list[str]]:
    """返回 (已完成的页数, 已收集的文本列表)。"""
    if not os.path.exists(CKPT_PATH):
        return 0, []
    parts = []
    done = 0
    with open(CKPT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("--- 第") and line.endswith("(OCR) ---"):
                done += 1
            parts.append(line)
    return done, parts


def ocr_pdf_all():
    """逐页 OCR，支持断点续跑。返回最终文本。"""
    # 检查文件存在
    if not os.path.exists(PDF_PATH):
        log(f"[错误] PDF 不存在: {PDF_PATH}")
        return None

    # 加载 checkpoint
    start_page, parts = load_checkpoint()
    log(f"checkpoint 已识别 {start_page} 页，从第 {start_page + 1} 页续跑")

    import pypdfium2 as pdfium
    from services.ocr_service import OCRService, _reserve_project_utils

    _reserve_project_utils()
    ocr = OCRService(device="cpu")

    doc = pdfium.PdfDocument(PDF_PATH)
    n_pages = len(doc)
    log(f"PDF 总页数: {n_pages}")

    if start_page >= n_pages:
        log("checkpoint 已完整，无需再跑 OCR")
        doc.close()
        return "\n".join(parts)

    tmpdir = tempfile.mkdtemp(prefix="ocr152_")
    t0 = time.time()
    try:
        for i in range(start_page, n_pages):
            page = None
            try:
                t1 = time.time()
                page = doc[i]
                # 自适应 scale（与大文件管线一致）
                try:
                    pw, ph = page.get_size()
                except Exception:
                    pw = ph = 0.0
                scale = RENDER_DPI / 72.0
                if pw > 0 and ph > 0:
                    longest_in = max(pw, ph) / 72.0
                    if longest_in * scale > PDF_MAX_SIDE_PX:
                        scale = PDF_MAX_SIDE_PX / longest_in
                if scale <= 0:
                    scale = RENDER_DPI / 72.0

                bitmap = page.render(scale=scale)
                img = bitmap.to_pil()
                img_path = os.path.join(tmpdir, f"p{i:04d}.png")
                img.save(img_path)
                page.close()
                page = None

                text = ocr.recognize(img_path)
                try:
                    os.remove(img_path)
                except OSError:
                    pass

                if text and text.strip():
                    parts.append(f"--- 第{i+1}页(OCR) ---")
                    parts.append(text)
                else:
                    log(f"  第{i+1}页 无文字（{ocr.last_error or '未识别到文字'}）")

                # 立即追加到 checkpoint（每页落盘）
                with open(CKPT_PATH, "a", encoding="utf-8") as f:
                    f.write(f"--- 第{i+1}页(OCR) ---\n")
                    f.write(text + "\n" if text else "\n")

                if (i + 1) % 20 == 0 or i == n_pages - 1:
                    el = time.time() - t0
                    rate = (i + 1 - start_page) / el if el > 0 else 0
                    eta = (n_pages - i - 1) / rate / 60 if rate > 0 else 0
                    log(f"  进度 {i+1}/{n_pages} 页，本次 {i+1-start_page} 页耗时 {el:.0f}s，"
                        f"剩余约 {eta:.1f} 分钟")
            except Exception as e:
                log(f"  第{i+1}页异常: {type(e).__name__}: {e}，跳过")
                with open(CKPT_PATH, "a", encoding="utf-8") as f:
                    f.write(f"--- 第{i+1}页(OCR) ---\n\n")
                if page is not None:
                    try:
                        page.close()
                    except Exception:
                        pass
    finally:
        try:
            doc.close()
        except Exception:
            pass
        shutil.rmtree(tmpdir, ignore_errors=True)

    total_chars = sum(len(p) for p in parts)
    log(f"OCR 全部完成：{n_pages} 页，共 {total_chars} 字，总耗时 {(time.time()-t0)/60:.1f} 分钟")
    return "\n".join(parts)


def write_to_db(text: str):
    """把 OCR 全文写入 documents 并切块入库、回填 token_count、补向量。"""
    import psycopg

    if not text or not text.strip():
        log("[错误] OCR 文本为空，拒绝入库")
        return False

    with psycopg.connect(**DB_CONFIG) as pg, pg.cursor() as cur:
        # 更新 documents
        cur.execute(
            """
            UPDATE documents
            SET content=%s, index_status='indexing', parse_progress=0.5,
                ocr_used=TRUE, chunk_count=0, updated_at=now()
            WHERE id=%s
            """,
            (text, DOC_ID),
        )
        pg.commit()
        log("documents.content 已更新，开始切块入库")

    # 用项目 ORM 路径切块（复用 ingest_text，保证 search_vector 生成列自动填充）
    import orm_aliases
    orm_aliases.install()
    from database import SessionLocal
    from services import kb_service

    db = SessionLocal()
    try:
        from models import Document
        doc = db.query(Document).filter(Document.id == DOC_ID).first()
        if doc is None:
            log("[错误] 数据库找不到文档152")
            return False

        # 文档152当前无块，replace=True 不会触发物理删除闸门
        n = kb_service.ingest_text(
            db, DOC_ID, doc.file_name or DOC_NAME, text,
            subject=SUBJECT, replace=True,
        )
        log(f"切块入库完成，新增 {n} 个分块")

        # 回填 token_count（ORM 不映射该列，用原生 SQL）
        with psycopg.connect(**DB_CONFIG) as pg, pg.cursor() as cur:
            cur.execute(
                "SELECT id, text FROM knowledge_chunks WHERE document_id=%s",
                (DOC_ID,),
            )
            rows = cur.fetchall()
            for cid, ctext in rows:
                cur.execute(
                    "UPDATE knowledge_chunks SET token_count=%s WHERE id=%s",
                    (token_count(ctext), cid),
                )
            pg.commit()
            log(f"已回填 {len(rows)} 个分块的 token_count")

        # 更新文档状态
        has_chunks = kb_service.has_searchable_chunks(db, DOC_ID)
        doc.index_status = "indexed" if has_chunks else "failed"
        doc.parse_progress = 1.0
        doc.chunk_count = n
        db.commit()
        log(f"文档状态更新: index_status={doc.index_status}, chunk_count={n}")
        db.close()

        # 补向量（增量，只处理缺向量的块）
        log("开始为文档152的分块补向量...")
        from pipeline.build_vectors import main as build_vectors_main
        import psycopg as _pg

        # build_vectors 是全库增量，会包含文档152的新块。跑它即可。
        rc = build_vectors_main([])
        log(f"build_vectors 返回码: {rc}")

        # 验证文档152向量覆盖
        with _pg.connect(**DB_CONFIG) as pg2, pg2.cursor() as cur2:
            cur2.execute(
                "SELECT COUNT(*) FROM chunk_vectors WHERE document_id=%s AND embedding_f32 IS NOT NULL",
                (DOC_ID,),
            )
            vec_n = cur2.fetchone()[0]
            log(f"文档152 向量覆盖: {vec_n} 条")
        return rc == 0
    finally:
        try:
            db.close()
        except Exception:
            pass


def main() -> int:
    log("===== 文档152 OCR 重新解析启动 =====")
    text = ocr_pdf_all()
    if text is None:
        return 1
    ok = write_to_db(text)
    log("===== 文档152 OCR 重新解析结束 =====")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
