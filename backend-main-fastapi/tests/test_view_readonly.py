# -*- coding: utf-8 -*-
"""视图只读守卫（完善方案 05 §3.2 / P1-3 回归闸）。

背景：库中存在 subject_config / kaoyan_subjects 等视图，历史上脚本往视图写数据
直接失败（10-28 P1-3）。规则：**ORM 不得映射可写视图**，写入一律指向真实表。

做法：列出库中全部视图，断言 ORM 映射的 __table__ 不在视图集合中；
历史豁免显式白名单（附整改待办），白名单只允许缩小、不允许新增。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

#: 历史豁免：ORM 映射了视图但暂未整改。新增条目必须在 PR 说明原因。
VIEW_MAPPING_ALLOWLIST: dict[str, str] = {
    "kaoyan_subjects": "只读学科视图（KaoyanSubject 仅查询）；写入走 disciplines / subjects",
    "subject_config": "只读兼容视图（旧契约层只查询）；写入走 subject_configs 真实表",
}


@pytest.fixture(scope="module")
def view_names():
    from database import engine

    try:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text("SELECT table_name FROM information_schema.views WHERE table_schema = current_schema()")
                )
                .scalars()
                .all()
            )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL 不可用：{exc}")
    return set(rows)


def test_orm_does_not_map_views(view_names):
    from database import Base

    mapped = set(Base.metadata.tables.keys())
    offenders = sorted((mapped & view_names) - set(VIEW_MAPPING_ALLOWLIST))
    assert not offenders, (
        "以下 ORM 类映射到了视图（只读，写入会失败）："
        f"{offenders}。请改为映射真实表，或登记到 VIEW_MAPPING_ALLOWLIST 并附整改计划。"
    )


def test_allowlist_entries_still_views(view_names):
    """白名单只允许缩小：视图改名/删除后，残留条目必须清理。"""
    stale = sorted(set(VIEW_MAPPING_ALLOWLIST) - view_names)
    assert not stale, f"白名单中的视图已不存在，请从 VIEW_MAPPING_ALLOWLIST 删除：{stale}"


def test_writes_go_to_real_tables():
    """静态检查：routers/services 里不得出现对已知视图名的 INSERT/UPDATE/DELETE。"""
    import re
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent
    views = ("subject_config", "kaoyan_subjects")
    pattern = re.compile(rf"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+({'|'.join(views)})\b", re.I)
    hits = []
    for sub in ("routers", "services"):
        for p in (base / sub).rglob("*.py"):
            src = p.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(src):
                hits.append(str(p.relative_to(base)))
    assert not hits, f"发现对视图的写语句：{hits}（应写入真实表）"
