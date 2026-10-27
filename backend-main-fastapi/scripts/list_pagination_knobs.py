"""列出所有「无上限或上限超 MAX_PAGE_SIZE」的分页/limit 入参声明，供人工核对。

为什么不自动改：这些参数的默认值各处不同（20/50/100/200/500），自动改写容易把
默认值一起冲掉；本脚本只做定位，改由 Edit 逐处做，避免一次性大改引入语义漂移。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.response import MAX_PAGE_SIZE  # 单一口径：不在这里再写一遍 200

ROUTER_DIR = Path(__file__).resolve().parent.parent / "routers"
NAME_RE = re.compile(r"\b(limit|page_size|num|size)\s*:\s*(int|str)\s*=\s*([^,)]+)")


def main() -> int:
    total = 0
    for path in sorted(ROUTER_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in NAME_RE.finditer(line):
                name, _typ, decl = m.group(1), m.group(2), m.group(3)
                has_le = re.search(r"\ble=\d+", decl)
                if has_le and int(has_le.group()[3:]) <= MAX_PAGE_SIZE:
                    continue
                total += 1
                print(f"{path.name}:{lineno}: {name} -> {decl.strip()}  [{'le=%s' % has_le.group()[3:] if has_le else 'NO CAP'}]")
    print(f"合计 {total} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
