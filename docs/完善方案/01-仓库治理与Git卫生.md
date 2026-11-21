# 01 · 仓库治理与 Git 卫生

> 覆盖问题：R02（部署产物/dump 入库）、R21（治理文件缺失）、R22（.gitignore 误伤）、R23（第三方 vendor 与一次性目录）、R30（版权合规）
> 优先级：R02 = P0，其余 P2 ｜ 预计总工作量：1.5–2 天

---

## 1. 现状与证据（commit a7f92ea 实测）

### 1.1 仓库体积构成（git tree 全量统计）

| 目录 | 体积 | 文件数 | 问题 |
|---|---|---|---|
| `deploy/` | **80.5 MB** | 24 | 14 个 `kaoyan-deploy-*.tar.gz`（每个 ~3.5MB，2026-10-18~10-26 的构建包）+ **`datasync_20261019.dump` 33.7MB 数据库 dump** 全部被 git 跟踪 |
| `tools/` | 8.6 MB | 32 | `tools/ocr/DeepSeek-OCR/DeepSeek-OCR-main/` 是**第三方仓库整体拷贝**（含 7.4MB 论文 PDF、assets 演示图） |
| `backend-main-fastapi/` | 12.9 MB | 1027 | `scripts/tmp_repo/`（tseka1.json 473KB、math2_tree.json 288KB 等临时抓取产物）入库 |
| `data/backups/` | 0.9 MB | 2 | `kaoyan_school_domain_20261021.sql` 备份 SQL 入库 |
| `frontend/` 根 | — | — | `error-review.png`、`quiz_knowledge_view.png` 调试截图入库 |
| 根目录 | — | — | `kbmap-fix/`（一次性修复 SQL+verify 脚本）、`scripts/organize_knowledge_base.py` 孤悬 |

仓库总 116.2MB，其中 **~90MB 是"不该进版本库的东西"**。每次 clone 都要拖这些死重，且 dump/备份 SQL 可能含用户数据与凭据（详见 02 文档）。

### 1.2 .gitignore 的隐患

```gitignore
*.txt          # ← 全局禁 txt，只豁免 requirements.txt
!requirements.txt
```
任何新增的 `数据说明.txt`、`导入清单.txt`、`LICENSE.txt` 都会被**静默忽略**——`git add` 不报错、`git status` 不显示，文件就这样丢了。这是"为了挡一次性报告"付出的过大代价。

### 1.3 治理文件缺失

- 无 `LICENSE`（公开仓库无许可证 = 默认保留所有权利，他人法律上不可用；与"开源备考平台"的定位矛盾）
- 无 `CONTRIBUTING.md` / `SECURITY.md` / `CHANGELOG.md` / `.github/ISSUE_TEMPLATE/` / `dependabot.yml`
- 仓库 About 为空（无 description / website / topics），GitHub 搜索与个人主页展示都吃亏
- `.github/workflows/` 只有 ci.yml 一个文件

### 1.4 版权内容公开

LFS 跟踪的 `backend-main-fastapi/scripts/data/` 含英语/数学真题 PDF、ECDICT 词库等；`datasync dump` 可能含教材分块正文。README 仅一句"仅用于个人备考学习"。**公开仓库分发版权教材/真题扫描件有侵权风险**（个人使用抗辩不覆盖公开传播）。

---

## 2. 完善标准（做到什么程度算合格）

1. **版本库只存"源码 + 可复现构建所需的一切"**：构建产物、数据库 dump、备份、抓取快照、第三方整仓、调试截图一律不入库。
2. 仓库克隆体积 ≤ 25MB（不含 LFS 拉取）；`git count-objects -vH` 的 size-pack 显著下降。
3. 敏感/版权内容不出现在公开可见的任何 commit（历史含）。
4. `.gitignore` 精确到目录/模式，不用全局后缀封杀；新增正常文件不会被静默忽略。
5. LICENSE / SECURITY / CONTRIBUTING / CHANGELOG / About / issue 模板齐备。
6. 第三方依赖以 submodule / pip 依赖 / 下载脚本之一管理，不 vendor 整仓。

