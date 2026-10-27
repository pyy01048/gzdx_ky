"""跨模块常量引用静态检查（防 AttributeError 类 bug）。

## 为什么需要

实际踩过：`services/learning_analytics_service.py` 写了
`kp_mastery.MASTERY_THRESHOLD`，而正典名是 `MASTERED_THRESHOLD`。
这类错误：

  * **静态不可见** —— 语法没错，import 也没错，只有执行到那一行才炸；
  * **报错信息不指向真因** —— 它被上层 `except` 包成"概览查询失败"，
    于是 /api/analytics/overview 与 /weak-points **两个端点恒 500**
    而错误日志里看不到"常量名写错"这件事；
  * **测试不易覆盖** —— 该分支依赖真实数据才会走到。

本工具把这类错误提前到"提交前就能看到"。

## 检查范围

只查**项目内模块**（services/ routers/ core/ 下的 .py）的大写常量引用，
形如 `module.CONSTANT`。理由：
  * 大写下划线命名 → 基本可以确定是模块级常量（函数/类名混进来的概率极低）；
  * 限定项目内模块 → 不误报第三方库的动态属性。

## 用法

    python scripts/audit_module_attrs.py            # 检查并报告
    python scripts/audit_module_attrs.py --json
"""

from __future__ import annotations

import argparse
import ast
import importlib
import io
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

SCAN_DIRS = ("services", "routers", "core")
MODULE_DIRS = ("services", "routers", "core")

#: 形如 `foo.BAR_BAZ`（常量引用）
_ATTR_REF = re.compile(r"\b([a-z_][a-z0-9_]*)\.([A-Z][A-Z0-9_]{2,})\b")


def _project_modules() -> dict[str, list[str]]:
    """模块名 → **候选**点分导入路径列表（只收项目内模块）。

    必须是一对多：`services/taxonomy.py` 与 `routers/taxonomy.py` 同名，
    早先版本用 `{stem: dotted}` 建映射，后者把前者**覆盖**掉，
    于是 `taxonomy.ALL_SUBJECTS` 被拿去和 routers 那个模块比 → 一片误报
    （实测 27 处里绝大多数是这么来的）。现在任一候选含该属性即算命中。
    """
    out: dict[str, list[str]] = {}
    for d in MODULE_DIRS:
        for p in (BASE_DIR / d).glob("*.py"):
            if p.stem.startswith("_"):
                continue
            out.setdefault(p.stem, []).append(f"{d}.{p.stem}")
    return out


def scan() -> list[dict]:
    mods = _project_modules()
    # 先把每个模块的属性表缓存下来（导入失败的记为 None，跳过检查）
    attrs: dict[str, list[set | None]] = {}
    for name, candidates in mods.items():
        table: list[set | None] = []
        for dotted in candidates:
            try:
                table.append(set(dir(importlib.import_module(dotted))))
            except Exception:  # noqa: BLE001
                table.append(None)
        attrs[name] = table

    findings: list[dict] = []
    for d in SCAN_DIRS:
        for p in sorted((BASE_DIR / d).rglob("*.py")):
            if "_backup_" in str(p) or p.name.startswith("_"):
                continue
            try:
                src = io.open(p, encoding="utf-8").read()
            except Exception:  # noqa: BLE001
                continue
            # 用 AST 而非正则：正则会把注释/docstring 里提到的
            # "core.db_session.VECTOR_BACKEND" 也当成真实引用（实测 2 处误报）。
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)):
                    continue
                mod, attr = node.value.id, node.attr
                if not attr.isupper():
                    continue
                if mod not in attrs or mod == p.stem:
                    continue
                known_list = attrs[mod]
                if all(k is None for k in known_list):
                    continue  # 所有候选都导入失败，无法判定
                # 任一候选模块有该属性即命中（同名模块场景）
                if any(k is not None and attr in k for k in known_list):
                    continue
                findings.append({
                    "file": str(p.relative_to(BASE_DIR)),
                    "line": node.lineno,
                    "ref": f"{mod}.{attr}",
                    "module": mod,
                })
    return findings


def _suggest(mod: str, attr: str, known: set) -> str:
    """给出最可能的正确名字（同前缀/编辑距离近的）。"""
    import difflib

    cands = difflib.get_close_matches(attr, [a for a in known
                                             if a.isupper()], n=2, cutoff=0.6)
    return "、".join(cands) if cands else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="跨模块常量引用检查")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    items = scan()
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 1 if items else 0

    print("=" * 72)
    print("跨模块常量引用检查")
    print("=" * 72)
    if not items:
        print("未发现指向不存在常量的引用。")
        return 0

    mods = _project_modules()
    for it in items:
        try:
            known = set()
            for _cand in mods[it["module"]]:
                try:
                    known |= set(dir(importlib.import_module(_cand)))
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            known = set()
        hint = _suggest(it["module"], it["ref"].split(".")[-1], known)
        print(f"\n  {it['file']}:{it['line']}")
        print(f"    引用了不存在的常量: {it['ref']}")
        if hint:
            print(f"    是否想写: {hint} ？")

    print()
    print("-" * 72)
    print(f"合计 {len(items)} 处 —— 这些会在执行到该行时抛 AttributeError，"
          "且常被上层 except 包装成无关的错误信息。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
