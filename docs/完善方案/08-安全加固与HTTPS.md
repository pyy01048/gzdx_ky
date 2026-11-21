# 08 · 安全加固与 HTTPS

> 覆盖问题：R03（公网明文 HTTP / 生产模式未确认）、R20（SSH root + 无主机指纹校验）
> 优先级：🔴 P0（R03）/ P1（R20）｜ 预计工作量：1–2 天

---

## 1. 现状与证据

### 1.1 公网明文 HTTP（nginx-kaoyan.conf 自述）

```
2026-10-18 公网开放（个人使用决策）：
用户为个人使用决定暂不备案、不开 HTTPS，直接开放公网 IP。
残留风险（用户已知情）：HTTP 明文传输密码；大陆节点未备案，
运营商/云厂商可能干扰 80 端口；IP 非固定。
```
- 站点 `60.204.223.140:80` 对全网开放，**登录密码、JWT cookie、错题照片、AI 对话全部明文过公网**。同一 WiFi/运营商路径上的任何中间人都可截获。
- "已知情"不改变风险等级：这是个人平台唯一真正暴露在互联网的攻击面，P0。
- 安全响应头只有 nosniff / X-Frame-Options / Referrer-Policy，**无 CSP**；无 TLS 自然无 HSTS。
- 限流做得对：api 10r/s、登录 burst=3、AI 2r/s，且 refresh 不纳入限流（有踩坑注释）。

### 1.2 生产模式开关未确认

- `main.py`：`APP_ENV=production` 时关闭 /docs、/redoc、/openapi.json 与局域网 CORS 正则。
- **`deploy/backend.env.template` 里没有 APP_ENV 这一行**——若服务器照模板部署，/docs 与 openapi.json 正在公网裸奔（485 条路由的完整说明书）。需立即实测确认。

### 1.3 SSH 与旁路

- `ssh_run.py` / `push_update.py`：root 直登 + `AutoAddPolicy()`（不校验主机指纹，理论可被中间人）；密钥认证已做对。
- 服务器 IP、Tailscale IP（100.72.33.1 / 100.92.154.42）写在公开仓库（转私有后降级为低危）。
- `backend.env.template` 注释："三个旁路服务本身无鉴权，务必配置 SERVICE_TOKEN 并保持一致"——**OCR(8888)/reranker(8140)/Ollama(11434) 在家庭节点上是否真的校验 token、是否只监听 Tailscale 网段，需实测**。Ollama 默认无鉴权，若家庭节点端口误暴露公网 = 免费 GPU 代理。

### 1.4 已达标（保持，不要重复建设）

PBKDF2 24 万轮 + 首登强改密 + 登录失败锁定（5 次/300s 锁 900s）+ JWT 双 httpOnly cookie + token_version 失效机制 + app 级默认拒绝访问策略 + 凭据 AES-256-GCM 落库 + 行级隔离 scope.py。认证授权层在个人项目里属于超配水平。

---

## 2. 完善标准

1. **公网入口必须 TLS**，或干脆不对公网开放（二选一，不允许长期明文）。
2. 服务器 `APP_ENV=production` 确认生效：/docs、/redoc、/openapi.json 公网 404。
3. 安全头齐备：CSP（适配 SPA + SSE）、HSTS（TLS 后）、nosniff、frame、referrer。
4. SSH：专用部署用户 + sudo 最小授权、禁 root 密码登录、known_hosts 固定指纹、fail2ban。
5. 防火墙最小开放：公网仅 80/443（或全关走 Tailscale）；PG/旁路端口只监听内网。
6. 旁路三服务 token 校验实测通过，且只绑定 Tailscale IP。
7. 依赖漏洞按 03 文档清零（安全基线的一部分）。

---

## 3. 落地步骤

### 3.1 立即核验（10 分钟，今天就做）

```bash
# 公网实测（本机执行）
curl -s -o /dev/null -w "%{http_code}" http://60.204.223.140/docs          # 期望 404；若 200 → 立即整改
curl -s -o /dev/null -w "%{http_code}" http://60.204.223.140/openapi.json  # 期望 404
# 服务器侧确认
grep APP_ENV /etc/kaoyan/backend.env    # 必须有 APP_ENV=production
```
若缺失：`echo 'APP_ENV=production' | sudo tee -a /etc/kaoyan/backend.env && sudo systemctl restart kaoyan`，复测。
同时把 `APP_ENV=production` 补进 `deploy/backend.env.template`（模板缺陷根治）。

家庭节点核验：
```powershell
# 家庭 Windows 节点：确认三服务监听地址
netstat -ano | findstr "8888 8140 11434"   # 期望只出现 100.92.154.42 或 127.0.0.1，绝不能是 0.0.0.0
# Ollama：系统环境变量 OLLAMA_HOST=100.92.154.42:11434（而非 0.0.0.0）
# 从公网侧（服务器）反向验证不可达：
#   curl -m 5 http://<家庭公网IP>:11434/api/tags   期望超时/拒绝
```
旁路 token：用错误 SERVICE_TOKEN 请求 OCR/reranker，期望 401；若服务本身不校验，在家庭节点前置一个只绑 Tailscale 的反代（Caddy/nginx）统一校验 `X-Service-Token`。

### 3.2 TLS 三选一（按推荐序）

