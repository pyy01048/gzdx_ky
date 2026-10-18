# -*- coding: utf-8 -*-
"""PAI-DSW 训练前体检：把会在训练中途才炸的东西在开跑前一次性测出来。

为什么需要：train_dsw.py 的失败模式（torch 是 CPU 版 / bitsandbytes 装不上 /
transformers 字段改名 / 磁盘放不下基座 / 样本被截断成无学习目标）各自要跑到
加载模型或第一个 step 才暴露，而每次暴露的代价是几十分钟下载 + 一次实例重启。
本脚本只读不训，几十秒内给出结论，并把结果写成 JSON 供平台侧读取。

用法（DSW 上）：
    python3 preflight.py --data-dir /mnt/workspace/train_data
    python3 preflight.py --data-dir /mnt/workspace/train_data --with-tokenizer
    python3 preflight.py --no-4bit --max-len 2048

退出码：0 = 可以开训；1 = 有 FAIL 项，先修；2 = 连基本环境都测不了。
"""

import os
import sys
import json
import shutil
import argparse
import importlib
import importlib.metadata as md
import itertools

# 容器 locale 可能是 POSIX，中文输出会 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

PASS, WARN, FAIL = "pass", "warn", "fail"

#: 基座参数量 → fp16 磁盘/内存占用（GB），用于磁盘闸门。取整到偏保守。
BASE_SIZE_GB = {"0.5b": 1.0, "1.5b": 3.0, "3b": 6.2, "4b": 8.0, "7b": 15.0}

#: LoRA checkpoint 体积 × save_total_limit 的余量（GB）
CKPT_HEADROOM_GB = 5.0


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, name, detail):
        self.items.append({"level": level, "name": name, "detail": str(detail)})
        mark = {PASS: "[OK]  ", WARN: "[警告]", FAIL: "[失败]"}[level]
        print(f"  {mark} {name}: {detail}")
        return level

    @property
    def worst(self):
        levels = {i["level"] for i in self.items}
        return FAIL if FAIL in levels else (WARN if WARN in levels else PASS)


def _ver(mod):
    try:
        return md.version(mod)
    except Exception:  # noqa: BLE001
        return None


def check_python(r: Report):
    print("\n================ 解释器与依赖 ================")
    r.add(PASS, "python", sys.version.split()[0])
    for mod in ("torch", "transformers", "peft", "datasets",
                "accelerate", "bitsandbytes", "modelscope"):
        try:
            importlib.import_module(mod)
        except ImportError:
            r.add(FAIL if mod in ("torch", "transformers", "peft") else WARN,
                  f"依赖 {mod}", "未安装 —— 先跑 bash env_setup.sh")
            continue
        r.add(PASS, f"依赖 {mod}", _ver(mod) or "版本未知")


def check_gpu(r: Report):
    print("\n================ GPU ================")
    try:
        import torch
    except ImportError:
        return r.add(FAIL, "torch", "无法 import，跳过 GPU 检查")
    if not torch.cuda.is_available():
        return r.add(FAIL, "CUDA", f"torch {torch.__version__} 看不到 GPU "
                                  f"（驱动上限 CUDA 12.4；torch 被换成不匹配的版本就会这样）"
                                  f"→ bash env_setup.sh --restore")
    p = torch.cuda.get_device_properties(0)
    cap = torch.cuda.get_device_capability(0)
    r.add(PASS, "GPU", f"{p.name} {p.total_memory/1024**3:.1f}GB, "
                       f"torch CUDA={torch.version.cuda}, capability={cap[0]}.{cap[1]}")
    return cap


def check_4bit(r: Report, quantize: bool, cap):
    if not quantize:
        return
    print("\n================ QLoRA 4bit ================")
    try:
        import bitsandbytes  # noqa: F401
    except ImportError as e:
        r.add(FAIL, "bitsandbytes", f"import 失败: {e}")
        return
    # nf4 需要 Turing 及以上（capability >= 7.5）；A10 是 8.6
    if cap and cap < (7, 5):
        r.add(FAIL, "4bit 支持", f"capability {cap} 低于 7.5，nf4 不可用")
    else:
        r.add(PASS, "4bit 支持", f"bitsandbytes {_ver('bitsandbytes')} + capability {cap}")


