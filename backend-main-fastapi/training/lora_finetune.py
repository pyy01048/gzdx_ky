# -*- coding: utf-8 -*-
"""本地模型 LoRA 微调脚本。

使用本地 Qwen2.5-3B-Instruct 进行 LoRA/QLoRA 微调，
打造专有考研答疑模型。

依赖：
    pip install torch transformers peft datasets accelerate trl

使用方法：
    # 1. 准备数据（从数据库导出 SFT 样本）
    python lora_finetune.py --stage prepare

    # 2. 开始微调（需要 GPU，预计 2-4 小时）
    python lora_finetune.py --stage train

    # 3. 合并模型并导出
    python lora_finetune.py --stage merge

    # 4. 导入 Ollama
    python lora_finetune.py --stage ollama
"""

import sys
import os
import json
import argparse
import datetime

# Windows 控制台默认 GBK，打印 ✓/中文进度会直接 UnicodeEncodeError 让训练白跑一轮
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 数据目录
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lora_finetune")
os.makedirs(DATA_DIR, exist_ok=True)

# 模型配置
# 基座可用 LORA_MODEL_NAME 覆盖为本地已缓存路径（离线机没有 HF 网络）：
#   LORA_MODEL_NAME=C:\Users\33884\.cache\modelscope\hub\models\Qwen--Qwen2.5-3B-Instruct\snapshots\master
MODEL_NAME = os.environ.get("LORA_MODEL_NAME", "Qwen/Qwen2.5-4B-Instruct")  # 或本地路径
OUTPUT_DIR = os.path.join(DATA_DIR, "checkpoints")
MERGED_DIR = os.path.join(DATA_DIR, "merged")
MAX_LENGTH = 2048
BATCH_SIZE = 2
GRADIENT_ACCUMULATION = 8
LEARNING_RATE = float(os.environ.get('LORA_LR', '1e-4'))
NUM_EPOCHS = int(os.environ.get('LORA_EPOCHS', '3'))
LORA_R = int(os.environ.get("LORA_R", "16"))
LORA_ALPHA = int(os.environ.get("LORA_ALPHA", "32"))
LORA_DROPOUT = 0.05

#: 与 API 共用的训练状态文件；命令行启动的训练也能被页面看到
STATE_FILE = os.path.join(DATA_DIR, "training_state.json")


def _update_state(**updates):
    """原子更新训练状态文件（保留 API 写入的 log_path/config 等字段）。"""
    current = {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            current = json.load(f)
    except (OSError, ValueError):
        pass
    current.update(updates)
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

#: Qwen2.5 的 ChatML 特殊标记，Modelfile 模板必须还原角色，否则指令模型认不出用户轮次
#: 必须写成完整 token（含闭合 ">"）：裸前缀会让 Ollama 的 stop 串查表落空。
CHATML_START = "<|im_start|>"
CHATML_END = "<|im_end|>"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def prepare_data():
    """从数据库导出 SFT 样本为训练格式。"""
    print("=" * 60)
    print("阶段1：准备训练数据")
    print("=" * 60)

    from database import SessionLocal
    from models import SFTExample

    db = SessionLocal()
    examples = db.query(SFTExample).all()
    print(f"从数据库读取 SFT 样本: {len(examples)} 条")

    if not examples:
        print("警告：数据库中没有 SFT 样本，将创建示例数据")
        examples = create_demo_examples()

    # 转换为训练格式
    train_data = []
    for ex in examples:
        # 构建对话格式
        messages = []
        if ex.system:
            messages.append({"role": "system", "content": ex.system})
        # 字段名必须跟 models.SFTExample 对齐：ORM 里是 user_input（不是 user）。
        # 写错时 demo 分支与数据库分支都会 AttributeError，--stage prepare 直接崩。
        messages.append({"role": "user", "content": ex.user_input or ""})
        messages.append({"role": "assistant", "content": ex.assistant or ""})

        train_data.append({
            "messages": messages,
            "subject": ex.subject or "general",
            "source": "database",
        })

    # 划分训练集和验证集（9:1）
    import random
    random.shuffle(train_data)
    split_idx = int(len(train_data) * 0.9)
    train_set = train_data[:split_idx]
    val_set = train_data[split_idx:]

    # 保存为 JSONL
    train_path = os.path.join(DATA_DIR, "train.jsonl")
    val_path = os.path.join(DATA_DIR, "val.jsonl")

    with open(train_path, "w", encoding="utf-8") as f:
        for item in train_set:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open(val_path, "w", encoding="utf-8") as f:
        for item in val_set:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"训练集: {len(train_set)} 条 -> {train_path}")
    print(f"验证集: {len(val_set)} 条 -> {val_path}")

    # 统计学科分布
    from collections import Counter
    subjects = Counter(item["subject"] for item in train_data)
    print("\n学科分布:")
    for subj, count in subjects.most_common():
        print(f"  {subj}: {count} 条")

    db.close()
    print("\n✓ 数据准备完成！")
    return train_path, val_path


