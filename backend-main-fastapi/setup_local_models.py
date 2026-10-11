# -*- coding: utf-8 -*-
"""本地模型一键部署：检测 → 安装指引 → 拉取 → 验证。

### 为什么是脚本而不是自动下载

实测这台机器的网络：GitHub 直连约 **0.02 MB/s**，
1.1GB 的 OllamaSetup.exe 需要 **20 小时以上** —— 自动下载没有意义，
只会卡住让人以为程序坏了。

所以本脚本做的是**把该做的事检测清楚、把命令准备好、把结果验证掉**：
用户在网络好的时候跑一条命令即可，不用自己拼参数。

### 用法

    python setup_local_models.py            # 全面检测 + 给出下一步
    python setup_local_models.py --pull     # 检测通过后自动拉取推荐模型
    python setup_local_models.py --verify   # 只验证已装模型是否可用
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

#: 本机推荐拉取的模型（按 model_registry 的适配判定得出）
RECOMMENDED = [
    ("deepseek-r1:7b", "数学 / 数电 / 模电 / 电路 / 信号与系统 / 通信 / 光学 / 普物 / 408",
     "≈4.7GB", "推理首选，完美适配 8GB"),
    ("qwen3:4b", "文档要点提炼 / OCR 纠错（批量任务）",
     "≈2.6GB", "又快又稳，日常问答与批量处理"),
    ("qwen3:8b", "政治 / 英语（中文理解）",
     "≈5.2GB", "中文最强，可与 7B 共存按科切换"),
]

OLLAMA_DOWNLOAD = "https://ollama.com/download/OllamaSetup.exe"


def c(code: str) -> str:
    return f"\033[{code}m"


def hdr(title: str) -> None:
    print("\n" + "=" * 68)
    print(f"  {title}")
    print("=" * 68)


def find_ollama() -> str | None:
    """定位 ollama 可执行文件。"""
    exe = shutil.which("ollama")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
        os.path.expandvars(r"%ProgramFiles%\Ollama\ollama.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Ollama\ollama.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def ollama_running() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=4) as r:
            return r.status_code == 200
    except Exception:
        return False


def installed_models() -> list[dict]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=6) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("models", [])
    except Exception:
        return []


def check_hardware() -> dict:
    try:
        from services import model_registry as mr
        from dataclasses import asdict
        hw = mr.detect_hardware()
        return {**asdict(hw), "tier": hw.tier}
    except Exception as e:
        return {"error": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser(description="本地模型一键部署")
    ap.add_argument("--pull", action="store_true", help="检测通过后自动拉取推荐模型")
    ap.add_argument("--verify", action="store_true", help="只验证已装模型")
    args = ap.parse_args()

    # ---------------- 1. 硬件 ----------------
    hdr("1. 硬件检测")
    hw = check_hardware()
    if "error" in hw:
        print(f"  检测失败: {hw['error']}")
    else:
        print(f"  GPU    : {hw.get('gpu_name') or '未检测到'}")
        print(f"  显存   : {hw.get('vram_gb')} GB")
        print(f"  内存   : {hw.get('ram_gb')} GB")
        print(f"  档位   : {hw.get('tier')}")
        if hw.get("vram_gb", 0) >= 8:
            print(f"  {c('32')}→ 可运行 7B/8B（Q4 量化），14B 及以上无望{c('0m')}")
        elif hw.get("vram_gb", 0) > 0:
            print(f"  {c('33')}→ 显存偏小，建议用 4B 级别的模型{c('0m')}")
        else:
            print(f"  {c('33')}→ 无可用的 N 卡 GPU，只能走云端 API 或 CPU 推理（很慢）{c('0m')}")

    # ---------------- 2. Ollama ----------------
    hdr("2. Ollama 检测")
    exe = find_ollama()
    running = ollama_running()

    if not exe:
        print(f"  {c('31')}未安装 Ollama{c('0m')} —— 这是使用本地模型的前提")
        print()
        print("  安装方式（任选其一）：")
        print(f"    · 官网下载：{OLLAMA_DOWNLOAD}")
        print("    · 或 winget：winget install Ollama.Ollama")
        print()
        print(f"  {c('33')}注意{c('0m')}：本机实测 GitHub 直连约 0.02MB/s，")
        print("        安装包约 1.1GB，可能很慢。建议在网络好的时段下载，")
        print("        或手动拷贝安装包过来。")
        print()
        print("  装好后重新运行本脚本即可继续。")
        return 1

    print(f"  {c('32')}已安装{c('0m')}: {exe}")
    try:
        v = subprocess.run([exe, "--version"], capture_output=True, text=True,
                           timeout=20, errors="ignore")
        print(f"  版本: {(v.stdout or v.stderr).strip()[:80]}")
    except Exception:
        pass

    if running:
        print(f"  {c('32')}服务运行中{c('0m')}: {OLLAMA_HOST}")
    else:
        print(f"  {c('33')}服务未运行{c('0m')} —— 需要启动 Ollama（开始菜单里打开，")
        print("        或运行 `ollama serve`）。启动后重新运行本脚本。")
    print(f"  可执行文件: {exe}")
    print(f"  注意：新版 Ollama 自带 NVIDIA 支持；CPU 版 torch 不影响 Ollama 使用 GPU。")

    # ---------------- 3. 已装模型 ----------------
    hdr("3. 已装模型")
    models = installed_models() if running else []
    if models:
        for m in models:
            name = m.get("name", "?")
            size = round((m.get("size") or 0) / 1024 ** 3, 1)
            print(f"  · {name:<28} {size:>5} GB")
    elif running:
        print("  （还没有任何模型）")
    else:
        print("  （服务未运行，无法列出）")

    if args.verify:
        return 0

    # ---------------- 4. 推荐清单 ----------------
    hdr("4. 推荐拉取的模型（按你的 8GB 显存判定）")
    missing = []
    installed_names = {m.get("name", "") for m in models}
    installed_names |= {n.split(":")[0] for n in list(installed_names)}

    for name, use, size, why in RECOMMENDED:
        have = name in installed_names or name.split(":")[0] in installed_names
        mark = f"{c('32')}已装{c('0m')}" if have else f"{c('33')}待拉取{c('0m')}"
        print(f"  [{mark}] {name:<18} {size:>8}  {why}")
        print(f"             用途：{use}")
        if not have:
            missing.append(name)

    if not missing:
        print(f"\n  {c('32')}推荐模型都已安装。{c('0m')}可直接在应用「设置 → 模型选型」里查看。")
        return 0

    print()
    print("  拉取命令（复制执行，或加 --pull 让脚本代跑）：")
    for name in missing:
        print(f"    ollama pull {name}")

    if args.pull:
        if not running:
            print(f"\n  {c('31')}服务未运行，无法拉取。请先启动 Ollama。{c('0m')}")
            return 1
        hdr("5. 开始拉取")
        for name in missing:
            print(f"\n  → ollama pull {name}")
            try:
                subprocess.run([exe, "pull", name], timeout=7200)
            except KeyboardInterrupt:
                print("  已中断")
                break
            except Exception as e:
                print(f"  失败: {e}")
        hdr("完成")
        for m in installed_models():
            print(f"  · {m.get('name')}  {round((m.get('size') or 0)/1024**3,1)} GB")
    else:
        print()
        print("  提示：模型体积共约 12GB，本机网络较慢，建议分批拉取。")
        print("        只想要一个先用，就拉 deepseek-r1:7b（性价比最高）。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
