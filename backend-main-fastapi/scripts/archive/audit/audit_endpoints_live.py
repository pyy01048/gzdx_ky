"""对**运行中的后端**做全 GET 端点实扫，专找 5xx。

## 与 tests/test_api_contract.py 的区别

| | test_api_contract | 本工具 |
|---|---|---|
| 目标 | CI 门禁（跑在隔离测试库） | **运维排查**（打真实运行实例 + 生产库） |
| 数据 | 空库/夹具，很多接口返回 404 | 真实数据，能暴露"有数据才触发"的 bug |
| 覆盖 | 全部 GET | 全部 GET（同一份路由表） |

两者互补：契约测试保证"不退化"，本工具回答"**现在这台机器上到底哪些接口是坏的**"。

## 为什么需要它

历史上多次出现"某个端点恒 500，但没人知道"——因为它不在任何测试的
断言路径里（例：/api/gate/stats、/api/notice-alert/*、/api/answers/stats
曾长期 500，直到手工逐个点才发现）。全量实扫能在几秒内回答这个问题。

## 用法

    python scripts/audit_endpoints_live.py                    # 默认打 127.0.0.1:8000
    python scripts/audit_endpoints_live.py --base http://127.0.0.1:8000
    python scripts/audit_endpoints_live.py --only-errors      # 只列 4xx/5xx
    python scripts/audit_endpoints_live.py --timeout 20
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

#: 有副作用 / 会跑长任务 / 会改磁盘的 GET —— 扫描时跳过（与契约测试同口径）
SKIP_PATHS = {
    "/api/storage/scan",
    "/api/backup",
    "/api/kb/heal/status",
    "/api/kb/heal",
    "/api/kb/repair-paths",
    "/api/kb/normalize-status",
    "/api/imports/scan/{task_id}",
    "/api/documents/{doc_id}/export",
}

#: 路径参数统一用 1（项目里绝大多数资源 id 从 1 开始）
_PARAM_ID = 1


def _opener():
    """绕开系统代理：本地 8000 走代理会得到 502 Bad Gateway。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _routes():
    from fastapi.routing import APIRoute

    import main as app_module

    out = []
    for r in app_module.app.routes:
        if isinstance(r, APIRoute) and "GET" in r.methods:
            out.append(r.path)
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser(description="全 GET 端点实扫")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--only-errors", action="store_true", help="只列非 2xx")
    args = ap.parse_args()

    op = _opener()
    paths = _routes()
    print("=" * 72)
    print(f"全 GET 端点实扫 · 目标 {args.base} · 共 {len(paths)} 条")
    print("=" * 72)

    ok, client_err, server_err, skipped, unreachable = [], [], [], [], []
    t0 = time.time()

    for tpl in paths:
        if tpl in SKIP_PATHS:
            skipped.append(tpl)
            continue
        # 路径参数替换：用正则把 {xxx} 换掉，避免手写映射表
        import re

        url = args.base + re.sub(r"\{[^}]+\}", str(_PARAM_ID), tpl)
        try:
            resp = op.open(url, timeout=args.timeout)
            code = resp.status
            resp.read()
        except urllib.error.HTTPError as e:
            code = e.code
            try:
                e.read()
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            unreachable.append((tpl, f"{type(e).__name__}: {str(e)[:60]}"))
            continue

        if 200 <= code < 300:
            ok.append(tpl)
        elif 400 <= code < 500:
            client_err.append((tpl, code))
        else:
            server_err.append((tpl, code))

    elapsed = time.time() - t0
    print(f"\n耗时 {elapsed:.1f}s")
    print(f"  2xx  {len(ok)}")
    print(f"  4xx  {len(client_err)}")
    print(f"  5xx  {len(server_err)}   <- 这些是源码 Bug")
    print(f"  跳过 {len(skipped)}（副作用端点）")
    if unreachable:
        print(f"  连不上 {len(unreachable)}")

    if client_err and not args.only_errors:
        print("\n[4xx]（可能是入参校验或无数据，非必然缺陷）")
        for p, c in client_err:
            print(f"  {c}  {p}")

    if server_err:
        print("\n[5xx] 必须修：")
        for p, c in server_err:
            print(f"  {c}  {p}")
    else:
        print("\n没有 5xx —— 所有 GET 端点均可用。")

    if unreachable:
        print("\n[连不上]")
        for p, e in unreachable:
            print(f"  {p}  {e}")

    return 1 if server_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
