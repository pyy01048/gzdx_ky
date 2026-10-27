# -*- coding: utf-8 -*-
"""内联硬编码色值 → 设计令牌 清理（设计系统铁律：业务代码禁裸 hex）。

背景
----
tokens.css 使用铁律第 1 条：「业务 CSS / 内联 style 禁止出现裸 hex，
一律 var(--token)。唯一例外 #fff / #000」。

实测 src/ 内联 style 中有 45 处硬编码色值、24 种颜色，均是旧配色残留
（如 #16a34a 旧绿、#ef4444 旧红、#c0392b 旧危险色），与当前令牌体系脱节。
后果：改主题色时这些地方不变色，界面出现「两种绿」「两种红」。

映射依据
--------
按**语义**映射到 tokens.css 既有令牌，而非按色相近似：
  · 成功/做对类绿 → var(--success) / var(--success-ink) / var(--success-soft)
  · 错误/做错类红 → var(--danger)  / var(--danger-ink)  / var(--danger-soft)
  · 警告类橙黄   → var(--warn)    / var(--warn-ink)    / var(--warn-soft)
  · 中性灰       → var(--muted)

安全设计：
  · 只改 `style={{...}}` 内的字面量，不碰 className / CSS 文件
  · 保留 #fff / #000（令牌铁律明确允许）
  · 默认 dry-run；--apply 前逐文件备份
  · 替换后复核：内联 style 中非白黑色值应为 0
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

# 路径按本文件位置推导（P0-B2：拆除机器专属绝对路径绑定）
_REPO = Path(__file__).resolve().parents[2]
SRC_ROOT = _REPO / "frontend" / "src"

#: 裸 hex → 令牌（按语义映射，不是色相近似）
COLOR_MAP: dict[str, str] = {
    # ---- 成功 / 正面 绿系 ----
    "#16a34a": "var(--success)",
    "#15803d": "var(--success-ink)",
    "#dcfce7": "var(--success-soft)",
    "#86efac": "var(--success-border)",
    "#166534": "var(--success-ink)",
    # ---- 错误 / 负面 红系 ----
    "#ef4444": "var(--danger)",
    "#c0392b": "var(--danger)",
    "#e74c3c": "var(--danger)",
    "#f56c6c": "var(--danger)",
    "#b91c1c": "var(--danger-ink)",
    "#991b1b": "var(--danger-ink)",
    "#fef2f2": "var(--danger-soft)",
    "#fecaca": "var(--danger-border)",
    # ---- 警告 橙黄系 ----
    "#ad6800": "var(--warn-ink)",
    "#b45309": "var(--warn-ink)",
    "#7a5b00": "var(--warn-ink)",
    "#f0b429": "var(--warn)",
    "#fff7e6": "var(--warn-soft)",
    "#fff8e1": "var(--warn-soft)",
    "#ffe1a8": "var(--warn-border)",
    # ---- 中性 ----
    "#6b7280": "var(--muted)",
    # ---- 品牌蓝（旧值 → 现令牌）----
    "#2b5a9e": "var(--accent)",
    "#3a6fb8": "var(--accent-hover)",
}

#: 明确允许保留的例外（令牌铁律）
ALLOWED = {"#fff", "#ffffff", "#000", "#000000"}

STYLE_RE = re.compile(r"style=\{\{.*?\}\}", re.S)
HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")


def iter_jsx() -> list[Path]:
    out: list[Path] = []
    for root, dirs, names in os.walk(SRC_ROOT):
        dirs[:] = [d for d in dirs
                   if d not in ("node_modules", "_removed", "dist")
                   and not d.startswith("_migration_backup")]
        for n in names:
            if n.endswith((".jsx", ".js")) and ".bak" not in n:
                out.append(Path(root) / n)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="内联硬编码色值清理")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    files = iter_jsx()
    hits: list[tuple[Path, str, str]] = []   # (文件, 原色, 新令牌)
    unknown: dict[str, int] = {}

    for fp in files:
        text = fp.read_text(encoding="utf-8", errors="ignore")
        for block in STYLE_RE.findall(text):
            for c in HEX_RE.findall(block):
                lc = c.lower()
                if lc in ALLOWED:
                    continue
                if lc in COLOR_MAP:
                    hits.append((fp, c, COLOR_MAP[lc]))
                else:
                    unknown[lc] = unknown.get(lc, 0) + 1

    print("=" * 66)
    print("内联硬编码色值 → 设计令牌")
    print("=" * 66)
    print(f"  扫描文件：{len(files)}")
    print(f"  可替换：{len(hits)} 处")
    print(f"  未映射（需人工判断）：{len(unknown)} 种")

    from collections import Counter
    c1 = Counter(f"{old} → {new}" for _f, old, new in hits)
    print("\n  替换明细：")
    for k, v in c1.most_common(30):
        print(f"    {v:>3}  {k}")

    if unknown:
        print("\n  未映射色值（保留原样，待人工确认）：")
        for k, v in sorted(unknown.items(), key=lambda x: -x[1]):
            print(f"    {v:>3}  {k}")

    if not args.apply:
        print("\n[预览模式] 未修改文件。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = SRC_ROOT / f"_color_backup_{stamp}"
    bak.mkdir(exist_ok=True)

    changed = 0
    for fp in files:
        text = fp.read_text(encoding="utf-8")
        original = text

        def fix_block(m: re.Match) -> str:
            block = m.group()
            for old_hex, token in COLOR_MAP.items():
                # 只替换 style 块内的裸 hex（大小写不敏感）
                block = re.sub(re.escape(old_hex), token, block, flags=re.I)
            return block

        text = STYLE_RE.sub(fix_block, text)
        if text != original:
            rel = fp.relative_to(SRC_ROOT)
            dest = bak / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fp, dest)
            fp.write_text(text, encoding="utf-8")
            changed += 1

    print(f"\n备份目录：{bak}")
    print(f"已处理 {changed} 个文件")

    # 复核
    left = 0
    for fp in files:
        t = fp.read_text(encoding="utf-8", errors="ignore")
        for block in STYLE_RE.findall(t):
            for c in HEX_RE.findall(block):
                if c.lower() not in ALLOWED:
                    left += 1
    print(f"复核：内联 style 中剩余非白黑色值 {left} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
