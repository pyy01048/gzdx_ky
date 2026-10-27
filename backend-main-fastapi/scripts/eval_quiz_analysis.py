# -*- coding: utf-8 -*-
"""题库解析模型对照评测：base vs LoRA（答案准确率 + 解析质量 LLM 盲评）。

评测集固定为 `data/lora_finetune_quiz_v1/holdout.json`（50 题，训练/验证均未见过），
题目、选项、答案、参考解析都来自清洗后的题库。两类指标：

1. 答案准确率：从模型输出里抽 `答案：X`，与标准答案字母集合精确比对；
2. 解析质量：由**第三方裁判模型**（默认 qwen3:8b）在不知道来源模型的前提下，
   对照参考解析按 1-5 分打分（考点/步骤/正确性/易错点）。

用法：
    python scripts/eval_quiz_analysis.py --models qwen25-3b-base:latest,kaoyan-analysis-v1
    python scripts/eval_quiz_analysis.py --models kaoyan-analysis-v1 --no-judge

产出：temp/quiz_analysis_eval.json（逐题原始输出）+
      exports/quiz_analysis_eval_report.md（对照表）+
      eval_runs kind=quiz_analysis（每个模型一行）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

#: 本机 shell 里的 OLLAMA_HOST 可能是 0.0.0.0 或缺失协议头，urllib 会直接报
#: unknown url type；统一补协议并换回回环地址。
from utils.ollama_host import resolve_ollama_host as _resolve_ollama_host

OLLAMA_HOST = _resolve_ollama_host()
DATA_DIR = os.path.join(BASE_DIR, "data", "lora_finetune_quiz_v1")
HOLDOUT_PATH = os.path.join(DATA_DIR, "holdout.json")
TEMP_DIR = os.environ.get("TEMP_DIR", os.path.join(BASE_DIR, "temp"))
OUT_JSON = os.path.join(TEMP_DIR, "quiz_analysis_eval.json")
OUT_MD = os.path.join(BASE_DIR, "exports", "quiz_analysis_eval_report.md")

SYSTEM_PROMPT = (
    "你是一位考研辅导老师。回答时先给出正确选项，再给出解析；"
    "解析先点明考点，再写关键步骤，最后指出易错点。"
    "不要复述题干原文；不确定时明确说明，不要编造。"
)

JUDGE_SYSTEM = (
    "你是考研阅卷老师。给你一道客观题、标准答案、参考解析，以及一份学生解析。"
    "只评价解析质量，不看学生选的答案对错。按 1-5 打分："
    "5=考点准确且步骤完整、结论正确；4=基本正确但略简；3=方向对但有缺漏；"
    "2=有明显错误或空泛；1=答非所问/复述题干/编造。"
    "只输出 JSON：{\"score\": 整数, \"reason\": \"不超过30字\"}。"
)

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

ANSWER_RE = re.compile(r"答案[：:]\s*[*_`\s]*([A-H](?:\s*[,，、/和]?\s*[A-H])*)", re.I)
EXPL_RE = re.compile(r"解析[：:]\s*[*_`\s]*(.+)", re.S)
LETTERS_RE = re.compile(r"[A-H]")


def chat(model: str, system: str, user: str, *, temperature: float = 0.1,
         timeout: float = 300.0, think: bool | None = None,
         num_ctx: int = 1536, num_predict: int = 160) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": False,
        "keep_alive": "5m",
        "options": {"temperature": temperature, "num_ctx": num_ctx,
                    "num_predict": num_predict},
    }
    if think is not None:
        payload["think"] = think
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with _OPENER.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return ((data.get("message") or {}).get("content") or "").strip()


def options_text(options) -> str:
    lines = []
    for opt in options or []:
        if isinstance(opt, dict):
            key = str(opt.get("key", "")).strip()
            text = str(opt.get("text", "")).strip()
            if key:
                lines.append(f"{key}. {text}")
        elif isinstance(opt, str):
            lines.append(opt)
    return "\n".join(lines)


def render_question(case: dict) -> str:
    return (
        f"【科目】{case.get('subject') or '未分类'}\n"
        f"【题目】{case.get('content') or ''}\n"
        f"【选项】\n{options_text(case.get('options'))}"
    )


def gold_set(case: dict) -> set:
    return set(LETTERS_RE.findall(str(case.get("answer") or "").upper()))


def parse_output(text: str) -> tuple[set, str, bool]:
    """返回 (答案字母集合, 解析正文, 是否按格式作答)。"""
    m = ANSWER_RE.search(text[:300])
    if m:
        pred = set(LETTERS_RE.findall(m.group(1).upper()))
    else:
        head = re.sub(r"【.*?】", "", text[:80])
        pred = set(LETTERS_RE.findall(head.upper())[:1])
    em = EXPL_RE.search(text)
    expl = em.group(1).strip() if em else ""
    formatted = bool(m) and len(expl) >= 30
    return pred, expl, formatted


def judge_score(judge_model: str, case: dict, model_out: str,
                timeout: float) -> tuple[int | None, str]:
    user = (
        f"题目：{case.get('content') or ''}\n"
        f"选项：\n{options_text(case.get('options'))}\n"
        f"标准答案：{case.get('answer')}\n"
        f"参考解析：{case.get('analysis') or ''}\n\n"
        f"学生解析：\n{model_out[:2200]}\n/no_think"
    )
    try:
        raw = chat(judge_model, JUDGE_SYSTEM, user, temperature=0.0,
                   timeout=timeout, think=False, num_ctx=3072, num_predict=192)
    except Exception as e:  # noqa: BLE001
        return None, f"裁判调用失败: {str(e)[:60]}"
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            score = int(obj.get("score"))
            if 1 <= score <= 5:
                return score, str(obj.get("reason") or "")[:60]
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    sm = re.search(r"\b([1-5])\b", raw)
    return (int(sm.group(1)) if sm else None), raw[:60].replace("\n", " ")


def fingerprint(cases: list[dict]) -> str:
    blob = "\n".join(f"{c.get('id')}:{c.get('content')}" for c in cases)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def unload(model: str) -> None:
    """显式卸载，避免 3B 与被测/裁判模型同时驻留 8GB 显存。"""
    try:
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=json.dumps({"model": model, "keep_alive": 0}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with _OPENER.open(req, timeout=30) as resp:
            resp.read()
    except Exception:  # noqa: BLE001
        pass


def run_model(model: str, cases: list[dict], *, timeout: float) -> dict:
    records = []
    correct = refused = formatted = 0
    per_subject = defaultdict(lambda: [0, 0])
    t0 = time.time()
    for i, case in enumerate(cases, 1):
        try:
            out = chat(model, SYSTEM_PROMPT, render_question(case), timeout=timeout)
        except Exception as e:  # noqa: BLE001
            out = ""
            print(f"  [!] {model} 第 {i} 题调用失败: {str(e)[:100]}")
        pred, expl, is_fmt = parse_output(out)
        gold = gold_set(case)
        ok = bool(gold) and pred == gold
        correct += int(ok)
        formatted += int(is_fmt)
        refused += int(not pred)
        per_subject[case.get("subject") or "其他"][0] += int(ok)
        per_subject[case.get("subject") or "其他"][1] += 1
        records.append({
            "id": case.get("id"), "subject": case.get("subject"),
            "gold": "".join(sorted(gold)), "pred": "".join(sorted(pred)),
            "correct": ok, "formatted": is_fmt, "output": out,
            "judge_score": None, "judge_reason": None,
        })
        if i % 10 == 0 or i == len(cases):
            print(f"  {model}: {i}/{len(cases)} acc={correct / i:.3f}", flush=True)

    answer_secs = time.time() - t0
    unload(model)
    return {
        "model": model,
        "n": len(records),
        "accuracy": round(correct / max(1, len(records)), 4),
        "refusal_rate": round(refused / max(1, len(records)), 4),
        "format_rate": round(formatted / max(1, len(records)), 4),
        "avg_judge_score": None,
        "judge_n": 0,
        "per_subject": {s: {"acc": round(v[0] / v[1], 4), "n": v[1]}
                        for s, v in sorted(per_subject.items())},
        "answer_secs": round(answer_secs, 1),
        "judge_secs": 0.0,
        "records": records,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="题库解析模型对照评测")
    ap.add_argument("--models", required=True, help="逗号分隔，如 base,lora")
    ap.add_argument("--holdout", default=HOLDOUT_PATH)
    ap.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", "qwen3:8b"))
    ap.add_argument("--no-judge", action="store_true", help="跳过解析质量盲评")
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    with open(args.holdout, encoding="utf-8") as f:
        cases = json.load(f)
    cases = [c for c in cases if gold_set(c)]
    if not cases:
        print("评测集为空或答案都解析不出来")
        return 1
    print(f"评测集 {len(cases)} 题，指纹 {fingerprint(cases)}；"
          f"模型: {models}；裁判: {'无' if args.no_judge else args.judge_model}")

    report = {"holdout": args.holdout, "n": len(cases),
              "fingerprint": fingerprint(cases),
              "judge_model": None if args.no_judge else args.judge_model,
              "models": {}}
    for model in models:
        report["models"][model] = run_model(model, cases, timeout=args.timeout)

    if not args.no_judge:
        total = sum(len(m["records"]) for m in report["models"].values())
        done = 0
        for model, m in report["models"].items():
            t1 = time.time()
            for case, rec in zip(cases, m["records"]):
                score, reason = judge_score(args.judge_model, case, rec["output"],
                                            args.timeout)
                rec["judge_score"] = score
                rec["judge_reason"] = reason
                done += 1
                if done % 10 == 0 or done == total:
                    print(f"  judge[{args.judge_model}]: {done}/{total}", flush=True)
            m["judge_secs"] = round(time.time() - t1, 1)
            scores = [r["judge_score"] for r in m["records"]
                      if r["judge_score"] is not None]
            m["avg_judge_score"] = (round(sum(scores) / len(scores), 3)
                                    if scores else None)
            m["judge_n"] = len(scores)
        unload(args.judge_model)

    print("\n===== 对照表 =====")
    print(f"{'模型':<32}{'答案准确率':>10}{'格式合规':>10}{'解析均分':>10}{'拒答':>8}")
    for model, m in report["models"].items():
        score = f"{m['avg_judge_score']:.2f}" if m["avg_judge_score"] is not None else "—"
        print(f"{model:<32}{m['accuracy']:>10.3f}{m['format_rate']:>10.3f}"
              f"{score:>10}{m['refusal_rate']:>8.1%}")

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("# 题库解析模型评测（holdout 50 题）\n\n")
        f.write(f"- 数据集指纹：`{report['fingerprint']}`\n")
        f.write(f"- 解析质量裁判：{report['judge_model'] or '未启用'}\n\n")
        f.write("| 模型 | 答案准确率 | 格式合规率 | 解析均分(1-5) | 拒答率 | 耗时 |\n")
        f.write("| :--- | ---: | ---: | ---: | ---: | ---: |\n")
        for model, m in report["models"].items():
            score = f"{m['avg_judge_score']:.2f}" if m["avg_judge_score"] is not None else "—"
            f.write(f"| {model} | {m['accuracy']:.3f} | {m['format_rate']:.3f} | "
                    f"{score} | {m['refusal_rate']:.1%} | {m['answer_secs']:.0f}s |\n")
        f.write("\n## 分学科\n\n")
        for model, m in report["models"].items():
            f.write(f"### {model}\n\n")
            for s, v in m["per_subject"].items():
                f.write(f"- {s}: {v['acc']:.3f}（{v['n']} 题）\n")
            f.write("\n")
    print(f"报告：{OUT_JSON}\n      {OUT_MD}")

    try:
        from database import SessionLocal
        from services.eval_store import record_eval_run

        db = SessionLocal()
        try:
            for model, m in report["models"].items():
                run_id = record_eval_run(
                    "quiz_analysis",
                    arm=model,
                    metrics={k: v for k, v in m.items() if k != "records"},
                    primary_metric=m["accuracy"],
                    n_samples=m["n"],
                    fingerprint=report["fingerprint"],
                    report_path=OUT_JSON,
                    notes=(f"解析均分={m['avg_judge_score']}（裁判 {report['judge_model']}）；"
                           f"格式合规={m['format_rate']}"),
                    db=db,
                )
                print(f"入库：eval_runs #{run_id} {model}" if run_id else f"入库失败 {model}")
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        print(f"eval_runs 入库异常（忽略）: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
