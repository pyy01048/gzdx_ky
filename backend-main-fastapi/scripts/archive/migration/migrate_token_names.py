# -*- coding: utf-8 -*-
"""旧设计令牌名 → 新令牌名 全量替换（tokens.css 迁移收尾第二步）。

背景
----
tokens.css 已建立完整新令牌体系（304 个变量，对标 gitgraduate 纸感学术蓝），
并通过「旧变量兼容桥」把旧名映射到新令牌，保证迁移期间样式不炸。

现在做最后一步：把源码里的旧变量引用全部替换为新名。
替换完成后即可删除兼容桥，设计系统收敛为单一来源。

实测规模：50 个文件、1854 处引用。

安全设计（关键）：
  1. **只替换 var() 中的引用**，不碰变量定义（兼容桥本身、--sp-* 定义等）
     —— 否则会把兼容桥的 `--ink: var(--fg)` 改坏。
  2. **长名优先**：--ink-2 ���须在 --ink 之前替换，否则 --ink-2 会被截成 --fg-2 错位。
     实现上按名字长度倒序处理，并用负向断言排除后续是 [a-z0-9-] 的情况。
  3. 默认 dry-run，--apply 才写；写入前逐个文件备份。
  4. 替换后校验：全项目 var(--旧名) 引用数应为 0（兼容桥定义除外）。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

SRC_ROOT = Path(r"D:\平台\frontend\src")

#: 旧名 → 新令牌（与 tokens.css 兼容桥保持严格一致）
TOKEN_MAP: dict[str, str] = {
    # 颜色
    "--ink": "--fg",
    "--ink-2": "--fg-2",
    "--ink-3": "--muted",
    "--line": "--border",
    "--line-strong": "--border-strong",
    "--paper": "--surface",
    "--card": "--surface",
    "--text": "--fg",
    "--primary": "--accent",
    "--blue": "--accent",
    "--blue-soft": "--accent-soft",
    "--red": "--danger",
    "--red-soft": "--danger-soft",
    "--green": "--success",
    "--green-soft": "--success-soft",
    "--gold": "--warn",
    "--gold-soft": "--warn-soft",
    "--violet": "--chart-5",
    "--violet-soft": "--info-soft",
    "--color-success": "--success",
    "--color-warning": "--warn",
    "--color-danger": "--danger",
    "--color-error": "--danger",
    "--color-info": "--info",
    "--ring": "--focus-ring",
    # 圆角
    "--r-xs": "--radius-sm",
    "--r-sm": "--radius-sm",
    "--r-md": "--radius-md",
    "--r-lg": "--radius-xl",
    "--r-xl": "--radius-xl",
    "--r-2xl": "--radius-xl",
    "--r-full": "--radius-full",
    # 间距
    **{f"--sp-{i}": f"--space-{i}" for i in range(1, 17)},
    # 字号
    **{f"--fs-{n}": f"--text-{n}"
       for n in ("xs", "sm", "base", "md", "lg", "xl", "2xl", "3xl")},
    # 阴影（第一轮漏掉，实测复核剩余 77 处引用后补入）
    "--shadow-0": "--shadow-flat",
    "--shadow-1": "--shadow-sm",
    "--shadow-2": "--shadow-md",
    "--shadow-3": "--shadow-lg",
    "--shadow-4": "--shadow-overlay",
    # 动效时长（第二轮复核补入，剩余 103 处）
    "--dur-fast": "--motion-fast",
    "--dur-base": "--motion-base",
    "--dur-slow": "--motion-slow",
    # 字重 / 行高
    # 注意：tokens.css 的正式命名就是 --fw-* / --lh-*（第 128-130、510-512 行），
    # 这里只把兼容桥里的"二级别名"指向一级正式名。
    "--fw-bold": "--fw-semibold",
    "--lh-normal": "--lh-base",
}

#: 特殊处理：--accent-grad 在兼容桥里是「蓝→深蓝同色系渐变」（非紫粉，合规），
#: 但不能简单删掉——有 11 处在用。映射到 tokens.css 中定义的同名变量，
#: 保留视觉但统一来源。tokens.css 未定义该名时由兼容桥兜底，此处不改。
LEGACY_KEEP = {"--accent-grad"}

#: 不处理的文件（定义来源 / 备份 / 构建产物）
SKIP_NAMES = {"tokens.css", "tokens.js", "themeTokens.js"}


def build_patterns() -> list[tuple[re.Pattern, str, str]]:
    """按名字长度倒序构造替换正则，避免 --ink 吃掉 --ink-2。"""
    out: list[tuple[re.Pattern, str, str]] = []
    for old in sorted(TOKEN_MAP, key=len, reverse=True):
        new = TOKEN_MAP[old]
        # 匹配 var( --old ) 或 var( --old , fallback )，且 old 后面不是 [a-z0-9-]
        pat = re.compile(
            r"var\(\s*" + re.escape(old) + r"(?![a-z0-9-])\s*([,)])"
        )
        out.append((pat, new, old))
    return out


def iter_files() -> list[Path]:
    files: list[Path] = []
    for root, dirs, names in os.walk(SRC_ROOT):
        # 关键：必须排除迁移备份目录，否则复核会把备份里的旧引用一起数进来，
        # 误报「剩余 N 处」（实测踩坑）。
        dirs[:] = [d for d in dirs
                   if d not in ("node_modules", "_removed", "dist", ".vite")
                   and not d.startswith("_migration_backup")]
        for name in names:
            if not name.endswith((".jsx", ".js", ".css")):
                continue
            if ".bak" in name:
                continue
            if name in SKIP_NAMES:
                continue
            files.append(Path(root) / name)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="旧令牌名全量替换")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    patterns = build_patterns()
    files = iter_files()

    total_hits = 0
    per_file: list[tuple[Path, int]] = []

    for fp in files:
        try:
            text = fp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits = 0
        for pat, _new, _old in patterns:
            hits += len(pat.findall(text))
        if hits:
            per_file.append((fp, hits))
            total_hits += hits

    print("=" * 66)
    print("旧令牌名 → 新令牌名 全量替换")
    print("=" * 66)
    print(f"  扫描文件：{len(files)}")
    print(f"  待替换引用：{total_hits} 处（{len(per_file)} 个文件）\n")

    for fp, n in sorted(per_file, key=lambda x: -x[1])[:14]:
        print(f"  {n:>4}  {fp.relative_to(SRC_ROOT)}")

    if not args.apply:
        print("\n[预览模式] 未修改文件。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak_dir = SRC_ROOT / f"_migration_backup_{stamp}"
    bak_dir.mkdir(exist_ok=True)
    print(f"\n备份目录：{bak_dir}")

    changed = 0
    for fp, _n in per_file:
        text = fp.read_text(encoding="utf-8")
        original = text
        for pat, new, _old in patterns:
            text = pat.sub(lambda m, n=new: f"var({n}{m.group(1)}", text)
        if text != original:
            rel = fp.relative_to(SRC_ROOT)
            dest = bak_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fp, dest)
            fp.write_text(text, encoding="utf-8")
            changed += 1

    print(f"已替换 {changed} 个文件")

    # 复核：全项目旧引用应为 0（排除 tokens.css 兼容桥定义）
    left = 0
    for fp in iter_files():
        t = fp.read_text(encoding="utf-8", errors="ignore")
        for pat, _new, _old in patterns:
            left += len(pat.findall(t))
    print(f"复核：剩余旧引用 {left} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
