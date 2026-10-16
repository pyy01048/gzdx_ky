# -*- coding: utf-8 -*-
"""知识库文档 → 题库：识别预览 + 受控入库（V8 阶段3）。

背景
----
``quiz_questions`` 存量全部来源=「真题:xxx」，而 ``documents`` 表有 1800+ 篇
知识库文档里其实躺着大量可识别的题目（真题卷、带解析的练习），一直没被结构化。

本路由把纯本地识别引擎 ``services/qbank_builder.py`` 包成**人机协同**的入库闭环：

  1. ``POST /api/kb-import/scan``（只读，绝不写库）
     对每篇文档用 ``extract_questions`` 抽取候选题，做字段映射 + 去重标注，
     返回预览。前端据此渲染勾选界面。

  2. ``POST /api/kb-import/confirm``（唯一写入口）
     只插入用户勾选确认的候选题，source 写入 ``知识库:<文档标题>``。
     再次查重（哈希防并发），幂等。

硬红线
------
* scan 接口**绝不写库**；真正写库只能走 confirm，且由人在预览界面勾选触发。
* 不做任何批量静默入库。

索引契约（scan/confirm 对齐 + 幂等的关键）
------------------------------------------
``index`` 是**单篇文档内"文档内去重后候选列表"的下标**，该列表**只依赖文档自身
正文、不依赖当前题库内容**——因此：
  * scan 与 confirm 对同一文档重算得到的 index 必然一致；
  * 即使两次 confirm 之间题库已变化（已插入过），index 也不漂移。
对存量题库的去重只做两件事：
  * scan 里给候选打 ``already_exists`` 标记、计入 ``dup_skipped``（前端置灰）；
  * confirm 入库前再查一次哈希，已存在则 ``skipped_existing`` 跳过。
"""

from __future__ import annotations

import time
from difflib import SequenceMatcher
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Document, QuizQuestion
from services import qbank_builder as qb
from services import taxonomy
from services.quiz_content_gate import admit as gate_admit
from services.quiz_content_gate import build_stem_answer_index, gate_log_summary

router = APIRouter(prefix="/api/kb-import", tags=["kb-import"])

#: 单篇文档返回的候选数上限（防超大响应）。超出后打 truncated=true。
MAX_CANDIDATES_PER_DOC = 200
#: 相似度去重阈值（与 qbank_builder.is_duplicate 一致）
SIMILARITY_THRESHOLD = 0.86


# --------------------------------------------------------------------------- #
# 请求体模型
# --------------------------------------------------------------------------- #
class ScanRequest(BaseModel):
    """POST /scan 入参。doc_ids 缺省=全部文档。"""

    doc_ids: Optional[list[int]] = None


class SelectedItem(BaseModel):
    doc_id: int
    index: int


class ConfirmRequest(BaseModel):
    """POST /confirm 入参（二选一）。

    形式 A（推荐，前端勾选后回传）::

        {"selected": [{"doc_id": 3, "index": 0}, {"doc_id": 3, "index": 2}]}

    形式 B（按 doc_ids 对齐下标数组）::

        {"doc_ids": [3, 4], "candidate_indexes": [[0, 2], [1]]}
    """

    selected: Optional[list[SelectedItem]] = None
    doc_ids: Optional[list[int]] = None
    candidate_indexes: Optional[list[list[int]]] = None


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _load_docs(db: Session, doc_ids: Optional[list[int]]) -> list[Document]:
    """按 doc_ids 取文档；缺省取全部。任一 doc_id 不存在 → 404。"""
    q = db.query(Document)
    if doc_ids is not None:
        if not doc_ids:
            return []
        rows = q.filter(Document.id.in_(doc_ids)).all()
        found = {d.id for d in rows}
        missing = [i for i in doc_ids if i not in found]
        if missing:
            # /api 下 404 会被全局 SPA 处理器改写为 {detail:"Not Found", path:...}，
            # 这是项目既有行为（见 main.py spa_fallback_handler），测试据此断言。
            raise HTTPException(status_code=404, detail=f"文档不存在: {missing}")
        # 保持入参顺序
        rows.sort(key=lambda d: doc_ids.index(d.id))
        return rows
    return q.order_by(Document.id.asc()).all()


def _build_existing_index(db: Session):
    """建立存量题目去重索引。

    QuizQuestion 表无 content_hash 列，因此现场计算：
      - hashes: 现有题干 content_hash 集合（O(1) 精确判重）
      - by_len / lengths: 归一化文本按长度分桶，供相似度复核时只与
        "长度相近"的存量题比对（长度差太大必不相似，直接跳过），
        把 O(候选×1871) 的 SequenceMatcher 降到 O(候选×少量近长题)。
    返回 (hashes, by_len, lengths_sorted)。
    """
    rows = db.query(QuizQuestion.content).all()
    hashes: set[str] = set()
    by_len: dict[int, list[str]] = {}
    for (content,) in rows:
        if not content:
            continue
        h = qb.content_hash(content)
        hashes.add(h)
        n = qb.normalize_text(content)
        by_len.setdefault(len(n), []).append(n)
    return hashes, by_len, sorted(by_len)


