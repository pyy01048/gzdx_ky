# -*- coding: utf-8 -*-
"""院校类型补全（V17）：kaoyan.cn 筛选模型第三维「院校类型」。

- `ensure_school_type_schema`：ALTER kaoyan_schools ADD school_type（幂等）
- `enrich_from_tags`：只从**已有数据**（tags JSON / intro 首句）提取类型词，
  不匹配则留空——严禁编造；输出待人工确认清单
- 类型枚举对齐 kaoyan.cn：综合类/理工类/农林类/医药类/师范类/语言类/财经类/
  政法类/体育类/艺术类/民族类/军事类/其他

复试用 `syllabus_spider`（见同目录）：工科/理科复试大纲爬取骨架。
"""
from __future__ import annotations

import json
import re
from typing import Dict, List

from sqlalchemy.orm import Session

SCHOOL_TYPES = ["综合类", "理工类", "农林类", "医药类", "师范类", "语言类",
                "财经类", "政法类", "体育类", "艺术类", "民族类", "军事类"]
_TYPE_RE = re.compile("(" + "|".join(SCHOOL_TYPES) + ")")

_DDLS = [
    "ALTER TABLE kaoyan_schools ADD COLUMN school_type TEXT",
]


def ensure_school_type_schema(db: Session) -> Dict:
    applied = []
    conn = db.connection().connection
    for ddl in _DDLS:
        try:
            conn.execute(ddl)
            applied.append(ddl.split("ADD COLUMN")[1].strip().split(" ")[0])
        except Exception:
            pass  # 列已存在
    conn.commit()
    return {"applied": applied}


def enrich_from_seed(db: Session) -> Dict:
    """kaoyan.cn 实测抓取的 name→类型 映射（school_type_seed.json）优先灌库。

    精确匹配院校名；命中写 school_type + school_type_source='kaoyan.cn'。
    返回 {matched, unmatched}，unmatched 供人工核对（勿编造）。
    """
    ensure_school_type_schema(db)
    from pathlib import Path
    seed_path = Path(__file__).parent / "school_type_seed.json"
    if not seed_path.exists():
        return {"matched": 0, "unmatched": [], "error": "seed 文件缺失"}
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    conn = db.connection().connection
    matched, unmatched = 0, []
    for s in seed:
        row = conn.execute(
            "SELECT id FROM kaoyan_schools WHERE name=?", (s["name"],)).fetchone()
        if row:
            conn.execute(
                "UPDATE kaoyan_schools SET school_type=?, school_type_source='kaoyan.cn' "
                "WHERE id=?", (s["school_type"], row[0]))
            matched += 1
        else:
            unmatched.append(s["name"])
    conn.commit()
    return {"matched": matched, "unmatched": unmatched, "seed_size": len(seed)}


def enrich_from_tags(db: Session, dry_run: bool = True) -> Dict:
    """从 tags JSON / intro 中提取院校类型（命中唯一类型才写，多个/零个留空）。"""
    ensure_school_type_schema(db)
    conn = db.connection().connection
    rows = conn.execute(
        "SELECT id, name, tags, intro FROM kaoyan_schools WHERE school_type IS NULL"
    ).fetchall()
    updated, pending = 0, []
    for sid, name, tags_json, intro in rows:
        hits: List[str] = []
        for blob in (tags_json, (intro or "")[:60]):
            if not blob:
                continue
            try:
                text = blob if isinstance(blob, str) and blob.strip().startswith("[") \
                    else json.dumps(blob, ensure_ascii=False)
                blob_text = " ".join(json.loads(text)) if text.startswith("[") else str(blob)
            except Exception:
                blob_text = str(blob)
            hits += [t for t in _TYPE_RE.findall(blob_text) if t not in hits]
        if len(hits) == 1:
            pending.append({"id": sid, "name": name, "school_type": hits[0]})
            if not dry_run:
                conn.execute("UPDATE kaoyan_schools SET school_type=? WHERE id=?",
                             (hits[0], sid))
                updated += 1
        elif len(hits) > 1:
            pending.append({"id": sid, "name": name, "ambiguous": hits})
    if not dry_run:
        conn.commit()
    return {"scanned": len(rows), "updated": updated, "pending_review": pending[:50]}
