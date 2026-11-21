#!/usr/bin/env bash
# 硕途考研平台 · 每日数据库备份（pg_dump 加密 + 本地滚动 + 异地 rclone + 心跳）
# 完善方案 09 §3.2：备份 3-2-1（3 份副本 / 2 种介质 / 1 份异地）。
#
# 服务器 crontab：
#   0 3 * * * /opt/kaoyan/deploy/backup.sh >> /var/log/kaoyan-backup.log 2>&1
#
# 环境变量（可写在 /etc/kaoyan/backup.env）：
#   RCLONE_REMOTE=kaoyan-backup:kaoyan-backups   远程目录（未配置则跳过异地同步并明确告警）
#   HC_BACKUP_PING=https://hc-ping.com/<uuid>    备份心跳；成功 ping，失败 /fail
#   KEEP_LOCAL=7  KEEP_REMOTE=30                 两处保留份数
set -euo pipefail
. /etc/kaoyan/.secrets            # 取 PG_PASSWORD
[ -f /etc/kaoyan/backup.env ] && . /etc/kaoyan/backup.env

BK=${BK_DIR:-/opt/kaoyan/backups}
STAMP=$(date +%Y%m%d_%H%M%S)
KEEP_LOCAL=${KEEP_LOCAL:-7}
KEEP_REMOTE=${KEEP_REMOTE:-30}
mkdir -p "$BK"
DUMP="$BK/kaoyan_$STAMP.dump"
export PGPASSWORD="$PG_PASSWORD"

heartbeat() {  # $1=ok|fail  $2=说明
  [ -z "${HC_BACKUP_PING:-}" ] && return 0
  if [ "$1" = "ok" ]; then
    curl -fsS -m 10 "$HC_BACKUP_PING" -d "$2" >/dev/null || true
  else
    curl -fsS -m 10 "$HC_BACKUP_PING/fail" -d "$2" >/dev/null || true
  fi
}
trap 'heartbeat fail "backup failed at line $LINENO"' ERR

# 排除内部备份表（去重/修复脚本的 *_backup_* 留档，仅备份数据、无业务引用）
pg_dump -h 127.0.0.1 -U kaoyan -d kaoyan -Fc -f "$DUMP" \
  -T 'public.*backup*' -T 'public.*bak*' -T 'public.*_old*' -T 'public.*tmp*'

# 加密（对称；密钥 = KAOYAN_SECRET_KEY，必须异地单独保管，绝不与密文同存储）
openssl enc -aes-256-cbc -pbkdf2 -salt -in "$DUMP" -out "$DUMP.enc" \
  -pass "pass:$KAOYAN_SECRET_KEY"
shred -u "$DUMP" 2>/dev/null || rm -f "$DUMP"

# 本地滚动
ls -1t "$BK"/*.enc 2>/dev/null | tail -n +$((KEEP_LOCAL + 1)) | xargs -r rm -f

# 异地同步 + 异地滚动
if [ -n "${RCLONE_REMOTE:-}" ] && command -v rclone >/dev/null 2>&1; then
  rclone copy "$BK" "$RCLONE_REMOTE" --include "*.enc" --min-age 1m --transfers 2
  rclone lsf "$RCLONE_REMOTE" --files-only 2>/dev/null | sort -r | tail -n +$((KEEP_REMOTE + 1)) \
    | while read -r f; do rclone deletefile "$RCLONE_REMOTE/$f"; done
  echo "offsite ok: $RCLONE_REMOTE"
else
  echo "[!] 未配置 RCLONE_REMOTE 或未安装 rclone：异地备份缺失（3-2-1 未达成）"
fi

SIZE=$(du -h "$DUMP.enc" | cut -f1)
echo "backup ok: $DUMP.enc ($SIZE)"
heartbeat ok "backup $STAMP $SIZE"

# 注意：
# 1) /etc/kaoyan/backend.env 与 .secrets 也需纳入异地备份（否则网盘/AI 凭据不可解）
# 2) 备份密钥（KAOYAN_SECRET_KEY）用密码管理器或纸质离线保存，不与密文放同一存储
# 3) 每季度恢复演练：docs/guides/backup-restore-drill.md（完善方案 05 §3.5）
