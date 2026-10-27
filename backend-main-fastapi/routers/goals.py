"""考研目标路由。"""

import asyncio
import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from core.models import Goal, KaoyanSchool, KaoyanScoreline
from models import User
from schemas import GoalCreate, GoalUpdate, UniversityCreate, UniversitySearchRequest
from utils.scope import owner_id, scoped  # B4 行级隔离
from utils.security import current_user
from utils.timeutil import local_today

#: /strategy 等待 AI 的上限（秒）；须小于 utils/timeout_guard 对该路径的 90s 阈值。
STRATEGY_AI_TIMEOUT = 80.0

router = APIRouter(prefix="/api/goals", tags=["goals"])


def _school_dict(db: Session, s: KaoyanSchool) -> dict:
    """组装院校响应（保持旧 /university 接口结构，数据源迁移至 kaoyan_schools/kaoyan_scorelines）。"""
    lines = (
        db.query(KaoyanScoreline)
        .filter(KaoyanScoreline.school_id == s.id)
        .order_by(KaoyanScoreline.year.desc())
        .all()
    )
    return {
        "id": s.id,
        "name": s.name,
        "type": s.level,
        "city": s.city or s.province,
        "major_name": None,
        "score_lines": {str(ln.year): ln.total_line for ln in lines if ln.total_line is not None},
        "admission_ratio": None,
        "difficulty": None,
    }


