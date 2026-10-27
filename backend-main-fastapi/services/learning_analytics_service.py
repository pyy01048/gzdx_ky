# -*- coding: utf-8 -*-
"""
学习分析服务（V2.0 新增）

包含：
- 错题AI分析：自动分析错误原因、生成解析、推荐变式题
- 考点诊断：基于答题记录分析各考点掌握度，识别薄弱考点
- 学习轨迹：记录每日学习数据，生成趋势分析
- 学习报告：周报/月报自动生成
- 作文评分：多维度智能评分
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import ErrorRecord, AnswerRecord
from services import error_linker, kp_mastery
from services.ai_service import AIService
from services.study_calendar import day_ledger, fill_series, streak_summary
from utils.timeutil import iso_utc_z, local_today, utcnow


class LearningAnalyticsService:
    """学习分析服务。"""

    def __init__(self, db: Session):
        self.db = db
        self.ai = AIService(db)

    # ------------------------------------------------------------------
    # 错题AI分析
    # ------------------------------------------------------------------
    async def analyze_error(self, error_id: int) -> Dict[str, Any]:
        """AI分析单道错题，生成错误原因、详细解析、知识点链接和变式题建议。

        Args:
            error_id: 错题记录ID

        Returns:
            {
                "error_id": int,
                "question": str,
                "user_answer": str,
                "correct_answer": str,
                "error_reason": str,          # AI分析的错误原因
                "error_category": str,        # 错误分类：概念不清/计算失误/审题错误/方法不当
                "detailed_explanation": str,  # 详细解析
                "related_knowledge": list,    # 相关知识点
                "similar_questions": list,     # 推荐的同类变式题
                "review_suggestion": str,      # 复习建议
            }
        """
        error = self.db.query(ErrorRecord).filter(ErrorRecord.id == error_id).first()
        if not error:
            raise ValueError(f"错题记录 {error_id} 不存在")

        # 构建AI分析prompt
        prompt = f"""请作为一位经验丰富的考研辅导老师，分析以下错题：

题目：{error.content or '（无题目内容）'}
用户答案：{error.my_answer or '（未作答）'}
正确答案：{error.correct_answer or '（无正确答案）'}
题目解析：{error.analysis or '（无解析）'}
学科：{error.subject or '未知'}

请按以下格式输出分析结果：

【错误原因】
分析用户做错这道题的根本原因，是概念不清、计算失误、审题错误还是方法不当？

【错误分类】
只能选择以下之一：概念不清 / 计算失误 / 审题错误 / 方法不当 / 知识盲区

【详细解析】
给出这道题的完整解题步骤和思路，让用户理解为什么正确答案是对的，用户的答案错在哪里。

【相关知识点】
列出这道题涉及的3-5个核心知识点，每个知识点用一句话说明。

【变式题建议】
给出2道同类型的变式题，帮助用户巩固这个知识点。每道题包含题目和答案。

