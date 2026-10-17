# -*- coding: utf-8 -*-
"""Ollama 看门狗：进程被回收时自动拉起，供长时间批量抽取期间使用。

只在**需要跑批量知识点抽取**时才开，平时不需要。
    python scripts/_ollama_watchdog.py          # 前台跑，Ctrl+C 退出

每 8 秒探一次 127.0.0.1:11434/api/tags，不通则重新 `ollama serve`。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

EXE = r"C:\Users\33884\AppData\Local\Programs\Ollama\ollama.exe"
HOST = "http://127.0.0.1:11434"
DETACHED = 0x00000008
NEW_GROUP = 0x00000200
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def alive() -> bool:
    try:
        with _OPENER.open(f"{HOST}/api/tags", timeout=3) as r:
            return bool(json.loads(r.read().decode()).get("models"))
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    env = dict(os.environ)
    env["OLLAMA_MODELS"] = r"D:\ollama-models"
    env["OLLAMA_HOST"] = "127.0.0.1:11434"
    print("[watchdog] 监控 Ollama，Ctrl+C 退出", flush=True)
    while True:
        if not alive():
            print("[watchdog] Ollama 不可达，拉起中 ...", flush=True)
            subprocess.Popen(
                [EXE, "serve"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                creationflags=DETACHED | NEW_GROUP, close_fds=True, env=env,
            )
            time.sleep(10)
        else:
            time.sleep(8)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[watchdog] 退出")
        sys.exit(0)
