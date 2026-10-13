# -*- coding: utf-8 -*-
"""评测/体检结果入库（eval_runs 表）。

设计约定：
1. 写入失败只记日志、绝不抛——跑了一小时的评测产物比落库重要，
   不能因为入库报错把整个脚本结果掀掉。
2. metrics 原样存脚本自己的 report dict，不在此层改结构；
   趋势页需要的标量单独提到 primary_metric 列。
3. fingerprint 用数据集内容哈希，不用文件 mtime：同一份数据重跑
   必须能对上同一条指纹，否则趋势图会随文件复制而漂移。
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("eval_store")


def _jsonable(v: Any) -> Any:
    """numpy 标量/NaN/无穷转成可落库的纯 Python 值。"""
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else float(v)
    item = getattr(v, "item", None)          # numpy 标量
    if callable(item):
        try:
            return _jsonable(item())
        except Exception:  # noqa: BLE001
            pass
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return str(v)


def file_fingerprint(path: str) -> str:
    """数据集内容指纹（sha1 前 16 位）；文件不存在返回空串。"""
    if not path or not os.path.exists(path):
        return ""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()[:16]


def text_fingerprint(parts) -> str:
    """没有文件时（如在线抽样评测）用样本内容拼串做指纹。"""
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def record_eval_run(kind: str, *, arm: str = "", metrics: Optional[Dict] = None,
                    primary_metric: Optional[float] = None, n_samples: Optional[int] = None,
                    fingerprint: str = "", report_path: str = "", notes: str = "",
                    db=None) -> Optional[int]:
    """落一条运行记录，返回 id；失败返回 None（不抛）。"""
    from database import Base, engine
    from models import EvalRun

    # 脚本侧常在服务器启动前跑，表可能还没被 create_all 建过（同 build_subject_prototypes）
    Base.metadata.create_all(bind=engine, tables=[EvalRun.__table__])

    own = db is None
    if own:
        from database import SessionLocal
        db = SessionLocal()
    try:
        row = EvalRun(
            kind=kind, arm=arm or None, dataset_fingerprint=fingerprint or None,
            n_samples=n_samples,
            primary_metric=None if primary_metric is None else float(primary_metric),
            metrics=_jsonable(metrics or {}), report_path=report_path or None,
            notes=notes or None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info("eval_runs 落库 #%s kind=%s arm=%s primary=%s",
                    row.id, kind, arm, primary_metric)
        return row.id
    except Exception as e:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("eval_runs 落库失败（不影响评测产物）: %s", e)
        return None
    finally:
        if own:
            db.close()