def _is_bank_dup(
    content: str,
    existing_hashes: set[str],
    existing_by_len: dict[int, list[str]],
    existing_lengths: list[int],
) -> bool:
    """该题干是否已存在于题库：content_hash 精确命中 或 与近长存量题干高度相似(>=0.86)。"""
    h = qb.content_hash(content)
    if h in existing_hashes:
        return True
    cnorm = qb.normalize_text(content)
    clen = len(cnorm)
    if clen == 0:
        return True
    lo = int(clen * 0.6)
    hi = int(clen / 0.6) + 1
    for L in existing_lengths:
        if L < lo:
            continue
        if L > hi:
            break  # lengths 升序，超出上界即可停
        for enorm in existing_by_len[L]:
            if SequenceMatcher(None, cnorm, enorm).ratio() >= SIMILARITY_THRESHOLD:
                return True
    return False


def _build_stem_index(db: Session):
    """构造"归一化题干 → 已见答案集合"索引，用于入库前的同题干答案冲突检测。

    只收 ``is_junk`` 不为 1 的题（隔离题不应参与冲突判定，否则被隔离的
    错误答案会把正确的新题也拦下来），且只收答案非空的行。
    """
    rows = (
        db.query(QuizQuestion.content, QuizQuestion.answer)
        .filter(QuizQuestion.is_junk.isnot(True))
        .all()
    )
    return build_stem_answer_index(rows)


def _classify_candidate(raw: dict[str, Any], doc: Document) -> dict[str, Any]:
    """把 extract_questions 的原始一条 + 文档上下文，映射成落库字段。"""
    content = (raw.get("content") or "").strip()
    classified = qb.classify_question(
        content,
        subject_hint=doc.subject,
        section_type=raw.get("section_type"),
    )
    return {
        "content": content,
        "options": raw.get("options") or [],
        "answer": raw.get("answer"),
        "analysis": raw.get("analysis"),
        "subject": classified["subject"],
        "chapter": classified["chapter"],
        "knowledge_point": classified["knowledge_point"],
        "question_type": classified["question_type"],
        "difficulty": classified["difficulty"],
        # 保留原始大题区题型：入库闸门对判断/简答等"陈述式"题目需要它
        "section_type": raw.get("section_type") or "",
        "content_hash": qb.content_hash(content),
    }


def _list_doc_candidates(
    doc: Document,
    existing_hashes: set[str],
    existing_by_len: dict[int, list[str]],
    existing_lengths: list[int],
) -> tuple[list[dict[str, Any]], int, bool]:
    """列出单篇文档的候选题（scan/confirm 共用，保证 index 对齐 + 幂等）。

    index 基于**文档内去重**后的列表，不依赖题库内容（见模块 docstring）。
    对题库的去重仅体现在 ``already_exists`` 标记与 ``already_count`` 上。

    返回 (候选列表[带 index/already_exists], 已存在数, 是否因单篇上限截断)。
    """
    raws = qb.extract_questions(doc.content or "", source_hint=doc.file_name or "")
    out: list[dict[str, Any]] = []
    local_seen: set[str] = set()  # 文档内重复题干
    already_count = 0
    truncated = False
    for raw in raws:
        cand = _classify_candidate(raw, doc)
        h = cand["content_hash"]
        if h in local_seen:
            continue  # 同一文档内重复题干，不另立候选
        local_seen.add(h)
        exists = _is_bank_dup(cand["content"], existing_hashes, existing_by_len, existing_lengths)
        cand["already_exists"] = exists
        if exists:
            already_count += 1
        cand["index"] = len(out)  # index 与题库无关，稳定
        out.append(cand)
        if len(out) >= MAX_CANDIDATES_PER_DOC:
            truncated = True
            break
    return out, already_count, truncated


# --------------------------------------------------------------------------- #
# POST /scan（只读）
# --------------------------------------------------------------------------- #
@router.post("/scan")
async def scan(payload: ScanRequest, db: Session = Depends(get_db)):
    """扫描知识库文档，识别候选题（**只读，绝不写库**）。

    body: ``{"doc_ids": [int, ...]}``（缺省=全部文档，支持分批传 doc_ids）。
    """
    t0 = time.perf_counter()
    # 确保科目字典缓存就绪（自定义科目归一）
    try:
        taxonomy.ensure_subject_config_seeds(db)
    except Exception:  # noqa: BLE001
        pass
    taxonomy.load_configured_subjects(db)

    docs = _load_docs(db, payload.doc_ids)
    total_docs = db.query(Document).count()

    existing_hashes, existing_by_len, existing_lengths = _build_existing_index(db)

    items: list[dict[str, Any]] = []
    total_candidates = 0
    total_dup = 0
    for doc in docs:
        cands, already_count, truncated = _list_doc_candidates(
            doc, existing_hashes, existing_by_len, existing_lengths
        )
        total_candidates += len(cands)
        total_dup += already_count
        items.append({
            "doc_id": doc.id,
            "doc_title": doc.file_name,
            "subject": doc.subject,
            "candidate_count": len(cands),
            "already_exists": already_count,
            "truncated": truncated,
            "candidates": cands,
        })

    elapsed = round(time.perf_counter() - t0, 3)
    return {
        "total_docs": total_docs,
        "scanned_docs": len(docs),
        "total_candidates": total_candidates,
        "dup_skipped": total_dup,
        "elapsed_seconds": elapsed,
        "max_candidates_per_doc": MAX_CANDIDATES_PER_DOC,
        "items": items,
    }