【复习建议】
针对用户的错误，给出具体的复习建议和后续学习方向。
"""

        try:
            messages = [
                {"role": "system", "content": "你是一位经验丰富的考研辅导老师，擅长分析错题和给出针对性学习建议。回答要专业、详细、有针对性。"},
                {"role": "user", "content": prompt},
            ]
            result = await self.ai.chat(messages)
            ai_content = result.get("content", "")

            # 解析AI输出
            analysis = self._parse_error_analysis(ai_content)

            # 更新错题记录的错误原因
            if analysis.get("error_category"):
                try:
                    error.error_reason = analysis["error_category"]
                    self.db.commit()
                except Exception:
                    self.db.rollback()

            return {
                "error_id": error_id,
                "question": error.content or "",
                "user_answer": error.my_answer or "",
                "correct_answer": error.correct_answer or "",
                "error_reason": analysis.get("error_reason", ""),
                "error_category": analysis.get("error_category", "待分析"),
                "detailed_explanation": analysis.get("detailed_explanation", ""),
                "related_knowledge": analysis.get("related_knowledge", []),
                "similar_questions": analysis.get("similar_questions", []),
                "review_suggestion": analysis.get("review_suggestion", ""),
                "ai_raw": ai_content[:2000],
            }
        except Exception as e:
            return {
                "error_id": error_id,
                "question": error.content or "",
                "error_reason": "",
                "error_category": "分析失败",
                "detailed_explanation": "",
                "related_knowledge": [],
                "similar_questions": [],
                "review_suggestion": "",
                "error": str(e),
            }

    def _parse_error_analysis(self, content: str) -> Dict[str, Any]:
        """解析AI输出的错题分析文本。"""
        result = {
            "error_reason": "",
            "error_category": "",
            "detailed_explanation": "",
            "related_knowledge": [],
            "similar_questions": [],
            "review_suggestion": "",
        }

        # 按【】标签分段
        sections = re.split(r"【([^】]+)】", content)
        for i in range(1, len(sections), 2):
            title = sections[i].strip()
            body = sections[i + 1].strip() if i + 1 < len(sections) else ""

            if "错误原因" in title:
                result["error_reason"] = body[:500]
            elif "错误分类" in title:
                # 提取分类
                for cat in ["概念不清", "计算失误", "审题错误", "方法不当", "知识盲区"]:
                    if cat in body:
                        result["error_category"] = cat
                        break
                if not result["error_category"]:
                    result["error_category"] = body[:50]
            elif "详细解析" in title:
                result["detailed_explanation"] = body[:1500]
            elif "相关知识点" in title:
                # 提取知识点列表
                points = re.findall(r"[\d.、]\s*([^\n，。]+)", body)
                result["related_knowledge"] = [p.strip() for p in points[:8] if p.strip()]
            elif "变式题" in title or "类似题" in title:
                result["similar_questions"] = [body[:800]]
            elif "复习建议" in title:
                result["review_suggestion"] = body[:500]

        return result

    # ------------------------------------------------------------------
    # 考点诊断
    # ------------------------------------------------------------------
    def diagnose_weak_points(self, subject: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """基于答题记录和错题记录，诊断薄弱考点。

        考点名单**不在这里算**：唯一出口是
        ``services/error_linker.weak_points_view``（仪表盘 D-10、学习画像 TOP10、
        今日洞察 weak_top 取的是同一份）。本方法只把它投影成接口字段。

        Returns:
            {
                "total_questions": int,
                "correct_rate": float,            # 0-100
                "weak_points": [
                    {"knowledge_point_id": int, "knowledge_point": str, "subject": str,
                     "chapter": str, "error_count": int, "mastery": int,
                     "level": "薄弱"/"已掌握", "suggestion": str}
                ],
                "error_categories": {"概念不清": int, "计算失误": int, ...},
                "subject_distribution": {"数学": int, "英语": int, ...},
            }
        """
        # 统计答题记录
        query = self.db.query(AnswerRecord)
        if subject:
            query = query.filter(AnswerRecord.subject == subject)
        total_answers = query.count()
        correct_answers = query.filter(AnswerRecord.is_correct == True).count()
        correct_rate = round(correct_answers / total_answers * 100, 1) if total_answers > 0 else 0

        # 统计错题
        error_query = self.db.query(ErrorRecord).filter(ErrorRecord.status == "active")
        if subject:
            error_query = error_query.filter(ErrorRecord.subject == subject)
        errors = error_query.all()

        # 错误原因分类统计
        error_categories = {"概念不清": 0, "计算失误": 0, "审题错误": 0, "方法不当": 0, "知识盲区": 0, "待分析": 0}
        for e in errors:
            reason = (e.error_reason or "待分析").strip()
            matched = False
            for cat in error_categories:
                if cat in reason:
                    error_categories[cat] += 1
                    matched = True
                    break
            if not matched:
                error_categories["待分析"] += 1

        # 学科分布
        subject_dist = {}
        for e in errors:
            subj = e.subject or "未知"
            subject_dist[subj] = subject_dist.get(subj, 0) + 1

        # 薄弱考点分析（唯一出口：error_knowledge_links × active 错题）
        weak_points = self._weak_point_rows(subject, limit)

        return {
            "total_questions": total_answers,
            "correct_answers": correct_answers,
            "correct_rate": correct_rate,
            "total_errors": len(errors),
            "weak_points": weak_points,
            "error_categories": error_categories,
            "subject_distribution": subject_dist,
            "diagnosis_time": iso_utc_z(utcnow()),
        }

    def _weak_point_rows(self, subject: Optional[str], limit: int) -> List[Dict[str, Any]]:
        """把 ``error_linker.weak_points_view`` 投影成 /weak-points 的响应字段。

        ``knowledge_point`` 是 ``name`` 的旧键名，保留是为了不弄坏已有调用方；
        新增的 ``knowledge_point_id`` 让前端能深链到错题本，
        ``mastery`` 的三态判定走 kp_mastery 的阈值（这里没有第四套）。
        一条错题都没挂上知识点 ⇒ 空列表，界面显示「还没归集」，
        不再用正则从题干猜考点名（那会凭空造出「XX定理」这种库里不存在的标签）。
        """
        rows = []
        for p in error_linker.weak_points_view(self.db, subject=subject, limit=limit):
            # weak_points_view 的行必然来自 error_knowledge_links，即有学习记录。
            state = kp_mastery.classify_state(p["mastery"], has_records=True)
            name = p["name"]
            rows.append({
                "knowledge_point_id": p["knowledge_point_id"],
                "knowledge_point": name,
                "subject": p["subject"],
                "chapter": p["chapter"],
                "error_count": p["error_count"],
                "mastery": p["mastery"],
                "level": kp_mastery.STATE_LABELS[state],
                "suggestion": (
                    f"「{name}」掌握较好，可适当减少复习频率。"
                    if state == kp_mastery.STATE_MASTERED
                    else f"「{name}」还有 {p['error_count']} 道错题未毕业，建议优先复习这个考点。"
                ),
            })
        return rows

    # ------------------------------------------------------------------
    # 学习轨迹
    # ------------------------------------------------------------------
    def get_learning_traces(self, days: int = 30) -> Dict[str, Any]:
        """最近 N 天的学习轨迹：**全部派生自 ``services/study_calendar`` 日活台账**。

        Returns:
            {
                "days": int,
                "total_study_days": int,
                "effective_study_days": int,
                "current_streak": int,
                "longest_streak": int,
                "streak_rule": str,
                "daily_data": [
                    {"date": "2026-08-01", "tasks_completed": int, "questions_done": int,
                     "errors_added": int, "study_duration_minutes": int,
                     "reviews_done": int, "correct_rate": float|None, "is_effective": bool}
                ],
                "weekly_summary": [...],
            }

        历史实现自带两套**私有口径**（2026-10-16 起废弃）：

        1. 时长 = 已完成任务 ×30 分钟 + 答题 ×5 分钟 的**估算值**。估算数一旦进
           指标卡就等于撒谎——用户从没开过专注计时，也会被记成"今天学了 150 分钟"；
        2. streak 只看 tasks/questions 非空，和仪表盘的「有效学习日」判定对不上，
           同一个用户两处能给出两个连续天数。

        现在时长只认真实专注记录 ``focus_minutes``，连续天数走 ``streak_summary``；
        任务完成认 ``Task.completed_at``（原实现按 ``updated_at``，今天改过一次状态
        就会被算成"今天完成"）。
        """
        end_date = local_today()
        start_date = end_date - timedelta(days=days - 1)

        ledger = day_ledger(self.db, start_day=start_date, end_day=end_date)
        series = fill_series(ledger, start_date, end_date)
        streak = streak_summary(ledger, today=end_date)

        daily_data = [
            {
                "date": a.date.isoformat(),
                "tasks_completed": a.tasks_done,
                "questions_done": a.questions_done,
                "errors_added": a.errors_added,
                # 真实专注分钟：没记录就是 0，不拿题数/任务数换算
                "study_duration_minutes": a.focus_minutes,
                "reviews_done": a.reviews_done,
                "correct_rate": a.correct_rate,
                "is_effective": a.is_effective,
            }
            for a in series
        ]

        # 周汇总
        weekly_summary = self._calc_weekly_summary(daily_data)

        return {
            "days": days,
            "date_range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "total_study_days": sum(1 for a in series if a.is_active),
            "effective_study_days": streak["total_days"],
            "current_streak": streak["current"],
            "longest_streak": streak["longest"],
            "streak_rule": streak["rule"],
            "total_tasks_completed": sum(a.tasks_done for a in series),
            "total_questions_done": sum(a.questions_done for a in series),
            "total_study_minutes": sum(a.focus_minutes for a in series),
            "daily_data": daily_data,
            "weekly_summary": weekly_summary,
        }

    def _calc_weekly_summary(self, daily_data: List[Dict]) -> List[Dict]:
        """计算周汇总数据。"""
        weeks = []
        current_week = None
        for d in daily_data:
            date = datetime.fromisoformat(d["date"])
            week_num = date.isocalendar()[1]
            if current_week is None or current_week["week"] != week_num:
                if current_week:
                    weeks.append(current_week)
                current_week = {
                    "week": week_num,
                    "start_date": d["date"],
                    "tasks_completed": 0,
                    "questions_done": 0,
                    "study_minutes": 0,
                }
            current_week["end_date"] = d["date"]
            current_week["tasks_completed"] += d["tasks_completed"]
            current_week["questions_done"] += d["questions_done"]
            current_week["study_minutes"] += d["study_duration_minutes"]
        if current_week:
            weeks.append(current_week)
        return weeks

    # ------------------------------------------------------------------
    # 学习报告生成
    # ------------------------------------------------------------------
    async def generate_study_report(self, report_type: str = "weekly") -> Dict[str, Any]:
        """生成学习报告（周报/月报）。

        Args:
            report_type: "weekly" 或 "monthly"
        """
        days = 7 if report_type == "weekly" else 30
        traces = self.get_learning_traces(days)
        diagnosis = self.diagnose_weak_points()

        # AI生成报告总结
        prompt = f"""请根据以下学习数据，生成一份{'周' if report_type == 'weekly' else '月'}学习报告总结：

