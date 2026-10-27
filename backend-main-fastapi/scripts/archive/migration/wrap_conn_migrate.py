# -*- coding: utf-8 -*-
"""给未包装的裸 DBAPI 连接套上 wrap_conn（双底座兼容）。

问题
----
项目已有完整兼容层 `services/dbapi_compat.py`（含 `wrap_conn`），
它能把 SQLite 风格的 SQL（`?` 占位符 / `executescript` / `lastrowid` /
`INSERT OR IGNORE` / `IFNULL`）在 PostgreSQL 下透明改写后执行。

但迁移**只做了一半**：实测 146 处取连接点中，72 处已包 `wrap_conn`，
约 74 处仍是裸连接，例如

    conn = db_session.connection().connection      # ← 未包装
    conn.execute("... WHERE status = ?", ("active",))
    → psycopg.ProgrammingError: the query has 0 placeholders but 1 parameters

修复方式极简且低风险：只把**取连接那一行**改写为

    conn = wrap_conn(db_session.connection().connection)

SQL 文本、业务逻辑一律不动 —— 正因为兼容层在 execute 时才改写，
所以 SQLite 路径行为完全不变（wrap_conn 对 SQLite 直通原对象）。

安全设计
--------
1. 只匹配 `xxx.connection().connection` 赋值/传参形态，且该行未含 wrap_conn；
2. 自动识别接收者变量名（db / db_session / session …），保持原样；
3. 补 `from services.dbapi_compat import wrap_conn` 导入（按相对层级调整前缀）；
4. dry-run 默认；--apply 备份；改完逐文件 `py_compile` 语法校验。

**不改** scripts/ 下的一次性脚本：它们是历史运维脚本，
执行环境多为当时的 SQLite，改动收益低而验证成本高。
"""
from __future__ import annotations

import argparse
import os
import py_compile
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(r"D:\平台\backend-main-fastapi")
TARGET_DIRS = ("routers", "services", "core")

#: 形如 conn = db.connection().connection  /  xxx = db_session.connection().connection
ASSIGN_RE = re.compile(
    r"^(?P<indent>\s*)(?P<lhs>\w+)\s*=\s*(?P<recv>\w+)\.connection\(\)\.connection\s*$",
    re.M,
)
#: 作为实参传递：fn(db.connection().connection, ...)
ARG_RE = re.compile(r"(?<!wrap_conn\()(?<!\.)\b(?P<recv>\w+)\.connection\(\)\.connection")


def comment_lines(text: str) -> set[int]:
    """返回注释行行号集合（用于跳过被注释掉的代码）。"""
    out = set()
    for i, ln in enumerate(text.split("\n"), 1):
        s = ln.strip()
        if s.startswith("#"):
            out.add(i)
    return out


def migrate(text: str) -> tuple[str, int]:
    """返回 (新文本, 改动数)。"""
    lines = text.split("\n")
    commented = comment_lines(text)
    n = 0
    for i, ln in enumerate(lines):
        if (i + 1) in commented:
            continue
        if "wrap_conn" in ln:
            continue

        m = ASSIGN_RE.match(ln)
        if m:
            lines[i] = (
                f"{m.group('indent')}{m.group('lhs')} = "
                f"wrap_conn({m.group('recv')}.connection().connection)"
            )
            n += 1
            continue

        if ARG_RE.search(ln):
            lines[i] = ARG_RE.sub(lambda mm: f"wrap_conn({mm.group(0)})", ln)
            n += 1

    out = "\n".join(lines)
    if n:
        out = ensure_import(out)
    return out, n


def ensure_import(text: str) -> str:
    """补 wrap_conn 导入（若尚无）。"""
    if re.search(r"^\s*from\s+[\w.]*dbapi_compat\s+import", text, re.M):
        # 已有导入，确保含 wrap_conn
        def add(m):
            names = m.group(2)
            if "wrap_conn" in names:
                return m.group(0)
            return f"{m.group(1)}{names.rstrip()}, wrap_conn"
        return re.sub(
            r"(^\s*from\s+[\w.]*dbapi_compat\s+import\s+)([^\n]+)", add, text, count=1, flags=re.M
        )

    depth = text.count("\n")
    # 按文件所在层级决定相对路径
    if "Path(__file__)" in text:
        pass
    rel = "from services.dbapi_compat import wrap_conn"
    # services/ 内部子包（如 services/kaoyan/x.py）需要上跳一级
    anchor = re.search(r"^from\s+\.\.?[\w.]*\s+import|^from\s+services", text, re.M)

    # 插到最后一个 import 之后
    imports = list(re.finditer(r"^(?:from|import)\s+[^\n]+$", text, re.M))
    if not imports:
        return text
    last = imports[-1]
    return text[: last.end()] + f"\n{rel}" + text[last.end():]


def detect_prefix(path: Path) -> str:
    """按文件位置推断 dbapi_compat 的导入路径。"""
    parts = path.relative_to(ROOT).parts
    if parts[0] == "services":
        # services/x.py → services.dbapi_compat；services/kaoyan/x.py 同样可用绝对导入
        return "from services.dbapi_compat import wrap_conn"
    return "from services.dbapi_compat import wrap_conn"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    plan = []
    for d in TARGET_DIRS:
        for root, dirs, files in os.walk(ROOT / d):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = Path(root) / f
                if p.name == "dbapi_compat.py":
                    continue
                t = p.read_text(encoding="utf-8", errors="ignore")
                if "dbapi_compat import" in t and "wrap_conn(" in t:
                    continue
                new, n = migrate(t)
                if n:
                    # 用正确的导入路径重写
                    new = re.sub(
                        r"^from services\.dbapi_compat import wrap_conn$",
                        detect_prefix(p), new, flags=re.M,
                    )
                    plan.append((p, n, new))

    print("=" * 68)
    print("裸连接 → wrap_conn（双底座兼容）")
    print("=" * 68)
    print(f"  待处理 {sum(n for _, n, _ in plan)} 处 / {len(plan)} 文件\n")
    for p, n, _ in sorted(plan, key=lambda x: -x[1]):
        print(f"  {n:>3}  {p.relative_to(ROOT)}")

    if not args.apply:
        print("\n[预览模式] 未修改文件。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = ROOT / f"_wrapconn_backup_{stamp}"
    done = 0
    failed = []
    for p, n, new in plan:
        rel = p.relative_to(ROOT)
        dest = bak / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        p.write_text(new, encoding="utf-8")
        # 语法校验
        try:
            py_compile.compile(str(p), doraise=True, cfile=tempfile.mktemp())
            done += 1
        except py_compile.PyCompileError as e:
            shutil.copy2(dest, p)          # 回滚该文件
            failed.append((rel, str(e)[:120]))

    print(f"\n备份：{bak}")
    print(f"已处理 {done} 个文件")
    if failed:
        print(f"语法失败已回滚 {len(failed)} 个：")
        for r, e in failed:
            print(f"  ✗ {r}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
