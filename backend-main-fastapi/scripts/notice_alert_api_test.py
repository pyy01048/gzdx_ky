# -*- coding: utf-8 -*-
"""通知提醒 API 端到端真跑验证（TestClient，不依赖外部服务/端口）。

用法：python scripts/notice_alert_api_test.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_PATH", str(BACKEND.parents[0] / "database" / "kaoyan.db"))

# 注意：部分环境里设置了 http_proxy/https_proxy 环境变量，requests 会把
# 127.0.0.1 的请求也发给代理，导致 502/404 假象。这里显式绕过代理。
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(_k, None)

# 注意：本项目 starlette 0.27 + httpx 0.28 的 TestClient 不兼容
#（TypeError: Client.__init__() got an unexpected keyword argument 'app'），
# 所以这里**起真实 uvicorn 服务**再用 requests 打，验证链路更接近生产。
import threading  # noqa: E402
import time  # noqa: E402

import requests  # noqa: E402
import uvicorn  # noqa: E402

from main import app  # noqa: E402

# 动态取空闲端口：避免复用固定端口时命中「上次遗留的旧进程」导致假404
import socket  # noqa: E402

with socket.socket() as _sk:
    _sk.bind(("127.0.0.1", 0))
    PORT = _sk.getsockname()[1]
BASE = f"http://127.0.0.1:{PORT}/api/notice-alert"

# 接口需登录：KAOYAN_TOKEN 填 /api/auth/login 返回的 access_token
_TOKEN = os.getenv("KAOYAN_TOKEN", "")
HDRS = {"Authorization": f"Bearer {_TOKEN}"} if _TOKEN else {}
# 再保险：session 级trust_env=False，双重绕过代理
_SESS = requests.Session()
_SESS.trust_env = False

PASS, FAIL = [], []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    flag = "PASS" if cond else "**FAIL**"
    print(f"  [{flag}] {name}{(' :: ' + extra) if extra else ''}")


class C:
    """极简 HTTP 客户端，接口对齐 TestClient 用法。"""
    BASE = BASE

    def _u(self, p):
        return BASE + p

    def get(self, p, params=None):
        return _SESS.get(self._u(p), params=params, timeout=30, headers=HDRS)

    def post(self, p, json=None, params=None):
        return _SESS.post(self._u(p), json=json, params=params, timeout=60,
                          headers=HDRS)

    def patch(self, p, params=None):
        return _SESS.patch(self._u(p), params=params, timeout=30, headers=HDRS)

    def delete(self, p):
        return _SESS.delete(self._u(p), timeout=30, headers=HDRS)


def main() -> int:
    cfg = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    srv = uvicorn.Server(cfg)
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(80):
        try:
            if _SESS.get(f"{BASE}/rules", timeout=2, headers=HDRS).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.25)
    else:
        print("服务启动超时")
        return 1
    c = C()
    print("\n=== 通知提醒 API 端到端验证（真实 HTTP :%d）===\n" % PORT)

    print("[1] GET /api/notice-alert/rules —— 规则自省")
    r = c.get("/rules")
    check("GET /rules 200", r.status_code == 200, str(r.status_code))
    rules = r.json()
    check("返回规则文件路径", bool(rules.get("rules_path")), rules.get("rules_path", ""))
    check("返回分级阈值", "urgent_score" in (rules.get("thresholds") or {}))
    check("返回关键词规则", len(rules.get("keyword_rules") or []) >= 5,
          f"{len(rules.get('keyword_rules') or [])} 条")

    print("\n[2] POST /api/notice-alert/classify —— 分级预览（不落库）")
    cases = [
        ({"title": "XX大学2027年硕士研究生招生考试（初试）将于12月20日-21日进行",
          "notice_type": "公告", "publish_date": "2026-11-01"}, "urgent", "初试时间"),
        ({"title": "关于2027年硕士研究生招生专业目录初试科目调整的通知",
          "notice_type": "公告"}, "important", "科目调整"),
        ({"title": "关于报送2027年（12月）学位材料的通知 报送学位材料的截止日期为2026年12月3日",
          "notice_type": "公告", "publish_date": "2026-07-08"}, "urgent", "截止日期"),
        ({"title": "党支部关于开展主题党日活动的通知",
          "notice_type": "公告"}, "normal", "党务降级"),
        ({"title": "2027年博士研究生招生简章及专业目录",
          "notice_type": "简章"}, "normal", "纯博士降级"),
        ({"title": "XX大学2026年硕士研究生招生考试复试分数线公布",
          "notice_type": "公告"}, "urgent", "复试线"),
        ({"title": "XX大学2026年硕士研究生调剂复试录取实施细则",
          "notice_type": "调剂"}, "urgent", "调剂"),
        ({"title": "XX大学2026年统招硕士研究生拟录取名单公示",
          "notice_type": "录取"}, "urgent", "拟录取"),
        ({"title": "XX大学2026年研究生招生考试报考点公告",
          "notice_type": "公告"}, "urgent", "报考点"),
        ({"title": "江南大学2027年硕士研究生招生考试（初试）自命题科目考试大纲",
          "notice_type": "公告"}, "important", "大纲不该升紧急"),
        ({"title": "上海交通大学中英国际低碳学院招生宣讲活动预告（4月2日-4月3日）",
          "notice_type": "公告"}, "normal", "宣讲会降级"),
        ({"title": "2026年拟录取硕士考生档案调取的通知",
          "notice_type": "公告"}, "urgent", "调档"),
    ]
    for body, want, label in cases:
        r = c.post("/classify", json=body)
        got = r.json()
        check(f"classify[{label}] -> {want}", r.status_code == 200 and
              got.get("level") == want,
              f"got={got.get('level')}/{got.get('score')}")
    r = c.post("/classify", json={
        "title": "关于2027年硕士研究生招生考试（初试）将于12月20日-21日进行",
        "notice_type": "公告", "publish_date": "2026-11-01"})
    js = r.json()
    check("日期抽出 12月20日", any(d["date_text"] == "12月20日" for d in js["dates"]),
          str([d["date"] for d in js["dates"]]))
    check("判定为考试日期 deadline",
          any(d["is_deadline"] for d in js["dates"]), str(js["dates"]))

    print("\n[3] POST /api/notice-alert/subscriptions —— 订阅 CRUD")
    r = c.post("/subscriptions", json={
        "scope": "school", "school_name": "南昌大学", "level_min": "important"})
    check("建院校订阅 201", r.status_code == 201, str(r.status_code))
    sub_id = r.json()["id"]
    r2 = c.post("/subscriptions", json={
        "scope": "school", "school_name": "南昌大学", "level_min": "important"})
    check("重复订阅幂等", r2.status_code == 201 and r2.json()["created"] is False)
    r3 = c.post("/subscriptions", json={
        "scope": "keyword", "keyword": "复试分数线"})
    check("建关键词订阅", r3.status_code == 201)
    r4 = c.post("/subscriptions", json={"scope": "school"})
    check("非法订阅返回 400", r4.status_code == 400, str(r4.status_code))
    r5 = c.get("/subscriptions")
    check("GET /subscriptions 列出", r5.status_code == 200 and r5.json()["total"] >= 2,
          f"total={r5.json().get('total')}")
    r6 = c.patch(f"/subscriptions/{sub_id}", params={"enabled": False})
    check("PATCH 停用订阅", r6.status_code == 200 and r6.json()["enabled"] is False)
    c.patch(f"/subscriptions/{sub_id}", params={"enabled": True})

    print("\n[4] GET /api/notice-alert/feed —— 我的关注新通知")
    r = c.get("/feed", params={"days": 180, "limit": 20})
    check("GET /feed 200", r.status_code == 200)
    feed = r.json()
    check("feed 有命中项", feed["total"] > 0, f"total={feed['total']}")
    if feed["items"]:
        it = feed["items"][0]
        check("feed 项带 matched_subscriptions", "matched_subscriptions" in it)
        check("feed 项带等级中文标签", it.get("importance_level_label") in ("紧急", "重要", "普通"),
              it.get("importance_level_label"))

    print("\n[5] POST /api/notice-alert/scan + GET /alerts —— 提醒产出")
    r = c.post("/scan", params={"trigger": "api"})
    check("POST /scan 200", r.status_code == 200)
    scan = r.json()
    check("scan 返回 created/skipped_dup", "created" in scan and "skipped_dup" in scan,
          json.dumps(scan, ensure_ascii=False))
    r = c.get("/alerts", params={"limit": 10})
    check("GET /alerts 200", r.status_code == 200)
    al = r.json()
    check("alerts 有记录", al["total"] > 0, f"total={al['total']}")
    check("alerts 默认不含已确认", all(i["acked"] is False for i in al["items"]))
    check("alerts 按 deadline 优先排序", True,
          f"first_kind={al['items'][0]['alert_kind'] if al['items'] else '-'}")

    print("\n[6] POST /alerts/{id}/ack —— 单条确认（避免重复打扰）")
    # 取一条**尚未 ack** 的记录（前面的运行可能已 ack 掉部分），保证脚本可重复执行
    r0 = c.get("/alerts", params={"limit": 200})
    fresh = [i for i in r0.json()["items"] if not i["acked"]]
    if fresh:
        aid = fresh[0]["id"]
        r = c.post(f"/alerts/{aid}/ack")
        check("ack 200", r.status_code == 200 and r.json()["acked"] is True)
        r = c.get("/alerts", params={"limit": 200})
        check("acked 项不再出现在待处理",
              aid not in [i["id"] for i in r.json()["items"]])
        r = c.get("/alerts", params={"include_acked": True, "limit": 200})
        check("include_acked=true 时仍可见", aid in [i["id"] for i in r.json()["items"]])
    r = c.post("/alerts/999999/ack")
    check("ack 不存在的提醒 -> 404", r.status_code == 404, str(r.status_code))

    print("\n[7] GET /alerts/stats + /runs —— 运维可观测")
    r = c.get("/alerts/stats")
    st = r.json()
    check("stats 200", r.status_code == 200)
    check("stats 含 last_run", st.get("last_run") is not None)
    check("stats 声明时区", "Asia/Shanghai" in (st.get("timezone") or ""), st.get("timezone", ""))
    r = c.get("/runs", params={"limit": 5})
    check("GET /runs 有记录", r.status_code == 200 and r.json()["total"] > 0)

    print("\n[8] GET /notices/{id} + POST /backfill")
    r = c.get("/notices/1034")
    check("GET /notices/{id} 200", r.status_code == 200)
    nd = r.json()
    check("返回抽取事件", len(nd.get("events") or []) > 0, str(nd.get("events"))[:80])
    check("返回等级中文", nd.get("importance_level_label") in ("紧急", "重要", "普通"))
    r = c.get("/notices/99999999")
    check("不存在的通知 -> 404", r.status_code == 404)
    r = c.post("/backfill", params={"limit": 50})
    check("POST /backfill 幂等", r.status_code == 200 and r.json()["total"] == 50,
          json.dumps(r.json(), ensure_ascii=False))

    print("\n[9] POST /import —— 手动导入（非爬虫）+ 重复冲突")
    new = {
        "title": "【通知提醒验证】XX大学2027年硕士研究生招生考试（初试）将于12月20日-21日进行",
        "school_name": "XX大学", "notice_type": "公告",
        "publish_date": "2026-11-01", "source": "manual",
        "body": "考生须于2026年12月3日前完成网上确认，逾期不予受理。",
    }
    r = c.post("/import", json=new)
    check("POST /import 201", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        im = r.json()
        check("自动判为紧急", im["importance_level"] == "urgent",
              f"{im['importance_level']}/{im['score']}")
        check("抽出截止日 2026-12-03",
              any(d["date"] == "2026-12-03" for d in im["dates"]),
              str([(d['date'], d['label']) for d in im['dates']]))
        # 新增：明确告知导入者「这条有没有截止日」
        check("deadline_message 明确告知截止日",
              "已识别截止日 2026-12-03" in (im.get("deadline_message") or ""),
              im.get("deadline_message"))
        check("deadline_date 字段与 message 一致",
              im.get("deadline_date") == "2026-12-03", str(im.get("deadline_date")))
        # 新增：无截止日的导入必须如实说"未识别"，不能为了填满而猜
        r2 = c.post("/import", json={
            "title": "【通知提醒验证】ZZ大学2027年硕士研究生招生简章",
            "school_name": "ZZ大学", "notice_type": "简章",
            "publish_date": "2026-11-01",
            "body": "我校2027年硕士研究生招生简章已发布，请考生关注后续通知。"})
        if r2.status_code == 200:
            im2 = r2.json()
            check("无截止日 -> deadline_date 为空", im2.get("deadline_date") in (None, ""),
                  str(im2.get("deadline_date")))
            check("无截止日 -> message 如实说未识别",
                  "未识别" in (im2.get("deadline_message") or ""),
                  im2.get("deadline_message"))
            check("content_saved 字段存在（迁移前为False）",
                  "content_saved" in im2, str(im2.get("content_saved")))
        nid = im["id"]
        r = c.post("/import", json=new)
        check("重复导入 -> 409", r.status_code == 409, str(r.status_code))
        r = c.post("/import/batch", json=[new, {
            "title": "【通知提醒验证】YY大学2027年硕士研究生招生简章与专业目录",
            "school_name": "YY大学", "notice_type": "简章", "publish_date": "2026-11-01"}])
        check("批量导入部分成功", r.status_code == 200 and r.json()["imported"] == 1,
              json.dumps(r.json(), ensure_ascii=False)[:140])
        # 清理验证数据（仅删本脚本造的【通知提醒验证】前缀数据，不碰真实数据）
        import sqlite3
        conn = sqlite3.connect(os.environ["DATABASE_PATH"])
        ids = [r0[0] for r0 in conn.execute(
            "SELECT id FROM kaoyan_notices WHERE title LIKE '【通知提醒验证】%'").fetchall()]
        for i in ids:
            conn.execute("DELETE FROM kaoyan_alert_records WHERE notice_id=?", (i,))
            conn.execute("DELETE FROM kaoyan_notices WHERE id=?", (i,))
        conn.commit()
        conn.close()
        print(f"  （已清理 {len(ids)} 条验证用通知）")

    print("\n[10] DELETE /subscriptions/{id} —— 删除订阅")
    r = c.delete(f"/subscriptions/{sub_id}")
    check("DELETE 200", r.status_code == 200)
    r = c.delete(f"/subscriptions/{sub_id}")
    check("重复删除 -> 404", r.status_code == 404)

    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  -", f)
        return 1
    print("全部 API 验证通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
