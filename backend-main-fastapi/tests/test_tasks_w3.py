# -*- coding: utf-8 -*-
"""W3 任务体验重做后端侧测试（多科目/循环/按日打卡/日历/模块字典/进度条）。

口径权威源：services/task_recurrence.py + routers/study/tasks.py。
迁移分片：core/sql/126_tasks_w3.sql（测试库走 ORM create_all，列/表同名同型）。
"""

import datetime
import uuid

import pytest


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def make_task(client):
    """创建任务并返回 id；用例负责用唯一标题避免互相干扰。"""

    def _make(**payload):
        body = {"title": _uniq("w3")}
        body.update(payload)
        r = client.post("/api/tasks", json=body)
        assert r.status_code == 200, r.text
        return r.json()["id"]

    return _make


class TestTaskW3Fields:
    def test_create_with_all_new_fields_and_list_back(self, client, make_task):
        tid = make_task(
            subject="英语",
            subjects=["英语", "数学"],
            modules=["真题", "单词"],
            start_date="2026-11-01",
            end_date="2026-11-30",
            recurrence={"freq": "workdays"},
            remind={"type": "point", "time": "08:30"},
            show_progress=True,
            progress_total=100,
        )
        items = client.get("/api/tasks", params={"page_size": 200}).json()["items"]
        t = next(x for x in items if x["id"] == tid)
        assert t["subjects"] == ["英语", "数学"]
        assert t["subject"] == "英语"  # 兼容列 = 首元素
        assert t["modules"] == ["真题", "单词"]
        assert t["start_date"] == "2026-11-01" and t["end_date"] == "2026-11-30"
        assert t["recurrence"]["freq"] == "workdays"
        assert t["remind"] == {"type": "point", "time": "08:30"}
        assert t["show_progress"] is True and t["progress_total"] == 100
        assert t["is_recurring"] is True

    def test_invalid_inputs_are_rejected_not_swallowed(self, client):
        bad_cases = [
            ({"recurrence": {"freq": "yearly"}, "start_date": "2026-11-01"}, "循环"),
            ({"remind": {"type": "point", "time": "25:99"}}, "提醒"),
            ({"remind": {"type": "range", "start": "09:00", "end": "08:00"}}, "早于"),
            ({"recurrence": {"freq": "daily"}}, "锚点"),  # 无任何日期锚点 → 日历展不出，宁缺不假
            ({"show_progress": True}, "progress_total"),
            ({"start_date": "2026-11-10", "end_date": "2026-11-01"}, "结束日期"),
        ]
        for payload, keyword in bad_cases:
            r = client.post("/api/tasks", json={"title": _uniq("w3-bad"), **payload})
            assert r.status_code == 400, (payload, r.text)
            assert keyword in r.json().get("message", "") or keyword in str(r.json()), payload

    def test_legacy_create_unchanged(self, client, make_task):
        """老调用方（只有 title/subject/due_date）不受 W3 字段影响。"""
        tid = make_task(subject="政治", due_date="2026-12-01")
        items = client.get("/api/tasks", params={"page_size": 200}).json()["items"]
        t = next(x for x in items if x["id"] == tid)
        assert t["recurrence"] == {"freq": "none"}
        assert t["is_recurring"] is False
        assert t["show_progress"] is False


