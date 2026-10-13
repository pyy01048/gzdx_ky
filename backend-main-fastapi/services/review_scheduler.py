"""艾宾浩斯/SM-2 复习调度算法。"""

import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from models import Flashcard, Task, ErrorRecord
from utils.timeutil import utcnow  # 统一 naive UTC 时间规范（P0-4）


class ReviewScheduler:
    """艾宾浩斯/SM-2 复习调度器。"""

    # 艾宾浩斯复习间隔（分钟）
    EBINGHAUS_INTERVALS = [
        20,            # 20 分钟后
        60,            # 1 小时后
        9 * 60,        # 9 小时后
        24 * 60,       # 1 天后
        2 * 24 * 60,   # 2 天后
        5 * 24 * 60,   # 5 天后
        8 * 24 * 60,   # 8 天后
        15 * 24 * 60,  # 15 天后
    ]

    @staticmethod
    def calculate_next_review(
        quality: int,
        repetitions: int,
        interval: int,
        ef: float,
    ) -> Tuple[datetime.datetime, int, int, float, str]:
        """SM-2 算法计算下次复习时间。

        :param quality: 回答质量评分 0-5
        :param repetitions: 已复习次数
        :param interval: 当前间隔（天）
        :param ef: 难度因子
        :return: (next_review, new_repetitions, new_interval, new_ef, mastery)
        """
        if quality < 3:
            # 答错，重置
            new_repetitions = 0
            new_interval = 1
        else:
            new_repetitions = repetitions + 1
            if new_repetitions == 1:
                new_interval = 1
            elif new_repetitions == 2:
                new_interval = 6
            else:
                new_interval = round(interval * ef)

        # 更新难度因子
        new_ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        if new_ef < 1.3:
            new_ef = 1.3

        next_review = utcnow() + datetime.timedelta(days=new_interval)  # naive UTC（P0-4）

        # 掌握状态
        if quality < 3:
            mastery = "learning"
        elif new_repetitions >= 5 and new_interval >= 15:
            mastery = "mastered"
        elif new_repetitions >= 1:
            mastery = "review"
        else:
            mastery = "new"

        return next_review, new_repetitions, new_interval, new_ef, mastery

    @staticmethod
    def ebinghaus_next_review(review_count: int) -> Optional[datetime.datetime]:
        """根据艾宾浩斯曲线计算下次复习时间。"""
        if review_count < len(ReviewScheduler.EBINGHAUS_INTERVALS):
            minutes = ReviewScheduler.EBINGHAUS_INTERVALS[review_count]
            return utcnow() + datetime.timedelta(minutes=minutes)  # naive UTC（P0-4）
        # 超过最大间隔，30 天后复习
        return utcnow() + datetime.timedelta(days=30)  # naive UTC（P0-4）

    @staticmethod
    def get_due_flashcards(db: Session, limit: int = 100) -> List[Flashcard]:
        """获取今日待复习卡片。"""
        now = utcnow()  # naive UTC，与 DB 列比较（P0-4）
        # V12 修复：next_review 为 NULL 的卡片是"新卡"（从未学习），不计入今日待复习。
        # 旧逻辑把 NULL 全算到期 → 500/500 卡全部"今日待复习"，调度失真。
        return (
            db.query(Flashcard)
            .filter(
                (Flashcard.next_review != None),
                (Flashcard.next_review <= now),
            )
            .order_by(Flashcard.next_review.asc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_due_tasks(db: Session, limit: int = 100) -> List[Task]:
        """获取今日待复习任务。"""
        now = utcnow()  # naive UTC，与 DB 列比较（P0-4）
        return (
            db.query(Task)
            .filter(
                (Task.next_review != None),
                (Task.next_review <= now),
                (Task.status != "done"),
            )
            .order_by(Task.next_review.asc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_due_errors(db: Session, limit: int = 100) -> List[ErrorRecord]:
        """获取今日待复习错题。"""
        now = utcnow()  # naive UTC，与 DB 列比较（P0-4）
        return (
            db.query(ErrorRecord)
            .filter(
                (ErrorRecord.next_review != None),
                (ErrorRecord.next_review <= now),
                (ErrorRecord.status == "active"),
            )
            .order_by(ErrorRecord.next_review.asc())
            .limit(limit)
            .all()
        )
