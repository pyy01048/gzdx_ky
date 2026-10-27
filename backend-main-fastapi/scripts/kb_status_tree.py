# -*- coding: utf-8 -*-
"""知识库目录状态前缀可视化（模块 E7）。

扫描 knowledge_base 目录树，为每个文件 / 目录标注状态前缀：
  [OK ] 已入库（manifest 命中）
  [.. ] 待入库（inbox 中且未入库）
  [!! ] 不合格（命中 invalid_inbox.jsonl）
  [?? ] 孤儿（documents 中但 manifest 未命中）

目录级前缀按子项聚合：[ALL] 全部已入库 / [PART] 部分 / [EMPTY] 空 / [NEW] 含待入库或异常。

用法：
    python scripts/kb_status_tree.py                # 终端树 + 汇总
    python scripts/kb_status_tree.py --markdown      # 额外导出 markdown 到 knowledge_base/meta/kb_status_tree.md
    python scripts/kb_status_tree.py --max-depth 2   # 限制目录深度
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

# 路径按本文件位置推导（P0-B2：拆除机器专属绝对路径绑定）
_REPO = Path(__file__).resolve().parents[2]
DEFAULT_KB_ROOT = str(_REPO / "knowledge_base")


def load_jsonl_lines(path: str) -> list[dict]:
    out = []
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def collect_state(kb_root: str) -> dict:
    docs_dir = os.path.join(kb_root, "documents")
    inbox_dir = os.path.join(kb_root, "inbox")
    meta_dir = os.path.join(kb_root, "meta")

    manifest = load_jsonl_lines(os.path.join(meta_dir, "manifest.jsonl"))
    invalid = load_jsonl_lines(os.path.join(meta_dir, "invalid_inbox.jsonl"))

    # basename 集合（按 os.path.basename 统一）
    indexed = set()
    for rec in manifest:
        fn = os.path.basename(str(rec.get("file") or rec.get("target") or ""))
        if fn:
            indexed.add(fn)
    invalid_names = set()
    for rec in invalid:
        fn = os.path.basename(str(rec.get("file") or ""))
        if fn:
            invalid_names.add(fn)

    # 扫描文件树：{相对路径: state}
    states: dict[str, str] = {}
    for base_dir, label in ((docs_dir, "documents"), (inbox_dir, "inbox")):
        if not os.path.isdir(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            for fn in sorted(files):
                rel = os.path.relpath(os.path.join(root, fn), kb_root)
                if label == "documents":
                    st = "OK" if fn in indexed else "??"
                else:
                    if fn in invalid_names:
                        st = "!!"
                    elif fn in indexed:
                        st = "OK"
                    else:
                        st = ".."
                states[rel] = st
    return {"kb_root": kb_root, "states": states,
            "indexed_count": len(indexed), "invalid_count": len(invalid_names),
            "manifest_count": len(manifest)}


def dir_agg(states: dict[str, str], kb_root: str, rel_dir: str) -> str:
    """目录聚合状态：ALL / PART / EMPTY / NEW。"""
    prefix = rel_dir.rstrip("/\\") + os.sep
    children = {k: v for k, v in states.items() if k.startswith(prefix) and k != rel_dir}
    if not children:
        return "EMPTY"
    vals = set(children.values())
    if vals == {"OK"}:
        return "ALL"
    if "!!" in vals or ".." in vals or "??" in vals:
        return "NEW"
    return "PART"


def render_tree(states: dict[str, str], kb_root: str, max_depth: int = 0) -> list[str]:
    lines: list[str] = []
    roots = sorted({k.split(os.sep)[0] for k in states})
    for r in roots:
        lines.append(f"[{dir_agg(states, kb_root, r):^4}] {r}/")
        sub = {k: v for k, v in states.items() if k.startswith(r + os.sep)}
        for rel in sorted(sub):
            depth = rel.count(os.sep) + 1
            if max_depth and depth > max_depth:
                continue
            indent = "  " * depth
            tag = {"OK": "OK ", "..": ".. ", "!!": "!! ", "??": "?? "}.get(sub[rel], "?? ")
            lines.append(f"{indent}[{tag}] {os.path.basename(rel)}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库目录状态前缀可视化")
    parser.add_argument("--kb-root", default=DEFAULT_KB_ROOT, help="知识库根目录")
    parser.add_argument("--markdown", action="store_true", help="额外导出 markdown")
    parser.add_argument("--max-depth", type=int, default=0, help="文件层级深度限制（0=不限）")
    args = parser.parse_args()

    data = collect_state(args.kb_root)
    states = data["states"]

    # 汇总
    n_ok = sum(1 for v in states.values() if v == "OK")
    n_wait = sum(1 for v in states.values() if v == "..")
    n_invalid = sum(1 for v in states.values() if v == "!!")
    n_orphan = sum(1 for v in states.values() if v == "??")
    summary = (f"文件总数 {len(states)} | 已入库 {n_ok} | 待入库 {n_wait} | "
               f"不合格 {n_invalid} | 孤儿 {n_orphan}")
    print(summary)

    tree = render_tree(states, args.kb_root, args.max_depth)
    print("\n".join(tree) if tree else "（目录树为空）")

    if args.markdown:
        md_dir = os.path.join(args.kb_root, "meta")
        os.makedirs(md_dir, exist_ok=True)
        md_path = os.path.join(md_dir, "kb_status_tree.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# 知识库目录状态（E7 前缀标注）\n\n{summary}\n\n```\n" +
                    "\n".join(tree) + "\n```\n")
        print(f"已导出: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