**方案 B（推荐，零成本零备案）：关公网，全走 Tailscale**
个人备考平台，访问者只有自己的手机/电脑/平板——Tailscale 已就位（100.72.33.1），根本不需要公网入口。
```bash
# 服务器：nginx 只监听 Tailscale IP
#   listen 100.72.33.1:80;   （删除 0.0.0.0:80 与 [::]:80）
sudo ufw deny 80/tcp
sudo ufw allow in on tailscale0
sudo ufw reload
```
- 手机装 Tailscale 客户端后体验与公网一致，且流量全程 WireGuard 加密。
- Tailscale 还可开 HTTPS（`tailscale cert` 为机器名签 Let's Encrypt 证书，MagicDNS + HTTPS 功能），内网也拿 TLS。
- 代价：分享给他人试用时需对方装 Tailscale（第一批试用者走查场景可临时开公网 + 方案 A/C）。

**方案 A（要公开分享时）：域名 + 备案 + certbot**
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d kaoyan.example.com   # 自动改 nginx + 续期 cron
```
nginx 启用仓库里已备好的 443 注释块（ssl_certificate/HSTS 都写好了），80 全量 301。大陆节点域名需 ICP 备案（阿里云/华为云 App 内 1–2 周）；**不想备案就把服务器迁到境外轻量节点或只用方案 B**。

**方案 C（无域名过渡）：Let's Encrypt IP 证书 / 自签**
- 2026 年 Let's Encrypt 已支持 IP 地址短期证书（6 天 profile，需 ACME 客户端支持 shortlived profile，如 certbot ≥4.x / acme.sh），`acme.sh --issue --alpn -d 60.204.223.140 --profile shortlived` 可拿到浏览器可信的 IP 证书，自动续期必须 ≤3 天一跑。
- 自签证书 + 自己设备手动信任：零依赖但每台设备要装根证书，手机体验差，仅作最后备选。
> 无论 A/B/C，**明文 80 传密码的现状必须在本周内结束**。

### 3.3 安全头与 CSP（TLS 后）

nginx server 块追加：
```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self' data:; object-src 'none'; frame-ancestors 'self'; base-uri 'self'" always;
# 说明：SPA 无外链脚本；夸克网盘 iframe 若启用需加 frame-src https://pan.quark.cn；
# AI SSE 走 connect-src 'self' 已覆盖。上线前用 Report-Only 模式跑一周收集违规再转强制。
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;  # 仅 TLS 后
```
cookie 复核：JWT cookie 在 TLS 后应加 `Secure` 属性（utils/security.py 的 set_cookie 处，按 APP_ENV 分支）。

### 3.4 SSH 加固（半天）

```bash
# 服务器
sudo adduser deploy
sudo usermod -aG www-data deploy
# 最小 sudo：只允许部署所需命令
echo 'deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart kaoyan, /usr/bin/systemctl reload nginx, /usr/bin/tar, /usr/bin/chown' | sudo tee /etc/sudoers.d/deploy
# 密钥登录
sudo -u deploy mkdir -p ~deploy/.ssh && cat ~/.ssh/authorized_keys >> ~deploy/.ssh/authorized_keys
# sshd：/etc/ssh/sshd_config
#   PermitRootLogin no
#   PasswordAuthentication no
#   AllowUsers deploy
sudo systemctl restart ssh
# fail2ban
sudo apt install fail2ban
sudo systemctl enable --now fail2ban
```
客户端（ssh_run.py / push_update.py）：
```python
# AutoAddPolicy → 固定指纹
cli.load_system_host_keys()
cli.set_missing_host_key_policy(paramiko.RejectPolicy())
# 首次：ssh-keyscan -t ed25519 60.204.223.140 >> ~/.ssh/known_hosts（与云控制台指纹核对）
# SSH_USER 默认改 deploy；部署脚本里 systemctl 等命令加 sudo 前缀
```
防火墙基线：
```bash
sudo ufw default deny incoming
sudo ufw allow in on tailscale0
sudo ufw allow 22/tcp        # 若方案 B 且 SSH 也走 Tailscale，可删此条
# 方案 A/C 才开 80/443
sudo ufw enable
```
PG 复核：`listen_addresses='localhost'`（模板已约定），`ss -lntp | grep 5432` 确认。

### 3.5 常态化

- SECURITY.md 写明：漏洞报告渠道、支持版本、"公网入口必须 TLS"基线。
- 每月：`sudo apt update && sudo apt upgrade`（服务器系统补丁）、fail2ban 状态、ufw 规则复核。
- 每季度：gitleaks 全仓扫（02 文档）+ 公网端口扫描自查（`nmap -Pn -p- <服务器IP>` 从外部视角）。

---

## 4. 验收清单

- [ ] /docs、/openapi.json 公网 404（APP_ENV=production 确认 + 模板补行）
- [ ] 明文公网登录入口已消除（方案 B 关公网 / A 域名 TLS / C IP 证书，三选一落地）
- [ ] 手机/电脑经加密通道访问全流程正常（登录、拍照上传、AI 流式）
- [ ] CSP Report-Only 一周无误报后转强制；HSTS 生效（TLS 方案）
- [ ] JWT cookie 带 Secure（TLS 方案）
- [ ] SSH：deploy 用户 + 禁 root + 禁密码 + RejectPolicy + fail2ban
- [ ] ufw 最小开放；PG 只监听 localhost；旁路三服务只绑 Tailscale 且 token 校验实测 401
- [ ] nmap 外部扫描无非预期开放端口