学习天数：{traces['total_study_days']}天
连续学习：{traces['current_streak']}天
完成任务：{traces['total_tasks_completed']}个
刷题数量：{traces['total_questions_done']}道
学习时长：{traces['total_study_minutes']}分钟
正确率：{diagnosis['correct_rate']}%
薄弱考点：{', '.join([p['knowledge_point'] for p in diagnosis['weak_points'][:5]])}

请用鼓励性的语气，总结本阶段学习情况，指出优点和不足，给出下一阶段的学习建议。
字数控制在300字以内。"""

        try:
            messages = [
                {"role": "system", "content": "你是一位贴心的学习教练，擅长用鼓励性的语言总结学习情况并给出建议。"},
                {"role": "user", "content": prompt},
            ]
            result = await self.ai.chat(messages)
            ai_summary = result.get("content", "")
        except Exception:
            ai_summary = "AI总结生成失败，请查看详细数据。"

        return {
            "report_type": report_type,
            "period_days": days,
            "generated_at": iso_utc_z(utcnow()),
            "ai_summary": ai_summary,
            "learning_traces": traces,
            "weak_point_diagnosis": diagnosis,
            "suggestions": self._generate_suggestions(traces, diagnosis),
        }

    def _generate_suggestions(self, traces: Dict, diagnosis: Dict) -> List[str]:
        """基于数据生成具体学习建议。"""
        suggestions = []

        if traces["current_streak"] >= 7:
            suggestions.append(f"连续学习{traces['current_streak']}天，保持得很好！继续保持这个节奏。")
        elif traces["current_streak"] >= 3:
            suggestions.append(f"已经连续学习{traces['current_streak']}天，再接再厉，争取突破7天！")
        else:
            suggestions.append("学习连续性有待提高，建议每天固定时间学习，培养学习习惯。")

        if diagnosis["correct_rate"] >= 80:
            suggestions.append(f"正确率{diagnosis['correct_rate']}%，表现优秀！可以适当增加题目难度。")
        elif diagnosis["correct_rate"] >= 60:
            suggestions.append(f"正确率{diagnosis['correct_rate']}%，基础尚可，建议针对错题进行专项突破。")
        else:
            suggestions.append(f"正确率{diagnosis['correct_rate']}%，基础需要加强，建议先回归教材和基础题。")

        if diagnosis["weak_points"]:
            weak = diagnosis["weak_points"][0]
            suggestions.append(f"最薄弱考点是「{weak['knowledge_point']}」（错误{weak['error_count']}次），建议本周重点复习。")

        if traces["total_questions_done"] < 50:
            suggestions.append("刷题量偏少，建议每天至少完成10道练习题，保持题感。")

        return suggestions

    # ------------------------------------------------------------------
    # 作文/主观题评分
    # ------------------------------------------------------------------
    async def grade_essay(self, title: str, content: str, essay_type: str = "英语作文") -> Dict[str, Any]:
        """AI智能评分作文/主观题，多维度分析。

        Args:
            title: 作文题目
            content: 作文内容
            essay_type: 作文类型（英语作文/政治大题/专业课论述题等）
        """
        prompt = f"""请作为一位资深的{essay_type}阅卷老师，对以下作文进行评分和点评：

