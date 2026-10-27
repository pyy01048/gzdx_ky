"""P0 缺陷定点回归测试。

为什么单独一个文件
------------------
``tests/test_core.py`` 的 149 个用例全是纯函数级（SM-2 / 艾宾浩斯 / 分页 / 命名转换），
**没有一个真正调用过 routers 层**，所以下面这些在生产环境炸 500 的缺陷一个都没被拦住：

==========================================  ============================================
缺陷                                          表现
==========================================  ============================================
routers/review.py:120 ``datetime.UTC``       /api/review/stats → 500 AttributeError
routers/planner.py:281 naive vs aware        /api/planner/ebbinghaus/due → 500 TypeError
planner.py:482 缺 phase_daily_reviews DDL     /api/planner/phase → 500 OperationalError
routers/exam.py:95 裸 SQL 字符串              /api/exam/blueprints → 500（已修，防回归）
==========================================  ============================================

本文件直接打这些点，且**断言业务语义**（不只断言"不报错"）：
比如蓝图列表必须真的能按 subject 排序、字段齐全；due 计算必须能把
"已过期未打卡"的节点挑出来。

运行
----
    D:/Anaconda/python.exe -m pytest tests/test_regression_p0.py -v
"""
from __future__ import annotations

import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal  # noqa: E402


# --------------------------------------------------------------------------- #
# 一、list_blueprints 返回结构（直接防 exam.py:95 裸 SQL 回归）
# --------------------------------------------------------------------------- #

class TestListBlueprints:

    @pytest.fixture(autouse=True)
    def _blueprints(self, db_schema):  # noqa: ARG002
        """确保 exam_blueprints 表存在且有预置数据（幂等）。"""
        from services.module_a_schema import ensure_blueprints

        db = SessionLocal()
        try:
            ensure_blueprints(db)
        finally:
            db.close()

    def test_returns_200(self, client):
        """/api/exam/blueprints 必须 200。

        历史缺陷：exam.py:95 用裸字符串调 ``db.execute()``，SQLAlchemy 2.x 要求
        显式 ``text()``，否则 ``ArgumentError`` → 500。这条断言直接钉死该修复。
        """
        resp = client.get("/api/exam/blueprints")
        assert resp.status_code == 200, (
            f"蓝图接口 500：status={resp.status_code} body={resp.text[:300]}"
        )

    def test_returns_list_not_error_wrapper(self, client):
        """必须返回 list（前端直接 ``.map``），不能是 {code,message} 错误壳。"""
        data = client.get("/api/exam/blueprints").json()
        assert isinstance(data, list), (
            f"期望 list，实际 {type(data).__name__}: {str(data)[:200]}"
        )

    def test_required_fields_present(self, client):
        """每条蓝图必须含 SQL 里 SELECT 的全部 10 个字段，一个都不能少。

        少字段 → 前端表格出现 undefined → 渲染错乱但不报错，最难查。
        """
        data = client.get("/api/exam/blueprints").json()
        assert data, "预置蓝图未写入，测试前置条件不满足"
        required = {
            "id", "subject", "paper", "year", "section",
            "question_type", "count", "score_per_question",
            "sort_order", "is_active",
        }
        for i, row in enumerate(data):
            missing = required - set(row)
            assert not missing, (
                f"第 {i} 条蓝图缺字段 {missing}；实际字段={sorted(row)}"
            )

    def test_field_types_correct(self, client):
        """字段类型口径：id/count/sort_order/year 为整型，score_per_question 为浮点。"""
        data = client.get("/api/exam/blueprints").json()
        for row in data:
            assert isinstance(row["id"], int), f"id 应为 int，实际 {type(row['id'])}"
            assert isinstance(row["count"], int), f"count 应为 int，实际 {type(row['count'])}"
            assert isinstance(row["sort_order"], int), \
                f"sort_order 应为 int，实际 {type(row['sort_order'])}"
            assert isinstance(row["score_per_question"], (int, float)), \
                f"score_per_question 应为数值，实际 {type(row['score_per_question'])}"
            # section / question_type / subject / paper 是 NOT NULL 的 TEXT
            for f in ("subject", "paper", "section", "question_type"):
                assert isinstance(row[f], str) and row[f], \
                    f"{f} 是 NOT NULL TEXT，实际 {row[f]!r}"

    def test_sorted_by_subject_then_sort_order(self, client):
        """必须按 (subject, sort_order) 排序 —— SQL 里 ORDER BY 的语义。"""
        data = client.get("/api/exam/blueprints").json()
        keys = [(r["subject"], r["sort_order"]) for r in data]
        assert keys == sorted(keys), f"蓝图未按 (subject, sort_order) 排序：{keys}"

    def test_preset_blueprints_present(self, client):
        """预置的 4 科 8 条蓝图必须都在（数学2 / 408 / 政治 / 英语二）。"""
        data = client.get("/api/exam/blueprints").json()
        pairs = {(r["subject"], r["paper"]) for r in data}
        for expected in [
            ("数学", "math2"), ("408", "cs408"),
            ("政治", "politics"), ("英语", "english2"),
        ]:
            assert expected in pairs, f"缺少预置蓝图 {expected}；现有={sorted(pairs)}"

    def test_preset_counts_match_spec(self, client):
        """预置蓝图题量口径（政治 16+17、英语 50）必须正确 —— 组卷依赖它。"""
        data = client.get("/api/exam/blueprints").json()
        by_key = {(r["subject"], r["section"]): r for r in data}
        # 政治：16 单选 ×1 分 + 17 多选 ×2 分 = 50 分
        assert by_key[("政治", "一、单项选择题")]["count"] == 16
        assert by_key[("政治", "一、单项选择题")]["score_per_question"] == 1.0
        assert by_key[("政治", "二、多项选择题")]["count"] == 17
        # 英语：50 题 × 2 分 = 100 分
        assert by_key[("英语", "一、词汇与语法（四选一）")]["count"] == 50
        assert by_key[("英语", "一、词汇与语法（四选一）")]["score_per_question"] == 2.0
        # 408：40 选择 ×2 分 + 7 综合 ×10 分 = 150 分
        assert by_key[("408", "一、单项选择题")]["count"] == 40

    def test_filter_by_subject_after_shape(self, client):
        """形状正确后，才谈得上按科目筛选（前端蓝图页依赖）。"""
        data = client.get("/api/exam/blueprints").json()
        subjects = {r["subject"] for r in data}
        assert "数学" in subjects
        math_rows = [r for r in data if r["subject"] == "数学"]
        assert math_rows, "数学蓝图不应为空"
        assert all(r["paper"] == "math2" for r in math_rows)


