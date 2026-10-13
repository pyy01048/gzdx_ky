# -*- coding: utf-8 -*-
"""题库流水线升级脚本（2026-10）：
1) 题干指纹 + 编辑距离去重扫描（报告疑似重复对）
2) 相似题/变式题聚类 → 写 variant_group
3) 缺答案解析题目：多角色互校提示词 → 本地模型生成（ai_generated=true, verified=false）
4) 可选：变式题生成试点（source=ai:variant）

幂等可重跑；输出 JSON 报告到 TEMP_DIR（PowerShell 吞 stdout 规避）。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

from database import SessionLocal  # noqa: E402
from models import QuizQuestion  # noqa: E402
from services import qbank_builder  # noqa: E402
from services.model_gateway import get_gateway  # noqa: E402
from services.quiz_content_gate import admit as gate_admit  # noqa: E402

DUP_THRESHOLD = 0.86       # 题干编辑距离相似度 ≥ 此值判重复
VARIANT_THRESHOLD = 0.75   # ≥ 此值聚为变式组
SAMPLE_ANSWER_N = 8        # 答案解析生成试点题数（缺答案的题里取前 N）
SAMPLE_VARIANT_N = 5       # 变式题生成试点题数


def scan(db) -> dict:
    """去重扫描 + 变式聚类 + 写 variant_group。"""
    qs = db.query(
        QuizQuestion.id, QuizQuestion.content, QuizQuestion.answer,
        QuizQuestion.subject, QuizQuestion.question_type,
        QuizQuestion.knowledge_point, QuizQuestion.variant_group,
    ).all()
    rows = [
        {"id": q.id, "content": q.content or "", "answer": q.answer,
         "subject": q.subject, "question_type": q.question_type or "single",
         "knowledge_point": q.knowledge_point or "", "variant_group": q.variant_group}
        for q in qs
    ]
    total = len(rows)

    # 1) 去重扫描（指纹组内全配对）
    dup_pairs = qbank_builder.dedupe_scan(rows, threshold=DUP_THRESHOLD)
    # 指纹相同 = 精确重复；编辑距离复核仅对指纹不同但可能近似的情况，此处指纹组已覆盖
    hash_dup_ids = sorted({x for p in dup_pairs for x in (p["id_a"], p["id_b"])})

    # 2) 变式聚类 → 写 variant_group
    clusters = qbank_builder.group_variants(rows, threshold=VARIANT_THRESHOLD)
    cluster_count = 0
    for idx, cl in enumerate(clusters):
        gid = f"VG{idx + 1:04d}"
        for qid in cl:
            db.query(QuizQuestion).filter(QuizQuestion.id == qid).update(
                {"variant_group": gid}
            )
        cluster_count += 1
    db.commit()

    return {
        "total_questions": total,
        "dup_pairs_count": len(dup_pairs),
        "dup_pair_sample": dup_pairs[:20],
        "hash_dup_ids": hash_dup_ids,
        "variant_clusters_count": cluster_count,
        "variant_groups": [cl for cl in clusters[:30]],
        "variant_grouped_questions": sum(len(cl) for cl in clusters),
    }


def _extract_json(text: str) -> dict:
    """从模型输出里抽取 JSON 对象（容忍 markdown 代码块包裹）。"""
    t = (text or "").strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return {}
    raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        # 尝试去掉尾部多余逗号等
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
        except Exception:
            return {}


def generate_answers(db, n: int) -> dict:
    """为缺答案解析的题批量生成（多角色互校提示词），标 ai_generated/verified。"""
    missing = db.query(QuizQuestion).filter(
        (QuizQuestion.answer.is_(None)) | (QuizQuestion.answer == "")
    ).order_by(QuizQuestion.id).limit(n).all()
    if not missing:
        return {"generated": 0, "note": "无缺答案解析题目"}

    gw = get_gateway()
    ok = 0
    failed = []
    for q in missing:
        prompt = qbank_builder.generate_answer_prompt({
            "content": q.content,
            "options": q.options,
            "question_type": q.question_type,
            "subject": q.subject,
        })
        try:
            resp = gw.chat(
                prompt,
                subject=None,
                task="json_gen",
                prefer="local",
            )
            data = _extract_json(resp.get("answer") or "")
            ans = data.get("answer") or ""
            ana = data.get("analysis") or ""
            if not ans and not ana:
                raise ValueError("模型输出无有效答案")
            q.answer = (ans or "")[:2000] or None
            q.analysis = (ana or "")[:3000] or None
            q.ai_generated = True
            q.verified = False
            ok += 1
        except Exception as e:
            failed.append({"id": q.id, "err": str(e)[:120]})
        db.commit()

    return {
        "generated": ok,
        "failed": failed,
        "engine": getattr(gw, "strategy", "local"),
    }


def generate_variants(db, n: int) -> dict:
    """变式题生成试点：从有答案的题里取前 n 道，生成同考点变式题入库。"""
    src = db.query(QuizQuestion).filter(
        QuizQuestion.answer.isnot(None),
        QuizQuestion.answer != "",
        QuizQuestion.source.notlike("%ai:variant%"),
    ).order_by(QuizQuestion.id).limit(n).all()
    if not src:
        return {"generated": 0, "note": "无可用母题"}

    gw = get_gateway()
    created = 0
    failed = []
    for q in src:
        prompt = qbank_builder.generate_variant_prompt({
            "content": q.content,
            "options": q.options,
            "answer": q.answer,
            "analysis": q.analysis,
            "question_type": q.question_type,
        })
        try:
            resp = gw.chat(
                prompt,
                subject=None,
                task="json_gen",
                prefer="local",
            )
            data = _extract_json(resp.get("answer") or "")
            content = data.get("content") or ""
            if len(content) < 6:
                raise ValueError("模型输出无有效变式题干")
            variant_src = "ai:variant:" + str(q.id)
            # 入库前内容闸门（docx/16 §1.5-H）：变式题由模型产出，此前
            # 直接 db.add，是两条未接闸写入路径之一。
            ok, reason = gate_admit(
                content,
                options=data.get("options") or [],
                answer=data.get("answer"),
                source=variant_src,
            )
            if not ok:
                raise ValueError(f"闸门拦截：{reason}")
            exists = db.query(QuizQuestion).filter(
                QuizQuestion.content.like(content[:40] + "%")
            ).first()
            if exists:
                raise ValueError("变式题与库内重复")
            db.add(QuizQuestion(
                content=content[:2000],
                options=data.get("options") or None,
                answer=(data.get("answer") or "")[:2000] or None,
                analysis=(data.get("analysis") or "")[:3000] or None,
                subject=q.subject,
                chapter=q.chapter,
                knowledge_point=data.get("knowledge_point") or q.knowledge_point or "",
                difficulty=q.difficulty,
                source=variant_src,
                question_type=q.question_type or "single",
                ai_generated=True,
                verified=False,
                variant_group=q.variant_group,
            ))
            db.commit()
            created += 1
        except Exception as e:
            db.rollback()
            failed.append({"id": q.id, "err": str(e)[:120]})

    return {"generated": created, "failed": failed}


def main() -> None:
    out_path = os.path.join(
        os.environ.get("TEMP_DIR", BASE_DIR),
        "qbank_upgrade_result.json",
    )
    buf = io.StringIO()
    try:
        db = SessionLocal()
        try:
            report = {"scan": scan(db)}
            report["answer_gen"] = generate_answers(db, SAMPLE_ANSWER_N)
            report["variant_gen"] = generate_variants(db, SAMPLE_VARIANT_N)
            buf.write(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            db.close()
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        print("RESULT_WRITTEN " + out_path)
    except Exception:
        import traceback
        with open(out_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print("ERROR_WRITTEN " + out_path)


if __name__ == "__main__":
    main()
