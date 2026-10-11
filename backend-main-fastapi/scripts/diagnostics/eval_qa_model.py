# -*- coding: utf-8 -*-
"""答疑模型评测：让"训练有没有变好"变成可测量的事实。

### 为什么需要它

现状是：训练跑了 789 步、合并出 5.9GB 模型，但**从没验证过效果** ——
没有任何脚本能回答"微调后比基座强在哪、有没有训坏"。
没有评测就没有迭代方向，继续炼丹只是浪费电。

### 评测做法

1. 从验证集（`val.jsonl`）抽 N 条，取出真实答案里的**关键术语**
2. 用同一批问题分别问 基座模型 / 微调模型
3. 计算确定性指标（不需要人工、不需要外部 API）：
   - `term_hit`    关键术语命中率 —— 答没答到点子上
   - `len_ratio`   输出长度是否健康（过短=敷衍，过长=复读）
   - `repetition`  重复率 —— 复读是微调最常见的退化
   - `chinese`     中文占比 —— 是否变成英文/乱码
4. 输出对照表，直接看微调是涨还是跌

用法：
    # 只评微调模型（快，先看现状）
    python eval_qa_model.py --model data/lora_finetune/merged --limit 10

    # 与基座对照（评测的核心价值）
    python eval_qa_model.py --compare --limit 10

    # 换评测集
    python eval_qa_model.py --model <路径> --questions data/lora_finetune/val.jsonl
"""

import argparse
import json
import os
import re
import statistics
import sys
import time

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
LORA_DIR = os.path.join(BASE, "data", "lora_finetune")

DEFAULT_SYSTEM = (
    "你是一个考研备考助手，专长是考研英语、政治、数学和专业课"
    "（数字电子技术、模拟电子技术等）。你基于用户提供的学习资料和知识库，"
    "给出准确、简洁、有条理的回答。"
)

# 停用词：这些不算"关键术语"，命中它们没有区分度
STOPWORDS = {
    "的", "了", "是", "在", "和", "与", "或", "有", "为", "对", "从", "到", "把", "被",
    "这个", "那个", "可以", "因此", "所以", "但是", "如果", "就是", "一个", "以及",
    "我们", "他们", "它", "这", "那", "其", "之", "也", "都", "而", "等", "中",
    "答案", "解析", "题目", "本题", "如下", "以下", "上述", "例如", "如图",
}


# --------------------------------------------------------------------------- #
# 关键术语抽取
# --------------------------------------------------------------------------- #
def extract_key_terms(text: str, *, top_k: int = 12) -> list[str]:
    """从参考答案里抽出关键术语。

    **必须用分词**：早期版本用 `[\\u4e00-\\u9fff]{2,6}` 硬切，
    抽出来的是 '卡诺图是用来' 这种跨词碎片，命中率指标完全失真。
    这里用 jieba 分词（缺失时退化为 2-gram，仅作兜底）。
    """
    if not text:
        return []
    counts: dict[str, int] = {}

    # —— 中文专业术语（分词 + 词性过滤）—— #
    try:
        import jieba.posseg as pseg

        for word, flag in pseg.cut(text):
            w = word.strip()
            if len(w) < 2 or len(w) > 8:
                continue
            if w in STOPWORDS:
                continue
            # 保留名词/动词/专名/缩写等实词，丢掉虚词与标点
            if not flag or flag[0] not in "nvatjgi":
                continue
            counts[w] = counts.get(w, 0) + 1
    except ImportError:
        for m in re.finditer(r"[\u4e00-\u9fff]{2,4}", text):
            w = m.group(0)
            if w in STOPWORDS:
                continue
            counts[w] = counts.get(w, 0) + 1

    # —— 英文缩写 / 型号 / 数字（JK、TTL、CMOS、555、D/A）—— #
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9/\-]{1,9}|\d{3,4}", text):
        w = m.group(0)
        if w.lower() in {"the", "and", "for", "with", "that", "this"}:
            continue
        counts[w] = counts.get(w, 0) + 1

    # 排序：长度优先（长术语区分度更高），其次频次
    ranked = sorted(counts.items(), key=lambda kv: (-len(kv[0]), -kv[1]))
    return [w for w, _ in ranked[:top_k]]


# --------------------------------------------------------------------------- #
# 确定性指标
# --------------------------------------------------------------------------- #
def term_hit_rate(answer: str, terms: list[str]) -> float:
    """关键术语命中率。"""
    if not terms:
        return 0.0
    a = answer or ""
    hit = sum(1 for t in terms if t in a)
    return round(hit / len(terms), 4)


