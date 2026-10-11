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
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from models import ErrorRecord, AnswerRecord, Task, Document, KnowledgeChunk, KnowledgePoint
from services.ai_service import AIService


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

        Returns:
            {
                "total_questions": int,
                "correct_rate": float,
                "weak_points": [
                    {"knowledge_point": str, "error_count": int, "correct_count": int,
                     "mastery": float, "level": "薄弱"/"一般"/"良好", "suggestion": str}
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

        # 薄弱考点分析（基于错题题目中的关键词）
        weak_points = self._extract_weak_points(errors, limit)

        return {
            "total_questions": total_answers,
            "correct_answers": correct_answers,
            "correct_rate": correct_rate,
            "total_errors": len(errors),
            "weak_points": weak_points,
            "error_categories": error_categories,
            "subject_distribution": subject_dist,
            "diagnosis_time": datetime.now().isoformat(),
        }

    def _extract_weak_points(self, errors: List[ErrorRecord], limit: int) -> List[Dict[str, Any]]:
        """从错题中提取薄弱考点关键词。"""
        # 简单的关键词提取（后续可升级为AI聚类）
        keyword_count = {}
        keyword_errors = {}

        for e in errors:
            text = (e.content or "") + " " + (e.analysis or "")
            # 提取常见考点关键词
            keywords = re.findall(r"[\u4e00-\u9fa5]{2,6}(?:定理|公式|法则|性质|概念|定理|函数|方程|积分|导数|矩阵|向量|概率|语法|词汇|阅读|写作|电路|信号|系统|逻辑|触发器|寄存器|计数器|放大|滤波|调制)", text)
            for kw in keywords:
                keyword_count[kw] = keyword_count.get(kw, 0) + 1
                if kw not in keyword_errors:
                    keyword_errors[kw] = []
                keyword_errors[kw].append(e.id)

        # 排序并生成结果
        sorted_kw = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)[:limit]
        result = []
        for kw, count in sorted_kw:
            # 估算掌握度（错误次数越多，掌握度越低）
            mastery = max(10, 100 - count * 15)
            if mastery < 40:
                level = "薄弱"
                suggestion = f"「{kw}」错误较多，建议重点复习相关概念和公式，多做练习题巩固。"
            elif mastery < 70:
                level = "一般"
                suggestion = f"「{kw}」掌握一般，建议定期复习，适当增加练习量。"
            else:
                level = "良好"
                suggestion = f"「{kw}」掌握较好，可适当减少复习频率。"

            result.append({
                "knowledge_point": kw,
                "error_count": count,
                "error_ids": keyword_errors.get(kw, [])[:5],
                "mastery": mastery,
                "level": level,
                "suggestion": suggestion,
            })

        return result

    # ------------------------------------------------------------------
    # 学习轨迹
    # ------------------------------------------------------------------
    def get_learning_traces(self, days: int = 30) -> Dict[str, Any]:
        """获取最近N天的学习轨迹数据。

        Returns:
            {
                "days": int,
                "total_study_days": int,
                "current_streak": int,
                "longest_streak": int,
                "daily_data": [
                    {"date": "2026-08-01", "tasks_completed": int, "questions_done": int,
                     "errors_added": int, "study_duration_minutes": int}
                ],
                "weekly_summary": {...},
                "subject_heatmap": {...},
            }
        """
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days - 1)

        daily_data = []
        study_dates = set()

        for i in range(days):
            date = start_date + timedelta(days=i)
            date_str = date.isoformat()
            next_date = date + timedelta(days=1)

            # 统计当日完成的任务
            tasks_completed = self.db.query(Task).filter(
                Task.status == "done",
                Task.updated_at >= date_str,
                Task.updated_at < next_date.isoformat(),
            ).count()

            # 统计当日答题数
            questions_done = self.db.query(AnswerRecord).filter(
                AnswerRecord.created_at >= date_str,
                AnswerRecord.created_at < next_date.isoformat(),
            ).count()

            # 统计当日新增错题
            errors_added = self.db.query(ErrorRecord).filter(
                ErrorRecord.created_at >= date_str,
                ErrorRecord.created_at < next_date.isoformat(),
            ).count()

            # 估算学习时长（每个任务30分钟，每道题5分钟）
            study_minutes = tasks_completed * 30 + questions_done * 5

            if tasks_completed > 0 or questions_done > 0 or errors_added > 0:
                study_dates.add(date_str)

            daily_data.append({
                "date": date_str,
                "tasks_completed": tasks_completed,
                "questions_done": questions_done,
                "errors_added": errors_added,
                "study_duration_minutes": study_minutes,
            })

        # 计算连续学习天数
        current_streak = 0
        for d in reversed(daily_data):
            if d["tasks_completed"] > 0 or d["questions_done"] > 0:
                current_streak += 1
            else:
                break

        # 最长连续天数
        longest_streak = 0
        temp_streak = 0
        for d in daily_data:
            if d["tasks_completed"] > 0 or d["questions_done"] > 0:
                temp_streak += 1
                longest_streak = max(longest_streak, temp_streak)
            else:
                temp_streak = 0

        # 周汇总
        weekly_summary = self._calc_weekly_summary(daily_data)

        return {
            "days": days,
            "date_range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "total_study_days": len(study_dates),
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "total_tasks_completed": sum(d["tasks_completed"] for d in daily_data),
            "total_questions_done": sum(d["questions_done"] for d in daily_data),
            "total_study_minutes": sum(d["study_duration_minutes"] for d in daily_data),
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
学习时长：约{traces['total_study_minutes']}分钟
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
            "generated_at": datetime.now().isoformat(),
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
                "graded_at": datetime.now().isoformat(),
            }
        except Exception as e:
            return {
                "title": title,
                "essay_type": essay_type,
                "total_score": 0,
                "max_score": 100,
                "ai_evaluation": "",
                "error": str(e),
                "graded_at": datetime.now().isoformat(),
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