class TestCalendarExpansion:
    def _dates(self, client, start, end):
        r = client.get("/api/tasks/calendar", params={"start": start, "end": end})
        assert r.status_code == 200, r.text
        return r.json()["items"]

    def test_daily_and_workdays_within_range(self, client, make_task):
        tid_daily = make_task(start_date="2026-11-02", end_date="2026-11-13", recurrence={"freq": "daily"})
        tid_wd = make_task(
            title=_uniq("w3-wd"),
            start_date="2026-11-02",
            end_date="2026-11-13",
            recurrence={"freq": "workdays"},
        )
        items = self._dates(client, "2026-11-02", "2026-11-08")
        daily = sorted(i["date"] for i in items if i["id"] == tid_daily)
        workdays = sorted(i["date"] for i in items if i["id"] == tid_wd)
        assert daily == [
            "2026-11-02",
            "2026-11-03",
            "2026-11-04",
            "2026-11-05",
            "2026-11-06",
            "2026-11-07",
            "2026-11-08",
        ]
        # 2026-11-02 是周一：本周工作日 = 02..06，周末不出现
        assert workdays == ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]

    def test_weekly_saturday_and_custom_interval(self, client, make_task):
        tid_sat = make_task(
            title=_uniq("w3-sat"),
            start_date="2026-11-01",
            end_date="2026-11-30",
            recurrence={"freq": "weekly", "weekdays": [5]},
        )
        tid_e3 = make_task(
            title=_uniq("w3-every3"),
            start_date="2026-11-01",
            end_date="2026-11-30",
            recurrence={"freq": "custom", "interval": 3},
        )
        items = self._dates(client, "2026-11-01", "2026-11-30")
        sat = sorted(i["date"] for i in items if i["id"] == tid_sat)
        assert sat == ["2026-11-07", "2026-11-14", "2026-11-21", "2026-11-28"]
        every3 = sorted(i["date"] for i in items if i["id"] == tid_e3)
        assert every3 == [
            "2026-11-01",
            "2026-11-04",
            "2026-11-07",
            "2026-11-10",
            "2026-11-13",
            "2026-11-16",
            "2026-11-19",
            "2026-11-22",
            "2026-11-25",
            "2026-11-28",
        ]

    def test_specific_and_ebbinghaus_day_offsets(self, client, make_task):
        tid_spec = make_task(
            title=_uniq("w3-spec"),
            start_date="2026-11-01",
            recurrence={"freq": "specific", "dates": ["2026-11-05", "2026-11-11", "2026-12-31"]},
        )
        tid_ebb = make_task(
            title=_uniq("w3-ebb"),
            start_date="2026-11-01",
            recurrence={"freq": "ebbinghaus"},
        )
        items = self._dates(client, "2026-11-01", "2026-11-30")
        spec = sorted(i["date"] for i in items if i["id"] == tid_spec)
        assert spec == ["2026-11-05", "2026-11-11"]  # 12-31 超出查询窗口
        ebb = sorted(i["date"] for i in items if i["id"] == tid_ebb)
        # 日粒度点位 = 锚点 + [0,1,2,4,7,15,30]；30 天点若落在窗口外则不出现（诚实：不硬凑）
        expected_in_window = [
            (datetime.date(2026, 11, 1) + datetime.timedelta(days=off)).isoformat() for off in (0, 1, 2, 4, 7, 15, 30)
        ]
        assert ebb == [d for d in expected_in_window if "2026-11-01" <= d <= "2026-11-30"]

    def test_non_recurring_due_date_single_occurrence(self, client, make_task):
        tid = make_task(title=_uniq("w3-one"), due_date="2026-11-05")
        items = self._dates(client, "2026-11-01", "2026-11-30")
        mine = [i for i in items if i["id"] == tid]
        assert [i["date"] for i in mine] == ["2026-11-05"]
        assert mine[0]["done"] is False

    def test_calendar_rejects_bad_range(self, client):
        assert client.get("/api/tasks/calendar", params={"start": "2026-11-30", "end": "2026-11-01"}).status_code == 400
        assert client.get("/api/tasks/calendar", params={"start": "abc", "end": "2026-11-01"}).status_code == 400
        assert (
            client.get("/api/tasks/calendar", params={"start": "2020-01-01", "end": "2026-11-01"}).status_code == 400
        )  # 跨度超限

    def test_calendar_defaults_to_window_without_params(self, client):
        """API 契约巡检口径：GET 无参必须 2xx（默认今天 ±45 天窗口）。"""
        r = client.get("/api/tasks/calendar")
        assert r.status_code == 200
        body = r.json()
        assert body["start"] <= body["end"] and isinstance(body["items"], list)


