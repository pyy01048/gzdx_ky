"""#28 零风险清理清单：**只测量、只出清单、绝不删除**。

用户裁定的范围（见 docx/16 与项目记忆）：只做"零风险"清理，任何删除都要**逐条人工批准**。
所以本脚本：
* 全程只读 —— 生产库用 `mode=ro` 打开，从不写入、从不 `os.remove`；
* 每一项都给**实测字节数 + 文件数 + 删了会坏什么 + 复核方法**，让人能拍板而不是听我保证；
* 按风险分三档：`zero`（无任何引用/依赖，重建只需重跑脚本）、`low`（有引用但可验证）、
  `needs_review`（体量大但依赖复杂，本轮不建议动）。

用法：
    python scripts/disk_cleanup_manifest.py              # 打印清单（Markdown）
    python scripts/disk_cleanup_manifest.py --json       # 机器可读
    python scripts/disk_cleanup_manifest.py --min-mb 200 # 只列 ≥200MB 的项
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from typing import Dict, List

ROOT = r"D:\平台"
BACKEND = os.path.join(ROOT, "backend-main-fastapi")
LIVE_DB = os.path.join(ROOT, "database", "kaoyan.db")
STORAGE_DOCS = os.path.join(BACKEND, "data", "storage", "documents")
KB = os.path.join(ROOT, "knowledge_base")

_GB = 1024 ** 3
_MB = 1024 ** 2


def _dir_size(path: str) -> Dict[str, float]:
    total = 0
    files = 0
    for dp, _dn, fn in os.walk(path, onerror=lambda e: None):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
                files += 1
            except OSError:
                pass
    return {"bytes": total, "files": files}


def _glob_files(pattern: str) -> List[str]:
    d = os.path.dirname(pattern)
    if not os.path.isdir(d):
        return []
    rx = re.compile("^" + re.escape(os.path.basename(pattern)).replace("\\*", ".*") + "$")
    return [os.path.join(d, n) for n in sorted(os.listdir(d)) if rx.match(n)]


def item(key, path, label, risk, breaks, how, bytes_=None, files=None):
    if bytes_ is None:
        if os.path.isdir(path):
            s = _dir_size(path)
            bytes_, files = s["bytes"], int(s["files"])
        elif os.path.exists(path):
            bytes_, files = os.path.getsize(path), 1
        else:
            return None
    if bytes_ <= 0:
        return None
    return {"key": key, "path": path, "label": label, "risk": risk,
            "bytes": int(bytes_), "files": int(files or 0),
            "size_gb": round(bytes_ / _GB, 3), "size_mb": round(bytes_ / _MB, 1),
            "breaks": breaks, "verify": how,
            "mtime": time.strftime("%Y-%m-%d", time.localtime(
                os.path.getmtime(path))) if os.path.exists(path) else ""}


def build() -> List[Dict]:
    out: List[Dict] = []

    # ---- 1. 手工数据库快照（同一份 640MB 库的多个历史副本）----
    for p in _glob_files(os.path.join(ROOT, "database", "kaoyan.db.*")):
        base = os.path.basename(p)
        if base.endswith(("-wal", "-shm", "-journal")):
            continue  # 活动附属文件，不是快照
        out.append(item(f"db_snapshot:{base}", p, f"数据库快照 {base}", "low",
                        "回滚能力：删了就只剩最新一份快照，误操作后无法回到该时点",
                        "确认 `documents/chunks` 计数与现网一致后再决定保留几份"
                        "（用 `sqlite3 -readonly` 比对，不要打开写连接）"))

    # ---- 2. 自动备份目录（滚动）----
    for p in (os.path.join(ROOT, "data", "backups"),
              os.path.join(ROOT, "_backup_notice_alert"),
              os.path.join(ROOT, "_archive", "db_backups"),
              os.path.join(BACKEND, "data", "backups")):
        if os.path.isdir(p):
            s = _dir_size(p)
            rel = os.path.relpath(p, ROOT)
            if p.endswith("backups"):
                breaks = f"失去 {rel} 里历史时点的库快照；最新一份仍在，回滚能力不受影响"
                how = "按 mtime 排序只留最新 1–2 份，其余逐条确认"
            else:
                breaks = f"失去 {rel} 这组一次性任务备份；该任务（通知提醒/正文解析）已验收并回归"
                how = "确认对应任务已合入且回归测试在跑，再整目录归档或删除"
            out.append(item("backup_dir:" + p, p, f"备份目录 {rel}", "low",
                            breaks, how, bytes_=s["bytes"], files=s["files"]))

    # ---- 3. LoRA 训练产物（两条 LoRA 路线都已实测否决）----
    for d in sorted(os.listdir(os.path.join(BACKEND, "data"))):
        if not d.startswith("lora_finetune"):
            continue
        base = os.path.join(BACKEND, "data", d)
        merged = os.path.join(base, "merged")
        ckpt = os.path.join(base, "checkpoints")
        if os.path.isdir(merged):
            s = _dir_size(merged)
            out.append(item(f"lora_merged:{d}", merged, f"{d} merged 权重", "low",
                            "失去「重新造一个 Ollama 标签」的能力（需重训才能再合）；"
                            "现网答疑用的是 ~/.ollama 里已建的模型，与此目录无关",
                            "两条 LoRA 在 130 道留出集上都与基座同分（docx/14 §9.7），"
                            "确认不再需要该臂后删"))
        if os.path.isdir(ckpt):
            opt_files = [os.path.join(dp, f)
                         for dp, _dn, fn in os.walk(ckpt, onerror=lambda e: None)
                         for f in fn
                         if f.startswith(("optimizer", "scheduler", "rng_state"))]
            opt = sum(os.path.getsize(p) for p in opt_files if os.path.exists(p))
            tot = _dir_size(ckpt)
            # 只报优化器态那部分（bytes 与 files 必须同集合，否则体量与文件数对不上）
            out.append(item(f"lora_optim:{d}", ckpt,
                            f"{d} checkpoints 里的优化器/随机态（整目录 {tot['bytes']/_GB:.2f}GB）",
                            "zero" if opt else "low",
                            "优化器/随机态只服务「续训」，训练已完成即无用；"
                            "adapter 权重留着可复现合并，本项不含它",
                            "只删 optimizer*.pt / scheduler*.pt / rng_state*，"
                            "保留 adapter_model.safetensors",
                            bytes_=opt, files=len(opt_files)))

    # ---- 4. storage/documents 孤儿（磁盘有、DB 无引用）----
    if os.path.isdir(STORAGE_DOCS):
        orph_bytes = orph_n = 0
        ref_names = set()
        try:
            con = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
            for (fp,) in con.execute("SELECT file_path FROM documents"):
                if fp:
                    ref_names.add(os.path.normpath(os.path.basename(str(fp))))
            con.close()
            for n in os.listdir(STORAGE_DOCS):
                p = os.path.join(STORAGE_DOCS, n)
                if os.path.isfile(p) and os.path.normpath(n) not in ref_names:
                    orph_bytes += os.path.getsize(p)
                    orph_n += 1
        except sqlite3.Error as e:  # 读不到引用就当 0，绝不猜
            print(f"[warn] 读取 documents.file_path 失败，孤儿项跳过：{e}", file=sys.stderr)
        if orph_n:
            out.append(item("storage_orphans", STORAGE_DOCS,
                            f"storage/documents 中 DB 无引用的孤儿文件", "needs_review",
                            "若某文档记录被删过而正文仍在，删除只丢原始文件（索引/chunk 已不在库里）；"
                            "但文件名归一/大小写差异会误判，必须人工抽查",
                            "逐条比对 documents.file_name，确认无引用再删",
                            bytes_=orph_bytes, files=orph_n))

    # ---- 5. 临时/缓存（零风险）----
    for p, lbl in ((os.path.join(ROOT, "temp"), "temp/ 探针与日志"),):
        if os.path.isdir(p):
            s = _dir_size(p)
            out.append(item("temp_dir", p, lbl, "zero", "无：只放一次性探针产物", "可直接清",
                            bytes_=s["bytes"], files=s["files"]))
    pyc = 0
    pyc_n = 0
    for dp, dn, fn in os.walk(BACKEND, onerror=lambda e: None):
        if os.path.basename(dp) == "__pycache__":
            for f in fn:
                try:
                    pyc += os.path.getsize(os.path.join(dp, f))
                    pyc_n += 1
                except OSError:
                    pass
            dn[:] = []
    if pyc:
        out.append(item("pycache", BACKEND, "backend __pycache__", "zero",
                        "无：Python 自动重建", "可删", bytes_=pyc, files=pyc_n))

    out = [r for r in out if r]   # item() 对缺失/0 字节路径返回 None
    out.sort(key=lambda r: -r["bytes"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-mb", type=float, default=1.0)
    args = ap.parse_args()

    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    rows = [r for r in build() if r["bytes"] >= args.min_mb * _MB]
    zero = sum(r["bytes"] for r in rows if r["risk"] == "zero")
    low = sum(r["bytes"] for r in rows if r["risk"] == "low")
    review = sum(r["bytes"] for r in rows if r["risk"] == "needs_review")

    if args.json:
        print(json.dumps({"items": rows, "recoverable": {
            "zero_gb": round(zero / _GB, 2), "low_gb": round(low / _GB, 2),
            "needs_review_gb": round(review / _GB, 2)}}, ensure_ascii=False, indent=1))
        return 0

    print(f"扫描根：{ROOT}｜生产库只读打开，本脚本不删除任何文件\n")
    print(f"| 项 | 体量 | 文件 | 风险 | 删了会坏什么 | 怎么复核 |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        sz = f"{r['size_gb']:.2f} GB" if r["bytes"] >= _GB else f"{r['size_mb']:.0f} MB"
        print(f"| {r['label']} | {sz} | {r['files']} | {r['risk']} | {r['breaks']} | {r['verify']} |")
    print(f"\n**零风险（zero）合计 {zero/_GB:.2f} GB**｜低风险（low）{low/_GB:.2f} GB"
          f"｜需人工复核（needs_review）{review/_GB:.2f} GB")
    print("任何删除都要逐条批准后才做（范围裁定：宁可空也不要不可逆）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