def create_demo_examples():
    """创建示例 SFT 数据（用于测试）。"""
    examples = []
    demo_data = [
        ("数字电子技术", "什么是与门？", "与门是一种基本逻辑门，当所有输入都为高电平时，输出才为高电平。逻辑表达式：Y = A · B"),
        ("数字电子技术", "什么是触发器？", "触发器是具有记忆功能的基本存储单元，可存储1位二进制信息。常见类型有SR触发器、JK触发器、D触发器、T触发器。"),
        ("英语", "abandon是什么意思？", "abandon /əˈbændən/ v. 放弃，抛弃；遗弃 n. 狂热，放任。例句：He abandoned his car in the snow."),
        ("英语", "如何写考研英语作文开头？", "考研英语作文开头常用方法：1. 描述现象：Nowadays, ... has become a common phenomenon. 2. 引用名言：As a saying goes, ... 3. 提出问题：Should we ...? 4. 数据引入：According to a recent survey, ..."),
        ("数学", "什么是极限？", "极限是微积分的基本概念，描述函数在某点附近的变化趋势。定义：对于任意ε>0，存在δ>0，当0<|x-x₀|<δ时，|f(x)-A|<ε，则称A为f(x)在x₀处的极限。"),
        ("政治", "什么是矛盾的普遍性？", "矛盾的普遍性是指矛盾存在于一切事物的发展过程中，即事事有矛盾；每一事物的发展过程中存在着自始至终的矛盾运动，即时时有矛盾。"),
    ]

    for subject, instruction, output in demo_data:
        # 字段名对齐 models.SFTExample（system / user_input / assistant），
        # 否则 prepare_data() 读 ex.user_input 会 AttributeError。
        ex = type('obj', (object,), {
            'system': f'你是一个考研{subject}辅导老师，请用简洁明了的语言回答问题。',
            'user_input': instruction,
            'assistant': output,
            'subject': subject,
            'source': 'demo',
        })()
        examples.append(ex)

    return examples


def _make_early_stop():
    """构造 EarlyStoppingCallback（惰性导入，避免未装 trl 时脚本无法启动）。

    为什么需要（2026-10-14 实测）：v3b 训练在第 2 轮 eval_loss 最低（0.7946），
    第 3 轮反弹到 0.8986 —— 已过拟合。按 epoch 评估时无法中途叫停，
    白跑一整轮（约 40 分钟）。改为按步评估 + 早停后，拐点出现即停并回滚最优权重。
    """
    try:
        from transformers import EarlyStoppingCallback
        return EarlyStoppingCallback(early_stopping_patience=_env_int("LORA_EARLY_STOP", 3))
    except Exception:  # noqa: BLE001
        return None