class TestCheckInsAndProgress:
    def test_recurring_checkin_per_date_roundtrip(self, client, make_task):
        tid = make_task(
            title=_uniq("w3-ci"),
            start_date="2026-11-02",
            end_date="2026-11-30",
            recurrence={"freq": "daily"},
        )
        r = client.post(f"/api/tasks/{tid}/complete", json={"date": "2026-11-03"})
        assert r.status_code == 200 and r.json()["checkin"] is True
        # 幂等：同一天重复打卡不产生第二行
        client.post(f"/api/tasks/{tid}/complete", json={"date": "2026-11-03"})
        items = client.get("/api/tasks/calendar", params={"start": "2026-11-02", "end": "2026-11-05"}).json()["items"]
        mine = {i["date"]: i for i in items if i["id"] == tid}
        assert mine["2026-11-03"]["done"] is True
        assert mine["2026-11-04"]["done"] is False

        t = next(x for x in client.get("/api/tasks", params={"page_size": 200}).json()["items"] if x["id"] == tid)
        assert t["checkin_dates"] == ["2026-11-03"]

        r = client.post(f"/api/tasks/{tid}/uncomplete", json={"date": "2026-11-03"})
        assert r.status_code == 200
        t = next(x for x in client.get("/api/tasks", params={"page_size": 200}).json()["items"] if x["id"] == tid)
        assert t["checkin_dates"] == []

    def test_legacy_complete_keeps_old_semantics(self, client, make_task):
        """非循环 + 不带 date = 旧口径：status=done + 艾宾浩斯 next_review。"""
        tid = make_task(title=_uniq("w3-legacy"), due_date="2026-11-05")
        r = client.post(f"/api/tasks/{tid}/complete")
        assert r.status_code == 200
        assert r.json()["status"] == "done"
        assert r.json()["next_review"]
        t = next(x for x in client.get("/api/tasks", params={"page_size": 200}).json()["items"] if x["id"] == tid)
        assert t["status"] == "done"
        assert t["is_recurring"] is False

    def test_progress_bar_endpoint(self, client, make_task):
        tid = make_task(
            title=_uniq("w3-prog"),
            due_date="2026-11-05",
            show_progress=True,
            progress_total=3,
        )
        assert client.post(f"/api/tasks/{tid}/progress", json={"delta": 2}).json()["progress_done"] == 2
        assert client.post(f"/api/tasks/{tid}/progress", json={"delta": 5}).json()["progress_done"] == 3  # 封顶
        assert client.post(f"/api/tasks/{tid}/progress", json={"delta": -10}).json()["progress_done"] == 0  # 钳底
        r = client.post(f"/api/tasks/{tid}/progress", json={"delta": 1})
        assert r.status_code == 200
        # 未开进度条的任务不能调进度
        other = make_task(title=_uniq("w3-noprog"), due_date="2026-11-05")
        assert client.post(f"/api/tasks/{other}/progress", json={"delta": 1}).status_code == 400

    def test_checkin_also_bumps_progress_when_enabled(self, client, make_task):
        tid = make_task(
            title=_uniq("w3-ci-prog"),
            start_date="2026-11-02",
            end_date="2026-11-30",
            recurrence={"freq": "daily"},
            show_progress=True,
            progress_total=2,
        )
        client.post(f"/api/tasks/{tid}/complete", json={"date": "2026-11-02"})
        r = client.post(f"/api/tasks/{tid}/uncomplete", json={"date": "2026-11-02"})
        assert r.status_code == 200
        t = next(x for x in client.get("/api/tasks", params={"page_size": 200}).json()["items"] if x["id"] == tid)
        assert t["progress_done"] == 0


class TestModuleDict:
    def test_module_crud_and_dedupe(self, client):
        subject = _uniq("科目")
        r = client.post("/api/tasks/modules", json={"subject": subject, "name": "真题"})
        assert r.status_code == 200
        mid = r.json()["id"]
        r2 = client.post("/api/tasks/modules", json={"subject": subject, "name": "真题"})
        assert r2.json()["id"] == mid  # 重名幂等

        items = client.get("/api/tasks/modules", params={"subject": subject}).json()["items"]
        assert [m["name"] for m in items] == ["真题"]

        assert client.delete(f"/api/tasks/modules/{mid}").status_code == 200
        assert client.get("/api/tasks/modules", params={"subject": subject}).json()["items"] == []
        assert client.delete(f"/api/tasks/modules/{mid}").status_code == 404

    def test_module_requires_names(self, client):
        assert client.post("/api/tasks/modules", json={"subject": "", "name": "x"}).status_code == 400
