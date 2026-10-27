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
      echo "前端已回滚（FastAPI 同进程托管，无需重启后端）"
    else
      echo "无 static.prev，无法回滚前端"; exit 1
    fi
    ;;
  backend)
    echo "重启后端（配置/代码已回退到磁盘当前版本时使用）..."
    systemctl restart kaoyan
    systemctl --no-pager --lines=20 status kaoyan || true
    ;;
  db)
    echo "数据库回滚需先停机，再用备份 pg_restore，见 DEPLOY.md §10（破坏性变更走 Alembic/扩列切读）"
    echo "示例： systemctl stop kaoyan && pg_restore -h 127.0.0.1 -U kaoyan -d kaoyan --clean --if-exists <dump>"
    ;;
  *)
    echo "用法: $0 {frontend|backend|db}"; exit 2;;
esac