def train_lora(data_dir: str = None, output_dir: str = None,
               resume_from: str = None):
    """执行 LoRA 微调。

    :param resume_from: 从指定 checkpoint 目录恢复训练（如 checkpoints/checkpoint-448）。
        用于中断续跑：Trainer 会恢复优化器状态、学习率调度与早停计数，
        已跑的步数不白费（2026-10-14 实测：58% 处被守卫中断后靠它续跑）。

    :param data_dir: 训练数据目录（默认 DATA_DIR）。
        用 `scripts/build_qa_dataset.py` 重建的干净数据集时传
        `data/lora_finetune_v2` —— **强烈建议用新数据集**：
        旧的 train.jsonl 里 91.6% 的样本答案是题干的切片，
        训练出来只会复读输入（评测照抄率 0.72）。
    :param output_dir: 检查点输出目录（默认 OUTPUT_DIR）
    """
    print("=" * 60)
    print("阶段2：LoRA 微调训练")
    print("=" * 60)

    data_dir = data_dir or DATA_DIR
    out_dir = output_dir or (
        os.path.join(data_dir, "checkpoints") if data_dir != DATA_DIR else OUTPUT_DIR
    )

    _update_state(
        pid=os.getpid(),
        status="training",
        started_at=_now(),
        finished_at=None,
        data_dir=os.path.abspath(data_dir),
        output_dir=os.path.abspath(out_dir),
        log_path=os.environ.get("TRAIN_LOG_PATH") or os.path.join(data_dir, "train.log"),
        base_model=MODEL_NAME,
        message="训练中",
        config={
            "num_epochs": int(os.environ.get("TRAIN_EPOCHS", NUM_EPOCHS)),
            "batch_size": int(os.environ.get("TRAIN_BATCH_SIZE", BATCH_SIZE)),
            "learning_rate": LEARNING_RATE,
            "lora_r": LORA_R,
            "lora_alpha": LORA_ALPHA,
        },
    )

    try:
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            TrainingArguments,
            Trainer,
            DataCollatorForSeq2Seq,
            BitsAndBytesConfig,
        )
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from datasets import load_dataset
    except ImportError as e:
        print(f"✗ 缺少依赖库: {e}")
        print("请先安装：pip install torch transformers peft datasets accelerate trl bitsandbytes")
        _update_state(status="error", finished_at=_now(), message=f"缺少依赖库: {e}")
        return

    # 检查 GPU
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"使用设备: {device}")
    gpu_memory = 0.0
    if device == "cuda":
        gpu_name = torch.cuda.get_device_name(0)
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"GPU: {gpu_name} ({gpu_memory:.1f} GB)")
    else:
        print("警告：未检测到 GPU，训练将非常缓慢，建议使用 GPU")
        print("      提示：当前 torch 可能是 CPU 版（torch.__version__ 带 +cpu），")
        print("            需装 CUDA 版：pip install torch --index-url "
              "https://download.pytorch.org/whl/cu124")

    # QLoRA 4bit量化配置（8GB显存必备）
    use_qlora = device == "cuda" and gpu_memory < 12
    if use_qlora:
        print("\n启用 QLoRA 4bit量化（适配8GB显存）")
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
    else:
        bnb_config = None

    # 加载数据
    train_path = os.path.join(data_dir, "train.jsonl")
    val_path = os.path.join(data_dir, "val.jsonl")

    if not os.path.exists(train_path):
        print(f"训练数据不存在: {train_path}")
        if data_dir == DATA_DIR:
            print("先运行 --stage prepare，或用 scripts/build_qa_dataset.py 生成干净数据集")
            prepare_data()
        else:
            _update_state(status="error", finished_at=_now(), message=f"训练数据不存在: {train_path}")
            return

    dataset = load_dataset("json", data_files={
        "train": train_path,
        "validation": val_path,
    })
    print(f"训练集: {len(dataset['train'])} 条")
    print(f"验证集: {len(dataset['validation'])} 条")

    # 加载模型和分词器
    print(f"\n加载模型: {MODEL_NAME}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 梯度检查点开关在这里就要定下来：它同时决定 kbit 预处理是否启用 checkpointing。
    use_gc = _env_int("TRAIN_GRAD_CKPT", 1) == 1

    model_kwargs = {
        "trust_remote_code": True,
        # transformers 5.x 把 torch_dtype 改名为 dtype（旧名仍可用但会打弃用警告）
        "dtype": torch.bfloat16 if device == "cuda" else torch.float32,
    }
    if use_qlora:
        model_kwargs["quantization_config"] = bnb_config
        # 整块放 GPU0：device_map="auto" 在 8GB 卡上会把部分层溢出到 CPU/磁盘，
        # 每步来回搬运，实测慢一个数量级。
        model_kwargs["device_map"] = {"": 0}
    elif device == "cuda":
        model_kwargs["device_map"] = "auto"

    model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, **model_kwargs)

    if use_qlora:
        # 必须显式传 use_reentrant=False：peft 默认用 use_reentrant=True，
        # 与下面 TrainingArguments 的 use_reentrant=False 两套开关叠加，
        # 会在 kbit 模型上把输入梯度算丢（表现为 loss 不降 / 显存反复重算）。
        model = prepare_model_for_kbit_training(
            model,
            use_gradient_checkpointing=use_gc,
            gradient_checkpointing_kwargs={"use_reentrant": False} if use_gc else None,
        )

    # 配置 LoRA
    lora_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # 根据显存调整训练参数（必须在数据预处理之前定义max_len）
    # 全部可经环境变量覆盖，方便在小显存机器上实测挑配置而不用改代码：
    #   TRAIN_BATCH_SIZE / TRAIN_GRAD_ACCUM / TRAIN_MAX_LEN / TRAIN_EPOCHS
    #   TRAIN_GRAD_CKPT=0 关梯度检查点，TRAIN_MAX_STEPS=N 只跑 N 步做基准
    train_batch_size = _env_int("TRAIN_BATCH_SIZE", 1 if use_qlora else BATCH_SIZE)
    grad_accum = _env_int("TRAIN_GRAD_ACCUM", 8 if use_qlora else GRADIENT_ACCUMULATION)
    eval_batch_size = _env_int("TRAIN_EVAL_BS", train_batch_size)
    epochs = _env_int("TRAIN_EPOCHS", NUM_EPOCHS)
    if use_qlora:
        # Windows 桌面合成器（explorer/webview/NVIDIA overlay 共 17 个进程）常驻
        # 占掉 ~3.6GB，训练实际只有 ~4.3GB 可用；1024 会溢出到共享显存，
        # 实测单步 11~13 分钟（慢 80 倍）。样本 token 长度 p90=479，
        # 所以 640 既放得下又留得住余量，超出部分截断（无学习目标的样本会被剔除）。
        max_len = _env_int("TRAIN_MAX_LEN", 640)
        # 开梯度检查必须关 KV cache，否则每步白算一遍 past_key_values
        model.config.use_cache = False
        print(f"\nQLoRA模式: batch_size={train_batch_size}, grad_accum={grad_accum}, "
              f"max_len={max_len}, grad_ckpt={use_gc}, epochs={epochs}")
    else:
        max_len = _env_int("TRAIN_MAX_LEN", MAX_LENGTH)
        model.config.use_cache = True
        print(f"\n训练模式: batch_size={train_batch_size}, grad_accum={grad_accum}, "
              f"max_len={max_len}, epochs={epochs}")

    # 数据预处理
    def preprocess_function(examples):
        texts = []
        prompt_lens = []
        for messages in examples["messages"]:
            full = tokenizer.apply_chat_template(messages, tokenize=False,
                                                 add_generation_prompt=False)
            # 只有 assistant 轮参与 loss：旧写法把题干/prompt 也当学习目标，
            # 模型学到的是"复述问题"，这正是上一版 LoRA 照抄率 0.72 的直接来源。
            head = tokenizer.apply_chat_template(messages[:-1], tokenize=False,
                                                 add_generation_prompt=True)
            texts.append(full)
            prompt_lens.append(len(tokenizer(head, add_special_tokens=False)["input_ids"]))

        # 不做静态 padding：实测样本 token 长度中位 215 / p95 662，
        # 全部补齐到 1024 会把 4 倍算力花在 pad 上。交给 collator 动态补齐，
        # labels 的 pad 位由 DataCollatorForSeq2Seq 统一填 -100（不进 loss）。
        tokenized = tokenizer(texts, truncation=True, max_length=max_len)
        labels = []
        for ids, plen in zip(tokenized["input_ids"], prompt_lens):
            labels.append([-100 if i < plen else tid for i, tid in enumerate(ids)])
        tokenized["labels"] = labels
        return tokenized

    tokenized_datasets = dataset.map(
        preprocess_function,
        batched=True,
        remove_columns=dataset["train"].column_names,
    )

    # 兜底：prompt 过长被截断后，assistant 区间可能整段被切没 → 该样本 labels 全 -100，
    # 交叉熵没有有效目标会返回 NaN 并把整个训练毁掉。这类样本必须丢掉并计数。
    def _has_target(example):
        return any(l != -100 for l in example["labels"])

    dropped = {}
    for split in ("train", "validation"):
        before = len(tokenized_datasets[split])
        tokenized_datasets[split] = tokenized_datasets[split].filter(_has_target)
        dropped[split] = before - len(tokenized_datasets[split])
    print(f"  截断后无学习目标样本已剔除: train {dropped['train']} 条, "
          f"val {dropped['validation']} 条")

    # 训练参数
    # 计算warmup_steps（transformers 5.x移除了warmup_ratio）
    n_train = len(tokenized_datasets["train"])
    total_steps = max(1, (n_train // (train_batch_size * grad_accum)) * epochs)
    warmup_steps = int(total_steps * 0.03)
    print(f"\n训练配置: 总步数={total_steps}, warmup_steps={warmup_steps}, "
          f"有效批量={train_batch_size * grad_accum}")

    max_steps = _env_int("TRAIN_MAX_STEPS", -1)
    # 每轮评估 4 次（至少 20 步一次），保证能捕捉到 eval_loss 的拐点
    eval_steps = max(20, total_steps // max(1, epochs * 4)) if epochs else 50

    training_args = TrainingArguments(
        output_dir=out_dir,
        num_train_epochs=epochs,
        max_steps=max_steps,
        per_device_train_batch_size=train_batch_size,
        per_device_eval_batch_size=eval_batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=LEARNING_RATE,
        weight_decay=0.01,
        warmup_steps=warmup_steps,
        lr_scheduler_type="cosine",
        logging_steps=10,
        # 评估/保存策略（2026-10-14 改进）：
        # 原实现按 epoch 评估，v3b 因此直到第 3 轮才发现 eval_loss 反弹
        # （0.7946 → 0.8986），已过拟合且白跑一轮。改为按步评估 + 早停，
        # 一旦验证损失连续 2 次不降就停，并回滚到最优 checkpoint。
        save_strategy="steps" if max_steps <= 0 else "no",
        eval_strategy="steps" if max_steps <= 0 else "no",
        save_steps=eval_steps if max_steps <= 0 else 500,
        eval_steps=eval_steps if max_steps <= 0 else 500,
        load_best_model_at_end=max_steps <= 0,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to="none",
        bf16=device == "cuda",
        fp16=False,
        gradient_checkpointing=use_gc,
        gradient_checkpointing_kwargs={"use_reentrant": False} if use_gc else None,
        # paged_adamw_8bit 依赖 CUDA UVM，在 Windows WDDM 上会把优化器状态来回搬进
        # 共享显存 —— 实测单步 11~13 分钟。可训练参数只有 3000 万，普通 AdamW 常驻
        # 显存约 240MB，直接用它。
        optim="adamw_torch",
        dataloader_num_workers=0,
        # checkpoint 保留数（2026-10-14 教训：原来写死 2，训练中自动删旧 checkpoint
        # 时触发 bulk-delete 安全守卫，直接把训练进程杀掉（实测 58% 处中断）。
        # 改为环境变量可配，默认 8 —— LoRA checkpoint 每个 ~250MB，8 个约 2GB，可接受。
        save_total_limit=_env_int("LORA_SAVE_LIMIT", 8),
    )

    # 训练器
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_datasets["train"],
        eval_dataset=tokenized_datasets["validation"],
        # 不能用 DataCollatorForLanguageModeling：它会拿 input_ids 覆盖我们算好的
        # prompt-mask labels。Seq2Seq 版才按 -100 填充 labels。
        data_collator=DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model,
                                             padding="longest", max_length=max_len),
        # 早停：验证损失连续 N 次不改善即停，避免像 v3b 那样跑到过拟合
        callbacks=([c for c in [_make_early_stop()] if c] if max_steps <= 0 else []),
    )

    # 开始训练
    print("\n开始训练...", flush=True)
    t0 = datetime.datetime.now()
    # resume：从 checkpoint 恢复（优化器状态/学习率调度/早停计数一并恢复）
    result = trainer.train(resume_from_checkpoint=resume_from) if resume_from \
        else trainer.train()
    if device == "cuda":
        peak = torch.cuda.max_memory_allocated() / 1024**3
        reserved = torch.cuda.max_memory_reserved() / 1024**3
        steps = int(result.global_step) or 1
        secs = (datetime.datetime.now() - t0).total_seconds()
        print(f"[基准] 步数={steps} 用时={secs:.0f}s 单步={secs / steps:.1f}s/it "
              f"峰值allocated={peak:.2f}GB reserved={reserved:.2f}GB "
              f"每千步={secs / steps * 1000 / 3600:.2f}h", flush=True)

    if max_steps > 0:
        print("[基准模式] 不保存权重", flush=True)
        _update_state(status="completed", finished_at=_now(), message="基准模式完成（未保存权重）")
        return None

    # 保存模型
    final_output = os.path.join(out_dir, "final")
    trainer.save_model(final_output)
    tokenizer.save_pretrained(final_output)
    print(f"\n✓ 训练完成！模型保存到: {final_output}")
    _update_state(status="completed", finished_at=_now(), message="训练完成")

    return final_output


def _warn_if_low_ram(need_gb: float = 8.0) -> None:
    """合并前提示内存是否够。

    合并阶段要把整个 3B 基座以 fp16 常驻 CPU 内存（约 6.2GB），再叠加 LoRA 反量化
    与写盘缓冲。可用内存不足时不会报 OOM，而是静默掉进页面文件 —— 实测能把
    两分钟的合并拖到十几分钟，甚至被系统直接杀掉，所以提前喊一声。
    """
    try:
        import psutil
    except ImportError:
        return
    avail = psutil.virtual_memory().available / 1024**3
    print(f"可用内存: {avail:.1f} GB")
    if avail < need_gb:
        print(f"⚠ 合并约需 {need_gb:.0f}GB 空闲内存（3B fp16 基座 ~6.2GB + 合并/写盘缓冲），"
              f"当前仅 {avail:.1f}GB。建议先关掉占内存的程序再跑 --stage merge。")


def merge_model(data_dir: str = None, output_dir: str = None):
    """合并 LoRA 权重并导出完整模型。

    路径跟着训练目录走：用 data/lora_finetune_v2 训练出的适配器，
    就必须合并 v2 自己的 final/，否则会静默合并上一版脏权重。
    """
    print("=" * 60)
    print("阶段3：合并模型并导出")
    print("=" * 60)

    lora_dir = output_dir or (
        os.path.join(data_dir, "checkpoints") if data_dir else OUTPUT_DIR
    )
    merged_dir = os.path.join(os.path.dirname(os.path.abspath(lora_dir)), "merged")

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
    except ImportError as e:
        print(f"✗ 缺少依赖库: {e}")
        return

    lora_path = os.path.join(lora_dir, "final")
    if not os.path.exists(lora_path):
        print(f"LoRA 模型不存在: {lora_path}")
        print("请先运行 --stage train")
        return

    _warn_if_low_ram()

    print(f"加载基础模型: {MODEL_NAME}")
    base_model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        # transformers 5.x：torch_dtype 已改名 dtype
        dtype=torch.float16,
        device_map="cpu",
        # 边加载边落位，避免先建满精度中间副本再转 fp16 的翻倍内存峰值
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)

    print(f"加载 LoRA 权重: {lora_path}")
    model = PeftModel.from_pretrained(base_model, lora_path)

    print("合并权重...")
    merged_model = model.merge_and_unload()

    os.makedirs(merged_dir, exist_ok=True)
    merged_model.save_pretrained(merged_dir, safe_serialization=True)
    tokenizer.save_pretrained(merged_dir)
    _write_ollama_compat_config(merged_dir)

    print(f"\n✓ 模型合并完成！保存到: {merged_dir}")
    return merged_dir


