# -*- coding: utf-8 -*-
"""考研规划路由（模块 F1）：18 节点里程碑 + 阶段→月→周→日 三层规划。

新增接口（保持既有 186 接口不变）：
  GET  /api/plan/milestones?year=2027   18 节点时间线（无种子时自动生成，幂等）
  POST /api/plan/generate?year=2027     显式生成/更新 18 节点种子（upsert，不删已有）
  GET  /api/plan/roadmap?year=2027      阶段→月→周→日 三层规划（联动 goals 目标）
"""
from __future__ import annotations

import calendar
import datetime
import math
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models import Goal, Milestone, User
from utils.scope import scoped
from utils.security import current_user
from utils.timeutil import local_today

router = APIRouter(prefix="/api/plan", tags=["考研规划"])

# 18 节点定义：category / name / 相对初试日偏移（天，负=考前）/ importance / action / pitfalls
# 初试日 exam_date = (year-1)年 12 月倒数第二个周六（起 2 天），后续节点在 year 年
MILESTONE_SPECS: List[Dict[str, Any]] = [
    {"name": "招生简章发布", "category": "招生", "offset_days": -105, "importance": 2,
     "action": "核对目标院校招生人数、初试科目、参考书目是否有变",
     "pitfalls": "忽略简章变动，复习科目白费"},
    {"name": "考试大纲发布", "category": "大纲", "offset_days": -95, "importance": 4,
     "action": "对照新大纲逐条核对考点，更新复习范围",
     "pitfalls": "按旧大纲复习，新增/删减考点不清楚"},
    {"name": "预报名", "category": "报名", "offset_days": -80, "importance": 5,
     "action": "完成研招网预报名，确认报考点/专业代码",
     "pitfalls": "错过预报名，正式报名时报考点可能被占满"},
    {"name": "正式报名", "category": "报名", "offset_days": -70, "importance": 5,
     "action": "正式报名并缴费，核对报名信息无误",
     "pitfalls": "信息填错（考试方式/专业方向）无法改"},
    {"name": "网上确认", "category": "确认", "offset_days": -50, "importance": 5,
     "action": "按要求上传照片/材料完成网上确认",
     "pitfalls": "错过确认=报名无效，一年白费"},
    {"name": "命题封题", "category": "命题", "offset_days": -35, "importance": 1,
     "action": "安心按真题规律复习，不再追偏难怪",
     "pitfalls": "焦虑猜测押题，打乱节奏"},
    {"name": "打印准考证", "category": "准考证", "offset_days": -10, "importance": 4,
     "action": "打印准考证，预订考点附近住宿，踩点",
     "pitfalls": "临近考试才发现考点远/住宿紧张"},
    {"name": "初试", "category": "初试", "offset_days": 0, "importance": 5,
     "action": "保持状态，考一科忘一科，检查答题卡填涂",
     "pitfalls": "对答案/失眠影响后续科目"},
    {"name": "阅卷", "category": "阅卷", "offset_days": 20, "importance": 1,
     "action": "休息调整，整理复试通用材料（简历/证书）",
     "pitfalls": "彻底放飞，复试准备来不及"},
    {"name": "成绩公布", "category": "查分", "offset_days": 60, "importance": 5,
     "action": "查询成绩，核对复查流程，判断是否过线",
     "pitfalls": "只盯总分，忽视单科线"},
    {"name": "自划线公布", "category": "院校线", "offset_days": 75, "importance": 4,
     "action": "对比目标院校自划线，确定进入复试名单",
     "pitfalls": "差几分放弃，错过破格/校内调剂"},
    {"name": "国家线公布", "category": "国家线", "offset_days": 85, "importance": 4,
     "action": "确认是否过国家线，准备调剂预案",
     "pitfalls": "等线期间不准备复试内容"},
    {"name": "复试", "category": "复试", "offset_days": 95, "importance": 5,
     "action": "专业课笔试+面试+英语口语全面准备，模拟面试",
     "pitfalls": "只背书不开口，面试表现差"},
    {"name": "调剂系统开放", "category": "调剂", "offset_days": 105, "importance": 4,
     "action": "一志愿不稳立即填报调剂，锁定可调院校",
     "pitfalls": "挑三拣四错过黄金 48 小时"},
    {"name": "体检", "category": "体检", "offset_days": 130, "importance": 2,
     "action": "按院校要求完成体检，保留报告",
     "pitfalls": "体检项目遗漏被要求补检"},
    {"name": "政审", "category": "政审", "offset_days": 135, "importance": 2,
     "action": "准备政审表/档案材料，联系档案所在单位",
     "pitfalls": "档案所在地不清楚，材料拖延"},
    {"name": "拟录取名单", "category": "录取", "offset_days": 150, "importance": 4,
     "action": "确认拟录取，核对公示期异议流程",
     "pitfalls": "未及时确认导致错失"},
    {"name": "录取通知书", "category": "录取", "offset_days": 180, "importance": 3,
     "action": "接收录取通知书，办理调档/住宿/缴费",
     "pitfalls": "错过调档时间影响入学"},
]


