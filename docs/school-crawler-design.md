# 院校爬虫设计与实测报告（school_crawler）

> 实现：`backend-main-fastapi/pipeline/school_crawler.py`（2026-10-18/19 夜间放量版）
> 状态：试点验证通过（+3 院校/+43 专业），全国放量运行中（见文末实时计数）

## ADR-1 数据源：研招网 zsml 公开接口
- **单位层** `GET /zsml/rs/dws.do?ssdm=&dwmc=&xxfs=1&pageno=1`（匿名可用）
- **专业层** `POST /zsml/rs/dwzys.do`（form: dwdm/mldm/zymc/xxfs/curPage，无需 sign）
- 备选：院校官网（维护成本高）、教育部名单（仅静态名单无招生数据）→ 不采用
- 实测约束（2026-10-18）：两接口匿名每页硬封顶 10 条，翻页要求登录；`dwmc/zymc` 模糊搜索有效 → 用**关键词穷举**突破 10 条上限（与 services/kaoyan/spider_yz 同构）；`mldm` 门类过滤有效（08 工学/07 理学）

## ADR-2 全国覆盖策略：两阶段
1. **Roster 阶段**（`--roster-sweep`）：31 省 × 76 个泛化关键词穷举 dws.do，每请求收 ≤10 个单位，按 dwdm 去重 → 覆盖研招网几乎全部招生单位（~900+），1 请求/组合，共 ~2356 请求建档 `kaoyan_schools`（名称/省份/dwdm 入 tags）
2. **Majors 阶段**（`--all-schools`）：对库内全部院校逐所抓专业目录（门类基线 + 关键词穷举，kw-limit 控请求量），断点按 (dwdm|门类) 记录

## ADR-3 合规与稳健性
- 仅公开匿名接口；不带任何登录态/cookie；不碰需登录的翻页
- 限速：每请求 uniform(1.5, 2.5)s，失败退避 2/4/8s；robots.txt 预检（实测 404=无限制，若出现 Disallow /zsml 则拒爬）
- 请求预算硬上限（--max-requests）超限优雅停止；全状态断点（data/spider_state/*.json）
- UA 固定 Chrome 标识；溯源：source_url=yz.chsi.com.cn、collected_at、KaoyanCollectionRun 批次日志（含逐请求清单）
- 落库：单校一事务（批次回滚粒度=院校）；upsert 幂等（重跑不重复插入）

## 试点实测（2026-10-18 23:40）
- 北邮/北科大/清华：院校 +3，专业 +30（工学），请求 7/40
- 二轮补抓：理学 +13 专业（kw-limit 3）
- 字段完整率 100%（code/name/subject_code/degree_type）

## 夜间放量实时计数（运行中，以 DB 为准）
- 阶段 1 完成后：`kaoyan_schools` ≈ 900+（全国招生单位）
- 阶段 2 完成后：`kaoyan_majors` ≈ 数千（全库院校 × 工学/理学基线+关键词）
- 查询：`SELECT COUNT(*) FROM kaoyan_schools / kaoyan_majors;`

## 已知边界与后续
- 分数线/招生人数（scorelines/admissions）匿名接口拿不到 → 留登录态方案或人工导入，不在本轮
- `--school-list` 支持外部名单文件（教育部 2952 所名单 CSV 已部分获取，网络受限，后续补全）
- 门类覆盖：本轮 08 工学/07 理学；其余门类（经管文法等）加 CATEGORIES 条目即可放量
