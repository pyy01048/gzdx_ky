"""代码上机 OJ 域模型：题目 / 测试用例 / 提交记录 / 判题结果。

对齐 core/sql/097_code_oj.sql。
"""

from __future__ import annotations

import datetime

from sqlalchemy import REAL, Boolean, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..pg_types import JSONBList
from .base import Base, BigIntKey, BigIntPKMixin, DateTimeUTC


class CodeProblem(BigIntPKMixin, Base):
    """编程题目表。"""

    __tablename__ = "code_problems"

    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="题目标题")
    subject: Mapped[str | None] = mapped_column(String(50), comment="所属科目")
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="2", comment="难度等级 1-5")
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="题目描述（Markdown）")
    input_format: Mapped[str | None] = mapped_column(Text, comment="输入格式说明")
    output_format: Mapped[str | None] = mapped_column(Text, comment="输出格式说明")
    sample_input: Mapped[str | None] = mapped_column(Text, comment="样例输入")
    sample_output: Mapped[str | None] = mapped_column(Text, comment="样例输出")
    hints: Mapped[str | None] = mapped_column(Text, comment="提示")
    time_limit_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1000", comment="时限（毫秒）")
    memory_limit_kb: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="256000", comment="内存限制（KB）"
    )
    tags: Mapped[list | None] = mapped_column(JSONBList, comment="标签数组")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", comment="是否公开")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间"
    )

    testcases: Mapped[list["CodeProblemTestcase"]] = relationship("CodeProblemTestcase", back_populates="problem")
    submissions: Mapped[list["CodeSubmission"]] = relationship("CodeSubmission", back_populates="problem")


class CodeProblemTestcase(BigIntPKMixin, Base):
    """题目测试用例表。"""

    __tablename__ = "code_problem_testcases"

    problem_id: Mapped[int] = mapped_column(
        ForeignKey("code_problems.id", ondelete="CASCADE"), nullable=False, comment="所属题目 ID"
    )
    input_data: Mapped[str] = mapped_column(Text, nullable=False, comment="输入数据")
    expected_output: Mapped[str] = mapped_column(Text, nullable=False, comment="期望输出")
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", comment="是否为样例测试点")
    score_weight: Mapped[float] = mapped_column(REAL, nullable=False, server_default="1.0", comment="该测试点分值权重")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="执行顺序")

    problem: Mapped["CodeProblem | None"] = relationship("CodeProblem", back_populates="testcases")


class CodeSubmission(BigIntPKMixin, Base):
    """代码提交记录表。"""

    __tablename__ = "code_submissions"

    problem_id: Mapped[int] = mapped_column(
        ForeignKey("code_problems.id", ondelete="CASCADE"), nullable=False, comment="题目 ID"
    )
    user_id: Mapped[int | None] = mapped_column(BigIntKey, comment="用户 ID")
    language: Mapped[str] = mapped_column(String(20), nullable=False, comment="编程语言 cpp/python/c/java")
    code: Mapped[str] = mapped_column(Text, nullable=False, comment="提交的代码")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending", comment="判题状态")
    score: Mapped[float] = mapped_column(REAL, nullable=False, server_default="0.0", comment="得分 0-100")
    total_testcases: Mapped[int | None] = mapped_column(Integer, comment="总测试点数")
    passed_testcases: Mapped[int | None] = mapped_column(Integer, comment="通过的测试点数")
    compile_error: Mapped[str | None] = mapped_column(Text, comment="编译错误信息")
    error_message: Mapped[str | None] = mapped_column(Text, comment="运行时错误信息")
    max_time_ms: Mapped[int | None] = mapped_column(Integer, comment="最大运行耗时（毫秒）")
    max_memory_kb: Mapped[int | None] = mapped_column(Integer, comment="峰值内存占用（KB）")
    submitted_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="提交时间"
    )
    judged_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="判题完成时间")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间"
    )

    problem: Mapped["CodeProblem | None"] = relationship("CodeProblem", back_populates="submissions")
    results: Mapped[list["CodeSubmissionResult"]] = relationship("CodeSubmissionResult", back_populates="submission")


class CodeSubmissionResult(BigIntPKMixin, Base):
    """提交逐测试点判题结果。"""

    __tablename__ = "code_submission_results"

    submission_id: Mapped[int] = mapped_column(
        ForeignKey("code_submissions.id", ondelete="CASCADE"), nullable=False, comment="所属提交 ID"
    )
    testcase_id: Mapped[int | None] = mapped_column(
        ForeignKey("code_problem_testcases.id", ondelete="SET NULL"), comment="测试用例 ID"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, comment="该测试点状态 ac/wa/tle/mle/re")
    time_ms: Mapped[int | None] = mapped_column(Integer, comment="该测试点耗时（毫秒）")
    memory_kb: Mapped[int | None] = mapped_column(Integer, comment="该测试点内存（KB）")
    actual_output: Mapped[str | None] = mapped_column(Text, comment="实际输出（WA 时用于对比）")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间"
    )

    submission: Mapped["CodeSubmission | None"] = relationship("CodeSubmission", back_populates="results")


class CodeTag(Base):
    """OJ 题目标签字典。"""

    __tablename__ = "code_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="标签名称")
    category: Mapped[str | None] = mapped_column(String(50), comment="标签分类")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间"
    )


class CodeProblemTag(Base):
    """题目-标签多对多关联。"""

    __tablename__ = "code_problem_tags"

    problem_id: Mapped[int] = mapped_column(
        ForeignKey("code_problems.id", ondelete="CASCADE"), primary_key=True, comment="题目 ID"
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("code_tags.id", ondelete="CASCADE"), primary_key=True, comment="标签 ID"
    )
