# -*- coding: utf-8 -*-
"""最小推理冒烟测试：微调后的 merged 模型是否可用、输出是否连贯。

用 CPU 跑（当前 torch 是 CPU 版），只生成很短的回答，纯粹验证：
  1. 模型能否加载
  2. 是否输出连贯中文（而非乱码/复读）
  3. 是否遵守 system 人设
"""
import os
import sys
import time

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MERGED = os.path.join(BASE, "data", "lora_finetune", "merged")

SYSTEM = (
    "你是一个考研备考助手，专长是考研英语、政治、数学和专业课"
    "（数字电子技术、模拟电子技术等）。你基于用户提供的学习资料和知识库，"
    "给出准确、简洁、有条理的回答。"
)

PROMPTS = [
    "什么是卡诺图？它用来做什么？",
    "JK触发器和D触发器有什么区别？",
]


def main() -> int:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"torch {torch.__version__} | cuda={torch.cuda.is_available()}")
    print(f"模型目录: {MERGED}")
    if not os.path.isdir(MERGED):
        print("[x] merged 目录不存在")
        return 1

    t0 = time.time()
    print("\n加载 tokenizer ...")
    tok = AutoTokenizer.from_pretrained(MERGED, trust_remote_code=True)
    print(f"  vocab={tok.vocab_size} chat_template={'有' if tok.chat_template else '无'}")

    print("加载模型（float32，CPU 上约需 12GB 内存）...")
    model = AutoModelForCausalLM.from_pretrained(
        MERGED, torch_dtype=torch.float32, trust_remote_code=True, low_cpu_mem_usage=True,
    )
    model.eval()
    n_param = sum(p.numel() for p in model.parameters())
    print(f"  参数量 {n_param/1e9:.2f}B | 加载耗时 {time.time()-t0:.1f}s")

    for q in PROMPTS:
        print("\n" + "=" * 70)
        print(f"Q: {q}")
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]
        text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tok(text, return_tensors="pt")
        t1 = time.time()
        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=120, do_sample=False,
                repetition_penalty=1.1, pad_token_id=tok.eos_token_id,
            )
        gen = out[0][inputs["input_ids"].shape[1]:]
        ans = tok.decode(gen, skip_special_tokens=True)
        print(f"A ({time.time()-t1:.1f}s): {ans.strip()[:400]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
