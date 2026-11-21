# -*- coding: utf-8 -*-
"""S1 kernel ↔ shell 桥接层（**新增模块**，不改 kernel 纯函数语义）。

Meoo S0 交付清单的 S1 三接线点：
1. **drift**：``study_calendar.day_ledger`` → ``kernel.ledger_export.export_ledger``
   → ``kernel.drift_detector.compute_drift``。计划分钟暂无 shell 数据源 →
   planned=0，由 G2 显式给出 ``no_plan`` 状态（绝不伪造计划量）；
   缺失日期补 0 行保持窗口连续（completed=0 是"没学"，不是吞掉）。
2. **FSRS 影子/切流**：``ReviewScheduler.calculate_next_review`` 埋钩子——
   ``KAOYAN_FSRS_SHADOW=1``（默认）只记差异日志、行为不变；
   ``KAOYAN_FSRS_ENGINE=kernel`` 才切流（默认 legacy）。
3. **事件投影**：``kernel.event_store.rebuild`` → SQLite 落表
   （``scripts/kernel_event_rebuild.py`` 消费 Projection/RebuildReport）；
   ``mirror_event`` 助手按 schema 追加 jsonl 镜像（``KAOYAN_EVENT_MIRROR=1`` 默认）。

红线：kernel 依赖缺失 / 配置缺失 / 任何异常 → **降级 legacy + warning**，
绝不打断复习/任务主链（与 study_event_service 的吞异常口径同族）。
"""

from __future__ import annotations

import dataclasses
import datetime
import importlib
import json
import logging
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: 仓库根（services/ 的上两级）；服务器布局 /opt/kaoyan 同构
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_MOD_CACHE: Dict[str, Any] = {}


def _mod(name: str):
    """懒加载 kernel 子模块；失败缓存 None 并 warning（降级不炸主链）。"""
    if name not in _MOD_CACHE:
        try:
            _MOD_CACHE[name] = importlib.import_module(f"kernel.{name}")
        except Exception as exc:  # noqa: BLE001 - 红线：降级
            logger.warning("kernel 模块 %s 不可用（降级 legacy）: %s", name, exc)
            _MOD_CACHE[name] = None
    return _MOD_CACHE[name]


def fsrs_shadow() -> bool:
    return os.environ.get("KAOYAN_FSRS_SHADOW", "1") == "1"


def fsrs_engine() -> str:
    return os.environ.get("KAOYAN_FSRS_ENGINE", "legacy").strip().lower()


# --------------------------------------------------------------------------- #
# 1) drift 接线
# --------------------------------------------------------------------------- #
def drift_for_user(db, user_id: Optional[int], *, days: int = 30) -> Dict[str, Any]:
    """day_ledger → export_ledger → compute_drift（按用户隔离，B4）。"""
    from utils.timeutil import local_today

    from services.study_calendar import day_ledger

    dd = _mod("drift_detector")
    le = _mod("ledger_export")
    cl = _mod("config_loader")
    if not (dd and le and cl):
        return {
            "drift": None,
            "status": "kernel_unavailable",
            "window_days": 0,
            "planned_avg": 0.0,
            "completed_avg": 0.0,
        }
    today = local_today()
    start = today - datetime.timedelta(days=days - 1)
    rows = day_ledger(db, start_day=start, end_day=today, user_id=user_id)
    ledger_rows = []
    for i in range(days):
        d = start + datetime.timedelta(days=i)
        act = rows.get(d.isoformat())
        ledger_rows.append({"date": d.isoformat(), "focus_minutes": int(act.focus_minutes) if act else 0})
    dto = le.export_ledger(ledger_rows)
    cfg = cl.load_rules_config().drift
    res = dd.compute_drift(dto, cfg)
    return {
        "drift": res.drift,
        "status": res.status,
        "window_days": res.window_days,
        "planned_avg": res.planned_avg,
        "completed_avg": res.completed_avg,
        "planned_source": "none",  # G2：计划功能接线前显式 no_plan，不伪造
    }


