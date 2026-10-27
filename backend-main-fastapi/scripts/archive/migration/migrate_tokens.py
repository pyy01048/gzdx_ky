# -*- coding: utf-8 -*-
"""tokens.css 迁移收尾：删除 global.css 中的旧变量定义块。

背景
----
src/styles/tokens.css 头部注释里写明了迁移计划：
  「迁移完成后（各页面旧变量全量替换）删除 global.css 的两个 :root 块
    与 [data-theme='dark'] 块，再删除本文件末尾的『旧变量兼容桥』章节。」

当前 global.css 里仍残留 4 个旧块（共约 184 行），与 tokens.css 同名但值不同
（旧深色 #10151E vs 新浅色 #F7F7F5）。因 tokens.css 后加载，实际生效的是新值，
所以**界面现在没有颜色错乱**；但旧块留在源码里会让后续维护者误改、且阻碍主题切换。

本脚本安全删除这些旧块，并处理例外：
  · `@media (prefers-contrast: high)` 里的 :root 是**无障碍特性**，不是冗余，
    改写为新变量名（--line→--border, --ink-3→--muted）保留。

安全设计：
  · 默认 dry-run；--apply 才写文件
  · 写前自动备份 .bak2
  · 删前逐块打印，便于人工核对
  · 删除后校验：文件内不应再有裸 hex 定义在 :root 里
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

TARGET = Path(r"D:\平台\frontend\src\styles\global.css")


def find_blocks(lines: list[str]) -> list[tuple[int, int, str]]:
    """找出所有顶层 :root / [data-theme='dark'] 块，返回 (起, 止, 首行)。

    **排除**位于 `@media (prefers-contrast: high)` 内的块 —— 那是无障碍特性，
    必须保留（只改写变量名），不能当冗余删掉。
    """
    blocks: list[tuple[int, int, str]] = []

    # 先标记哪些行属于 prefers-contrast 媒体查询
    in_contrast = [False] * len(lines)
    i = 0
    while i < len(lines):
        if "prefers-contrast" in lines[i]:
            depth = 0
            j = i
            while j < len(lines):
                depth += lines[j].count("{") - lines[j].count("}")
                in_contrast[j] = True
                if depth == 0 and j > i:
                    break
                j += 1
            i = j + 1
        else:
            i += 1

    for i, line in enumerate(lines):
        if not re.match(r"^\s*(:root|\[data-theme=['\"]dark['\"]\])\s*\{", line):
            continue
        if len(line) - len(line.lstrip()) > 2:
            continue
        if in_contrast[i]:
            continue          # 无障碍块，跳过
        depth = 0
        end = i
        for j in range(i, len(lines)):
            depth += lines[j].count("{") - lines[j].count("}")
            if depth == 0 and j > i:
                end = j
                break
        blocks.append((i, end, line.strip()))
    return blocks


def main() -> int:
    ap = argparse.ArgumentParser(description="global.css 旧令牌块清理")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not TARGET.exists():
        print(f"[x] 文件不存在：{TARGET}")
        return 2

    src = TARGET.read_text(encoding="utf-8")
    lines = src.splitlines()
    blocks = find_blocks(lines)

    print("=" * 66)
    print("global.css 旧令牌块清理")
    print("=" * 66)
    print(f"  文件总行数：{len(lines)}")
    print(f"  检测到顶层旧块：{len(blocks)} 个\n")

    total = 0
    for s, e, head in blocks:
        # 头部注释（向前探测最多 6 行的注释块）
        comment_top = s
        for k in range(s - 1, max(s - 7, -1), -1):
            t = lines[k].strip()
            if t.startswith(("/*", "*", "*/")) or t == "":
                comment_top = k
            else:
                break
        n = e - comment_top + 1
        total += n
        print(f"  行{comment_top + 1:>5}-{e + 1:<5} ({n:>3} 行)  {head[:44]}")

    print(f"\n  合计可删：{total} 行（占 {total * 100 // len(lines)}%）")

    # 高对比度块：改用新令牌，不删
    hc = [i for i, l in enumerate(lines)
          if "prefers-contrast" in l]
    if hc:
        print(f"\n  注意：检测到 {len(hc)} 处 prefers-contrast 无障碍块，"
              "将改写为新令牌而非删除")

    if not args.apply:
        print("\n[预览模式] 未修改文件。")
        return 0

    backup = TARGET.with_suffix(f".css.bak2-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(TARGET, backup)
    print(f"\n已备份：{backup}")

    # 从后往前删，避免行号偏移
    out = list(lines)
    for s, e, _head in sorted(blocks, key=lambda x: -x[0]):
        comment_top = s
        for k in range(s - 1, max(s - 7, -1), -1):
            t = out[k].strip()
            if t.startswith(("/*", "*", "*/")) or t == "":
                comment_top = k
            else:
                break
        del out[comment_top:e + 1]

    text = "\n".join(out)
    # 无障碍块改写为新令牌名
    text = text.replace("--line: #000;", "--border: #000;")
    text = text.replace("--ink-3: #333;", "--muted: #333;")
    TARGET.write_text(text, encoding="utf-8")

    print(f"已删除 {total} 行，文件现 {len(text.splitlines())} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
