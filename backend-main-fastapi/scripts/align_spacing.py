# -*- coding: utf-8 -*-
"""内联间距/字号数值 → 设计令牌（4pt 网格对齐）。

审查发现（2026-10 实测）
------------------------
内联 margin/padding 共 300+ 处，其中 **98 处不是 4 的倍数**：

    6px×44   10px×23   14px×11   18px×11   2px×5   11px×2   9px×1   7px×1

人眼对**重复的间距韵律**高度敏感：一旦数字不成体系，界面就会「说不清哪里怪」。
同理字号出现 13.5px 这类半像素值，说明是手调而非取自令牌阶梯。

映射策略（就近对齐到 4pt 网格，而非精确等值）
----------------------------------------------
  2  → 4    (--space-1)
  6  → 8    (--space-1 的 2 倍语义；用 4/8 阶梯中最接近且不小于原值的)
  7  → 8
  9  → 8
  10 → 12   (--space-3)
  11 → 12
  14 → 16   (--space-4)
  18 → 20   (--space-5)
其余已是 4 倍数的不动（4/8/12/16/20/24/32/40/48/64 均已在阶梯内）。

**就近规则**：绝对值差相等时取较大值 —— 宁可略宽松，不要挤压。
这一点对中文排版尤为重要：中文没有词间空格，行距偏紧会显著降低可读性。

安全设计：
  · 只改**内联 style 中的数字字面量**，不动 CSS 文件（CSS 侧走令牌已有基础）
  · 不碰 0 / auto / 百分比 / 含 var() 的表达式
  · 不碰 width/height/minWidth 等尺寸属性（只处理 margin/padding/gap）
  · 默认 dry-run；--apply 前逐文件备份
  · 字号单列处理：13.5 → var(--text-sm)，12 → var(--text-xs)，14 → var(--text-base)
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
SRC = _REPO / "frontend" / "src"

#: 间距：非 4 倍数 → 就近 4pt 网格值
SPACE_FIX = {2: 4, 6: 8, 7: 8, 9: 8, 10: 12, 11: 12, 14: 16, 18: 20, 22: 24, 26: 24}

#: 间距 px → 令牌（覆盖 tokens.css 的 --space-* 阶梯）
SPACE_TOKEN = {
    4: "var(--space-1)", 8: "var(--space-2)", 12: "var(--space-3)",
    16: "var(--space-4)", 20: "var(--space-5)", 24: "var(--space-6)",
    32: "var(--space-8)", 40: "var(--space-10)", 48: "var(--space-12)",
    64: "var(--space-16)",
}

#: 字号：手调值 → 令牌阶梯
#: tokens.css 阶梯：--text-xs=12 / --text-sm=13 / --text-base=14 /
#: --text-md=17 / --text-lg=20 / --text-xl=24 / --text-2xl=clamp(28..36)
#: 实测还散落 10/11/12.5/12.8/13.5/15/16/18/19/22/26/30/32/36/40/48 等手调值，
#: 一律就近归入阶梯。小于 12 的（10/11）归 xs —— 中文正文低于 12px 已不可读，
#: 这些多是给紧凑徽标用的，保持最小值即可。
FONT_FIX = {
    "10": "var(--text-xs)", "11": "var(--text-xs)", "11.5": "var(--text-xs)",
    "12": "var(--text-xs)", "12.5": "var(--text-xs)", "12.8": "var(--text-xs)",
    "13": "var(--text-sm)", "13.5": "var(--text-sm)",
    "14": "var(--text-base)", "15": "var(--text-base)", "16": "var(--text-md)",
    "17": "var(--text-md)", "18": "var(--text-md)", "19": "var(--text-lg)",
    "20": "var(--text-lg)", "22": "var(--text-xl)", "24": "var(--text-xl)",
    "26": "var(--text-2xl)", "28": "var(--text-2xl)", "30": "var(--text-2xl)",
    "32": "var(--text-2xl)", "36": "var(--text-3xl)", "40": "var(--text-3xl)",
    "48": "var(--text-3xl)",
}

#: 只处理这些 CSS 属性
SPACE_PROPS = ("margin", "marginTop", "marginBottom", "marginLeft", "marginRight",
               "padding", "paddingTop", "paddingBottom", "paddingLeft", "paddingRight",
               "gap", "rowGap", "columnGap")

STYLE_RE = re.compile(r"style=\{\{(.*?)\}\}", re.S)


def iter_files() -> list[Path]:
    out: list[Path] = []
    for root, dirs, names in os.walk(SRC):
        dirs[:] = [d for d in dirs
                   if d not in ("node_modules", "_removed", "dist")
                   and not d.startswith(("_migration_backup", "_color_backup", "_spacing_backup"))]
        for n in names:
            if n.endswith((".jsx", ".js")) and ".bak" not in n:
                out.append(Path(root) / n)
    return out


def fix_block(block: str) -> tuple[str, int]:
    """修正单个 style={{...}} 块内的间距与字号。返回 (新块, 改动数)。"""
    out = block
    n = 0

    # ---- 间距：先归一非 4 倍数，再统一换成令牌 ----
    # 支持三种写法：prop: 14 / prop: '14px' / prop: '8px 0 0'（简写）
    # 统一目标：prop: 'var(--space-N)' —— 值一律走令牌，不再出现裸数字。
    #
    # 关键（实测踩坑）：简写里的 0 必须保留在**引号内**。
    # 早期实现逐段替换时把 0 落在引号外，产出
    #   margin: 'var(--space-2)' 0 0'   ← 语法错误，构建失败。
    # 因此这里一次性重写整个值字符串。
    pat_num = re.compile(
        rf"\b({'|'.join(SPACE_PROPS)})\s*:\s*'([\d\s]*px[\d\spx]*|\d+(?:\s+\d+)*)'(?=\s*[,}}]|\s*$)"
    )

    def repl_space(m: re.Match) -> str:
        nonlocal n
        prop, raw = m.group(1), m.group(2).strip()
        if not raw or re.search(r"[a-zA-Z(]", raw.replace("px", "")):
            return m.group()
        parts = raw.replace("px", "").split()
        if not all(p.isdigit() for p in parts):
            return m.group()
        out_parts = []
        for p in parts:
            v = int(p)
            if v == 0:
                out_parts.append("0")          # 0 保留在引号内
                continue
            v = SPACE_FIX.get(v, v)
            tok = SPACE_TOKEN.get(v)
            out_parts.append(tok or f"{v}px")
        n += 1
        return f"{prop}: '{' '.join(out_parts)}'"

    out = pat_num.sub(repl_space, out)

    # ---- 无引号单值：marginTop: 6 / gap: 18 ----
    # 组 1 必须**连冒号一起捕获**，否则回填时冒号丢失，
    # 产出 marginBottom'var(--space-4)' 这种语法错误（实测踩坑）。
    pat_bare = re.compile(rf"(\b({'|'.join(SPACE_PROPS)})\s*:\s*)(\d+)(?=\s*[,}}]|\s*$)")

    def repl_bare(m: re.Match) -> str:
        nonlocal n
        v = int(m.group(3))
        if v == 0:
            return m.group()
        tok = SPACE_TOKEN.get(SPACE_FIX.get(v, v))
        if not tok:
            return m.group()
        n += 1
        return f"{m.group(2)}: '{tok}'"

    out = pat_bare.sub(repl_bare, out)

    # ---- 字号：fontSize: <数字> ----
    # 支持带引号（'13'）与不带引号（13）两种写法。
    # 关键：JS 对象里 fontSize 的值**必须带引号**，写成
    #   fontSize: var(--text-xs)   ← 语法错误（esbuild 报 Unexpected "var"）
    #   fontSize: 'var(--text-xs)' ← 正确
    # 因此无论原值是否带引号，替换结果一律带引号（实测踩坑：漏加引号构建失败）。
    pat = re.compile(r"(fontSize\s*:\s*)'?([\d.]+)'?(?=\s*[,}}]|\s*$)")

    def repl_font(m: re.Match) -> str:
        nonlocal n
        raw = m.group(2)
        if raw not in FONT_FIX:
            return m.group()
        n += 1
        return f"{m.group(1)}'{FONT_FIX[raw]}'"

    out = pat.sub(repl_font, out)
    return out, n


def main() -> int:
    ap = argparse.ArgumentParser(description="内联间距/字号对齐 4pt 网格")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    files = iter_files()
    total = 0
    changed_files: list[tuple[Path, int]] = []

    for fp in files:
        text = fp.read_text(encoding="utf-8", errors="ignore")
        cnt = 0

        def repl(m: re.Match) -> str:
            nonlocal cnt
            new_block, k = fix_block(m.group(1))
            cnt += k
            return f"style={{{{{new_block}}}}}"

        new_text = STYLE_RE.sub(repl, text)
        if cnt:
            changed_files.append((fp, cnt))
            total += cnt
            if args.apply:
                pass

    print("=" * 66)
    print("内联间距 / 字号 → 4pt 网格对齐")
    print("=" * 66)
    print(f"  扫描文件：{len(files)}")
    print(f"  待修正：{total} 处（{len(changed_files)} 个文件）\n")
    for fp, k in sorted(changed_files, key=lambda x: -x[1])[:14]:
        print(f"  {k:>4}  {fp.relative_to(SRC)}")

    if not args.apply:
        print("\n[预览模式] 未修改文件。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = SRC / f"_spacing_backup_{stamp}"
    bak.mkdir(exist_ok=True)

    done = 0
    for fp in files:
        text = fp.read_text(encoding="utf-8")
        cnt = 0

        def repl(m: re.Match) -> str:
            nonlocal cnt
            new_block, k = fix_block(m.group(1))
            cnt += k
            return f"style={{{{{new_block}}}}}"

        new_text = STYLE_RE.sub(repl, text)
        if cnt:
            rel = fp.relative_to(SRC)
            dest = bak / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fp, dest)
            fp.write_text(new_text, encoding="utf-8")
            done += 1

    print(f"\n备份目录：{bak}")
    print(f"已处理 {done} 个文件")

    # 复核：非 4 倍数的内联间距应为 0
    left = 0
    for fp in files:
        t = fp.read_text(encoding="utf-8", errors="ignore")
        for m in STYLE_RE.findall(t):
            for prop in SPACE_PROPS:
                for mm in re.finditer(rf"\b{prop}\s*:\s*(\d+)\s*[,}}]", m):
                    if int(mm.group(1)) % 4 != 0:
                        left += 1
    print(f"复核：剩余非 4 倍数内联间距 {left} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
