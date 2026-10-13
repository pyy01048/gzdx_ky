# -*- coding: utf-8 -*-
"""本地知识库健康体检与自愈。

### 为什么需要

知识库是"能自己长"的系统：不断有新资料进来、有解析失败的、有扫描件没 OCR 的、
有分块没向量化的。零散的修复脚本解决不了长期问题 ——
需要一个**统一入口**：先如实报告缺口，再按缺口逐项修。

### 它检查什么（都是实测出来的真实缺口）

| 缺口 | 现状 | 后果 |
|------|------|------|
| 状态口径不统一 | `indexed` 1064 篇 + `ready` 481 篇两套词表 | 统计/幂等判断失准 |
| 扫描件正文为空 | 120 篇 | 内容根本没进知识库 |
| 分块缺向量 | 22902 块中 20299 有向量，缺 2603 | 向量召回漏数据 |
| 资料元信息缺失 | doc_type / structure_level 为空 | 前端无法按层级筛选 |

### 用法

    python -m services.kb_pipeline --report      # 只体检（默认）
    python -m services.kb_pipeline --heal        # 体检并修复可自动修的
    python -m services.kb_pipeline --heal --ocr  # 修复时含扫描件 OCR（慢）
"""

from __future__ import annotations

import datetime
import os
from typing import Any, Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Document, KnowledgeChunk
from services.doc_naming import apply_display_name
from services.smart_ingest import gate_for_write
from utils.timeutil import utcnow_aware  # 统一 naive UTC 时间规范（P0-4）

#: index_status 的**唯一合法取值**。
#  历史上出现过 "ready"（旧导入脚本）与 "indexed"（现行）两套词表并存，
#  导致幂等判断和统计口径都对不上 —— 这里统一为下面 4 个。
VALID_STATUS = ("pending", "indexing", "indexed", "failed")

#: 视为"已成功入库"的状态（含历史遗留别名，读取时两者都认）
DONE_STATUS = ("indexed", "ready")

#: 历史别名 → 规范值
STATUS_ALIAS = {"ready": "indexed", "done": "indexed", "ok": "indexed"}