# --------------------------------------------------------------------------- #
# POST /confirm（唯一写入口）
# --------------------------------------------------------------------------- #
def _resolve_selected(payload: ConfirmRequest) -> list[tuple[int, int]]:
    """把两种入参形式统一成 [(doc_id, candidate_index), ...]。"""
    pairs: list[tuple[int, int]] = []
    if payload.selected:
        for it in payload.selected:
            pairs.append((int(it.doc_id), int(it.index)))
        return pairs
    if payload.doc_ids and payload.candidate_indexes:
        if len(payload.doc_ids) != len(payload.candidate_indexes):
            raise HTTPException(
                status_code=400,
                detail="doc_ids 与 candidate_indexes 长度不一致",
            )
        for did, idxs in zip(payload.doc_ids, payload.candidate_indexes):
            for i in idxs:
                pairs.append((int(did), int(i)))
        return pairs
    raise HTTPException(
        status_code=400,
        detail="必须提供 selected 或 (doc_ids + candidate_indexes)",
    )


@router.post("/confirm")
async def confirm(payload: ConfirmRequest, db: Session = Depends(get_db)):
    """受控入库：只插入用户勾选确认的候选题。

    幂等：再查一次 content_hash 防并发/重复提交；已存在则跳过。
    source 写入 ``知识库:<文档标题>``。
    """
    pairs = _resolve_selected(payload)
    if not pairs:
        raise HTTPException(status_code=400, detail="未选择任何候选题")

    # 校验 doc_id 存在（不存在 → 404，全局处理器会改写 detail）
    doc_ids = sorted({did for did, _ in pairs})
    docs = db.query(Document).filter(Document.id.in_(doc_ids)).all()
    found = {d.id: d for d in docs}
    missing = [i for i in doc_ids if i not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"文档不存在: {missing}")

    taxonomy.load_configured_subjects(db)
    existing_hashes, existing_by_len, existing_lengths = _build_existing_index(db)
    stem_index = _build_stem_index(db)

    # 预计算每篇被引用文档的候选列表（与 scan 完全同口径，index 稳定）
    doc_cands: dict[int, list[dict[str, Any]]] = {}
    for did in doc_ids:
        doc_cands[did], _al, _trunc = _list_doc_candidates(
            found[did], existing_hashes, existing_by_len, existing_lengths
        )

    # 写前备份：批量入库后要清理错入库的题，只能靠物理删除（历史上就因判重缺陷
    # 误删过 158 条真题）。留一个回滚点，比事后删干净安全得多。备份做不成即 503 拒绝。
    from services.kb_service import ensure_write_backup

    ensure_write_backup()

    inserted = 0
    skipped_existing = 0
    out_of_range = 0
    rejected_by_gate: dict[str, int] = {}
    by_subject: dict[str, int] = {}

    for did, idx in pairs:
        cands = doc_cands[did]
        if idx < 0 or idx >= len(cands):
            out_of_range += 1
            continue
        cand = cands[idx]
        # 入库前再查一次哈希防并发（含本批次内已插入的）
        h = cand["content_hash"]
        if h in existing_hashes:
            skipped_existing += 1
            continue

        # ===== 入库前内容闸门（纵深防御：即便前端勾选/索引漂移绕过 scan 过滤）=====
        _src = f"知识库:{found[did].file_name}"
        _ok, _reason = gate_admit(
            cand["content"],
            options=cand.get("options") or [],
            answer=cand.get("answer"),
            source=_src,
            section_type=cand.get("section_type") or "",
            stem_answer_index=stem_index,
        )
        if not _ok:
            rejected_by_gate[_reason] = rejected_by_gate.get(_reason, 0) + 1
            continue

        new_q = QuizQuestion(
            content=cand["content"],
            options=cand["options"] or None,
            answer=cand["answer"],
            analysis=cand["analysis"],
            subject=cand["subject"],
            chapter=cand["chapter"] or None,
            knowledge_point=cand["knowledge_point"] or None,
            difficulty=cand["difficulty"],
            question_type=cand["question_type"],
            source=_src,
            confidence="medium",
        )
        db.add(new_q)
        db.flush()  # 拿到 id，同时让同事务内后续查重可见
        existing_hashes.add(h)  # 本批次内去重
        inserted += 1
        by_subject[cand["subject"]] = by_subject.get(cand["subject"], 0) + 1

    db.commit()
    if rejected_by_gate:
        gate_log_summary()
    return {
        "inserted": inserted,
        "skipped_existing": skipped_existing,
        "out_of_range": out_of_range,
        "rejected_by_gate": rejected_by_gate,
        "by_subject": by_subject,
    }
