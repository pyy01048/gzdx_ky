# PAI-DSW 云端训练包（考研答疑模型 LoRA）

## 环境事实（2026-10-18 实测确认）

| 项 | 值 |
|---|---|
| GPU | NVIDIA A10，**24GB**（23028MiB），CUDA 12.4，驱动 550.163.01 |
| Python | `/usr/local/bin/python3`（**3.11**，root 身份，pip 直接装） |
| OSS 挂载 | `/mnt/data/` → `oss://oss-pai-087n0xbfgdz56tjfyu-cn-shanghai/考研资料数据集/` |
| 持久盘 | `/mnt/workspace`（cloudDisk，实例重启不丢；**/root 容器层会丢**） |
| 知识库数据 | 已上传至 OSS `考研资料数据集/`（即本地 knowledge_base，79GB 原始文件） |

> ⚠️ **OSS 挂载点读写走网络**：训练数据、checkpoint 一律落 `/mnt/workspace`，
> 只有"确定要长期保存/回传"的产物才 cp 到 `/mnt/data`。

## 整体方案（三段分工）

```
┌─ 本地机器（Windows）─────────────────────────────┐
│ ① 数据管线：OCR/智能入库/KP抽取（已有代码，走PostgreSQL真库+Ollama）│
│ ② QA数据集构建：scripts/build_qa_dataset.py → 276条（已随本包分发） │
│ ④ adapter下载 → merge（本地7B基座）→ ollama create → 评测上线      │
└──────────────────┬───────────────────────────────┘
                   │ 数据集打进git仓库 / adapter走OSS
┌─ 阿里云 PAI-DSW（A10 24GB）──────────────────────┐
│ ③ LoRA 训练：Qwen2.5-7B-Instruct + QLoRA 4bit（本目录代码）        │
│    后续可选：OCR文本抽取、KP批量抽取（GPU比本地8GB快一个量级）      │
└──────────────────────────────────────────────────┘
```

**为什么 adapter 回传而不是合并模型**：7B fp16 合并模型 ~15GB，adapter 只有 ~500MB。
Ollama 导入时会自己做 Q4 量化，本地只要有 7B 基座 + 16GB 内存就能合并。

## DSW 上三步跑完

```bash
# 0. 探测环境（第一次必跑，输出贴回来可判断要不要补依赖）
cd /mnt/workspace
git clone https://github.com/pyy01048/gzdx_ky.git
cd gzdx_ky/training/pai_dsw
bash probe_env.sh

# 1. 一键：备数据 → 训练 → 回传OSS（约 30-60 分钟，含首次下载 15GB 基座）
bash run_all.sh

# 2. 分步模式（排查问题时用）
SKIP_PROBE=1 bash run_all.sh                    # 只训练
bash prepare_data.sh && python3 train_dsw.py --data-dir /mnt/workspace/train_data --output-dir /mnt/workspace/lora_out
bash push_checkpoint.sh                         # 手动回传
```

## 训练配置（A10 24GB 默认值，环境变量可覆盖）

| 变量 | 默认 | 说明 |
|---|---|---|
| `BASE_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | 换 `Qwen/Qwen2.5-4B-Instruct` 更快（A10 上约快 40%） |
| `TRAIN_BATCH_SIZE` | 2（4bit）/ 1（bf16） | A10 24GB 有余量可试 4 |
| `TRAIN_GRAD_ACCUM` | 8 | 有效批量 = batch × accum |
| `TRAIN_MAX_LEN` | 1024 | 样本 p95=662，1024 覆盖绝大多数 |
| `TRAIN_EPOCHS` | 3 | 小数据集 + 早停，第 3 轮多半用不上 |
| `LORA_LR` | 1e-4 | 7B 上也可试 7e-5 |
| `LORA_R` / `LORA_ALPHA` | 16 / 32 | 与本地版一致 |
| `LORA_EARLY_STOP` | 3 | eval_loss 连续 3 次不降即停并回滚最优 |
| `OSS_OUT` | `/mnt/data/考研资料数据集/lora_out` | adapter 回传路径 |

`--no-4bit` 切 bf16 LoRA（约 19-21GB，贴 24GB 顶，仅显存确实富余时用）。

## 断点续跑（DSW 实例被回收/主动停止后）

```bash
# checkpoint 已在 OSS：先从 OSS 拉回 workspace（几百 MB）
mkdir -p /mnt/workspace/resume
cp -r /mnt/data/考研资料数据集/lora_out/checkpoints/checkpoint-* /mnt/workspace/resume/ 2>/dev/null || true
# 注意：自动回传只传 final/；训练中途的 checkpoint 需在训练侧另存，
# 或接受从头再训（276条数据集全程仅 ~10 分钟，重训成本可忽略）
python3 train_dsw.py --data-dir /mnt/workspace/train_data \
    --output-dir /mnt/workspace/lora_out \
    --resume /mnt/workspace/resume/checkpoint-320
