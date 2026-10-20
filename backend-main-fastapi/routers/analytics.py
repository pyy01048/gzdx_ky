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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from services.learning_analytics_service import LearningAnalyticsService
from services.study_event_service import learning_summary

from utils.response import MAX_PAGE_SIZE

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _optional_user_id(request: Request, db: Session):
    """可选登录态：有 token 就按用户收窄，没有/失效则保持匿名全库口径。

    学习统计的资产表（tasks/flashcards/words/error_records）都带 ``user_id``，
    此前 analytics 一律全库计数——多用户下"我的学习数据"会算进别人的。
    这里不强制登录（保留脚本/巡检的匿名调用），只在带 token 时按人过滤。
    """
    try:
        from utils.security import ACCESS_COOKIE, _bearer, decode_token, load_token_user

        token = _bearer(request) or request.cookies.get(ACCESS_COOKIE)
        if not token:
            return None
        user = load_token_user(db, decode_token(token, "access"))
        return getattr(user, "id", None)
    except Exception:  # noqa: BLE001 - 可选登录态解析失败不能影响统计
        return None


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
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    """获取薄弱考点诊断结果，基于答题记录和错题记录分析。

    考点名单来自 ``services/error_linker.weak_points_view``，与仪表盘 D-10、
    学习画像 TOP10、今日洞察是同一份；`subject` 为空时给出全学科名单。
    """
    service = LearningAnalyticsService(db)
    try:
        result = service.diagnose_weak_points(subject=subject, limit=limit)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"考点诊断失败: {str(e)}")


@router.get("/traces")
async def get_learning_traces(
    request: Request,
    days: int = 30,
    db: Session = Depends(get_db),
):
    """获取最近N天的学习轨迹数据，包含每日学习统计、连续学习天数、周汇总。

    额外附带 ``study_events`` 行为流水汇总（真实耗时 / 答题事件 / 连续天数），
    与业务表台账互为补充：台账回答"完成了多少"，埋点回答"实际学了多久"。
    """
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days 参数范围应为 1-365")
    service = LearningAnalyticsService(db)
    try:
        result = service.get_learning_traces(days=days)
        uid = _optional_user_id(request, db) if request is not None else None
        result["study_events"] = learning_summary(db, user_id=uid, days=days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"学习轨迹查询失败: {str(e)}")


@router.get("/study-summary")
async def get_study_summary(
    request: Request,
    days: int = Query(30, ge=0, le=365, description="统计窗口天数；0 表示全部历史"),
    db: Session = Depends(get_db),
):
    """学习数据一览（设置页 / 仪表盘共用口径）。

    返回业务表资产存量（任务 / 卡片 / 单词 / 错题 / 答题记录）与
    ``study_events`` 行为流水（真实学习分钟、答题事件、活跃天数、连续天数）。
    带登录 token 时按用户过滤；匿名调用保持全库口径（兼容巡检脚本）。
    """
    try:
        uid = _optional_user_id(request, db) if request is not None else None
        return learning_summary(db, user_id=uid, days=days or None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"学习数据汇总失败: {str(e)}")


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
async def get_analytics_overview(request: Request, db: Session = Depends(get_db)):
    """获取学习分析概览，汇总核心指标。

    业务表台账（任务 / 答题 / 错题）与 ``study_events`` 行为流水并用：
    台账缺失时（例如尚未回填历史数据）不会把"实际学过"直接显示成 0。
    """
    service = LearningAnalyticsService(db)
    try:
        uid = _optional_user_id(request, db)
        traces = service.get_learning_traces(days=7)
        diagnosis = service.diagnose_weak_points(limit=5)
        events = learning_summary(db, user_id=uid, days=7)
        return {
            # 连续天数：台账优先，台账为 0 时回退到埋点流水
            "current_streak": traces["current_streak"] or events["current_streak"],
            "longest_streak": max(traces["longest_streak"], events["current_streak"]),
            "weekly_tasks": traces["total_tasks_completed"],
            "weekly_questions": traces["total_questions_done"] or events["answer_events_total"],
            # 真实时长优先用埋点记录；台账的 focus_minutes 与其同源（study_sessions）
            "weekly_study_minutes": traces["total_study_minutes"] or events["study_minutes"],
            "correct_rate": diagnosis["correct_rate"],
            "total_errors": diagnosis["total_errors"],
            "top_weak_points": diagnosis["weak_points"][:3],
            "error_categories": diagnosis["error_categories"],
            # —— study_events 行为流水（热力图 / 连续天数 / 学习数据一览） ——
            "study_events_total": events["study_events_total"],
            "answer_events_total": events["answer_events_total"],
            "study_minutes": events["study_minutes"],
            "today_study_minutes": events["today_study_minutes"],
            "active_days": events["active_days"],
            "study_summary": events,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"概览查询失败: {str(e)}")
