#!/usr/bin/env bash
# 硕途考研平台 · 系统级看门狗（完善方案 09 §3.3）
# 与进程内 utils/server_watchdog.py 互补：进程内的管请求质量，本脚本管"进程/机器还活着吗"。
#
# crontab：*/30 * * * * /opt/kaoyan/deploy/watchdog.sh >> /var/log/kaoyan-watchdog.log 2>&1
#
# 环境变量（/etc/kaoyan/watchdog.env）：
#   HC_DISK_PING=https://hc-ping.com/<uuid>    磁盘水位
#   HC_SVC_PING=https://hc-ping.com/<uuid>     服务存活
#   HC_NODE_PING=https://hc-ping.com/<uuid>    家庭算力节点连通
#   TAILSCALE_NODE=100.92.154.42               家庭节点 Tailscale IP
#   DISK_THRESHOLD=85                          磁盘使用率告警阈值（%）
set -uo pipefail
[ -f /etc/kaoyan/watchdog.env ] && . /etc/kaoyan/watchdog.env

DISK_THRESHOLD=${DISK_THRESHOLD:-85}
fail() { [ -n "${1:-}" ] && curl -fsS -m 10 "$1/fail" -d "$2" >/dev/null || true; }
ok()   { [ -n "${1:-}" ] && curl -fsS -m 10 "$1"       -d "$2" >/dev/null || true; }

# 1) 磁盘水位
USE=$(df / | awk 'NR==2{gsub("%","",$5); print $5}')
if [ "${USE:-0}" -ge "$DISK_THRESHOLD" ]; then
  echo "DISK ALERT: ${USE}%"
  fail "${HC_DISK_PING:-}" "disk ${USE}%"
else
  ok "${HC_DISK_PING:-}" "disk ${USE}%"
fi

# 2) 服务存活（进程 + 本地健康端点）
if systemctl is-active --quiet kaoyan && curl -fsS -m 5 http://127.0.0.1:8000/api/health >/dev/null; then
  ok "${HC_SVC_PING:-}" "kaoyan alive"
else
  echo "SERVICE ALERT: kaoyan not healthy"
  fail "${HC_SVC_PING:-}" "kaoyan down"
fi

# 3) 家庭算力节点（Tailscale 内网）
if [ -n "${TAILSCALE_NODE:-}" ]; then
  if ping -c1 -W3 "$TAILSCALE_NODE" >/dev/null 2>&1; then
    ok "${HC_NODE_PING:-}" "node up"
  else
    echo "NODE ALERT: ${TAILSCALE_NODE} unreachable"
    fail "${HC_NODE_PING:-}" "node down"
  fi
fi
