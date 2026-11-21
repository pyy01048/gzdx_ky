# -*- coding: utf-8 -*-
"""生成数据字典 docs/data-dictionary.md（完善方案 05 §3.4）。

内容：每张表/视图 → 类型、行数、列（名/类型/可空/默认）、注释、ORM 类、主要写入方。

用法：
    cd backend-main-fastapi
    python scripts/diagnostics/gen_data_dictionary.py                 # 写 docs/data-dictionary.md
    python scripts/diagnostics/gen_data_dictionary.py --stdout         # 只打印
    python scripts/diagnostics/gen_data_dictionary.py --out ../docs/data-dictionary.md

只读操作：仅查询 information_schema / pg_class 与 count(*)，不做任何写入。
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from sqlalchemy import inspect, text  # noqa: E402

WRITE_HINT = re.compile(r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM|\.add\(|bulk_insert|MERGE\s+INTO)", re.I)


def _source_corpus() -> dict[str, str]:
    """把 routers/ services/ 源码按文件读成 {相对路径: 内容}，用于推断写入方。"""
    corpus = {}
    for sub in ("routers", "services", "utils", "core"):
        d = BASE / sub
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            try:
                corpus[str(p.relative_to(BASE)).replace("\\", "/")] = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
    return corpus


def _writers(table: str, corpus: dict[str, str], limit: int = 3) -> str:
    hits = []
    pattern = re.compile(rf"\b{re.escape(table)}\b", re.I)
    for path, src in corpus.items():
        if not pattern.search(src):
            continue
        # 只保留"附近的写入语义"，纯读引用不算
        for line in src.splitlines():
            if table.lower() in line.lower() and WRITE_HINT.search(line):
                hits.append(path)
                break
    uniq = sorted(set(hits))
    if not uniq:
        return "—（未在 routers/services 命中写入语句）"
    more = f" 等 {len(uniq)} 处" if len(uniq) > limit else ""
    return "、".join(uniq[:limit]) + more


def _orm_map() -> dict[str, str]:
    try:
        from database import Base  # noqa: PLC0415

        return {t.name: f"{m.__module__}.{m.__name__}" for t, m in Base.metadata.tables.items()}
    except Exception:  # noqa: BLE001 —— 无依赖环境下允许降级
        return {}


def build(engine) -> str:
    insp = inspect(engine)
    corpus = _source_corpus()
    orm = _orm_map()
    lines: list[str] = [
        "# 数据字典（自动生成）",
        "",
        f"> 生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} · "
        f"生成器：`scripts/diagnostics/gen_data_dictionary.py`  ",
        "> **请勿手改**：结构变更后重新生成；视图标注 READONLY（写入一律指向真实表）。",
        "",
    ]
    tables = insp.get_table_names()
    views = insp.get_view_names() if hasattr(insp, "get_view_names") else []
    rows_stat: dict[str, int | None] = {}
    with engine.connect() as conn:
        for name in tables + views:
            try:
                rows_stat[name] = conn.execute(text(f'SELECT count(*) FROM "{name}"')).scalar()
            except Exception:  # noqa: BLE001
                rows_stat[name] = None

    def render(name: str, kind: str) -> list[str]:
        cols = insp.get_columns(name)
        comments = {}
        try:
            with engine.connect() as conn:
                for r in conn.execute(
                    text(
                        "SELECT a.attname, col_description(a.attrelid, a.attnum) "
                        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                        "WHERE c.relname = :t AND a.attnum > 0 AND NOT a.attisdropped"
                    ),
                    {"t": name},
                ):
                    comments[r[0]] = r[1]
        except Exception:  # noqa: BLE001
            pass
        out = [f"### `{name}`", "", f"- 类型：**{kind}**" + ("（READONLY）" if kind == "VIEW" else "")]
        out.append(f"- 行数：{rows_stat.get(name) if rows_stat.get(name) is not None else '未知'}")
        out.append(f"- ORM 类：{orm.get(name, '—（无 ORM 映射）')}")
        out.append(f"- 主要写入方：{'—（视图只读）' if kind == 'VIEW' else _writers(name, corpus)}")
        if comments and any(comments.values()):
            out.append("- 列注释：" + "；".join(f"`{k}`={v}" for k, v in comments.items() if v))
        out += ["", "| 列 | 类型 | 可空 | 默认 |", "|---|---|---|---|"]
        for c in cols:
            default = c.get("default")
            out.append(
                f"| {c['name']} | {c['type']} | {'是' if c.get('nullable', True) else '否'} | "
                f"{default if default is not None else ''} |"
            )
        out.append("")
        return out

    lines += [f"## 一、真实表（{len(tables)} 张）", ""]
    for t in sorted(tables):
        lines += render(t, "TABLE")
    lines += [f"## 二、视图（{len(views)} 个）", ""]
    if not views:
        lines += ["（无视图）", ""]
    for v in sorted(views):
        lines += render(v, "VIEW")

    missing_orm = sorted(set(tables) - set(orm))
    lines += ["## 三、ORM 未覆盖表清单", "", f"共 {len(missing_orm)} 张（作为 models 拆分的输入，见 04 文档）：", ""]
    lines += [f"- `{t}`" for t in missing_orm] or ["（全部已覆盖）"]
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BASE.parent / "docs" / "data-dictionary.md"))
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()

    from core.db_session import IS_POSTGRES, build_database_url  # noqa: PLC0415
    from sqlalchemy import create_engine  # noqa: PLC0415

    if not IS_POSTGRES:
        print("[x] 数据字典仅支持 PostgreSQL（DATABASE_BACKEND=postgresql）")
        return 2
    engine = create_engine(build_database_url())
    md = build(engine)
    if args.stdout:
        print(md)
        return 0
    Path(args.out).write_text(md, encoding="utf-8", newline="\n")
    print(f"已生成 {args.out}（{len(md.splitlines())} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
