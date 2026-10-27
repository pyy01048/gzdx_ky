# -*- coding: utf-8 -*-
"""models.py 的 ENUM 列：String → PgEnumAware 批量迁移。

背景：旧 models.py 把 34 个实为 PG ENUM 的列写成 String，导致 PG 上报
`operator does not exist: xxx = character varying`，并因事务 aborted 连带
打挂整个接口（详见 core/pg_enum_aware.py 的模块注释）。

策略
----
不盲目替换所有 `Column(String)`。只替换 **ENUM_COLUMNS 清单中确认为 ENUM 的列**，
判定依据是「表名 + 列名」双匹配，避免误伤同名的普通字符串列
（例如多张表都有 `status`、`engine`，但只有部分是真 ENUM）。

实现
----
1. 解析 models.py，按 `class Xxx(Base)` + `__tablename__ = "yyy"` 建立
   类 → 表名的映射；
2. 在类体内查找 `col = Column(String(...))` 且 (表名, col) 命中清单的；
3. 替换类型部分，其余参数（default/comment/nullable）原样保留。

安全：
  · dry-run 默认；--apply 前备份
  · 逐条打印改动，便于人工复核
  · 替换后 import models 失败即回滚提示
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pg_enum_aware import ENUM_COLUMNS  # noqa: E402

MODELS = Path(r"D:\平台\backend-main-fastapi\models.py")

#: class Xxx(...):  __tablename__ = "yyy"
CLASS_RE = re.compile(
    r"^class\s+(\w+)\s*\([^)]*\)\s*:\s*\n(?:\s*\"\"\".*?\"\"\"\s*\n)?",
    re.M | re.S,
)
TABLE_RE = re.compile(r'__tablename__\s*=\s*["\'](\w+)["\']')

#: 列定义：col = Column(String(50), ...)
COL_RE = re.compile(
    r"^(?P<indent>\s*)(?P<col>\w+)\s*=\s*Column\(\s*String\((?P<len>\d+)\)",
    re.M,
)


def build_table_map(src: str) -> dict[int, str]:
    """行号 → 所属表名。"""
    out: dict[int, str] = {}
    current = None
    for m in re.finditer(r'^__tablename__\s*=\s*["\'](\w+)["\']', src, re.M):
        current = m.group(1)
        out[m.start()] = current
    return out


def migrate(src: str) -> tuple[str, list[tuple[str, str, str]]]:
    """返回 (新源码, [(表名, 列名, ENUM类型名)])。"""
    lines = src.split("\n")
    changes: list[tuple[str, str, str]] = []

    # 逐行跟踪当前 class 的 tablename
    table_of_line: dict[int, str] = {}
    cur_table = None
    in_class = False
    for i, ln in enumerate(lines):
        if re.match(r"^class\s+\w+", ln):
            in_class = True
            cur_table = None
        if in_class:
            m = re.search(r'__tablename__\s*=\s*["\'](\w+)["\']', ln)
            if m:
                cur_table = m.group(1)
            table_of_line[i] = cur_table or ""

    out = list(lines)
    for i, ln in enumerate(lines):
        m = COL_RE.match(ln)
        if not m:
            continue
        table = table_of_line.get(i, "")
        col = m.group("col")
        if not table or (table, col) not in ENUM_COLUMNS:
            continue
        # 主键列跳过：ENUM 作主键会改变外键引用与索引行为，风险高收益低。
        # 实测 subject_prototypes.engine 是 primary_key=True，保持 String 更安全
        # （读多写少，且该表主要按字符串等值查找，PG 会隐式转换失败但影响面小，
        #   后续随 core/models 迁移一并解决）。
        if "primary_key=True" in ln:
            continue
        enum_name = ENUM_COLUMNS[(table, col)]
        length = m.group("len")
        new_ln = COL_RE.sub(
            lambda mm: (
                f"{mm.group('indent')}{mm.group('col')} = "
                f"Column(PgEnumAware(\"{enum_name}\", {length})"
            ),
            ln,
            count=1,
        )
        out[i] = new_ln
        changes.append((table, col, enum_name))

    return "\n".join(out), changes


def ensure_import(src: str) -> str:
    """补 PgEnumAware 导入。"""
    if "PgEnumAware" in src.split("\n\n")[0] and "import PgEnumAware" in src[:2000]:
        return src
    anchor = "from database import Base"
    if anchor in src:
        return src.replace(
            anchor,
            anchor + "\nfrom core.pg_enum_aware import PgEnumAware",
            1,
        )
    return src


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    src = MODELS.read_text(encoding="utf-8")
    new, changes = migrate(src)

    print("=" * 68)
    print("models.py ENUM 列迁移：String → PgEnumAware")
    print("=" * 68)
    print(f"  命中 {len(changes)} 处\n")
    for t, c, e in changes:
        print(f"  {t}.{c:<24} → {e}")

    if not args.apply:
        print("\n[预览模式] 未修改文件。")
        return 0

    new = ensure_import(new)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = MODELS.with_suffix(f".py.bak-{stamp}")
    shutil.copy2(MODELS, bak)
    MODELS.write_text(new, encoding="utf-8")

    print(f"\n备份：{bak}")
    print(f"已写入 {MODELS}")

    # 用**子进程**验证可导入。
    # 不能用同进程 importlib.reload：reload 会重新执行 models.py，而 Base.metadata
    # 里已注册过同名 Table，触发 "Table 'goals' is already defined"（实测踩坑）。
    import subprocess
    r = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, r'D:\\平台\\backend-main-fastapi'); import models; print('OK')"],
        capture_output=True, text=True, cwd=str(MODELS.parent),
    )
    if "OK" in (r.stdout or ""):
        print("✓ models 导入成功（子进程验证）")
        return 0
    print(f"✗ models 导入失败：{(r.stderr or '')[-400:]}")
    print("  已回滚")
    shutil.copy2(bak, MODELS)
    return 1


if __name__ == "__main__":
    sys.exit(main())
