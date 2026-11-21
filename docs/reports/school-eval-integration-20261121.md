# 外部资产并入与工学学科评估上线报告（2026-11-21）

> 范围：用户指示「D:\研途\题库建设、D:\下载\数据管理、D:\下载\工学院校评价库 全部并入 D:\研途\gzdx_ky，秉着最高标准完善剩下的部分」。
> 纪律：reports 只增不改；所有数字来自实测命令输出，不手填估算。

## 一、三个文件夹并入（data-assets/，gitignore 不入库）

| 包 | 来源 | 实测体量 | 校验 |
|---|---|---|---|
| 题库建设 | `D:\研途\题库建设` | 85 文件 / 506,159,543 B | robocopy 后文件数+字节总数与源一致 |
| 08工学数据包 | `D:\下载\数据管理\gzdx_ky_08工学数据包` | 23,652 文件 / 2,059,230,965 B | 同上 |
| 工学院校评价库 | `D:\下载\工学院校评价库` | 5 文件 / 1,782,222 B | 同上 |

- `D:\下载\数据管理` 顶层 5 个 CSV 与包内 `index/` 同名件 md5 一致（重复件，未复制）。
- 顶层 `README_交付说明.md` 与包内版本仅差一行 AI 生成注记，以包内为准。
- 外部审计方案 14 篇并入 `docs/完善方案/`（docs/README §四已改「不入库」旧注）。
- 目录说明：`data-assets/README.md`（消费状态 + 口径纪律 + 服务器导入注意）。
- 踩坑：Git Bash MSYS 把 robocopy `/E` 转成 `E:/` 致静默失败（exit 0），需 `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"`。

## 二、工学院校评价库 → PG 权威 schema + 功能上线

### 数据层
- 新分片 `core/sql/119_school_engineering_eval.sql`：ky_discipline / ky_school / ky_school_discipline_eval / ky_school_double_first + 2 视图，全列 COMMENT ON，幂等。
- `core/pg_schema.sql` 补接 \ir：119 + **116/118（此前漏接，健康检查门禁会 FAIL，已验证幂等后补上）**。
- 导入脚本 `scripts/import_school_eval_pg.py`（默认 dry-run，--apply 单事务）：MySQL 交付件转写解析，industry_tags/strengths 的 Python 字面量串 → JSONB。
- 本地与服务器入库数一致：**48 / 329 / 2011 / 179**；交叉校验 schools.json 内嵌 evals 2011 = discipline_eval.json 2011。
- 数据清洗：直辖市 province==city 导致源简介「位于北京北京」叠词 **82 行**，在导入归一层 `_dedup_loc` 修复，两库重导后均为 0。

### API（routers/kaoyan/school_eval.py，注册进 kaoyan 域）
- `GET /api/kaoyan/school-eval/schools`（q/province/四标志/unit_type/data_status/sort/分页）
- `GET /api/kaoyan/school-eval/schools/{id}`（评估明细按等级排序 + 双一流 + 优势学科 + kaoyan_schools 联动 id）
- `GET /api/kaoyan/school-eval/disciplines`（48 学科 + school_cnt）
- `GET /api/kaoyan/school-eval/disciplines/{code}/rank`（normal/joint/institute 分组不混排）
- 零 current_user 依赖 → `/api/kaoyan` 前缀访客可读；每个响应带 caveats 口径四条。

### 前端（/kaoyan/school-eval，公开壳 KaoyanModuleLayout 内）
- `src/v3/pages/KaoyanSchoolEval.jsx`：Segmented 双视图（院校总览 329 所一次拉全量本地筛选 + 按学科选校服务端榜单）；详情 Dialog（优势学科对象数组渲染、评估等级徽标、双一流、站内院校详情跳转）；URL 深链 `?view=rank&disc=0812`；caveats 常驻渲染；空态即交付。
- navConfig school 组第 4 项 + CRUMB；kaoyanApi 4 方法；App.jsx lazy+route；pages.smoke 守卫表登记。
- 实测捕获形状陷阱：strengths_json 是 `[{code,name,grade,double_first}]` 对象数组而非字符串数组（直接渲染会 React crash），已按真实数据修正。

## 三、测试与构建（实测）

| 项 | 结果 |
|---|---|
| tests/test_school_eval.py（新增 9 用例：壳/口径/筛选/排序分页/422/详情/联动/分组/404） | 9 passed |
| tests/test_api_contract.py（新路由占位 id 404 入 ALLOWED_4XX 白名单，理由注明） | 25 passed, 1 skipped |
| tests/test_kaoyan_ext.py 回归 | passed（合跑 48 passed） |
| 前端 vitest 全量 | **50 文件 / 489 用例全过** |
| vite build | 10.43s 成功（产物 → backend static） |
| project_healthcheck | 27 项 24 过；3 个 FAIL 均为**存量问题**（见 §六） |