# --------------------------------------------------------------------------- #
# 二、planner 艾宾浩斯 / due 计算（防 planner.py:281 时区比较炸 500）
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# 二、planner 艾宾浩斯 / due 计算
#
# 历史缺陷 B（planner.py:281 naive/aware datetime 比较 → 500）已由工程师修复，
# 本类已恢复为**硬红线**（不带 xfail）：一旦回退，立即失败。
# 同理覆盖工程师一并修掉的另一个隐藏 bug：原去重逻辑读 `{field}_done`，
# 而 ebbinghaus_items 表根本没有这些列 → getattr 恒为 None → 已打卡周期
# 反复出现在待复习列表。
# --------------------------------------------------------------------------- #

class TestEbbinghausDueCalculation:

    @staticmethod
    def _due_json(client):
        """取 due 接口 JSON；先断言 200，让失败信息直接指向根因而不是 KeyError。"""
        resp = client.get("/api/planner/ebbinghaus/due")
        assert resp.status_code == 200, (
            f"due 接口 500（planner.py:281 naive/aware 比较）："
            f"status={resp.status_code} body={resp.text[:300]}"
        )
        return resp.json()

    def test_due_endpoint_returns_expected_shape(self, client):
        """/api/planner/ebbinghaus/due 必须返回 {total, items[]} 结构。"""
        data = self._due_json(client)
        assert set(data) >= {"total", "items"}, f"缺字段：{sorted(data)}"
        assert isinstance(data["total"], int)
        assert isinstance(data["items"], list)
        assert data["total"] == len(data["items"]), "total 与 items 长度不一致"

    def test_due_items_have_required_fields(self, client, sample_data):  # noqa: ARG001
        """每条 due 项必须含 id/content/subject/due_cycle/due_time。

        due_cycle 必须是中文标签（前端直接显示），due_time 必须是 ISO 字符串。
        """
        items = self._due_json(client)["items"]
        assert items, "种子数据里有一条已过期未打卡的艾宾浩斯条目，due 不应为空"
        valid_labels = {"5分钟", "30分钟", "12小时", "1天", "2天", "4天", "7天", "15天", "1个月"}
        for item in items:
            assert set(item) >= {"id", "content", "subject", "due_cycle", "due_time"}, \
                f"due 项缺字段：{sorted(item)}"
            assert item["due_cycle"] in valid_labels, \
                f"due_cycle 应为中文标签，实际 {item['due_cycle']!r}"
            assert isinstance(item["due_time"], str) and item["due_time"], \
                f"due_time 应为非空 ISO 字符串，实际 {item['due_time']!r}"
            assert len(item["content"]) <= 100, "content 应被截断到 100 字"

    def test_due_picks_earliest_expired_cycle(self, client):
        """核心算法语义：多个周期都过期时，取**最早**那个（循环里遇到就 break）。

        种子条目里 5min / 30min / 12h / 1d 均已过期 → 必须报 "5分钟"，
        若报成 "1天" 说明 break 位置错了。
        """
        items = self._due_json(client)["items"]
        assert items, "due 列表为空，无法验证周期选择逻辑"
        assert items[0]["due_cycle"] == "5分钟", (
            f"应取最早过期周期 5分钟，实际 {items[0]['due_cycle']}"
        )

    def test_mastered_items_excluded_from_due(self, client, sample_data):  # noqa: ARG001
        """mastered=True 的条目不得出现在 due 里。"""
        db = SessionLocal()
        try:
            item = db.query(_ebbinghaus_model()).first()
            assert item is not None, "种子数据缺失 EbbinghausItem"
            original = item.mastered
            item.mastered = True
            db.commit()
            try:
                items = self._due_json(client)["items"]
                assert not any(i["id"] == item.id for i in items), \
                    "已掌握条目仍出现在 due 列表中"
            finally:
                item.mastered = original
                db.commit()
        finally:
            db.close()

    def test_not_yet_due_cycle_excluded(self, client):
        """未到期的周期不得出现在 due 里（种子条目的 7d 节点是未来时间）。"""
        items = self._due_json(client)["items"]
        assert not any(i["due_cycle"] == "7天" for i in items), \
            "未到期的 7 天周期被误判为到期"

    def test_list_ebbinghaus_shape(self, client):
        """/api/planner/ebbinghaus 列表项字段完整性（含 1d/7d/15d 三个展示位）。"""
        resp = client.get("/api/planner/ebbinghaus")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data, "种子数据应有 1 条艾宾浩斯条目"
        required = {"id", "seq", "learn_date", "content", "subject",
                    "mastered", "review_1d", "review_7d", "review_15d"}
        for row in data:
            missing = required - set(row)
            assert not missing, f"艾宾浩斯列表项缺字段 {missing}；实际={sorted(row)}"

    def test_list_ebbinghaus_date_fields_are_iso_or_none(self, client):
        """日期字段必须是 ISO 字符串或 None，不能是 datetime 对象（否则 JSON 序列化炸）。"""
        for row in client.get("/api/planner/ebbinghaus").json():
            for f in ("learn_date", "review_1d", "review_7d", "review_15d"):
                v = row[f]
                assert v is None or isinstance(v, str), \
                    f"{f} 应为 ISO 字符串或 None，实际 {type(v).__name__}: {v!r}"

    def test_due_time_is_comparable_across_timezones(self, client):
        """回归点：SQLite 读回的 naive datetime 与 aware now 比较会 TypeError。

        这条断言通过 HTTP 层间接覆盖 planner.py:281 —— 只要该行还裸着，
        整个接口就会 500，本用例必然红。
        """
        resp = client.get("/api/planner/ebbinghaus/due")
        assert resp.status_code == 200
        assert "TypeError" not in resp.text
        assert "offset-naive" not in resp.text

    def test_earlybird_streak_consecutive_days(self, client, fresh_earlybird):  # noqa: ARG002
        """连续早起天数：种子里有今天+昨天 → current_streak 应 ≥ 2。"""
        data = client.get("/api/planner/earlybird/streak").json()
        assert set(data) >= {"current_streak", "total_days", "avg_wake_time"}, \
            f"streak 缺字段：{sorted(data)}"
        assert data["current_streak"] >= 2, \
            f"连续天数应 ≥2（今天+昨天），实际 {data['current_streak']}"
        assert data["total_days"] >= 2
        # 平均起床时间口径 06:30 与 07:00 → 06:45
        assert data["avg_wake_time"] == "06:45", \
            f"平均起床时间应为 06:45，实际 {data['avg_wake_time']}"


