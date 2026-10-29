# 考研学习平台

> 面向**贵州大学 834 电子技术基础**（数字电子技术 + 模拟电子技术）的本地化备考系统。
> 核心能力：扫描版真题 OCR 入库 → 章节/知识点/题型三级结构化 → 错题本与知识库联动 →
> 本地模型优先的 AI 答疑 → 复习进度追踪。
>
> **数据不出网**：本地模型 + 本地知识库；需要更强能力时可选云端 API 兜底。

---

## 目录

- [快速开始](#快速开始)
- [启动方式（5 种）](#启动方式5-种)
- [桌面快捷方式](#桌面快捷方式)
- [功能总览](#功能总览)
- [手机使用](#手机使用)
- [AI 与模型](#ai-与模型)
- [知识库](#知识库)
- [目录结构](#目录结构)
- [常用维护命令](#常用维护命令)
- [故障排查](#故障排查)
- [文档索引](#文档索引)

---

## 快速开始

### 环境要求

| 项 | 要求 | 本机实测 |
| :--- | :--- | :--- |
| Python | 3.10+ | 3.13.9 (Anaconda) |
| Node.js | 18+（仅改前端时需要） | v24.16.0 |
| GPU | 可选（本地模型加速） | RTX 4060 Laptop 8GB |
| 磁盘 | 建议 ≥ 20GB 可用 | C 92.9GB / D 264.2GB |

### 首次运行

```bash
# 1. 装依赖
cd backend-main-fastapi
pip install -r requirements.txt

# 2. 环境自检（会明确告诉你能跑 / 缺什么）
python scripts\diagnostics\check_env.py

# 3. 启动
双击项目根目录的「启动.bat」，或
python main.py
```

浏览器打开 **http://127.0.0.1:8000**

> 前端已构建好并放在 `backend-main-fastapi/static/`，
> **不改前端就不需要 npm**。只改后端时直接启动即可。

---

## 启动方式（5 种）

### 方式 1：图形菜单（推荐）

双击 **`启动.bat`**，出现菜单：

```
   ============================================================
      考研学习平台 · 启动器
   ============================================================

      当前配置: 监听 0.0.0.0:8000
      局域网访问: 已开启（手机可访问）
      [状态] 服务正在运行 -> http://127.0.0.1:8000

   ------------------------------------------------------------
     请选择启动方式:
   ------------------------------------------------------------

      [1]  本机模式     仅本机访问，最安全（推荐日常用）
      [2]  局域网模式   手机/平板可访问，显示二维码
      [3]  后台模式     静默启动，不占任务栏，自动开浏览器
      [4]  停止服务     关闭正在运行的服务
      [5]  打开浏览器   服务已在运行时直接用
      [6]  环境自检     检查 Python / 依赖 / 数据库 / 模型
      [7]  开发模式     前端热更新（需要 Node.js）

      [0]  退出
```

### 方式 2：单文件直启（不看菜单）

| 文件 | 用途 |
| :--- | :--- |
| `启动-本机.bat` | 仅本机访问，最安全 |
| `启动-局域网.bat` | 手机可访问，打印二维码 + 自动放行防火墙 |
| `停止.bat` | 关闭服务（含后台模式） |

### 方式 3：命令行

```bash
cd backend-main-fastapi

python main.py                    # 按 .env 的 HOST/PORT 启动
python run_server.py              # 后台模式（写 PID + 日志，便于精确停止）
python show_access.py             # 只打印局域网地址与二维码
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload   # 开发热重载
```

### 方式 4：桌面快捷方式

见下节。

### 方式 5：开发模式（前后端分离）

```bash
# 终端 1：后端热重载
cd backend-main-fastapi
python -m uvicorn main:app --reload

# 终端 2：前端热更新
cd frontend
npm run dev          # http://127.0.0.1:5173
```

或用 `启动.bat` 选 `[7]` 一键拉起两个窗口。

---

## 桌面快捷方式

```bash
python tools/create_shortcuts.py            # 只建主快捷方式
python tools/create_shortcuts.py --all      # 主 + 本机 + 局域网 + 停止
python tools/create_shortcuts.py --remove   # 删除
```

会创建 4 个图标：

| 图标 | 作用 |
| :--- | :--- |
| 考研学习平台 | 启动器（多模式菜单） |
| 考研平台·本机 | 直接本机模式 |
| 考研平台·局域网 | 直接局域网模式 |
| 考研平台·停止 | 关闭服务 |

> 脚本会自动探测真实桌面路径 —— 本机桌面被重定向到了 `D:\桌面`，
> 硬编码 `%USERPROFILE%\Desktop` 会找不到。

---

## 功能总览

| 模块 | 路径 | 能力 |
| :--- | :--- | :--- |
| 仪表盘 | `/` | 倒计时、今日任务、学习时长趋势、连续打卡、薄弱科目 |
| **知识地图** | `/kbmap` | 章节→知识点→题型三级结构 + 掌握度 + 复习队列 + 覆盖率体检 |
| 任务打卡 | `/tasks` | 打卡、阶段管理、复习计划、AI 生成计划 |
| 刷题中心 | `/quiz` | 386 道题（当前为 PG 导入子集，见「知识库规模」）、按知识点/**真题套卷/按年份**题号网格、答题提交、统计、题库管理 |
| 错题本 | `/notebook` | 📷 手机拍照 OCR 收录、自动挂靠知识点、AI 分析、毕业归档 |
| 文档知识库 | `/documents` | 上传解析、扫描版真题 OCR、**知识库健康面板（体检+一键修复）** |
| AI 助手 | `/assistant` | SSE 流式对话，本地 Ollama 优先 / 云端兜底，RAG 标注来源 |
| 记忆卡片 | `/cards` | SM-2 间隔重复 |
| 单词记忆 | `/words` | 20 词（当前为 PG 导入子集）、背诵、跟打、默写 |
| 学习计划 | `/planner` | 日/周/月计划、艾宾浩斯、阶段复习 |
| 网盘联动 | `/pan` | 百度网盘 OAuth、关键词搜索、下载入库、token 自动续期 |
| 设置 | `/settings` | **备考科目**、**模型选型**、AI 服务商、手机访问二维码、数据导入导出 |

> **已移除的冗余模块**（源码在 `_archive/`，数据已备份）：
> - **课程表**：三张表长期 0 行，属本科教务功能，与考研无关
> - **专注计时 / 番茄钟**：`pomodoro_sessions` 长期 1 行数据，
>   却占 13.7KB 路由 + 32.7KB 页面 + 200+ 处引用。
>   **学习时长统计保留**（`study_sessions`），仪表盘时长/趋势/打卡不受影响。

---

## 手机使用

1. 双击 **`启动-局域网.bat`**（或 `启动.bat` 选 `[2]`）
2. 控制台会打印手机访问地址与二维码
3. 手机连**同一 WiFi**，扫码或输入地址

```
手机访问 : http://192.168.10.6:8000   ← 同一 WiFi 下可用
```

**建议开启访问密码**：编辑 `backend-main-fastapi/.env`

```ini
APP_PASSWORD=你的密码
```

否则同一 WiFi 下任何设备都能访问。

**手机端典型用法**：拍照收录错题 → OCR 自动识别 → 挂靠知识点 → 加入复习队列。

→ 详见 [docs/手机访问与局域网服务器.md](docs/手机访问与局域网服务器.md)

---

## AI 与模型

### 双层架构

| 层 | 说明 |
| :--- | :--- |
| **本地** | Ollama（`127.0.0.1:11434`）。按科目自动选模型；未启动自动跳过 |
| **云端** | DeepSeek / 豆包 / 通义千问等 OpenAI 兼容接口 |
| **路由** | `services/ai_router.py`：识别问题科目 → 选对应模型 → 本地不可用自动降级云端 |
| **选型** | `services/model_registry.py`：按**本机显存**判定能不能跑，不看排行榜参数量 |
| **检索** | PostgreSQL GIN（jieba/BM25）+ 向量（bge-small-zh-v1.5）+ RRF 融合（SQLite 降级路径保留 FTS5） |

### 分科路由（8GB 显存实测口径）

| 科目 | 首选模型 | 需显存 | 判定 |
| :--- | :--- | ---: | :--- |
| 数学 / 数电 / 模电 / 电路 / 信号与系统 / 通信原理 / 光学 / 普物 / 408 / 真题 | **deepseek-r1:7b** | 5.91 GB | ✅ 完美 |
| 政治 / 英语 | **qwen3:8b** | 6.26 GB | 🟢 可运行 |
| 文档处理 / OCR 纠错（批量） | **qwen3:4b** | 3.82 GB | ✅ 完美 |

### 安装本地模型

```bash
cd backend-main-fastapi

python setup_local_models.py          # 检测硬件/Ollama/已装模型，给出下一步
python setup_local_models.py --pull   # 自动拉取推荐模型
```

或手动：

```bash
ollama pull qwen3:4b            # 2.6GB，最小，先跑通链路
ollama pull deepseek-r1:7b      # 4.7GB，推理首选
ollama pull qwen3:8b            # 5.2GB，中文最强
```

> ⚠️ **模型存放位置**：默认 `C:\Users\<你>\.ollama\models`。
> 本机 C 盘只剩 92.9GB，建议移到 D 盘：

```bash
setx OLLAMA_MODELS "D:\ollama-models"
# 设置后需重启 Ollama 生效
```

> ⚠️ **网络实测**：Ollama registry 约 300-600 KB/s，
> 2.6GB 约需 50 分钟。下载**可断点续传**，中断后重跑同一条命令会接着下。

### 云端兜底

在「设置 → AI 服务」填 API Key 即可。本地没模型时自动走云端，不会报错。

→ 详见 [docs/模型选型与分科路由.md](docs/模型选型与分科路由.md)

---

## 知识库

### 建立链路（8 步）

```
资料（本地目录 / 上传 / 百度网盘）
  ├─ 1. 扫描入库    目录递归扫描 PDF/Word/PPT/TXT/MD
  ├─ 2. 解析正文    pypdf → pdfplumber 提取文本层
  ├─ 3. 扫描件 OCR  无文本层 ⇒ pypdfium2 渲染 → 本地 RapidOCR
  ├─ 4. 分块        按段落/句子切分，块间带重叠
  ├─ 5. 全文索引    jieba 分词 → PostgreSQL GIN（SQLite 降级路径保留 FTS5）
  ├─ 6. 向量索引    bge-small-zh-v1.5 本地嵌入
  ├─ 7. 结构化      识别章节树 →「章节→知识点→题型」
  └─ 8. 元信息标记  doc_type + 扫描件标记
```

**四个入口**：目录批量导入 · 单文件上传 · 百度网盘下载入库 · 一键修复缺口

### 体检与自愈

```bash
python -m services.kb_pipeline            # 体检：如实报告缺什么
python -m services.kb_pipeline --heal     # 自愈：缺什么补什么
```

或在「文档知识库」页顶部看**知识库健康面板**，一键修复。

修复顺序（有依赖，不能调换）：
状态归一化 → **找回源文件路径** → 空正文重解析（含 OCR）→ 元信息 → 补向量

### 当前数据实况（2026-10-10 实测，真库 `database/kaoyan.db`）

| 指标 | 数值（2026-10-21 实测，`scripts/diagnostics/readme_counts.py` 可复核） |
| :--- | ---: |
| 文档 | 705 |
| 知识分块 | 20,676 |
| 已向量化 | 20,676（100%） |
| 知识点 | 1,860 |
| 题目 | 386（全部可作答；345 有解析、259 带图；57 有年份 2005–2015 且标注真题来源） |
| 院校 / 院校条目 / 公告 | 818 / 128 / 1,258 |
| 分数线 | 88,315（择校采集中，数字随 `kaoyan_score_crawler` 增长） |
| 单词 | 20 |

> 旧版 README 写「9,171 题 / 4,569 词 / 文档 1,846」——那是 SQLite 时代的数字；
> 迁移 PG 后只导入了子集，本表已按库中实测更新。刷新口径：
> `cd backend-main-fastapi && .venv/Scripts/python.exe scripts/diagnostics/readme_counts.py`

→ 详见 [docs/本地知识库建立与自愈.md](docs/本地知识库建立与自愈.md)

---

## 目录结构

```
平台/
├── 启动.bat                    ★ 多模式启动菜单
├── 启动-本机.bat                 仅本机访问
├── 启动-局域网.bat               手机可访问 + 二维码
├── 停止.bat                     关闭服务
├── README.md                    本文件
│
├── backend-main-fastapi/        后端（FastAPI + SQLAlchemy 2.0 + PostgreSQL，SQLite 降级路径保留）
│   ├── main.py                  入口：路由注册 + 种子上线
│   ├── run_server.py            后台模式启动器（写 PID）
│   ├── check_env.py             ★ 环境自检
│   ├── setup_local_models.py    ★ 本地模型检测/拉取
│   ├── project_audit.py         ★ 项目体检
│   ├── reclassify_subjects.py   学科重标（幂等）
│   ├── check_ocr_quality.py     OCR 噪声量化
│   ├── migrate.py               数据库迁移入口
│   ├── models.py                27 个 ORM 模型
│   ├── routers/                 20 个路由模块
│   ├── services/                32 个业务服务
│   │   ├── model_registry.py    ★ 模型档案 + 显存判定 + 分科路由
│   │   ├── taxonomy.py          ★ 科目/章节/题型唯一权威（16 科）
│   │   ├── subject_config.py    ★ 备考科目配置
│   │   ├── kb_pipeline.py       ★ 知识库体检 + 自愈
│   │   ├── kb_service.py        分块入库 + 学科分类器
│   │   ├── ai_router.py         科目识别 + 引擎路由
│   │   ├── document_parser.py   解析 + 扫描件 OCR
│   │   └── netdisk_service.py   百度网盘
│   ├── scripts/                 迁移与重建脚本
│   ├── tests/                   128 项测试 + 3 套验收
│   ├── static/                  前端构建产物（已含）
│   └── data/
│       ├── kaoyan.db            数据库（单文件）
│       ├── storage/documents/   资料原件
│       ├── lora_finetune/       微调模型（5.76GB + 0.66GB）
│       └── archive/             历史备份
│
├── frontend/                    前端源码（React + Vite）
│   └── src/
│       ├── pages/               15 个页面
│       ├── components/          含 ModelSelectPanel / SubjectSettings / KbHealthPanel
│       ├── styles/              6 个样式文件
│       └── api/client.js        接口层
│
├── docs/                        ★ 文档中心
│   ├── 项目方案.md                权威方案与数据实况
│   ├── 项目深度体检报告.md          ★ 缺口清单与优化建议
│   ├── 备考科目配置.md             考试口径 vs 专业课支撑
│   ├── 模型选型与分科路由.md        该装哪个模型 / 哪科用哪个
│   ├── 手机访问与局域网服务器.md     手机使用与排查
│   ├── 本地知识库建立与自愈.md      知识库体检与修复
│   ├── 百度网盘模块说明.md         网盘接入
│   ├── 答疑模型训练指南.md         模型训练与评测
│   └── archive/                 历史文档（已过期仅留档）
│
├── tools/                       构建与安装工具
│   ├── make_bats.py             生成 .bat（无 BOM，含校验）
│   └── create_shortcuts.py      创建桌面快捷方式
│
├── assets/                      图标
├── backend-ocr-paddle/          可选 OCR 微服务（PP-OCRv5，端口 8888）
└── _archive/                    归档（8 个子目录，零引用）
    ├── dead_dirs/                 旧实现 + 废弃 alembic + 旧启动脚本
    ├── oneoff_scripts/            一次性诊断脚本
    ├── removed_pomodoro/          番茄钟（已移除模块）
    ├── removed_schedule/          课程表（已移除模块）
    └── unused_*/                  未使用的历史组件
```

---

## 常用维护命令

全部在 `backend-main-fastapi` 目录下执行。

### 健康检查

```bash
python scripts\diagnostics\check_env.py            # 环境自检（能不能跑）
python scripts\diagnostics\api_health_check.py     # 接口健康
python -m services.kb_pipeline                     # 知识库体检
python scripts\diagnostics\check_ocr_quality.py     # OCR 噪声量化
python -m pytest tests/ -q                         # 后端单测
```

### 数据维护

```bash
python -m services.kb_pipeline --heal        # 修复知识库缺口
python -m services.kb_pipeline --heal --embeddings   # 顺带补向量
python scripts\backfill_quiz_meta.py --apply # 刷题 year/paper/题号 回填（幂等，先备份）
python migrate.py                            # 数据库迁移
```

> ⚠️ **真库在 `D:\平台\database\kaoyan.db`**（由 `.env` 的 `DATABASE_PATH` 指定）。
> `backend-main-fastapi/data/kaoyan.db` 是空的诱饵库，别用它判断数据。
> 完整、与当前代码一致的文档见 **`docx/`**（01 总览 / 02 启动使用 / 03 刷题与院校 / 04 路线图）。

### 模型

```bash
python setup_local_models.py           # 检测 + 建议
python setup_local_models.py --pull    # 拉取推荐模型
python lora_finetune.py --stage all    # LoRA 微调全流程
python eval_qa_model.py                # 评测微调模型
python check_train_env.py              # 训练环境体检
```

### 前端（只在改前端时需要）

```bash
cd frontend
npm install
npm run dev        # 开发热更新 :5173
npm run build      # 构建
```

构建后需部署到后端：

```powershell
# 清空 static 后复制 dist
Remove-Item backend-main-fastapi\static\* -Recurse -Force
Copy-Item frontend\dist\* backend-main-fastapi\static\ -Recurse -Force
```

### 工具

```bash
python tools/make_bats.py              # 重新生成 .bat（无 BOM）
python tools/create_shortcuts.py --all # 重建桌面快捷方式
```

---

## 故障排查

### 页面打不开 / 502

```bash
python check_env.py      # 先看是不是依赖或前端产物缺失
```

### 端口被占

```bash
# 方式 1：用停止脚本
双击 停止.bat

# 方式 2：手动找进程
netstat -ano | findstr ":8000"
taskkill /PID <PID> /F
```

### 手机访问不了

1. 确认手机与电脑**同一 WiFi**（手机别开流量）
2. `.env` 里 `HOST=0.0.0.0`
3. 防火墙放行 8000（右键 `启动-局域网.bat` → 以管理员身份运行）
4. 部分路由器开了**AP 隔离**，需在路由器后台关闭

### 本地模型不生效

```bash
python setup_local_models.py     # 检查 Ollama 与已装模型
```

- Ollama 未运行 → 开始菜单打开 Ollama
- 没有模型 → `ollama pull qwen3:4b`
- 都没有 → 走云端 API（在「设置 → AI 服务」配 Key）

### 检索不到内容

```bash
python -m services.kb_pipeline   # 看分块/向量/索引状态
```

- 缺向量 → `--heal --embeddings`
- 分块为 0 → 检查文档是否解析成功

### 中文显示乱码（控制台）

PowerShell 显示问题，**文件本身是正确的 UTF-8**。执行一次：

```powershell
chcp 65001
```

### `.bat` 双击闪退

检查是否有 **UTF-8 BOM**（cmd 无法解析）：

```powershell
python tools/make_bats.py    # 重新生成，会自动校验 BOM
```

---

## 技术栈

| 层 | 技术 |
| :--- | :--- |
| 后端 | FastAPI · SQLAlchemy 2.0 · PostgreSQL 16.15（便携版，SQLite 降级路径保留） · APScheduler · uvicorn |
| 前端 | React 18 · Vite 5 · Zustand · React Router（HashRouter） |
| 检索 | PostgreSQL GIN（jieba BM25） · 向量 KNN / pgvector · RRF 融合 |
| 嵌入 | bge-small-zh-v1.5（fastembed 本地） |
| OCR | RapidOCR（PP-OCRv4 ONNX） · pypdfium2 渲染 |
| 本地模型 | Ollama（deepseek-r1 / qwen3 系列） |
| 微调 | Qwen2.5-3B + LoRA（peft / trl） |
| 网盘 | 百度网盘开放平台（OAuth + 自动续期） |

---

## 2026-10-23 深度体检与修复汇总

本次按「功能完整」路线对七大功能域做了一轮深度体检与修复（详见 `docx/56~58`）：

| 域 | 问题 | 处置 |
| :--- | :--- | :--- |
| 题库 | 科目选择后默认「真题」Tab 下 0 题（数电/模电/电路/自控题全在教材/自定义来源） | 前端 `Quiz.jsx` 当前来源 0 题自动回退「全部来源」+ toast 明示 |
| 题库 | 7 道无答案题、8 道占位选项题可被抽到 | 已下架（`is_available=false`），可回滚脚本 `quiz_fix_work/13_rollback.sql` |
| 题库 | 8 道多选答案异常（如 19331 CACA，实为多空填空） | 改为 `fill` 题型，可正常文本作答 |
| 知识地图 | 571 个知识点（电路/信号/通信/408 等科目）不在「全部」树中 | `taxonomy.py` 补 MAJOR/已登记科目，31 科 2735 点全部可达 |
| 知识地图 | 关联真题区块恒空（响应字段读错 `items`→`questions`） | `KnowledgeArticle.jsx` 已修复；无关联题显示友好空态 + 「去全部题」 |
| 知识地图 | `/knowledge/1` 深链 404 白屏 | 404 友好空态（「知识点不存在」+ 返回地图） |
| 词库 | `root/example` 恒为 null（数据在 `word_examples`/`word_roots` 独立表） | `words.py` 序列化层只读增强，list/get/due/review 均返回例句/词根 |
| 代码题库 | 「收录题目 0 道」与考点全景不一致（科目 JOIN 失配） | `codebank_service.list_subjects` 并入题目实际科目，收录 600 题 |
| 代码题库 | `/api/codebank/subjects` 500 IndexError | 已修复（SQL 补 `s.id`，`question_count=r[4]`） |
| 智能组卷 | 易错模式无匹配题时 404，导致「智能组卷」不可用 | `insight.py` 易错模式退化为随机抽题 |
| 测试 | 全量 pytest 基线 1 failed（PDF 导出裸用 `datetime.date.today()`） | 统一改为 `utils.timeutil.local_today()` |

数据变更均有备份表（`quiz_questions_bak_20261023`，11765 行）与可回滚 SQL；本次未动任何表结构。

### 第二轮继续修复（详见 `docx/60`）

| 域 | 问题 | 处置 |
| :--- | :--- | :--- |
| 词库 | 5512 词全挂 `user_id=1`，新用户按 B4 隔离看不到任何词 | `words.py` 懒加载克隆：新用户首访自动分配内置词库副本（SM-2 调度重置），实测 5492 词开箱即用 |
| AI 助手 | u2-flash 首 token 约 35s，前端无进展反馈 | 后端发 `status=thinking` 事件 + 思维链阈值 2000→120 主动输出；前端「模型思考中…」状态条 |
| 题库 | 「计算机基础」520 题实为计组，但 KB 无该科目知识点 | 归并到「计算机学科专业基础408」（520 题），知识地图/刷题中心打通 |
| 题库 | 政治 5141 题混入 1773 道公务员行测常识 | 独立科目「公务员行测常识」（内容保留，政治回归 3368 纯考研政治） |
| 院校库 | 首屏 5.6s（列表聚合慢） | `/kaoyan/schools` 与热度榜加 60s TTL 缓存，实测 288ms → 12ms |

第二轮数据变更备份：`bak_quiz_questions_jsj_20261023`（520 行）、`bak_quiz_questions_gwy_20261023`（1773 行）。
全量验证：后端 pytest **1427 passed / 0 failed**；前端 vitest **458 passed**；生产构建成功。

---

## 文档索引

权威文档在 **`docx/`**（2026-10-10 已清理过期稿并重写）：

| 文档 | 内容 |
| :--- | :--- |
| [docx/README.md](docx/README.md) | 文档中心索引 |
| [docx/01-项目总览与现状.md](docx/01-项目总览与现状.md) | 平台是什么、技术栈、真实数据、目录、模块地图 |
| [docx/02-启动与使用指南.md](docx/02-启动与使用指南.md) | 5 种启动、环境自检、本机/局域网/手机、排障、维护命令 |
| [docx/03-刷题与院校模块.md](docx/03-刷题与院校模块.md) | 刷题中心与院校库：功能、数据口径、接口契约 |
| [docx/04-后续开发路线图与本次变更.md](docx/04-后续开发路线图与本次变更.md) | 已知短板、后续待办、本次变更日志 |
| [docx/53-计划时间表手动修改改造报告.md](docx/53-计划时间表手动修改改造报告.md) | 计划表：艾宾浩斯自定义节奏 + 手动改时间（2026-10-23） |
| [docx/56-UI功能走查报告-20261023.md](docx/56-UI功能走查报告-20261023.md) | UI 功能走查（2026-10-23） |
| [docx/57-题库导入深检与修复报告.md](docx/57-题库导入深检与修复报告.md) | 题库导入深检与修复（2026-10-23） |
| [docx/58-知识库与知识地图修复报告.md](docx/58-知识库与知识地图修复报告.md) | 知识库与知识地图修复（2026-10-23） |
| [docx/59-完善工作汇总.md](docx/59-完善工作汇总.md) | 深度体检修复最终汇总（2026-10-23） |
| [docx/60-继续修复报告.md](docx/60-继续修复报告.md) | 第二轮修复：词库/AI 首 token/计算机基础/公务员行测/院校库缓存（2026-10-23） |
| [docx/61-规整归一与AI板块升级报告.md](docx/61-规整归一与AI板块升级报告.md) | 规整归一 + AI 板块升级：AI 讲题回流盲点池闭环（2026-10-23） |
| [docx/62-第一批试用者走查报告.md](docx/62-第一批试用者走查报告.md) | 第一批试用者走查：UI 严苛审查 + 逐题核验 + B4 隔离漏洞修复（2026-10-23） |
| [docx/63-并发协作与提交策略.md](docx/63-并发协作与提交策略.md) | 并发 agent 工作区协作：基线冻结 / 分支隔离 / 测试库隔离（2026-10-23） |
| [docx/64-遗留建议落实报告.md](docx/64-遗留建议落实报告.md) | 遗留建议落实：周会议题聚合 / 提交策略 / AI 测试确定性 / stuck 样式收编（2026-10-23） |
| [docx/65-题库词库逐源检测与修复报告.md](docx/65-题库词库逐源检测与修复报告.md) | 逐源审计全部导入文件：缺A/新题型选项/解析错位/OCR碎片修复 + 0854 教材全景填充（2026-10-23） |
| [docx/66-knowledge_base全量入库报告.md](docx/66-knowledge_base全量入库报告.md) | knowledge_base 全量入库：音视频清理 + 0854 收尾 + 剩余 2553 文件并行导入（2026-10-23） |
| [docx/67-全局检查与0854教材填充报告.md](docx/67-全局检查与0854教材填充报告.md) | 全局检查修复（知识地图挂接/向量100%/FTS生成列回填）+ 12 领域书本级教材全部入库（2026-10-24） |
| [docx/68-项目整合与全面体检修复报告.md](docx/68-项目整合与全面体检修复报告.md) | 项目整合体检：pytest 1434 + vitest 458 全过、服务恢复、知识点挂接回填、题库/词库去重（2026-10-24） |
| [docx/69-项目部署与公网发布报告.md](docx/69-项目部署与公网发布报告.md) | 部署公网 60.204.223.140：清理打包 + 全量数据库迁移（2666 文档/81348 向量）+ nginx/systemd 上线 + 公网全链路测试（2026-10-24） |

---

## 已知短板

诚实列出当前不足（详见 `docx/04-后续开发路线图与本次变更.md`）：

| 短板 | 现状 |
| :--- | :--- |
| 专业课（数电/模电）真题少 | 题库 11,765 题（开源 10,876 + 教材 386 + 真题 503）已全量可用；但数电/模电/电路专业课真题仍未导入（源文档已有 503 chunks 可抽取） |
| 年份覆盖不完整 | 英语/数学真题 503 题带年份（1998–2025）；数电/模电真题年份仍缺失 |
| 真题覆盖率低 | 386 题中仅 57 题标注真题来源，`is_past_exam` 尚未回填 |
| 院校热度/星级为派生代理 | 无真实报考人数/官方星级数据 |
| 前端 e2e 薄 | 后端 pytest 1,375 项 + 前端 vitest 404 项；Playwright 仅 3 个 smoke |
| 分数线表无上限 | 88,315 行且采集中持续增长，需要归档策略（见审计 P2） |

---

*本平台仅用于个人备考学习。使用时请遵守各资料来源的版权规定。*
