# -*- coding: utf-8 -*-
"""仓库内文档相对链接校验（完善方案 12 §3.4）。

只校验"现行文档"（README / docs/README.md / docs/guides/** / docs/decisions/** /
CONTRIBUTING / SECURITY / deploy/DEPLOY.md）；历史报告归档允许失效（归档不改），
用 ``--all`` 可全量扫描但默认不作为门禁。

用法：
    python backend-main-fastapi/scripts/diagnostics/check_doc_links.py
    python .../check_doc_links.py --all
退出码：0 全部通过；1 有失效链接（CI 门禁）。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "#", "data:")

CURRENT_DOCS = [
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "deploy/DEPLOY.md",
    "docs/README.md",
]


def _current_files() -> list[Path]:
    files = [REPO / p for p in CURRENT_DOCS if (REPO / p).exists()]
    for sub in ("docs/guides", "docs/decisions"):
        d = REPO / sub
        if d.exists():
            files += sorted(d.rglob("*.md"))
    return files


def _all_files() -> list[Path]:
    files = list(REPO.glob("*.md")) + list(REPO.glob("docs/**/*.md")) + list(REPO.glob("deploy/*.md"))
    return sorted(set(files))


def check(files: list[Path]) -> list[str]:
    problems: list[str] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(f"{f}: 读取失败 {exc}")
            continue
        for m in LINK_RE.finditer(text):
            raw = m.group(1).strip()
            target = raw.split("#", 1)[0].strip()
            if not target or target.lower().startswith(SKIP_SCHEMES):
                continue
            if target.startswith("/"):  # 站内绝对路径不当仓库路径处理
                continue
            resolved = (f.parent / target).resolve()
            if not resolved.exists():
                line_no = text[: m.start()].count("\n") + 1
                problems.append(f"{f.relative_to(REPO)}:{line_no} → {raw}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="扫描全部 md（含历史归档）")
    args = ap.parse_args()

    files = _all_files() if args.all else _current_files()
    problems = check(files)
    print(f"检查 {len(files)} 个文档")
    if problems:
        print(f"[x] {len(problems)} 条失效链接：")
        for p in problems:
            print("   ", p)
        return 1
    print("[✓] 相对链接全部有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
