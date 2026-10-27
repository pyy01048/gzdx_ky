# -*- coding: utf-8 -*-
"""从题库构建「题目解析」SFT 数据集与留出评测集。

### 为什么单独建这一套数据

旧 `lora_finetune_v3` 的 248 条验证样本里 **181 条（73%）** 的答案是
「理解时要抓住它的判定条件与典型应用场景」这类模板句，模型学不到解析能力。
题库修完公式后，386 道里有 203 道具备「题干 + 选项 + 答案 + 可读解析」，
是当前唯一能支撑「题目解析」训练与评测的真实监督信号。

### 质量门（任一不满足即剔除，并计入 reasons）

1. 解析非空且 ≥20 字（20–40 字多为精炼结论，保留）
2. 题干/选项/解析不含图片 Markdown、`question_figures` 路径或 `[[F:n]]` 占位符
3. 不含图注引用（如图/图示/图中/图 1-3/结构图/波形图…）——文本模型看不到图，
   带图注的解析会教模型编造缺失信息
4. 答案必须能在选项 key 中找到
5. 不含明显残缺公式（`＝＝`/`，，`/`。。` 等连续标点）

### 划分

按学科分层，先留出 `--holdout` 题做评测（**全程不参与训练与早停**），
再从剩余样本留 `--val` 题做早停验证，其余进训练集。种子固定，重复运行结果一致。

用法：
    python scripts/build_quiz_analysis_dataset.py --dry-run
    python scripts/build_quiz_analysis_dataset.py --out-dir data/lora_finetune_quiz_v1
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from database import SessionLocal  # noqa: E402
from models import QuizQuestion  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 题干/解析里出现这些词就说明答案依赖插图，文本模型无法作答
FIGURE_REF = re.compile(
    r"(如图|图示|图中|下图|上图|见图|图\s*\d|图[一二三四五六七八九十]|"
    r"结构图|电路图|波形图|相量图|向量图|状态转换图|曲线如图|框图|流程图|示意图)"
)
IMAGE_LINK = re.compile(r"(!\[|question_figures|/media/images/)")
PLACEHOLDER = re.compile(r"\[\[F:\d+\]\]")
BROKEN = re.compile(r"(＝＝|，，|。。|＞＞|＜＜|\\;\\;)")
#: 解析以「如下：」「关系为」这类引导词收尾，说明后面的公式被旧管线吞掉了
INCOMPLETE_TAIL = re.compile(r"(如下|关系|方程|可得|于是|则|为)[：:]?\s*$")
#: 题尾来源标注，如「[电子科技大学 2006 研]」，训练时去掉以减少噪声
SOURCE_TAG = re.compile(r"\[[^\[\]]{0,30}(?:研|年)[^\[\]]{0,10}\]\s*$")

SYSTEM_PROMPT = (
    "你是一位考研辅导老师。回答时先给出正确选项，再给出解析；"
    "解析先点明考点，再写关键步骤，最后指出易错点。"
    "不要复述题干原文；不确定时明确说明，不要编造。"
)


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _options_text(options) -> str:
    lines = []
    for opt in options or []:
        if not isinstance(opt, dict):
            continue
        key = str(opt.get("key", "")).strip()
        text = str(opt.get("text", "")).strip()
        if key:
            lines.append(f"{key}. {text}")
    return "\n".join(lines)


def collect_usable(db) -> tuple[list[QuizQuestion], Counter]:
    rows = db.query(QuizQuestion).order_by(QuizQuestion.id).all()
    ok: list[QuizQuestion] = []
    reasons: Counter = Counter()

    for q in rows:
        content = _text(q.content).strip()
        analysis = _text(q.analysis).strip()
        options = q.options or []
        options_json = json.dumps(options, ensure_ascii=False)
        keys = {str(o.get("key", "")).strip() for o in options if isinstance(o, dict)}

        if not analysis:
            reasons["无解析"] += 1
            continue
        if len(analysis) < 20:
            reasons["解析过短(<20字)"] += 1
            continue
        blob = content + analysis + options_json
        if IMAGE_LINK.search(blob):
            reasons["含图片链接"] += 1
            continue
        if FIGURE_REF.search(blob):
            reasons["依赖插图"] += 1
            continue
        if not keys:
            reasons["无选项"] += 1
            continue
        if str(q.answer or "").strip() not in keys:
            reasons["答案不在选项内"] += 1
            continue
        if PLACEHOLDER.search(blob):
            reasons["残留占位符"] += 1
            continue
        if BROKEN.search(content) or BROKEN.search(analysis):
            reasons["残缺公式"] += 1
            continue
        if INCOMPLETE_TAIL.search(analysis):
            reasons["解析尾部缺公式"] += 1
            continue
        ok.append(q)

    return ok, reasons


def _quota(total: int, sizes: dict[str, int], minimum: int = 1) -> dict[str, int]:
    """按学科样本量比例分配名额，最大余数法补齐到 total。"""
    n_all = sum(sizes.values())
    if n_all <= 0:
        return {}
    exact = {s: total * n / n_all for s, n in sizes.items()}
    quota = {s: int(v) for s, v in exact.items()}
    for s, n in sizes.items():
        if n >= 10 and quota[s] < minimum:
            quota[s] = minimum
    remainder = total - sum(quota.values())
    if remainder > 0:
        for s in sorted(sizes, key=lambda x: (exact[x] - int(exact[x]), sizes[x]), reverse=True):
            if remainder <= 0:
                break
            quota[s] += 1
            remainder -= 1
    elif remainder < 0:
        for s in sorted(sizes, key=lambda x: (exact[x] - int(exact[x]))):
            if remainder >= 0:
                break
            if quota[s] > 0:
                quota[s] -= 1
                remainder += 1
    return quota


def _pick(groups: dict[str, list[QuizQuestion]], quota: dict[str, int], rng: random.Random):
    picked: list[QuizQuestion] = []
    for subject, qs in groups.items():
        n = min(quota.get(subject, 0), len(qs))
        picked.extend(qs[:n])
    return picked


def build(out_dir: str, holdout_n: int, val_n: int, seed: int, dry_run: bool) -> dict:
    db = SessionLocal()
    try:
        usable, reasons = collect_usable(db)
    finally:
        db.close()

    if not usable:
        raise SystemExit("没有可用样本，检查质量门")

    rng = random.Random(seed)
    by_subject: dict[str, list[QuizQuestion]] = defaultdict(list)
    for q in usable:
        by_subject[q.subject or "未分类"].append(q)
    for qs in by_subject.values():
        rng.shuffle(qs)
    sizes = {s: len(qs) for s, qs in by_subject.items()}

    holdout_n = min(holdout_n, len(usable) - 2)
    holdout = _pick(by_subject, _quota(holdout_n, sizes), rng)
    holdout_ids = {q.id for q in holdout}

    rest = {s: [q for q in qs if q.id not in holdout_ids] for s, qs in by_subject.items()}
    rest_sizes = {s: len(qs) for s, qs in rest.items() if qs}
    val_n = min(val_n, sum(rest_sizes.values()) - 1)
    val = _pick(rest, _quota(val_n, rest_sizes), rng)
    val_ids = {q.id for q in val}

    train = [q for q in usable if q.id not in holdout_ids and q.id not in val_ids]

    def to_sample(q: QuizQuestion) -> dict:
        content = SOURCE_TAG.sub("", _text(q.content)).strip()
        return {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"【科目】{q.subject or '未分类'}\n"
                        f"【题目】{content}\n"
                        f"【选项】\n{_options_text(q.options)}"
                    ),
                },
                {
                    "role": "assistant",
                    "content": f"答案：{str(q.answer).strip()}\n解析：{_text(q.analysis).strip()}",
                },
            ],
            "id": q.id,
            "subject": q.subject,
        }

    train_samples = [to_sample(q) for q in train]
    val_samples = [to_sample(q) for q in val]
    holdout_rows = [
        {
            "id": q.id,
            "subject": q.subject,
            "content": SOURCE_TAG.sub("", _text(q.content)).strip(),
            "options": q.options,
            "answer": str(q.answer).strip(),
            "analysis": _text(q.analysis).strip(),
        }
        for q in holdout
    ]

    stats = {
        "seed": seed,
        "source_total": len(usable) + sum(reasons.values()),
        "usable": len(usable),
        "rejected_reasons": dict(reasons),
        "train": len(train_samples),
        "val": len(val_samples),
        "holdout": len(holdout_rows),
        "holdout_ids": sorted(holdout_ids),
        "train_subjects": dict(Counter(q.subject for q in train)),
        "holdout_subjects": dict(Counter(q.subject for q in holdout)),
    }

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if dry_run:
        print("\n[dry-run] 未写文件")
        return stats

    os.makedirs(out_dir, exist_ok=True)
    for name, rows in (("train.jsonl", train_samples), ("val.jsonl", val_samples)):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "holdout.json"), "w", encoding="utf-8") as f:
        json.dump(holdout_rows, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "dataset_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"\n已写入 {out_dir}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="构建题库解析 SFT 数据集与留出评测集")
    parser.add_argument("--out-dir", default=os.path.join(BASE_DIR, "data", "lora_finetune_quiz_v1"))
    parser.add_argument("--holdout", type=int, default=50, help="留出评测题数")
    parser.add_argument("--val", type=int, default=20, help="早停验证题数")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    build(args.out_dir, args.holdout, args.val, args.seed, args.dry_run)


if __name__ == "__main__":
    main()
