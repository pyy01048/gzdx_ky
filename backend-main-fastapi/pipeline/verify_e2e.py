# -*- coding: utf-8 -*-
"""端到端联合验证：数据库 → 后端 API → 前端资源 三层贯通性检查。

为什么需要单独一个脚本
----------------------
项目此前多次出现"某一层看起来正常、合起来不可用"的事故，例如：
  * 后端切了 PG 但 database.py 不读开关，页面数据全是旧的 SQLite；
  * 教材数据入库了但没建 API，前端看不到；
  * 前端构建产物没部署到 static，页面白屏；
  * PG 枚举不能与字符串比较，ORM 查询整片 500。

逐层自测都通，合起来却坏 —— 所以必须有一层**跨层**的验证：从真实 HTTP 接口
拉到真实数据，再校验数据是否符合业务预期。

检查项
------
A. 数据库层：核心表行数、向量覆盖率、科目/教材/院校完整性
B. 后端层：关键接口逐一调用，断言 HTTP 200 且**响应体结构符合前端消费契约**
C. 前端层：构建产物存在、index.html 引用的资源可访问、SPA 深链可回退
D. 跨层一致性：同一业务实体在 DB / API / 前端资源三处口径一致
   （如教材总数 DB=26，API 返回 26；知识点 DB=1067，API 汇总 1067）

用法
----
    python -m pipeline.verify_e2e               # 全量检查
    python -m pipeline.verify_e2e --base http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline.config import pg_database_url  # noqa: E402

STATIC_DIR = BASE_DIR / "static"
REPORT = BASE_DIR.parent / "data" / "e2e_verify_report.json"


class Checker:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def add(self, layer: str, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append({"layer": layer, "name": name, "ok": ok, "detail": detail})
        flag = "OK  " if ok else "FAIL"
        print(f"  {flag} [{layer}] {name}" + (f"  —— {detail}" if detail else ""))
        return ok

    @property
    def failed(self) -> list[dict]:
        return [r for r in self.results if not r["ok"]]


def get_json(base: str, path: str, timeout: int = 20):
    """请求接口，返回 (status, 解析后的 JSON 或 None, 原始前 200 字符)。"""
    url = base.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(raw), raw[:200]
            except json.JSONDecodeError:
                return r.status, None, raw[:200]
    except urllib.error.HTTPError as e:
        return e.code, None, e.read().decode("utf-8", errors="replace")[:200]
    except Exception as e:  # noqa: BLE001
        return 0, None, str(e)[:200]


def check_database(c: Checker) -> dict:
    """A. 数据库层：核心表行数与业务完整性。"""
    print("\n[A] 数据库层")
    stat: dict = {}
    try:
        import psycopg
        # 空库是当前的合法状态（数据尚未导入），所以门槛取「有即可」而不是写死
        # 满库量级；否则清库后这条检查会一路报 FAIL，看不出是真故障还是没数据。
        with psycopg.connect(pg_database_url()) as pg, pg.cursor() as cur:
            for tbl, min_rows in [
                ("documents", 1), ("knowledge_chunks", 1), ("chunk_vectors", 1),
                ("knowledge_points", 1), ("quiz_questions", 1), ("textbooks", 1),
                ("subject_chapters", 1), ("kaoyan_schools", 1), ("kaoyan_majors", 1),
                ("words", 1), ("sft_examples", 1),
            ]:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                n = cur.fetchone()[0]
                stat[tbl] = n
                c.add("DB", f"{tbl} 行数 ≥ {min_rows}", n >= min_rows, f"实际 {n}")

            # 向量覆盖率
            cur.execute("SELECT COUNT(*) FROM chunk_vectors WHERE embedding_f32 IS NOT NULL")
            with_vec = cur.fetchone()[0]
            rate = with_vec / stat["knowledge_chunks"] if stat["knowledge_chunks"] else 0
            stat["vector_coverage"] = round(rate, 4)
            c.add("DB", "向量覆盖率 ≥ 80%", rate >= 0.8, f"{rate:.1%}（{with_vec} 块）")

            # 教材与院校关联
            cur.execute("SELECT COUNT(*) FROM textbook_schools")
            links = cur.fetchone()[0]
            stat["textbook_school_links"] = links
            c.add("DB", "教材-院校关联存在", links > 0, f"{links} 条")

            # 教材阶段分类（初试/复试）
            cur.execute("SELECT unnest(exam_stages) s, COUNT(*) FROM textbooks GROUP BY 1")
            stages = dict(cur.fetchall())
            stat["textbook_stages"] = stages
            c.add("DB", "教材含初试与复试分类",
                  "初试" in stages and "复试" in stages, str(stages))

            # 科目与章节
            cur.execute("SELECT COUNT(*) FROM subjects WHERE is_active")
            stat["subjects"] = cur.fetchone()[0]
            c.add("DB", "备考科目 ≥ 11", stat["subjects"] >= 11, f"{stat['subjects']} 个")
    except Exception as exc:  # noqa: BLE001
        c.add("DB", "数据库连接", False, str(exc)[:160])
    return stat


def check_backend(c: Checker, base: str) -> dict:
    """B. 后端层:接口可用性 + 响应结构契约。"""
    print("\n[B] 后端层（接口契约）")
    stat: dict = {}

    #: (路径, 描述, 结构断言函数)
    endpoints = [
        ("/api/health", "健康检查", lambda d: isinstance(d, dict)),
        ("/api/textbooks/stats/overview", "教材概览",
         lambda d: d.get("total", 0) > 0 and "by_stage" in d),
        ("/api/textbooks/by-subject", "教材分组",
         lambda d: isinstance(d.get("groups"), list) and d.get("total_books", 0) > 0),
        ("/api/textbooks/1", "教材详情",
         lambda d: d.get("title") and "schools" in d and "documents" in d),
        ("/api/textbooks/school/33", "院校教材（东南大学）",
         lambda d: d.get("school", {}).get("name") and d.get("total", -1) >= 0),
        ("/api/taxonomy/subjects", "科目清单",
         lambda d: isinstance(d.get("subjects"), list) and len(d["subjects"]) > 0),
        ("/api/taxonomy/tree", "知识结构树",
         lambda d: isinstance(d.get("tree"), list) and len(d["tree"]) > 0),
        ("/api/taxonomy/coverage", "语料覆盖体检",
         lambda d: isinstance(d.get("subjects"), list)),
        ("/api/review/progress", "复习进度",
         lambda d: "total_knowledge_points" in d),
        ("/api/quiz/questions?limit=5", "刷题列表",
         lambda d: isinstance(d.get("questions"), list)),
        ("/api/quiz/subjects", "题库科目",
         lambda d: isinstance(d, (list, dict))),
        ("/api/documents?limit=5", "文档列表",
         lambda d: isinstance(d, (list, dict))),
        ("/api/quality/tree-overlay", "语料质量层",
         lambda d: isinstance(d, dict)),
        ("/api/words/decks", "单词词库",
         lambda d: isinstance(d, (list, dict))),
        ("/api/kaoyan/stats", "择校统计",
         lambda d: isinstance(d, dict)),
        ("/api/dashboard", "仪表盘",
         lambda d: isinstance(d, dict)),
        ("/api/tasks", "任务列表",
         lambda d: isinstance(d, (list, dict))),
    ]

    for path, desc, assertion in endpoints:
        status, data, raw = get_json(base, path)
        if status != 200:
            c.add("API", f"{desc} ({path})", False, f"HTTP {status} {raw[:80]}")
            continue
        try:
            ok = assertion(data) if data is not None else False
        except Exception as exc:  # noqa: BLE001
            ok = False
            raw = f"断言异常 {exc}"
        c.add("API", f"{desc} ({path})", bool(ok), "" if ok else f"结构不符 {raw[:80]}")
        if path == "/api/textbooks/stats/overview" and data:
            stat["api_textbook_total"] = data.get("total")
        if path == "/api/review/progress" and data:
            stat["api_kp_total"] = data.get("total_knowledge_points")
    return stat


def check_frontend(c: Checker, base: str) -> dict:
    """C. 前端层：产物存在 + 资源可访问 + SPA 深链。"""
    print("\n[C] 前端层（构建与部署）")
    stat: dict = {}

    idx = STATIC_DIR / "index.html"
    c.add("FE", "static/index.html 存在", idx.exists(), str(idx))
    if not idx.exists():
        return stat

    html = idx.read_text(encoding="utf-8", errors="replace")
    # 提取首页引用的 js/css
    import re
    assets = re.findall(r'(?:src|href)="\.?/?(assets/[^"]+)"', html)
    stat["index_assets"] = assets
    c.add("FE", "index.html 引用资源 ≥ 2", len(assets) >= 2, f"{len(assets)} 个")

    ok_assets = 0
    for a in assets[:6]:
        s, _, _ = get_json(base, "/" + a)
        if s == 200:
            ok_assets += 1
    c.add("FE", "引用的资源可访问", ok_assets == len(assets[:6]),
          f"{ok_assets}/{len(assets[:6])}")

    # 教材页 chunk 是否已构建（前端新页面的关键证据）
    tps = list((STATIC_DIR / "assets" / "js").glob("Textbooks-*.js")) \
        if (STATIC_DIR / "assets" / "js").exists() else []
    stat["textbooks_chunk"] = [p.name for p in tps]
    c.add("FE", "教材页代码块已构建", len(tps) > 0, ", ".join(p.name for p in tps))

    # SPA 深链回退（HashRouter 或 history fallback 都应返回 index）
    #
    # 断言方式修正（2026-10-14）：原先检查 `"root" in raw[:4000]` 会误报 ——
    # get_json() 对 HTML 走 JSONDecodeError 分支，raw 只保留前 200 字符，
    # 而 index.html 的 <div id="root"> 往往在第 200 字符之后。
    # 改为直接抓完整 HTML 判断。
    for p in ("/", "/textbooks", "/knowledge"):
        try:
            with urllib.request.urlopen(base.rstrip("/") + p, timeout=15) as r:
                body = r.read().decode("utf-8", errors="replace")
                status = r.status
        except Exception as e:  # noqa: BLE001
            status, body = 0, str(e)
        # 判定：HTTP 200 且返回的是 SPA 外壳（含挂载点或 assets 引用）
        is_shell = ("id=\"root\"" in body or "id='root'" in body
                    or "assets/js/" in body)
        c.add("FE", f"深链 {p} 返回 SPA 外壳",
              status == 200 and is_shell,
              f"HTTP {status}, 外壳={is_shell}, 长度={len(body)}")
    return stat


def check_cross_layer(c: Checker, db: dict, api: dict, fe: dict) -> None:
    """D. 跨层一致性：同一实体在 DB / API / 前端三处口径一致。"""
    print("\n[D] 跨层一致性")

    # 教材总数：DB vs API
    if db.get("textbooks") is not None and api.get("api_textbook_total") is not None:
        same = db["textbooks"] == api["api_textbook_total"]
        c.add("X", "教材总数 DB == API", same,
              f"DB {db['textbooks']} vs API {api['api_textbook_total']}")

    # 知识点总数：DB vs API
    if db.get("knowledge_points") is not None and api.get("api_kp_total") is not None:
        same = db["knowledge_points"] == api["api_kp_total"]
        c.add("X", "知识点总数 DB == API", same,
              f"DB {db['knowledge_points']} vs API {api['api_kp_total']}")

    # 教材页代码块已部署（前端能渲染教材页）
    c.add("X", "教材页端到端可用（DB+API+FE）",
          bool(db.get("textbooks")) and bool(api.get("api_textbook_total"))
          and bool(fe.get("textbooks_chunk")),
          "教材表 + 教材接口 + 教材页代码块三者齐备")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="前后端数据库端到端联合验证")
    p.add_argument("--base", default="http://127.0.0.1:8000")
    args = p.parse_args(argv)

    print("=" * 74)
    print("端到端联合验证：数据库 → 后端 API → 前端")
    print(f"后端地址：{args.base}")
    print("=" * 74)

    c = Checker()
    db = check_database(c)
    api = check_backend(c, args.base)
    fe = check_frontend(c, args.base)
    check_cross_layer(c, db, api, fe)

    print("\n" + "=" * 74)
    total = len(c.results)
    failed = len(c.failed)
    print(f"总计 {total} 项，通过 {total - failed}，失败 {failed}")
    if failed:
        print("\n失败项：")
        for r in c.failed:
            print(f"  [{r['layer']}] {r['name']} —— {r['detail']}")
    verdict = "PASS" if failed == 0 else "FAIL"
    print(f"\n联合验证结论：{verdict}")
    print("=" * 74)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "verdict": verdict, "total": total, "failed": failed,
        "results": c.results, "db": db, "api": api, "fe": fe,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告：{REPORT}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
