"""
核心逻辑单元测试
- SM-2 间隔重复算法
- FTS 查询预处理
- 分页响应工具
- 字段命名转换

运行方式：pytest tests/ -v
"""
import os
import sys
import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from services.review_scheduler import ReviewScheduler
from utils.response import (
    MAX_PAGE_SIZE,
    PaginatedResponse,
    page_params,
    paginate_query,
    stamp_utc_z,
    to_utc_z,
)


# --------------------------------------------------------------------------- #
# SM-2 算法测试
# --------------------------------------------------------------------------- #

class TestSM2Algorithm:
    """SM-2 间隔重复算法测试"""

    def test_first_review_good(self):
        """第一次复习，回答好（quality=4）"""
        next_review, reps, interval, ef, mastery = ReviewScheduler.calculate_next_review(
            quality=4, repetitions=0, interval=0, ef=2.5
        )
        assert reps == 1
        assert interval == 1
        assert ef >= 2.5  # 回答好，EF 应增加或不变
        assert mastery in ["review", "learning"]

    def test_first_review_bad(self):
        """第一次复习，回答差（quality=2）"""
        next_review, reps, interval, ef, mastery = ReviewScheduler.calculate_next_review(
            quality=2, repetitions=0, interval=0, ef=2.5
        )
        assert reps == 0  # 答错，重置
        assert interval == 1
        assert mastery == "learning"

    def test_second_review_good(self):
        """第二次复习，回答好"""
        next_review, reps, interval, ef, mastery = ReviewScheduler.calculate_next_review(
            quality=4, repetitions=1, interval=1, ef=2.5
        )
        assert reps == 2
        assert interval == 6  # 第二次复习间隔为 6 天

    def test_third_review_good(self):
        """第三次复习，回答好，间隔 = 上次间隔 * EF"""
        next_review, reps, interval, ef, mastery = ReviewScheduler.calculate_next_review(
            quality=4, repetitions=2, interval=6, ef=2.5
        )
        assert reps == 3
        assert interval == round(6 * 2.5)  # 15 天

    def test_ef_minimum(self):
        """EF 不低于 1.3"""
        next_review, reps, interval, ef, mastery = ReviewScheduler.calculate_next_review(
            quality=0, repetitions=5, interval=30, ef=1.5
        )
        assert ef >= 1.3

    def test_mastered_after_many_reviews(self):
        """多次复习后达到 mastered 状态"""
        next_review, reps, interval, ef, mastery = ReviewScheduler.calculate_next_review(
            quality=5, repetitions=5, interval=15, ef=2.5
        )
        assert reps >= 5
        assert interval >= 15
        assert mastery == "mastered"

    def test_next_review_is_future(self):
        """下次复习时间应在未来"""
        next_review, reps, interval, ef, mastery = ReviewScheduler.calculate_next_review(
            quality=4, repetitions=0, interval=0, ef=2.5
        )
        # P0-4：复习调度器返回 naive UTC（与 DB 的 DateTime 列同语义），
        # 不能与 aware 的 datetime.UTC 比较，否则 TypeError。
        assert next_review > datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# 艾宾浩斯算法测试
# --------------------------------------------------------------------------- #

class TestEbinghaus:
    """艾宾浩斯复习曲线测试"""

    def test_first_review_interval(self):
        """第一次复习间隔 20 分钟"""
        result = ReviewScheduler.ebinghaus_next_review(0)
        assert result is not None
        expected = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                    + datetime.timedelta(minutes=20))
        assert abs((result - expected).total_seconds()) < 5

    def test_last_interval(self):
        """超过最大间隔后，30 天后复习"""
        result = ReviewScheduler.ebinghaus_next_review(100)
        expected = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                    + datetime.timedelta(days=30))
        assert abs((result - expected).total_seconds()) < 5


