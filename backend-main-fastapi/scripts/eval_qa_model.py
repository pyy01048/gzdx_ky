# -*- coding: utf-8 -*-
"""答疑模型自动评测（docx/14 阶段 C，补 README 声称却缺失的 eval_qa_model）。

目的：**用数据裁决** 本地微调（1.5B/3B）是否值得继续、RAG 增强贡献多少 ——
00 号文档称 3B、12 号实测 1.5B，两说并存且从未量化。

题源：`quiz_questions` 客观题（single/multiple/judge，有答案有选项），
按 subject 分层抽样（默认 300 题）。判分：正则抽选项字母，多选全对才得分；
`--judge` 追加 LLM 复核"实质等价正确"（如多选漏选的宽松判定）。
`--with-rag` 对每题拼 hybrid_search top-3 上下文，同题跑"裸/带RAG"两列，
把模型问题与检索问题分开归因。

用法：
    python scripts/eval_qa_model.py --models qwen2.5:1.5b-instruct,kaoyan-assistant
    python scripts/eval_qa_model.py --models kaoyan-assistant --with-rag --n 100
产出：控制台对照表 + TEMP/eval_qa_result.json + exports/eval_qa_report.md
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import sys
import time
import urllib.request

# Windows 控制台默认 GBK，报表里的 ✓/中文会直接 UnicodeEncodeError 崩掉整轮评测
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OUT_JSON = os.path.join(os.environ.get("TEMP_DIR", os.path.join(BASE_DIR, "temp")),
                        "eval_qa_result.json")
OUT_MD = os.path.join(BASE_DIR, "exports", "eval_qa_report.md")

SYSTEM = "你是考研答疑助教。先给出答案选项字母，再给一行简短理由。"


def _build_opener():
    """绕代理 —— 本机 Ollama 被 http_proxy 劫持是实测踩过的坑（同 kp_extract）。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


_OPENER = _build_opener()


def chat(model: str, prompt: str, *, timeout: float = 120.0) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 4096},
    }).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_HOST}/v1/chat/completions",
                                 data=payload, headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


def build_eval_set(db, n: int, per_subject_cap: int, seed: int = 42) -> list[dict]:
    """客观题分层抽样：有选项、有答案、题干完整。"""
    from models import QuizQuestion

    rng = random.Random(seed)
    q = db.query(QuizQuestion).filter(
        QuizQuestion.question_type.in_(("single", "multiple", "judge")),
        QuizQuestion.answer.isnot(None), QuizQuestion.answer != "",
        QuizQuestion.content.isnot(None),
    )
    by_subj: dict = defaultdict(list)
    for row in q.yield_per(1000):
        text = (row.content or "").strip()
        if len(text) < 8:
            continue
        opts = row.options
        if row.question_type != "judge" and (not opts or len(opts) < 2):
            continue
        by_subj[row.subject or "其他"].append({
            "id": row.id, "subject": row.subject or "其他",
            "type": row.question_type, "content": text[:800],
            "options": opts or [], "answer": str(row.answer).strip(),
        })
    cases: list[dict] = []
    subjects = sorted(by_subj)
    cap = max(1, per_subject_cap)
    while len(cases) < n and subjects:
        nxt = []
        for s in subjects:
            pool = by_subj[s]
            if not pool:
                continue
            cases.append(pool.pop(rng.randrange(len(pool))))
            if pool and len([c for c in cases]) < n:
                nxt.append(s)
            if len(cases) >= n:
                break
        subjects = nxt
    return cases[:n]


def render_question(c: dict, rag_ctx: str = "") -> str:
    lines = [f"【{c['subject']}·{'多选题' if c['type']=='multiple' else '判断题' if c['type']=='judge' else '单选题'}】{c['content']}"]
    if c["type"] == "judge":
        lines.append("A. 正确\nB. 错误")
    else:
        for i, opt in enumerate(c["options"]):
            letter = chr(65 + i)
            txt = opt if isinstance(opt, str) else json.dumps(opt, ensure_ascii=False)
            if not re.match(r"^\s*[A-H][．.、）)]", txt):
                txt = f"{letter}．{txt}"
            lines.append(txt[:200])
    if rag_ctx:
        lines.append(f"参考资料：\n{rag_ctx[:1200]}")
    lines.append("请只作答（单选一个字母；多选列出全部字母；判断 A=正确 B=错误）：")
    return "\n".join(lines)


_LETTER_RE = re.compile(r"[A-H]")
_JUDGE_RE = re.compile(r"(正确|错误|对|错|√|×|True|False)")


