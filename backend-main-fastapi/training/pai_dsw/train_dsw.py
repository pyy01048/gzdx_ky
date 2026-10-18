# -*- coding: utf-8 -*-
"""PAI-DSW 云端 LoRA 训练脚本（Qwen2.5 系列，A10 24GB 实测调优）。

设计来源：本地 training/lora_finetune.py（715 行，本地 8GB 显存验证过），
训练逻辑原样复用（prompt 掩码 / 动态 padding / NaN 样本剔除 / 早停 /
use_reentrant=False / DataCollatorForSeq2Seq），只做 DSW 环境适配：

  1. OSS 已挂载到 /mnt/data/——数据/模型/checkpoint 的读写直接走文件路径，
     不需要 ossutil/oss2 SDK，也不需要 AK/SK；
  2. 基座经 ModelScope snapshot_download 拉取，缓存落到 /mnt/workspace
     （持久 cloudDisk；DSW 实例停止后 /root 容器层会丢，15GB 不能重下）；
  3. transformers 版本兼容：4.x 的 evaluation_strategy/torch_dtype 与 5.x 的
     eval_strategy/dtype 自动切换，不挑镜像版本；
  4. A10 24GB 默认 QLoRA 4bit（7B 约 11GB，余量充足、速度快）；
     --no-4bit 切 bf16 LoRA（约 19-21GB，贴顶，仅显存确实富余时用）；
  5. 训练结束自动把 adapter 复制到 OSS（/mnt/data 挂载点），
     本地机器随后下载 merge——adapter 只有 ~500MB，不要传 15GB 合并模型。

数据格式（与本地一致，每行一个 JSON）：
    {"messages": [{"role": "system"/"user"/"assistant", "content": "..."}],
     "subject": "...", "source": "..."}

用法：
    # 训练（数据目录来自 git 仓库或 /mnt/data 上传）
    python3 train_dsw.py \
        --data-dir  /mnt/workspace/gzdx_ky/data/lora_finetune_v2 \
        --output-dir /mnt/workspace/lora_out

    # 断点续跑（先把 OSS 上的 checkpoint 拉回 workspace）
    python3 train_dsw.py --data-dir ... --output-dir ... \
        --resume /mnt/workspace/lora_out/checkpoints/checkpoint-320
"""

import os
import sys
import json
import shutil
import datetime
import argparse

# 容器 locale 可能是 POSIX，打印中文/进度条会 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# transformers 版本兼容层（DSW 镜像版本不可控，4.x/5.x 都要能跑）
# ---------------------------------------------------------------------------

def _build_training_args(**kwargs):
    """按 transformers 版本选用 eval_strategy / evaluation_strategy。

    eval_strategy 是 4.41+ 的新名（evaluation_strategy 同期弃用、5.0 移除）。
    写死任何一个都会在另一种版本上 TypeError 让训练起不来。
    """
    import dataclasses
    from transformers import TrainingArguments
    fields = {f.name for f in dataclasses.fields(TrainingArguments)}
    if "eval_strategy" in fields:
        kwargs["eval_strategy"] = kwargs.pop("evaluation_strategy", "no")
    else:
        if "evaluation_strategy" in kwargs:
            kwargs["evaluation_strategy"] = kwargs.pop("evaluation_strategy")
        elif "eval_strategy" in kwargs:
            kwargs["evaluation_strategy"] = kwargs.pop("eval_strategy")
    return TrainingArguments(**kwargs)


def _load_base_model(model_name, quantize_4bit):
    """加载基座；自动处理 dtype/torch_dtype 改名（transformers 4.56+ 用 dtype）。

    QLoRA 4bit 下 compute dtype 由 BitsAndBytesConfig 管，dtype 仅作声明。
    """
    import torch
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    model_kwargs = {
        "trust_remote_code": True,
        "low_cpu_mem_usage": True,
        "device_map": {"": 0},
    }
    if quantize_4bit:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        dtype_value = torch.bfloat16
    else:
        dtype_value = torch.bfloat16

    try:
        return AutoModelForCausalLM.from_pretrained(
            model_name, dtype=dtype_value, **model_kwargs)
    except TypeError:
        # transformers < 4.56 不认识 dtype=，回退旧名 torch_dtype=
        return AutoModelForCausalLM.from_pretrained(
            model_name, torch_dtype=dtype_value, **model_kwargs)


