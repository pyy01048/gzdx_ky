# bge-reranker-v2-m3 CPU 微服务部署报告

> 部署日期：2026-10-10  
> 部署位置：`D:\平台\backend-reranker\`  
> 状态：**✅ 成功运行中**（端口 8140，模型已加载）

---

## 1. 环境与依赖清单

| 项目 | 值 |
|---|---|
| 操作系统 | Windows（无 GPU） |
| 隔离方式 | venv（基于 pyy 环境 Python 3.12.13 创建，**不污染 pyy 主环境**） |
| venv 路径 | `D:\平台\backend-reranker\data\venv\` |
| Python 版本 | 3.12.13 |
| 核心包 | torch==2.14.1+cpu, FlagEmbedding==1.4.2, fastapi==0.143.0, uvicorn==0.54.0, transformers==5.19.0, sentence-transformers==6.1.0 |

### 关键依赖版本（pip freeze 摘要）

```
torch==2.14.1+cpu
FlagEmbedding==1.4.2
fastapi==0.143.0
uvicorn==0.54.0
transformers==5.19.0
sentence-transformers==6.1.0
huggingface-hub==1.33.0
accelerate==1.15.0
peft==0.21.2
numpy==2.5.3
```

---

## 2. 权重来源与大小

| 项目 | 值 |
|---|---|
| 模型仓库 | `BAAI/bge-reranker-v2-m3` |
| 下载源 | `https://hf-mirror.com`（HF 国内镜像） |
| 本地路径 | `D:\平台\backend-reranker\data\models\bge-reranker-v2-m3\` |
| 总大小 | **2.14 GB**（fp32 safetensors） |
| 主要文件 | `model.safetensors`（~2.1GB）、`config.json`、`tokenizer.json`、`tokenizer_config.json`、`sentencepiece.bpe.model`、`special_tokens_map.json` |
| 架构 | XLM-RoBERTa-large（560M 参数），cross-encoder reranker |

> 注：首次下载需设置 `HF_HUB_DISABLE_XET=1`，否则 hf-mirror 不支持 xet/CAS 协议会报 401。

---

## 3. 接口契约

### `POST /rerank`

**请求：**
```json
{
  "query": "三极管共射极放大电路的工作原理",
  "documents": [
    {"id": "doc1", "text": "..."},
    {"id": "doc2", "text": "..."}
  ]
}
```

**响应：**
```json
{
  "results": [
    {"id": "doc1", "score": 0.997},
    {"id": "doc6", "score": 0.963}
  ],
  "model": "bge-reranker-v2-m3",
  "took_ms": 1307.2
}
```

- score 已归一化到 `[0, 1]`，**降序排列**
- 模型不可用时返回原序 + score=0（调用方自动 LLM 兜底）

### `GET /health`
返回 `{"status": "ok"|"unavailable", "model": "...", "error": null}`

---

## 4. 8140 验证结果

### 健康检查
```
GET http://127.0.0.1:8140/health
→ {"status":"ok","model":"bge-reranker-v2-m3","error":null}
```

### 重排测试样本（电子技术中文 query）

**Query：** `三极管共射极放大电路的工作原理`

| 排名 | 文档 ID | 内容摘要 | Score | 判断 |
|---|---|---|---|---|
| 1 | doc1 | 共射极放大电路，基极输入/集电极输出/静态工作点 | **0.997** | ✅ 直接相关 |
| 2 | doc6 | 互补推挽功率放大电路，NPN/PNP 三极管对称工作 | **0.963** | ✅ 三极管相关 |
| 3 | doc4 | MOS 场效应管共源极放大电路 | **0.739** | ✅ 同类放大拓扑 |
| 4 | doc5 | 欧姆定律 I=U/R | **0.043** | ⚪ 基础电路定律，低分合理 |
| 5 | doc2 | 运算放大器虚短虚断 | **0.017** | ⚪ 不同器件，低分合理 |
| 6 | doc3 | TNT 三硝基甲苯炸药 | **0.00003** | ✅ "三"字误匹配正确排末位 |

**CPU 性能：**
- 模型加载：4.5 秒
- 6 条文档重排：1.3 秒（CPU 推理）

---

## 5. 服务启动方式

### 方式一：双击启动
```
D:\平台\backend-reranker\启动.bat
```

### 方式二：命令行
```powershell
cd D:\平台\backend-reranker
$env:HF_ENDPOINT="https://hf-mirror.com"
$env:HF_HUB_DISABLE_XET="1"
.\data\venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8140
```

### 停止服务
```
D:\平台\backend-reranker\停止.bat
```

---

## 6. 部署过程记录（逐级降级路径）

| 步骤 | 结果 | 说明 |
|---|---|---|
| conda create -n reranker | ❌ 失败 | repo.anaconda.com 连接超时（网络受限） |
| **降级：venv from pyy Python 3.12** | ✅ 成功 | venv 与 pyy 完全隔离，不污染主环境 |
| torch CPU 安装 | ✅ 成功 | torch 2.14.1+cpu，从 download.pytorch.org/whl/cpu |
| FlagEmbedding + fastapi | ✅ 成功 | 清华镜像安装 |
| 模型下载（首次 xet） | ❌ 401 | hf-mirror 不支持 xet/CAS 协议 |
| **降级：HF_HUB_DISABLE_XET=1** | ✅ 成功 | 普通 HTTP 下载，2.14GB 完成 |
| 模型加载 | ✅ 成功 | 4.5 秒加载完毕 |
| /rerank 测试 | ✅ 成功 | 6 条中文样本分数排序合理 |

---

## 7. 文件清单

```
D:\平台\backend-reranker\
├── app.py                  # FastAPI 服务源码
├── download_model.py       # 模型下载脚本
├── requirements.txt         # Python 依赖清单
├── 启动.bat                 # 一键启动
├── 停止.bat                # 一键停止
├── README.md               # 本报告
└── data/                   # （已加入 .gitignore，不入库）
    ├── venv/               # Python 虚拟环境
    └── models/
        └── bge-reranker-v2-m3/   # 模型权重 2.14GB
```

---

## 8. 遗留项与注意事项

1. **CPU 推理速度**：6 条文档约 1.3 秒，若检索管线候选集 >50 条建议设 top_k 截断后再 rerank。
2. **内存占用**：模型加载后约占用 ~2.5GB 内存（fp32），确保系统可用内存充足。
3. **开机自启**：当前需手动启动，如需开机自启可后续注册为 Windows 服务或加入启动脚本。
4. **与主后端解耦**：服务独立运行在 8140 端口，主后端 `backend-main-fastapi` 通过 HTTP 调用即可；若本服务未启动，调用方应捕获连接错误并回退到 LLM rerank。
5. **权重不可入库**：`data/` 已加入 `.gitignore`，模型权重和 venv 均不会进入 git 仓库。
