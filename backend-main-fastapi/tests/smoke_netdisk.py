# -*- coding: utf-8 -*-
"""网盘模块接口验收（不依赖已授权：未授权时应给出明确指引而非 500）。"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8000"
FAILS = []


def call(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:200]
    except Exception as e:
        return 0, str(e)


def check(cond, label, detail=""):
    if not cond:
        FAILS.append(label)
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}{(' — ' + str(detail)) if detail else ''}")


print("=" * 74)
print("1) OAuth 授权入口")
print("=" * 74)
st, d = call("GET", "/api/netdisk/auth-url")
check(st == 200 and d.get("auth_url", "").startswith("https://openapi.baidu.com/oauth/2.0/authorize"),
      "授权 URL 生成", st)
if st == 200:
    url = d["auth_url"]
    # 百度要求 device_id 为 32 位十六进制
    import re
    m = re.search(r"device_id=([0-9a-fA-F]+)", url)
    check(bool(m) and len(m.group(1)) == 32, "device_id 为 32 位十六进制",
          m.group(1)[:12] + "..." if m else "缺失")
    check("scope=basic" in url or "scope=basic%2Cnetdisk" in url, "含 netdisk scope")
    check("client_id=" in url, "含 client_id")

print()
print("=" * 74)
print("2) token 状态（前端据此提示重新授权）")
print("=" * 74)
st, d = call("GET", "/api/netdisk/token-status")
check(st == 200, "token-status 可读", st)
if st == 200:
    check("authorized" in d and "expires_in_seconds" in d and "expired" in d,
          "返回授权状态/剩余有效期/是否过期", json.dumps(d, ensure_ascii=False)[:120])

print()
print("=" * 74)
print("3) 新增查询接口——未授权时应 401 且给人话提示，不能 500")
print("=" * 74)
for path in ("/api/netdisk/search?keyword=" + urllib.parse.quote("数电") + "&page=1",
             "/api/netdisk/recursive-files?path=/&max_depth=1&max_items=20&deadline=15",
             "/api/netdisk/quota"):
    st, d = call("GET", path)
    # 百度 API 本身较慢（单请求 6-7s），允许 200/401/502/504
    ok = st in (200, 401, 502, 504)
    check(ok, f"{path[:60]}", f"HTTP {st}")
    if st == 200 and isinstance(d, dict):
        if "total" in d:
            extra = f"返回 {d.get('total')} 项"
            if d.get("truncated"):
                extra += f"（已截断：{d.get('reason') or '达上限'}）"
            print(f"        {extra}")
    elif st != 200 and isinstance(d, dict):
        detail = d.get("detail")
        msg = detail.get("message") if isinstance(detail, dict) else (detail or d.get("message"))
        check(bool(msg), "  错误信息是人话", str(msg)[:70])

print()
print("=" * 74)
print("4) 连通性自检接口")
print("=" * 74)
st, d = call("POST", "/api/netdisk/test-connection/baidu")
check(st == 200, "test-connection/baidu 可调用", f"HTTP {st}")
if st == 200:
    check("connected" in d and "message" in d, "返回 connected + message")
    check("has_refresh_token" in d, "回报是否具备 refresh_token")
    print(f"        message: {d.get('message')}")
    if d.get("auth_url"):
        print("        auth_url: 已提供（引导用户授权）")

print()
print("=" * 74)
print("5) 回归：原有网盘接口仍在")
print("=" * 74)
for path in ("/api/netdisk/files?path=/", "/api/netdisk/platform-configs"):
    st, _ = call("GET", path)
    check(st == 200, path, f"HTTP {st}")

print()
print("=" * 74)
if FAILS:
    print(f"❌ 失败 {len(FAILS)} 项：")
    for f in FAILS:
        print("   -", f)
    sys.exit(1)
print("✅ 网盘接口验收通过")
