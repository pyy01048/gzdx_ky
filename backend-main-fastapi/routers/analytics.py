# -*- coding: utf-8 -*-
"""
学习分析路由（V2.0 新增）

包含：
- 错题AI分析
- 薄弱考点诊断
- 学习轨迹查询
- 学习报告生成
- 作文/主观题智能评分
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from services.learning_analytics_service import LearningAnalyticsService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class ErrorAnalyzeRequest(BaseModel):
    error_id: int = Field(..., description="错题记录ID")


class WeakPointRequest(BaseModel):
    subject: str | None = Field(None, description="学科过滤，如'数学'/'英语'")
    limit: int = Field(20, description="返回薄弱考点数量上限", ge=1, le=50)


class LearningTraceRequest(BaseModel):
    days: int = Field(30, description="查询最近N天的学习数据", ge=1, le=365)


class StudyReportRequest(BaseModel):
    report_type: str = Field("weekly", description="报告类型：weekly/monthly")


class EssayGradeRequest(BaseModel):
    title: str = Field(..., description="作文题目")
    content: str = Field(..., description="作文内容")
    essay_type: str = Field("英语作文", description="作文类型：英语作文/政治大题/专业课论述题等")


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@router.post("/errors/{error_id}/analyze")
async def analyze_error(error_id: int, db: Session = Depends(get_db)):
    """AI分析单道错题，生成错误原因、详细解析、知识点链接和变式题建议。"""
    service = LearningAnalyticsService(db)
    try:
        result = await service.analyze_error(error_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"错题分析失败: {str(e)}")


@router.get("/weak-points")
async def get_weak_points(
    subject: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """获取薄弱考点诊断结果，基于答题记录和错题记录分析。"""
    service = LearningAnalyticsService(db)
    try:
        result = service.diagnose_weak_points(subject=subject, limit=limit)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"考点诊断失败: {str(e)}")


@router.get("/traces")
async def get_learning_traces(
    days: int = 30,
    db: Session = Depends(get_db),
):
    """获取最近N天的学习轨迹数据，包含每日学习统计、连续学习天数、周汇总。"""
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days 参数范围应为 1-365")
    service = LearningAnalyticsService(db)
    try:
        result = service.get_learning_traces(days=days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"学习轨迹查询失败: {str(e)}")


@router.post("/report")
async def generate_study_report(
    request: StudyReportRequest,
    db: Session = Depends(get_db),
):
    """生成学习报告（周报/月报），包含AI总结、学习数据、薄弱考点和学习建议。"""
    if request.report_type not in ["weekly", "monthly"]:
        raise HTTPException(status_code=400, detail="report_type 应为 weekly 或 monthly")
    service = LearningAnalyticsService(db)
    try:
        result = await service.generate_study_report(report_type=request.report_type)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"学习报告生成失败: {str(e)}")


@router.post("/grade-essay")
async def grade_essay(
    request: EssayGradeRequest,
    db: Session = Depends(get_db),
):
    """AI智能评分作文/主观题，多维度分析（内容/结构/语言/词汇/格式）。"""
    if not request.title or not request.content:
        raise HTTPException(status_code=400, detail="题目和内容不能为空")
    service = LearningAnalyticsService(db)
    try:
        result = await service.grade_essay(
            title=request.title,
            content=request.content,
            essay_type=request.essay_type,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"作文评分失败: {str(e)}")


@router.get("/overview")
async def get_analytics_overview(db: Session = Depends(get_db)):
    """获取学习分析概览，汇总核心指标。"""
    service = LearningAnalyticsService(db)
    try:
        traces = service.get_learning_traces(days=7)
        diagnosis = service.diagnose_weak_points(limit=5)
        return {
            "current_streak": traces["current_streak"],
            "longest_streak": traces["longest_streak"],
            "weekly_tasks": traces["total_tasks_completed"],
            "weekly_questions": traces["total_questions_done"],
            "weekly_study_minutes": traces["total_study_minutes"],
            "correct_rate": diagnosis["correct_rate"],
            "total_errors": diagnosis["total_errors"],
            "top_weak_points": diagnosis["weak_points"][:3],
            "error_categories": diagnosis["error_categories"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"概览查询失败: {str(e)}")
