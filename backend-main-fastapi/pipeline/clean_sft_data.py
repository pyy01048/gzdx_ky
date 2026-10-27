# -*- coding: utf-8 -*-
"""训练数据清洗与重建：把 LoRA SFT 样本从"能用的原料"提纯为"可训练的语料"。

为什么必须先清洗（2026-10-14 实测）
-----------------------------------
库里 `sft_examples` 有 4670 条，抽检发现**结构性问题**：

  * assistant 长度中位 160 字符、最长仅 189 —— 全部是被硬截断的文本片段，不是完整答案；
  * **91.6% 是"复述型"**：assistant 前 60 字直接出现在 user 里（模型只会学会照抄输入）；
  * assistant 以"答案是："开头的比例 90.3%，但其中相当一部分与题干无关
    （实测案例：问"555 定时器画波形"，答"JK 相连即为 T 触发器"）。

用这种数据微调，**准确率不是提高而是下降**——模型会学到"复述用户输入 + 套用固定前缀"。

而 `data/lora_finetune_v3/` 的样本质量明显更好（复述型 0%、system prompt 明确要求
"先结论后原理、不复述题目原文"），但仍有 24% 答案存疑、9.7% 过短。

本脚本做三件事
--------------
1. **多源合并**：PG `sft_examples` + 文件系统 v2/v3（以 v3 为主，去重后合并）；
2. **质量过滤**：剔除复述型、过短、答非所问、占位符残留的样本；
3. **规范化输出**：统一 messages 三段式 + 按科目分层切分 train/val，
   并输出质量报告供人工复核。

红线
----
* **不改动源数据**：只读 PG 与 v2/v3 文件，产物写新目录 `lora_finetune_clean/`。
* **过滤留证据**：每条被剔除的样本都记录原因，写入报告，可回溯。
* **不做"生成式补数据"**：不从零编造问答对，只用已有真实语料。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DATA_DIR = BASE_DIR / "data"
OUT_DIR = DATA_DIR / "lora_finetune_clean"
REPORT = DATA_DIR / "sft_clean_report.json"

#: 统一 system prompt（对齐 v3 的专业口径：先结论、后原理、不复述题面）
SYSTEM_PROMPT = (
    "你是一位考研辅导老师，负责计算机与电子信息类考研的答疑，"
    "专长是数字电子技术、模拟电子技术（834 电子技术基础）以及数学二、英语二、政治。"
    "回答要求：先给结论，再解释原理，必要时给出解题步骤；"
    "只讲与问题相关的内容，不要复述题目原文。"
)

#: 质量门禁阈值
MIN_ANSWER_CHARS = 40        # assistant 太短说明被截断或不完整
MIN_QUESTION_CHARS = 6       # 题干太短无信息量
MAX_ANSWER_CHARS = 3000      # 超长多为拼接污染
RELEVANCE_MIN = 0.12         # 题干关键词在答案中的最低覆盖率

#: 明显的占位/噪声答案
_PLACEHOLDER_RE = re.compile(
    r"^(略|见解析|见正文|无|None|null|答案见.{0,6}|详见.{0,6}|"
    r"（?[0-9]+）?\s*$|第?\s*[0-9]+\s*页)", re.I
)
#: 选项/题号残留（答案里混进下一题的题号）
_NEXT_QUESTION_RE = re.compile(r"^\s*[（(]?\s*[0-9]{1,2}\s*[）)]?\s*[、.]\s*\S{0,4}(下列|如图|已知|求)")
#: 纯水印/页眉
_WATERMARK_RE = re.compile(r"(第\s*\d+\s*页|扫描全能王|微信公众号|微信[:：]|东坡哥|QQ群?[:：]\s*\d+)")
#: 答案开头常见编辑残留
_EDIT_NOISE = re.compile(r"^(答案[:：]|解析[:：]|解[:：]|【答案】|【解析】)+")
#: 答案里的"生成模板"外壳：`答案是：X\n解析：Y\n考点：Z`
#: 实测 80% 的样本带这套外壳，是数据生成时注入的。它有两个害处：
#:   1. 模型学到的是"填模板"而不是"讲解"，答复杂题时只剩空壳；
#:   2. 「考点：卡诺图（第6章 时序电路）」这类**章节标注大量是错的**
#:      （实测：卡诺图属第2章逻辑代数，却被标成第6章）。
#: 处理：把外壳剥掉还原成自然表述；章节归属一律**不保留**（错误信息比没有更糟）。
_ANSWER_PREFIX_RE = re.compile(r"^\s*(?:答案|答|解析|解)\s*[:：]\s*")
_PARSE_BLOCK_RE = re.compile(r"\n?\s*(?:解析|解)\s*[:：]\s*")
_POINT_BLOCK_RE = re.compile(r"\n?\s*(?:考点|考察点|考査点)\s*[:：][^\n]*")
_CHAPTER_INLINE_RE = re.compile(
    r"[（(]\s*第\s*[0-9一二三四五六七八九十]+\s*章[^）)]*[）)]"
    r"|属于\s*第\s*[0-9一二三四五六七八九十]+\s*章[^。；;\n]*"
    r"|这\s*部分\s*内容\s*属于\s*「[^」]*」"
    r"|本题\s*考[查査][^。\n]*(?:考点|等考点)[^。\n]*"
)


def strip_template(answer: str) -> str:
    """剥掉生成模板外壳，还原自然讲解。

    顺序：先删整块（考点行），再删行内标记（解析：），最后去前缀与章节标注。
    """
    a = answer or ""
    a = _POINT_BLOCK_RE.sub("", a)
    a = _PARSE_BLOCK_RE.sub("\n", a)
    for _ in range(3):
        new = _ANSWER_PREFIX_RE.sub("", a)
        if new == a:
            break
        a = new
    a = _CHAPTER_INLINE_RE.sub("", a)
    a = re.sub(r"[ \t]+", " ", a)
    a = re.sub(r"\n{3,}", "\n\n", a)
    return a.strip()


#: 空壳答案：剥掉"答案是/解析/考点/模板词"后只剩标点与空白。
#: 实测坏例：「答案是：``` 答案： ```\n解析：本题考査「…」等考点。\n考点：…」
#: —— 有完整框架但零实质内容，比"过短"更隐蔽，必须单独拦。
_SHELL_PATTERNS = [
    re.compile(r"^\s*```[\s\S]*?```\s*$"),
    re.compile(r"^[\s`「」【】\[\]（）()：:、，,。.…—\-]*$"),
]
#: 骨架词：出现这些词但去掉后无实义内容，视为空壳
_SHELL_TOKENS = ("答案", "解析", "考点", "本题考查", "本题考査", "解析如下", "仅供参考")


def _norm(s: str) -> str:
    """归一化：去空白、去零宽字符，用于相似度比对。"""
    if not s:
        return ""
    s = s.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", "", s)


def _tokenize(s: str) -> list[str]:
    """中文按 2-gram + 英文按词切分（不依赖 jieba，保证脚本零外依赖）。"""
    if not s:
        return []
    toks: list[str] = []
    # 英文/数字词
    toks += re.findall(r"[A-Za-z]{2,}", s)
    # 中文 2-gram
    han = re.findall(r"[\u4e00-\u9fff]+", s)
    for seg in han:
        for i in range(len(seg) - 1):
            toks.append(seg[i:i + 2])
    return toks


def judge(question: str, answer: str) -> tuple[bool, str]:
    """判定样本是否可用于训练。返回 (是否保留, 原因)。"""
    q, a = (question or "").strip(), (answer or "").strip()
    if len(q) < MIN_QUESTION_CHARS:
        return False, "问题过短"
    if len(a) < MIN_ANSWER_CHARS:
        return False, "答案过短（疑似截断）"
    if len(a) > MAX_ANSWER_CHARS:
        return False, "答案超长（疑似拼接污染）"
    if _PLACEHOLDER_RE.match(a):
        return False, "占位答案（略/见解析）"
    if _WATERMARK_RE.search(a):
        return False, "答案含水印残留"

    for pat in _SHELL_PATTERNS:
        if pat.match(a):
            return False, "空壳答案（无实质内容）"

    nq, na = _norm(q), _norm(a)
    # 1) 复述型：答案前 60 字直接出现在题干里
    if len(na) >= 60 and na[:60] in nq:
        return False, "复述型（答案照抄题干）"
    # 2) 完全一致
    if nq and na == nq:
        return False, "答案与题干完全相同"
    # 3) 下一题残留
    if _NEXT_QUESTION_RE.match(_EDIT_NOISE.sub("", a)):
        return False, "答案混入下一题题干"
    # 4) 相关性：题干关键词在答案中的覆盖
    kws = [t for t in _tokenize(q) if not t.isdigit()][:40]
    if kws:
        hit = sum(1 for k in set(kws) if k in na)
        cov = hit / max(1, len(set(kws)))
        if cov < RELEVANCE_MIN:
            return False, f"答非所问（关键词覆盖 {cov:.0%}）"

    # 5) 骨架剥离后是否还有实质内容
    #    实测坏例：「答案是：``` 答案： ``` 解析：本题考查「并行加法器」等考点。考点：二进制」
    #    剥掉"答案是/解析/考点/引号内容"后若有意义字符不足 12 个，判为空壳。
    stripped = na
    for tok in _SHELL_TOKENS:
        stripped = stripped.replace(_norm(tok), "")
    stripped = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", stripped)
    if len(stripped) < 12:
        return False, "空壳答案（剥除骨架词后无实质内容）"
    return True, "ok"


def load_pg_samples() -> list[dict]:
    """从 PG 读取 sft_examples（列名 user_input，PG 侧改名后的口径）。"""
    out: list[dict] = []
    try:
        from sqlalchemy import text as _t

        from database import engine
        with engine.connect() as conn:
            rows = conn.execute(_t(
                "SELECT system, user_input, assistant, subject FROM sft_examples"
            )).fetchall()
        for sysm, u, a, subj in rows:
            out.append({"system": sysm or "", "user": u or "",
                        "assistant": a or "", "subject": subj or "其他",
                        "_src": "pg"})
    except Exception as exc:  # noqa: BLE001
        print(f"  [警告] 读取 PG sft_examples 失败：{str(exc)[:120]}")
    return out


def load_file_samples() -> list[dict]:
    """读取 lora_finetune_v2 / v3 的 jsonl（v3 优先，后读的覆盖先读的）。"""
    out: list[dict] = []
    for ver in ("v2", "v3"):
        for split in ("train", "val"):
            p = DATA_DIR / f"lora_finetune_{ver}" / f"{split}.jsonl"
            if not p.exists():
                continue
            for line in p.open(encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                msgs = obj.get("messages") or obj.get("conversations") or []
                s = u = a = ""
                for m in msgs:
                    role = m.get("role") or m.get("from")
                    c = m.get("content") or m.get("value") or ""
                    if role == "system":
                        s = c
                    elif role in ("user", "human"):
                        u = c
                    elif role in ("assistant", "gpt"):
                        a = c
                if u and a:
                    out.append({"system": s, "user": u, "assistant": a,
                                "subject": obj.get("subject") or "其他",
                                "_src": f"{ver}_{split}"})
    return out


def split_question_context(user: str) -> str:
    """从 user 里剥出"题干"部分。

    v3 的 user 常形如「<题干原文>例题：<真正的问题>」或夹杂 OCR 碎片，
    关键词覆盖判定应针对**问题部分**，而不是整段原文（否则失真）。
    """
    u = user or ""
    for marker in ("例题：", "例题:", "例：", "例:", "题目：", "题目:"):
        if marker in u:
            tail = u.split(marker)[-1]
            if len(tail) >= MIN_QUESTION_CHARS:
                return tail
    return u


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SFT 训练数据清洗与重建")
    p.add_argument("--out-dir", default=str(OUT_DIR))
    p.add_argument("--val-ratio", type=float, default=0.08)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    print("=" * 70)
    print("SFT 训练数据清洗与重建")
    print("=" * 70)

    print("[1/4] 加载多源样本 …")
    pg = load_pg_samples()
    files = load_file_samples()
    print(f"  PG sft_examples : {len(pg)} 条")
    print(f"  文件 v2/v3      : {len(files)} 条")

    # 合并：文件源（质量更高）优先，PG 补充。按 (归一化user, 归一化assistant) 去重。
    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for s in files + pg:
        key = (_norm(s["user"])[:200], _norm(s["assistant"])[:200])
        if key in seen:
            continue
        seen.add(key)
        merged.append(s)
    print(f"  去重合并后      : {len(merged)} 条")

    print("[2/4] 剥离生成模板 + 质量过滤 …")
    kept: list[dict] = []
    rejects: Counter = Counter()
    reject_detail: list[dict] = []
    stripped_n = 0
    for s in merged:
        # 先剥模板：把「答案是：X 解析：Y 考点：Z（第N章）」还原成自然讲解。
        # 这是修"套模板"与"章节标错"两个问题的关键一步 —— 不剥掉，
        # 模型学到的就是「填模板 + 照抄错误章节」。
        raw_a = s["assistant"] or ""
        clean_a = strip_template(raw_a)
        if clean_a != raw_a:
            stripped_n += 1
        s["assistant"] = clean_a
        ok, reason = judge(split_question_context(s["user"]), s["assistant"])
        if ok:
            kept.append(s)
        else:
            rejects[reason] += 1
            if len(reject_detail) < 300:
                reject_detail.append({"reason": reason,
                                      "user": (s["user"] or "")[:120],
                                      "assistant": (s["assistant"] or "")[:120],
                                      "_src": s["_src"]})
    print(f"  模板剥离生效 {stripped_n} 条（答案已还原为自然表述）")
    print(f"  保留 {len(kept)} 条 / 剔除 {len(merged) - len(kept)} 条")
    for r, n in rejects.most_common():
        print(f"    - {r}: {n}")

    print("[3/4] 分层切分 train/val …")
    # 按科目分层，保证 val 覆盖各科（而不是全落在数电）
    by_subj: dict[str, list[dict]] = {}
    for s in kept:
        by_subj.setdefault(s["subject"], []).append(s)
    train, val = [], []
    for subj, items in by_subj.items():
        n_val = max(1, int(len(items) * args.val_ratio)) if len(items) >= 12 else 0
        val.extend(items[:n_val])
        train.extend(items[n_val:])
    print(f"  train {len(train)} / val {len(val)}")
    print(f"  科目分布（train）: {dict(Counter(s['subject'] for s in train).most_common(8))}")

    if args.dry_run:
        print("\n[dry-run] 未写文件。")
        return 0

    print("[4/4] 写出产物 …")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def _write(path: Path, items: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as f:
            for s in items:
                f.write(json.dumps({
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": s["user"]},
                        {"role": "assistant", "content": s["assistant"]},
                    ],
                    "subject": s["subject"],
                    "source": s["_src"],
                }, ensure_ascii=False) + "\n")

    _write(out / "train.jsonl", train)
    _write(out / "val.jsonl", val)

    report = {
        "sources": {"pg": len(pg), "files": len(files), "merged": len(merged)},
        "kept": len(kept), "rejected": len(merged) - len(kept),
        "reject_reasons": dict(rejects),
        "template_stripped": stripped_n,
        "train": len(train), "val": len(val),
        "subject_distribution": dict(Counter(s["subject"] for s in kept).most_common()),
        "reject_samples": reject_detail,
        "system_prompt": SYSTEM_PROMPT,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已写出 {out / 'train.jsonl'} / {out / 'val.jsonl'}")
    print(f"  质量报告：{REPORT}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