def _exam_date(year: int) -> datetime.date:
    """初试日 —— 委托给 services.exam_calendar 这一唯一权威出口。

    原先此处自己按"(year-1) 年 12 月倒数第二个周六"推导，与 dashboard_service 写死的
    12/21 是两套规则。已公布的届（如 2027 届 = 2026-12-19）必须用官方日期，
    不能靠规律蒙——规律对已公布的届可能给出别的答案。
    """
    from services import exam_calendar

    return exam_calendar.resolve_exam_date(year)[0]


def _seed_milestones(db: Session, year: int) -> List[Milestone]:
    """幂等生成/更新 18 节点种子（year+name 唯一）。"""
    exam = _exam_date(year)
    existing = {m.name: m for m in db.query(Milestone).filter(Milestone.year == year).all()}
    seeded: List[Milestone] = []
    for spec in MILESTONE_SPECS:
        off = spec["offset_days"]
        start = exam + datetime.timedelta(days=off)
        # 节点持续天数：初试 2 天；其余 5 天（录取通知书 15 天）
        days = 2 if spec["name"] == "初试" else (15 if spec["name"] == "录取通知书" else 5)
        end = start + datetime.timedelta(days=days - 1)
        if spec["name"] in existing:
            m = existing[spec["name"]]
            m.category = spec["category"]
            m.start_date = start
            m.end_date = end
            m.importance = spec["importance"]
            m.action = spec["action"]
            m.pitfalls = spec["pitfalls"]
            m.is_active = True
        else:
            m = Milestone(
                year=year, name=spec["name"], category=spec["category"],
                start_date=start, end_date=end, importance=spec["importance"],
                action=spec["action"], pitfalls=spec["pitfalls"], is_active=True,
            )
            db.add(m)
        seeded.append(m)
    try:
        db.commit()
    except IntegrityError:
        # 前端并发打 roadmap+milestones，同一届种子被另一请求抢先写入；用胜者的行即可
        db.rollback()
        return db.query(Milestone).filter(Milestone.year == year).all()
    return seeded


def _goal_context(db: Session, user) -> Dict[str, Any]:
    # Goal 属个人域（108 迁移表清单），读写均按当前用户 scope；
    # Milestone 是公共招生日历内容，不随用户隔离。
    goal = db.query(Goal).filter(scoped(Goal, user)).order_by(Goal.id.asc()).first()
    if not goal:
        return {}
    ctx: Dict[str, Any] = {
        "university": goal.university,
        "major": goal.major,
        "total_score_target": goal.total_score_target,
    }
    if goal.exam_date:
        ctx["exam_date"] = goal.exam_date.isoformat()
    return ctx