## 四、部署与公网验证（60.204.223.140）

- `deploy/push_update.py`（SSH_USER=root）：版本 26b9bdd-dirty；迁移账本已有 51 条 → `--all-pending` 正确只执行 119 并入账（无 baseline 陷阱复发）。
- 评价库数据文件单独 scp 至 `/opt/kaoyan/data-assets/工学院校评价库/`（部署包不含 data-assets），服务器 --apply 入库 48/329/2011/179。
- 公网匿名实测：`schools?is_985=true` total=**39**；`disciplines/0812/rank` total=**172**（normal 165 / joint 6 / institute 1）；schools/disciplines/SPA 路由均 200。
- Playwright 实测线上页面：总览 24 卡片、统计瓦片 329/39/113/2011（全由真实数据派生）、口径说明在页；0812 榜单 172 行、首位北京大学 A+；详情弹窗优势学科/评估明细/「查看招生数据」链接齐全；**控制台 0 错误**。

## 五、810 章节习题批次服务器同步（附带闭合）

- 现状核查：本地 chapter_exercise 823 题（810 批次 + 13 存量），服务器 **0**（2026-11-20 导入只入了本地）。
- 服务器缺 8 个科目（力学/动力工程及工程热物理/微机原理与接口技术/电力电子技术/电力系统分析/电机与拖动/过程控制/高电压技术）；subject_removals 空（无删除墓碑）→ 经 **subject_config 可写视图**（092 触发器）补建 8 科，未私建 subjects 行，符合 ADR-002 单源。
- 新脚本 `scripts/sync_quiz_chapter_exercise.py`（--export/--apply/--dry-run）：科目名映射 + content+options 指纹去重、只增不改、chapter_id/origin_* 跨库置 NULL、来源诚实标注保留。
- 踩坑：`option_count`/`is_past_exam` 是 GENERATED ALWAYS 列，INSERT 必须排除；subject_config 是视图不能 ON CONFLICT。
- 结果：服务器 **APPLY_OK 新增 823，指纹跳过 0**；高电压技术/过程控制/信号与系统 各 30 题在库。两脚本已进 push_update 打包白名单。

## 六、文档治理与链接门禁

- `.gitignore` += `data-assets/`；`data-assets/README.md` 消费台账；docs/README §三/§四 更新；CHANGELOG [Unreleased] 补记。
- `check_doc_links.py` 首跑发现 **13 条存量失效链接**：`docs/guides/` 7 篇（git 索引有暂存内容、工作树文件缺失，AD 状态）与 `docs/plan-gap/` 6 篇（HEAD 有、工作树被删，本轮取证确认删除发生在本会话之前、非文档三分诊所为）。从 git blob 原样恢复 13 文件（纯新增写回，未用 checkout/restore 覆盖任何现存文件），复检 **18 文档相对链接全部有效**。

## 七、遗留与待决（不在本轮擅自处理）

1. **healthcheck 3 个存量 FAIL**：① 9 个分片漏 \ir（000_schema_migrations、108×2、109、110、111、112×2、113）——需逐个判定是「漏接」还是「有意不入主链」（如账本表由执行器自建），不能盲接；② 109_admission_details.sql 3 处 CREATE INDEX 非幂等；③ pdf_export.py 6 处 Windows 字体盘符字面量（Linux 部署需字体回退策略）。
2. **本地↔服务器题库全量分叉**：本轮同步后服务器 11,305 题 vs 本地 11,006 题，且分类分布不同（本地真题 2,589 / 服务器真题 724+新增）。chapter_exercise 批次已对齐；其余分叉属历史双向漂移，全量合并需要「哪边是权威」的产品决策，未擅自合并。
3. 工作树含跨阶段未提交变更（本轮未提交，避免混入他人/他阶段暂存内容）。
4. **服务器 worker 静默死亡观察**（存量，非本轮引入）：24h 内 38 次 "Child process died"（多数集中在部署重启窗口；孤立事件 23:21:46 与 01:17:23，后者早于/独立于本轮代码变更）。无内核 OOM、无 segfault 记录、无 Python traceback；uvicorn 父进程 ~2s 自动补 worker，期间出现短暂 502。01:17 事件后全路由复测：login 200（0.13s）/ forgot/reset 422 / inspect 200 / reset-link 302 / school-eval 200，全部健康。建议下次维护窗口在 kaoyan.service 加 `Environment=PYTHONFAULTHANDLER=1` 以捕获下次死亡现场，本轮未重启服务（深夜有真实用户流量）。
