# 安全策略

## 支持版本

| 版本 | 状态 |
|---|---|
| main | 支持 |

## 报告漏洞

发现安全问题请通过 GitHub 仓库的私密 Security Advisories 提交：
`https://github.com/pyy01048/gzdx_ky/security/advisories/new`

不接受通过公开 issue 报告安全漏洞。

## 处理时限

- 高危（公网暴露组件，如 multipart/PDF 解析 DoS）：48 小时内响应
- 其它：一周内响应

## 安全基线

详见 `docs/` 内安全治理文档：
- 密钥管理：连接参数只来自环境变量，禁止入库入源码
- 公网组件漏洞：`pip-audit -r backend-main-fastapi/requirements.txt --strict` 须 0 high/critical
- 服务器凭据：`/etc/kaoyan/backend.env` 权限 600，数据库口令与开发环境不同
