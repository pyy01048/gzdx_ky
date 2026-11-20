#!/bin/sh
# gitleaks 本地包装（docs/完善方案/02 §3.3）：
# gitleaks 可执行不存在时打印提示并放行（密钥扫描由 CI 的 gitleaks-action job 兜底）；
# 存在时对 staged 内容做密钥扫描，发现即阻断提交。
if ! command -v gitleaks >/dev/null 2>&1; then
  echo "[gitleaks] 本机未安装 gitleaks，跳过本地扫描（CI job 会兜底）。安装：scoop/winget install gitleaks"
  exit 0
fi
exec gitleaks protect --staged --redact --config "$(git rev-parse --show-toplevel)/.gitleaks.toml"
