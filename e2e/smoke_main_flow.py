# -*- coding: utf-8 -*-
"""考研平台前端 E2E 冒烟 v2：启动 -> 登录(N/A) -> 刷题 -> 错题 -> 答疑"""
import json, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5173"
OUT = r"C:\Users\33884\AppData\Roaming\Tencent\Marvis\User\oAN1i2T40ogJFVM4CCm9d72iRr_I\workspace\conv_51d23e78795f4b14aea781ef45710b16\output"
results = []

def record(name, ok, detail=""):
    results.append({"step": name, "ok": ok, "detail": detail[:300]})
    print(("PASS" if ok else "FAIL"), name, "|", detail[:300])

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.set_default_timeout(15000)
    page_errors = []
    page.on("pageerror", lambda e: page_errors.append(str(e)[:200]))

    # 1. 启动
    try:
        page.goto(BASE + "/#/", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        title = page.title()
        body = page.locator("body").inner_text()
        ok = "考研档案" in title and "页面出了点问题" not in body[:300]
        record("启动-首页加载", ok, f"title={title}")
        page.screenshot(path=OUT + r"\e2e_01_home.png")
    except Exception as e:
        record("启动-首页加载", False, str(e)[:200])

    # 2. 登录（本地单机平台无登录模块）
    has_login = page.get_by_role("button", name="登录").count() > 0 or page.locator("input[type=password]").count() > 0
    record("登录-无登录模块N/A", not has_login, "本地单机平台无登录UI，跳过")

    # 3. 刷题
    try:
        page.goto(BASE + "/#/quiz", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1200)
        start_btn = page.get_by_role("button", name="开始刷题").first
        if start_btn.is_disabled():
            page.get_by_role("button", name="刷新题库").first.click(timeout=8000)
            page.wait_for_timeout(2000)
            start_btn = page.get_by_role("button", name="开始刷题").first
        start_btn.evaluate("el => el.click()")
        page.wait_for_timeout(2000)
        body = page.locator("body").inner_text()
        q_ok = "题目" in body or "选项" in body or "答题" in body
        record("刷题-开始刷题", q_ok, body[:120].replace("\n", " | "))

        opt_row = page.locator("button.list-row").first
        text_inp = page.locator("input[placeholder*='答案']").first
        submitted = False
        # 等待会话渲染出选项或填空输入框（最多15s）
        page.wait_for_selector("button.list-row, input[placeholder*='答案']", timeout=15000)
        if opt_row.count():
            opt_row.evaluate("el => el.click()")
            page.wait_for_timeout(2500)
            body2 = page.locator("body").inner_text()
            done = any(k in body2 for k in ["回答正确", "回答错误", "正确答案", "解析", "下一题"])
            record("刷题-提交答案", done, body2[:200].replace("\n", " | "))
            submitted = True
        elif text_inp.count():
            text_inp.evaluate("el => el.focus()")
            page.keyboard.type("A")
            page.keyboard.press("Enter")
            page.wait_for_timeout(2500)
            body2 = page.locator("body").inner_text()
            done = any(k in body2 for k in ["回答正确", "回答错误", "正确答案", "解析", "下一题"])
            record("刷题-提交答案(填空)", done, body2[:200].replace("\n", " | "))
            submitted = True
        else:
            body2 = page.locator("body").inner_text()
            record("刷题-提交答案", False, "未找到选项/输入框 | " + body2[:160].replace("\n", " "))
        if submitted:
            nb = page.get_by_role("button", name="下一题 →")
            if nb.count():
                nb.first.evaluate("el => el.click()")
                page.wait_for_timeout(1200)
                record("刷题-下一题", True, "")
            else:
                record("刷题-下一题", False, "未找到下一题按钮")
        page.screenshot(path=OUT + r"\e2e_02_quiz.png")
    except Exception as e:
        record("刷题", False, str(e)[:200])

    # 4. 错题
    try:
        page.goto(BASE + "/#/notebook", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        body = page.locator("body").inner_text()
        has_err = "待复习" in body or "错题" in body
        record("错题本-加载", has_err, body[:150].replace("\n", " | "))
        page.screenshot(path=OUT + r"\e2e_03_notebook.png")
    except Exception as e:
        record("错题本", False, str(e)[:200])

    # 5. 答疑
    try:
        page.goto(BASE + "/#/assistant", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1200)
        inp = page.locator("textarea, input[placeholder*='提问']").first
        inp.scroll_into_view_if_needed(timeout=8000)
        inp.evaluate("el => el.focus()")
        inp.fill("请简要说明：数字电子技术中的逻辑门是什么？")
        page.keyboard.press("Enter")
        deadline = time.time() + 90
        reply_ok = False
        body = ""
        while time.time() < deadline:
            body = page.locator("body").inner_text()
            if "逻辑门" in body and len(body) > 600:
                reply_ok = True
                break
            if "无法" in body and "连接" in body:
                break
            page.wait_for_timeout(3000)
        record("答疑-发送并获回复", reply_ok, body[:300].replace("\n", " | ") if reply_ok else "等待超时")
        page.screenshot(path=OUT + r"\e2e_04_assistant.png")
    except Exception as e:
        record("答疑", False, str(e)[:200])

    if page_errors:
        print("PAGE_ERRORS:", page_errors[:5])
    browser.close()

passed = sum(1 for r in results if r["ok"])
print("=====SUMMARY=====")
print(json.dumps({"total": len(results), "passed": passed, "failed": len(results) - passed, "details": results}, ensure_ascii=False, indent=1))