# --------------------------------------------------------------------------- #
# 体检
# --------------------------------------------------------------------------- #
def health_report(db: Session) -> dict[str, Any]:
    """如实报告知识库当前状态与缺口。"""
    total_docs = db.query(func.count(Document.id)).scalar() or 0
    total_chunks = db.query(func.count(KnowledgeChunk.id)).scalar() or 0

    # 状态分布
    by_status = {
        str(s or "null"): c
        for s, c in db.query(Document.index_status, func.count(Document.id))
        .group_by(Document.index_status).all()
    }
    legacy = {k: v for k, v in by_status.items() if k in STATUS_ALIAS}
    unknown = {k: v for k, v in by_status.items()
               if k not in VALID_STATUS and k not in STATUS_ALIAS and k != "null"}

    # 正文为空
    empty_docs = db.query(func.count(Document.id)).filter(
        (Document.content.is_(None)) | (func.length(func.trim(Document.content)) == 0)
    ).scalar() or 0

    # 未向量化的分块（用 NOT EXISTS 避免把整张向量表读进内存）
    try:
        conn = db.connection().connection
        have_vec = conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks_vec"
        ).fetchone()[0]
    except Exception:
        have_vec = None
    missing_embed = max(0, total_chunks - have_vec) if have_vec is not None else None

    # 元信息缺失
    missing_type = db.query(func.count(Document.id)).filter(
        (Document.doc_type.is_(None)) | (Document.doc_type == "")
    ).scalar() or 0
    missing_level = db.query(func.count(Document.id)).filter(
        (Document.structure_level.is_(None)) | (Document.structure_level == "")
    ).scalar() or 0

    ocr_docs = db.query(func.count(Document.id)).filter(Document.ocr_used == True).scalar() or 0  # noqa: E712

    # 目录存在但未入库的文件（可选，目录不存在则跳过）
    unimported = None

    issues: list[dict[str, Any]] = []
    if legacy:
        issues.append({
            "key": "legacy_status",
            "level": "warn",
            "title": f"{sum(legacy.values())} 篇文档用了历史状态值 {list(legacy)}",
            "impact": "幂等判断与统计口径对不上，重复导入可能遗漏",
            "fix": "normalize_status",
            "auto": True,
        })
    if unknown:
        issues.append({
            "key": "unknown_status",
            "level": "warn",
            "title": f"{sum(unknown.values())} 篇文档状态值未知 {list(unknown)}",
            "impact": "这些文档不会被统计为已入库",
            "fix": None,
            "auto": False,
        })
    if empty_docs:
        issues.append({
            "key": "empty_content",
            "level": "error",
            "title": f"{empty_docs} 篇文档正文为空",
            "impact": "内容完全没进知识库，AI 检索不到",
            "fix": "reparse_empty",
            "auto": True,
        })
    if missing_embed:
        issues.append({
            "key": "missing_embedding",
            "level": "warn",
            "title": f"{missing_embed} 个分块没有向量",
            "impact": "向量召回漏掉这些内容（FTS5 仍可检索）",
            "fix": "build_embeddings",
            "auto": False,  # 需要 embedding 服务/API Key，交由显式调用
        })
    if missing_type or missing_level:
        issues.append({
            "key": "missing_meta",
            "level": "info",
            "title": f"元信息缺失：doc_type {missing_type} 篇 / structure_level {missing_level} 篇",
            "impact": "前端无法按资料层级筛选",
            "fix": "backfill_meta",
            "auto": True,
        })

    return {
        # 纯展示字段：带 +00:00 偏移的 ISO8601 对前端更友好，使用 aware 模式
        "checked_at": utcnow_aware().isoformat(),
        "documents": {
            "total": total_docs,
            "by_status": by_status,
            "legacy_status": legacy,
            "unknown_status": unknown,
            "empty_content": empty_docs,
            "ocr_used": ocr_docs,
            "missing_doc_type": missing_type,
            "missing_structure_level": missing_level,
        },
        "chunks": {
            "total": total_chunks,
            "with_embedding": have_vec,
            "missing_embedding": missing_embed,
        },
        "issues": issues,
        "healthy": not any(i["level"] in ("error", "warn") for i in issues),
    }


# --------------------------------------------------------------------------- #
# 自愈
# --------------------------------------------------------------------------- #
def normalize_status(db: Session, *, commit: bool = True) -> int:
    """把历史状态别名统一成规范值（ready → indexed）。"""
    changed = 0
    for alias, canonical in STATUS_ALIAS.items():
        rows = db.query(Document).filter(Document.index_status == alias).all()
        for d in rows:
            d.index_status = canonical
            changed += 1
    if commit and changed:
        db.commit()
    return changed


def backfill_meta(db: Session, *, commit: bool = True, limit: Optional[int] = None) -> dict:
    """补齐 doc_type / structure_level / ocr_used。"""
    from services.kb_service import detect_doc_meta

    q = db.query(Document).filter(
        (Document.doc_type.is_(None)) | (Document.doc_type == "")
        | (Document.structure_level.is_(None)) | (Document.structure_level == "")
    )
    if limit:
        q = q.limit(limit)
    filled = 0
    for doc in q.all():
        try:
            detect_doc_meta(db, doc)
            filled += 1
        except Exception as e:
            print(f"  [!] 文档 {doc.id} 元信息判定失败: {e}")
    if commit:
        db.commit()
    return {"filled": filled}