def _write_ollama_compat_config(merged_dir: str) -> None:
    """补齐 Ollama 导入所需的顶层 config 键。

    transformers 5.x 把 rope_theta 移进 rope_parameters、把 torch_dtype 改名 dtype，
    而 Ollama 0.14.2 的 safetensors 导入器只读顶层键：读不到就写
    qwen2.rope.freq_base = 0.0，模型加载后 RoPE 直接出 NaN
    （现象：/api/chat 500 + "model runner has unexpectedly stopped"，
    llama-sampling.cpp 断言 found，评测全 0）。
    """
    cfg_path = os.path.join(merged_dir, "config.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"⚠ 无法读取 {cfg_path}，跳过 Ollama 兼容键补齐: {e}")
        return

    changed = []
    if cfg.get("rope_theta") is None:
        theta = (cfg.get("rope_parameters") or {}).get("rope_theta") or \
                (cfg.get("rope_scaling") or {}).get("rope_theta")
        if theta is not None:
            cfg["rope_theta"] = theta
            changed.append(f"rope_theta={theta}")
    if cfg.get("torch_dtype") is None and cfg.get("dtype"):
        cfg["torch_dtype"] = cfg["dtype"]
        changed.append(f"torch_dtype={cfg['dtype']}")

    if not changed:
        print("Ollama 兼容键已齐备，config.json 未改动")
        return
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"✓ config.json 补齐 Ollama 兼容键: {', '.join(changed)}")


