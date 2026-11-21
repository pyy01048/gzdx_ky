#!/usr/bin/env bash
# 硕途考研平台 · 回滚（应用/前端；数据库回滚见 DEPLOY.md §10）
# 约定：发布时保留上一版 static 为 static.prev；systemd 指向当前版本目录。
set -euo pipefail
D=/opt/kaoyan/backend-main-fastapi
ACTION="${1:-frontend}"

case "$ACTION" in
  frontend)
    echo "回滚前端静态到上一版 static.prev ..."
    if [ -d "$D/static.prev" ]; then
      rm -rf "$D/static.rollback_tmp"
      mv "$D/static" "$D/static.rollback_tmp"
      mv "$D/static.prev" "$D/static"
      mv "$D/static.rollback_tmp" "$D/static.prev"
      chown -R www-data:www-data "$D/static"
      systemctl reload nginx 2>/dev/null || true
      echo "前端已回滚（nginx 直接服务 static，reload 即生效，无需重启后端）"
    else
      echo "无 static.prev，无法回滚前端"; exit 1
    fi
    ;;
  backend)
    echo "重启后端（配置/代码已回退到磁盘当前版本时使用；如需恢复代码用 backend-code）..."
    systemctl restart kaoyan
    systemctl --no-pager --lines=20 status kaoyan || true
    ;;
  backend-code)
    echo "回滚后端代码到最近一次发布前备份 pre-*.tar.gz（push_update.py 生成）..."
    BK=/opt/kaoyan/backups
    LATEST=$(ls -1t "$BK"/pre-*.tar.gz 2>/dev/null | head -1)
    if [ -z "$LATEST" ]; then echo "无 pre-*.tar.gz 代码备份，无法回滚"; exit 1; fi
    echo "使用备份：$LATEST"
    # 回滚自身也要可逆：先把当前代码另存（用 rollback-safety- 前缀，避免被 pre-*  glob 误选）
    SAFETY="$BK/rollback-safety-$(date +%Y%m%d_%H%M%S).tar.gz"
    tar -czf "$SAFETY" \
      --exclude='backend-main-fastapi/.venv' --exclude='backend-main-fastapi/data' \
      --exclude='backend-main-fastapi/uploads' --exclude='backend-main-fastapi/logs' \
      -C /opt/kaoyan backend-main-fastapi
    # 解包覆盖代码+static（.venv/data/uploads/logs 不在包内，保留不动）
    tar xzf "$LATEST" -C /opt/kaoyan
    chown -R www-data:www-data "$D"
    systemctl restart kaoyan
    sleep 4
    systemctl is-active kaoyan
    echo "后端代码已回滚。注意：tar 覆盖不删除新版新增的文件，若本次发布新增过路由/模块文件需手动清理。"
    ;;
  db)
    echo "数据库回滚需先停机，再【解密】备份并 pg_restore，见 DEPLOY.md §10（破坏性变更走 Alembic/扩列切读）"
    echo "backup.sh 产出的是加密 .dump.enc（密钥=KAOYAN_SECRET_KEY），不能直接 pg_restore。示例："
    echo "  systemctl stop kaoyan"
    echo '  openssl enc -d -aes-256-cbc -pbkdf2 -in /opt/kaoyan/backups/kaoyan_<ts>.dump.enc -out /tmp/kaoyan.dump -pass "pass:$KAOYAN_SECRET_KEY"'
    echo "  pg_restore -h 127.0.0.1 -U kaoyan -d kaoyan --clean --if-exists /tmp/kaoyan.dump"
    echo "  shred -u /tmp/kaoyan.dump && systemctl start kaoyan"
    ;;
  *)
    echo "用法: $0 {frontend|backend|backend-code|db}"; exit 2;;
esac
