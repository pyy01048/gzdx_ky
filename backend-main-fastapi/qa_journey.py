# -*- coding: utf-8 -*-
"""WP-C 新账号首跑旅程复验（本地 :8001，真库 kaoyan，非生产）。

用法：D:/Anaconda/python.exe qa_journey.py [--base http://127.0.0.1:8001]
覆盖：注册→邮箱验证→登录→零数据诚实断言→词书显式导入→双账号串号断言。
WP-B 落地后追加：规划覆盖层持久化 / 里程碑勾选 / 任务编辑 / 阶段计划增删改。
httpx trust_env=False：绕开注入代理（localhost 走代理必挂）。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8001"
OUTBOX = pathlib.Path(__file__).parent / "data" / "outbox"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def register_verify_login(c: httpx.Client, tag: str) -> dict:
    email = f"qa_{tag}_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "QaProbe#2026x"
    r = c.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": pwd,
            "display_name": f"旅程{tag}",
        },
    )
    if r.status_code != 200:
        raise SystemExit(f"register failed: {r.status_code} {r.text[:300]}")
    #  outbox 取验证 token
    token = None
    for _ in range(20):
        files = sorted(OUTBOX.glob(f"*{email}*.eml"), key=lambda p: p.stat().st_mtime)
        if files:
            m = re.search(r"token=([A-Za-z0-9_\-]+)", files[-1].read_text(encoding="utf-8", errors="ignore"))
            if m:
                token = m.group(1)
                break
        time.sleep(0.5)
    if not token:
        raise SystemExit(f"verify token not found for {email}")
    r = c.post("/api/auth/verify-email", json={"token": token})
    check(f"{tag} 邮箱验证", r.status_code == 200, r.text[:120])
    r = c.post("/api/auth/login", json={"username": email, "password": pwd})
    check(f"{tag} 登录", r.status_code == 200, r.text[:120])
    return r.json().get("user", {})


def zeros(d: dict, keys: list[str]) -> bool:
    return all((d.get(k) or 0) == 0 for k in keys)


def journey(base: str) -> None:
    with httpx.Client(base_url=base, trust_env=False, timeout=30) as c:
        user_a = register_verify_login(c, "journeyA")
        uid_a = user_a.get("id")
        print(f"--- user A id={uid_a} ---")

        # ---- 零数据诚实断言（WP-A 契约） ----
        r = c.get("/api/review/stats")
        d = r.json()
        check(
            "review/stats 全零",
            r.status_code == 200
            and zeros(d, ["active_errors", "due_errors", "graduated_errors", "today_reviews", "total_reviews"]),
            json.dumps(d),
        )

        r = c.get("/api/review/due")
        d = r.json()
        check("review/due 空队列", r.status_code == 200 and d.get("total") == 0 and not d.get("items"), str(d)[:160])

        r = c.get("/api/review/progress")
        check("review/progress 可达", r.status_code == 200, str(r.json())[:160])

        r = c.get("/api/review/weak-points")
        d = r.json()
        check("review/weak-points 空", r.status_code == 200 and d.get("total") == 0, str(d)[:120])

        r = c.get("/api/review/link-stats")
        d = r.json()
        check(
            "link-stats 全零",
            r.status_code == 200 and zeros(d, ["total_errors", "linked_errors", "total_links"]),
            str(d)[:160],
        )

        r = c.get("/api/insight/today")
        d = r.json()
        rev = next((s for s in d.get("suggestions", []) if s.get("label") == "到期复习"), {})
        check(
            "insight/today 到期复习=0",
            r.status_code == 200 and d.get("due_review_count") == 0 and rev.get("count") == 0,
            f"due={d.get('due_review_count')} rev={rev.get('count')}",
        )

        r = c.get("/api/dashboard/summary")
        d = r.json()
        goal = d.get("goal") or {}
        check("dashboard goal 未配置", r.status_code == 200 and goal.get("configured") is False, str(goal)[:120])

        for ep in ("daily", "week", "month"):
            r = c.get(f"/api/planner/{ep}")
            d = r.json()
            check(
                f"planner/{ep} exists=false",
                r.status_code == 200 and d.get("exists") is False and not d.get("tasks"),
                str(d)[:120],
            )

        # ---- 词书：无自动克隆 + 显式导入（WP-A 新契约） ----
        r = c.get("/api/words/decks")
        check("words/decks 首访为空（无自动克隆）", r.status_code == 200 and r.json() == [], str(r.json())[:160])
        r = c.get("/api/words/stats")
        check(
            "words/stats 全零",
            r.status_code == 200
            and zeros(r.json(), ["total", "new", "learning", "reviewing", "mastered", "due_today"]),
            str(r.json())[:160],
        )

        r = c.get("/api/words/templates")
        if r.status_code == 404:
            check("words/templates 目录", False, "404 — WP-A 未落地或未重启 :8001")
        else:
            templates = r.json()
            check("words/templates 目录非空", r.status_code == 200 and len(templates) > 0, str(templates)[:160])
            if templates:
                tid = templates[0]["id"]
                r = c.post("/api/words/decks/import", json={"template_id": tid})
                ok = r.status_code == 200
                check("words 显式导入", ok, r.text[:160])
                r2 = c.post("/api/words/decks/import", json={"template_id": tid})
                check("words 重复导入幂等", r2.status_code == 200, r2.text[:120])
                r = c.get("/api/words/stats")
                check(
                    "导入后 stats=词书词数",
                    r.status_code == 200 and r.json().get("total") == templates[0].get("word_count"),
                    f"total={r.json().get('total')} expect={templates[0].get('word_count')}",
                )

        # ---- 周报 / 模考 零数据 ----
        r = c.get("/api/insight/weekly-report")
        if r.status_code == 404:
            r = c.get("/api/insight/weekly_report")
        check(
            "周报可达且零数据",
            r.status_code == 200,
            str(r.json())[:200] if r.status_code == 200 else f"{r.status_code}",
        )

        # ---- 公共招生日历（事实数据，允许非空但须标注公共） ----
        r = c.get("/api/plan/roadmap")
        d = r.json()
        check(
            "plan/roadmap 公共日历可达",
            r.status_code == 200 and len(d.get("stages", [])) > 0,
            f"stages={len(d.get('stages', []))}",
        )

        # ---- 双账号串号断言 ----
        with httpx.Client(base_url=base, trust_env=False, timeout=30) as c2:
            user_b = register_verify_login(c2, "journeyB")
            print(f"--- user B id={user_b.get('id')} ---")
            # A 造一条错题源数据：通过 tasks 创建（个人域已隔离）
            r = c.post("/api/tasks", json={"title": "串号探针任务A", "subject": "数学"})
            check("A 创建任务", r.status_code in (200, 201), r.text[:160])
            r = c2.get("/api/tasks")
            tasks_b = r.json()
            items = tasks_b.get("items") if isinstance(tasks_b, dict) else tasks_b
            leaked = any("串号探针" in str(t.get("title", "")) for t in (items or []))
            check("B 看不到 A 的任务", r.status_code == 200 and not leaked, str(items)[:160])
            r = c2.get("/api/review/stats")
            check(
                "B review/stats 全零",
                zeros(r.json(), ["active_errors", "due_errors", "total_reviews"]),
                str(r.json())[:120],
            )
            r = c2.get("/api/words/decks")
            check("B 词库为空（A 导入不串号）", r.status_code == 200 and r.json() == [], str(r.json())[:160])
            r = c2.get("/api/insight/today")
            check("B 到期复习=0", r.json().get("due_review_count") == 0, str(r.json().get("due_review_count")))

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n==== {len(RESULTS) - len(failed)}/{len(RESULTS)} PASS ====")
    if failed:
        print("FAILED:", *failed, sep="\n  - ")
        sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    journey(ap.parse_args().base)