def _ebbinghaus_model():
    from models import EbbinghausItem

    return EbbinghausItem


# --------------------------------------------------------------------------- #
# 三、review/stats 返回字段完整性（防 review.py:120 datetime.UTC 炸 500）
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# 三、review/stats 返回字段完整性
#
# 历史缺陷 A（review.py:120 `datetime.UTC` → AttributeError → 500）已由工程师修复，
# 本类已恢复为**硬红线**。注意修复里还包含第二个隐患：DB 读回的 next_review /
# created_at 都是 naive，若用 aware 的 now 比较会抛 TypeError ——
# test_due_errors_subset_of_active 等口径断言会一起守住它。
# --------------------------------------------------------------------------- #

class TestReviewStats:

    def test_returns_200(self, client):
        """/api/review/stats 必须 200。

        历史缺陷：review.py:120 ``from datetime import datetime`` 之后写
        ``datetime.UTC`` —— 拿到的是 datetime **类**，类上没有 UTC 属性 →
        AttributeError → 500。
        """
        resp = client.get("/api/review/stats")
        assert resp.status_code == 200, (
            f"review/stats 500（review.py:120 datetime.UTC）："
            f"status={resp.status_code} body={resp.text[:300]}"
        )

    def test_all_five_fields_present(self, client):
        """必须返回全部 5 个统计字段，缺一个前端面板就渲染成 undefined。"""
        data = client.get("/api/review/stats").json()
        required = {
            "active_errors", "due_errors", "graduated_errors",
            "today_reviews", "total_reviews",
        }
        missing = required - set(data)
        assert not missing, (
            f"review/stats 缺字段 {missing}；实际返回={sorted(data)}，body={data}"
        )

    def test_fields_are_non_negative_ints(self, client):
        """计数类字段必须是非负整数（负数说明 SQL 过滤条件写反了）。"""
        data = client.get("/api/review/stats").json()
        for field in ("active_errors", "due_errors", "graduated_errors",
                      "today_reviews", "total_reviews"):
            value = data[field]
            assert isinstance(value, int) and not isinstance(value, bool), \
                f"{field} 应为 int，实际 {type(value).__name__}: {value!r}"
            assert value >= 0, f"{field} 不应为负数：{value}"

    def test_no_error_envelope(self, client):
        """不能返回 {code, message, detail} 错误壳伪装成 200。"""
        data = client.get("/api/review/stats").json()
        assert "code" not in data or data.get("code") != "UNKNOWN_ERROR", \
            f"返回了错误信封：{data}"
        assert "active_errors" in data

    def test_active_errors_matches_db(self, client):
        """统计口径校验：active_errors 必须等于库里 status='active' 的错题数。"""
        from models import ErrorRecord

        db = SessionLocal()
        try:
            expected = db.query(ErrorRecord).filter(
                ErrorRecord.status == "active").count()
        finally:
            db.close()
        assert client.get("/api/review/stats").json()["active_errors"] == expected

    def test_graduated_errors_matches_db(self, client):
        """graduated_errors 口径校验。"""
        from models import ErrorRecord

        db = SessionLocal()
        try:
            expected = db.query(ErrorRecord).filter(
                ErrorRecord.status == "graduated").count()
        finally:
            db.close()
        assert client.get("/api/review/stats").json()["graduated_errors"] == expected

    def test_due_errors_subset_of_active(self, client):
        """业务不变式：到期错题必然是 active 的子集，due <= active。"""
        data = client.get("/api/review/stats").json()
        assert data["due_errors"] <= data["active_errors"], (
            f"due_errors({data['due_errors']}) 不应超过 "
            f"active_errors({data['active_errors']})"
        )

    def test_sibling_review_endpoints_also_ok(self, client):
        """同一 router 的兄弟接口一并守住，避免只修一个。"""
        for path in ("/api/review/due", "/api/review/progress",
                     "/api/review/history", "/api/review/weak-points",
                     "/api/review/link-stats"):
            resp = client.get(path)
            assert resp.status_code == 200, (
                f"{path} → {resp.status_code}，body前200字={resp.text[:200]}"
            )


