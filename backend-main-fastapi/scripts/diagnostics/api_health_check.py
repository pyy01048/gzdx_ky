#!/usr/bin/env python
"""接口健康巡检脚本（GET 全路由自动探测）。

用户视角的"一键体检"：把这个脚本放进定时任务或 CI，每次发版前跑一遍，
就能知道"这一版到底有多少接口是坏的"。

它做什么
--------
1. 拉取 ``{base_url}/openapi.json``，取出**全部 GET 路由**；
2. 逐个发起 GET 请求（并发受限、带超时、失败不中断）；
3. 汇总并打印：总数 / 200 数 / 4xx 数 / 5xx 数 / 超时数 / 失败数 /
   平均耗时 / P95 耗时 / **最慢 10 个接口**；
4. 逐条列出所有非 2xx 的接口（路径 + 状态码 + 响应体前 300 字 + 耗时）；
5. **退出码**：有 5xx / 超时 / 连接失败 → 非 0（便于接入自动化门禁）。

安全边界（重要）
----------------
* 只发 GET，**永不**发 POST/PUT/DELETE —— 不会创建/修改/删除任何数据。
* 默认跳过有副作用的 GET（磁盘扫描 / 备份 / 修复 / 迁移 / 导入 / 同步 /
  爬虫），用 ``--include-side-effects`` 可解除（但不建议在生产跑）。
* ``--concurrency`` 默认 4，足够暴露连接池饥饿，又不至于打垮本地服务。

用法
----
    python scripts/diagnostics/api_health_check.py
    python scripts/diagnostics/api_health_check.py --base-url http://127.0.0.1:8000
    python scripts/diagnostics/api_health_check.py --timeout 3 --concurrency 8
    python scripts/diagnostics/api_health_check.py --json out.json     # 存机器可读结果
    python scripts/diagnostics/api_health_check.py --strict-4xx         # 4xx 也算失败

退出码
------
    0  全部通过（无 5xx / 无超时 / 无连接失败）
    1  存在 5xx / 超时 / 连接失败
    2  脚本自身无法运行（服务不可达、openapi 拉不到等）
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

try:
    import httpx
except ImportError:  # pragma: no cover
    print("缺少依赖 httpx，请先安装：pip install httpx", file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------- #
# 代理绕过（重要）
# --------------------------------------------------------------------------- #
# 本机 / 公司网络常设 HTTP_PROXY=http://127.0.0.1:xxxx 之类的环境变量，
# httpx 会**自动读取**这些变量并把对 127.0.0.1 的请求也发给代理，
# 结果本地后端被探测成 `502 Bad Gateway`（假故障，非常误导）。
# 本脚本只探测本机/内网后端，必须显式 trust_env=False 绕过代理。
_TRUST_ENV = False


def _client(base_url: str, timeout: float, concurrency: int) -> httpx.Client:
    """构造一个绕过系统代理的 httpx 客户端。"""
    limits = httpx.Limits(
        max_connections=max(2, concurrency),
        max_keepalive_connections=max(2, concurrency),
    )
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        follow_redirects=True,
        limits=limits,
        trust_env=_TRUST_ENV,
        headers={"user-agent": "kaoyan-api-health-check/1.0"},
    )


# --------------------------------------------------------------------------- #
# 默认配置
# --------------------------------------------------------------------------- #

DEFAULT_BASE_URL = "http://127.0.0.1:8000"

#: 有副作用 / 会跑长任务 / 会改磁盘的 GET，默认跳过。
#: 精确路径匹配（不用子串，避免误杀 /api/kb/health 这类只读接口）。
DEFAULT_SKIP_PATHS = {
    "/api/storage/scan",             # 递归全盘扫描
    "/api/backup",                   # 备份文件
    "/api/kb/heal/status",           # 知识库修复
    "/api/imports/scan/{task_id}",   # 导入扫描
}

#: 需要路径变量的路由 → 用什么值填。取小整数通常能命中"资源不存在"分支，
#: 快速验证「查询本身」不报错，而不是验证业务数据。
PATH_PARAM_VALUES = {
    "task_id": "1",
    "error_id": "1",
    "doc_id": "1",
    "word_id": "1",
    "paper_id": "1",
    "kp_id": "1",
    "plan_id": "1",
    "item_id": "1",
    "session_id": "1",
    "school_id": "1",
    "college_id": "1",
    "major_id": "1",
    "file_id": "1",
    "platform": "quark",
    "subject": "数学",
    "name": "qa",
    "id": "1",
}

#: 单接口耗时超过该值即计入"慢接口"清单（毫秒）。
SLOW_MS = 1000.0

BODY_PREVIEW = 300


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #

@dataclass
class ProbeResult:
    """单个接口的探测结果。"""
    path: str                      # openapi 路径模板，如 /api/tasks/{id}
    url: str                       # 实际请求的 URL
    status: Optional[int] = None   # HTTP 状态码；超时/异常为 None
    elapsed_ms: float = 0.0
    error: str = ""                # 异常摘要（超时 / 连接失败 / 解析失败）
    body_preview: str = ""         # 响应体前 300 字（仅非 2xx 时填充）

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def is_5xx(self) -> bool:
        return self.status is not None and self.status >= 500

    @property
    def is_4xx(self) -> bool:
        return self.status is not None and 400 <= self.status < 500

    @property
    def is_timeout(self) -> bool:
        return "timeout" in self.error.lower() or "timed out" in self.error.lower()

    @property
    def category(self) -> str:
        if self.status is None:
            return "timeout" if self.is_timeout else "error"
        if self.is_5xx:
            return "5xx"
        if self.is_4xx:
            return "4xx"
        if 200 <= self.status < 300:
            return "2xx"
        return "3xx"


@dataclass
class Report:
    """整体巡检报告。"""
    base_url: str = ""
    total: int = 0
    skipped: int = 0
    results: List[ProbeResult] = field(default_factory=list)
    elapsed_total_s: float = 0.0
    fatal: str = ""                # 脚本级错误（服务不可达等）

    # ---- 派生统计 ----
    @property
    def counts(self) -> Dict[str, int]:
        c: Dict[str, int] = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "timeout": 0, "error": 0}
        for r in self.results:
            c[r.category] = c.get(r.category, 0) + 1
        return c

    @property
    def avg_ms(self) -> float:
        vals = [r.elapsed_ms for r in self.results if r.status is not None]
        return round(statistics.fmean(vals), 1) if vals else 0.0

    @property
    def p95_ms(self) -> float:
        vals = sorted(r.elapsed_ms for r in self.results if r.status is not None)
        if not vals:
            return 0.0
        idx = max(0, min(len(vals) - 1, int(round(0.95 * (len(vals) - 1)))))
        return round(vals[idx], 1)

    @property
    def max_ms(self) -> float:
        vals = [r.elapsed_ms for r in self.results if r.status is not None]
        return round(max(vals), 1) if vals else 0.0

    @property
    def error_rate(self) -> float:
        """错误率 = (5xx + 超时 + 异常) / 总数。3xx 不算错误。"""
        if not self.total:
            return 0.0
        c = self.counts
        bad = c["5xx"] + c["timeout"] + c["error"]
        return round(bad / self.total * 100, 2)

    @property
    def slowest(self) -> List[ProbeResult]:
        return sorted(self.results, key=lambda r: -r.elapsed_ms)[:10]

    @property
    def failed(self) -> List[ProbeResult]:
        return [r for r in self.results if not r.ok]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_url": self.base_url,
            "total": self.total,
            "skipped": self.skipped,
            "elapsed_total_s": round(self.elapsed_total_s, 2),
            "counts": self.counts,
            "avg_ms": self.avg_ms,
            "p95_ms": self.p95_ms,
            "max_ms": self.max_ms,
            "error_rate_pct": self.error_rate,
            "fatal": self.fatal,
            "results": [asdict(r) for r in self.results],
        }


# --------------------------------------------------------------------------- #
# 核心逻辑
# --------------------------------------------------------------------------- #

def _resolve_url(template: str, op: Dict[str, Any]) -> str:
    """把 openapi 路径模板中的 ``{var}`` 替换为探测用假值。"""
    url = template
    for param in op.get("parameters", []) or []:
        if param.get("in") != "path":
            continue
        name = param.get("name", "")
        token = "{" + name + "}"
        if token in url:
            url = url.replace(token, PATH_PARAM_VALUES.get(name, "1"))
    return url


def fetch_openapi(base_url: str, timeout: float) -> Dict[str, Any]:
    """拉取 openapi.json。失败抛异常（由调用方转成退出码 2）。"""
    url = base_url.rstrip("/") + "/openapi.json"
    with _client(base_url, timeout, concurrency=1) as c:
        resp = c.get("/openapi.json")
        resp.raise_for_status()
        return resp.json()


def collect_get_routes(spec: Dict[str, Any], skip_paths: set) -> List[tuple]:
    """从 openapi spec 抽出待探测的 (模板, 实际URL, operation) 列表。"""
    cases = []
    for template, item in (spec.get("paths") or {}).items():
        op = item.get("get")
        if not op:
            continue
        if template in skip_paths:
            continue
        cases.append((template, _resolve_url(template, op), op))
    return cases


def probe_one(
    client: httpx.Client,
    template: str,
    url_path: str,
    params: Optional[Dict[str, Any]] = None,
) -> ProbeResult:
    """探测单个接口。任何异常都转成 ProbeResult，不向外抛。"""
    start = time.perf_counter()
    try:
        resp = client.get(url_path, params=params)
    except httpx.TimeoutException as exc:
        return ProbeResult(
            path=template, url=url_path,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            error=f"timeout: {type(exc).__name__}",
        )
    except Exception as exc:  # noqa: BLE001 - 连接失败/DNS/协议错误等
        return ProbeResult(
            path=template, url=url_path,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            error=f"{type(exc).__name__}: {exc}"[:BODY_PREVIEW],
        )

    elapsed = (time.perf_counter() - start) * 1000
    result = ProbeResult(path=template, url=url_path,
                         status=resp.status_code, elapsed_ms=elapsed)
    # 只在非 2xx 时抓 body 摘要，省内存也省时间
    if not (200 <= resp.status_code < 300):
        try:
            result.body_preview = resp.text[:BODY_PREVIEW].replace("\n", " ")
        except Exception:  # noqa: BLE001
            result.body_preview = "<无法读取响应体>"
    return result


def probe_all(
    base_url: str,
    spec: Dict[str, Any],
    skip_paths: set,
    timeout: float,
    concurrency: int,
    verbose: bool = False,
) -> Report:
    """并发探测所有 GET 路由，返回完整报告。"""
    cases = collect_get_routes(spec, skip_paths)
    report = Report(base_url=base_url, total=len(cases), skipped=len(skip_paths))
    if not cases:
        report.fatal = "openapi 中没有可探测的 GET 路由"
        return report

    started = time.perf_counter()
    with _client(base_url, timeout, concurrency) as client:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = {
                pool.submit(probe_one, client, tpl, url): (tpl, url)
                for tpl, url, _op in cases
            }
            done = 0
            for fut in as_completed(futures):
                tpl, url = futures[fut]
                try:
                    res = fut.result()
                except Exception as exc:  # noqa: BLE001 - 兜底，probe_one 已自行捕获
                    res = ProbeResult(path=tpl, url=url, error=f"{type(exc).__name__}: {exc}")
                report.results.append(res)
                done += 1
                if verbose:
                    print(f"  [{done}/{len(cases)}] {res.category.upper():>6} "
                          f"{res.elapsed_ms:8.1f}ms {tpl}", flush=True)

    report.elapsed_total_s = time.perf_counter() - started
    # 结果按路径排序，保证多次运行输出可比对（as_completed 顺序不确定）
    report.results.sort(key=lambda r: r.path)
    return report


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #

def _bar(value: float, total: int, width: int = 24) -> str:
    if total <= 0:
        return ""
    filled = int(round(value / total * width))
    return "█" * filled + "·" * (width - filled)


def print_report(report: Report, show_all_errors: bool = True, top_slow: int = 10) -> None:
    """打印人类可读的巡检报告。"""
    line = "═" * 78
    print(line)
    print(" 接口健康巡检报告 · API Health Check")
    print(line)
    print(f" 目标服务 : {report.base_url}")
    print(f" 完成时间 : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" 总耗时   : {report.elapsed_total_s:.2f}s")
    if report.fatal:
        print(f" ⚠ 致命错误: {report.fatal}")
    print(line)

    c = report.counts
    print(" 【总览】")
    print(f"   GET 路由总数 : {report.total}   (跳过副作用接口 {report.skipped} 个)")
    print(f"   2xx 正常     : {c['2xx']:>4}  {_bar(c['2xx'], report.total)}")
    print(f"   3xx 跳转     : {c['3xx']:>4}  {_bar(c['3xx'], report.total)}")
    print(f"   4xx 客户端   : {c['4xx']:>4}  {_bar(c['4xx'], report.total)}")
    print(f"   5xx 服务端   : {c['5xx']:>4}  {_bar(c['5xx'], report.total)}   ← 必须为 0")
    print(f"   超时         : {c['timeout']:>4}  {_bar(c['timeout'], report.total)}   ← 必须为 0")
    print(f"   连接/其他异常: {c['error']:>4}  {_bar(c['error'], report.total)}   ← 必须为 0")
    print()
    print(f"   平均耗时     : {report.avg_ms:>8.1f} ms")
    print(f"   P95 耗时     : {report.p95_ms:>8.1f} ms")
    print(f"   最慢单接口   : {report.max_ms:>8.1f} ms")
    print(f"   错误率       : {report.error_rate:>8.2f} %   "
          f"(5xx + 超时 + 异常) / 总数")
    print(line)

    # ---- 非 2xx 明细 ----
    failed = report.failed
    if failed:
        label = "全部非 2xx 接口" if show_all_errors else "非 2xx 接口（仅显示 5xx/超时/异常）"
        print(f" 【{label}】共 {len(failed)} 个")
        for r in failed:
            head = f" {r.status if r.status is not None else r.category.upper():>6}"
            print(f"{head} | {r.elapsed_ms:8.1f}ms | {r.path}")
            if r.error:
                print(f"        └─ 错误: {r.error[:BODY_PREVIEW]}")
            elif r.body_preview:
                print(f"        └─ 响应: {r.body_preview[:BODY_PREVIEW]}")
        print(line)
    else:
        print(" 【非 2xx 接口】无 —— 全部 GET 路由均返回 2xx 🎉")
        print(line)

    # ---- 最慢 TOP N ----
    slow = [r for r in report.slowest if r.elapsed_ms > 0][:top_slow]
    if slow:
        print(f" 【最慢 {len(slow)} 个接口】")
        for i, r in enumerate(slow, 1):
            flag = " ⚠慢" if r.elapsed_ms >= SLOW_MS else ""
            st = r.status if r.status is not None else r.category.upper()
            print(f"   {i:>2}. {r.elapsed_ms:8.1f}ms  [{st}]{flag}  {r.path}")
        print(line)

    # ---- 结论 ----
    bad = c["5xx"] + c["timeout"] + c["error"]
    if bad == 0:
        print(f" ✅ 结论：全部 {report.total} 个 GET 接口健康，无 5xx / 超时 / 连接异常。")
    else:
        print(f" ❌ 结论：发现 {bad} 个严重问题（5xx={c['5xx']} 超时={c['timeout']} "
              f"异常={c['error']}），详见上方明细。")
    print(line)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="GET 路由健康巡检：统计 5xx / 超时 / 慢接口，有严重问题则退出码非 0。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--base-url", default=DEFAULT_BASE_URL,
                   help=f"后端服务地址（默认 {DEFAULT_BASE_URL}）")
    p.add_argument("--timeout", type=float, default=10.0,
                   help="单接口超时秒数（默认 10）")
    p.add_argument("--concurrency", type=int, default=4,
                   help="并发数（默认 4；调大可更快暴露连接池饥饿，但压力大）")
    p.add_argument("--json", metavar="FILE", default=None,
                   help="把完整结果写入 JSON 文件（机器可读，便于趋势对比）")
    p.add_argument("--include-side-effects", action="store_true",
                   help="连磁盘扫描/备份/修复这类有副作用的 GET 也一起探测（谨慎）")
    p.add_argument("--strict-4xx", action="store_true",
                   help="把 4xx 也算作失败（默认只把 5xx/超时/异常算失败）")
    p.add_argument("--top-slow", type=int, default=10,
                   help="打印最慢 N 个接口（默认 10）")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="边探测边打印进度")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="只输出汇总行，不打印明细")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    parsed = urlparse(args.base_url)
    if not parsed.scheme or not parsed.hostname:
        print(f"非法的 base_url：{args.base_url}", file=sys.stderr)
        return 2

    skip_paths = set() if args.include_side_effects else set(DEFAULT_SKIP_PATHS)

    try:
        spec = fetch_openapi(args.base_url, timeout=max(args.timeout, 10.0))
    except Exception as exc:  # noqa: BLE001
        print(line := "═" * 78, file=sys.stderr)
        print(f" 无法获取 {args.base_url}/openapi.json：{type(exc).__name__}: {exc}",
              file=sys.stderr)
        print(" 请确认后端服务已启动、地址端口正确。", file=sys.stderr)
        print(line, file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"已获取 {len(spec.get('paths') or {})} 条路径定义，开始巡检 {args.base_url} …")

    report = probe_all(
        base_url=args.base_url,
        spec=spec,
        skip_paths=skip_paths,
        timeout=args.timeout,
        concurrency=args.concurrency,
        verbose=args.verbose,
    )

    if args.quiet:
        c = report.counts
        print(
            f"TOTAL={report.total} 2xx={c['2xx']} 4xx={c['4xx']} 5xx={c['5xx']} "
            f"TIMEOUT={c['timeout']} ERROR={c['error']} "
            f"AVG={report.avg_ms}ms P95={report.p95_ms}ms ERR_RATE={report.error_rate}%"
        )
    else:
        print_report(report, show_all_errors=True, top_slow=args.top_slow)

    if args.json:
        try:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
            print(f"完整结果已写入：{os.path.abspath(args.json)}")
        except Exception as exc:  # noqa: BLE001
            print(f"写 JSON 失败（不影响主流程）：{exc}", file=sys.stderr)

    # ---- 退出码 ----
    c = report.counts
    if c["5xx"] or c["timeout"] or c["error"] or report.fatal:
        return 1
    if args.strict_4xx and c["4xx"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
