#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSW 合成训练数据生产：7B 当工人，按能力模板批量造问答。

### 核心设计：我们出题，模型只作答

第一版构想是"让 7B 同时生成问题和答案"，实测这是合成数据最脆的一环——格式
不稳、幻觉多、还容易自问自答。改成：
  1. **问题由种子确定性构造**（模板 + crc32 选句，同种子必出同问题，可复现）
  2. **答案由 7B 依据种子资料生成**（不允许脱离资料编造）
  3. **质检三道闸**：不得照抄问题、长度区间、必须提及种子术语

这样问题质量与多样性由模板保证，答案质量由 7B + 资料保证，两者都不依赖
模型"自觉"。

### 五类能力（对应 docx/26 的 C5-C9）

| kind | 能力 | 种子 | 产出 |
|---|---|---|---|
| socratic | 主动追问 | 知识点+释义 | 反问定位盲点 + 讲解 |
| contrast | 易混辨析 | 同学科两个相近知识点 | 对比 + 判定方法 |
| gen_quiz | 智能出题 | 知识点+资料 | 新题 + 答案 + 解析 |
| summarize | 总结提炼 | 多段正文 | 结构化复习笔记 |
| flashcards | 记忆卡片 | 知识点+释义 | 正面问 / 背面答 |

### 用法

    # 从 OCR 产物里抽种子（没跑 OCR 时可用 v3 数据集兜底）
    python3 gen_synthetic.py --ocr-dir /mnt/workspace/ocr_out \
                             --out-dir /mnt/workspace/synth \
                             --max-per-kind 1500

    # 只看会生成多少条，不加载模型
    python3 gen_synthetic.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import zlib
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

#: 与 build_qa_dataset.py / lora_finetune.py 训练样本**逐字一致**的 system。
#: 训练-推理 system 不一致是效果打折的隐形杀手，这里必须复用同一份。
SYSTEM = (
    "你是一位考研辅导老师，负责计算机与电子信息类（834 电子技术基础：数字电子、"
    "模拟电子）以及数学二、英语二、政治的答疑。答疑风格：① 先判断学生卡在概念还是计算——"
    "概念不清时先抛一个引导性问题帮他定位盲点（苏格拉底式引导）再讲解，计算类直接给结论与步骤；"
    "② 结构：先给结论，再讲原理，必要时给出解题步骤，只讲与问题相关的内容，不复述题目原文；"
    "③ 对定义、公式、考点等记忆型内容，提示用间隔重复（当天、1天、3天、7天后回顾，对应 SM-2 记忆曲线）巩固；"
    "④ 不确定时明确说明并给出最稳妥的复习建议，不编造。"
)

_AI_REFUSAL = ("作为一个AI", "作为一个 AI", "我无法提供", "抱歉，我不能", "语言模型",
               "我是一个助手", "以上内容仅供参考")


# --------------------------------------------------------------------------- #
# 质检闸
# --------------------------------------------------------------------------- #