class TestReviewProgressShape:
    """/api/review/progress 的返回结构（前端复习进度面板依赖）。"""

    def test_top_level_keys(self, client):
        data = client.get("/api/review/progress").json()
        assert isinstance(data, dict), f"期望 dict，实际 {type(data).__name__}"
        assert data, "progress 不应为空对象"

    def test_percentages_are_numbers(self, client):
        """掌握率类百分比必须是数值，且落在 0~100。"""
        data = client.get("/api/review/progress").json()

        def _walk(node, path="$"):
            problems = []
            if isinstance(node, dict):
                for k, v in node.items():
                    problems += _walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node[:20]):
                    problems += _walk(v, f"{path}[{i}]")
            elif isinstance(node, (int, float)) and not isinstance(node, bool):
                leaf = path.rsplit(".", 1)[-1].lower()
                if any(t in leaf for t in ("rate", "pct", "percent", "ratio")):
                    if not (0.0 <= float(node) <= 100.0):
                        problems.append(f"{path}={node} 不在 0~100")
            return problems

        problems = _walk(data)
        assert not problems, "百分比字段越界：" + "; ".join(problems)


# --------------------------------------------------------------------------- #
# 四、planner/phase 缺表缺陷（防 planner.py:482 500）
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# 四、planner/phase 缺表缺陷（planner.py:482 曾 500）
#
# 历史缺陷 C 已由工程师修复：module_a_schema.py:216 补上了
#   CREATE TABLE IF NOT EXISTS phase_daily_reviews (+ 索引 idx_pdr_plan)
# 本类已恢复为**硬红线**（不带 xfail）—— 防止该 DDL 将来被误删。
# 为什么这条特别重要：真实库里该表是历史遗留的，删掉建表语句在
# 「本机继续跑」时完全看不出问题，只有换机/重建库/新部署才会炸。
# 契约测试跑在**空库**上，正是为了暴露这类"本地能跑、换机就崩"的缺陷。
# --------------------------------------------------------------------------- #