def check_transformers_compat(r: Report, quantize: bool):
    """transformers 4.x/5.x 的字段改名会在构造参数时才炸，这里提前判定。"""
    print("\n================ transformers 兼容层 ================")
    try:
        import dataclasses
        from transformers import TrainingArguments
        import transformers
    except ImportError as e:
        r.add(FAIL, "transformers", str(e))
        return
    fields = {f.name for f in dataclasses.fields(TrainingArguments)}
    if "eval_strategy" in fields:
        r.add(PASS, "eval 参数名", "用 eval_strategy（4.41+/5.x）")
    elif "evaluation_strategy" in fields:
        r.add(PASS, "eval 参数名", "用 evaluation_strategy（<4.41）")
    else:
        r.add(FAIL, "eval 参数名", "TrainingArguments 两个名字都没有，train_dsw.py 会 TypeError")

    major = int(transformers.__version__.split(".")[0])
    r.add(PASS, "dtype 参数名",
          f"transformers {transformers.__version__} → "
          f"{'dtype（5.x 已把 torch_dtype 移除）' if major >= 5 else 'torch_dtype（旧名，dtype 会 TypeError）'}")

    if not quantize:
        # bf16 路径不过 prepare_model_for_kbit_training，梯度检查点缺
        # enable_input_require_grads 时 LoRA 梯度可能恒为 0（loss 不降），
        # 且 use_cache 未关会白算 past_key_values —— 这是实测过的坑，必须喊出来。
        r.add(WARN, "bf16 + 梯度检查点",
              "--no-4bit 时 train_dsw.py 不走 prepare_model_for_kbit_training，"
              "需确认已 model.enable_input_require_grads() 且 config.use_cache=False，"
              "否则可能 loss 不降")


def check_disk(r: Report, base_model: str):
    print("\n================ 磁盘与 OSS 挂载 ================")
    key = next((k for k in BASE_SIZE_GB if k in base_model.lower()), None)
    need = (BASE_SIZE_GB[key] if key else 15.0) + CKPT_HEADROOM_GB
    for path in ("/mnt/workspace", "/mnt/systemDisk"):
        if not os.path.isdir(path):
            continue
        free = shutil.disk_usage(path).free / 1024**3
        level = PASS if free >= need else FAIL
        r.add(level, f"磁盘 {path}", f"空闲 {free:.1f}GB，本次约需 {need:.1f}GB"
                                    f"（基座 + {CKPT_HEADROOM_GB:.0f}GB checkpoint 余量）")
    r.add(PASS, "基座缓存目录", os.environ.setdefault(
        "MODELSCOPE_CACHE", "/mnt/workspace/.cache/modelscope")
        + "（必须落持久盘；/root 容器层实例停止即丢）")

    if not os.path.isdir("/mnt/data"):
        r.add(FAIL, "OSS 挂载", "/mnt/data 不存在，产物无法回传")
        return
    try:
        top = list(itertools.islice(os.listdir("/mnt/data"), 30))
        r.add(PASS, "OSS 挂载", f"/mnt/data 可读，顶层 {len(top)} 项: {', '.join(top[:5])}")
    except OSError as e:
        r.add(FAIL, "OSS 挂载", f"读取失败: {e}")


