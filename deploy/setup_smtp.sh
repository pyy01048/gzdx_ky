#!/usr/bin/env bash
# 一键配置真实 SMTP 发信（硕途考研平台 · 华为云）
# 用法：
#   bash setup_smtp.sh <provider> <email> <authcode> [test_to]
#   provider: qq | 163 | gmail | brevo | custom
#   custom 需额外环境变量 SMTP_HOST/SMTP_PORT/SMTP_SSL
# 例：
#   bash setup_smtp.sh qq 12345678@qq.com abcdefghijklmnop 12345678@qq.com
#
# 做四件事：备份 env → 写入 SMTP 配置 → 发一封真实测试邮件 → 重启 kaoyan。
# 授权码不是邮箱登录密码：QQ/163 在「设置→账户→开启 SMTP→生成授权码」获取。
set -euo pipefail

PROVIDER="${1:-}"; EMAIL="${2:-}"; AUTHCODE="${3:-}"; TEST_TO="${4:-$EMAIL}"
ENV_FILE=/etc/kaoyan/backend.env
APP_DIR=/opt/kaoyan/backend-main-fastapi

if [[ -z "$PROVIDER" || -z "$EMAIL" || -z "$AUTHCODE" ]]; then
  echo "用法: bash setup_smtp.sh <qq|163|gmail|brevo|custom> <email> <authcode> [test_to]"; exit 2
fi

case "$PROVIDER" in
  qq)     HOST=smtp.qq.com;            PORT=465; SSL=1 ;;
  163)    HOST=smtp.163.com;           PORT=465; SSL=1 ;;
  gmail)  HOST=smtp.gmail.com;         PORT=465; SSL=1 ;;
  brevo)  HOST=smtp-relay.brevo.com;   PORT=587; SSL=0 ;;
  custom) HOST="${SMTP_HOST:?custom 需设 SMTP_HOST}"; PORT="${SMTP_PORT:-465}"; SSL="${SMTP_SSL:-1}" ;;
  *) echo "未知 provider: $PROVIDER"; exit 2 ;;
esac

echo "[1/4] 备份 env → ${ENV_FILE}.bak-smtp-$(date +%Y%m%d-%H%M%S)"
cp "$ENV_FILE" "${ENV_FILE}.bak-smtp-$(date +%Y%m%d-%H%M%S)"

echo "[2/4] 写入 SMTP 配置（provider=$PROVIDER host=$HOST port=$PORT ssl=$SSL）"
# 先剔除旧的 SMTP/MAIL_FROM 行，再追加新值，避免重复
grep -v -E '^(SMTP_HOST|SMTP_PORT|SMTP_SSL|SMTP_USER|SMTP_PASSWORD|MAIL_FROM)=' "$ENV_FILE" > "${ENV_FILE}.tmp"
cat >> "${ENV_FILE}.tmp" <<EOF
SMTP_HOST=$HOST
SMTP_PORT=$PORT
SMTP_SSL=$SSL
SMTP_USER=$EMAIL
SMTP_PASSWORD=$AUTHCODE
MAIL_FROM=$EMAIL
EOF
mv "${ENV_FILE}.tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "[3/4] 发送真实测试邮件 → $TEST_TO"
cd "$APP_DIR"
set -a; . "$ENV_FILE"; set +a
if .venv/bin/python - "$TEST_TO" <<'PY'
import sys
from services.email_service import send_email, smtp_configured
to = sys.argv[1]
assert smtp_configured(), "SMTP_HOST 未生效"
ok = send_email(to, "SMTP 配置测试 · 硕途考研",
                "这是一封测试邮件。收到它说明平台真实发信已打通，注册验证与找回密码邮件可以正常投递。\n\n—— 硕途考研平台")
print("TEST_SEND_OK" if ok else "TEST_SEND_FAIL")
sys.exit(0 if ok else 1)
PY
then
  echo "    测试邮件发送成功，请查收 $TEST_TO（含垃圾箱）"
else
  echo "    [!] 测试邮件发送失败：请核对授权码/邮箱是否开启 SMTP。配置已写入，可修正后重跑。"
  echo "    详细错误见：journalctl -u kaoyan -n 30 --no-pager（或下方 python 日志）"
  exit 1
fi

echo "[4/4] 重启 kaoyan 使配置生效"
systemctl restart kaoyan
sleep 4
systemctl is-active kaoyan
echo "[OK] SMTP 真实发信已上线。注册/找回密码邮件将投递到用户收件箱。"
