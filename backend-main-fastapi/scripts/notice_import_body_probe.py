# -*- coding: utf-8 -*-
"""导入 5 条**测试用**通知（带真实格式正文），验证 `/import` 正文解析。

**这 5 条是测试数据，title 带 `【正文解析验证·勿删】` 前缀，导入后 id 清单报 team-lead，
由 team-lead 决定清还是留，不自行删除、不混进真数据。**

正文不是凭空编的——按真库 134 条 urgent 的真实标题反推合理正文：
  #7/#10  网上报名公告      → 研招网统一报名窗口句式
  #59     推免预报名通知     → 预报名 + 复试确认句式
  #3      历年复试分数线     → 公布日句式（无截止）
  #27     期末考试安排       → 往年/已结束句式（防误抽）

用法：
    python scripts/notice_import_body_probe.py            # 真实 HTTP 导入
    python scripts/notice_import_body_probe.py --dry-run  # 只打印将要导入的内容
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402
import uvicorn  # noqa: E402

from main import app  # noqa: E402
from utils.auth import APP_PASSWORD as _PW  # noqa: E402

PREFIX = "【正文解析验证·勿删】"

# 5 条测试样本：覆盖「有截止 / 无截止 / 往年不抽 / 模糊日期 / 多个日期」
SAMPLES = [
    {
        "title": f"{PREFIX}XX大学2027年全国硕士研究生招生考试网上报名公告",
        "school_name": "XX大学", "notice_type": "公告",
        "publish_date": "2026-09-20", "source": "manual",
        "url": "https://example.edu.cn/2026/0920/c1/page.htm",
        "body": (
            "各位考生：\n"
            "2027年全国硕士研究生招生考试报名工作即将开始，现将有关事项公告如下。\n"
            "网上报名时间为2026年10月5日至10月25日，每日9:00-22:00，逾期不再补报。\n"
            "报名截止时间为2026年10月25日，请各位考生务必在此日期前完成报名信息提交。\n"
            "网上确认时间为2026年11月1日至11月5日。\n"
            "初试时间为2026年12月20日至12月21日。"
        ),
        "_expect": "2026-10-25（区间终点=截止；区间起点10-05不当截止）",
    },
    {
        "title": f"{PREFIX}XX大学2027年接收推荐免试研究生预报名通知",
        "school_name": "XX大学", "notice_type": "推免",
        "publish_date": "2026-09-01", "source": "manual",
        "body": (
            "我校2027年接收推荐免试研究生预报名工作即将启动。\n"
            "请于2026年9月20日前完成复试确认，逾期视为放弃复试资格。\n"
            "复试时间为2026年9月28日，具体安排另行通知。"
        ),
        "_expect": "2026-09-20（截止语义在日期之后：「9月20日前完成」）",
    },
    {
        "title": f"{PREFIX}XX大学关于2026年硕士研究生录取通知书邮寄信息填报的通知",
        "school_name": "XX大学", "notice_type": "录取",
        "publish_date": "2026-06-10", "source": "manual",
        "body": (
            "2026级硕士研究生录取通知书即将寄发。\n"
            "请于2026年6月20日前登录系统完成邮寄地址填报，逾期将按默认地址寄送。\n"
            "去年填报截止时间为2025年6月20日，请勿参照往年时间。"
        ),
        "_expect": "2026-06-20（同条内有往年日期 2025-06-20，必须跳过不抽）",
    },
    {
        "title": f"{PREFIX}XX大学2027年硕士研究生复试录取工作实施细则",
        "school_name": "XX大学", "notice_type": "复试",
        "publish_date": "2027-03-01", "source": "manual",
        "body": (
            "复试时间为2027年3月下旬，具体日期以学院通知为准。\n"
            "请考生保持通讯畅通，及时关注我校研究生招生信息网。"
        ),
        "_expect": "无（模糊日期「3月下旬」不精确化，不猜不填）",
    },
    {
        "title": f"{PREFIX}XX大学2026年春季学期研究生部分课程期末考试安排",
        "school_name": "XX大学", "notice_type": "公告",
        "publish_date": "2026-01-05", "source": "manual",
        "body": (
            "2026年春季学期研究生课程期末考试安排如下。\n"
            "预报名已于2025年9月25日截止，正式报名通道已关闭。\n"
            "本次考试不涉及新的报名事项，请考生按原安排参加考试。"
        ),
        "_expect": "无（「已于…截止」是已结束事件，不能当待办截止）",
    },
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印内容，不导入")
    args = ap.parse_args()

    print("=" * 78)
    print("  /import 正文解析探针（5 条测试数据）"
          + ("（DRY-RUN）" if args.dry_run else "（真实 HTTP 导入）"))
    print("=" * 78)

    if args.dry_run:
        for i, s in enumerate(SAMPLES, 1):
            print(f"\n--- 样本 {i} ---")
            print(f"  title: {s['title']}")
            print(f"  publish: {s['publish_date']}")
            print(f"  预期: {s['_expect']}")
            print("  正文:")
            for line in s["body"].split("\n"):
                print(f"    {line}")
        return

    # ---- 真实 HTTP ----
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(60):
        if srv.started:
            break
        time.sleep(0.25)

    s = requests.Session()
    s.trust_env = False
    hdrs = {"X-App-Password": _PW} if _PW else {}

    results = []
    for i, smp in enumerate(SAMPLES, 1):
        payload = {k: v for k, v in smp.items() if not k.startswith("_")}
        r = s.post(f"http://127.0.0.1:{port}/api/notice-alert/import",
                   json=payload, headers=hdrs, timeout=30)
        print(f"\n--- 样本 {i}: {smp['title'][len(PREFIX):][:44]} ---")
        print(f"  HTTP {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            print(f"  导入 id            : {d['id']}")
            print(f"  deadline_date      : {d.get('deadline_date')}")
            print(f"  deadline_message   : {d.get('deadline_message')}")
            print(f"  content_saved      : {d.get('content_saved')}  "
                  f"(body_chars={d.get('body_chars')})")
            print(f"  抽取事件           : "
                  f"{[(x['date'], x['kind'], x['is_deadline']) for x in d['dates']]}")
            print(f"  预期               : {smp['_expect']}")
            results.append({"id": d["id"], "title": smp["title"],
                            "deadline": d.get("deadline_date"),
                            "message": d.get("deadline_message")})
        else:
            print(f"  失败: {r.text[:200]}")
        time.sleep(0.2)

    srv.should_exit = True
    time.sleep(0.5)

    print()
    print("=" * 78)
    print("  测试导入 id 清单（报 team-lead，由 team-lead 决定清还是留）")
    print("=" * 78)
    for r in results:
        print(f"  #{r['id']:<6} deadline={r['deadline'] or '空':<12} {r['title'][:46]}")
    print(f"  合计 {len(results)} 条")
    print()
    print("  JSON（供脚本化核对）:")
    print("  " + json.dumps(
        [{"id": r["id"], "deadline": r["deadline"]} for r in results],
        ensure_ascii=False))


if __name__ == "__main__":
    main()
