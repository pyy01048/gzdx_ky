# -*- coding: utf-8 -*-
"""事件溯源底座（落地方案 §4.2，S0 交付纯函数部分）。

- EVENT_MAP：现有 7 类白名单 → v2.0 事件码（附录 B/C）。
- append：唯一 I/O 例外，路径由调用方注入；单行 JSON＋flush；失败抛由 shell 吞为 warning。
- iter_events：坏行隔离 yield (event|None, error|None)，不中断流。
- derive：纯函数投影——event_id 幂等去重、ts 全序 apply、jsonschema 入库校验。
- rebuild：读 jsonl → derive → 返回 RebuildReport（shell 脚本 S1 消费）。

G4：重复事件不重复计数；坏事件拒收率 100% 且报行号与违反字段。
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import jsonschema

#: 现有白名单 → v2.0 事件码（study_event_service.KNOWN_EVENT_TYPES 不动）
EVENT_MAP: Dict[str, str] = {
    "answer": "quiz.answered",
    "review": "task.reviewed",
    "flashcard": "word.reviewed",
    "word": "word.reviewed",
    "focus": "signal.focus",
    "study": "task.partial",
    "exam_submit": "exam.submitted",
}

#: v2.0 扩展事件码（kernel 直接写；总方案 §3.1 枚举冻结）
EXTENDED_EVENT_TYPES = (
    "baseline.answered",
    "task.completed",
    "task.partial",
    "task.missed",
    "task.reviewed",
    "word.reviewed",
    "word.mastered",
    "dictation.result",
    "quiz.answered",
    "code.submitted",
    "code.audited",
    "code.compliance_checked",
    "plan.proposed",
    "plan.approved",
    "plan.adjusted",
    "retro.done",
    "signal.subjective",
    "signal.focus",
    "evidence.collected",
    "evidence.audited",
    "misc.retested",
    "exam.submitted",
)

ALL_EVENT_TYPES = frozenset(EXTENDED_EVENT_TYPES)

#: 入库 schema：event_id/ts/type 必填；type 必须在冻结枚举内
EVENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["event_id", "ts", "type"],
    "properties": {
        "event_id": {"type": "string", "minLength": 1},
        "ts": {"type": "string", "minLength": 1},
        "type": {"type": "string", "enum": sorted(ALL_EVENT_TYPES)},
        "subject_type": {"type": ["string", "null"]},
        "subject_id": {"type": ["string", "integer", "null"]},
        "payload": {"type": ["object", "null"]},
        "source": {"type": ["string", "null"]},
        "evidence_grade": {"type": ["string", "null"]},
    },
}


def map_legacy_event(event_type: str) -> str:
    """旧白名单类型 → v2.0 码；未知类型显式抛错（不静默透传脏类型）。"""
    try:
        return EVENT_MAP[event_type]
    except KeyError:
        raise ValueError(f"未知旧事件类型: {event_type!r}") from None


def _parse_ts(ts: str) -> datetime.datetime:
    """解析 ISO 时间串为 **naive UTC**。带时区偏移的输入先折算到 UTC 再去 tzinfo。"""
    t = ts.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(t)
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


# --------------------------------------------------------------------------- #
# append / iter
# --------------------------------------------------------------------------- #
def append(path: Path, event: Dict[str, Any]) -> None:
    """追加单行 JSON 并 flush。任何异常向上抛（shell 侧吞为 warning，红线 5）。

    写入前做 schema 校验：坏事件在镜像层同样拒收，绝不落盘污染事实源。
    """
    jsonschema.validate(instance=event, schema=EVENT_SCHEMA)
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def iter_events(path: Path) -> Iterator[Tuple[int, Optional[Dict], Optional[str]]]:
    """逐行读取；坏行隔离 yield (行号, None, 错误说明)，不中断流。"""
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                yield lineno, None, f"JSON 解析失败: {exc.msg}"
                continue
            try:
                jsonschema.validate(instance=obj, schema=EVENT_SCHEMA)
            except jsonschema.ValidationError as exc:
                yield (
                    lineno,
                    None,
                    f"schema 校验失败: {'/'.join(map(str, exc.absolute_path)) or exc.schema.get('type', '?')}（{exc.message[:120]}）",
                )
                continue
            yield lineno, obj, None


# --------------------------------------------------------------------------- #
# derive：纯函数投影
# --------------------------------------------------------------------------- #
@dataclass
class Projection:
    """derive 输出投影（内存态；S1 落 SQLite 表由 shell 负责）。"""

    rules_version: str
    tasks: Dict[str, Dict] = field(default_factory=dict)
    word_states: Dict[str, Dict] = field(default_factory=dict)
    daily_signals: Dict[str, Dict] = field(default_factory=dict)
    anchors: Dict[str, Dict] = field(default_factory=dict)
    evidence: Dict[str, Dict] = field(default_factory=dict)
    counters: Dict[str, int] = field(default_factory=dict)
    applied_ids: List[str] = field(default_factory=list)
    rejected: List[Tuple[int, str]] = field(default_factory=list)  # (行号或序号, 原因)
    duplicate_ids: int = 0


def _apply_event(proj: Projection, ev: Dict[str, Any]) -> None:
    et = ev["type"]
    payload = ev.get("payload") or {}
    if et.startswith("task."):
        tid = str(payload.get("task_id") or ev.get("subject_id") or "")
        if tid:
            cur = proj.tasks.setdefault(tid, {"task_id": tid, "status": "pending", "events": []})
            if et == "task.completed":
                cur["status"] = "done"
            elif et == "task.missed":
                cur["status"] = "missed"
            elif et == "task.partial":
                cur["status"] = "partial"
            cur["events"].append(ev["event_id"])
    elif et in ("word.reviewed", "word.mastered"):
        wid = str(payload.get("card_id") or ev.get("subject_id") or "")
        if wid:
            st = proj.word_states.setdefault(wid, {"card_id": wid, "reviews": 0, "mastered": False})
            st["reviews"] += 1
            if et == "word.mastered":
                st["mastered"] = True
    elif et == "signal.focus":
        day = str(ev["ts"])[:10]
        sig = proj.daily_signals.setdefault(day, {"date": day, "focus_seconds": 0})
        sig["focus_seconds"] += int(payload.get("duration_seconds") or 0)
    elif et == "evidence.collected":
        eid = str(ev.get("subject_id") or ev["event_id"])
        proj.evidence[eid] = {"ev_id": eid, "payload": payload, "grade": ev.get("evidence_grade")}
    elif et == "evidence.audited":
        eid = str(payload.get("ev_id") or "")
        if eid in proj.evidence:
            proj.evidence[eid]["audit"] = payload
    proj.counters[et] = proj.counters.get(et, 0) + 1
    proj.applied_ids.append(ev["event_id"])


def derive(events: List[Dict[str, Any]], rules_version: str) -> Projection:
    """纯函数重建投影：ts 全序 apply（乱序容忍）＋ event_id 幂等去重。

    无 ts 可解析的事件进 rejected，不进投影（拒收可定位）。
    """
    proj = Projection(rules_version=rules_version)
    seen: set = set()
    valid: List[Tuple[datetime.datetime, int, Dict[str, Any]]] = []
    for idx, ev in enumerate(events):
        try:
            jsonschema.validate(instance=ev, schema=EVENT_SCHEMA)
            ts = _parse_ts(ev["ts"])
        except (jsonschema.ValidationError, ValueError, TypeError) as exc:
            proj.rejected.append((idx, str(exc)[:200]))
            continue
        valid.append((ts, idx, ev))
    # ts 全序；同 ts 按到达序号稳定排序 → 乱序到达结果与顺序写入一致
    valid.sort(key=lambda x: (x[0], x[1]))
    for _ts, idx, ev in valid:
        eid = ev["event_id"]
        if eid in seen:
            proj.duplicate_ids += 1
            continue
        seen.add(eid)
        _apply_event(proj, ev)
    return proj


@dataclass(frozen=True)
class RebuildReport:
    total_lines: int
    applied: int
    duplicates: int
    rejected: List[Tuple[int, str]]
    rules_version: str


def rebuild(path: Path, rules_version: str) -> Tuple[Projection, RebuildReport]:
    """从 jsonl 全量重建投影（删库重建 diff=0 的内核侧保证）。"""
    events: List[Dict[str, Any]] = []
    total = 0
    pre_rejected: List[Tuple[int, str]] = []
    for lineno, ev, err in iter_events(path):
        total = max(total, lineno)
        if err or ev is None:
            pre_rejected.append((lineno, err or "空行外错误"))
            continue
        events.append(ev)
    proj = derive(events, rules_version)
    report = RebuildReport(
        total_lines=total,
        applied=len(proj.applied_ids),
        duplicates=proj.duplicate_ids,
        rejected=pre_rejected + proj.rejected,
        rules_version=rules_version,
    )
    return proj, report