---

## 3. 落地步骤

### 3.1 第一步（5 分钟止血）：仓库转私有

GitHub → Settings → General → Danger Zone → **Change repository visibility → Private**。
理由：R01/R02/R30 三项风险都因"公开"而放大；转私有立即消除公网暴露，后续清理从容做。个人备考平台没有公开协作需求前，私有是正确默认。

### 3.2 移除当前跟踪的产物（先做这步，再清历史）

```powershell
cd D:\研途\gzdx_ky
# 部署产物与 dump（保留 DEPLOY.md / 模板 / 脚本 / nginx / systemd 配置）
git rm --cached deploy/datasync_20261019.dump
git rm --cached (git ls-files 'deploy/kaoyan-deploy-*.tar.gz')
# 备份 SQL、临时抓取、调试截图
git rm --cached data/backups/kaoyan_school_domain_20261021.sql
git rm --cached -r backend-main-fastapi/scripts/tmp_repo
git rm --cached frontend/error-review.png frontend/quiz_knowledge_view.png
# 第三方整仓：改为下载脚本（见 3.5）
git rm --cached -r tools/ocr/DeepSeek-OCR/DeepSeek-OCR-main
```

`.gitignore` 增补（替换 `*.txt` 段）：

```gitignore
# ── 构建/部署产物（可再生，不入库）──
deploy/*.tar.gz
deploy/*.dump
*.dump
*.dump.enc
data/backups/
backend-main-fastapi/scripts/tmp_repo/
# ── 调试截图与一次性报告（精确路径，不再全局禁 txt）──
frontend/*.png
!frontend/public/**
# 删除原来的 "*.txt" 与 "!requirements.txt" 两行；
# 一次性 txt 报告改为放 docs/reports/（入库）或 temp/（已忽略）
# ── 第三方参考仓库 ──
tools/ocr/DeepSeek-OCR/DeepSeek-OCR-main/
```

> 注意：`git rm --cached` 只解除跟踪不删本地文件；dump 与 tar.gz 本地仍保留在 deploy/ 供回滚用，但今后新生成的包建议直接输出到 `deploy/artifacts/`（整目录忽略）。

### 3.3 历史清理（git filter-repo，周末做）

当前历史 116MB 的大头就是这些产物。清理后克隆体积预计降到 ~20MB。

```powershell
# 0) 先完整备份仓库目录（复制 D:\研途\gzdx_ky 到 D:\研途\gzdx_ky_backup_历史清理前）
# 1) 安装工具
pip install git-filter-repo
# 2) 在"完整克隆"上操作（当前是浅克隆，先补全历史；网络慢可走镜像）
git fetch --unshallow
# 3) 删除历史中的产物路径
git filter-repo --invert-paths `
  --path deploy/datasync_20261019.dump `
  --path-glob 'deploy/kaoyan-deploy-*.tar.gz' `
  --path data/backups/kaoyan_school_domain_20261021.sql `
  --path backend-main-fastapi/scripts/tmp_repo/ `
  --path tools/ocr/DeepSeek-OCR/DeepSeek-OCR-main/ `
  --force
# 4) 口令历史清理见 02 文档 §3.4（同一轮 filter-repo 一起做，避免重写两次历史）
# 5) filter-repo 会移除 origin，重新挂回并强推（私有仓库 + 唯一开发者，强推安全）
git remote add origin https://github.com/pyy01048/gzdx_ky.git
git push --force --all
git push --force --tags
```

⚠️ 铁律：**历史重写前必须完整备份**；重写后所有旧 commit SHA 变化，其它机器上的旧克隆必须重新 clone（不能 pull）。LFS 对象不受 filter-repo 影响，但清理后跑 `git lfs fsck` 校验。

### 3.4 一次性目录归位

