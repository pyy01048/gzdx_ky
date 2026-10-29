# -*- coding: utf-8 -*-
"""通用题目分析引擎路由（模块1：MathLens 式结构化分析 + HTML 讲义）。"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from schemas import AnalysisRequest, LectureRequest
from services import analysis_engine

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _resolve_question(req, db) -> str:
    """优先取显式文本；否则若有图片路径先走三层 OCR。"""
    if req.question and req.question.strip():
        return req.question.strip()
    if req.image_path:
        if not os.path.isfile(req.image_path):
            raise HTTPException(status_code=400, detail=f"图片不存在: {req.image_path}")
        ocr = analysis_engine.recognize_problem_image(req.image_path)
        if ocr.get("error") or not ocr.get("text"):
            raise HTTPException(status_code=422, detail=f"OCR 识别失败: {ocr.get('error')}")
        return ocr["text"].strip()
    raise HTTPException(status_code=400, detail="question 与 image_path 至少提供一个")


@router.post("/analyze")
def analyze(req: AnalysisRequest, db: Session = Depends(get_db)):
    """题目输入 → 结构化分析（已知条件/思路/分步推导/结论验证/知识点/易错点）。"""
    question = _resolve_question(req, db)
    try:
        result = analysis_engine.analyze_problem(
            question=question,
            subject=req.subject,
            prefer=req.prefer,
            db=db,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"分析失败: {type(e).__name__}: {e}") from e
    result["subject"] = req.subject or "未分类"
    return result


@router.post("/lecture")
def generate_lecture(req: LectureRequest, db: Session = Depends(get_db)):
    """生成可视化 HTML 讲义（KaTeX 公式渲染）并落盘。"""
    analysis = req.analysis
    if not analysis:
        question = _resolve_question(req, db)
        try:
            analysis = analysis_engine.analyze_problem(
                question=question,
                subject=req.subject,
                prefer=req.prefer,
                db=db,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"分析失败: {type(e).__name__}: {e}") from e
    analysis["question"] = analysis.get("question") or req.question or ""
    analysis["subject"] = analysis.get("subject") or req.subject or ""
    try:
        html = analysis_engine.build_lecture_html(analysis)
        path = analysis_engine.save_lecture(html, subject=analysis.get("subject"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"讲义生成失败: {type(e).__name__}: {e}") from e
    return {"path": path, "name": os.path.basename(path), "lecture_dir": analysis_engine.LECTURE_DIR}


@router.get("/lectures")
def list_lectures():
    """已生成讲义列表。"""
    return analysis_engine.list_lectures()


@router.post("/ocr")
def ocr_problem_image(body: dict, db: Session = Depends(get_db)):
    """仅 OCR 图片题目（供前端预览识别文本）。"""
    image_path = body.get("image_path") or ""
    prefer = body.get("prefer") or "auto"
    if not image_path or not os.path.isfile(image_path):
        raise HTTPException(status_code=400, detail=f"图片不存在: {image_path}")
    return analysis_engine.recognize_problem_image(image_path, prefer=prefer)


@router.post("/layout-cut")
def ocr_layout_cut(body: dict, db: Session = Depends(get_db)):
    """OCR 版面切题：识别图片 → 按版面切分为多道独立题目（stem/options/type）。

    P0 能力：借助含坐标的 OCR 结果（blocks + box），识别题号模式切分题目与选项，
    产出结构化字段，供批量入库/逐题分析。
    """
    image_path = body.get("image_path") or ""
    prefer = body.get("prefer") or "auto"
    min_qno = int(body.get("min_qno") or 1)
    if not image_path or not os.path.isfile(image_path):
        raise HTTPException(status_code=400, detail=f"图片不存在: {image_path}")
    from services import ocr_layout
    from services.ocr_router import recognize_file

    result = recognize_file(image_path, prefer=prefer)
    if result.error or not result.text:
        raise HTTPException(status_code=422, detail=f"OCR 识别失败: {result.error}")
    try:
        questions = ocr_layout.cut_questions(result, min_qno=min_qno)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"版面切题失败: {type(e).__name__}: {e}") from e
    return {
        "engine": result.engine,
        "question_count": len(questions),
        "questions": questions,
        "full_text": result.text,
    }


# ---------------- T7：学习者画像 ---------------- #
@router.get("/profile")
def learner_profile(days: int = 30, db: Session = Depends(get_db)):
    """学习者画像聚合（总览/科目掌握度/薄弱知识点/复习队列/趋势/建议）。

    数据全部来自真实行为表（answer_records/error_records/exam_sessions/tasks），
    建议为规则生成（确定性），不调 LLM。
    """
    from services.learner_profile import build_profile

    days = max(7, min(days, 180))  # 窗口夹紧，防全表扫描
    return build_profile(db, days=days)
