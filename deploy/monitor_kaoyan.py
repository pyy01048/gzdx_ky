#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""考研平台存活监控 + 自愈 + 邮件告警（V3.12 评审 B-01/W0 整改）。

部署（服务器侧，root crontab 每分钟一次）：
    * * * * * /usr/bin/python3 /opt/kaoyan/monitor_kaoyan.py >> /opt/kaoyan/logs/monitor-cron.log 2>&1

行为：
  * 直连 uvicorn（127.0.0.1:8000/api/health，8s 超时）与经 nginx（127.0.0.1:80）各探一次。
    健康探针现在是零 DB 访问的常数时间接口，8s 超时即视为假死。
  * 应用连续 2 次失败 → systemctl restart kaoyan（systemd Restart=always 只兜进程退出，
    兜不住「进程活着但事件循环占死」——那正是评审期间全站瘫痪的形态）。
  * 应用正常但 nginx 连续 2 次失败 → systemctl restart nginx。
  * 自愈动作 / 持续故障通过 SMTP 发告警邮件（凭据只读 /etc/kaoyan/backend.env，
    与后端同一通道；30 分钟内同类告警不重复发）。
  * 状态落 /opt/kaoyan/monitor_state.json，日志追加 /opt/kaoyan/logs/monitor.log。

只依赖标准库；不 import 后端代码（后端挂死时监控必须还能跑）。
"""

import json
import os
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage

try:
    import fcntl  # Linux 服务器侧单实例锁；非 Linux 环境降级为无锁
except ImportError:
    fcntl = None

ENV_FILE = "/etc/kaoyan/backend.env"
STATE_FILE = "/opt/kaoyan/monitor_state.json"
LOCK_FILE = "/opt/kaoyan/monitor.lock"
LOG_FILE = "/opt/kaoyan/logs/monitor.log"
APP_URL = "http://127.0.0.1:8000/api/health"
NGINX_URL = "http://127.0.0.1:80/api/health"
TIMEOUT = 8
FAIL_THRESHOLD = 2          # 连续失败次数达到即自愈
ALERT_COOLDOWN = 1800       # 同类告警 30 分钟冷却
HEAL_COOLDOWN = 300         # 两次自愈重启至少间隔 5 分钟，防持续故障下重启风暴
RESTART_TIMEOUT = 120       # > systemd 默认 TimeoutStopSec(90s)，避免 restart 被误判超时


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_env() -> dict:
    env = {}
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                k, v = raw.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def probe(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            body = r.read(200)
            return r.status == 200 and b'"ok"' in body
    except Exception:
        return False


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)  # 原子替换，避免半截 JSON 让计数清零
    except OSError as e:
        log(f"[warn] 状态写入失败: {e}")


def acquire_lock():
    """单实例守卫：cron 每分钟一次，最坏耗时可能 >60s，防并发双重启。"""
    if fcntl is None:
        return None
    try:
        os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
        fh = open(LOCK_FILE, "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh  # 持有到进程退出自动释放
    except OSError:
        return None


def send_alert(env: dict, subject: str, body: str) -> None:
    host = env.get("SMTP_HOST", "")
    if not host:
        log("[warn] 未配置 SMTP_HOST，告警仅记录日志")
        return
    to = env.get("ALERT_MAIL_TO") or env.get("SMTP_USER", "")
    if not to:
        log("[warn] 无告警收件人（ALERT_MAIL_TO / SMTP_USER），仅记录日志")
        return
    msg = EmailMessage()
    msg["From"] = env.get("MAIL_FROM") or env.get("SMTP_USER", "")
    msg["To"] = to
    msg["Subject"] = f"[考研平台告警] {subject}"
    msg.set_content(body)
    port = int(env.get("SMTP_PORT", "465") or 465)
    try:
        if port == 465 or env.get("SMTP_SSL") == "1":
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as s:
                s.login(env.get("SMTP_USER", ""), env.get("SMTP_PASSWORD", ""))
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(env.get("SMTP_USER", ""), env.get("SMTP_PASSWORD", ""))
                s.send_message(msg)
        log(f"[alert] 告警邮件已发送: {subject} -> {to}")
    except Exception as e:
        log(f"[warn] 告警发信失败: {e}")


def alert_throttled(state: dict, key: str, env: dict, subject: str, body: str) -> None:
    now = time.time()
    last = state.get("alerts", {}).get(key, 0)
    if now - last < ALERT_COOLDOWN:
        return
    send_alert(env, subject, body)
    state.setdefault("alerts", {})[key] = now


def restart(unit: str) -> bool:
    try:
        r = subprocess.run(["systemctl", "restart", unit], capture_output=True, text=True, timeout=RESTART_TIMEOUT)
    except subprocess.TimeoutExpired:
        # 捕获超时而非让异常冒泡：否则 main 中断、状态不落盘、计数不清零 → 下分钟连环重启
        log(f"[heal] systemctl restart {unit} 超时(>{RESTART_TIMEOUT}s)，视为失败；计数将清零避免连环重启")
        return False
    ok = r.returncode == 0
    log(f"[heal] systemctl restart {unit} -> {'ok' if ok else 'FAIL: ' + r.stderr.strip()}")
    return ok


def main() -> int:
    lock = acquire_lock()
    if fcntl is not None and lock is None:
        log("[skip] 另一监控实例正在运行，本次跳过（防并发双重启）")
        return 0
    try:
        env = load_env()
        state = load_state()
        app_ok = probe(APP_URL)
        nginx_ok = probe(NGINX_URL)

        app_fails = 0 if app_ok else state.get("app_fails", 0) + 1
        nginx_fails = 0 if (nginx_ok or not app_ok) else state.get("nginx_fails", 0) + 1
        state["app_fails"] = app_fails
        state["nginx_fails"] = nginx_fails
        state["last_check"] = datetime.now(timezone.utc).isoformat()
        state["last_app_ok"] = app_ok
        state["last_nginx_ok"] = nginx_ok

        now_ts = time.time()
        can_heal = now_ts - state.get("last_heal_ts", 0) >= HEAL_COOLDOWN

        if app_fails >= FAIL_THRESHOLD and can_heal:
            log(f"[heal] 应用连续 {app_fails} 次探测失败，重启 kaoyan")
            restarted = restart("kaoyan")
            state["app_fails"] = 0
            state["last_heal"] = state["last_check"]
            state["last_heal_ts"] = now_ts
            alert_throttled(
                state, "app_down", env,
                "后端假死/不可达，已自动重启",
                f"时间: {state['last_check']}\n连续失败: {app_fails} 次（{TIMEOUT}s 超时口径）\n"
                f"systemctl restart kaoyan: {'成功' if restarted else '失败，需要人工介入'}\n"
                f"主机: 60.204.223.140\n\n若反复触发，请查 journalctl -u kaoyan 与 cgroup memory.events。",
            )
        elif nginx_fails >= FAIL_THRESHOLD and can_heal:
            log(f"[heal] nginx 连续 {nginx_fails} 次探测失败（应用正常），重启 nginx")
            restart("nginx")
            state["nginx_fails"] = 0
            state["last_heal_ts"] = now_ts
            alert_throttled(
                state, "nginx_down", env,
                "nginx 入口不可达（后端正常），已自动重启",
                f"时间: {state['last_check']}\n应用直连正常，nginx 入口连续 {nginx_fails} 次失败。\n已执行 systemctl restart nginx。",
            )
        elif app_fails >= FAIL_THRESHOLD or nginx_fails >= FAIL_THRESHOLD:
            log(f"[watch] 达到自愈阈值但在 {HEAL_COOLDOWN}s 冷却期内，跳过重启（防重启风暴）")
        elif not app_ok:
            log(f"[watch] 应用探测失败 {app_fails}/{FAIL_THRESHOLD}（未到自愈阈值）")
        elif not nginx_ok:
            log(f"[watch] nginx 探测失败 {nginx_fails}/{FAIL_THRESHOLD}（应用正常）")

        save_state(state)
        return 0
    finally:
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    sys.exit(main())
