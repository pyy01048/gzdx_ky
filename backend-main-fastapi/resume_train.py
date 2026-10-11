# -*- coding: utf-8 -*-
"""从 checkpoint 恢复 LoRA 训练。

使用方法：
    python resume_train.py --checkpoint checkpoint-526
    python resume_train.py --checkpoint D:\平台\backend-main-fastapi\data\lora_finetune\checkpoints\checkpoint-526
"""

import sys
import os
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 数据目录
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lora_finetune")
OUTPUT_DIR = os.path.join(DATA_DIR, "checkpoints")

# 模型配置（使用本地ModelScope缓存，避免HuggingFace网络问题）
MODEL_NAME = r"C:\Users\33884\.cache\modelscope\hub\models\Qwen--Qwen2.5-3B-Instruct\snapshots\master"
MAX_LENGTH = 2048
BATCH_SIZE = 2
GRADIENT_ACCUMULATION = 8
LEARNING_RATE = 2e-4
NUM_EPOCHS = 3
LORA_R = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05


def resume_training(checkpoint_path):
    """从指定 checkpoint 恢复训练。"""
    print("=" * 60)
    print("恢复 LoRA 训练")
    print("=" * 60)
    print(f"从 checkpoint 恢复: {checkpoint_path}")
    print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    if not os.path.exists(checkpoint_path):
        print(f"✗ checkpoint 不存在: {checkpoint_path}")
        return None

    try:
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            TrainingArguments,
            Trainer,
            DataCollatorForLanguageModeling,
            BitsAndBytesConfig,
        )
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, PeftModel
        from datasets import load_dataset
    except ImportError as e:
        print(f"✗ 缺少依赖库: {e}")
        print("请先安装：pip install torch transformers peft datasets accelerate trl bitsandbytes")
        return None

    # 检查 GPU
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"使用设备: {device}")
    if device == "cuda":
        gpu_name = torch.cuda.get_device_name(0)
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"GPU: {gpu_name} ({gpu_memory:.1f} GB)")
    else:
        print("警告：未检测到 GPU，训练将非常缓慢")

    # QLoRA 4bit量化配置
    use_qlora = device == "cuda" and gpu_memory < 12
    if use_qlora:
        print("\n启用 QLoRA 4bit量化")
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
    else:
        bnb_config = None

    # 加载数据
    train_path = os.path.join(DATA_DIR, "train.jsonl")
    val_path = os.path.join(DATA_DIR, "val.jsonl")

    if not os.path.exists(train_path):
        print("✗ 训练数据不存在，请先运行 lora_finetune.py --stage prepare")
        return None

    dataset = load_dataset("json", data_files={
        "train": train_path,
        "validation": val_path,
    })
    print(f"训练集: {len(dataset['train'])} 条")
    print(f"验证集: {len(dataset['validation'])} 条")

    # 加载基础模型和分词器
    print(f"\n加载基础模型: {MODEL_NAME}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model_kwargs = {
        "trust_remote_code": True,
        "torch_dtype": torch.bfloat16 if device == "cuda" else torch.float32,
    }
    if use_qlora:
        model_kwargs["quantization_config"] = bnb_config
        model_kwargs["device_map"] = {"": 0}
    elif device == "cuda":
        model_kwargs["device_map"] = "auto"

    base_model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, **model_kwargs)

    if use_qlora:
        base_model = prepare_model_for_kbit_training(base_model)

    # 从 checkpoint 加载 LoRA 权重
    print(f"\n从 checkpoint 加载 LoRA 权重: {checkpoint_path}")
    model = PeftModel.from_pretrained(base_model, checkpoint_path, is_trainable=True)
    model.print_trainable_parameters()

    # 根据显存调整训练参数
    if use_qlora:
        train_batch_size = 1
        eval_batch_size = 1
        grad_accum = 16
        max_len = 1024
        print(f"\nQLoRA模式: batch_size={train_batch_size}, grad_accum={grad_accum}, max_len={max_len}")
    else:
        train_batch_size = BATCH_SIZE
        eval_batch_size = BATCH_SIZE
        grad_accum = GRADIENT_ACCUMULATION
        max_len = MAX_LENGTH

    # 数据预处理
    def preprocess_function(examples):
        texts = []
        for messages in examples["messages"]:
            text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
            texts.append(text)

        tokenized = tokenizer(
            texts,
            truncation=True,
            max_length=max_len,
            padding="max_length",
        )
        tokenized["labels"] = tokenized["input_ids"].copy()
        return tokenized

    tokenized_datasets = dataset.map(
        preprocess_function,
        batched=True,
        remove_columns=dataset["train"].column_names,
    )

    # 训练参数
    total_steps = (len(dataset["train"]) // (train_batch_size * grad_accum)) * NUM_EPOCHS
    warmup_steps = int(total_steps * 0.03)
    print(f"\n训练配置: 总步数={total_steps}, warmup_steps={warmup_steps}")

    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=train_batch_size,
        per_device_eval_batch_size=eval_batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=LEARNING_RATE,
        weight_decay=0.01,
        warmup_steps=warmup_steps,
        lr_scheduler_type="cosine",
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="epoch",
        load_best_model_at_end=True,
        report_to="none",
        bf16=device == "cuda",
        fp16=False,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="paged_adamw_8bit" if use_qlora else "adamw_torch",
        dataloader_num_workers=0,
        save_total_limit=3,
        resume_from_checkpoint=checkpoint_path,
    )

    # 训练器
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_datasets["train"],
        eval_dataset=tokenized_datasets["validation"],
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )

    # 从 checkpoint 恢复训练
    print("\n从 checkpoint 恢复训练...")
    print(f"预计还需训练约 {total_steps - 526} 步（从第526步开始）")
    print()

    trainer.train(resume_from_checkpoint=checkpoint_path)

    # 保存最终模型
    final_output = os.path.join(OUTPUT_DIR, "final")
    trainer.save_model(final_output)
    tokenizer.save_pretrained(final_output)
    print(f"\n✓ 训练完成！最终模型保存到: {final_output}")
    print(f"完成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return final_output


def main():
    parser = argparse.ArgumentParser(description="从 checkpoint 恢复 LoRA 训练")
    parser.add_argument(
        "--checkpoint",
        type=str,
        default="checkpoint-526",
        help="恢复训练的 checkpoint 路径或名称（默认：checkpoint-526）",
    )
    args = parser.parse_args()

    # 解析 checkpoint 路径
    checkpoint_path = args.checkpoint
    if not os.path.isabs(checkpoint_path):
        # 相对路径，拼接默认目录
        checkpoint_path = os.path.join(OUTPUT_DIR, checkpoint_path)

    resume_training(checkpoint_path)


if __name__ == "__main__":
    main()