def repetition_rate(answer: str, *, n: int = 8) -> float:
    """n-gram 重复率 —— 复读是微调最常见的退化表现。"""
    s = re.sub(r"\s+", "", answer or "")
    if len(s) < n * 2:
        return 0.0
    grams = [s[i:i + n] for i in range(len(s) - n + 1)]
    if not grams:
        return 0.0
    return round(1 - len(set(grams)) / len(grams), 4)


def chinese_ratio(answer: str) -> float:
    """中文占比（专业课答疑应该以中文为主）。"""
    s = answer or ""
    if not s:
        return 0.0
    cn = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    return round(cn / len(s), 4)


def copy_ratio(answer: str, question: str, *, n: int = 12) -> float:
    """答案照抄题干/资料的比例 —— **微调最常见的失败模式**。

    训练样本形如"请根据以下资料讲解…<大段原文>"时，模型很容易学会
    "把原文吐回去"而不是"讲解"。这种模型 term_hit 会虚高（抄原文当然命中术语），
    但完全没在答疑。

    做法：把答案切成 n-gram，统计有多少比例能在题干里原样找到。
    """
    a = re.sub(r"\s+", "", answer or "")
    q = re.sub(r"\s+", "", question or "")
    if len(a) < n or not q:
        return 0.0
    grams = [a[i:i + n] for i in range(len(a) - n + 1)]
    if not grams:
        return 0.0
    copied = sum(1 for g in grams if g in q)
    return round(copied / len(grams), 4)


def length_health(answer: str, *, lo: int = 15, hi: int = 1200) -> bool:
    """长度是否落在健康区间（过短=敷衍，过长=失控）。"""
    n = len((answer or "").strip())
    return lo <= n <= hi


# --------------------------------------------------------------------------- #
# 推理
# --------------------------------------------------------------------------- #
class Runner:
    """模型推理封装（CPU/GPU 自适应，4bit 量化可选）。"""

    def __init__(self, model_path: str, *, load_4bit: bool = True, device: str = "auto"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)

        use_cuda = torch.cuda.is_available() and device != "cpu"
        self.device = "cuda" if use_cuda else "cpu"

        kwargs = {"trust_remote_code": True}
        self.quantized = False
        if use_cuda and load_4bit:
            try:
                from transformers import BitsAndBytesConfig

                kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                )
                kwargs["device_map"] = "auto"
                self.quantized = True
            except Exception as e:
                print(f"  [!] 4bit 量化不可用（{e}），回退半精度")
                kwargs["torch_dtype"] = torch.float16
                kwargs["device_map"] = "auto"
        elif use_cuda:
            kwargs["torch_dtype"] = torch.float16
            kwargs["device_map"] = "auto"
        else:
            kwargs["torch_dtype"] = torch.float32
            kwargs["low_cpu_mem_usage"] = True

        self.model = AutoModelForCausalLM.from_pretrained(model_path, **kwargs)
        if not self.quantized and not use_cuda:
            self.model.to("cpu")
        self.model.eval()

    def ask(self, question: str, *, system: str = DEFAULT_SYSTEM,
            max_new_tokens: int = 300, temperature: float = 0.0) -> tuple[str, float]:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": question}]
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(text, return_tensors="pt").to(self.device)
        gen_kwargs = {
            "max_new_tokens": max_new_tokens,
            "pad_token_id": self.tokenizer.eos_token_id,
            "repetition_penalty": 1.1,
        }
        if temperature and temperature > 0:
            gen_kwargs.update(do_sample=True, temperature=temperature, top_p=0.9)
        else:
            gen_kwargs["do_sample"] = False

        t0 = time.time()
        with self.torch.no_grad():
            out = self.model.generate(**inputs, **gen_kwargs)
        elapsed = time.time() - t0
        gen = out[0][inputs["input_ids"].shape[1]:]
        return self.tokenizer.decode(gen, skip_special_tokens=True).strip(), elapsed


# --------------------------------------------------------------------------- #
# 评测集
# --------------------------------------------------------------------------- #
def load_questions(path: str, limit: int) -> list[dict]:
    """从 jsonl 读评测样本，返回 [{question, reference, terms}]。"""
    items: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msgs = obj.get("messages") or []
            q = ref = None
            for m in msgs:
                if m.get("role") == "user" and q is None:
                    q = m.get("content")
                elif m.get("role") == "assistant":
                    ref = m.get("content")
            if not q or not ref:
                continue
            items.append({
                "question": q,
                "reference": ref,
                "terms": extract_key_terms(ref),
            })
            if len(items) >= limit:
                break
    return items