def _find_storage_roots() -> list[str]:
    """项目内可能存放资料原件的目录。

    ⚠️ 必须包含 ``knowledge_base``：实测 2611 篇里在盘的 1857 篇中，1484 篇
    的原文就在 ``D:\\平台\\knowledge_base`` 下。此前只列 ``data/storage*``，
    导致 ``repair_file_paths`` 对自己最大的资料目录完全视而不见（只能找回零散
    副本）。路径按 ``routers/documents.py`` 同一种算法（realpath + 仅在目录
    存在时追加）算出，不硬编码绝对路径。
    """
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    roots = [
        os.path.join(base, "data", "storage", "documents"),
        os.path.join(base, "data", "storage"),
        os.path.join(base, "data", "uploads"),
    ]
    kb_root = os.path.realpath(os.path.join(base, os.pardir, "knowledge_base"))
    if os.path.isdir(kb_root):
        roots.append(kb_root)
    return roots


def build_file_index() -> dict[str, list[str]]:
    """建立「文件名(小写) → [实际路径]」索引，用于找回源文件。"""
    idx: dict[str, list[str]] = {}
    for root in _find_storage_roots():
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                idx.setdefault(f.lower(), []).append(os.path.join(dirpath, f))
    return idx


def _index_hits(name: str, idx: dict[str, list[str]]) -> list[str]:
    """按文件名在索引里找同名文件，带 ``.pdf`` 去/补后缀回退。

    三处归一：`repair_file_paths` 与只读的 `plan_file_path_repairs` 共用这一份
    匹配逻辑，避免两处各写一遍导致"计划"与"执行"结果不一致。
    """
    key = (name or "").lower()
    hits = idx.get(key) or []
    if not hits and key.endswith(".pdf"):
        hits = idx.get(key[:-4]) or []
    if not hits and not key.endswith(".pdf"):
        hits = idx.get(key + ".pdf") or []
    return hits


