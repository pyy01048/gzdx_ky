# 实测陷阱档案（证据级）

每条含：现象 → 根因 → 处置。全部在本仓库真实发生过。

## T1 mock 照抄页面想象的后端形状

- 现象：测试全绿，线上整块永不渲染 / 渲染崩。
- 根因：mock 返回 `[]` 而真实接口返回对象（或反之）；`correct_rate` 0-100 与 `accuracy` 0-1 混用；
  mock 写成 client.js 里不存在的旧方法名（mock 永不生效）。
- 处置：写 mock 前读真实路由函数返回语句与 client.js 方法签名；断言容器类型与数值口径。

## T2 200 + 空 body → null 落 state 后渲染崩

- 处置：client 层对空 body 归一为约定空态结构；页面渲染前 null 守卫。

## T3 App.jsx 未闭合 JSX 注释吞掉路由

- 现象：整片路由消失、白屏。
- 处置：改 App.jsx 后必须 build + 浏览器逐路由 smoke。

## T4 全局文本查询多命中（表现为 timeout）

- 现象：todayTasks 双面板导致文本定位多命中，自动化超时。
- 处置：定位用 role / testid / 容器限定，不用裸全局文本。

## T5 vi.mock 工厂闭包 const → TDZ

- 处置：mock 工厂内不得引用外部后声明的 const；数据放工厂内或 hoisted。

## T6 wrap_conn 被 commit 失效

- 处置：测试包装连接的生命周期覆盖整个用例，commit 后重新包装或改用事件监听。

## T7 TEXT 列与 timestamptz 列格式分治

- 现象：naive UTC 写入、aware 读出，`now - row.created_at` TypeError → 500。
- 根因：PG 侧 TIMESTAMPTZ（迁移 116），models 声明 naive DateTime；database.py 强制 session timezone=UTC。
- 处置：一切读出时间先过 `utils.timeutil.to_naive_utc`；进 JSONB / 审计快照先 `iso_utc_z`
  （AuditLog.before_data/after_data 裸 datetime 会序列化 500）。

## T8 前端接口漂移

- 处置：定期把 client.js 全部调用 + 裸 fetch 对照 OpenAPI（历史基线 224 条调用 + 2 处裸 fetch）。

## T9 迁移账本 checksum halt

- 现象：启动「没报错」但新索引不存在；后续所有编号迁移被 halt。
- 根因：已入账脚本内容被修改 → `ChecksumMismatch`；启动日志 GBK，中文 grep 漏报。
- 处置：结构变更只加新编号脚本；重登记前逐条比对线上 schema（列类型 / 索引 / 约束）与脚本当前内容全等；
  用 `core.migrations.run_pending` 手动跑并打印 applied/baselined；查 `pg_indexes` 确认生效。
  事故记录：116 入账后被编辑 → 117/118 全部停摆，比对确认线上已含 116 全部 DDL 后重登记 checksum 才恢复。

## T10 测试库并发污染

- 现象：计数断言（如「某事件恰好 1 条」）随机失败；单跑同用例却通过。
- 根因：残留 pytest 进程与当前跑共用测试库；fixture wipe 只 NULL 可空外键不删行时跨运行累积。
- 处置：wipe 必须真删审计 / 事件行；开跑前清残留进程；stop 后台任务后按 PID 确认子进程已死。

## T11 凭据密文与密钥不匹配 → 整链路 500

- 现象：/api/netdisk/files、/api/ai/providers 500（InvalidTag → SecretDecodeError）。
- 根因：EncryptedText 在 ORM hydration 期解密，早于任何业务 try/except。
- 处置：列层 `process_result_value` 捕获 SecretDecodeError 降级 None（每进程告警一次）；
  业务侧 None = 未配置 → 走「从未授权 200 空态」；写回路径 exclude_unset / 显式赋值，禁止盲写回。

## T12 浏览器验证假象

- hash 路由同 URL 导航 = same-document，不加载新 bundle（截图仍是旧 UI）。
- 重启 :8000 后会话全失效（JWT 密钥随进程），401 先重登录再下结论。
- 截图工具：省略 filename 才内联返回；`scale` 必填；console 查询需 level 参数。

## T13 空态与假数据

- 前端 seed 数据冒充真实数据是缺陷；空态文案 + 恢复路径才是交付物。
- 硬编码路径 / 科目 / 计数一律视为缺陷（data-agnostic 框架优先）。