题目：{title}

作文内容：
{content}

请按以下格式输出评分结果：

【总分】
满分100分，给出总分。

【各维度评分】
1. 内容切题（25分）：得分 + 评语
2. 结构逻辑（20分）：得分 + 评语
3. 语言表达（25分）：得分 + 评语
4. 词汇语法（20分）：得分 + 评语
5. 书写格式（10分）：得分 + 评语

【亮点分析】
指出作文中的2-3个亮点。

【问题与改进建议】
指出作文中的3-5个问题，并给出具体的改进建议。

【修改示范】
选取作文中1-2段需要改进的文字，给出修改后的版本。

【总体评价】
用2-3句话总结这篇作文的整体水平和提升方向。
"""

        try:
            messages = [
                {"role": "system", "content": f"你是一位资深的{essay_type}阅卷老师，评分严格、点评专业、建议具体。"},
                {"role": "user", "content": prompt},
            ]
            result = await self.ai.chat(messages)
            ai_content = result.get("content", "")

            # 解析评分
            total_score = self._extract_score(ai_content)

            return {
                "title": title,
                "essay_type": essay_type,
                "total_score": total_score,
                "max_score": 100,
                "ai_evaluation": ai_content,
                "graded_at": iso_utc_z(utcnow()),
            }
        except Exception as e:
            return {
                "title": title,
                "essay_type": essay_type,
                "total_score": 0,
                "max_score": 100,
                "ai_evaluation": "",
                "error": str(e),
                "graded_at": iso_utc_z(utcnow()),
            }

    def _extract_score(self, content: str) -> int:
        """从AI输出中提取总分。"""
        match = re.search(r"总分[：:]\s*(\d+)", content)
        if match:
            return int(match.group(1))
        match = re.search(r"(\d+)\s*分\s*[（(]\s*满分", content)
        if match:
            return int(match.group(1))
        return 0