@router.get("/subjects")
async def get_subjects(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """读取备考科目配置（考试科目 + 专业课支撑科目，B4：读本人 Goal）。

    这是"方便我设置"的入口：改这里，进度统计口径、AI 分科路由、
    资料归类、出题范围会一起跟着变。
    """
    from services import subject_config

    return subject_config.get_config(db, user_id=owner_id(user))


@router.put("/subjects")
async def update_subjects(payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """设置备考科目。

    body: `{"exam_subjects": ["数字电子技术","模拟电子技术","数学","英语","政治"],
            "support_subjects": ["电路","信号与系统","计算机学科专业基础408"]}`
    传空数组表示清空该层（清空后即为「尚未配置」，不会再回填内置默认科目）。
    """
    from services import subject_config

    exam = payload.get("exam_subjects")
    support = payload.get("support_subjects")
    if exam is None and support is None:
        raise HTTPException(status_code=400, detail="至少提供 exam_subjects 或 support_subjects")
    if exam is not None and not isinstance(exam, list):
        raise HTTPException(status_code=400, detail="exam_subjects 必须是数组")
    if support is not None and not isinstance(support, list):
        raise HTTPException(status_code=400, detail="support_subjects 必须是数组")

    return subject_config.set_config(
        db, exam_subjects=exam, support_subjects=support, user_id=owner_id(user)
    )


@router.get("")
async def get_goal(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取考研目标。"""
    goal = db.query(Goal).filter(scoped(Goal, user)).order_by(Goal.id.asc()).first()
    if not goal:
        return {"message": "尚未设置目标"}
    return {
        "id": goal.id,
        "exam_date": goal.exam_date.isoformat() if goal.exam_date else None,
        "total_score_target": goal.total_score_target,
        "politics_target": goal.politics_target,
        "english_target": goal.english_target,
        "math_target": goal.math_target,
        "major_target": goal.major_target,
        "university": goal.university,
        "major": goal.major,
        "subjects": goal.subject_codes,
        "support_subjects": goal.support_subject_codes,
        # 每日目标原样返回（None=未设）：仪表盘进度环与设置页共用同一份分母，
        # 前端不再自带"今日 50 词"这类默认值。
        "daily_focus_minutes": goal.daily_focus_minutes,
        "daily_new_words": goal.daily_new_words,
        "daily_review_words": goal.daily_review_words,
        "daily_questions": goal.daily_questions,
        "remark": goal.remark,
    }


# --------------------------------------------------------------------------- #
# 届数 / 初试日期（用户要求「届可以随时调整」）
# --------------------------------------------------------------------------- #
@router.get("/exam-calendar")
async def get_exam_calendar(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """当前届数与初试日期（只读）。

    返回值由 ``services.exam_calendar`` 统一推导 —— 前端不要再自己算。
    """
    from services import exam_calendar

    goal = db.query(Goal).filter(scoped(Goal, user)).order_by(Goal.id.asc()).first()
    info = exam_calendar.resolve_for_db(goal)
    info["configured"] = bool(goal and goal.exam_date)
    # 可选届范围：当前 ±6 年，方便前端渲染下拉而不用写死
    today_year = exam_calendar.default_exam_year()
    info["year_options"] = list(range(today_year - 6, today_year + 7))
    return info


@router.put("/exam-calendar")
async def update_exam_calendar(payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """调整届数（或直接指定初试日期）。

    两种用法：
    1. ``{"exam_year": 2027}`` —— 只给届数，初试日按官方公布值 / 规律自动推算（推荐）。
    2. ``{"exam_date": "2026-12-19"}`` —— 直接钉死某一天（官方临时调整时用）。
    3. ``{"exam_year": 2027, "exam_date": "2026-12-19"}`` —— 两者都传，以 exam_date 为准，
       同时保存届数语义。

    改了届数后，复习里程碑（``/api/plan/*``）会按新届数重新推导，
    不需要用户再去别处手动同步。
    """
    from services import exam_calendar

    goal = db.query(Goal).filter(scoped(Goal, user)).order_by(Goal.id.asc()).first()
    if not goal:
        goal = Goal(user_id=owner_id(user))  # B4：新建目标归属当前用户
        db.add(goal)

    exam_year = payload.get("exam_year")
    raw_date = payload.get("exam_date")

    if raw_date:
        try:
            exam_date = datetime.date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            raise HTTPException(status_code=422, detail="exam_date 需为 YYYY-MM-DD")
    elif exam_year is not None:
        try:
            year = exam_calendar.validate_exam_year(exam_year)
        except exam_calendar.ExamYearError as e:
            raise HTTPException(status_code=422, detail=str(e))
        exam_date, _ = exam_calendar.resolve_exam_date(year)
    else:
        raise HTTPException(status_code=400, detail="至少提供 exam_year 或 exam_date")

    goal.exam_date = exam_date
    # 分项目标自洽性：分项之和与总分不一致时（真库实测 65+65+115+115=360 但总分填 350），
    # 不擅自改用户的分项目标，只把修正后的总分回填并明确告知，避免两个数字互相矛盾。
    parts = [goal.politics_target, goal.english_target,
             goal.math_target, goal.major_target]
    old_total = goal.total_score_target
    adjusted_total = None
    if all(p is not None for p in parts):
        s = sum(parts)
        if old_total != s:
            adjusted_total = s

    if adjusted_total is not None:
        goal.total_score_target = adjusted_total

    db.commit()
    db.refresh(goal)

    info = exam_calendar.resolve_for_db(goal)
    info["configured"] = True
    info["total_score_adjusted_from"] = None
    if adjusted_total is not None:
        info["total_score_adjusted_from"] = {
            "old": old_total,
            "new": adjusted_total,
            "reason": "四科分项目标之和与原总分不一致，已按分项之和回填",
        }
    return info


@router.put("")
async def update_goal(goal: GoalUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """更新目标。"""
    db_goal = db.query(Goal).filter(scoped(Goal, user)).order_by(Goal.id.asc()).first()
    if not db_goal:
        db_goal = Goal(user_id=owner_id(user))  # B4：新建目标归属当前用户
        db.add(db_goal)

    update_data = goal.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_goal, key, value)

    db.commit()
    db.refresh(db_goal)
    return {"id": db_goal.id, "message": "目标更新成功"}


@router.get("/university")
async def get_university(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取目标院校信息。"""
    goal = db.query(Goal).filter(scoped(Goal, user)).order_by(Goal.id.asc()).first()
    if not goal or not goal.university:
        schools = db.query(KaoyanSchool).limit(10).all()
    else:
        schools = (
            db.query(KaoyanSchool)
            .filter(KaoyanSchool.name.like(f"%{goal.university}%"))
            .all()
        )
    return [_school_dict(db, s) for s in schools]


@router.post("/university/search")
async def search_universities(
    keyword: str = "",
    city: str = "",
    type: str = "",
    db: Session = Depends(get_db),
):
    """搜索院校。"""
    query = db.query(KaoyanSchool)
    if keyword:
        query = query.filter(KaoyanSchool.name.like(f"%{keyword}%"))
    if city:
        query = query.filter(
            (KaoyanSchool.city == city) | (KaoyanSchool.province == city)
        )
    if type:
        query = query.filter(KaoyanSchool.level == type)

    schools = query.limit(50).all()
    return [_school_dict(db, s) for s in schools]


@router.get("/strategy")
async def get_strategy(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """AI 院校备考策略。"""
    from services.ai_service import AIService

    goal = db.query(Goal).filter(scoped(Goal, user)).order_by(Goal.id.asc()).first()
    if not goal:
        raise HTTPException(status_code=400, detail="请先设置考研目标")

    school = (
        db.query(KaoyanSchool).filter(KaoyanSchool.name.like(f"%{goal.university or ''}%")).first()
    )

    ai = AIService(db)
    prompt_parts = [
        f"目标院校：{goal.university or '未设置'}",
        f"目标专业：{goal.major or '未设置'}",
    ]
    if school:
        prompt_parts.append(f"院校类型：{school.level or ''}")
        prompt_parts.append(f"所在城市：{school.city or school.province or ''}")
    prompt_parts.append("请给出针对该院校该专业的备考策略，包括各科目标分数、复习重点和时间规划建议。")

    try:
        # 给 AI 一个明确上限：超时即走下方模板降级。上限须小于 timeout_guard 对本路径的
        # 90s 阈值，否则守卫先 504，降级永远轮不到。
        result = await asyncio.wait_for(ai.chat([
            {"role": "system", "content": "你是一位考研规划专家，擅长制定院校备考策略。"},
            {"role": "user", "content": "\n".join(prompt_parts)},
        ]), timeout=STRATEGY_AI_TIMEOUT)
        return {"content": result["content"]}
    except Exception as e:
        # AI 不可用（未配置服务商 / 本地模型未启动 / 网络异常）时优雅降级，
        # 返回基于目标数据的模板策略，而不是让该接口 500、页面白屏。
        return _fallback_strategy(goal, school, str(e))


def _fallback_strategy(goal, school, reason: str):
    """无 AI 时的规则模板备考策略（数据取自当前 Goal，不编造院校信息）。"""
    days_left = ""
    if goal.exam_date:
        try:
            n = (goal.exam_date - local_today()).days
            days_left = f"，距初试约 {n} 天" if n > 0 else ""
        except Exception:  # noqa: BLE001
            days_left = ""

    def _line(label, value, hint):
        if value:
            return f"- **{label}目标**：{value} 分"
        return f"- **{label}目标**：建议 {hint}"

    score_lines = [
        _line("政治", goal.politics_target, "65–70 分"),
        _line("英语", goal.english_target, "60–70 分（按院校层次调整）"),
        _line("数学/业务课一", goal.math_target, "90–110 分"),
        _line("专业课/业务课二", goal.major_target, "100–120 分"),
    ]
    total_line = (
        f"- **总分目标**：{goal.total_score_target} 分"
        if goal.total_score_target
        else "- **总分目标**：建议参照目标院校近三年复试线并上浮 10–15 分"
    )

    school_note = ""
    if school is None and goal.university:
        school_note = (
            f"\n> 注：题库中暂未检索到「{goal.university}」的完整招生数据，"
            "院校层次、复试线等请以研究生院官网为准。\n"
        )

    content = f"""# {goal.university or '目标院校'} · {goal.major or '目标专业'} 备考策略

> 本策略由系统模板生成（当前 AI 规划助手不可用：{reason}）。配置可用 AI 服务商后可获得个性化策略。
> 考试日期：{goal.exam_date or '未设置'}{days_left}
{school_note}
## 一、分数目标
{total_line}
{chr(10).join(score_lines)}

## 二、各科目复习重点
- **政治**：前期以马原、毛中特理解为主，配合选择题；9 月起结合时政，冲刺阶段集中背诵分析题模板与押题。
- **英语**：全程坚持单词与长难句，暑期前完成阅读方法论；中后期精练真题阅读、准备作文模板并定期默写。
- **数学/业务课一**：先过教材与基础概念，再按章节刷题、整理错题本；强化阶段成套训练，重视计算准确率。
- **专业课**：以目标院校指定教材与历年真题为核心，梳理知识框架与高频考点，真题至少做两遍并归纳命题规律。

## 三、时间规划（按阶段）
1. **基础阶段（启动—6 月）**：通读教材、建立知识框架，英语单词与数学基础同步推进，配套基础习题。
2. **强化阶段（7—9 月）**：分科专题突破、大量刷题，建立并持续维护错题本；专业课完成第一轮真题。
3. **提升阶段（10—11 月）**：成套真题与模拟卷限时训练，查漏补缺；政治分析题、英语作文开始背诵。
4. **冲刺模考（12 月—考前）**：按考试时间全真模考、回归错题与高频考点，调整作息与心态。

## 四、执行建议
- 每周制定可量化的学习计划并在打卡中复盘；错题及时归因、按艾宾浩斯节奏复习。
- 定期核对目标院校招生简章、专业目录与复试线，如有变动及时调整目标与科目。"""

    return {"content": content, "fallback": True, "fallback_reason": reason}