def extract_answer(model_out: str, qtype: str) -> set:
    if not model_out:
        return set()
    head = model_out[:120]
    if qtype == "judge":
        m = _JUDGE_RE.search(head)
        if m:
            return {"A"} if m.group(1) in ("正确", "对", "√", "True") else {"B"}
    letters = _LETTER_RE.findall(head.upper())
    if qtype == "multiple":
        return set(letters[:8]) if letters else set()
    return {letters[0]} if letters else set()


def _norm(txt: str) -> str:
    return re.sub(r"[\s，。、；：（）()【】\[\]\"'“”‘’,.;:!?！？]", "", str(txt or "")).lower()


def _opt_pairs(options) -> list:
    """把 options（list 或 dict）归一成 [(字母, 文本)]。"""
    pairs = []
    if isinstance(options, dict):
        for k, v in options.items():
            mm = re.match(r"^[\s(（【]*([A-Ha-h])", str(k))
            pairs.append((str(mm.group(1)).upper() if mm else chr(65 + len(pairs)), str(v)))
    elif isinstance(options, list):
        for i, opt in enumerate(options):
            s = opt if isinstance(opt, str) else json.dumps(opt, ensure_ascii=False)
            mm = re.match(r"^\s*[\(（【]?([A-Ha-h])[\)）.．、）:：]", s)
            letter = mm.group(1).upper() if mm else chr(65 + i)
            pairs.append((letter, s))
    return pairs


def gold_set(c: dict) -> set:
    """标准答案 → 选项字母集合。

    题库 answer 字段实测有三种存法：字母（"B"）、符号（"√"/"×"）、
    **正确选项全文**。前两种直接映射；第三种反查选项文本。
    解析不出返回空集（调用方把该题剔除出分母 —— 判不了的题不算模型错，
    否则 accuracy 被题库脏数据系统性压低）。
    """
    a = str(c.get("answer") or "").strip()
    if not a:
        return set()
    if c["type"] == "judge":
        if a in ("对", "正确", "√", "True", "T", "A") or a.startswith(("正确", "对")):
            return {"A"}
        if a in ("错", "错误", "×", "✗", "False", "F", "B") or a.startswith(("错误", "错")):
            return {"B"}
        return set()
    letters = re.findall(r"[A-H]", a.upper())
    if len(a) <= 4 and letters:                    # "B" / "ABD" / "B．"
        return set(letters)
    key = _norm(re.sub(r"^[A-H][．.、）):：]\s*", "", a.upper()))
    for letter, txt in _opt_pairs(c.get("options")):
        t = _norm(re.sub(r"^\s*[\(（【]?[A-Ha-h][\)）.．、:：]\s*", "", txt))
        if t and (t == key or (len(key) >= 8 and (key in t or t in key))):
            return {letter}
    return set()


def rag_context(db, c: dict) -> str:
    try:
        from services import search_service
        from services.embedding_service import generate_local_embeddings, is_local_model_available

        qv = None
        if is_local_model_available():
            qv = generate_local_embeddings([c["content"][:500]])[0]
        hits = search_service.hybrid_search(db, c["content"][:300], query_vec=qv,
                                            limit=3, subject=c["subject"])
        return "\n---\n".join((h.get("content") or h.get("text") or "")[:400] for h in hits)
    except Exception:  # noqa: BLE001
        return ""


def judge_second_pass(model: str, c: dict, out: str, gold: set, pred: set) -> bool:
    """LLM 复核：模型答案与标准答案不一致时，判'实质等价正确'与否。"""
    try:
        verdict = chat(model, (
            f"题目：{c['content'][:400]}\n标准答案：{''.join(sorted(gold))}\n"
            f"学生作答：{out[:200]}\n问：学生答案与标准答案是否实质等价（仅表述差异/多解释不算错，"
            "漏选错选算错）？只回答 对 或 错。"), timeout=60)
        return bool(re.search(r"^[\s]*对", verdict))
    except Exception:  # noqa: BLE001
        return False


def train_fingerprints(path: str) -> str:
    """把训练集题干归一化拼成一个大字符串，用于判定评测题是否"见过"。

    训练数据（build_qa_dataset.py）和评测集都取自 quiz_questions，
    不去重就会把训练过的题再考一遍 —— 微调模型的准确率会被背题系统性抬高。
    所以报表必须把 seen / unseen 分开算，只看 unseen 才是真实能力。
    """
    if not path or not os.path.exists(path):
        return ""
    blob = []
    for name in ("train.jsonl", "val.jsonl"):
        p = os.path.join(path, name) if os.path.isdir(path) else path
        if not os.path.exists(p):
            continue
        with io.open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                msgs = json.loads(line).get("messages") or []
                for m in msgs:
                    if m.get("role") == "user":
                        blob.append(_norm(m.get("content") or ""))
    return "\x00".join(blob)