# ---------------------------------------------------------------------------
# 环境变量（全部可覆盖，改超参不用动代码）
# ---------------------------------------------------------------------------

def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_str(name, default):
    return os.environ.get(name) or default


# Qwen2.5 ChatML 特殊标记（拼接写法，避免源码里出现裸标记被各处误解析）
CHATML_START = "<" + "|im_start|" + ">"
CHATML_END = "<" + "|im_end|" + ">"


# ---------------------------------------------------------------------------
# 数据预处理（与本地版完全一致——这些是踩过坑换来的，不要"简化"）
# ---------------------------------------------------------------------------

def preprocess_function(examples, tokenizer, max_len):
    """prompt 掩码 + 动态 padding。

    两个关键点（本地实测教训）：
    1. 只有 assistant 轮参与 loss——旧写法把题干也当学习目标，模型学会复述
       问题（上一版 LoRA 评测照抄率 0.72）；
    2. 不做静态 padding——样本 token 长度中位 215 / p95 662，补齐到 1024
       会把 4 倍算力花在 pad 上；交给 collator 动态补齐，labels 的 pad 位
       由 DataCollatorForSeq2Seq 填 -100。
    """
    texts = []
    prompt_lens = []
    for messages in examples["messages"]:
        full = tokenizer.apply_chat_template(messages, tokenize=False,
                                             add_generation_prompt=False)
        head = tokenizer.apply_chat_template(messages[:-1], tokenize=False,
                                             add_generation_prompt=True)
        texts.append(full)
        prompt_lens.append(len(tokenizer(head, add_special_tokens=False)["input_ids"]))

    tokenized = tokenizer(texts, truncation=True, max_length=max_len)
    labels = []
    for ids, plen in zip(tokenized["input_ids"], prompt_lens):
        labels.append([-100 if i < plen else tid for i, tid in enumerate(ids)])
    tokenized["labels"] = labels
    return tokenized


def _has_target(example):
    """prompt 过长被截断后 assistant 区间可能整段被切没 → labels 全 -100，
    交叉熵没有有效目标会返回 NaN 把整个训练毁掉。这类样本必须剔除。"""
    return any(l != -100 for l in example["labels"])


# ---------------------------------------------------------------------------
# 训练主流程
# ---------------------------------------------------------------------------