# --------------------------------------------------------------------------- #
# 评测主流程
# --------------------------------------------------------------------------- #
def evaluate(runner: Runner, items: list[dict], *, label: str,
             max_new_tokens: int, verbose: bool = True) -> dict:
    rows = []
    for i, it in enumerate(items, 1):
        ans, secs = runner.ask(it["question"], max_new_tokens=max_new_tokens)
        row = {
            "term_hit": term_hit_rate(ans, it["terms"]),
            "copy_ratio": copy_ratio(ans, it["question"]),
            "repetition": repetition_rate(ans),
            "chinese": chinese_ratio(ans),
            "length": len(ans),
            "healthy_len": length_health(ans),
            "seconds": round(secs, 1),
            "answer": ans,
            "question": it["question"][:60],
            "expected_terms": it["terms"][:5],
        }
        rows.append(row)
        if verbose:
            flag = " ⚠️照抄" if row["copy_ratio"] > 0.5 else ""
            print(f"  [{i}/{len(items)}] term_hit={row['term_hit']:.2f} "
                  f"copy={row['copy_ratio']:.2f} rep={row['repetition']:.2f} "
                  f"cn={row['chinese']:.2f} len={row['length']:>4} "
                  f"{row['seconds']:>5.1f}s{flag}")

    n = len(rows) or 1
    summary = {
        "label": label,
        "n": len(rows),
        "term_hit": round(statistics.mean(r["term_hit"] for r in rows), 4),
        "copy_ratio": round(statistics.mean(r["copy_ratio"] for r in rows), 4),
        "repetition": round(statistics.mean(r["repetition"] for r in rows), 4),
        "chinese": round(statistics.mean(r["chinese"] for r in rows), 4),
        "avg_length": round(statistics.mean(r["length"] for r in rows), 1),
        "healthy_len_rate": round(sum(1 for r in rows if r["healthy_len"]) / n, 4),
        "avg_seconds": round(statistics.mean(r["seconds"] for r in rows), 1),
        "rows": rows,
    }
    return summary


def print_summary(s: dict) -> None:
    print(f"\n  ── {s['label']} ──")
    print(f"     样本数        {s['n']}")
    print(f"     术语命中率    {s['term_hit']:.3f}   ← 越高越好（答到点子上）")
    print(f"     照抄率        {s['copy_ratio']:.3f}   ← 越低越好（>0.5 = 在吐原文，没答疑）")
    print(f"     重复率        {s['repetition']:.3f}   ← 越低越好（复读=退化）")
    print(f"     中文占比      {s['chinese']:.3f}")
    print(f"     平均长度      {s['avg_length']:.0f} 字")
    print(f"     长度健康率    {s['healthy_len_rate']:.3f}")
    print(f"     平均耗时      {s['avg_seconds']:.1f}s/题")
    if s["copy_ratio"] > 0.5:
        print("\n     ⚠️  照抄率过高：模型在复述资料而非答疑。")
        print("         根因通常是训练样本把大段原文塞进 user 消息，")
        print("         模型只学会了'续写原文'。需要精简样本（见 prepare_qa_dataset.py）。")


def compare(a: dict, b: dict) -> None:
    print("\n" + "=" * 74)
    print("对照结论")
    print("=" * 74)
    print(f"  {'指标':<14}{'基座':>10}{'微调':>10}{'变化':>12}   判读")
    verdict = []

    def line(name, av, bv, higher_better, tol=0.02):
        delta = bv - av
        arrow = "↑" if delta > tol else ("↓" if delta < -tol else "=")
        good = (delta > tol) if higher_better else (delta < -tol)
        bad = (delta < -tol) if higher_better else (delta > tol)
        judge = "变好" if good else ("变差" if bad else "基本持平")
        print(f"  {name:<14}{av:>10.3f}{bv:>10.3f}{arrow + ' ' + f'{delta:+.3f}':>12}   {judge}")
        if good:
            verdict.append(f"{name} 提升")
        elif bad:
            verdict.append(f"{name} 下降")

    line("术语命中率", a["term_hit"], b["term_hit"], True)
    line("照抄率", a["copy_ratio"], b["copy_ratio"], False)
    line("重复率", a["repetition"], b["repetition"], False)
    line("中文占比", a["chinese"], b["chinese"], True)
    line("长度健康率", a["healthy_len_rate"], b["healthy_len_rate"], True)

    print()
    if b["copy_ratio"] > 0.5:
        print("  ❌ 微调模型照抄率过高（>0.5）：它没有在答疑，而是在复述资料。")
        print("     这种情况下 term_hit 再高也没有意义 —— 抄原文必然命中术语。")
        print("     下一步应清洗训练数据（精简 user 里的原文长度），而不是继续加练。")
    elif not verdict:
        print("  ⚠️  微调相对基座没有明显变化 —— 继续加练的收益存疑，")
        print("      建议先扩大/清洗训练数据，而不是加训练轮数。")
    else:
        print("  " + "；".join(verdict))
        if any("下降" in v for v in verdict):
            print("  ⚠️  存在退化指标，注意是否过拟合或数据噪声过大。")


