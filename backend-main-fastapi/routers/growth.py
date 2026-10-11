# -*- coding: utf-8 -*-
"""成长体系（模块 F2）：等级 / 徽章 / 积分 / 成就。

基于 study_events 事件流水聚合计算：
  GET /api/growth/summary        总览（等级、积分、徽章/成就数量、下一等级进度）
  GET /api/growth/levels         等级定义
  GET /api/growth/badges         徽章列表（含解锁状态）
  GET /api/growth/achievements   成就列表（含解锁状态）
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import StudyEvent

router = APIRouter(prefix="/api/growth", tags=["成长体系"])

# --------------------------------------------------------------------------- #
# 等级定义（按累计积分阈值）
# --------------------------------------------------------------------------- #
LEVELS: List[Dict[str, Any]] = [
    {"level": 1, "threshold": 0, "name": "备考新兵"},
    {"level": 2, "threshold": 100, "name": "初出茅庐"},
    {"level": 3, "threshold": 300, "name": "渐入佳境"},
    {"level": 4, "threshold": 600, "name": "稳扎稳打"},
    {"level": 5, "threshold": 1000, "name": "厚积薄发"},
    {"level": 6, "threshold": 1500, "name": "学有所成"},
    {"level": 7, "threshold": 2100, "name": "博学多才"},
    {"level": 8, "threshold": 2800, "name": "出类拔萃"},
    {"level": 9, "threshold": 3600, "name": "名列前茅"},
    {"level": 10, "threshold": 4500, "name": "考研大师"},
]


def _points(stats: Dict[str, int]) -> int:
    return (
        stats["answer_correct"] * 10
        + stats["answer_wrong"] * 3
        + stats["submit_total"] * 5
        + stats["review_total"] * 4
        + stats["study_seconds"] // 60
    )


def _collect_stats(db: Session) -> Dict[str, int]:
    """聚合 study_events 基础统计（表可能为空）。"""
    s = {
        "answer_total": 0, "answer_correct": 0, "answer_wrong": 0,
        "submit_total": 0, "review_total": 0, "study_seconds": 0,
        "active_days": 0, "streak_days": 0, "fast_correct": 0,
    }
    try:
        rows = db.query(
            StudyEvent.event_type,
            func.count(StudyEvent.id),
        ).group_by(StudyEvent.event_type).all()
        for et, cnt in rows:
            if et in ("answer", "submit", "review", "study"):
                s[f"{et}_total"] = cnt

        corr = db.query(func.count(StudyEvent.id)).filter(
            StudyEvent.event_type == "answer", StudyEvent.is_correct.is_(True)
        ).scalar() or 0
        s["answer_correct"] = corr
        s["answer_wrong"] = max(0, s["answer_total"] - corr)

        dur = db.query(func.coalesce(func.sum(StudyEvent.duration_seconds), 0)).filter(
            StudyEvent.event_type == "study"
        ).scalar() or 0
        s["study_seconds"] = int(dur or 0)

        # 活跃天数
        days = db.query(func.date(StudyEvent.occurred_at)).distinct().all()
        day_set = {d[0] for d in days if d[0]}
        s["active_days"] = len(day_set)
        s["streak_days"] = _streak(day_set)

        # 快速答对（<=60s 且答对）
        fast = db.query(func.count(StudyEvent.id)).filter(
            StudyEvent.event_type == "answer",
            StudyEvent.is_correct.is_(True),
            StudyEvent.duration_seconds.isnot(None),
            StudyEvent.duration_seconds <= 60,
        ).scalar() or 0
        s["fast_correct"] = fast
    except Exception:
        pass
    return s


def _streak(day_set: set) -> int:
    if not day_set:
        return 0
    dset = set()
    for d in day_set:
        try:
            dset.add(datetime.date.fromisoformat(d))
        except (TypeError, ValueError):
            continue
    today = datetime.date.today()
    cur = today
    if cur not in dset:
        cur = today - datetime.timedelta(days=1)
    streak = 0
    while cur in dset:
        streak += 1
        cur -= datetime.timedelta(days=1)
    return streak


# --------------------------------------------------------------------------- #
# 徽章定义
# --------------------------------------------------------------------------- #
BADGE_SPECS: List[Dict[str, Any]] = [
    {"code": "first_answer", "name": "首答", "desc": "完成第一次答题", "icon": "1", "check": lambda s: s["answer_total"] >= 1},
    {"code": "correct_5", "name": "五连答对", "desc": "累计答对 5 题", "icon": "5", "check": lambda s: s["answer_correct"] >= 5},
    {"code": "correct_50", "name": "答题新星", "desc": "累计答对 50 题", "icon": "50", "check": lambda s: s["answer_correct"] >= 50},
    {"code": "answer_100", "name": "百题斩", "desc": "累计答题 100 题", "icon": "100", "check": lambda s: s["answer_total"] >= 100},
    {"code": "submit_10", "name": "模拟先锋", "desc": "完成 10 次交卷/模拟", "icon": "S", "check": lambda s: s["submit_total"] >= 10},
    {"code": "review_30", "name": "复习达人", "desc": "完成 30 次复习", "icon": "R", "check": lambda s: s["review_total"] >= 30},
    {"code": "study_10h", "name": "十小时磨砺", "desc": "累计学习时长达到 10 小时", "icon": "10h", "check": lambda s: s["study_seconds"] >= 36000},
    {"code": "study_50h", "name": "五十小时深耕", "desc": "累计学习时长达到 50 小时", "icon": "50h", "check": lambda s: s["study_seconds"] >= 180000},
    {"code": "active_7", "name": "七日打卡", "desc": "累计活跃 7 天", "icon": "7d", "check": lambda s: s["active_days"] >= 7},
    {"code": "active_30", "name": "月度坚持", "desc": "累计活跃 30 天", "icon": "30d", "check": lambda s: s["active_days"] >= 30},
    {"code": "streak_3", "name": "三日连击", "desc": "连续学习 3 天", "icon": "3x", "check": lambda s: s["streak_days"] >= 3},
    {"code": "streak_7", "name": "一周狂飙", "desc": "连续学习 7 天", "icon": "7x", "check": lambda s: s["streak_days"] >= 7},
    {"code": "fast_correct_10", "name": "快手学霸", "desc": "10 次 1 分钟内答对", "icon": "F", "check": lambda s: s["fast_correct"] >= 10},
]

# --------------------------------------------------------------------------- #
# 成就定义
# --------------------------------------------------------------------------- #
ACHIEVEMENT_SPECS: List[Dict[str, Any]] = [
    {"code": "acc_100", "name": "百题成钢", "desc": "累计答对 100 题", "check": lambda s: s["answer_correct"] >= 100},
    {"code": "acc_200", "name": "双百进阶", "desc": "累计答对 200 题", "check": lambda s: s["answer_correct"] >= 200},
    {"code": "acc_500", "name": "五百强者", "desc": "累计答对 500 题", "check": lambda s: s["answer_correct"] >= 500},
    {"code": "study_100h", "name": "百日千时", "desc": "累计学习时长达到 100 小时", "check": lambda s: s["study_seconds"] >= 360000},
    {"code": "streak_30", "name": "月月全勤", "desc": "连续学习 30 天", "check": lambda s: s["streak_days"] >= 30},
    {"code": "review_100", "name": "温故知新", "desc": "完成 100 次复习", "check": lambda s: s["review_total"] >= 100},
    {"code": "submit_30", "name": "模考达人", "desc": "完成 30 次模拟交卷", "check": lambda s: s["submit_total"] >= 30},
    {"code": "wrong_recover_20", "name": "错题逆袭", "desc": "累计答错 20 题后仍坚持（答题总量 >= 120）", "check": lambda s: s["answer_wrong"] >= 20 and s["answer_total"] >= 120},
    {"code": "allround_5", "name": "五科均衡", "desc": "活跃天数达到 5 天且答题超过 50 题", "check": lambda s: s["active_days"] >= 5 and s["answer_total"] >= 50},
    {"code": "rookie_done", "name": "成长启航", "desc": "首次达到 2 级（积分 >= 100）", "check": lambda s: _points(s) >= 100},
    {"code": "master_5", "name": "五级里程碑", "desc": "达到 5 级（积分 >= 1000）", "check": lambda s: _points(s) >= 1000},
    {"code": "grand_8", "name": "八级荣耀", "desc": "达到 8 级（积分 >= 2800）", "check": lambda s: _points(s) >= 2800},
]


def _level_of(points: int) -> Dict[str, Any]:
    cur = LEVELS[0]
    for i, lv in enumerate(LEVELS):
        if points >= lv["threshold"]:
            cur = lv
        else:
            break
    nxt = None
    for lv in LEVELS:
        if lv["threshold"] > points:
            nxt = lv
            break
    progress = 0
    if nxt:
        base = cur["threshold"]
        span = nxt["threshold"] - base
        progress = round((points - base) / span * 100) if span else 100
    return {"level": cur["level"], "name": cur["name"], "threshold": cur["threshold"],
            "next": ({"level": nxt["level"], "name": nxt["name"], "threshold": nxt["threshold"]} if nxt else None),
            "progress": min(progress, 100), "points": points}


def _points_detail(stats: Dict[str, int]) -> Dict[str, Any]:
    return [
        {"source": "答题答对", "count": stats["answer_correct"], "unit": 10, "points": stats["answer_correct"] * 10},
        {"source": "答题答错", "count": stats["answer_wrong"], "unit": 3, "points": stats["answer_wrong"] * 3},
        {"source": "交卷/模拟", "count": stats["submit_total"], "unit": 5, "points": stats["submit_total"] * 5},
        {"source": "复习", "count": stats["review_total"], "unit": 4, "points": stats["review_total"] * 4},
        {"source": "学习时长", "count": stats["study_seconds"] // 60, "unit": "1/分钟", "points": stats["study_seconds"] // 60},
    ]


@router.get("/summary")
def growth_summary(db: Session = Depends(get_db)):
    """成长总览：等级 / 积分 / 徽章 / 成就。"""
    stats = _collect_stats(db)
    points = _points(stats)
    level = _level_of(points)
    badges = [{"code": b["code"], "name": b["name"], "desc": b["desc"],
               "earned": b["check"](stats)} for b in BADGE_SPECS]
    achievements = [{"code": a["code"], "name": a["name"], "desc": a["desc"],
                     "earned": a["check"](stats)} for a in ACHIEVEMENT_SPECS]
    return {
        "level": level,
        "stats": stats,
        "points_detail": _points_detail(stats),
        "badge_count": sum(1 for b in badges if b["earned"]),
        "achievement_count": sum(1 for a in achievements if a["earned"]),
    }


@router.get("/levels")
def growth_levels():
    return {"levels": LEVELS}


@router.get("/badges")
def growth_badges(db: Session = Depends(get_db)):
    stats = _collect_stats(db)
    return {"badges": [{"code": b["code"], "name": b["name"], "desc": b["desc"],
                        "icon": b["icon"], "earned": b["check"](stats)} for b in BADGE_SPECS]}


@router.get("/achievements")
def growth_achievements(db: Session = Depends(get_db)):
    stats = _collect_stats(db)
    return {"achievements": [{"code": a["code"], "name": a["name"], "desc": a["desc"],
                              "earned": a["check"](stats)} for a in ACHIEVEMENT_SPECS]}