def create_ollama_modelfile(data_dir: str = None, output_dir: str = None,
                            tag: str = "kaoyan-assistant-v5"):
    """创建 Modelfile（默认新标签，不覆盖线上 kaoyan-assistant，便于新旧对照）。"""
    print("=" * 60)
    print("阶段4：生成 Ollama Modelfile")
    print("=" * 60)

    lora_dir = output_dir or (
        os.path.join(data_dir, "checkpoints") if data_dir else OUTPUT_DIR
    )
    merged_path = os.path.join(os.path.dirname(os.path.abspath(lora_dir)), "merged")
    if not os.path.exists(merged_path):
        print(f"合并模型不存在: {merged_path}")
        print("请先运行 --stage merge")
        return

    # 旧模板只渲染 System+Prompt，把 ChatML 角色标记整段丢掉，指令模型认不出用户轮次。
    # 这里按 Qwen2.5 原生 ChatML 复原，stop 词也补齐。
    template_str = (
        "{{ if .System }}" + CHATML_START + "system\n{{ .System }}" + CHATML_END + "\n{{ end }}"
        "{{ if .Prompt }}" + CHATML_START + "user\n{{ .Prompt }}" + CHATML_END + "\n{{ end }}"
        + CHATML_START + "assistant\n"
    )
    system_str = (
        "你是一位考研辅导老师，负责计算机与电子信息类（834 电子技术基础：数字电子、"
        "模拟电子）以及数学二、英语二、政治的答疑。答疑风格：① 先判断学生卡在概念还是计算——"
        "概念不清时先抛一个引导性问题帮他定位盲点（苏格拉底式引导）再讲解，计算类直接给结论与步骤；"
        "② 结构：先给结论，再讲原理，必要时给出解题步骤，只讲与问题相关的内容，不复述题目原文；"
        "③ 对定义、公式、考点等记忆型内容，提示用间隔重复（当天、1天、3天、7天后回顾，对应 SM-2 记忆曲线）巩固；"
        "④ 不确定时明确说明并给出最稳妥的复习建议，不编造。"
    )

    modelfile_content = (
        f"FROM {merged_path}\n\n"
        f'TEMPLATE """{template_str}"""\n\n'
        "PARAMETER temperature 0.7\n"
        "PARAMETER top_p 0.9\n"
        "PARAMETER top_k 40\n"
        "PARAMETER num_ctx 4096\n"
        "PARAMETER num_predict 2048\n\n"
        # 自定义 TEMPLATE 不会自动带 stop 词，缺了它模型会一路生成到
        # num_predict 上限（把下一轮 user 内容也编出来）。
        f"PARAMETER stop \"{CHATML_END}\"\n"
        f"PARAMETER stop \"{CHATML_START}\"\n\n"
        f'SYSTEM \"\"\"{system_str}\"\"\"\n'
    )

    modelfile_path = os.path.join(os.path.dirname(os.path.abspath(merged_path)), "Modelfile")
    with open(modelfile_path, "w", encoding="utf-8") as f:
        f.write(modelfile_content)

    print(f"Modelfile 已创建: {modelfile_path}")
    print("\n执行以下命令导入 Ollama:")
    print(f"  ollama create {tag} -f {modelfile_path}")
    print("\n对照评测（新旧模型都在时）:")
    print(f"  python scripts/eval_qa_model.py --models qwen2.5:1.5b,kaoyan-assistant,{tag} --n 150")
    print(f"\n确认新模型更准后，再在平台设置里把本地模型名改成: {tag}")

    return modelfile_path


