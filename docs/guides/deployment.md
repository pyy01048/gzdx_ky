# 部署（指针）

> 最后核对：2026-11-20 · 维护人：pyy

部署的唯一真相是 **[deploy/DEPLOY.md](../../deploy/DEPLOY.md)**（安装、systemd、Nginx、
环境变量、备份回滚、安全基线）。本页只列"最近变化"与"易错点"，避免两处口径漂移。

## 最近变化（2026-11-20）

| 项 | 变化 |
|---|---|
| 前端回滚 | `push_update.py` 解包前自动 `static → static.prev`，`rollback.sh frontend` 真正可用 |
| 版本标识 | 打包前生成 `_version.py`；`/api/health` 返回 `git_sha` / `built_at` |
| 迁移 | 部署统一执行 `execute_core_sql.py --all-pending`（账本化） |
| 部署包 | 输出 `deploy/artifacts/kaoyan-deploy-<ts>-<sha>.tar.gz`，本地保留 5 份 |
| 备份 | `backup.sh` 接通 rclone 异地 + healthchecks 心跳 + 本地 7 / 异地 30 份 |
| 监控 | `watchdog.sh`（磁盘/服务/家庭节点）+ `logrotate-kaoyan.conf` |
| SSH | 默认 `deploy` 用户 + 主机指纹固定校验（`SSH_HOST_POLICY=pin`） |
| 安全 | `APP_ENV=production` 写入环境模板；CSP Report-Only；生产 cookie 默认 Secure |

## 易错点

1. `APP_ENV=production` 缺失 → `/docs`、`/openapi.json` 公网可达。
2. 生产 cookie 默认 `Secure`：未上 TLS 时登录会失败（临时 `COOKIE_SECURE=0`，整改后移除）。
3. 迁移账本首次部署：`--status` 确认后再 `--all-pending`；账本为空且已有业务表会自动 baseline。
4. Nginx 改配置后先 `nginx -t` 再 reload；CSP 先 Report-Only 一周。
5. 部署包内不含 `.venv/data/uploads/logs`，解包不会覆盖运行数据。
