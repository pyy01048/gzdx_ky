"""公式识别路由（A2）：前缀 /api/formula。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services import formula_service

router = APIRouter(prefix="/api/formula", tags=["公式识别"])


class FormulaRecognizeRequest(BaseModel):
    image_path: str
    prefer: Optional[str] = None


class FormulaBatchRequest(BaseModel):
    image_paths: List[str]
    prefer: Optional[str] = None


class FormulaDetectRequest(BaseModel):
    ocr_text: str


@router.post("/recognize")
def recognize_formula(req: FormulaRecognizeRequest, db: Session = Depends(get_db)):
    """公式区识别：VLM + 强约束 prompt → LaTeX → 编译校验。"""
    result = formula_service.recognize_formula(req.image_path, prefer=req.prefer, db=db)
    if result.get("error") and not result.get("latex"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/batch")
def batch_recognize(req: FormulaBatchRequest, db: Session = Depends(get_db)):
    """批量公式识别。"""
    results = formula_service.batch_recognize(req.image_paths, prefer=req.prefer, db=db)
    return {"results": results, "total": len(results),
            "compile_ok_count": sum(1 for r in results if r.get("compile_ok"))}


@router.post("/detect")
def detect_formula(req: FormulaDetectRequest):
    """公式区启发式检测（纯文本判断，不调模型）。"""
    return formula_service.detect_formula_regions(req.ocr_text)


@router.get("/status")
def formula_status():
    """LaTeX 编译器与校验器状态。"""
    compiler = formula_service._find_compiler()
    return {
        "compiler": compiler,
        "compiler_name": formula_service.os.path.basename(compiler) if compiler else None,
        "fallback_validator": "balance_check",
        "mode": "compiler_first" if compiler else "fallback_only",
    }
