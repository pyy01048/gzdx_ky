# -*- coding: utf-8 -*-
"""用本地微调模型 kaoyan-analysis-v1 批量生成缺解析题目的解析。

数据源：PostgreSQL（quiz_questions，386 题中 52 题缺解析且有答案）。
生成后默认只落盘到 temp/（dry-run），人工抽检质量后再 --apply 写库。

用法：
    python scripts/backfill_analysis_with_model.py                 # dry-run
    python scripts/backfill_analysis_with_model.py --apply         # 写库
    python scripts/backfill_analysis_with_model.py --model qwen3:8b  # 换模型
"""
from __future__ import annotations

import argparse
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

from utils.ollama_host import resolve_ollama_host as _resolve_ollama_host

OLLAMA_HOST = _resolve_ollama_host()
TEMP_DIR = os.path.join(BASE_DIR, "temp")
OUT_JSON = os.path.join(TEMP_DIR, "backfill_analysis_dryrun.json")
OUT_MD = os.path.join(BASE_DIR, "exports", "backfill_analysis_dryrun.md")

SYSTEM_PROMPT = (
    "你是一位考研辅导老师。回答时先给出正确选项，再给出解析；"
    "解析先点明考点，再写关键步骤，最后指出易错点。"
    "不要复述题干原文；不确定时明确说明，不要编造。"
    "必须按以下格式输出：\n"
    "答案：X\n"
    "解析：……（不少于40字）"
)

ANSWER_RE = re.compile(r"答案[：:]\s*[*_`\s]*([A-H](?:\s*[,，、/和]?\s*[A-H])*)", re.I)
EXPL_RE = re.compile(r"解析[：:]\s*[*_`\s]*(.+)", re.S)
LETTERS_RE = re.compile(r"[A-H]")

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def chat(model: str, system: str, user: str, *, temperature: float = 0.1,
         timeout: float = 300.0, num_ctx: int = 2048, num_predict: int = 400) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": False,
        "keep_alive": "5m",
        "options": {"temperature": temperature, "num_ctx": num_ctx,
                    "num_predict": num_predict},
    }
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with _OPENER.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return ((data.get("message") or {}).get("content") or "").strip()


def options_text(options) -> str:
    if not options:
        return ""
    lines = []
    for opt in options:
        if isinstance(opt, dict):
            key = str(opt.get("key", "")).strip()
            text = str(opt.get("text", "")).strip()
            if key:
                lines.append(f"{key}. {text}")
        elif isinstance(opt, str):
            lines.append(opt)
    return "\n".join(lines)


def render_question(case: dict, anchor_answer: bool = False) -> str:
    base = (
        f"【科目】{case.get('subject') or '未分类'}\n"
        f"【题目】{case.get('content') or ''}\n"
        f"【选项】\n{options_text(case.get('options'))}"
    )
    if anchor_answer:
        return base + f"\n【正确答案】{case.get('answer')}\n请解释为什么选这个答案，并给出完整解析。"
    return base


def get_system_prompt(anchor_answer: bool = False) -> str:
    if anchor_answer:
        return (
            "你是一位考研辅导老师。根据给出的正确答案，解释该题为什么选这个答案，"
            "写出解析：先点明考点，再写关键步骤，最后指出易错点。"
            "不要复述题干原文；不要编造。"
            "必须按以下格式输出：\n"
            "答案：X\n"
            "解析：……（不少于40字）"
        )
    return SYSTEM_PROMPT


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


