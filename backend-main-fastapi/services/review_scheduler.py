"""艾宾浩斯/SM-2 复习调度算法。"""

import datetime
import logging
from types import SimpleNamespace
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session
from utils.scope import scoped
from utils.timeutil import utcnow  # 统一 naive UTC 时间规范（P0-4）

from models import ErrorRecord, Flashcard, Task

logger = logging.getLogger(__name__)


def _scoped_uid(model, user_id: Optional[int]):
    """B4：user_id 形式的行级过滤（复用 scoped()，开关 off / user_id 空 → 恒真）。"""
    return scoped(model, SimpleNamespace(id=user_id))


class ReviewScheduler:
    """艾宾浩斯/SM-2 复习调度器。"""

    # 艾宾浩斯复习间隔（分钟）
    EBINGHAUS_INTERVALS = [
        20,  # 20 分钟后
        60,  # 1 小时后
        9 * 60,  # 9 小时后
        24 * 60,  # 1 天后
        2 * 24 * 60,  # 2 天后
        5 * 24 * 60,  # 5 天后
        8 * 24 * 60,  # 8 天后
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

        # ── S1 kernel 影子/切流钩子（附加式；任何异常降级 legacy）──
        # KAOYAN_FSRS_SHADOW=1（默认）：只记 SM-2 vs FSRS 差异日志，行为不变；
        # KAOYAN_FSRS_ENGINE=kernel：切流，返回 kernel 建议（影子期验证后才开）。
        try:
            from services import kernel_bridge

            alt = kernel_bridge.fsrs_alternative(quality, repetitions, interval, ef, now=utcnow())
            if alt is not None:
                kernel_tuple, meta = alt
                if kernel_bridge.fsrs_engine() == "kernel":
                    return kernel_tuple
                if kernel_bridge.fsrs_shadow():
                    logger.info(
                        "FSRS_SHADOW q=%s legacy_interval=%s kernel_interval=%s diff_days=%s meta=%s",
                        quality,
                        new_interval,
                        kernel_tuple[2],
                        kernel_tuple[2] - new_interval,
                        meta,
                    )
        except Exception as exc:  # noqa: BLE001 - 红线：影子钩子绝不炸主链
            logger.warning("FSRS 影子钩子降级 legacy: %s", exc)

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
    def first_review_at(accuracy: Optional[float] = None) -> datetime.datetime:
        """新错题首入库的首次复习排程（naive UTC）。

        修复背景（与单词 V12 修复同族的错题侧缺口）：
            旧逻辑对三个错题入口（手动收录 / 刷题判错 / 模考回流）一律用
            ``ebinghaus_next_review(0)`` 排程——20 分钟后即"今日到期"。
            后果：新错题入册当天全部涌入"今日复习队列"，整本错题本失真
            （症状与单词侧"4568/4569 今日待复习"完全同族）。
            单词/卡片侧的口径是：新内容不进当日 due 队列，首间隔至少 1 天。

        按掌握度（accuracy，0-1）给合理的首次复习间隔：
            accuracy 缺失或 < 0.5（没掌握/未评估）→ 1 天后（SM-2 标准首间隔）
            0.5 ≤ accuracy < 0.8（半会）           → 2 天后
            accuracy ≥ 0.8（眼会手错）             → 3 天后
        """
        try:
            acc = float(accuracy) if accuracy is not None else None
        except (TypeError, ValueError):
            acc = None
        if acc is None or acc < 0.5:
            days = 1
        elif acc < 0.8:
            days = 2
        else:
            days = 3
        return utcnow() + datetime.timedelta(days=days)  # naive UTC（P0-4）

    @staticmethod
    def get_due_flashcards(db: Session, limit: int = 100, *, user_id: Optional[int] = None) -> List[Flashcard]:
        """获取今日待复习卡片（B4：user_id 提供时只看本人卡片）。"""
        now = utcnow()  # naive UTC，与 DB 列比较（P0-4）
        # V12 修复：next_review 为 NULL 的卡片是"新卡"（从未学习），不计入今日待复习。
        # 旧逻辑把 NULL 全算到期 → 500/500 卡全部"今日待复习"，调度失真。
        return (
            db.query(Flashcard)
            .filter(
                (Flashcard.next_review != None),  # noqa: E711 - SQLAlchemy IS NOT NULL 惯用
                (Flashcard.next_review <= now),
                _scoped_uid(Flashcard, user_id),
            )
            .order_by(Flashcard.next_review.asc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_due_tasks(db: Session, limit: int = 100, *, user_id: Optional[int] = None) -> List[Task]:
        """获取今日待复习任务（B4：user_id 提供时只看本人任务）。"""
        now = utcnow()  # naive UTC，与 DB 列比较（P0-4）
        return (
            db.query(Task)
            .filter(
                (Task.next_review != None),  # noqa: E711 - SQLAlchemy IS NOT NULL 惯用
                (Task.next_review <= now),
                (Task.status != "done"),
                _scoped_uid(Task, user_id),
            )
            .order_by(Task.next_review.asc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_due_errors(db: Session, limit: int = 100, *, user_id: Optional[int] = None) -> List[ErrorRecord]:
        """获取今日待复习错题（B4：user_id 提供时只看本人错题）。"""
        now = utcnow()  # naive UTC，与 DB 列比较（P0-4）
        return (
            db.query(ErrorRecord)
            .filter(
                (ErrorRecord.next_review != None),  # noqa: E711 - SQLAlchemy IS NOT NULL 惯用
                (ErrorRecord.next_review <= now),
                (ErrorRecord.status == "active"),
                _scoped_uid(ErrorRecord, user_id),
            )
            .order_by(ErrorRecord.next_review.asc())
            .limit(limit)
            .all()
        )