# --------------------------------------------------------------------------- #
# 新错题首入库排程测试（V12 同族修复）
#
# 历史缺陷：三个错题入口（手动收录 / 刷题判错 / 模考回流）一律用
# ebinghaus_next_review(0)（20 分钟后）给新错题排程 → 新错题入册当天
# 全部涌进"今日复习队列"，整本错题本调度失真（与单词侧
# "4568/4569 今日待复习"同族）。修复：first_review_at 按掌握度给
# ≥1 天的首间隔，新内容不当日到期。
# --------------------------------------------------------------------------- #

class TestErrorFirstReview:
    """ReviewScheduler.first_review_at：新错题首次复习排程。"""

    @staticmethod
    def _now():
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    def _assert_days_later(self, accuracy, days):
        result = ReviewScheduler.first_review_at(accuracy)
        expected = self._now() + datetime.timedelta(days=days)
        assert abs((result - expected).total_seconds()) < 5, (
            f"accuracy={accuracy!r} 应排在 {days} 天后，实际 {result}")

    def test_unknown_mastery_one_day(self):
        """未评估（None/0）→ SM-2 标准首间隔 1 天，不当日到期。"""
        self._assert_days_later(None, 1)
        self._assert_days_later(0.0, 1)

    def test_low_mastery_one_day(self):
        """accuracy < 0.5（没掌握）→ 1 天。"""
        self._assert_days_later(0.3, 1)
        self._assert_days_later(0.49, 1)

    def test_mid_mastery_two_days(self):
        """0.5 ≤ accuracy < 0.8（半会）→ 2 天。"""
        self._assert_days_later(0.5, 2)
        self._assert_days_later(0.79, 2)

    def test_high_mastery_three_days(self):
        """accuracy ≥ 0.8（眼会手错）→ 3 天。"""
        self._assert_days_later(0.8, 3)
        self._assert_days_later(1.0, 3)

    def test_garbage_accuracy_falls_back_to_one_day(self):
        """脏数据 accuracy 不能炸，回落 1 天。"""
        self._assert_days_later("abc", 1)
        self._assert_days_later([1], 1)

    def test_never_due_today(self):
        """不变式：首排程必须严格大于当前时刻——新错题不进今日队列。"""
        now = self._now()
        for acc in (None, 0.0, 0.5, 0.8, 1.0):
            assert ReviewScheduler.first_review_at(acc) > now


