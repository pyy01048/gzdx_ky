# -*- coding: utf-8 -*-
"""把 platform_configs 里的历史明文凭据就地改写成 AES-256-GCM 密文。

## 为什么需要

`utils/secret_codec.py` 的 `EncryptedText` 把加密封在 ORM 类型边界上：从此
写 platform_configs 的凭据必然加密。但它管不到**已经在库里的行**——那些行写于
闸门之前，token / app_key / secret_key 与 extra 里的 refresh_token 至今是明文。

明文留库的实际风险不是「谁连了库」，而是**备份**：`pg_dump` 出的 SQL、写前备份
落盘的副本，每一份都是一份可直接使用的凭据文件。网盘 refresh_token 有效期以年计，
泄漏后能反复续出新的 access_token。

本脚本做一次性收口：读原值 → 让同一套 ORM 重新写回（触发 seal）→ 校验密文前缀
与往返一致性。

## 用法

    python scripts/seal_stored_credentials.py            # DRY-RUN，只出清单
    python scripts/seal_stored_credentials.py --apply    # 确认清单后真写

幂等：已带 `enc:v1:` 前缀的值跳过，重复跑无副作用。全程不打印凭据原值，
只打印 sha256 摘要前 8 位用于比对往返。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from typing import Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.db_session import IS_POSTGRES, SessionLocal  # noqa: E402
from models import PlatformConfig  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402
from utils.secret_codec import SECRET_EXTRA_KEYS, is_sealed, seal_extra, unseal, unseal_extra  # noqa: E402

CRED_COLUMNS = ("token", "app_key", "secret_key")
_RAW_SQL = (
    "SELECT platform_name, token, app_key, secret_key, CAST(extra AS TEXT) "
    "FROM platform_configs ORDER BY platform_name"
)


def _digest(value: Optional[str]) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8] if value else "-"


def _raw_rows(db) -> Dict[str, Dict[str, Optional[str]]]:
    out: Dict[str, Dict[str, Optional[str]]] = {}
    for platform, *cols in db.execute(text(_RAW_SQL)).fetchall():
        out[platform] = dict(zip(CRED_COLUMNS, cols[:3]), extra=cols[3])
    return out


def _extra_dict(raw_extra: Optional[str]) -> dict:
    import json

    if not raw_extra:
        return {}
    loaded = json.loads(raw_extra)
    return loaded if isinstance(loaded, dict) else {}


def plaintext_targets(raw: Dict[str, Dict[str, Optional[str]]]) -> List[str]:
    """仍是明文的字段路径，形如 ``baidu_netdisk.token`` / ``x.extra.refresh_token``。"""
    targets: List[str] = []
    for platform, cols in raw.items():
        for name in CRED_COLUMNS:
            value = cols[name]
            if value and not is_sealed(value):
                targets.append(f"{platform}.{name}")
        for key in SECRET_EXTRA_KEYS:
            value = _extra_dict(cols["extra"]).get(key)
            if isinstance(value, str) and value and not is_sealed(value):
                targets.append(f"{platform}.extra.{key}")
    return targets


def snapshot(db) -> Dict[str, Tuple[str, ...]]:
    """ORM 视角的明文凭据摘要，用于改写后比对往返。"""
    out: Dict[str, Tuple[str, ...]] = {}
    for row in db.query(PlatformConfig).order_by(PlatformConfig.platform_name).all():
        extra = unseal_extra(row.extra or {})
        out[row.platform_name] = tuple(
            [_digest(getattr(row, c)) for c in CRED_COLUMNS]
            + [f"{k}={_digest(str(extra.get(k)))}" for k in SECRET_EXTRA_KEYS if extra.get(k)]
        )
    return out


def rewrite(db, targets: List[str]) -> int:
    """按清单改写；返回实际改写的字段数。"""
    by_platform: Dict[str, List[str]] = {}
    for path in targets:
        platform, _, field = path.partition(".")
        by_platform.setdefault(platform, []).append(field)

    touched = 0
    for platform, fields in by_platform.items():
        row = (
            db.query(PlatformConfig)
            .filter(PlatformConfig.platform_name == platform)
            .one_or_none()
        )
        if row is None:
            continue
        for field in fields:
            if field in CRED_COLUMNS:
                # 同值赋值不会标记 dirty，必须显式 flag 才触发带 seal 的 UPDATE
                flag_modified(row, field)
                touched += 1
        if any(f.startswith("extra.") for f in fields):
            row.extra = seal_extra(unseal_extra(row.extra or {}))
            touched += 1
    return touched


def verify(db, before_raw: Dict[str, Dict[str, Optional[str]]], before_snap: Dict[str, Tuple[str, ...]]) -> List[str]:
    failures: List[str] = []
    after_raw = _raw_rows(db)
    for platform, cols in after_raw.items():
        for name in CRED_COLUMNS:
            if cols[name] and not is_sealed(cols[name]):
                failures.append(f"{platform}.{name} 仍是明文")
        for key in SECRET_EXTRA_KEYS:
            value = _extra_dict(cols["extra"]).get(key)
            if isinstance(value, str) and value and not is_sealed(value):
                failures.append(f"{platform}.extra.{key} 仍是明文")
        for name in CRED_COLUMNS:
            old, new = before_raw.get(platform, {}).get(name), cols.get(name)
            if old and new and unseal(new) != old:
                failures.append(f"{platform}.{name} 改写后解不回原值")
    if snapshot(db) != before_snap:
        failures.append("ORM 摘要与改写前不一致")
    return failures


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="把 platform_configs 明文凭据改写为密文")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认只出清单）")
    args = parser.parse_args(argv)

    print(f"数据库后端：{'PostgreSQL' if IS_POSTGRES else 'SQLite'}")
    with SessionLocal() as db:
        before_raw = _raw_rows(db)
        targets = plaintext_targets(before_raw)
        if not targets:
            print("platform_configs 里没有明文凭据，无需改写。")
            return 0
        print(f"发现 {len(targets)} 处明文字段：")
        for path in targets:
            print(f"  - {path}")
        if not args.apply:
            print("\nDRY-RUN：未写库。确认无误后追加 --apply。")
            return 0

        before_snap = snapshot(db)
        touched = rewrite(db, targets)
        db.commit()
        db.expunge_all()
        failures = verify(db, before_raw, before_snap)

    print(f"\n已改写 {touched} 处。")
    if failures:
        print("校验失败：")
        for f in failures:
            print(f"  !! {f}")
        return 1
    print("校验通过：所有非空凭据均为 enc:v1: 密文，且能解回改写前的原值。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
