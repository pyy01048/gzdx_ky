# -*- coding: utf-8 -*-
"""
P2-M5 代码上机 OJ 服务层

核心功能:
1. 题目列表/详情查询
2. 代码提交与判题
3. 提交记录查询
4. 统计信息
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.models.code_oj import (
    CodeProblem,
    CodeProblemTestcase,
    CodeSubmission,
    CodeSubmissionResult,
)
from services.code_judge import judge_python_code

logger = logging.getLogger(__name__)


def list_problems(
    db: Session,
    *,
    subject: Optional[str] = None,
    difficulty: Optional[int] = None,
    tag: Optional[str] = None,
    is_public: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """获取编程题目列表。"""
    q = db.query(CodeProblem)
    if is_public:
        q = q.filter(CodeProblem.is_public == True)
    if subject:
        q = q.filter(CodeProblem.subject == subject)
    if difficulty:
        q = q.filter(CodeProblem.difficulty == difficulty)
    # TODO: tag 过滤需要 JOIN code_problem_tags 表

    problems = q.order_by(CodeProblem.id.desc()).offset(offset).limit(limit).all()

    return [
        {
            "id": p.id,
            "title": p.title,
            "subject": p.subject,
            "difficulty": p.difficulty,
            "tags": p.tags,
            "time_limit_ms": p.time_limit_ms,
            "memory_limit_kb": p.memory_limit_kb,
            "testcase_count": len(p.testcases),
        }
        for p in problems
    ]


def get_problem_detail(db: Session, problem_id: int) -> Optional[Dict[str, Any]]:
    """获取题目详情（含样例）。"""
    problem = db.query(CodeProblem).filter(CodeProblem.id == problem_id).first()
    if not problem:
        return None

    # 只返回样例测试点给前端
    sample_testcases = [tc for tc in problem.testcases if tc.is_sample]

    return {
        "id": problem.id,
        "title": problem.title,
        "subject": problem.subject,
        "difficulty": problem.difficulty,
        "description": problem.description,
        "input_format": problem.input_format,
        "output_format": problem.output_format,
        "sample_input": problem.sample_input,
        "sample_output": problem.sample_output,
        "hints": problem.hints,
        "time_limit_ms": problem.time_limit_ms,
        "memory_limit_kb": problem.memory_limit_kb,
        "tags": problem.tags,
        "sample_testcases": [
            {
                "input": tc.input_data,
                "expected_output": tc.expected_output,
            }
            for tc in sample_testcases
        ],
    }


def submit_code(
    db: Session,
    problem_id: int,
    language: str,
    code: str,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """提交代码并异步判题。

    Returns:
        {"submission_id", "status": "pending"}
    """
    # 验证题目存在
    problem = db.query(CodeProblem).filter(CodeProblem.id == problem_id).first()
    if not problem:
        raise ValueError(f"题目不存在: id={problem_id}")

    # 验证语言支持
    supported_languages = ["python", "cpp", "c", "java"]
    if language.lower() not in supported_languages:
        raise ValueError(f"不支持的语言: {language}，支持: {supported_languages}")

    # 创建提交记录
    submission = CodeSubmission(
        problem_id=problem_id,
        user_id=user_id,
        language=language.lower(),
        code=code,
        status="pending",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    # 同步判题（生产环境应改为异步任务队列）
    try:
        result = _judge_submission(db, submission)
        return {
            "submission_id": submission.id,
            "status": result["status"],
            "score": result["score"],
            "passed": result["passed"],
            "total": result["total"],
        }
    except Exception as e:
        logger.error(f"判题失败: submission_id={submission.id}, error={e}", exc_info=True)
        submission.status = "se"
        submission.error_message = f"System Error: {str(e)}"
        db.commit()
        return {
            "submission_id": submission.id,
            "status": "se",
            "error_message": str(e),
        }


def _judge_submission(db: Session, submission: CodeSubmission) -> Dict[str, Any]:
    """执行判题逻辑。"""
    from utils.timeutil import utcnow  # 统一 naive UTC 口径（test_local_clock_guard）

    problem = db.query(CodeProblem).filter(CodeProblem.id == submission.problem_id).first()
    if not problem:
        raise ValueError("题目不存在")

    # 获取所有测试用例
    testcases = (
        db.query(CodeProblemTestcase)
        .filter(CodeProblemTestcase.problem_id == problem.id)
        .order_by(CodeProblemTestcase.sort_order)
        .all()
    )

    if not testcases:
        submission.status = "se"
        submission.error_message = "No testcases found"
        submission.judged_at = utcnow()
        db.commit()
        return {"status": "se", "score": 0, "passed": 0, "total": 0}

    # 准备测试数据
    tc_data = [{"input": tc.input_data, "expected_output": tc.expected_output} for tc in testcases]

    # 执行判题（目前仅支持 Python）
    if submission.language == "python":
        judge_result = judge_python_code(
            submission.code,
            tc_data,
            time_limit_ms=problem.time_limit_ms,
            memory_limit_kb=problem.memory_limit_kb,
        )
    else:
        # 其他语言暂未实现
        judge_result = {
            "status": "ce",
            "passed": 0,
            "total": len(testcases),
            "score": 0.0,
            "details": [],
            "max_time_ms": 0,
            "compile_error": f"Language '{submission.language}' not supported yet",
        }

    # 更新提交记录
    submission.status = judge_result["status"]
    submission.score = judge_result["score"]
    submission.total_testcases = len(testcases)
    submission.passed_testcases = judge_result["passed"]
    submission.max_time_ms = judge_result.get("max_time_ms")
    submission.compile_error = judge_result.get("compile_error")
    submission.error_message = judge_result.get("error_message")
    submission.judged_at = utcnow()
    db.commit()

    # 保存逐测试点结果
    for i, detail in enumerate(judge_result.get("details", [])):
        tc = testcases[i] if i < len(testcases) else None
        result_record = CodeSubmissionResult(
            submission_id=submission.id,
            testcase_id=tc.id if tc else None,
            status=detail["status"],
            time_ms=detail.get("time_ms"),
            memory_kb=detail.get("memory_kb"),
            actual_output=detail.get("actual_output"),
        )
        db.add(result_record)
    db.commit()

    return judge_result


def get_submission_detail(db: Session, submission_id: int) -> Optional[Dict[str, Any]]:
    """获取提交详情（含逐测试点结果）。"""
    submission = db.query(CodeSubmission).filter(CodeSubmission.id == submission_id).first()
    if not submission:
        return None

    results = (
        db.query(CodeSubmissionResult)
        .filter(CodeSubmissionResult.submission_id == submission_id)
        .order_by(CodeSubmissionResult.id)
        .all()
    )

    return {
        "id": submission.id,
        "problem_id": submission.problem_id,
        "language": submission.language,
        "status": submission.status,
        "score": submission.score,
        "total_testcases": submission.total_testcases,
        "passed_testcases": submission.passed_testcases,
        "max_time_ms": submission.max_time_ms,
        "compile_error": submission.compile_error,
        "error_message": submission.error_message,
        "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
        "judged_at": submission.judged_at.isoformat() if submission.judged_at else None,
        "testcase_results": [
            {
                "testcase_id": r.testcase_id,
                "status": r.status,
                "time_ms": r.time_ms,
                "memory_kb": r.memory_kb,
                "actual_output": r.actual_output,
            }
            for r in results
        ],
    }


def get_user_submissions(
    db: Session,
    problem_id: Optional[int] = None,
    user_id: Optional[int] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """获取用户提交记录。"""
    q = db.query(CodeSubmission)
    if problem_id:
        q = q.filter(CodeSubmission.problem_id == problem_id)
    if user_id:
        q = q.filter(CodeSubmission.user_id == user_id)

    submissions = q.order_by(CodeSubmission.submitted_at.desc()).limit(limit).all()

    return [
        {
            "id": s.id,
            "problem_id": s.problem_id,
            "language": s.language,
            "status": s.status,
            "score": s.score,
            "passed_testcases": s.passed_testcases,
            "total_testcases": s.total_testcases,
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        }
        for s in submissions
    ]
