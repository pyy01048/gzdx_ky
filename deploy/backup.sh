#!/usr/bin/env bash
# 硕途考研平台 · 每日数据库备份（pg_dump 加密 + 本地滚动 + 异地同步占位）
# 用法：cron 每日执行，例如 0 3 * * * /opt/kaoyan/_deploy_tmp/backup.sh
set -euo pipefail
. /etc/kaoyan/.secrets            # 取 PG_PASSWORD
BK=/opt/kaoyan/backups
STAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BK"
DUMP="$BK/kaoyan_$STAMP.dump"
export PGPASSWORD="$PG_PASSWORD"
# 排除内部备份表（去重/修复脚本的 *_backup_* 留档，仅备份数据、无业务引用），
# 避免这些表随每日备份上传生产库/异地存储。
# 如需调整排除清单：pg_dump -T 'public.*backup*' 按表名模式匹配，可叠加多条 -T。
pg_dump -h 127.0.0.1 -U kaoyan -d kaoyan -Fc -f "$DUMP" \
  -T 'public.*backup*' -T 'public.*bak*' -T 'public.*_old*' -T 'public.*tmp*'
# 加密（对称；密钥 = KAOYAN_SECRET_KEY，务必异地备份该密钥，否则不可恢复）
openssl enc -aes-256-cbc -pbkdf2 -salt -in "$DUMP" -out "$DUMP.enc" -pass "pass:$KAOYAN_SECRET_KEY"
rm -f "$DUMP"
# 本地滚动保留 7 份
ls -1t "$BK"/*.enc 2>/dev/null | tail -n +8 | xargs -r rm -f
# 异地同步（占位：接入 rclone / aws s3 / 阿里 OSS 后取消注释）
# rclone copy "$BK" remote:kaoyan-backups --include "*.enc"
echo "backup ok: $DUMP.enc ($(du -h "$DUMP.enc" | cut -f1))"
# 注意：/etc/kaoyan/backend.env 与 .secrets 也需纳入异地备份（否则网盘/AI 凭据不可解）