| 现状 | 处置 |
|---|---|
| `kbmap-fix/`（6 个 SQL + 4 个 verify 脚本） | SQL 已执行过的并入 `backend-main-fastapi/core/sql/` 编号序列或移入 `docs/reports/kbmap-fix/` 留档；verify 脚本移入 `scripts/diagnostics/` |
| 根 `scripts/organize_knowledge_base.py` | 移入 `backend-main-fastapi/scripts/`（按 04 文档分区规则放 oneoff/ 或 tools/） |
| `backend-main-fastapi/` 根的 `TEST_FIX_SUMMARY.md`、`PROJECT_OPTIMIZATION_REPORT.md`、`数据扩充落地报告.md` | 移入 `docs/reports/` |
| `test_merged_model.py`（根，会加载模型权重） | 移入 `scripts/diagnostics/`，pytest.ini 注释同步更新 |

### 3.5 第三方仓库改为下载脚本

`tools/ocr/DeepSeek-OCR/` 只保留一个 `fetch.ps1`：

```powershell
# tools/ocr/DeepSeek-OCR/fetch.ps1 —— 按需拉取，不入库
$rev = "main"  # 钉住具体 commit SHA 更佳
$url = "https://github.com/deepseek-ai/DeepSeek-OCR/archive/refs/heads/$rev.zip"
Invoke-WebRequest $url -OutFile "$PSScriptRoot\deepseek-ocr.zip"
Expand-Archive "$PSScriptRoot\deepseek-ocr.zip" -DestinationPath $PSScriptRoot -Force
```
若只是用其中的模型/推理代码，优先评估 `pip install` 或 git submodule；整仓拷贝是最差选项（无法跟上游更新、体积大、许可证混入）。

### 3.6 补齐治理文件

- `LICENSE`：个人项目建议 **MIT**（代码）+ 在 README 明确"题库/教材/真题内容版权归原权利人，仅限个人学习，不随代码许可证授权"。
- `SECURITY.md`：漏洞报告邮箱 + 支持版本（指向 08 文档的安全基线）。
- `CONTRIBUTING.md`：分支命名（`fix/xxx`、`feat/xxx`）、commit 规范（`type(scope): 摘要`）、PR 必须过 CI、数据变更必须附备份与回滚 SQL（沿用 docx/63 并发协作约定）。
- `CHANGELOG.md`：从 docx/56–69、docs/P0-P1 修复报告提炼版本节点；此后每次发布追加。
- `.github/dependabot.yml`：

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: "/backend-main-fastapi"
    schedule: { interval: weekly }
  - package-ecosystem: npm
    directory: "/frontend"
    schedule: { interval: weekly }
```
- `.github/ISSUE_TEMPLATE/bug.md`：复现步骤 / 期望 / 实际 / 环境（Python、PG、浏览器）四段。
- About 填写：description「贵州大学 834/0854 考研本地化备考平台：OCR 入库 · 知识地图 · 刷题 · 错题 · 本地 AI 答疑」，topics：`kaoyan, fastapi, react, rag, ollama, postgresql, pgvector, ocr`。

---

## 4. 验收清单

- [ ] 仓库已转私有（或完成全部历史清理 + 版权内容移除后再评估公开）
- [ ] `git ls-files deploy/` 只剩配置/脚本/文档，无 tar.gz/dump
- [ ] `git count-objects -vH` size-pack ≤ 25MB（filter-repo 后）
- [ ] 新建 `测试.txt` 能被 `git status` 正常显示（.gitignore 不再误伤）
- [ ] LICENSE/SECURITY/CONTRIBUTING/CHANGELOG/dependabot/issue 模板存在且内容非占位
- [ ] About 有描述与 topics
- [ ] `tools/ocr/DeepSeek-OCR/` 只有 fetch 脚本与自研适配代码
- [ ] 历史清理前有完整备份目录，清理后 `git lfs fsck` 通过、CI 全绿
