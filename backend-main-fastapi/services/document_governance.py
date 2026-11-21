# -*- coding: utf-8 -*-
"""C 批次1：文档治理（失败重索引 / 确定性 KP 挂载 / 科目字典+待分类队列 / 摘要清洗）。

设计口径（台账 §10 / 评估报告 #10/#18/#23/#24）：
- **KP 挂载走确定性章节抽取_pass**：零模型依赖、全量覆盖、溯源到 knowledge_chunks、
  可逆（``extract_source='batch'`` 独立幂等：重跑只删 batch 行，不动 model/manual 行）。
  模型级语义精炼为待授权升级项（需可用 OpenAI 兼容端点），不在本批次伪造。
- **失败件**：有正文（>200 字）→ 重建分块转 indexed；无正文且源文件不在 →
  如实登记 parse_error「源文件缺失」，保持 failed，不伪造解析结果。
- **科目**：标准字典 = subject_config（内置种子+用户自定义，前端唯一来源）；
  别名命中 → 回写 subject + subject_source='keyword'；未命中 → 待分类队列
  （document_classify_queue），不再静默落「其他」。
- **摘要**：出参清洗（表格转纯文本、去 | 与 --- 残留），不改原文 content。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from models import Document, DocumentClassifyQueue, KnowledgeChunk, KnowledgePoint, SubjectConfig
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 摘要清洗（出参侧）
# --------------------------------------------------------------------------- #
_SEP_LINE_RE = re.compile(r"^[\s|:\-]+$")


def clean_md_summary(text: Optional[str]) -> str:
    """Markdown 表格 → 纯文本；去分隔行/管道符残留；保序拼接。"""
    if not text:
        return ""
    out: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if "|" in s and _SEP_LINE_RE.match(s):
            continue  # |---|---| 分隔行
        if s.count("|") >= 2:
            cells = [c.strip() for c in s.strip("|").split("|")]
            cells = [c for c in cells if c and not _SEP_LINE_RE.match(c)]
            if cells:
                out.append("、".join(cells))
            continue
        out.append(s.replace("|", " "))
    return " ".join(out).strip()


# --------------------------------------------------------------------------- #
# 失败件重索引
# --------------------------------------------------------------------------- #
SOURCE_MISSING_ERROR = (
    "源文件缺失：原入库路径不在服务器与当前运维机，无法重解析；请重新上传原文后调 POST /api/documents/{id}/reindex 重试"
)


def reindex_failed(db: Session, *, doc_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    """failed 件分流：有正文重建分块转 indexed；无正文登记源缺失。"""
    from services import kb_service

    q = db.query(Document).filter(Document.index_status == "failed")
    if doc_ids:
        q = q.filter(Document.id.in_(doc_ids))
    stats = {"reindexed": 0, "source_missing": 0, "ids_reindexed": [], "ids_missing": []}
    for d in q.all():
        body = (d.content or "").strip()
        if len(body) > 200:
            db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == d.id).delete()
            chunks = kb_service.chunk_text(body)
            for i, c in enumerate(chunks):
                db.add(KnowledgeChunk(document_id=d.id, doc_name=d.file_name, chunk_index=i, text=c, subject=d.subject))
            d.index_status = "indexed"
            d.parse_error = None
            d.parse_progress = 1.0
            d.chunk_count = len(chunks)
            stats["reindexed"] += 1
            stats["ids_reindexed"].append(d.id)
        else:
            d.parse_error = SOURCE_MISSING_ERROR
            stats["source_missing"] += 1
            stats["ids_missing"].append(d.id)
    db.commit()
    return stats


# --------------------------------------------------------------------------- #
# 确定性章节 KP 抽取
# --------------------------------------------------------------------------- #
_MD_HEAD_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百千0-9]+[章单元讲部分篇]\s*(.*)$")
_SECTION_RE = re.compile(r"^第[一二三四五六七八九十百千0-9]+节\s*(.*)$")
_NUM_HEAD_RE = re.compile(r"^\d+(?:\.\d+){1,3}[\.、\s]\s*(\S.{1,60})$")
KP_CAP_PER_DOC = 150


def _clean_heading(raw: str) -> str:
    s = raw.strip().strip("*").strip()
    s = re.sub(r"\s+", " ", s)
    return s[:60]


def extract_heading_kps(db: Session, doc: Document) -> Dict[str, Any]:
    """从正文标题行抽 KP（章节溯源 + 质量门禁 + batch 幂等）。"""
    from services.kp_extract import is_boilerplate, is_noise_name, name_is_generic, normalize_name_key

    body = doc.content or ""
    chunks = (
        db.query(KnowledgeChunk.id, KnowledgeChunk.chunk_index, KnowledgeChunk.text)
        .filter(KnowledgeChunk.document_id == doc.id)
        .all()
    )
    pool = {r.subject for r in db.query(SubjectConfig.subject).all()}
    subject = doc.subject if doc.subject in pool else None

    # batch 幂等：只清本来源旧行
    db.query(KnowledgePoint).filter(
        KnowledgePoint.document_id == doc.id, KnowledgePoint.extract_source == "batch"
    ).delete()

    chapter = ""
    seen: set = set()
    kept = 0
    dropped = 0
    for line in body.splitlines():
        s = line.strip()
        if not s or len(s) > 80:
            continue
        name = ""
        m = _MD_HEAD_RE.match(s)
        if m:
            level, title = len(m.group(1)), _clean_heading(m.group(2))
            if level == 1:
                chapter = title
                continue
            name = title
        else:
            mc = _CHAPTER_RE.match(s)
            if mc:
                chapter = _clean_heading(mc.group(1) or s)
                continue
            ms = _SECTION_RE.match(s)
            mn = _NUM_HEAD_RE.match(s)
            if ms:
                name = _clean_heading(ms.group(1) or s)
            elif mn:
                name = _clean_heading(mn.group(1))
        if not name or not (2 <= len(name) <= 60):
            continue
        key = normalize_name_key(name)
        if key in seen:
            dropped += 1
            continue
        if is_noise_name(name) or name_is_generic(name) or is_boilerplate(name):
            dropped += 1
            continue
        seen.add(key)
        src_id, src_idx = None, None
        for cid, cidx, ctext in chunks:
            if ctext and name in ctext:
                src_id, src_idx = cid, cidx
                break
        db.add(
            KnowledgePoint(
                name=name,
                subject=subject,
                chapter=chapter or None,
                document_id=doc.id,
                source_chunk_id=src_id,
                source_chunk_index=src_idx,
                extract_source="batch",
                subject_source="keyword" if subject else "fallback",
                mastery=0,
                exam_frequency=0,
            )
        )
        kept += 1
        if kept >= KP_CAP_PER_DOC:
            break
    db.flush()
    doc.knowledge_point_count = db.query(KnowledgePoint.id).filter(KnowledgePoint.document_id == doc.id).count()
    return {"doc_id": doc.id, "kept": kept, "dropped": dropped, "kp_count": doc.knowledge_point_count}


# --------------------------------------------------------------------------- #
# 科目字典 + 待分类队列
# --------------------------------------------------------------------------- #
#: 占位科目：字典池里存在但不算"已分类"（评估报告 #24 根因）
SUBJECT_PLACEHOLDERS = {"其他", "其它", "未分类", ""}

#: (关键词正则, 目标科目)；目标不在 subject_config 池内时跳过该条（不造字典外科目）
SUBJECT_ALIASES = [
    (r"线代|线性代数|概率论|高等数学|高数|数学", "数学"),
    (r"英语|单词|阅读理解|翻译|写作", "英语"),
    (r"政治|马原|毛中特|史纲|思修|时政", "政治"),
    (r"信号与系统|信号", "信号与系统"),
    (r"电路", "电路"),
    (r"数电|数字电子|数字逻辑", "数字电子技术"),
    (r"模电|模拟电子", "模拟电子技术"),
    (r"通信原理|通信", "通信原理"),
    (r"数据结构", "数据结构"),
    (r"操作系统", "操作系统"),
    (r"计算机网络|计网", "计算机网络"),
    (r"408", "计算机学科专业基础408"),
    (r"物理", "普通物理"),
    (r"自动控制|自控", "自动控制原理"),
]


def classify_subjects(db: Session) -> Dict[str, Any]:
    """非字典科目 → 别名回写；未命中进待分类队列（不静默落其他）。"""
    pool = {r.subject for r in db.query(SubjectConfig.subject).all()}
    real_pool = pool - SUBJECT_PLACEHOLDERS
    stats = {"reclassified": 0, "queued": 0, "already_ok": 0}
    bad = (
        db.query(Document)
        .filter(
            (Document.subject.is_(None))
            | (Document.subject.in_(SUBJECT_PLACEHOLDERS))
            | (Document.subject.notin_(real_pool))
        )
        .all()
    )
    for d in bad:
        text = f"{d.file_name or ''} {d.folder_path or ''}"
        hit = None
        for kw, target in SUBJECT_ALIASES:
            if target in real_pool and re.search(kw, text):
                hit = target
                break
        if hit:
            d.subject = hit
            d.subject_source = "keyword"
            stats["reclassified"] += 1
            db.query(DocumentClassifyQueue).filter(
                DocumentClassifyQueue.document_id == d.id, DocumentClassifyQueue.status == "pending"
            ).delete()
        else:
            row = db.query(DocumentClassifyQueue).filter(DocumentClassifyQueue.document_id == d.id).first()
            if row is None:
                db.add(
                    DocumentClassifyQueue(
                        document_id=d.id,
                        file_name=d.file_name,
                        suggested_subject=None,
                        reason="目录名/文件名未命中科目字典别名",
                        status="pending",
                    )
                )
                stats["queued"] += 1
    db.commit()
    stats["already_ok"] = db.query(Document.id).filter(Document.subject.in_(real_pool)).count()
    return stats


# --------------------------------------------------------------------------- #
# 批次编排（全量统计验收）
# --------------------------------------------------------------------------- #
def _snapshot(db: Session) -> Dict[str, Any]:
    from sqlalchemy import func

    return {
        "total": db.query(func.count(Document.id)).scalar(),
        "indexed": db.query(func.count(Document.id)).filter(Document.index_status == "indexed").scalar(),
        "failed": db.query(func.count(Document.id)).filter(Document.index_status == "failed").scalar(),
        "kp0_indexed": db.query(func.count(Document.id))
        .filter(Document.index_status == "indexed", Document.knowledge_point_count == 0)
        .scalar(),
        "kp_rows": db.query(func.count(KnowledgePoint.id)).scalar(),
        "kp_batch_rows": db.query(func.count(KnowledgePoint.id))
        .filter(KnowledgePoint.extract_source == "batch")
        .scalar(),
        "subject_other": db.query(func.count(Document.id)).filter(Document.subject == "其他").scalar(),
        "queue_pending": db.query(func.count(DocumentClassifyQueue.id))
        .filter(DocumentClassifyQueue.status == "pending")
        .scalar(),
    }


def run_batch1(db: Session, *, dry_run: bool = False, kp_doc_limit: Optional[int] = None) -> Dict[str, Any]:
    """批次1 全量执行 + 前后全量统计（非抽样验收口径）。"""
    before = _snapshot(db)
    if dry_run:
        return {"dry_run": True, "before": before}
    reindex = reindex_failed(db)
    classify = classify_subjects(db)
    kp_q = (
        db.query(Document)
        .filter(Document.index_status == "indexed", Document.knowledge_point_count == 0)
        .order_by(Document.id)
    )
    if kp_doc_limit:
        kp_q = kp_q.limit(kp_doc_limit)
    kp_docs = kp_q.all()
    kp_kept = 0
    kp_empty = 0
    for d in kp_docs:
        r = extract_heading_kps(db, d)
        kp_kept += r["kept"]
        if r["kept"] == 0:
            kp_empty += 1
    db.commit()
    after = _snapshot(db)
    return {
        "before": before,
        "after": after,
        "reindex": reindex,
        "classify": classify,
        "kp": {"docs_processed": len(kp_docs), "kp_kept": kp_kept, "docs_still_kp0": kp_empty},
    }