def fetch_missing() -> list[dict]:
    import psycopg
    conn = psycopg.connect(
        host="127.0.0.1", port=5432, user="kaoyan",
        password="kaoyan_dev_2026", dbname="kaoyan")
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, subject, chapter, question_type, difficulty,
               content, options, answer, source_kind, source_label, paper, year
        FROM quiz_questions
        WHERE analysis IS NULL OR length(trim(analysis)) < 10
        ORDER BY id
        """
    )
    cols = [d[0] for d in cur.description]
    rows = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        opts = d.get("options")
        if isinstance(opts, str):
            try:
                opts = json.loads(opts)
            except Exception:
                opts = []
        d["options"] = opts or []
        rows.append(d)
    conn.close()
    return rows


def unload(model: str) -> None:
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


def main() -> int:
    ap = argparse.ArgumentParser(description="批量生成缺解析题目的解析")
    ap.add_argument("--model", default="kaoyan-analysis-v1:latest")
    ap.add_argument("--anchor-answer", action="store_true",
                    help="以数据库标准答案为锚，让模型解释该答案（推荐，保证解析与答案一致）")
    ap.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args()

    cases = fetch_missing()
    anchor = args.anchor_answer
    system = get_system_prompt(anchor)
    print(f"缺解析题目：{len(cases)} 道；模型：{args.model}；"
          f"模式：{'写库' if args.apply else 'dry-run'}；"
          f"锚定答案：{'是' if anchor else '否'}")

    records = []
    correct = formatted = refused = 0
    per_subject = defaultdict(lambda: [0, 0])
    t0 = time.time()
    for i, case in enumerate(cases, 1):
        try:
            out = chat(args.model, system, render_question(case, anchor),
                       timeout=args.timeout)
        except Exception as e:  # noqa: BLE001
            out = ""
            print(f"  [!] #{case['id']} 调用失败: {str(e)[:100]}", flush=True)
        pred, expl, is_fmt = parse_output(out)
        gold = gold_set(case)
        ok = bool(gold) and pred == gold
        correct += int(ok)
        formatted += int(is_fmt)
        refused += int(not pred)
        per_subject[case.get("subject") or "其他"][0] += int(ok)
        per_subject[case.get("subject") or "其他"][1] += 1
        records.append({
            "id": case.get("id"),
            "subject": case.get("subject"),
            "gold": "".join(sorted(gold)),
            "pred": "".join(sorted(pred)),
            "correct": ok,
            "formatted": is_fmt,
            "analysis": expl,
            "raw_output": out,
        })
        if i % 10 == 0 or i == len(cases):
            print(f"  {i}/{len(cases)} acc={correct / i:.3f} "
                  f"format={formatted / i:.3f}", flush=True)

    elapsed = round(time.time() - t0, 1)
    unload(args.model)

    report = {
        "model": args.model,
        "n": len(records),
        "accuracy": round(correct / max(1, len(records)), 4),
        "format_rate": round(formatted / max(1, len(records)), 4),
        "refusal_rate": round(refused / max(1, len(records)), 4),
        "elapsed_secs": elapsed,
        "per_subject": {s: {"acc": round(v[0] / v[1], 4), "n": v[1]}
                        for s, v in sorted(per_subject.items())},
        "records": records,
    }

    os.makedirs(TEMP_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(f"# 缺解析题目批量生成（dry-run）\n\n")
        f.write(f"- 模型：`{args.model}`\n")
        f.write(f"- 样本：{len(records)} 题\n")
        f.write(f"- 答案准确率：{report['accuracy']:.3f}\n")
        f.write(f"- 格式合规率：{report['format_rate']:.3f}\n")
        f.write(f"- 拒答率：{report['refusal_rate']:.3f}\n")
        f.write(f"- 耗时：{elapsed}s\n\n")
        f.write("## 分学科\n\n")
        for s, v in report["per_subject"].items():
            f.write(f"- {s}: {v['acc']:.3f}（{v['n']} 题）\n")
        f.write("\n## 逐题结果\n\n")
        f.write("| ID | 科目 | 标准答案 | 模型答案 | 一致 | 格式 | 解析 |\n")
        f.write("| --: | --- | :--: | :--: | :--: | :--: | --- |\n")
        for r in records:
            ana = (r["analysis"] or "")[:60].replace("|", "/").replace("\n", " ")
            f.write(f"| {r['id']} | {r['subject']} | {r['gold']} | {r['pred']} "
                    f"| {'✓' if r['correct'] else '✗'} "
                    f"| {'✓' if r['formatted'] else '✗'} | {ana} |\n")

    print(f"\n===== 汇总 =====")
    print(f"答案准确率: {report['accuracy']:.3f}  ({correct}/{len(records)})")
    print(f"格式合规率: {report['format_rate']:.3f}  ({formatted}/{len(records)})")
    print(f"拒答率:     {report['refusal_rate']:.3f}")
    print(f"dry-run 报告: {OUT_JSON}\n            {OUT_MD}")

    if args.apply:
        import psycopg
        conn = psycopg.connect(
            host="127.0.0.1", port=5432, user="kaoyan",
            password="kaoyan_dev_2026", dbname="kaoyan")
        cur = conn.cursor()
        updated = 0
        skipped = 0
        for r in records:
            expl = (r["analysis"] or "").strip()
            # 解析正文必须有一定长度；答案字段保持数据库原值不动
            if len(expl) < 20:
                print(f"  [!] #{r['id']} 解析过短（{len(expl)}字），跳过写库")
                skipped += 1
                continue
            # 规整：如果模型输出缺“答案：X”，用标准答案补成规范格式
            raw = r["raw_output"] or ""
            if not re.search(r"答案\s*[：:]", raw[:200]):
                formatted_analysis = f"答案：{r['gold']}\n解析：{expl}"
            else:
                formatted_analysis = raw.strip()
            cur.execute(
                "UPDATE quiz_questions SET analysis=%s, updated_at=now() WHERE id=%s",
                (formatted_analysis, r["id"]),
            )
            updated += cur.rowcount
        conn.commit()
        conn.close()
        print(f"已写库 {updated} 条，跳过 {skipped} 条。")
    else:
        print("未写库（dry-run）。人工抽检报告后再用 --apply 落库。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())