def repair_file_paths(
    db: Session,
    *,
    commit: bool = True,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """把失效的 file_path 重新指回项目内的实际文件。

    历史原因：`documents.file_path` 记的是导入时的绝对路径
    （如 `D:\\考研资料数据集V1.0\\xxx.pdf`），后来资料被收进项目
    `data/storage/documents/`，旧路径就全部失效了 —— 于是这些文档
    再也无法重新解析，OCR 也就无从触发。
    """
    broken = [
        d for d in db.query(Document).all()
        if not (d.file_path and os.path.exists(d.file_path))
    ]
    if not broken:
        # 无断链时不建索引（walk knowledge_base 5000+ 文件），保持幂等调用的低成本
        return {"broken": 0, "repaired": 0, "not_found": 0, "indexed_files": 0}
    idx = build_file_index()
    stats = {"broken": len(broken), "repaired": 0, "not_found": 0,
             "indexed_files": sum(len(v) for v in idx.values())}

    for i, doc in enumerate(broken, 1):
        hits = _index_hits(doc.file_name or "", idx)
        if hits:
            doc.file_path = hits[0]
            stats["repaired"] += 1
        else:
            stats["not_found"] += 1
        if progress:
            progress(i, len(broken), doc.file_name or "")

    if commit and stats["repaired"]:
        db.commit()
    return stats


def plan_file_path_repairs(db: Session, *, max_candidates: int = 5) -> dict:
    """**只读**：输出"将要改哪些行的 file_path（old → new）"，不落库。

    口径与 `repair_file_paths` 完全一致（broken = 没登记路径或路径已失效），
    区别只是不写 `doc.file_path`、不 commit。给用户一次"要不要批量修复"的
    知情决策：`recoverable` 为 0 就说明这些文件真的不在盘上，不该给假承诺。
    """
    broken_docs = [
        d for d in db.query(Document).all()
        if not (d.file_path and os.path.exists(d.file_path))
    ]
    # 无断链就不建索引：build_file_index 要 walk 整个 knowledge_base（5000+ 文件），
    # 空库/健康库走这条零成本快路径。
    idx = build_file_index() if broken_docs else {}
    plan: list[dict] = []
    not_found = 0
    for doc in broken_docs:
        hits = _index_hits(doc.file_name or "", idx)
        if hits:
            plan.append({
                "doc_id": doc.id,
                "file_name": doc.file_name,
                "old": doc.file_path,
                "new": hits[0],
                "candidates": hits[:max_candidates],
            })
        else:
            not_found += 1
    return {
        "total_documents": db.query(Document).count(),
        "broken": len(broken_docs),
        "recoverable": len(plan),
        "not_found": not_found,
        "indexed_files": sum(len(v) for v in idx.values()),
        "plan": plan,
    }


def reparse_empty(
    db: Session,
    *,
    use_ocr: bool = True,
    limit: Optional[int] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """重新解析正文为空的文档（扫描件走 OCR）。

    这是把"120 篇扫描件"捞回知识库的唯一途径 ——
    它们当初解析出来是空字符串，直接标 indexed 但没有任何内容。
    """
    from services.document_parser import DocumentParser
    from services.kb_service import detect_doc_meta, has_searchable_chunks, ingest_text

    q = db.query(Document).filter(
        (Document.content.is_(None)) | (func.length(func.trim(Document.content)) == 0)
    )
    if limit:
        q = q.limit(limit)
    docs = q.all()

    stats = {"total": len(docs), "reparsed": 0, "chunks": 0, "rejected": 0,
             "no_file": 0, "empty_again": 0, "failed": 0}

    for i, doc in enumerate(docs, 1):
        path = doc.file_path or ""
        if not path or not os.path.exists(path):
            stats["no_file"] += 1
            if progress:
                progress(i, len(docs), f"{doc.file_name}: 源文件缺失")
            continue

        if progress:
            progress(i, len(docs), doc.file_name)

        try:
            parser = DocumentParser()
            text = parser.parse(path) if use_ocr else parser._extract_pdf_text(path)
        except Exception as e:
            stats["failed"] += 1
            print(f"  [!] {doc.file_name} 解析异常: {e}")
            continue

        if not text or not text.strip():
            stats["empty_again"] += 1
            doc.index_status = "failed"
            db.commit()          # 不 commit 这行 failed 会随下一轮的 rollback 一起丢
            continue

        # 质量闸门：OCR 重新解析出来的"正文"有相当一部分是占位错误提示或乱码，
        # 以前直接覆盖 doc.content 并切块，等于把空文档换成假文档。
        verdict = gate_for_write(db, text, path=path, doc_id=doc.id)
        if not verdict["ok"]:
            stats["rejected"] += 1
            doc.index_status = "failed"
            db.commit()
            print(f"  [x] {doc.file_name} 质量闸门拒绝：{'；'.join(verdict['reasons'])}")
            continue

        doc.content = text
        doc.index_status = "indexing"
        apply_display_name(db, doc, text)
        db.commit()

        try:
            n = ingest_text(db, doc.id, doc.file_name, text,
                            subject=doc.subject, replace=True)
            stats["chunks"] += n
        except Exception as e:
            stats["failed"] += 1
            doc.index_status = "failed"
            db.commit()
            print(f"  [!] {doc.file_name} 分块失败: {e}")
            continue

        try:
            detect_doc_meta(db, doc)
        except Exception:
            pass
        doc.index_status = "indexed" if has_searchable_chunks(db, doc.id) else "failed"
        doc.parse_progress = 1.0
        db.commit()
        stats["reparsed"] += 1

    return stats


def build_embeddings(force: bool = False) -> dict:
    """为缺向量的分块补向量（委托给 embedding_service）。"""
    from services import embedding_service

    fn = getattr(embedding_service, "build_all_embeddings", None)
    if fn is None:
        return {"ok": False, "message": "embedding_service 未提供 build_all_embeddings"}
    try:
        result = fn(force=force)
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------------------- #
# 一键入口
# --------------------------------------------------------------------------- #
def heal(
    db: Session,
    *,
    use_ocr: bool = True,
    do_embeddings: bool = False,
    limit: Optional[int] = None,
    progress: Optional[Callable[[str, dict], None]] = None,
) -> dict:
    """按体检结果自动修复能修的项，返回修复前后对比。"""
    before = health_report(db)
    actions: dict[str, Any] = {}

    def note(name: str, payload: Any):
        actions[name] = payload
        if progress:
            progress(name, payload if isinstance(payload, dict) else {"value": payload})

    # 1. 状态口径
    n = normalize_status(db)
    if n:
        note("normalize_status", {"changed": n})

    # 2. 元信息
    meta = backfill_meta(db, limit=limit)
    if meta.get("filled"):
        note("backfill_meta", meta)

    # 3. 找回失效的源文件路径（120 篇扫描件就靠这一步才能重新解析）
    repair = repair_file_paths(db)
    if repair["repaired"]:
        note("repair_file_paths", repair)

    # 4. 空正文重解析（含 OCR）
    empty = db.query(func.count(Document.id)).filter(
        (Document.content.is_(None)) | (func.length(func.trim(Document.content)) == 0)
    ).scalar() or 0
    if empty:
        note("reparse_empty", reparse_empty(db, use_ocr=use_ocr, limit=limit))

    # 5. 向量（需显式开启，依赖外部 embedding 服务）
    if do_embeddings:
        note("build_embeddings", build_embeddings())

    after = health_report(db)
    return {
        "before": before,
        "actions": actions,
        "after": after,
        "improved": (after["chunks"]["total"] - before["chunks"]["total"]),
    }


def print_report(rep: dict) -> None:
    d, c = rep["documents"], rep["chunks"]
    print("=" * 70)
    print("本地知识库体检")
    print("=" * 70)
    print(f"  文档总数      {d['total']}")
    print(f"    状态分布    {d['by_status']}")
    if d["legacy_status"]:
        print(f"    ⚠️ 历史状态  {d['legacy_status']}")
    if d["unknown_status"]:
        print(f"    ⚠️ 未知状态  {d['unknown_status']}")
    print(f"    正文为空    {d['empty_content']}")
    print(f"    扫描件 OCR  {d['ocr_used']}")
    print(f"    缺 doc_type {d['missing_doc_type']}")
    print(f"    缺层级标记  {d['missing_structure_level']}")
    print(f"  知识分块      {c['total']}")
    print(f"    已向量化    {c['with_embedding']}")
    print(f"    缺向量      {c['missing_embedding']}")
    print()
    if rep["issues"]:
        print("  发现缺口：")
        for i in rep["issues"]:
            mark = {"error": "🔴", "warn": "🟠", "info": "🔵"}.get(i["level"], "·")
            auto = "（可自动修复）" if i["auto"] else "（需手动/显式触发）"
            print(f"    {mark} {i['title']} {auto}")
            print(f"       影响：{i['impact']}")
    else:
        print("  ✅ 未发现缺口")
    print("=" * 70)


def main() -> int:
    import argparse
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="本地知识库体检与自愈")
    ap.add_argument("--heal", action="store_true", help="执行修复（默认只体检）")
    ap.add_argument("--ocr", action="store_true", default=True,
                    help="修复空正文时启用 OCR（默认开）")
    ap.add_argument("--no-ocr", dest="ocr", action="store_false")
    ap.add_argument("--embeddings", action="store_true", help="同时补向量（需 embedding 服务）")
    ap.add_argument("--limit", type=int, default=None, help="限制处理数量")
    args = ap.parse_args()

    from database import SessionLocal

    db = SessionLocal()
    try:
        if not args.heal:
            print_report(health_report(db))
            return 0

        print_report(health_report(db))
        print("\n开始修复…\n")

        def on_progress(name, payload):
            print(f"  [✓] {name}: {payload}")

        def on_item(i, total, label):
            print(f"      ({i}/{total}) {label}")

        result = heal(db, use_ocr=args.ocr, do_embeddings=args.embeddings,
                      limit=args.limit, progress=on_progress)
        print(f"\n修复后：")
        print_report(result["after"])
        print(f"\n新增分块：{result['improved']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
