# -*- coding: utf-8 -*-
"""本地模型 LoRA 微调脚本。

使用数据库中的 4670 条 SFT 样本对 qwen3.5:4b 进行 LoRA 微调，
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 数据目录
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lora_finetune")
os.makedirs(DATA_DIR, exist_ok=True)

# 模型配置
MODEL_NAME = "Qwen/Qwen2.5-4B-Instruct"  # 或本地路径
OUTPUT_DIR = os.path.join(DATA_DIR, "checkpoints")
MERGED_DIR = os.path.join(DATA_DIR, "merged")
MAX_LENGTH = 2048
BATCH_SIZE = 2
GRADIENT_ACCUMULATION = 8
LEARNING_RATE = 2e-4
NUM_EPOCHS = 3
LORA_R = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05


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
        messages.append({"role": "user", "content": ex.user or ""})
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
        ex = type('obj', (object,), {
            'system_prompt': f'你是一个考研{subject}辅导老师，请用简洁明了的语言回答问题。',
            'instruction': instruction,
            'input': '',
            'output': output,
            'subject': subject,
            'source': 'demo',
        })()
        examples.append(ex)

    return examples


def train_lora(data_dir: str = None, output_dir: str = None):
    """执行 LoRA 微调。

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
    out_dir = output_dir or OUTPUT_DIR

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
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from datasets import load_dataset
    except ImportError as e:
        print(f"✗ 缺少依赖库: {e}")
        print("请先安装：pip install torch transformers peft datasets accelerate trl bitsandbytes")
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

    model_kwargs = {
        "trust_remote_code": True,
        "torch_dtype": torch.bfloat16 if device == "cuda" else torch.float32,
    }
    if use_qlora:
        model_kwargs["quantization_config"] = bnb_config
        model_kwargs["device_map"] = {"": 0}
    elif device == "cuda":
        model_kwargs["device_map"] = "auto"

    model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, **model_kwargs)

    if use_qlora:
        model = prepare_model_for_kbit_training(model)

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
    # 计算warmup_steps（transformers 5.x移除了warmup_ratio）
    total_steps = (len(dataset["train"]) // (train_batch_size * grad_accum)) * NUM_EPOCHS
    warmup_steps = int(total_steps * 0.03)
    print(f"\n训练配置: 总步数={total_steps}, warmup_steps={warmup_steps}")

    training_args = TrainingArguments(
        output_dir=out_dir,
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
        save_total_limit=2,
    )

    # 训练器
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_datasets["train"],
        eval_dataset=tokenized_datasets["validation"],
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )

    # 开始训练
    print("\n开始训练...")
    trainer.train()

    # 保存模型
    final_output = os.path.join(out_dir, "final")
    trainer.save_model(final_output)
    tokenizer.save_pretrained(final_output)
    print(f"\n✓ 训练完成！模型保存到: {final_output}")

    return final_output


def merge_model():
    """合并 LoRA 权重并导出完整模型。"""
    print("=" * 60)
    print("阶段3：合并模型并导出")
    print("=" * 60)

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
    except ImportError as e:
        print(f"✗ 缺少依赖库: {e}")
        return

    lora_path = os.path.join(OUTPUT_DIR, "final")
    if not os.path.exists(lora_path):
        print(f"LoRA 模型不存在: {lora_path}")
        print("请先运行 --stage train")
        return

    print(f"加载基础模型: {MODEL_NAME}")
    base_model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float16,
        device_map="cpu",
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)

    print(f"加载 LoRA 权重: {lora_path}")
    model = PeftModel.from_pretrained(base_model, lora_path)

    print("合并权重...")
    merged_model = model.merge_and_unload()

    os.makedirs(MERGED_DIR, exist_ok=True)
    merged_model.save_pretrained(MERGED_DIR, safe_serialization=True)
    tokenizer.save_pretrained(MERGED_DIR)

    print(f"\n✓ 模型合并完成！保存到: {MERGED_DIR}")
    return MERGED_DIR


def create_ollama_modelfile():
    """创建 Ollama Modelfile 并导入模型。"""
    print("=" * 60)
    print("阶段4：导入 Ollama")
    print("=" * 60)

    merged_path = MERGED_DIR
    if not os.path.exists(merged_path):
        print(f"合并模型不存在: {merged_path}")
        print("请先运行 --stage merge")
        return

    # 创建 Modelfile（使用普通字符串拼接避免三引号嵌套问题）
    template_str = '{{{{ if .System }}}}{{{{ .System }}}}\n{{{{ end }}}}{{{{ if .Prompt }}}}{{{{ .Prompt }}}}\n{{{{ end }}}}'
    system_str = (
        "你是一个考研备考助手，专长是考研英语、政治、数学和专业课"
        "（数字电子技术、模拟电子技术等）。\n"
        "你基于用户提供的学习资料和知识库，给出准确、简洁、有条理的回答。\n"
        "回答时优先引用本地知识库内容，并标注来源。"
    )

    modelfile_content = (
        f"FROM {merged_path}\n\n"
        f'TEMPLATE """{template_str}"""\n\n'
        "PARAMETER temperature 0.7\n"
        "PARAMETER top_p 0.9\n"
        "PARAMETER top_k 40\n"
        "PARAMETER num_ctx 4096\n"
        "PARAMETER num_predict 2048\n\n"
        f'SYSTEM """{system_str}"""\n'
    )

    modelfile_path = os.path.join(DATA_DIR, "Modelfile")
    with open(modelfile_path, "w", encoding="utf-8") as f:
        f.write(modelfile_content)

    print(f"Modelfile 已创建: {modelfile_path}")
    print("\n执行以下命令导入 Ollama:")
    print(f"  ollama create kaoyan-assistant -f {modelfile_path}")
    print("\n导入完成后，运行:")
    print("  ollama run kaoyan-assistant")
    print("\n在平台设置中，将本地模型名称改为: kaoyan-assistant")

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
        "--output-dir",
        default=None,
        help="检查点输出目录（默认 <data-dir>/checkpoints）",
    )
    args = parser.parse_args()

    print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"执行阶段: {args.stage}")
    if args.data_dir:
        print(f"数据目录: {args.data_dir}")
    print()

    if args.stage == "prepare" or args.stage == "all":
        prepare_data()

    if args.stage == "train" or args.stage == "all":
        train_lora(data_dir=args.data_dir, output_dir=args.output_dir)

    if args.stage == "merge" or args.stage == "all":
        merge_model()

    if args.stage == "ollama" or args.stage == "all":
        create_ollama_modelfile()

    print(f"\n完成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("✓ 全部完成！")


if __name__ == "__main__":
    main()
