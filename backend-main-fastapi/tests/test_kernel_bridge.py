# -*- coding: utf-8 -*-
"""S1 kernel 桥接层回归（任务 #13）。

覆盖：
- drift 接线：/api/growth/drift 鉴权 + 无数据 no_plan（G2 不伪造计划）+
  有专注数据 completed_avg 正确 + 按 user_id 隔离（B4）；
- FSRS 影子：默认只记日志、SM-2 返回契约不变；切流 env 才换 kernel 建议；
  kernel 依赖缺失降级 legacy 不炸；
- 事件投影：rebuild → SQLite 幂等（重跑 dump diff=0）、坏行/重复计数不中断；
- 镜像助手：schema 校验追加、旧类型映射、未知类型/关闭开关安全降级。
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from types import SimpleNamespace

import pytest

UID = 990006


@pytest.fixture()
def stub_user(app_module):
    from utils.security import current_user

    prev = app_module.dependency_overrides.get(current_user)
    app_module.dependency_overrides[current_user] = lambda: SimpleNamespace(id=UID, role="user", username="s1_probe")
    yield
    if prev is None:
        app_module.dependency_overrides.pop(current_user, None)
    else:
        app_module.dependency_overrides[current_user] = prev


@pytest.fixture()
def focus_rows(db_schema):
    from database import SessionLocal
    from models import StudySession, User
    from utils.timeutil import local_today

    db = SessionLocal()
    today = local_today()
    try:
        for uid, nm in ((UID, "s1_probe"), (UID + 1, "s1_other")):
            if db.query(User).filter(User.id == uid).first() is None:
                db.add(
                    User(id=uid, username=nm, password_hash="!disabled", display_name=nm, role="user", is_active=True)
                )
        db.commit()
        for i in range(5):
            db.add(
                StudySession(
                    user_id=UID,
                    date=today - datetime.timedelta(days=i),
                    duration=60,
                    task_type="pomodoro",
                    subject="数学",
                )
            )
        # 他人数据：不得计入本人 drift（B4）
        db.add(StudySession(user_id=UID + 1, date=today, duration=500, task_type="pomodoro", subject="数学"))
        db.commit()
        yield
    finally:
        db.query(StudySession).filter(StudySession.user_id.in_([UID, UID + 1])).delete()
        db.query(User).filter(User.id.in_([UID, UID + 1])).delete()
        db.commit()
        db.close()


class TestDriftWiring:
    def test_requires_auth(self, client, app_module):
        from fastapi import HTTPException
        from utils.security import current_user

        def _deny():
            raise HTTPException(status_code=401, detail="未登录")

        prev = app_module.dependency_overrides.get(current_user)
        app_module.dependency_overrides[current_user] = _deny
        try:
            r = client.get("/api/growth/drift")
            assert r.status_code == 401
        finally:
            if prev is None:
                app_module.dependency_overrides.pop(current_user, None)
            else:
                app_module.dependency_overrides[current_user] = prev

    def test_no_data_no_plan(self, client, stub_user):
        r = client.get("/api/growth/drift")
        assert r.status_code == 200
        body = r.json()
        # G2：计划源未接线 → 显式 no_plan，drift=0，绝不伪造计划量
        assert body["status"] in ("no_plan", "kernel_unavailable")
        if body["status"] == "no_plan":
            assert body["drift"] == 0.0
            assert body["completed_avg"] == 0.0
            assert body["planned_source"] == "none"

    def test_focus_flows_into_completed(self, client, stub_user, focus_rows):
        r = client.get("/api/growth/drift?window=30")
        assert r.status_code == 200
        body = r.json()
        if body["status"] == "kernel_unavailable":
            pytest.skip("kernel 依赖缺失（降级路径另测）")
        assert body["status"] == "no_plan"
        # 5 天 ×60min 落在 7 天窗口内（含 2 个零日）→ completed_avg=300/7；
        # 他人 500min 不得混入（B4）
        assert body["completed_avg"] == pytest.approx(300 / 7)
        assert body["window_days"] == 7


class TestFsrsShadow:
    def test_shadow_logs_but_legacy_contract_unchanged(self, caplog):
        import logging

        from services.review_scheduler import ReviewScheduler

        with caplog.at_level(logging.INFO, logger="services.review_scheduler"):
            out = ReviewScheduler.calculate_next_review(4, 2, 6, 2.5)
        # SM-2：reps 3 → interval=round(6*2.5)=15
        assert out[1] == 3 and out[2] == 15
        assert any("FSRS_SHADOW" in m for m in caplog.messages)

    def test_cutover_env_switches_to_kernel(self, monkeypatch):
        from services.review_scheduler import ReviewScheduler

        monkeypatch.setenv("KAOYAN_FSRS_ENGINE", "kernel")
        out = ReviewScheduler.calculate_next_review(4, 2, 6, 2.5)
        assert out[1] == 3  # SM-2 列契约 reps+1
        assert 1 <= out[2] <= 60  # 间隔 sane（last_review 回推后不再激进失真）
        assert out[0].tzinfo is None  # naive UTC 契约（P0-4）
        # 确认真的走了 kernel（legacy 的 ef 恒为 2.5，kernel D→ef 逆映射不同）
        assert out[3] != pytest.approx(2.5)

    def test_kernel_missing_degrades_to_legacy(self, monkeypatch):
        from services import kernel_bridge
        from services.review_scheduler import ReviewScheduler

        monkeypatch.setitem(kernel_bridge._MOD_CACHE, "fsrs_adapter", None)
        monkeypatch.setitem(kernel_bridge._MOD_CACHE, "config_loader", None)
        out = ReviewScheduler.calculate_next_review(4, 2, 6, 2.5)
        assert out[2] == 15  # legacy 原样


class TestProjection:
    def _jsonl(self, tmp_path):
        p = tmp_path / "events.jsonl"
        ts = datetime.datetime(2026, 11, 21, 8, 0, 0).isoformat() + "Z"
        lines = [
            {
                "event_id": "e1",
                "ts": ts,
                "type": "task.completed",
                "subject_type": "task",
                "subject_id": "t1",
                "payload": {"minutes": 30},
            },
            {
                "event_id": "e2",
                "ts": ts,
                "type": "word.reviewed",
                "subject_type": "word",
                "subject_id": "w1",
                "payload": {"rating": 3},
            },
            {
                "event_id": "e1",
                "ts": ts,
                "type": "task.completed",
                "subject_type": "task",
                "subject_id": "t1",
                "payload": {},
            },  # 重复
            "this-is-not-json",  # 坏行
            {"event_id": "e3", "ts": ts, "type": "bogus.type"},  # 枚举外
        ]
        p.write_text("\n".join(json.dumps(x) if isinstance(x, dict) else x for x in lines), encoding="utf-8")
        return p

    def _dump(self, sqlite_path):
        conn = sqlite3.connect(str(sqlite_path))
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {
                t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in tables if t != "kernel_meta"
            }  # meta 含 rebuilt_at 时间戳
        finally:
            conn.close()

    def test_rebuild_counts_and_idempotent(self, tmp_path):
        from services.kernel_bridge import project_events_to_sqlite

        jsonl = self._jsonl(tmp_path)
        dbp = tmp_path / "proj.db"
        rep1 = project_events_to_sqlite(jsonl, dbp)
        assert rep1["applied"] == 2
        assert rep1["duplicates"] == 1
        assert len(rep1["rejected"]) == 2
        dump1 = self._dump(dbp)
        rep2 = project_events_to_sqlite(jsonl, dbp)
        assert rep2["applied"] == 2
        assert self._dump(dbp) == dump1  # 幂等：重跑 diff=0


class TestMirror:
    def test_append_and_legacy_map(self, tmp_path, monkeypatch):
        from services import kernel_bridge

        target = tmp_path / "mirror.jsonl"
        monkeypatch.setattr(kernel_bridge, "mirror_jsonl_path", lambda: target)
        assert kernel_bridge.mirror_event("review", {"rating": 4}, subject_id=7) is True
        ev = json.loads(target.read_text(encoding="utf-8").strip())
        assert ev["type"] == "task.reviewed"  # 旧白名单 → v2.0 码
        assert ev["subject_id"] == 7

    def test_unknown_type_and_off_switch_safe(self, tmp_path, monkeypatch):
        from services import kernel_bridge

        target = tmp_path / "mirror.jsonl"
        monkeypatch.setattr(kernel_bridge, "mirror_jsonl_path", lambda: target)
        assert kernel_bridge.mirror_event("totally_unknown") is False
        monkeypatch.setenv("KAOYAN_EVENT_MIRROR", "0")
        assert kernel_bridge.mirror_event("review") is False
        assert not target.exists()
