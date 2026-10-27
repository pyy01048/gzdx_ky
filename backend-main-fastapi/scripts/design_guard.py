# -*- coding: utf-8 -*-
"""设计系统合规门禁：一次扫描全部 UI 铁律违规。

检查项（对应 tokens.css 的使用铁律 + 团队 P0 规则）
--------------------------------------------------
  P0-1  emoji 作功能图标          → 禁止（UGC / AI 消息文本除外）
  P0-2  紫→粉渐变主视觉            → 禁止（#7C3AED / #A855F7 / #EC4899 及其组合）
  P0-3  弹跳缓动                   → 禁止 cubic-bezier(0.68,-0.55,0.265,1.55)
       内联 style 裸 hex          → 禁止（唯一例外 #fff / #000）
       业务 CSS 裸 hex            → 禁止（tokens.css 自身除外）
       var() 内裸 hex 回退值      → 禁止（令牌已定义，回退值只会误导）
       未定义令牌引用              → 禁止（引用了 tokens.css 里不存在的变量）

退出码：0 = 全部门禁通过；1 = 存在 Blocker。

用法：
    python scripts/design_guard.py            # 扫描并报告
    python scripts/design_guard.py --json     # 输出 JSON（供 CI 消费）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SRC = Path(r"D:\平台\frontend\src")
TOKENS_CSS = SRC / "styles" / "tokens.css"

#: 扫描时排除的目录
EXCLUDE_DIRS = {"node_modules", "_removed", "dist", ".vite", "test"}
#: 允许的 hex 例外
ALLOWED_HEX = {"#fff", "#ffffff", "#000", "#000000"}
#: 明令禁止的紫粉系
FORBIDDEN_PURPLE = {"#7c3aed", "#a855f7", "#ec4899", "#8b5cf6", "#667eea", "#764ba2"}
#: 禁止的弹跳缓动
BOUNCE = "cubic-bezier(0.68"

#: 「文字模拟图标」检测：把图标写成文字前缀（旧版遗留），如 "清单 题库列表"、"卡包 卡包"。
#: 特征：短词（2-4 字）+ 空格 + 后续文字，且短词属于常见图标词表。
#: 观感差、易写出重复（实测出现 "卡包 卡包"），且无法随主题变色。
FAKE_ICON_WORDS = ("地图", "清单", "统计", "资料", "卡包", "记录", "导航", "模块",
                   "对话", "快速", "重点", "工具", "设置", "数据", "图标", "目录", "文字")
FAKE_ICON_RE = re.compile(
    r"['\"“](?:" + "|".join(FAKE_ICON_WORDS) + r")[ 　][^'\"”]{2,18}['\"”]"
)

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF\ufe0f"
    "\U0001FA00-\U0001FAFF]"
)
HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
STYLE_RE = re.compile(r"style=\{\{.*?\}\}", re.S)
VAR_HEX_FALLBACK_RE = re.compile(r"var\(--[a-z0-9-]+,\s*#[0-9a-fA-F]{3,6}\)")
VAR_USE_RE = re.compile(r"var\(\s*(--[a-z0-9-]+)")

#: emoji 检查豁免文件：AI 对话消息、错误提示、测试
EMOJI_EXEMPT = {"Assistant.jsx", "GlobalAI.jsx"}


def iter_files(exts: tuple[str, ...]) -> list[Path]:
    """收集待扫文件。

    关键：必须排除**所有迁移备份目录**（`_*_backup*`）。
    实测踩坑：早期只列了 `_migration_backup` / `_color_backup`，
    后续新增的 `_spacing_backup_*` 未被排除，导致门禁把备份里的旧代码
    也算作违规，违规数从 5 虚增到 52 —— 门禁一旦误报就失去可信度。
    因此这里改为前缀规则 `_` + 含 `backup`，覆盖全部备份目录。
    """
    out: list[Path] = []
    for root, dirs, names in os.walk(SRC):
        dirs[:] = [d for d in dirs
                   if d not in EXCLUDE_DIRS
                   and not (d.startswith("_") and "backup" in d)
                   and d != "_removed"]
        for n in names:
            if n.endswith(exts) and ".bak" not in n:
                out.append(Path(root) / n)
    return out


def defined_tokens() -> set[str]:
    """收集 tokens.css 中定义的所有令牌名。

    注意：tokens.css 存在「一行定义多个变量」的紧凑写法
    （如 `--text-base: 14px;  --lh-base: 20px;`），所以不能用
    `^\\s*(--x):` 这种行首锚定正则，必须扫描整行中的所有定义。
    """
    if not TOKENS_CSS.exists():
        return set()
    text = TOKENS_CSS.read_text(encoding="utf-8")
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", text))


def strip_comments(text: str, is_css: bool) -> str:
    """去掉注释，避免把注释里的示例令牌名（如 var(--xx)）当成真实引用误报。"""
    if is_css:
        return re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    # JSX/JS：去掉 // 行注释与 /* */ 块注释（简化处理，够用即可）
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def main() -> int:
    ap = argparse.ArgumentParser(description="设计系统合规门禁")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    tokens = defined_tokens()
    jsx_files = iter_files((".jsx", ".js"))
    css_files = [f for f in iter_files((".css",)) if f.name != "tokens.css"]

    findings: dict[str, list[dict]] = {
        "emoji_icon": [], "forbidden_purple": [], "bounce_easing": [],
        "inline_bare_hex": [], "css_bare_hex": [], "var_hex_fallback": [],
        "undefined_token": [], "fake_icon_text": [],
    }

    # ---- JSX / JS ----
    for fp in jsx_files:
        text = fp.read_text(encoding="utf-8", errors="ignore")
        rel = str(fp.relative_to(SRC))

        if fp.name not in EMOJI_EXEMPT:
            for m in EMOJI_RE.finditer(text):
                findings["emoji_icon"].append(
                    {"file": rel, "char": m.group(), "pos": m.start()})

        clean = strip_comments(text, False)
        low = clean.lower()
        for c in FORBIDDEN_PURPLE:
            if c in low:
                findings["forbidden_purple"].append({"file": rel, "color": c})
        if BOUNCE in clean:
            findings["bounce_easing"].append({"file": rel})

        # 文字模拟图标（如 "清单 题库列表"）：排除代码标识符与 URL
        for fm in FAKE_ICON_RE.finditer(clean):
            findings["fake_icon_text"].append(
                {"file": rel, "text": fm.group().strip("'\"“”")})

        for i, line in enumerate(text.splitlines(), 1):
            if "style={{" in line:
                for c in HEX_RE.findall(line):
                    if c.lower() not in ALLOWED_HEX:
                        findings["inline_bare_hex"].append(
                            {"file": rel, "line": i, "color": c})

        for m in VAR_USE_RE.finditer(strip_comments(text, False)):
            if m.group(1) not in tokens:
                findings["undefined_token"].append(
                    {"file": rel, "token": m.group(1)})

    # ---- CSS ----
    for fp in css_files:
        text = fp.read_text(encoding="utf-8", errors="ignore")
        rel = str(fp.relative_to(SRC))

        clean = strip_comments(text, True)
        low = clean.lower()
        for c in FORBIDDEN_PURPLE:
            if c in low:
                findings["forbidden_purple"].append({"file": rel, "color": c})
        if BOUNCE in clean:
            findings["bounce_easing"].append({"file": rel})

        for m in VAR_HEX_FALLBACK_RE.finditer(clean):
            findings["var_hex_fallback"].append({"file": rel, "snippet": m.group()})
        for m in HEX_RE.finditer(text):
            if m.group().lower() not in ALLOWED_HEX:
                findings["css_bare_hex"].append({"file": rel, "color": m.group()})
        for m in VAR_USE_RE.finditer(strip_comments(text, True)):
            if m.group(1) not in tokens:
                findings["undefined_token"].append({"file": rel, "token": m.group(1)})

    # ---- 去重 ----
    findings["undefined_token"] = list({
        (d["file"], d["token"]): d for d in findings["undefined_token"]
    }.values())

    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
        return 0 if not any(findings.values()) else 1

    labels = {
        "emoji_icon": "P0-1 emoji 作功能图标",
        "forbidden_purple": "P0-2 紫粉系违规",
        "bounce_easing": "P0-3 弹跳缓动",
        "inline_bare_hex": "内联 style 裸 hex",
        "css_bare_hex": "业务 CSS 裸 hex",
        "var_hex_fallback": "var() 裸 hex 回退值",
        "undefined_token": "未定义令牌引用",
        "fake_icon_text": "文字模拟图标",
    }
    print("=" * 64)
    print("设计系统合规门禁")
    print("=" * 64)
    total = 0
    for k, label in labels.items():
        items = findings[k]
        total += len(items)
        mark = "PASS" if not items else f"FAIL ({len(items)})"
        print(f"  {label:<26} {mark}")
        for it in items[:4]:
            print(f"      {it}")
        if len(items) > 4:
            print(f"      ... 另有 {len(items) - 4} 项")

    print("-" * 64)
    print(f"  违规合计：{total}")
    print(f"  退出码：{0 if total == 0 else 1}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