def train(data_dir, output_dir, resume_from=None, no_4bit=False):
    import torch
    from transformers import (
        AutoTokenizer, Trainer, DataCollatorForSeq2Seq,
        EarlyStoppingCallback,
    )
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from datasets import load_dataset

    print("=" * 60)
    print("PAI-DSW LoRA 微调训练")
    print("=" * 60)
    print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据目录: {data_dir}")
    print(f"输出目录: {output_dir}")

    # ---- GPU 检查 -------------------------------------------------------
    if not torch.cuda.is_available():
        print("✗ 未检测到 CUDA。DSW 实例若选了纯 CPU 镜像，训练无法进行。")
        print("  请在 PAI 控制台把实例换成 GPU 镜像（或当前内核的 torch 是 CPU 版，")
        print("  需重装 CUDA 版 torch，见 README「环境修复」一节）。")
        sys.exit(2)
    gpu_name = torch.cuda.get_device_name(0)
    gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f"GPU: {gpu_name} ({gpu_mem:.1f} GB), CUDA {torch.version.cuda}")

    # ---- 量化决策 -------------------------------------------------------
    # A10 24GB：7B 4bit ≈ 11GB（默认，快且稳）；bf16 ≈ 19-21GB（贴顶）
    quantize_4bit = not no_4bit
    if no_4bit and gpu_mem < 20:
        print(f"⚠ 显存 {gpu_mem:.0f}GB 跑 bf16 7B 约需 19-21GB，大概率 OOM，"
              f"已自动回退 QLoRA 4bit")
        quantize_4bit = True
    print(f"量化模式: {'QLoRA 4bit' if quantize_4bit else 'bf16 LoRA'}")

    # ---- 数据 -----------------------------------------------------------
    train_path = os.path.join(data_dir, "train.jsonl")
    val_path = os.path.join(data_dir, "val.jsonl")
    for p in (train_path, val_path):
        if not os.path.exists(p):
            print(f"✗ 训练数据不存在: {p}")
            print("  先运行 bash prepare_data.sh，或确认 git clone 是否完整")
            sys.exit(2)

    dataset = load_dataset("json", data_files={
        "train": train_path, "validation": val_path})
    print(f"训练集: {len(dataset['train'])} 条, 验证集: {len(dataset['validation'])} 条")

    # ---- 基座模型（ModelScope，缓存落持久盘） ---------------------------
    os.environ.setdefault("MODELSCOPE_CACHE", "/mnt/workspace/.cache/modelscope")
    base_model = _env_str("BASE_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    if os.path.isdir(base_model):
        print(f"使用本地基座: {base_model}")
        model_name = base_model
    else:
        print(f"经 ModelScope 拉取基座: {base_model}（缓存 {os.environ['MODELSCOPE_CACHE']}）")
        from modelscope import snapshot_download
        model_name = snapshot_download(base_model,
                                       cache_dir=os.environ["MODELSCOPE_CACHE"])
        print(f"基座就绪: {model_name}")

    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = _load_base_model(model_name, quantize_4bit)

    # ---- LoRA 配置 ------------------------------------------------------
    use_gc = _env_int("TRAIN_GRAD_CKPT", 1) == 1
    if quantize_4bit:
        # use_reentrant=False 必须显式传：peft 默认 True，与 TrainingArguments
        # 的 False 两套开关叠加会在 kbit 模型上把输入梯度算丢（loss 不降）。
        model = prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=use_gc,
            gradient_checkpointing_kwargs={"use_reentrant": False} if use_gc else None)

    lora_config = LoraConfig(
        r=_env_int("LORA_R", 16),
        lora_alpha=_env_int("LORA_ALPHA", 32),
        lora_dropout=_env_float("LORA_DROPOUT", 0.05),
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ---- 训练超参（A10 24GB + QLoRA 默认值） ----------------------------
    train_bs = _env_int("TRAIN_BATCH_SIZE", 2 if quantize_4bit else 1)
    grad_accum = _env_int("TRAIN_GRAD_ACCUM", 8)
    epochs = _env_int("TRAIN_EPOCHS", 3)
    lr = _env_float("LORA_LR", 1e-4)
    max_len = _env_int("TRAIN_MAX_LEN", 1024)
    eval_bs = _env_int("TRAIN_EVAL_BS", train_bs)

    if quantize_4bit:
        model.config.use_cache = False  # 开梯度检查必须关 KV cache
    print(f"\n超参: batch={train_bs}, grad_accum={grad_accum}, max_len={max_len}, "
          f"epochs={epochs}, lr={lr}, grad_ckpt={use_gc}")

    # ---- 数据预处理 ------------------------------------------------------
    tokenized = dataset.map(
        lambda ex: preprocess_function(ex, tokenizer, max_len),
        batched=True,
        remove_columns=dataset["train"].column_names,
    )
    dropped = {}
    for split in ("train", "validation"):
        before = len(tokenized[split])
        tokenized[split] = tokenized[split].filter(_has_target)
        dropped[split] = before - len(tokenized[split])
    print(f"  截断后无学习目标样本已剔除: train {dropped['train']} 条, "
          f"val {dropped['validation']} 条")

    n_train = len(tokenized["train"])
    total_steps = max(1, (n_train // (train_bs * grad_accum)) * epochs)
    warmup_steps = int(total_steps * 0.03)
    eval_steps = max(20, total_steps // max(1, epochs * 4))
    print(f"  总步数={total_steps}, warmup={warmup_steps}, "
          f"有效批量={train_bs * grad_accum}, 每 {eval_steps} 步评估/保存")

    training_args = _build_training_args(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=train_bs,
        per_device_eval_batch_size=eval_bs,
        gradient_accumulation_steps=grad_accum,
        learning_rate=lr,
        weight_decay=0.01,
        warmup_steps=warmup_steps,
        lr_scheduler_type="cosine",
        logging_steps=10,
        # 按步评估+早停（本地 v3b 教训：按 epoch 评估发现过拟合时已白跑一轮）
        evaluation_strategy="steps",
        save_strategy="steps",
        save_steps=eval_steps,
        eval_steps=eval_steps,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to="none",
        bf16=True,
        fp16=False,
        gradient_checkpointing=use_gc,
        gradient_checkpointing_kwargs={"use_reentrant": False} if use_gc else None,
        # Linux 上 paged_adadamw_8bit 可用，但 torch AdamW 更稳（可训练参数少，
        # 优化器状态常驻仅 ~200MB，没必要为省显存冒 UVM 风险）
        optim="adamw_torch",
        dataloader_num_workers=2,
        save_total_limit=_env_int("LORA_SAVE_LIMIT", 8),
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["validation"],
        # 不能用 DataCollatorForLanguageModeling：它会用 input_ids 覆盖
        # 我们算好的 prompt-mask labels。Seq2Seq 版才按 -100 填充 labels。
        data_collator=DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model,
                                             padding="longest", max_length=max_len),
        callbacks=[EarlyStoppingCallback(
            early_stopping_patience=_env_int("LORA_EARLY_STOP", 3))],
    )

    print("\n开始训练...", flush=True)
    t0 = datetime.datetime.now()
    if resume_from:
        print(f"从 checkpoint 续跑: {resume_from}")
        trainer.train(resume_from_checkpoint=resume_from)
    else:
        trainer.train()

    peak = torch.cuda.max_memory_allocated() / 1024**3
    secs = (datetime.datetime.now() - t0).total_seconds()
    steps = max(1, trainer.state.global_step)
    print(f"[基准] 步数={steps} 用时={secs:.0f}s 单步={secs / steps:.1f}s/it "
          f"峰值显存={peak:.2f}GB")

    # ---- 保存 adapter ----------------------------------------------------
    final_dir = os.path.join(output_dir, "checkpoints", "final")
    trainer.save_model(final_dir)
    tokenizer.save_pretrained(final_dir)
    print(f"\n✓ 训练完成，adapter 保存到: {final_dir}")

    # ---- 回传 OSS（/mnt/data 挂载点即 OSS） ------------------------------
    oss_out = _env_str("OSS_OUT", "/mnt/data/考研资料数据集/lora_out")
    if os.path.isdir(oss_out) or os.path.isdir(os.path.dirname(oss_out)):
        try:
            dest = os.path.join(oss_out, "final")
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.copytree(final_dir, dest)
            size_mb = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(dest) for f in fs) / 1024**2
            print(f"✓ adapter 已回传 OSS: {dest} ({size_mb:.0f} MB)")
        except OSError as e:
            print(f"⚠ 回传 OSS 失败（不影响本地文件）: {e}")
            print(f"  可手动执行: cp -r {final_dir} {oss_out}/")
    else:
        print(f"⚠ OSS 输出目录不存在: {oss_out}，跳过自动回传")

    return final_dir


def main():
    parser = argparse.ArgumentParser(description="PAI-DSW 云端 LoRA 训练")
    parser.add_argument("--data-dir", required=True,
                        help="训练数据目录（含 train.jsonl / val.jsonl）")
    parser.add_argument("--output-dir", default="/mnt/workspace/lora_out",
                        help="checkpoint 输出目录（默认 /mnt/workspace/lora_out，"
                             "持久 cloudDisk；不要直接写 /mnt/data，OSS 读写慢）")
    parser.add_argument("--base-model", default=None,
                        help="基座模型名或本地路径（默认 Qwen/Qwen2.5-7B-Instruct）")
    parser.add_argument("--resume", default=None,
                        help="从指定 checkpoint 目录续跑")
    parser.add_argument("--no-4bit", action="store_true",
                        help="用 bf16 LoRA 代替默认的 QLoRA 4bit（显存≥20GB 才建议）")
    args = parser.parse_args()

    if args.base_model:
        os.environ["BASE_MODEL"] = args.base_model

    train(args.data_dir, args.output_dir,
          resume_from=args.resume, no_4bit=args.no_4bit)
    print("\n✓ 全部完成！")


if __name__ == "__main__":
    main()