def check_dataset(r: Report, data_dir: str, max_len: int):
    print("\n================ 训练数据 ================")
    stats = {}
    for split in ("train", "val"):
        path = os.path.join(data_dir, f"{split}.jsonl")
        if not os.path.exists(path):
            r.add(FAIL, f"{split}.jsonl", f"不存在: {path}（先跑 prepare_data.sh）")
            continue
        n = bad = no_target = 0
        ans_chars = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                n += 1
                try:
                    obj = json.loads(line)
                    msgs = obj["messages"]
                    assert msgs[-1]["role"] == "assistant", "末轮不是 assistant"
                    assert msgs[-1]["content"].strip(), "assistant 内容为空"
                    ans_chars.append(len(msgs[-1]["content"]))
                except (json.JSONDecodeError, KeyError, AssertionError, TypeError) as e:
                    bad += 1
                    if bad <= 3:
                        print(f"    第 {n} 行不合格: {e}")
        if bad:
            r.add(FAIL, f"{split}.jsonl", f"{n} 条中 {bad} 条不合格，训练会中途 AttributeError")
        else:
            r.add(PASS, f"{split}.jsonl", f"{n} 条，JSON 与角色顺序全部合格")
        stats[split] = n
        if ans_chars:
            avg = sum(ans_chars) / len(ans_chars)
            r.add(WARN if avg < 120 else PASS, f"{split} 答案均长",
                  f"{avg:.0f} 字（<120 字多为截断的定义句或模板句，"
                  f"学出来是复读而非讲解）")

    n_train = stats.get("train", 0)
    if n_train:
        # 有效批量 16（batch2×accum8）下的步数：少于 ~150 步的 LoRA 基本看不出差异，
        # 这是算力安排问题而非错误，所以只 WARN。
        steps = max(1, n_train // 16) * 3
        r.add(WARN if steps < 150 else PASS, "训练规模",
              f"{n_train} 条 × 3 轮 ≈ {steps} 步；样本量决定收益，A10 只是让它更快")
    return stats


def check_tokenizer(r: Report, base_model: str, max_len: int, data_dir: str):
    """可选：只下载分词器文件（几十 KB），算真实 token 长度分布。

    max_len 拍脑袋定小了会截掉学习目标（labels 全 -100 的样本要剔除），
    定大了把算力花在 pad 上，所以值得实测一次。
    """
    print("\n================ token 长度分布（--with-tokenizer）================")
    try:
        from modelscope import snapshot_download
        from transformers import AutoTokenizer
    except ImportError as e:
        r.add(WARN, "分词器", f"跳过: {e}")
        return
    try:
        snap = snapshot_download(
            base_model,
            cache_dir=os.environ["MODELSCOPE_CACHE"],
            allow_patterns=["tokenizer*", "*.json", "vocab*", "merges*", "chat_template*"])
        tok = AutoTokenizer.from_pretrained(snap, trust_remote_code=True)
    except Exception as e:  # noqa: BLE001
        r.add(WARN, "分词器", f"拉取失败（离线/网络）: {e}")
        return

    lens, over = [], 0
    with open(os.path.join(data_dir, "train.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            msgs = json.loads(line)["messages"]
            text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            n = len(tok(text, add_special_tokens=False)["input_ids"])
            lens.append(n)
            if n > max_len:
                over += 1
    if not lens:
        r.add(WARN, "分词器", "没有可测样本")
        return
    lens.sort()
    pct = lambda q: lens[min(len(lens) - 1, int(len(lens) * q))]
    r.add(WARN if over else PASS, "token 长度",
          f"中位 {pct(.5)} / p90 {pct(.9)} / p95 {pct(.95)} / 最长 {lens[-1]}；"
          f"max_len={max_len} 下有 {over}/{len(lens)} 条会被截断")


def main():
    ap = argparse.ArgumentParser(description="PAI-DSW 训练前体检")
    ap.add_argument("--data-dir", default="/mnt/workspace/train_data")
    ap.add_argument("--base-model", default=os.environ.get("BASE_MODEL",
                                                           "Qwen/Qwen2.5-7B-Instruct"))
    ap.add_argument("--max-len", type=int, default=int(os.environ.get("TRAIN_MAX_LEN", 1024)))
    ap.add_argument("--no-4bit", action="store_true")
    ap.add_argument("--with-tokenizer", action="store_true",
                    help="额外下载分词器（几十 KB）实测 token 长度分布")
    ap.add_argument("--json-out", default="/mnt/workspace/preflight.json")
    args = ap.parse_args()

    print("=" * 60)
    print("PAI-DSW 训练前体检")
    print("=" * 60)
    r = Report()
    check_python(r)
    cap = check_gpu(r)
    quantize = not args.no_4bit
    check_4bit(r, quantize, cap)
    check_transformers_compat(r, quantize)
    check_disk(r, args.base_model)
    ds = check_dataset(r, args.data_dir, args.max_len)
    if args.with_tokenizer:
        check_tokenizer(r, args.base_model, args.max_len, args.data_dir)

    print("\n" + "=" * 60)
    print(f"结论: {r.worst.upper()}")
    print("=" * 60)
    payload = {
        "verdict": r.worst,
        "base_model": args.base_model,
        "quantize_4bit": quantize,
        "max_len": args.max_len,
        "dataset": ds,
        "items": r.items,
    }
    try:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"机器可读结果: {args.json_out}")
    except OSError as e:
        print(f"⚠ 无法写 {args.json_out}: {e}")
    sys.exit(1 if r.worst == FAIL else 0)


if __name__ == "__main__":
    main()