def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def answer_is_copy(question: str, answer: str, *, n: int | None = None) -> bool:
    """答案是否基本照抄问题——合成数据最致命的质量问题，必须 0 条。

    n 必须**随问题长度自适应**：v3 的提问均值只有 17 字，若固定用 n=16，
    10 字问题的答案里根本不存在 16 字子串，16-gram 命中恒为 0，
    这道防线等于形同虚设（模型照抄学不会，自己却以为拦住了）。
    实测：固定 n=16 时 `q*12` 这种 blatant 复读都检测不出来。
    """
    a, q = _norm(answer), _norm(question)
    if len(a) < 8 or len(q) < 4:
        return False
    if n is None:
        n = max(6, min(16, len(q) // 3))
    if len(a) < n:
        return False
    grams = [a[i:i + n] for i in range(len(a) - n + 1)]
    return bool(grams) and sum(1 for g in grams if g in q) / len(grams) > 0.5


def answer_ok(answer: str, question: str, term: str | None,
              *, min_chars=80, max_chars=1500) -> tuple[bool, str]:
    """返回 (是否合格, 原因)。三道闸：长度 / 拒答话术 / 是否提及术语。"""
    a = (answer or "").strip()
    if len(a) < min_chars:
        return False, f"too_short({len(a)})"
    if len(a) > max_chars:
        return False, f"too_long({len(a)})"
    if any(t in a for t in _AI_REFUSAL):
        return False, "ai_refusal"
    if answer_is_copy(question, a):
        return False, "copy_of_question"
    if len(re.findall(r"[。！？；]", a)) < 2:
        return False, "too_few_sentences"
    if term and term not in a:
        return False, "term_not_mentioned"
    return True, ""


_LEAD_JUNK = re.compile(
    r"^\s*(?:好的|好|当然|没问题|可以|以下是|下面(是|为)|根据(所给|上述)?(的)?(资料|材料|内容|信息))"
    r"[，,：:。！!]?\s*"
)
_META_JUNK = re.compile(
    r"^\s*(?:我(来|来)?(回答|为你)?(作答|解答|说明)?|为你(解答|分析)?|"
    r"回答如下|答案如下|如下|解析如下|解答如下|"
    r"以下是(解答|回答|解析)|下面(是|为)(解答|回答|解析))"
    r"\s*[：:，,！!]?\s*"
)


def clean_answer(text: str) -> str:
    """剥掉模型爱加的寒暄与元话语，只留讲解本体。

    要剥**多层**："好的，我来回答，放大电路是…" 里前缀是"好的，"→"我来回答"。
    一次只剥一层会把"我来回答"留在开头，训练时等于教模型先寒暄再答题。
    循环剥到不动为止。
    """
    t = (text or "").strip()
    for _ in range(5):
        before = t
        t = _LEAD_JUNK.sub("", t, count=1)
        t = _META_JUNK.sub("", t, count=1)
        t = t.lstrip("：:，,。！! ")
        if t == before:
            break
    # 结尾元话语
    t = re.sub(r"\n*(希望|如果|如需|如果还有).{0,30}(问题|疑问|需要).{0,20}[。！!]?\s*$", "", t)
    return t.strip()


# --------------------------------------------------------------------------- #
# 种子抽取
# --------------------------------------------------------------------------- #

_STOP_TERM = set("的了是在和与或这那其该本就也都还又很更最把被让给从对为由及等")


def guess_term(text: str) -> str | None:
    """从正文里猜一个像术语的 2-4 字中文片段当种子术语。

    只用确定性 n-gram 频次（不用随机），同资料必出同术语。
    """
    zh = "".join(re.findall(r"[\u4e00-\u9fff]+", text or ""))
    if len(zh) < 30:
        return None
    for n, need in ((4, 2), (3, 2), (2, 4)):
        counter: dict[str, int] = {}
        for i in range(len(zh) - n + 1):
            g = zh[i:i + n]
            if g[0] in _STOP_TERM or g[-1] in _STOP_TERM:
                continue
            counter[g] = counter.get(g, 0) + 1
        cands = [(g, k) for g, k in counter.items() if k >= need]
        if not cands:
            continue
        for g, _ in sorted(cands, key=lambda kv: (-kv[1], kv[0])):
            if 2 <= len(g) <= 8:
                return g
    return None


def load_seeds(ocr_dir: str | None, limit: int) -> list[dict]:
    """从 OCR 产物 json 读种子：(text, term, subject, src)。"""
    seeds: list[dict] = []
    if not ocr_dir or not Path(ocr_dir).is_dir():
        print(f"[!] OCR 目录不可用: {ocr_dir}（将只用兜底种子）")
        return seeds
    files = sorted(Path(ocr_dir).glob("*.json"))
    print(f"[i] OCR 产物 {len(files)} 个")
    for p in files:
        try:
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        text = (rec.get("text") or "").strip()
        if len(text) < 200:
            continue
        # 每篇切 2-3 段做种子：一段长资料没必要只出一个问题
        paras = [s.strip() for s in re.split(r"\n{2,}", text) if len(s.strip()) >= 200]
        for para in paras[:3]:
            term = guess_term(para)
            if not term:
                continue
            seeds.append({"text": para[:1200], "term": term,
                          "subject": "", "src": rec.get("src", p.name)})
        if len(seeds) >= limit:
            break
    return seeds[:limit]


def fallback_seeds(limit: int) -> list[dict]:
    """没有 OCR 产物时的兜底：直接拿 v3 训练集里的答案当资料种子。"""
    out = []
    for cand in ("data/lora_finetune_v3/train.jsonl",
                 os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "data/lora_finetune_v3/train.jsonl")):
        p = Path(cand)
        if not p.exists():
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    it = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ans = it["messages"][2]["content"]
                term = guess_term(ans)
                if term and len(ans) >= 200:
                    out.append({"text": ans[:1200], "term": term,
                                "subject": it.get("subject", ""), "src": "v3"})
                if len(out) >= limit:
                    return out
        break
    return out


# --------------------------------------------------------------------------- #
# 五类生成器：question 由种子确定，answer 由 7B 生成
# --------------------------------------------------------------------------- #

_Q_SOCRATIC = ("考研里{t}这块我没太懂，能先帮我定位一下我卡在哪吗？",
               "{t}我总是搞混，先别直接讲，能不能先问我一个问题帮我理清思路？",
               "{t}到底该怎么理解？我怀疑自己漏了某个前提。")
_Q_CONTRAST = ("{t0}和{t1}我老是分不清，能对比讲讲吗？",
               "{t0}与{t1}的区别到底在哪？做题时怎么快速判断该用哪个？",
               "{t0}、{t1}这两个概念，考试里会怎么区分考？")
_Q_QUIZ = ("请根据下面的资料出一道{subject}的{ctype}题，并给出答案和解析。",
           "我要练手：基于这份资料出一道{ctype}题，附答案和解析。",
           "照着这份资料出一道{ctype}自测题，答案要唯一，解析要说清为什么。")
_Q_SUMMARY = ("把下面这份资料整理成一份结构化复习笔记。",
              "帮我把这份资料压缩成考前能快速回顾的要点笔记。",
              "下面这段内容，请提炼成条理清晰的复习提纲。")
_Q_CARD = ("把下面关于{t}的内容做成记忆卡片，正面写问题、背面写答案。",)

_CTYPES = ("单选题", "简答题", "判断题")


def build_tasks(seeds: list[dict], max_per_kind: int) -> list[dict]:
    """按五类能力把种子展开成生成任务。问题在本地构造（确定性）。"""
    tasks: list[dict] = []
    rng = random.Random(42)

    # socratic：每个种子出一条
    for s in seeds:
        if len([t for t in tasks if t["kind"] == "socratic"]) >= max_per_kind:
            break
        pick = zlib.crc32(f"soc|{s['src']}|{s['term']}".encode()) % len(_Q_SOCRATIC)
        tasks.append({
            "kind": "socratic", "term": s["term"], "src": s["src"],
            "subject": s.get("subject", ""),
            "question": _Q_SOCRATIC[pick].format(t=s["term"]),
            "material": s["text"],
            "instruction": (
                f"资料说的是「{s['term']}」相关内容。学生问：{_Q_SOCRATIC[pick].format(t=s['term'])}\n"
                f"请按两步作答：\n"
                f"第一步「追问：」写一个能精准定位学生盲点的反问（不要复述问题，"
                f"要问在学生最容易含糊过去的那一点上）；\n"
                f"第二步「讲解：」再给完整讲解，结论先行，讲清原理与典型应用。\n"
                f"只依据资料作答，资料没说的不要编。"),
        })

    # contrast：把种子两两配对（同一学科、相近术语）
    socratic_seeds = [s for s in seeds if s["term"]]
    pairs = list(zip(socratic_seeds, socratic_seeds[1:])) + \
        list(zip(socratic_seeds[::3], socratic_seeds[1::3]))
    rng.shuffle(pairs)
    n_contrast = 0
    for a, b in pairs:
        if n_contrast >= max_per_kind:
            break
        if a["term"] == b["term"]:
            continue
        n_contrast += 1
        pick = zlib.crc32(f"con|{a['term']}|{b['term']}".encode()) % len(_Q_CONTRAST)
        q = _Q_CONTRAST[pick].format(t0=a["term"], t1=b["term"])
        tasks.append({
            "kind": "contrast", "term": a["term"], "src": a["src"], "subject": "",
            "question": q,
            "material": f"【{a['term']}】{a['text']}\n\n【{b['term']}】{b['text']}",
            "instruction": (
                f"对比讲解「{a['term']}」与「{b['term']}」。格式：\n"
                f"先给一句话结论说清核心差别；然后分维度对比（定义/适用条件/易错点）；"
                f"最后给一个「怎么快速判定该用哪个」的操作性判断方法，并举一个典型错例。\n"
                f"只依据所给资料，不要编造资料没有的差别。"),
        })

    # gen_quiz：每 3 个种子出一条，控制总量
    for i, s in enumerate(seeds):
        if len([t for t in tasks if t["kind"] == "gen_quiz"]) >= max_per_kind:
            break
        if i % 3:
            continue
        ctype = _CTYPES[zlib.crc32(f"q|{s['src']}".encode()) % len(_CTYPES)]
        subj = s.get("subject") or "专业课"
        pick = zlib.crc32(f"quiz|{s['src']}".encode()) % len(_Q_QUIZ)
        q = _Q_QUIZ[pick].format(subject=subj, ctype=ctype)
        tasks.append({
            "kind": "gen_quiz", "term": s["term"], "src": s["src"], "subject": subj,
            "question": q, "material": s["text"],
            "instruction": (
                f"请出一道{ctype}：\n"
                f"题目：\n解析：（说清为什么是这个答案，步骤要能复现；单选题要给干扰项并说明错在哪）\n"
                f"要求：答案唯一、考点明确落在「{s['term']}」上、不得超出资料范围编造事实。"),
        })

    # summarize：每 4 个种子出一条
    for i, s in enumerate(seeds):
        if len([t for t in tasks if t["kind"] == "summarize"]) >= max_per_kind:
            break
        if i % 4:
            continue
        pick = zlib.crc32(f"sum|{s['src']}".encode()) % len(_Q_SUMMARY)
        q = _Q_SUMMARY[pick]
        tasks.append({
            "kind": "summarize", "term": s["term"], "src": s["src"],
            "subject": s.get("subject", ""), "question": q, "material": s["text"],
            "instruction": (
                "整理成复习笔记，要求：\n"
                "① 开头一句话点明这段讲的是什么主题；\n"
                "② 分条列核心要点（每条一句话，可含关键公式或判定条件）；\n"
                "③ 结尾给一句「最容易考/最容易错的地方」。\n"
                "只依据资料，不要添加资料之外的知识。"),
        })

    # flashcards：每 5 个种子出一条
    for i, s in enumerate(seeds):
        if len([t for t in tasks if t["kind"] == "flashcards"]) >= max_per_kind:
            break
        if i % 5:
            continue
        q = _Q_CARD[0].format(t=s["term"])
        tasks.append({
            "kind": "flashcards", "term": s["term"], "src": s["src"],
            "subject": s.get("subject", ""), "question": q, "material": s["text"],
            "instruction": (
                f"做 2 张关于「{s['term']}」的记忆卡片，严格用这个格式：\n"
                f"卡片1 正面：<问题>\n卡片1 背面：<一句话答案>\n"
                f"卡片2 正面：<问题>\n卡片2 背面：<一句话答案>\n"
                f"要求：正面是能自测的短问题，背面是一句话说清的答案，不要长段落。"),
        })

    return tasks


# --------------------------------------------------------------------------- #
# 批量生成
# --------------------------------------------------------------------------- #

MAX_NEW = {"socratic": 600, "contrast": 700, "gen_quiz": 700,
           "summarize": 700, "flashcards": 400}


def load_model(base_model: str):
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM

    os.environ.setdefault("MODELSCOPE_CACHE", "/mnt/workspace/.cache/modelscope")
    if os.path.isdir(base_model):
        path = base_model
    else:
        print(f"经 ModelScope 拉取基座: {base_model}")
        from modelscope import snapshot_download
        path = snapshot_download(base_model, cache_dir=os.environ["MODELSCOPE_CACHE"])
    tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
    tok.padding_side = "left"          # 生成必须左 padding
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        path, dtype=torch.bfloat16, device_map={"": 0}, trust_remote_code=True)
    model.eval()
    return tok, model