def main() -> int:
    ap = argparse.ArgumentParser(description="答疑模型评测")
    ap.add_argument("--model", default=os.path.join(LORA_DIR, "merged"),
                    help="模型路径（默认微调后的 merged）")
    ap.add_argument("--questions", default=os.path.join(LORA_DIR, "val.jsonl"),
                    help="评测样本 jsonl（默认验证集）")
    ap.add_argument("--limit", type=int, default=8, help="评测题数（CPU 上别设太大）")
    ap.add_argument("--max-new-tokens", type=int, default=250)
    ap.add_argument("--compare", action="store_true", help="与基座模型对照")
    ap.add_argument("--base-model", default="Qwen/Qwen2.5-3B-Instruct",
                    help="对照用基座模型（本地路径或 HF id）")
    ap.add_argument("--no-4bit", action="store_true", help="禁用 4bit 量化")
    ap.add_argument("--out", default=os.path.join(LORA_DIR, "eval_result.json"))
    args = ap.parse_args()

    print("=" * 74)
    print("答疑模型评测")
    print("=" * 74)

    if not os.path.exists(args.questions):
        print(f"[x] 评测集不存在: {args.questions}")
        return 1
    items = load_questions(args.questions, args.limit)
    if not items:
        print("[x] 评测集为空（需要含 user/assistant 的 jsonl）")
        return 1
    print(f"评测集: {args.questions}  取 {len(items)} 题")
    print(f"样例题: {items[0]['question'][:70]}...")
    print(f"期望术语: {items[0]['terms'][:6]}")

    import torch
    print(f"\ntorch {torch.__version__} | cuda={torch.cuda.is_available()}"
          + (f" | {torch.cuda.get_device_name(0)}" if torch.cuda.is_available() else ""))

    results = {}

    # 微调模型
    print("\n" + "-" * 74)
    print(f"评测微调模型: {args.model}")
    print("-" * 74)
    if not os.path.exists(args.model):
        print(f"[x] 模型不存在: {args.model}")
        return 1
    r_ft = Runner(args.model, load_4bit=not args.no_4bit)
    print(f"  设备={r_ft.device} 4bit={r_ft.quantized}")
    results["finetuned"] = evaluate(r_ft, items, label="微调模型",
                                    max_new_tokens=args.max_new_tokens)
    print_summary(results["finetuned"])

    # 基座对照
    if args.compare:
        print("\n" + "-" * 74)
        print(f"评测基座模型: {args.base_model}")
        print("-" * 74)
        try:
            r_base = Runner(args.base_model, load_4bit=not args.no_4bit)
            print(f"  设备={r_base.device} 4bit={r_base.quantized}")
            results["base"] = evaluate(r_base, items, label="基座模型",
                                       max_new_tokens=args.max_new_tokens)
            print_summary(results["base"])
            compare(results["base"], results["finetuned"])
        except Exception as e:
            print(f"  [!] 基座模型加载失败，跳过对照: {type(e).__name__}: {e}")

    # 存结果
    try:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"args": vars(args), "results": results}, f,
                      ensure_ascii=False, indent=1)
        print(f"\n[✓] 结果已保存: {args.out}")
    except Exception as e:
        print(f"[!] 保存结果失败: {e}")

    # 打印几条实际回答，便于肉眼判断
    print("\n" + "=" * 74)
    print("样例回答（前 2 题，便于人工判断）")
    print("=" * 74)
    for r in results["finetuned"]["rows"][:2]:
        print(f"\nQ: {r['question']}")
        print(f"期望术语: {r['expected_terms']}")
        print(f"A: {r['answer'][:400]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
