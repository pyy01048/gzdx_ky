# -*- coding: utf-8 -*-
"""闭环个性化推题服务（55 号 DeepTutor 升级方案 P0-C）。

闭环链路：识别薄弱知识点 → LLM 生成变式题 → 刷题 → 掌握门控。
本模块是「薄弱点识别 + 变式题生成 + 掌握门控」的服务层，全部按 user_id
做行级隔离（B4），生成类任务走 model_gateway，失败一律旁路容错。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from models import (
    AnswerRecord,
    KnowledgePoint,
    QuestionKnowledgeLink,
    QuizQuestion,
)

logger = logging.getLogger(__name__)

#: 变式题来源标记（与前端 / 题库管理筛选约定一致）
SOURCE_LABEL_AI_VARIANT = "ai:variant"


def identify_weak_points(
    db: Session,
    user_id: int,
    subject: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """融合三个信号识别薄弱知识点，返回按 weak_score 降序的列表。

    信号 A：错题密度（``error_linker.weak_knowledge_points``）
    信号 B：四态模型中的 weak 状态（``kp_mastery``，仅取已学且 mastery<70 的知识点）
    信号 C：L2 记忆事实中的 weakness（``memory_service.list_facts``）

    融合规则：按 knowledge_point_id 合并，``weak_score`` =
    ``error_count*2 + memory_fact_count*3 + (100-mastery)/10``。
    ``sources`` 为命中的信号子集（["error","mastery","memory"]）。
    """
    from services import error_linker, kp_mastery, memory_service

    limit = max(int(limit or 10), 0)

    # 信号 A：错题密度（已按 user_id 过滤）
    error_rows = error_linker.weak_knowledge_points(
        db, subject=subject, limit=30, user_id=user_id
    )
    merged: dict[int, dict[str, Any]] = {}
    for r in error_rows:
        kp_id = r.get("knowledge_point_id")
        if kp_id is None:
            continue
        merged[kp_id] = {
            "knowledge_point_id": kp_id,
            "name": r.get("name"),
            "subject": r.get("subject"),
            "chapter": r.get("chapter"),
            "mastery": int(r.get("mastery") or 0),
            "error_count": int(r.get("error_count") or 0),
            "memory_fact_count": 0,
            "sources": ["error"],
        }

    # 信号 B：四态模型中的 weak 状态（已学且 mastery ∈ (0, 70)）
    try:
        learned_ids = kp_mastery.learned_kp_ids(db)
        kp_q = db.query(KnowledgePoint)
        if subject:
            kp_q = kp_q.filter(KnowledgePoint.subject == subject)
        for kp in kp_q.all():
            mastery = int(kp.mastery or 0)
            state = kp_mastery.classify_state(mastery, kp.id in learned_ids)
            if state != kp_mastery.STATE_WEAK:
                continue
            if not (0 < mastery < kp_mastery.MASTERED_THRESHOLD):
                continue
            item = merged.get(kp.id)
            if item is None:
                merged[kp.id] = {
                    "knowledge_point_id": kp.id,
                    "name": kp.name,
                    "subject": kp.subject,
                    "chapter": kp.chapter,
                    "mastery": mastery,
                    "error_count": 0,
                    "memory_fact_count": 0,
                    "sources": [],
                }
            else:
                # 已有其它信号：取更低的 mastery（更薄弱）作为该点掌握度
                item["mastery"] = min(int(item.get("mastery") or 0), mastery)
            item = merged[kp.id]
            if "mastery" not in item.get("sources", []):
                item.setdefault("sources", []).append("mastery")
    except Exception as exc:  # noqa: BLE001 - 信号 B 失败不阻塞融合
        logger.warning("薄弱点识别-掌握度信号失败（已忽略）: %s", exc)

    # 信号 C：L2 记忆 weakness 事实（带 knowledge_point 字段）
    try:
        facts = memory_service.list_facts(
            db, user_id=user_id, fact_type="weakness", limit=200
        )
        for fact in facts:
            kp_id = fact.get("knowledge_point_id")
            # 名称字段：优先 kp_name，其次兼容 knowledge_point 字段
            kp_name = fact.get("kp_name") or fact.get("knowledge_point")
            if kp_id is None and kp_name:
                # 缺失 id 时尝试按名称匹配已合并项
                for item in merged.values():
                    if item.get("name") and str(item["name"]) == str(kp_name):
                        kp_id = item["knowledge_point_id"]
                        break
            if kp_id is None:
                continue
            item = merged.get(kp_id)
            if item is None:
                merged[kp_id] = {
                    "knowledge_point_id": kp_id,
                    "name": kp_name if kp_name and not isinstance(kp_name, dict) else None,
                    "subject": fact.get("subject"),
                    "chapter": None,
                    "mastery": 0,
                    "error_count": 0,
                    "memory_fact_count": 0,
                    "sources": [],
                }
            item["memory_fact_count"] = int(item.get("memory_fact_count") or 0) + 1
            if "memory" not in item.get("sources", []):
                item.setdefault("sources", []).append("memory")
    except Exception as exc:  # noqa: BLE001 - 信号 C 失败不阻塞融合
        logger.warning("薄弱点识别-记忆事实信号失败（已忽略）: %s", exc)

    # 融合计分 + 排序 + 截断
    out: list[dict[str, Any]] = []
    for item in merged.values():
        error_count = int(item.get("error_count") or 0)
        memory_fact_count = int(item.get("memory_fact_count") or 0)
        mastery = int(item.get("mastery") or 0)
        weak_score = (
            error_count * 2
            + memory_fact_count * 3
            + (100 - mastery) / 10
        )
        item["weak_score"] = round(weak_score, 2)
        item["sources"] = sorted(set(item.get("sources") or []))
        out.append(item)

    out.sort(key=lambda x: (-x.get("weak_score", 0), x.get("knowledge_point_id") or 0))
    return out[:limit]


# --------------------------------------------------------------------------- #
# 变式题生成
# --------------------------------------------------------------------------- #
_VARIANT_SYSTEM_PROMPT = "你是考研命题专家，只输出 JSON 数组，不要输出任何其他文字。"
_VARIANT_QUESTION_TYPES = ("single", "multiple", "judge", "calc", "fill", "essay")


def _build_variant_prompt(kp: KnowledgePoint, count: int) -> str:
    """构造变式题生成 prompt（让模型扮演考研命题老师）。"""
    return (
        f"你是考研命题老师，请基于知识点「{kp.name}」"
        f"（科目：{kp.subject}，章节：{kp.chapter}）命制 {count} 道变式题。\n"
        "要求：\n"
        "1. 题目必须紧扣该知识点，难度适中（约等于考研真题），不要重复。\n"
        "2. 严格输出 JSON 数组，不要输出任何其他文字、代码块标记或解释。\n"
        "3. 数组每项结构：\n"
        '   {"content": "题干", "options": [{"key": "A", "text": "选项"}], '
        '"answer": "正确答案", "analysis": "解析", "question_type": "single|multiple|judge|calc|fill|essay", '
        '"answer_type": "objective|subjective"}\n'
        "4. 客观题（single/multiple/judge）answer_type 为 objective，options 为 4 项数组；\n"
        "   主观题（essay）与计算题（calc）/ 填空题（fill）answer_type 为 subjective，options 可省略。\n"
        "5. 计算题的 question_type 用 calc，answer_type 用 subjective。"
    )


def _extract_json_array(text: str) -> list[Any]:
    """从模型输出中容错提取 JSON 数组。

    容忍 markdown 代码块（```json ... ```）与前后杂质，用正则
    ``\\[.*\\]`` 提取最外层数组后再 json.loads。
    """
    if not text:
        raise ValueError("模型输出为空")
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise ValueError("模型输出中未找到 JSON 数组")
    data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise ValueError("模型输出不是 JSON 数组")
    return data


def _normalize_variant_options(options: Any) -> list[dict[str, str]] | None:
    """把模型输出的 options 规整为 ``[{"key":"A","text":"..."}]`` 正典结构。

    - None / 空 → None
    - dict（如 {"A": "..."}）→ 转数组
    - 数组元素为 {key,text} dict → 保留；元素为字符串 → 按字母生成 key
    """
    if not options:
        return None
    out: list[dict[str, str]] = []
    if isinstance(options, dict):
        for k, v in options.items():
            if v is None or not str(v).strip():
                continue
            out.append({"key": str(k).strip().upper()[:1] or "A", "text": str(v).strip()})
        return out or None
    if isinstance(options, list):
        keys = "ABCDEFGH"
        for idx, opt in enumerate(options):
            if isinstance(opt, dict) and opt.get("text") is not None:
                key = str(opt.get("key") or "").strip().upper()[:1] or keys[idx % len(keys)]
                text = str(opt.get("text") or "").strip()
                if text:
                    out.append({"key": key, "text": text})
            elif isinstance(opt, str) and opt.strip():
                out.append({"key": keys[idx % len(keys)], "text": opt.strip()})
        return out or None
    return None


def generate_variant_questions(
    db: Session,
    user_id: int,
    kp_id: int,
    count: int = 3,
    subject: str | None = None,
) -> dict[str, Any]:
    """LLM 生成薄弱点变式题并入库。

    先查 KnowledgePoint，查不到抛 ``ValueError("知识点不存在")``。
    模型输出非法 JSON / 网关失败时**不抛异常**，返回
    ``{"created": 0, "error": "..."}``（旁路容错）。
    成功时提交并返回 ``{"created": n, "variant_group": "variant:<kp_id>", "question_ids": [...]}``。
    """
    from services.model_gateway import get_gateway

    kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == int(kp_id)).first()
    if kp is None:
        raise ValueError("知识点不存在")

    count = max(int(count or 3), 1)
    prompt = _build_variant_prompt(kp, count)
    try:
        result = get_gateway().chat(
            question=prompt,
            subject=subject or kp.subject,
            task="题目分析",
            system_prompt=_VARIANT_SYSTEM_PROMPT,
            db=db,
        )
        raw = (result or {}).get("answer") or ""
        items = _extract_json_array(raw)
    except Exception as exc:  # noqa: BLE001 - 解析失败/网关异常 → 降级返回
        db.rollback()
        logger.warning("变式题生成失败（已旁路）: %s", exc)
        return {"created": 0, "error": f"变式题生成失败：{exc}"}

    created_ids: list[int] = []
    variant_group = f"variant:{kp_id}"
    for item in items:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        question_type = str(item.get("question_type") or "single").strip().lower()
        if question_type not in _VARIANT_QUESTION_TYPES:
            question_type = "single"
        answer_type = str(item.get("answer_type") or (
            "objective" if question_type in ("single", "multiple", "judge") else "subjective"
        )).strip().lower()
        if answer_type not in ("objective", "subjective"):
            answer_type = (
                "objective" if question_type in ("single", "multiple", "judge") else "subjective"
            )
        q = QuizQuestion(
            content=content,
            options=_normalize_variant_options(item.get("options")),
            answer=str(item.get("answer") or "").strip() or None,
            analysis=str(item.get("analysis") or "").strip() or None,
            subject=kp.subject,
            chapter=kp.chapter,
            knowledge_point=kp.name,
            difficulty=3,
            source_label=SOURCE_LABEL_AI_VARIANT,
            question_type=question_type,
            answer_type=answer_type,
            ai_generated=True,
            verified=False,
            variant_group=variant_group,
            is_available=True,
            is_junk=False,
            confidence="medium",
        )
        db.add(q)
        db.flush()
        created_ids.append(q.id)

    if not created_ids:
        db.rollback()
        return {"created": 0, "error": "模型输出中没有可入库的有效题目"}

    db.commit()
    return {
        "created": len(created_ids),
        "variant_group": variant_group,
        "question_ids": created_ids,
    }


# --------------------------------------------------------------------------- #
# 掌握门控
# --------------------------------------------------------------------------- #
def mastery_gate(
    db: Session,
    user_id: int,
    kp_id: int,
    consecutive_required: int = 3,
) -> dict[str, Any]:
    """掌握门控：检查薄弱知识点最近连续答对是否达到阈值。

    - 知识点不存在 → ``{"mastered": False, "reason": "kp_not_found"}``
    - 无关联题目 → ``{"mastered": False, "reason": "no_linked_questions", "consecutive_correct": 0}``
    - 达到阈值 → 调 ``kp_mastery.touch_mastery`` 触发掌握度重算，并写 L1 记忆轨迹。
    """
    from services import kp_mastery, memory_service

    kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == int(kp_id)).first()
    if kp is None:
        return {"mastered": False, "reason": "kp_not_found"}

    linked_qids = [
        row[0]
        for row in db.query(QuestionKnowledgeLink.question_id)
        .filter(QuestionKnowledgeLink.knowledge_point_id == kp.id)
        .all()
    ]
    if not linked_qids:
        return {
            "mastered": False,
            "reason": "no_linked_questions",
            "consecutive_correct": 0,
            "required": consecutive_required,
            "kp_id": kp.id,
            "kp_name": kp.name,
            "mastery": int(kp.mastery or 0),
        }

    records = (
        db.query(AnswerRecord)
        .filter(
            AnswerRecord.user_id == int(user_id),
            AnswerRecord.question_id.in_(linked_qids),
            AnswerRecord.is_correct.isnot(None),
        )
        .order_by(AnswerRecord.created_at.desc(), AnswerRecord.id.desc())
        .all()
    )

    consecutive = 0
    for rec in records:
        if rec.is_correct:
            consecutive += 1
        else:
            break

    mastered = consecutive >= int(consecutive_required or 3)
    if mastered:
        try:
            kp_mastery.touch_mastery(db, [kp.id])
        except Exception as exc:  # noqa: BLE001 - 重算失败不影响门控结论
            logger.warning("掌握度重算失败（已忽略）: %s", exc)
        memory_service.record_trace(
            user_id=int(user_id),
            trace_type="study",
            title="知识点掌握门控通过",
            payload={
                "kp_id": kp.id,
                "kp_name": kp.name,
                "consecutive_correct": consecutive,
                "required": int(consecutive_required or 3),
            },
            subject=kp.subject,
            db=db,
        )
        try:
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()

    return {
        "mastered": mastered,
        "consecutive_correct": consecutive,
        "required": int(consecutive_required or 3),
        "kp_id": kp.id,
        "kp_name": kp.name,
        "mastery": int(kp.mastery or 0),
    }