def generate_batch(tok, model, batch: list[dict], max_new: int) -> list[str]:
    import torch
    prompts = []
    for t in batch:
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content":
                    f"资料：\n{t['material']}\n\n任务：\n{t['instruction']}"}]
        prompts.append(tok.apply_chat_template(msgs, tokenize=False,
                                               add_generation_prompt=True))
    enc = tok(prompts, return_tensors="pt", padding=True, truncation=True,
              max_length=2048).to(model.device)
    with torch.no_grad():
        out = model.generate(
            **enc, max_new_tokens=max_new, do_sample=True, temperature=0.85,
            top_p=0.9, repetition_penalty=1.05,
            pad_token_id=tok.pad_token_id)
    gen = out[:, enc["input_ids"].shape[1]:]
    return tok.batch_decode(gen, skip_special_tokens=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="DSW 合成训练数据生产")
    ap.add_argument("--ocr-dir", default="/mnt/workspace/ocr_out",
                    help="OCR 产物目录（种子来源）")
    ap.add_argument("--out-dir", default="/mnt/workspace/synth", help="产物目录")
    ap.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--max-per-kind", type=int, default=1500, help="每类能力最多生成多少条")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--seed-limit", type=int, default=2000, help="最多读多少个种子")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-kinds", default="", help="逗号分隔，如 summarize,flashcards")
    args = ap.parse_args()

    print("=" * 70)
    print("DSW 合成数据生产")
    print("=" * 70)

    seeds = load_seeds(args.ocr_dir, args.seed_limit)
    if len(seeds) < 50:
        fb = fallback_seeds(args.seed_limit)
        print(f"[i] OCR 种子不足（{len(seeds)}），补兜底种子 {len(fb)} 条")
        seeds = seeds + fb
    print(f"种子总数: {len(seeds)}")

    skip = {k.strip() for k in args.skip_kinds.split(",") if k.strip()}
    tasks = [t for t in build_tasks(seeds, args.max_per_kind) if t["kind"] not in skip]
    from collections import Counter
    print(f"待生成任务: {len(tasks)}  分布: {dict(Counter(t['kind'] for t in tasks))}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        for t in tasks[:5]:
            print(f"\n[{t['kind']}] Q: {t['question']}")
        return 0

    # 断点续跑：已完成的 (kind, src) 不再重做
    done = set()
    for kind in set(t["kind"] for t in tasks):
        p = out_dir / f"{kind}.jsonl"
        if not p.exists():
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    it = json.loads(line)
                    done.add((it.get("kind"), it.get("seed")))
                except json.JSONDecodeError:
                    pass
    todo = [t for t in tasks if (t["kind"], f"{t['src']}|{t['term']}") not in done]
    if done:
        print(f"已完成 {len(done)} 条，本轮剩 {len(todo)} 条")

    if not todo:
        print("✓ 无待生成任务")
        return 0

    print(f"加载基座（首次会下载 15GB 左右）: {args.base_model}")
    tok, model = load_model(args.base_model)

    stats = Counter()
    reject = Counter()
    handles = {k: open(out_dir / f"{k}.jsonl", "a", encoding="utf-8") for k in MAX_NEW}
    t0 = time.time()
    try:
        for i in range(0, len(todo), args.batch_size):
            batch = todo[i:i + args.batch_size]
            # 同批尽量同 kind：max_new_tokens 按 kind 不同
            by_kind: dict[str, list[dict]] = {}
            for t in batch:
                by_kind.setdefault(t["kind"], []).append(t)
            for kind, group in by_kind.items():
                try:
                    answers = generate_batch(tok, model, group, MAX_NEW[kind])
                except Exception as e:  # noqa: BLE001
                    print(f"  [!] 批次生成失败({kind}): {type(e).__name__}: {e}")
                    continue
                for t, raw in zip(group, answers):
                    ans = clean_answer(raw)
                    ok, why = answer_ok(ans, t["question"], t["term"] if kind != "contrast" else None)
                    if not ok:
                        reject[why] += 1
                        continue
                    item = {
                        "messages": [
                            {"role": "system", "content": SYSTEM},
                            {"role": "user", "content": t["question"]},
                            {"role": "assistant", "content": ans},
                        ],
                        "subject": t.get("subject") or "其他",
                        "source": f"synth_{kind}",
                        "seed": f"{t['src']}|{t['term']}",
                        "kind": kind,
                    }
                    handles[kind].write(json.dumps(item, ensure_ascii=False) + "\n")
                    stats[kind] += 1
            done_n = min(i + args.batch_size, len(todo))
            if (i // args.batch_size) % 10 == 0:
                el = time.time() - t0
                rate = done_n / max(1e-6, el / 60)
                print(f"  [{done_n}/{len(todo)}] 合格 {sum(stats.values())} "
                      f"({dict(stats)}) | {rate:.1f} 条/分 | 剩余 {elapsed_eta(done_n, len(todo), rate)}",
                      flush=True)
            # 每 20 批落盘一次，避免进程被杀丢结果
            if (i // args.batch_size) % 20 == 0:
                for h in handles.values():
                    h.flush()
    finally:
        for h in handles.values():
            h.close()

    print("\n" + "=" * 70)
    print(f"合成完成：合格 {sum(stats.values())} 条")
    for k, v in stats.most_common():
        print(f"   {k:<14} {v}")
    if reject:
        print("质检拒绝原因:")
        for k, v in reject.most_common(8):
            print(f"   {k:<20} {v}")
    print(f"\n产物: {out_dir}")
    print("下一步：合并 v3 + 合成 → v4 数据集，再跑训练")
    return 0


def elapsed_eta(done: int, total: int, rate_per_min: float) -> str:
    if rate_per_min <= 0:
        return "-"
    return f"{(total - done) / rate_per_min:.0f} 分钟"


if __name__ == "__main__":
    raise SystemExit(main())