class TestErrorCreationSchedulesFirstReview:
    """错题创建入口的首排程（API 级，V12 同族修复）。"""

    def test_manual_add_schedules_first_review(self, client, db_schema):
        """POST /api/errors：新错题 next_review 必须在 ~1 天后，不是 20 分钟后。"""
        r = client.post("/api/errors", json={
            "content": "首排程测试题", "correct_answer": "B",
            "subject": "数学", "status": "active",
        })
        assert r.status_code == 200, r.text
        from database import SessionLocal
        from models import ErrorRecord

        db = SessionLocal()
        try:
            err = db.query(ErrorRecord).filter(
                ErrorRecord.content == "首排程测试题").order_by(ErrorRecord.id.desc()).first()
            assert err is not None and err.next_review is not None
            now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            # DB 列是 TIMESTAMPTZ，psycopg 回读为 **aware** datetime；项目内部
            # 统一用 naive UTC（utils.timeutil.utcnow，P0-4 规范）。比较前先归一，
            # 否则 naive 与 aware 相减直接 TypeError（实测）。
            nr = err.next_review
            if nr.tzinfo is not None:
                nr = nr.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            delta_days = (nr - now).total_seconds() / 86400
            assert 0.9 <= delta_days <= 1.1, (
                f"新错题首间隔应约 1 天，实际 {delta_days:.3f} 天")
        finally:
            db.close()

    def test_quiz_wrong_answer_schedules_first_review(self, client, db_schema):
        """POST /api/quiz/submit 答错自动入册：next_review ~1 天后。"""
        from database import SessionLocal
        from models import ErrorRecord, QuizQuestion

        db = SessionLocal()
        try:
            # 选项用**正典格式** [{key,text}]：DB 约束 ck_quiz_questions_options
            # （is_canonical_options）只认该格式，字符串数组会被拒绝——
            # 这是刻意的严格契约，导入侧的规整由 services.content_sanitizer 统一负责。
            q = QuizQuestion(
                content="首排程刷题测试题",
                options=[{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
                answer="B", subject="数学", question_type="single",
            )
            db.add(q)
            db.commit()
            qid = q.id
        finally:
            db.close()

        r = client.post("/api/quiz/submit", json={
            "question_id": qid, "my_answer": "A", "mode": "practice"})
        assert r.status_code == 200, r.text

        db = SessionLocal()
        try:
            err = db.query(ErrorRecord).filter(
                ErrorRecord.question_id == qid).order_by(ErrorRecord.id.desc()).first()
            assert err is not None and err.next_review is not None
            now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            # DB 列是 TIMESTAMPTZ，psycopg 回读为 **aware** datetime；项目内部
            # 统一用 naive UTC（utils.timeutil.utcnow，P0-4 规范）。比较前先归一，
            # 否则 naive 与 aware 相减直接 TypeError（实测）。
            nr = err.next_review
            if nr.tzinfo is not None:
                nr = nr.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            delta_days = (nr - now).total_seconds() / 86400
            assert 0.9 <= delta_days <= 1.1, (
                f"刷题新错题首间隔应约 1 天，实际 {delta_days:.3f} 天")
        finally:
            db.close()


# --------------------------------------------------------------------------- #
# 分页响应测试
# --------------------------------------------------------------------------- #

class TestPaginatedResponse:
    """分页响应工具测试"""

    def test_basic_pagination(self):
        """基本分页"""
        items = [1, 2, 3, 4, 5]
        resp = PaginatedResponse(items=items, total=100, page=2, page_size=10)
        assert resp.items == items
        assert resp.total == 100
        assert resp.page == 2
        assert resp.page_size == 10
        assert resp.total_pages == 10

    def test_total_pages_calculation(self):
        """总页数计算"""
        assert PaginatedResponse(items=[], total=0, page=1, page_size=10).total_pages == 0
        assert PaginatedResponse(items=[], total=1, page=1, page_size=10).total_pages == 1
        assert PaginatedResponse(items=[], total=10, page=1, page_size=10).total_pages == 1
        assert PaginatedResponse(items=[], total=11, page=1, page_size=10).total_pages == 2

    def test_dict_output(self):
        """字典输出格式"""
        resp = PaginatedResponse(items=[1, 2], total=50, page=1, page_size=20)
        d = resp.dict()
        assert "items" in d
        assert "total" in d
        assert "page" in d
        assert "page_size" in d
        assert "total_pages" in d


# --------------------------------------------------------------------------- #
# 响应约定：时间格式（#19）
# --------------------------------------------------------------------------- #

class TestUtcZTimeFormat:
    """naive UTC 串补 ``Z`` —— 不补，前端 ``new Date()`` 会按本地时间解析，
    北京用户看什么时间都早 8 小时。"""

    @pytest.mark.parametrize("value", [
        "2026-10-16T16:00:00",
        "2026-10-16T16:00:00.123456",
        "2026-10-16T16:00",
    ])
    def test_naive_iso_gets_z(self, value):
        assert to_utc_z(value) == value + "Z"

    @pytest.mark.parametrize("value", [
        "2026-10-16T16:00:00Z",
        "2026-10-16T16:00:00+08:00",
        "2026-10-16T16:00:00-05:00",
        "2026-10-16",               # 纯日期：本来就不该带时区
        "2026-10-16 16:00:00",      # 展示串：补 Z 等于谎报它是 UTC
        "T16:00:00",
        "not-a-date",
        "",
    ])
    def test_other_shapes_untouched(self, value):
        assert to_utc_z(value) == value

    def test_stamp_is_recursive_and_only_touches_values(self):
        stamped = stamp_utc_z({
            "created_at": "2026-10-16T16:00:00",
            "day": "2026-10-16",
            "items": ["2026-10-16T16:00:00", 5, None, {"last_review": "2026-10-16T16:00:00"}],
            "count": 3,
        })
        assert stamped["created_at"] == "2026-10-16T16:00:00Z"
        assert stamped["day"] == "2026-10-16"
        assert stamped["items"][0] == "2026-10-16T16:00:00Z"
        assert stamped["items"][3]["last_review"] == "2026-10-16T16:00:00Z"
        # 键名一律不动（snake_case 约定，不做 camel 转换）
        assert set(stamped) == {"created_at", "day", "items", "count"}

    def test_stamp_leaves_scalar_and_none_alone(self):
        assert stamp_utc_z(5) == 5
        assert stamp_utc_z(None) is None


# --------------------------------------------------------------------------- #
# 响应约定：分页（#19）
# --------------------------------------------------------------------------- #

class _FakeQuery:
    """只实现 paginate_query 用到的那段 Query API。"""

    def __init__(self, rows):
        self.rows = rows
        self.offset_value = 0
        self.limit_value = None

    def count(self):
        return len(self.rows)

    def offset(self, n):
        self.offset_value = n
        return self

    def limit(self, n):
        self.limit_value = n
        return self

    def all(self):
        end = None if self.limit_value is None else self.offset_value + self.limit_value
        return self.rows[self.offset_value:end]


class TestPageParamsAndPaginate:

    def test_page_params_carry_offset_and_limit(self):
        assert page_params(page=3, page_size=50) == {
            "page": 3, "page_size": 50, "offset": 100, "limit": 50,
        }

    def test_page_size_cap_applies(self):
        """>200 的页长会被收敛，不能由调用方决定拉多少行。"""
        rows = list(range(1000))
        resp = paginate_query(_FakeQuery(rows), page=1, page_size=100000)
        assert resp.page_size == MAX_PAGE_SIZE
        assert len(resp.items) == MAX_PAGE_SIZE

    def test_illegal_page_clamped_to_first(self):
        resp = paginate_query(_FakeQuery([1, 2, 3]), page=0, page_size=2)
        assert (resp.page, resp.items, resp.total_pages) == (1, [1, 2], 2)

    def test_serialize_hook_runs_per_row(self):
        """paginate_query 交出的必须是可 JSON 化的行；serialize 就是把这层责任
        显式化（老实现直接把 ORM 对象塞进 items，渲染时才炸）。"""
        resp = paginate_query(_FakeQuery([1, 2]), page=1, page_size=10, serialize=lambda r: {"n": r})
        assert resp.dict() == {
            "items": [{"n": 1}, {"n": 2}], "total": 2,
            "page": 1, "page_size": 10, "total_pages": 1,
        }

    def test_offset_window(self):
        resp = paginate_query(_FakeQuery(list(range(10))), page=3, page_size=4)
        assert resp.items == [8, 9]
        assert resp.total_pages == 3


# --------------------------------------------------------------------------- #
# FTS 查询预处理测试
# --------------------------------------------------------------------------- #

class TestFTSQuery:
    """FTS 查询预处理测试"""

    def test_empty_query(self):
        """空查询返回空字符串"""
        from services.search_service import _fts_query
        result = _fts_query("")
        assert result == '""'

    def test_single_word(self):
        """单个词"""
        from services.search_service import _fts_query
        result = _fts_query("数学")
        assert '"数学"' in result

    def test_multiple_words(self):
        """多个词用 OR 连接"""
        from services.search_service import _fts_query
        result = _fts_query("数学 英语")
        assert "OR" in result
        assert '"数学"' in result
        assert '"英语"' in result

    def test_special_chars_removed(self):
        """特殊控制字符被移除"""
        from services.search_service import _fts_query
        result = _fts_query("test\x00query")
        assert "\x00" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