class TestPhasePlanSchemaExists:

    def test_phase_daily_reviews_table_is_created(self, db_schema):  # noqa: ARG001
        """phase_daily_reviews 表必须由代码建出来（幂等）。

        缺陷：planner.py:482/485/554/603 直接查这张表，但**全代码库没有任何
        CREATE TABLE**。该表只在 283MB 真实库里历史遗留存在 → 一旦换机/重建库
        （或全新部署），/api/planner/phase 立刻 500 OperationalError。
        """
        from sqlalchemy import text

        db = SessionLocal()
        try:
            names = [
                r[0] for r in db.execute(text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                )).fetchall()
            ]
        finally:
            db.close()
        assert "phase_daily_reviews" in names, (
            "phase_daily_reviews 表未创建 —— planner.py 的阶段复习功能在"
            "空库/新部署环境下必定 500。需要补 CREATE TABLE IF NOT EXISTS DDL。"
        )

    def test_phase_endpoint_ok_on_empty_database(self, client):
        """空库环境下 /api/planner/phase 也必须 200（这是它当前会炸的地方）。"""
        resp = client.get("/api/planner/phase")
        assert resp.status_code == 200, (
            f"phase 接口 500（缺 phase_daily_reviews DDL）："
            f"status={resp.status_code} body={resp.text[:300]}"
        )
        assert isinstance(resp.json(), list)

    def test_phase_reviews_endpoint_ok(self, client, sample_data):  # noqa: ARG001
        """阶段复习明细接口同样不得 500。"""
        plan_id = sample_data["plan_id"]
        resp = client.get(f"/api/planner/phase/{plan_id}/reviews")
        assert resp.status_code == 200, (
            f"phase reviews 500：status={resp.status_code} body={resp.text[:300]}"
        )
