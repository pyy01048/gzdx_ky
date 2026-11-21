# -*- coding: utf-8 -*-
"""event_store：EVENT_MAP 转码、append/iter 坏行隔离、derive 幂等去重、
ts 全序乱序容忍、rebuild 删库重建一致性（G4）。"""
import json

import pytest

from kernel.event_store import (
    ALL_EVENT_TYPES, EVENT_MAP, append, derive, iter_events, map_legacy_event,
    rebuild,
)


def _ev(eid, ts, etype="task.completed", **payload):
    e = {"event_id": eid, "ts": ts, "type": etype}
    if payload:
        e["payload"] = payload
    return e


class TestEventMap:
    def test_seven_legacy_types(self):
        assert len(EVENT_MAP) == 7
        assert set(EVENT_MAP) == {"answer", "review", "flashcard", "word",
                                  "focus", "study", "exam_submit"}
        for v in EVENT_MAP.values():
            assert v in ALL_EVENT_TYPES

    def test_map_legacy_ok_and_raise(self):
        assert map_legacy_event("answer") == "quiz.answered"
        with pytest.raises(ValueError):
            map_legacy_event("teleport")


class TestAppendIter:
    def test_append_then_iter(self, tmp_path):
        p = tmp_path / "events.jsonl"
        append(p, _ev("e1", "2026-11-20T10:00:00"))
        append(p, _ev("e2", "2026-11-20T11:00:00", task_id="t1"))
        rows = list(iter_events(p))
        assert len(rows) == 2 and all(err is None for _, _, err in rows)

    def test_append_rejects_bad_event(self, tmp_path):
        p = tmp_path / "events.jsonl"
        with pytest.raises(Exception):
            append(p, {"event_id": "x"})       # 缺 ts/type → schema 拒收，不落盘
        assert not p.exists() or p.stat().st_size == 0

    def test_bad_line_isolated(self, tmp_path):
        p = tmp_path / "events.jsonl"
        good = json.dumps(_ev("e1", "2026-11-20T10:00:00"))
        p.write_text(good + "\n{not json!!\n" +
                     json.dumps({"event_id": "e2"}) + "\n" + good.replace("e1", "e3") + "\n",
                     encoding="utf-8")
        rows = list(iter_events(p))
        assert rows[0][1] is not None
        assert rows[1][1] is None and "JSON" in rows[1][2]
        assert rows[2][1] is None and "schema" in rows[2][2]
        assert rows[3][1] is not None      # 坏行不中断流


class TestDerive:
    def test_idempotent_duplicate_event_id(self):
        e = _ev("dup", "2026-11-20T10:00:00", task_id="t1")
        proj = derive([e, dict(e)], "s0-r1")
        assert proj.duplicate_ids == 1
        assert proj.counters["task.completed"] == 1

    def test_out_of_order_same_result(self):
        a = _ev("a", "2026-11-20T09:00:00", task_id="t1")
        b = _ev("b", "2026-11-20T10:00:00", task_id="t1")
        p1 = derive([a, b], "v")
        p2 = derive([b, a], "v")
        assert p1.applied_ids == p2.applied_ids      # ts 全序 → 乱序到达同结果

    def test_zulu_ts_normalized_naive(self):
        proj = derive([_ev("z", "2026-11-20T10:00:00Z", task_id="t")], "v")
        assert proj.counters["task.completed"] == 1

    def test_bad_event_rejected_not_applied(self):
        proj = derive([{"event_id": "x", "ts": "not-a-date", "type": "task.completed"}], "v")
        assert len(proj.rejected) == 1
        assert proj.applied_ids == []

    def test_unknown_type_rejected_by_schema(self):
        proj = derive([_ev("u", "2026-11-20T10:00:00", etype="alien.landed")], "v")
        assert len(proj.rejected) == 1

    def test_focus_signal_aggregation(self):
        evs = [_ev(f"f{i}", f"2026-11-20T0{i}:00:00", duration_seconds=600)
               for i in range(1, 4)]
        for e in evs:
            e["type"] = "signal.focus"
        proj = derive(evs, "v")
        assert proj.daily_signals["2026-11-20"]["focus_seconds"] == 1800


class TestRebuild:
    def test_rebuild_matches_derive(self, tmp_path):
        p = tmp_path / "e.jsonl"
        evs = [_ev("r1", "2026-11-19T08:00:00", task_id="t1"),
               _ev("r2", "2026-11-20T08:00:00", card_id="w1")]
        evs[1]["type"] = "word.reviewed"
        for e in evs:
            append(p, e)
        append(p, evs[0])                              # 重复事件
        proj, report = rebuild(p, "s0-r1")
        assert report.applied == 2 and report.duplicates == 1
        # 删库重建 diff=0：与内存 derive 同投影
        direct = derive(evs, "s0-r1")
        assert proj.tasks == direct.tasks and proj.word_states == direct.word_states

    def test_rebuild_reports_bad_lines(self, tmp_path):
        p = tmp_path / "e.jsonl"
        p.write_text("garbage\n" + json.dumps(_ev("g", "2026-11-20T00:00:00", task_id="t")) + "\n",
                     encoding="utf-8")
        _proj, report = rebuild(p, "v")
        assert report.total_lines == 2
        assert report.rejected and report.rejected[0][0] == 1   # 报行号
