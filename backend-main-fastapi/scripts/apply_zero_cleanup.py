"""#28 收口：**先列后删**，且只删用户批准的 zero 三档。

批准范围（2026-10-13）：
  1. data/lora_finetune*/checkpoints 里的 optimizer*.pt / scheduler*.pt / rng_state*
     —— adapter_model.safetensors 与合并产物一律保留；
  2. backend-main-fastapi 下的 __pycache__；
  3. temp/ 目录（本轮探针已自行清空）。
low 档（merged 权重 11.52 GB、四个备份目录 8.13 GB、两个 DB 快照 1.24 GB）**不删**。

用法：默认只列清单；`--apply` 才真删。生产库全程不碰。
"""
from __future__ import annotations

from pathlib import Path
import argparse
import os
import shutil

# 路径按本文件位置推导（P0-B2：拆除机器专属绝对路径绑定）
_REPO = Path(__file__).resolve().parents[2]
ROOT = str(_REPO)
BACKEND = os.path.join(ROOT, "backend-main-fastapi")
OPT_PREFIX = ("optimizer", "scheduler", "rng_state")


def _human(n: int) -> str:
    return f"{n / 1073741824:.2f} GB" if n >= 1073741824 else f"{n / 1024:.0f} KB"


def optim_files() -> list[tuple[str, int]]:
    out = []
    for d in ("lora_finetune", "lora_finetune_v3b"):
        ckpt = os.path.join(BACKEND, "data", d, "checkpoints")
        if not os.path.isdir(ckpt):
            continue
        for dp, _dn, fn in os.walk(ckpt, onerror=lambda e: None):
            for f in fn:
                if f.startswith(OPT_PREFIX):
                    p = os.path.join(dp, f)
                    if os.path.isfile(p):
                        out.append((p, os.path.getsize(p)))
    return out


def pycache_dirs() -> list[str]:
    found = []
    for dp, dn, _fn in os.walk(BACKEND, onerror=lambda e: None):
        if os.path.basename(dp) == "__pycache__":
            found.append(dp)
            dn[:] = []
    return found


def dir_bytes(path: str) -> int:
    total = 0
    for dp, _dn, fn in os.walk(path, onerror=lambda e: None):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正删除（默认只列）")
    args = ap.parse_args()

    files = optim_files()
    pyc = pycache_dirs()
    tot_opt = sum(b for _p, b in files)
    tot_pyc = sum(dir_bytes(p) for p in pyc)

    print(f"[1] checkpoints 优化器/随机态：{len(files)} 个文件，{_human(tot_opt)}")
    for p, b in sorted(files, key=lambda x: -x[1]):
        print(f"    {_human(b):>10}  {p}")
    print(f"[2] __pycache__：{len(pyc)} 个目录，{_human(tot_pyc)}")
    for p in sorted(pyc):
        print(f"    {_human(dir_bytes(p)):>10}  {p}")
    print(f"合计 {_human(tot_opt + tot_pyc)}；low 档（merged 权重/备份目录/DB 快照）本轮不动")

    if not args.apply:
        print("\n（dry-run，未删除任何东西；加 --apply 才执行）")
        return 0

    freed = 0
    for p, b in files:
        try:
            os.remove(p)
            freed += b
        except OSError as exc:
            print(f"  删除失败 {p}: {exc}")
    for p in pyc:
        before = dir_bytes(p)
        try:
            shutil.rmtree(p, ignore_errors=False)
            freed += before
        except OSError as exc:
            print(f"  删除失败 {p}: {exc}")
    print(f"\n已释放 {_human(freed)}")

    # 复核：残留必须为 0
    left = optim_files()
    left_pyc = [p for p in pycache_dirs() if os.path.isdir(p)]
    print(f"复核残留：优化器态 {len(left)} 个 / __pycache__ {len(left_pyc)} 个目录")
    for d in ("lora_finetune", "lora_finetune_v3b"):
        ckpt = os.path.join(BACKEND, "data", d, "checkpoints")
        kept = [f for dp, _dn, fn in os.walk(ckpt, onerror=lambda e: None) for f in fn]
        print(f"  {d}/checkpoints 剩余 {len(kept)} 个文件（adapter 应完好）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
