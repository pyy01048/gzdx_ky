# -*- coding: utf-8 -*-
"""院校汇总卡（精准汇总单所院校的全部关键数据）。

把分散在 kaoyan_schools / kaoyan_colleges / kaoyan_majors / kaoyan_admissions /
kaoyan_scorelines / kaoyan_notices 六张表里的院校信息，聚合为一张结构化汇总卡，
供前端「院校详情 / 汇总」视图直接读取，避免前端多次请求拼接。

汇总维度（每校一张）：
- 基础：名称 / 层次 / 省份 / 城市 / 官网 / 简介 / 数据来源
- 专业：专业列表（含学位类型 / 初试科目 / 专业代码）
- 招生：各年招生 / 复试 / 录取人数 + 复试比
- 分数线：总分线 / 单科线 / 国家线（按年份）
- 通知：最新 N 条公告（含类型 / 日期 / 临期截止日 / 已读状态）

用法
----
    from services.kaoyan.school_summarizer import SchoolSummarizer
    s = SchoolSummarizer(db_session)
    card = s.summarize_school(school_id=1, notices_limit=5)
    cards = s.summarize_all(target_provinces=["云南","贵州","广西","广东","四川","重庆"])
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 六省目标院校（与项目「目标院校」口径一致）
TARGET_PROVINCES = ["云南", "贵州", "广西", "广东", "四川", "重庆"]


class SchoolSummarizer:
    """聚合单所/批量院校的汇总卡。只读，不写库。"""

    def __init__(self, db_session):
        self.db = db_session

    # ------------------------------------------------------------------ #
    # 单校汇总
    # ------------------------------------------------------------------ #
    def summarize_school(self, school_id: int, notices_limit: int = 5) -> Optional[Dict[str, Any]]:
        from sqlalchemy import text
        from models import (
            KaoyanSchool, KaoyanCollege, KaoyanMajor, KaoyanAdmission,
            KaoyanScoreLine,
        )

        school = self.db.query(KaoyanSchool).filter(KaoyanSchool.id == school_id).first()
        if not school:
            return None

        # 专业（含学院名）
        majors = (
            self.db.query(KaoyanMajor, KaoyanCollege.name)
            .outerjoin(KaoyanCollege, KaoyanCollege.id == KaoyanMajor.college_id)
            .filter(KaoyanMajor.school_id == school_id)
            .all()
        )
        major_list = [
            {
                "id": m.id,
                "code": m.code,
                "name": m.name,
                "degree_type": m.degree_type,
                "subject_code": m.subject_code,
                "exam_subjects": m.exam_subjects,
                "college": cname,
            }
            for m, cname in majors
        ]

        # 招生（按年份降序）
        adm = (
            self.db.query(KaoyanAdmission)
            .filter(KaoyanAdmission.school_id == school_id)
            .order_by(KaoyanAdmission.year.desc())
            .all()
        )
        admission_list = [
            {
                "year": a.year,
                "major_id": a.major_id,
                "enroll_count": a.enroll_count,
                "retest_count": a.retest_count,
                "admit_count": a.admit_count,
                "admit_avg_score": a.admit_avg_score,
                "retest_ratio": a.retest_ratio,
            }
            for a in adm
        ]

        # 分数线（按年份降序）
        sl = (
            self.db.query(KaoyanScoreLine)
            .filter(KaoyanScoreLine.school_id == school_id)
            .order_by(KaoyanScoreLine.year.desc())
            .all()
        )
        scoreline_list = [
            {
                "year": s.year,
                "major_id": s.major_id,
                "total_line": s.total_line,
                "politics_line": s.politics_line,
                "english_line": s.english_line,
                "math_line": s.math_line,
                "major_line": s.major_line,
                "national_line": s.national_line,
                "retest_line": s.retest_line,
                "line_type": s.line_type,
            }
            for s in sl
        ]

        # 通知（最新 N 条）—— kaoyan_notices 由 spider_notices 原生 DDL 建，
        # 无 ORM 模型，故走原生 SQL（列名以 spider_notices/_DDL 为准）。
        notice_rows = self.db.execute(text(
            """
            SELECT id, title, notice_type, publish_date, deadline_date,
                   importance_level, is_read, is_noise, url
            FROM kaoyan_notices
            WHERE school_id = :sid
            ORDER BY publish_date DESC, id DESC
            LIMIT :lim
            """
        ), {"sid": school_id, "lim": notices_limit}).fetchall()
        notice_list = [
            {
                "id": r.id,
                "title": r.title,
                "notice_type": r.notice_type,
                "publish_date": r.publish_date,
                "deadline_date": r.deadline_date,
                "importance_level": r.importance_level,
                "is_read": bool(r.is_read),
                "is_noise": bool(r.is_noise),
                "url": r.url,
            }
            for r in notice_rows
        ]

        return {
            "school_id": school.id,
            "name": school.name,
            "level": school.level,
            "province": school.province,
            "city": school.city,
            "type": school.type,
            "region": school.region,
            "official_url": school.official_url,
            "intro": school.intro,
            "data_source": school.data_source,
            "stats": {
                "major_count": len(major_list),
                "admission_count": len(admission_list),
                "scoreline_count": len(scoreline_list),
                "notice_count": len(notice_list),
            },
            "majors": major_list,
            "admissions": admission_list,
            "scorelines": scoreline_list,
            "notices": notice_list,
        }

    # ------------------------------------------------------------------ #
    # 批量汇总（目标院校过滤）
    # ------------------------------------------------------------------ #
    def summarize_all(
        self,
        target_provinces: Optional[List[str]] = None,
        notices_limit: int = 5,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """批量汇总。target_provinces 为空时默认六省目标院校。"""
        from models import KaoyanSchool

        provinces = target_provinces if target_provinces is not None else TARGET_PROVINCES
        q = self.db.query(KaoyanSchool)
        if provinces:
            q = q.filter(KaoyanSchool.province.in_(provinces))
        q = q.order_by(KaoyanSchool.id)
        if limit:
            q = q.limit(limit)
        schools = q.all()

        cards = []
        for s in schools:
            card = self.summarize_school(s.id, notices_limit=notices_limit)
            if card:
                cards.append(card)
        return cards
