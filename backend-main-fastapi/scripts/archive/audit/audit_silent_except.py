"""静默异常审计（`except ...: pass` 分级报告）。

## 为什么做这个

项目血泪教训 #1 就是"静默 except 是最贵的 bug"：曾经因为
`except Exception: pass` 吞掉建表失败，症状漂移到 190+ 个用例 ERROR、
排查成本极高。同类问题后续又在 `qa_foundation`（weak_knowledge /
answer_review_queue 表从未建出）和 `confidence_service`
（provenance / reviewed 列永远建不出来）各踩一次。

但"一刀切全改"也不对 —— 大量 pass 是**合理的**：
  * 惰性导入兜底（可选依赖没装）
  * "列/索引已存在" 这类幂等 DDL
  * 浏览器隐私模式下的 localStorage 写入
  * 探测型查询（表不存在就按空处理）

所以本工具**不判生死，只做分级**，把"无理由的裸吞"挑出来给人看。

## 分级规则

  HIGH —— **宽泛**异常（`except:` / `except Exception:`）+ `pass`，
          且所在块没有任何注释解释。这类最危险：将来任何异常都会被无声
          吞掉，且没人知道为什么。
  LOW  —— 收窄了异常类型的（`except OSError:` / `except sqlite3.Error:`），
          或带注释说明理由的。
          注意：**收窄类型本身就是一种"理由"** —— 例如
          `services/answer_cache.py` 操作独立 SQLite 文件，
          捕获 `sqlite3.Error` 是精确的，不该算 HIGH。
          （本条规则是被它纠正后才加上的：早期版本把它 6 处判成 HIGH，误报。）

## 用法

    python scripts/audit_silent_except.py              # 全部
    python scripts/audit_silent_except.py --high-only  # 只看 HIGH
    python scripts/audit_silent_except.py --json       # 机器可读
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("services", "routers")

_EXCEPT = re.compile(r"^(\s*)except\b[^:]*:\s*(#.*)?$")


def _has_reason(lines: list[str], idx: int) -> bool:
    """判断这个 except 是否有"理由说明"。

    看三处：except 行自身的行尾注释、其上方紧邻的注释行、pass 行自身的注释。
    """
    if "#" in lines[idx].split(":", 1)[-1]:
        return True
    # 上方紧邻注释
    j = idx - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j >= 0 and lines[j].strip().startswith("#"):
        return True
    # pass 行自身注释
    for k in range(idx + 1, min(idx + 3, len(lines))):
        body = lines[k]
        if body.strip() == "pass":
            return "#" in body
        if body.strip() and not body.strip().startswith("#"):
            break
    return False


def _find_pass_body(lines: list[str], idx: int) -> int | None:
    """返回 pass 所在行号；不是裸 pass 返回 None。"""
    for k in range(idx + 1, min(idx + 4, len(lines))):
        stripped = lines[k].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "pass":
            return k
        return None
    return None


def scan() -> list[dict]:
    out: list[dict] = []
    for d in SCAN_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            if "_backup_" in str(p):
                continue
            try:
                lines = io.open(p, encoding="utf-8").read().splitlines()
            except Exception:  # noqa: BLE001
                continue
            for i, ln in enumerate(lines):
                m = _EXCEPT.match(ln)
                if not m:
                    continue
                pl = _find_pass_body(lines, i)
                if pl is None:
                    continue
                reason = _has_reason(lines, i)
                # 收窄了异常类型的也算"有理由"：类型本身就是筛选意图的表达
                narrowed = not re.match(
                    r"^\s*except\s*(Exception)?\s*(as\s+\w+)?\s*:", ln
                )
                out.append({
                    "file": str(p.relative_to(ROOT)),
                    "line": i + 1,
                    "except": ln.strip()[:100],
                    "severity": "LOW" if (reason or narrowed) else "HIGH",
                })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="静默异常审计")
    ap.add_argument("--high-only", action="store_true", help="只列出 HIGH")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    items = scan()
    high = [x for x in items if x["severity"] == "HIGH"]
    low = [x for x in items if x["severity"] == "LOW"]

    if args.json:
        print(json.dumps({"high": high, "low": low, "total": len(items)},
                         ensure_ascii=False, indent=2))
        return 0

    show = high if args.high_only else items
    print("=" * 72)
    print(f"静默异常审计：共 {len(items)} 处（HIGH {len(high)} / LOW {len(low)}）")
    print("=" * 72)
    cur = None
    for it in show:
        if it["file"] != cur:
            cur = it["file"]
            print(f"\n{cur}")
        print(f"  [{it['severity']}] L{it['line']:<5} {it['except']}")
    print()
    print("-" * 72)
    print("HIGH = except Exception + pass 且**没有任何说明** —— 建议补注释或留痕日志。")
    print("LOW  = 有注释说明理由；仍建议复核理由是否还成立。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