```

## 本地侧收尾（Windows）

```bat
rem 1. 下载 OSS 上的 lora_out/final 到 data\lora_finetune_v2\checkpoints\final
rem    （PAI 控制台默认存储浏览下载，或本地 ossutil cp -r）
rem 2. 合并（pyy 环境，需 16GB+ 内存；7B 基座从 ModelScope 缓存指过来）
C:\Users\33884\.conda\envs\pyy\python.exe training\lora_finetune.py --stage merge ^
    --data-dir data\lora_finetune_v2 ^
    --base-model C:\Users\33884\.cache\modelscope\hub\models\Qwen--Qwen2.5-7B-Instruct\snapshots\master
rem 3. 导入 Ollama（新标签，不覆盖线上模型）
C:\Users\33884\.conda\envs\pyy\python.exe training\lora_finetune.py --stage ollama --data-dir data\lora_finetune_v2
ollama create kaoyan-assistant-v5 -f data\lora_finetune_v2\Modelfile
rem 4. 对照评测后再切换平台模型名
python scripts\eval_qa_model.py --models qwen2.5:1.5b,kaoyan-assistant,kaoyan-assistant-v5 --n 150
```

## 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `torch.cuda 不可用` | 镜像是 CPU 版 torch，按 probe 输出重装 cu124 版 |
| `No module named 'bitsandbytes'` | `pip install bitsandbytes`（QLoRA 必需） |
| 下载基座 15GB 慢/断 | ModelScope 内网 normally 快；断了重跑同一命令即断点续传 |
| 实例重启后要重下模型 | 模型缓存必须走 `/mnt/workspace/.cache/modelscope`（脚本已默认）；谁改回 /root 谁重下 |
| OOM（bf16 模式） | 换回默认 4bit，或 `BASE_MODEL=Qwen/Qwen2.5-4B-Instruct` |
| 上传 knowledge_base 后没数据可训 | knowledge_base 是**原始书籍**，训练用的是 QA 数据集（276 条，随 git 仓库分发）；知识库进训练管线见下方"长线" |

## 长线（knowledge_base → 训练数据，后续阶段）

OSS 上的 knowledge_base（79GB 原始文件）进模型要三段，每段独立可跑：

1. **文本抽取（DSW GPU 加速）**：扫描件 OCR（PaddleOCR/rapidocr）→ 每文档一个 .json 回传 OSS。
   本地已修好 OCR 管线（commit 9e29778），移植到 DSW 即可用 A10 加速。
2. **KP 抽取 + 知识图谱（本地）**：下载文本 → 既有 `smart_ingest.py` + `kp_extract.py`
   （Ollama qwen2.5-coder:7b）→ 知识点入 PostgreSQL 真库。
3. **QA 数据集扩充（本地）**：题库 + 新 KP → `build_qa_dataset.py` → 新 train/val
   上传 OSS → 回 DSW 训 v3。

> 大文件（>200MB 扫描件 78 个，红宝书 1655MB）OCR 超时方案待定：A 页数封顶 / C 动态超时结合。

## 远程串联模式（本电脑 AI Agent 直连 DSW）

不想手动复制粘贴时，让本电脑的 AI Agent 通过 SSH 直接操作 DSW——Agent 的
命令执行环境就是本电脑，缺的只是一条「本电脑 → DSW」网络路径 + 一把专用密钥。
**推荐 Tailscale（你已在用）**，不要把 22 端口裸暴露公网。

### 1. DSW 加入 Tailscale（VSCode 终端执行）

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up
tailscale ip -4        # 记下输出，如 100.x.x.x
```

容器缺 TUN 设备时报错则用用户态网络：

```bash
tailscaled --tun=userspace-networking & tailscale up
```

### 2. 本电脑生成专用密钥对（不要复用现有私钥）

```bash
ssh-keygen -t ed25519 -f ~/.ssh/dsw_key -N ""
```

### 3. 公钥装进 DSW（VSCode 终端执行，粘贴本机 `~/.ssh/dsw_key.pub` 的内容）

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "ssh-ed25519 AAAA...（你的公钥内容）" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### 4. 本电脑验证连通

```bash
ssh -i ~/.ssh/dsw_key -o StrictHostKeyChecking=no root@100.x.x.x nvidia-smi
```

### 5. 之后 Agent 可直接执行（输出回到 Agent 侧，无需人工中转）

```bash
ssh -i ~/.ssh/dsw_key root@100.x.x.x \
  "cd /mnt/workspace/gzdx_ky/backend-main-fastapi/training/pai_dsw && bash probe_env.sh"
```

### 安全边界

- 私钥只存本机 `~/.ssh/dsw_key`，Agent 只引用路径、不读取内容，不出现在对话里
- Tailscale 是加密内网；若改用 EIP，安全组只放行你家 IP，别开 0.0.0.0/0
- 备选方案说明：阿里云 MCP 生态只有 PAI 实例生命周期 API（创建/启停），
  **没有远程执行命令的 API**，所以 SSH 是唯一执行通道，配 MCP 替代不了