def main():
    parser = argparse.ArgumentParser(description="本地模型 LoRA 微调")
    parser.add_argument(
        "--stage",
        choices=["prepare", "train", "merge", "ollama", "all"],
        default="prepare",
        help="执行阶段：prepare(准备数据) / train(训练) / merge(合并) / ollama(导入Ollama) / all(全部)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="训练数据目录（默认 data/lora_finetune）。"
             "推荐用重建后的干净数据集：data/lora_finetune_v2",
    )
    parser.add_argument(
        "--base-model",
        default=None,
        help="基座模型路径或 HF 名（覆盖 LORA_MODEL_NAME 环境变量与默认值）。"
             "离线机建议传本地已缓存的 Qwen2.5-3B-Instruct 快照路径。",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="检查点输出目录（默认 <data-dir>/checkpoints）",
    )
    parser.add_argument(
        "--resume",
        default=None,
        help="从指定 checkpoint 目录恢复训练（如 data/xxx/checkpoints/checkpoint-448）",
    )
    parser.add_argument(
        "--tag",
        default="kaoyan-assistant-v5",
        help="导入 Ollama 的模型标签（默认新标签，不覆盖在用的 kaoyan-assistant）",
    )
    args = parser.parse_args()

    # --base-model 显式覆盖基座模型（优先于 LORA_MODEL_NAME 环境变量与默认值），
    # 这样离线机可直接传本地快照路径，而不会去 HF 拉取默认模型。
    global MODEL_NAME
    if args.base_model:
        MODEL_NAME = args.base_model

    print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"执行阶段: {args.stage}")
    if args.data_dir:
        print(f"数据目录: {args.data_dir}")
    print()

    if args.stage == "prepare" or args.stage == "all":
        prepare_data()

    if args.stage == "train" or args.stage == "all":
        try:
            train_lora(data_dir=args.data_dir, output_dir=args.output_dir,
                       resume_from=args.resume)
        except Exception as exc:  # noqa: BLE001 - 状态文件必须记录失败原因
            _update_state(status="error", finished_at=_now(),
                          message=f"{type(exc).__name__}: {exc}")
            raise

    if args.stage == "merge" or args.stage == "all":
        merge_model(data_dir=args.data_dir, output_dir=args.output_dir)

    if args.stage == "ollama" or args.stage == "all":
        create_ollama_modelfile(data_dir=args.data_dir, output_dir=args.output_dir, tag=args.tag)

    print(f"\n完成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("✓ 全部完成！")


if __name__ == "__main__":
    main()