def main() -> int:
    ap = argparse.ArgumentParser(description="答疑模型自动评测")
    ap.add_argument("--models", default="kaoyan-assistant",
                    help="逗号分隔，如 qwen2.5:1.5b-instruct,kaoyan-assistant")
    ap.add_argument("--n", type=int, default=300, help="评测题数")
    ap.add_argument("--per-subject", type=int, default=60, help="单科题数上限")
    ap.add_argument("--with-rag", action="store_true", help="追加 裸 vs RAG 对照列")
    ap.add_argument("--judge", action="store_true", help="错误答案 LLM 复核实质等价")
    ap.add_argument("--train-jsonl", default="",
                    help="训练集目录或文件，用于把评测题分成见过/没见过两栏")
    ap.add_argument("--holdout", action="store_true",
                    help="只考训练集里没出现过的题（微调模型不能靠背题拿分）")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.holdout and not args.train_jsonl:
        print("--holdout 需要同时给 --train-jsonl（否则无法判断是否见过）")
        return 2
    from database import SessionLocal
    db = SessionLocal()
    try:
        # holdout 只留没见过的题，而已见率实测 ~81% → 必须超采样才够题量
        pool_mult = 16 if args.holdout else 1
        cases = build_eval_set(db, args.n * pool_mult, args.per_subject * pool_mult)
        raw_n = len(cases)
        cases = [c for c in cases if gold_set(c)]
        if raw_n != len(cases):
            print(f"剔除答案无法解析的题 {raw_n-len(cases)} 道（answer 字段脏数据）")
        if not cases:
            print("题库没有可判分的客观题"); return 1
        blob = train_fingerprints(args.train_jsonl)
        if blob:
            for c in cases:
                c["seen"] = _norm(c["content"])[:40] in blob
            n_seen = sum(1 for c in cases if c["seen"])
            print(f"训练集重叠检查：{n_seen}/{len(cases)} 题的题干出现在训练集里"
                  f"（准确率请看 unseen 栏）")
            if args.holdout:
                cases = [c for c in cases if not c["seen"]][:args.n]
                print(f"[holdout] 只考训练集没出现过的题：{len(cases)} 道")
        print(f"评测集 {len(cases)} 题，覆盖 "
              f"{len(set(c['subject'] for c in cases))} 科；模型: {models}"
              f"{' +RAG对照' if args.with_rag else ''}")

        report: dict = {"cases": len(cases), "models": {}}
        rows = []
        for model in models:
            modes = [("裸", False)] + ([("RAG", True)] if args.with_rag else [])
            for mode, use_rag in modes:
                correct = refused = 0
                ctx_hit = ctx_len = 0
                split = {"seen": [0, 0], "unseen": [0, 0]}
                ctx_hit = ctx_len = 0
                letter_dist = Counter()
                per_subj = defaultdict(lambda: [0, 0])
                t0 = time.time()
                for i, c in enumerate(cases, 1):
                    ctx = rag_context(db, c) if use_rag else ""
                    if use_rag:
                        ctx_hit += int(bool(ctx.strip()))
                        ctx_len += len(ctx)
                    prompt = render_question(c, rag_ctx=ctx)
                    try:
                        out = chat(model, prompt, timeout=args.timeout)
                    except Exception as e:  # noqa: BLE001
                        out = ""
                        if i <= 3:
                            print(f"  [!] 调用失败: {str(e)[:100]}")
                    gold, pred = gold_set(c), extract_answer(out, c["type"])
                    for L in pred:
                        letter_dist[L] += 1
                    ok = bool(gold) and pred == gold
                    if not ok and args.judge and out and judge_second_pass(model, c, out, gold, pred):
                        ok = True
                    if not pred:
                        refused += 1
                    per_subj[c["subject"]][0] += int(ok)
                    per_subj[c["subject"]][1] += 1
                    correct += int(ok)
                    if "seen" in c:
                        bucket = "seen" if c["seen"] else "unseen"
                        split[bucket][0] += int(ok)
                        split[bucket][1] += 1
                    if i % 50 == 0:
                        print(f"  {model} [{mode}] {i}/{len(cases)} acc={correct/i:.3f}")
                acc = correct / len(cases)
                tag = f"{model}·{mode}"
                if use_rag:
                    report.setdefault("rag_health", {})[tag] = {
                        "ctx_hit_rate": round(ctx_hit / len(cases), 4),
                        "avg_ctx_chars": round(ctx_len / max(1, ctx_hit), 1),
                    }
                    if ctx_hit < 0.5 * len(cases):
                        print(f"  [!] {tag} 只有 {ctx_hit}/{len(cases)} 题检索到参考资料，"
                              f"RAG 列不可与裸答列直接比较")
                report["models"][tag] = {
                    "accuracy": round(acc, 4),
                    "unseen": ({
                        "accuracy": round(split["unseen"][0] / split["unseen"][1], 4),
                        "n": split["unseen"][1],
                        "seen_accuracy": (round(split["seen"][0] / split["seen"][1], 4)
                                          if split["seen"][1] else None),
                        "seen_n": split["seen"][1],
                    } if split["unseen"][1] else None),
                    "empty_or_refused_rate": round(refused / len(cases), 4),
                    "answer_letter_dist": dict(sorted(letter_dist.items(), key=lambda kv: -kv[1])),
                    "per_subject": {s: {"acc": round(v[0] / v[1], 4), "n": v[1]}
                                    for s, v in sorted(per_subj.items())},
                    "elapsed_s": round(time.time() - t0, 1),
                }
                rows.append((tag, acc, refused / len(cases),
                             report["models"][tag]["unseen"]))
                dist_str = " ".join(f"{k}:{v}" for k, v in
                                    sorted(letter_dist.items(), key=lambda kv: -kv[1])[:5])
                un = report["models"][tag]["unseen"]
                extra = f"  未见题 {un['accuracy']:.3f}(n={un['n']})" if un else ""
                if un and un["seen_n"]:
                    extra += f" / 见过 {un['seen_accuracy']:.3f}(n={un['seen_n']})"
                print(f"✅ {tag}: Accuracy {acc:.3f}  空白/拒答 {refused/len(cases):.1%}"
                      f"  作答分布[{dist_str}]{extra}")

        print("\n===== 对照表 =====")
        print(f"{'模型·模式':<38}{'Accuracy':>10}{'未见题':>10}{'拒答率':>8}")
        for tag, a, r, un in rows:
            print(f"{tag:<38}{a:>10.3f}{(un['accuracy'] if un else float('nan')):>10.3f}"
                  f"{r:>8.1%}")

        os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
        with open(OUT_JSON, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
        with open(OUT_MD, "w", encoding="utf-8") as f:
            f.write("# 答疑模型评测报告\n\n| 模型·模式 | Accuracy | 未见题 Accuracy | 空白/拒答率 |\n| :--- | :--- | :--- | :--- |\n")
            for tag, a, r, un in rows:
                ua = f"{un['accuracy']:.3f}" if un else "—"
                f.write(f"| {tag} | {a:.3f} | {ua} | {r:.1%} |\n")
            f.write("\n## 分学科\n\n")
            for tag in report["models"]:
                f.write(f"### {tag}\n\n")
                for s, v in report["models"][tag]["per_subject"].items():
                    if v["n"]:
                        f.write(f"- {s}: {v['acc']:.3f}（{v['n']} 题）\n")
                f.write("\n")
        print(f"报告：{OUT_JSON}\n      {OUT_MD}")

        # 入库：eval_runs（docx/14 口径，趋势页读这张表）。主指标优先取未见题准确率，
        # 没有 holdout 时退回全量 accuracy——见过题的分数不能当趋势。
        try:
            from services.eval_store import file_fingerprint, record_eval_run, text_fingerprint

            parts = ([file_fingerprint(args.train_jsonl)] if args.train_jsonl else [])
            parts.append("holdout" if args.holdout else "full")
            parts.extend(str(c.get("content") or "")[:200] for c in cases)
            unseen = [(tag, u["accuracy"]) for tag, _, _, u in rows if u and u.get("n")]
            if unseen:
                primary = max(v for _, v in unseen)
                note = f"主指标=未见题最高 accuracy（{max(unseen, key=lambda t: t[1])[0]}）"
            else:
                primary = max((a for _, a, _, _ in rows), default=0.0)
                note = "主指标=全量最高 accuracy（本轮无 holdout，含见过题）"
            run_id = record_eval_run(
                "qa", arm=",".join(models), metrics=report, primary_metric=primary,
                n_samples=len(cases), fingerprint=text_fingerprint(parts),
                report_path=OUT_JSON, notes=note, db=db,
            )
            print(f"入库：eval_runs #{run_id}" if run_id else "入库失败（详见日志，报告文件仍在）")
        except Exception as e:  # noqa: BLE001
            print(f"eval_runs 入库异常（忽略）: {e}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