def _build_roadmap(year: int, milestones: List[Milestone]) -> Dict[str, Any]:
    """阶段→月→周→日 三层规划。"""
    exam = _exam_date(year)
    today = local_today()

    # 阶段划分（按距初试天数）
    stages: List[Dict[str, Any]] = []
    base_end = exam - datetime.timedelta(days=210)
    stage_specs = [
        ("基础", exam - datetime.timedelta(days=360), exam - datetime.timedelta(days=210),
         "过一遍考纲全部考点 + 完成第一轮笔记与例题", "数学打基础 / 英语单词与长难句 / 专业课第一轮"),
        ("强化", exam - datetime.timedelta(days=210), exam - datetime.timedelta(days=90),
         "真题套卷 + 高频考点强化 + 错题本闭环", "暑期集中强化 / 真题分科训练 / 政治第一轮"),
        ("冲刺", exam - datetime.timedelta(days=90), exam,
         "模拟考试 + 查漏补缺 + 回归教材", "全真模拟 / 背诵冲刺 / 考场节奏演练"),
    ]
    months: List[Dict[str, Any]] = []
    for stage_name, s_start, s_end, stage_goal, stage_daily in stage_specs:
        # 该阶段覆盖的月份（从 s_start 所在月到 s_end 所在月，最多 6 个月）
        cur = s_start.replace(day=1)
        stage_months: List[Dict[str, Any]] = []
        while cur <= s_end and len(stage_months) < 6:
            # 当月内阶段部分
            m_start = max(s_start, cur)
            m_end = min(s_end, (cur.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1))
            weeks = int(math.ceil((m_end - m_start).days / 7))
            # 每周任务模板
            weekly = []
            for wk in range(1, weeks + 1):
                if stage_name == "基础":
                    weekly.append(f"第{wk}周：章节推进（数学+英语单词）并完成课后习题")
                elif stage_name == "强化":
                    weekly.append(f"第{wk}周：真题专项（2 套）+ 错题整理")
                else:
                    weekly.append(f"第{wk}周：全真模拟 {wk} 次 + 复盘")
            stage_months.append({
                "month": cur.strftime("%Y-%m"),
                "label": f"{cur.month}月（{stage_name}）",
                "start": m_start.isoformat(),
                "end": m_end.isoformat(),
                "weeks": weekly,
            })
            cur = (cur.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        stages.append({
            "name": stage_name,
            "start": s_start.isoformat(),
            "end": s_end.isoformat(),
            "goal": stage_goal,
            "daily_routine": stage_daily,
            "months": stage_months,
        })
        months.extend(stage_months)

    # 里程碑（带倒计时与所属阶段/月份）
    node_list = []
    for m in sorted(milestones, key=lambda x: x.start_date or datetime.date.max):
        start = m.start_date or exam
        remain = (start - today).days
        stage = "基础"
        if remain <= 90:
            stage = "冲刺"
        elif remain <= 210:
            stage = "强化"
        node_list.append({
            "id": m.id, "name": m.name, "category": m.category,
            "start": start.isoformat(), "end": (m.end_date or start).isoformat(),
            "importance": m.importance, "action": m.action, "pitfalls": m.pitfalls,
            "days_left": remain, "stage": stage,
        })

    from services import exam_calendar as _cal

    return {
        "year": year,
        "exam_date": exam.isoformat(),
        # 未公布的届是规则推导出来的，界面必须标「预估」，不能和教育部公布的日期混为一谈
        "exam_date_is_official": _cal.resolve_exam_date(year)[1],
        "days_to_exam": (exam - today).days,
        "stages": stages,
        "milestones": node_list,
    }


def _resolve_plan_year(db: Session, year: Optional[int] = None, user=None) -> int:
    """确定计划要按哪一届生成。

    优先级：显式传入 > 当前用户 Goal 里配置/反推出的届 > 按当前时间推断。
    原先三个端点都写死 ``year: int = 2027``，用户改了届数复习计划还停在旧年份。
    """
    from services import exam_calendar

    if year is not None:
        return exam_calendar.validate_exam_year(year)
    info = exam_calendar.resolve_for_db(
        db.query(Goal).filter(scoped(Goal, user)).order_by(Goal.id.asc()).first()
    )
    return exam_calendar.validate_exam_year(info["exam_year"])


def _plan_years(db: Session, target: int) -> List[int]:
    """规划页可选的届数：库里已经生成过节点的届 ∪ 当前目标届（倒序）。

    刻意不返回 [2026, 2027, 2028] 这种写死的候选——那是一条会过期的断言，
    到了下一年界面还在推销旧届。目标届永远包含在内（GET 会自动为其补种子）。
    """
    rows = db.query(Milestone.year).distinct().all()
    years = {int(r[0]) for r in rows if r[0] is not None}
    years.add(int(target))
    return sorted(years, reverse=True)


@router.get("/milestones")
def list_milestones(
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """18 节点时间线（无种子时自动生成）。year 不传则跟随当前用户配置的届。"""
    year = _resolve_plan_year(db, year, user)
    rows = db.query(Milestone).filter(Milestone.year == year).all()
    if not rows:
        _seed_milestones(db, year)
        rows = db.query(Milestone).filter(Milestone.year == year).all()
    today = local_today()
    exam = _exam_date(year)
    out = []
    for m in sorted(rows, key=lambda x: x.start_date or datetime.date.max):
        # 与 /roadmap 内嵌节点同一算法；缺 start_date 的节点退回初试日，
        # 否则前端读到 undefined 会渲染成「已过 NaN 天」（实测 18/18 命中）。
        anchor = m.start_date or exam
        out.append({
            "id": m.id, "year": m.year, "name": m.name, "category": m.category,
            "start": (m.start_date or "").isoformat() if m.start_date else None,
            "end": (m.end_date or "").isoformat() if m.end_date else None,
            "importance": m.importance, "action": m.action, "pitfalls": m.pitfalls,
            "days_left": (anchor - today).days,
            "is_active": m.is_active,
        })
    return {"year": year, "total": len(out), "milestones": out,
            "available_years": _plan_years(db, year),
            "exam_date": _exam_date(year).isoformat()}


@router.post("/generate")
def generate_milestones(
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """显式生成/更新 18 节点种子（upsert）。year 不传则跟随当前用户配置的届。"""
    year = _resolve_plan_year(db, year, user)
    seeded = _seed_milestones(db, year)
    return {"year": year, "total": len(seeded), "detail": "18 节点已生成/更新"}


@router.get("/roadmap")
def get_roadmap(
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """阶段→月→周→日 三层规划（联动当前用户 goals 目标）。year 不传则跟随其配置的届。"""
    year = _resolve_plan_year(db, year, user)
    rows = db.query(Milestone).filter(Milestone.year == year).all()
    if not rows:
        rows = _seed_milestones(db, year)
    roadmap = _build_roadmap(year, rows)
    roadmap["goal"] = _goal_context(db, user)
    roadmap["available_years"] = _plan_years(db, year)
    return roadmap