# --------------------------------------------------------------------------- #
# 2) FSRS 影子 / 切流
# --------------------------------------------------------------------------- #
def fsrs_alternative(
    quality: int,
    repetitions: int,
    interval: int,
    ef: float,
    *,
    now: Optional[datetime.datetime] = None,
    duration_ms: Optional[int] = None,
) -> Optional[Tuple[Tuple, Dict[str, Any]]]:
    """SM-2 入参 → kernel FSRS 建议（与 calculate_next_review 同构五元组）。

    返回 ``(next_review, reps, interval_days, ef_back, mastery), meta``；
    kernel 不可用返回 None（调用方保持 legacy）。
    """
    fa = _mod("fsrs_adapter")
    cl = _mod("config_loader")
    if not (fa and cl):
        return None
    from utils.timeutil import utcnow

    now = now or utcnow()
    cfg = cl.load_fsrs_config()
    state = fa.from_legacy(quality, repetitions, interval, ef, now=now)
    # SM-2 语义补全：legacy 无 last_review 时间戳，用"当前间隔已 elapsed"回推，
    # 否则 fsrs 以 elapsed=0/负值算 retrievability，Review 态间隔会激进失真。
    if interval > 0:
        state = dataclasses.replace(state, last_review=now - datetime.timedelta(days=int(interval)))
    rating = fa.rating_from_quality(quality, cfg)
    new, log = fa.review(state, rating, now, duration_ms, cfg)
    # 间隔以 due-now 实测天数为准（fsrs 6.x 的 log.scheduled_days 在 Review 态为 0）
    interval_days = max(0, (new.due - now).days)
    # reps 走 SM-2 列契约（+1）；kernel 原始 reps 进 meta 供影子期校准
    reps_out = int(repetitions) + 1
    # D→ef 逆映射（from_legacy 的 D_init=10-(ef-1.3)*4），保持列口径连续
    ef_back = round(1.3 + (10.0 - new.difficulty) / 4.0, 4)
    if new.mastered:
        mastery = "mastered"
    elif quality < 3 or new.learning:
        mastery = "learning"
    elif reps_out >= 1:
        mastery = "review"
    else:
        mastery = "new"
    meta = {
        "stability": round(new.stability, 4),
        "difficulty": round(new.difficulty, 4),
        "scheduled_days": interval_days,
        "kernel_reps": new.reps,
        "rating": int(rating),
    }
    return (new.due, reps_out, interval_days, ef_back, mastery), meta


# --------------------------------------------------------------------------- #
# 3) 事件镜像 + SQLite 投影
# --------------------------------------------------------------------------- #
def mirror_jsonl_path() -> Path:
    return _BACKEND_ROOT / "data" / "kernel_events.jsonl"


def mirror_event(
    event_type: str, payload: Optional[Dict] = None, subject_id: Any = None, *, source: str = "shell"
) -> bool:
    """按 schema 追加一行镜像；旧白名单类型自动映射 v2.0 码。

    ``KAOYAN_EVENT_MIRROR=0`` 关闭；任何失败 warning 不抛（红线 5）。
    """
    if os.environ.get("KAOYAN_EVENT_MIRROR", "1") != "1":
        return False
    es = _mod("event_store")
    if es is None:
        return False
    try:
        et = event_type if event_type in es.ALL_EVENT_TYPES else es.map_legacy_event(event_type)
        from utils.timeutil import utcnow

        ev = {
            "event_id": uuid.uuid4().hex,
            "ts": utcnow().isoformat() + "Z",
            "type": et,
            "subject_id": subject_id,
            "payload": payload or {},
            "source": source,
        }
        path = mirror_jsonl_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        es.append(path, ev)
        return True
    except Exception as exc:  # noqa: BLE001 - 红线：镜像失败不阻断主链
        logger.warning("kernel 事件镜像失败（不阻断）: %s", exc)
        return False


_PROJ_TABLES = ("tasks", "word_states", "daily_signals", "anchors", "evidence")


def project_events_to_sqlite(jsonl_path: Path, sqlite_path: Path) -> Dict[str, Any]:
    """rebuild(jsonl) → Projection 全量落 SQLite（事务内删旧插新，幂等）。

    返回 RebuildReport 字典（total/applied/duplicates/rejected/rules_version）。
    """
    es = _mod("event_store")
    if es is None:
        raise RuntimeError("kernel.event_store 不可用")
    proj, report = es.rebuild(Path(jsonl_path), rules_version="v2.0")
    sqlite_path = Path(sqlite_path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(sqlite_path))
    try:
        with conn:
            for t in _PROJ_TABLES:
                conn.execute(f"CREATE TABLE IF NOT EXISTS kernel_{t} (key TEXT PRIMARY KEY, data TEXT NOT NULL)")
                conn.execute(f"DELETE FROM kernel_{t}")
                conn.executemany(
                    f"INSERT INTO kernel_{t}(key, data) VALUES (?, ?)",
                    [(str(k), json.dumps(v, ensure_ascii=False)) for k, v in getattr(proj, t).items()],
                )
            conn.execute("CREATE TABLE IF NOT EXISTS kernel_counters (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            conn.execute("DELETE FROM kernel_counters")
            conn.executemany("INSERT INTO kernel_counters(key, value) VALUES (?, ?)", list(proj.counters.items()))
            conn.execute("CREATE TABLE IF NOT EXISTS kernel_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("DELETE FROM kernel_meta")
            meta = {
                "rules_version": report.rules_version,
                "total_lines": report.total_lines,
                "applied": report.applied,
                "duplicates": report.duplicates,
                "rejected": json.dumps(report.rejected, ensure_ascii=False),
                "applied_ids": json.dumps(proj.applied_ids, ensure_ascii=False),
                "rebuilt_at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z",
            }
            conn.executemany(
                "INSERT INTO kernel_meta(key, value) VALUES (?, ?)", [(k, str(v)) for k, v in meta.items()]
            )
    finally:
        conn.close()
    return {
        "total_lines": report.total_lines,
        "applied": report.applied,
        "duplicates": report.duplicates,
        "rejected": report.rejected,
        "rules_version": report.rules_version,
    }
