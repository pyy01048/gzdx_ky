# -*- coding: utf-8 -*-
"""后台模式启动器：写 PID 文件，便于「停止服务」精确关闭。

由 启动.bat 的后台模式调用：
    python run_server.py > data/server.log 2>&1
"""

import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PID_FILE = os.path.join(DATA_DIR, "server.pid")


def main() -> int:
    os.makedirs(DATA_DIR, exist_ok=True)

    # 记录自己的 PID，供 stop 使用（uvicorn run 在同一进程内）
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    def cleanup(*_args):
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except Exception:
            pass
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, cleanup)
        signal.signal(signal.SIGTERM, cleanup)
    except Exception:
        pass

    import uvicorn

    # ⚠️ 必须先加载 .env —— 否则 os.getenv("HOST") 读到的是空值，
    #    会退回 127.0.0.1，导致"局域网模式"静默失效（只监听本机）。
    #    main.py 里有 load_dotenv，但这里是独立入口，得自己加载。
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    except Exception:
        pass

    from utils.network import get_access_info

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    try:
        info = get_access_info(port=port)
        print("=" * 62, flush=True)
        print("  考研学习平台 · 后台服务", flush=True)
        print("=" * 62, flush=True)
        print(f"  本机访问 : {info['local_url']}", flush=True)
        if info.get("exposed") and info.get("lan_url"):
            print(f"  手机访问 : {info['lan_url']}", flush=True)
        print(f"  PID      : {os.getpid()}", flush=True)
        print("  停止服务 : 运行 启动.bat 选 [4]，或 kill 上面的 PID", flush=True)
        print("=" * 62, flush=True)
    except Exception as e:
        print(f"[warn] 访问信息生成失败: {e}", flush=True)

    try:
        uvicorn.run("main:app", host=host, port=port, reload=False, log_level="info")
    finally:
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
