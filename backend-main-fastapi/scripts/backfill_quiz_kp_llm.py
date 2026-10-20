#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""题目 → 知识点 LLM 回填（本地 Ollama 语义判断）。

### 为什么还要这一版
`quiz_questions` 386 道题里仍有 116 道 `knowledge_point` 为空，且题干被 OCR
啃得支离破碎（"设则（ ）"、"是（ ）"），纯文本匹配与 embedding 相似度都在
这些题上失效（270 道已是 embedding 的极限）。本脚本换用本地 7B 模型做**受限
分类**：把同科目候选知识点列表交给模型，让它只能从候选里挑 1 个。

### 关键约束
- **只处理 `knowledge_point` 为空的题**，重复执行不会覆盖人工/既有标签（幂等）。
- 写库前必须 `services.backup_service.create_backup()` 成功，否则中止。
- **模型输出严格校验**：`kp` 必须与候选列表中的名字逐字相等（仅归一化空白），
  否则整题判失败——绝不接受模型自造的知识点（防幻觉）。
- 单题超时 120s，失败重试 1 次；单题失败不影响其他题。
- `confidence < --threshold`（默认 0.6）或 `kp=null` 一律不写库，记入「待人工」。

### 候选池的构造
- 同科目知识点 <= ``MAX_KP_POOL``（120）：直接把全部候选名给模型（单段）。
- 超过 120（数学 1208 条 / 电路 280 条 / 数电 123 条）：两段式——
  先按 ``chapter`` 分组让模型选章，再在该章的知识点里选点。
  章节数过多时（数学有 360 个不同 chapter），先用题干字面重叠度 + 该章知识点
  数量做粗排，只把前 ``MAX_CHAPTERS``（40）个章节交给模型，避免 Prompt 爆炸。
- 题目自带的 ``chapter``（教材章节名）作为提示写进 Prompt，不作为硬约束：
  库里存在「数学」科目下混入自控原理章节题的情况，硬按章节过滤会全军覆没。

用法：
    python scripts/backfill_quiz_kp_llm.py --dry-run            # 前 15 道，只打印
    python scripts/backfill_quiz_kp_llm.py --dry-run --limit 30
    python scripts/backfill_quiz_kp_llm.py --apply              # 备份后写库
    python scripts/backfill_quiz_kp_llm.py --apply --json-out data/reports/kp_llm.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402

OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_THRESHOLD = 0.60
DEFAULT_TIMEOUT = 120
MAX_KP_POOL = 120          # 单段候选上限
MAX_CHAPTERS = 40          # 两段式时交给模型的章节数上限
MAX_CONTENT_CHARS = 1200   # 题干截断
MAX_OPTION_CHARS = 400     # 选项整体截断
DRY_RUN_SAMPLE = 15

SYSTEM_PROMPT = (
    "你是考研题库的知识点分类助手。你的唯一任务：从候选知识点列表里选出与题目"
    "**考查内容**最匹配的 1 个。\n"
    "硬性规则：\n"
    "1. kp 字段必须是候选列表中出现过的名字，逐字照抄，禁止改写、缩写、自造。\n"
    "2. 若题干/选项中出现了与某候选知识点**完全相同**的词（如题干问「静态工作点」"
    "而候选里就有「静态工作点」），优先直接选它。\n"
    "3. 判断依据是题目考查的定理/方法/性质，不是题干里恰好出现的名词。"
    "例如题干出现「正弦波振荡器」，考点是「振荡条件」而不是「正弦稳态电路」。\n"
    "4. 候选按章节分组，优先选与「教材章节提示」一致或相近的章节下的知识点；"
    "若该章节明显对不上（题库存在章节串科），再考虑其他章节。\n"
    "5. 只有题干完全没有可辨识的学科概念时才返回 null；只要能看出大致考点，"
    "就必须给出最可能的候选，并如实调低 confidence。\n"
    "6. 只输出一个 JSON 对象，不要解释、不要 Markdown 代码块。\n"
    '格式：{"kp": "知识点名或null", "confidence": 0.0, "reason": "一句话"}'
)


# --------------------------------------------------------------------------- #
# 数据读取
# --------------------------------------------------------------------------- #
def option_text(options) -> str:
    """jsonb options -> "A. xxx B. yyy" 纯文本。"""
    if not options:
        return ""
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except Exception:
            return options
    if isinstance(options, dict):
        options = list(options.values())
    parts = []
    for opt in options:
        if isinstance(opt, dict):
            key = str(opt.get("key") or "").strip()
            val = str(opt.get("text") or opt.get("content") or "").strip()
            parts.append(f"{key}. {val}" if key else val)
        else:
            parts.append(str(opt).strip())
    return " ".join(p for p in parts if p)


def load_questions(cur) -> list[dict]:
    cur.execute("""
        SELECT id, subject, chapter, content, options
        FROM quiz_questions
        WHERE btrim(coalesce(knowledge_point, '')) = ''
        ORDER BY id
    """)
    out = []
    for qid, subject, chapter, content, options in cur.fetchall():
        out.append({
            "id": qid,
            "subject": (subject or "").strip(),
            "chapter": (chapter or "").strip(),
            "content": (content or "").strip(),
            "options": option_text(options),
        })
    return out


def load_kps(cur) -> dict[str, list[dict]]:
    """subject -> 知识点列表；同名只保留 id 最小的一条。"""
    cur.execute("""
        SELECT id, name, subject, chapter, description
        FROM knowledge_points
        WHERE btrim(coalesce(name, '')) <> ''
        ORDER BY id
    """)
    by_subject: dict[str, dict[str, dict]] = defaultdict(dict)
    for kid, name, subject, chapter, desc in cur.fetchall():
        name = re.sub(r"\s+", " ", (name or "").strip())
        subject = (subject or "").strip()
        if not name or not subject or len(name) > 200:
            continue
        if name not in by_subject[subject]:
            by_subject[subject][name] = {
                "id": kid,
                "name": name,
                "chapter": (chapter or "").strip(),
                "desc": (desc or "").strip(),
            }
    return {s: list(v.values()) for s, v in by_subject.items()}


# --------------------------------------------------------------------------- #
# 候选池
# --------------------------------------------------------------------------- #
def name_overlap(text: str, name: str) -> float:
    """知识点名/章节名与题干文本的字面重叠（2-gram 覆盖率，便宜且够用）。"""
    if not text or not name:
        return 0.0
    grams = {name[i:i + 2] for i in range(len(name) - 1)} or {name}
    hit = sum(1 for g in grams if g in text)
    return hit / len(grams)


def chapter_groups(kps: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for kp in kps:
        groups[kp["chapter"] or "(未标注章节)"].append(kp)
    return dict(groups)


def rank_chapters(groups: dict[str, list[dict]], q: dict) -> list[str]:
    """章节太多时粗排：题干字面命中优先，其次该章知识点数量。"""
    hay = q["content"] + " " + q["options"] + " " + q["chapter"]
    scored = []
    for ch, items in groups.items():
        hit = max((name_overlap(hay, it["name"]) for it in items[:40]), default=0.0)
        scored.append((round(hit, 4), len(items), ch))
    scored.sort(reverse=True)
    return [ch for _, _, ch in scored[:MAX_CHAPTERS]] if len(groups) > MAX_CHAPTERS \
        else [ch for _, _, ch in scored]


# --------------------------------------------------------------------------- #
# Ollama 调用
# --------------------------------------------------------------------------- #
def ollama_chat(model: str, messages: list[dict], timeout: int) -> str:
    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.1, "top_p": 0.9, "num_ctx": 8192},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    msg = payload.get("message") or {}
    return str(msg.get("content") or payload.get("response") or "")


def parse_json_object(text: str) -> dict | None:
    """从模型输出里抠第一个 JSON 对象（容忍 ```json 围栏与前后废话）。"""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    for m in re.finditer(r"\{[^{}]*\}", cleaned, flags=re.S):
        try:
            obj = json.loads(m.group(0))
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u3000", " ")).strip()


def validate(obj: dict, candidates: list[str]) -> tuple[str | None, float, str, str]:
    """返回 (kp 或 None, confidence, reason, 错误信息)。空错误串表示通过校验。"""
    cand_set = {norm_name(c): c for c in candidates}
    raw_kp = obj.get("kp", None)
    reason = str(obj.get("reason") or "").strip()[:120]
    try:
        conf = float(obj.get("confidence") or 0.0)
    except Exception:
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    if raw_kp is None or (isinstance(raw_kp, str) and norm_name(raw_kp).lower() in
                          ("", "null", "none", "无")):
        return None, 0.0, reason, ""

    if not isinstance(raw_kp, str):
        return None, conf, reason, f"kp 类型非法：{type(raw_kp).__name__}"

    key = norm_name(raw_kp)
    if key not in cand_set:
        return None, conf, reason, f"kp「{key}」不在候选列表内"
    return cand_set[key], conf, reason, ""


# --------------------------------------------------------------------------- #
# 单题判断
# --------------------------------------------------------------------------- #
def build_question_block(q: dict) -> str:
    content = q["content"][:MAX_CONTENT_CHARS] or "(题干为空)"
    opts = q["options"][:MAX_OPTION_CHARS] or "(无选项)"
    lines = [f"科目：{q['subject']}", f"题干：{content}", f"选项：{opts}"]
    if q["chapter"]:
        lines.append(f"教材章节提示：{q['chapter']}")
    return "\n".join(lines)


#: 自动控制原理章节特征词。库里有一批「数学」科目的题其实是自控原理题
#: （第1-10章 线性系统/根轨迹/频域/校正…），而数学科目的 1208 条知识点里
#: 只有 2 条根轨迹相关，强行匹配只会产出「二阶常系数微分方程」这类错标。
CONTROL_KEYWORDS = ("自动控制", "控制系统", "根轨迹", "频域分析", "校正方法",
                    "线性系统", "离散系统", "非线性控制", "最优控制",
                    "状态空间", "时域分析法")
CONTROL_KP_MIN = 10


def looks_cross_domain(q: dict, kps: list[dict]) -> bool:
    """题干章节像自控，但本学科几乎没有自控知识点 → 判为串科，转人工。"""
    if not q["chapter"] or not any(kw in q["chapter"] for kw in CONTROL_KEYWORDS):
        return False
    hits = sum(1 for kp in kps
               if any(kw in f"{kp['chapter']} {kp['name']}" for kw in CONTROL_KEYWORDS))
    return hits < CONTROL_KP_MIN


def format_candidates(pool: list[dict]) -> str:
    """按章节分组罗列候选名——给模型结构信号，显著减少「名词撞车」误配。"""
    groups = chapter_groups(pool)
    ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    blocks = []
    for ch, items in ordered:
        names = "、".join(k["name"] for k in items)
        blocks.append(f"【{ch}】{names}")
    return "\n".join(blocks)


def ask_point(model: str, q: dict, pool: list[dict], timeout: int,
              chapter_hint: str = "") -> tuple[dict, dict]:
    """返回 ({kp, confidence, reason, error}, meta)。失败会自动重试 1 次。"""
    candidates = [k["name"] for k in pool]
    head = build_question_block(q)
    if chapter_hint:
        head = f"已选章节：{chapter_hint}\n" + head
    user = (
        f"{head}\n\n"
        f"候选知识点（共 {len(candidates)} 个，按章节分组，只能从中选）：\n"
        + format_candidates(pool)
        + "\n\n请从中选最匹配的 1 个。信息不足时 kp 返回 null。只输出 JSON。"
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user}]
    meta = {"calls": 0, "seconds": 0.0}
    last_err = "未执行"

    for attempt in range(2):
        t0 = time.time()
        try:
            raw = ollama_chat(model, messages, timeout)
            meta["calls"] += 1
            meta["seconds"] += time.time() - t0
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            meta["calls"] += 1
            meta["seconds"] += time.time() - t0
            last_err = f"调用失败：{type(exc).__name__}: {exc}"
            continue

        obj = parse_json_object(raw)
        if obj is None:
            last_err = "输出不是合法 JSON"
        else:
            kp, conf, reason, err = validate(obj, candidates)
            if not err:
                return {"kp": kp, "confidence": conf, "reason": reason, "error": ""}, meta
            last_err = err
        # 把失败输出回喂，要求修正（仅重试 1 次）
        messages = messages + [
            {"role": "assistant", "content": raw[:600]},
            {"role": "user", "content":
             f"上面的输出无效：{last_err}。只能从候选列表里逐字照抄一个名字，"
             "信息不足就返回 null。请重新只输出 JSON。"},
        ]

    return {"kp": None, "confidence": 0.0, "reason": "", "error": last_err}, meta


def ask_chapter(model: str, q: dict, chapters: list[str], counts: dict[str, int],
                timeout: int) -> tuple[str | None, str, int]:
    listing = "\n".join(f"- {ch}（{counts[ch]} 条）" for ch in chapters)
    user = (
        f"{build_question_block(q)}\n\n"
        f"候选章节（共 {len(chapters)} 个，只能从中选）：\n{listing}\n\n"
        "先判断这道题属于哪个章节，只输出 JSON："
        '{"chapter": "章节名", "reason": "一句话"}。信息不足时 chapter 返回 null。'
    )
    messages = [{"role": "system", "content":
                 "你是考研题库的章节归类助手，只能从候选章节里逐字选择，只输出 JSON。"},
                {"role": "user", "content": user}]
    raw = ""
    calls = 0
    err = "未执行"
    for _ in range(2):
        try:
            raw = ollama_chat(model, messages, timeout)
            calls += 1
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            calls += 1
            raw = ""
            err = f"调用失败：{type(exc).__name__}"
        else:
            obj = parse_json_object(raw)
            if obj is not None and obj.get("chapter") is not None:
                ch = norm_name(str(obj.get("chapter")))
                for cand in chapters:
                    if norm_name(cand) == ch:
                        return cand, "", calls
                err = f"章节「{ch}」不在候选内"
            elif obj is not None:
                return None, "模型判定章节信息不足", calls
            else:
                err = "输出不是合法 JSON"
        messages = messages + [
            {"role": "assistant", "content": raw[:400]},
            {"role": "user", "content": f"输出无效：{err}。请只输出 JSON，章节名必须逐字来自候选。"},
        ]
    return None, err, calls


def decide(model: str, q: dict, kps: list[dict], timeout: int) -> dict:
    """单题决策：直接选点或两段式选章→选点。"""
    t0 = time.time()
    meta = {"calls": 0, "seconds": 0.0, "mode": "direct", "chapter": None}

    if len(kps) <= MAX_KP_POOL:
        pool = kps
        res, m = ask_point(model, q, pool, timeout)
        meta["calls"] += m["calls"]
        meta["seconds"] += m["seconds"]
    else:
        meta["mode"] = "chapter"
        groups = chapter_groups(kps)
        chap_names = rank_chapters(groups, q)
        picked, err, chap_calls = ask_chapter(
            model, q, chap_names, {c: len(groups[c]) for c in chap_names}, timeout)
        meta["calls"] += chap_calls
        if picked:
            meta["chapter"] = picked
            pool = groups[picked][:MAX_KP_POOL]
        else:
            # 选章失败：退化为全科目字面粗排 top120，仍受候选校验保护
            hay = q["content"] + " " + q["options"] + " " + q["chapter"]
            pool = sorted(kps, key=lambda k: -name_overlap(hay, k["name"]))[:MAX_KP_POOL]
            meta["mode"] = "chapter-fallback"
        res, m = ask_point(model, q, pool, timeout, chapter_hint=meta["chapter"] or "")
        meta["calls"] += m["calls"]
        meta["seconds"] += m["seconds"]

    name_to_kp = {k["name"]: k for k in kps}
    res["kp_obj"] = name_to_kp.get(res["kp"]) if res["kp"] else None
    res["candidates"] = len(pool)
    res["elapsed"] = round(time.time() - t0, 2)
    meta["seconds"] = round(meta["seconds"], 2)
    return {**res, "meta": meta}


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="题目知识点 LLM 回填（本地 Ollama）")
    ap.add_argument("--dry-run", action="store_true", help="只判断不写库（默认前 15 道）")
    ap.add_argument("--apply", action="store_true", help="备份后写库")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama 模型，默认 {DEFAULT_MODEL}")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"写库置信度阈值，默认 {DEFAULT_THRESHOLD}")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="单次调用超时（秒）")
    ap.add_argument("--limit", type=int, default=-1,
                    help="只处理前 N 道（0=全部；默认 dry-run 15 道、apply 全部）")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份（不建议）")
    ap.add_argument("--json-out", default="", help="把逐题结果写到 JSON 报告")
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        ap.error("必须指定 --dry-run 或 --apply")
    apply = args.apply and not args.dry_run

    limit = args.limit if args.limit >= 0 else (0 if apply else DRY_RUN_SAMPLE)

    with psycopg.connect(pg_database_url()) as conn:
        with conn.cursor() as cur:
            all_questions = load_questions(cur)
            kps_by_subject = load_kps(cur)

        total_empty = len(all_questions)
        questions = all_questions[:limit] if limit else all_questions

        print(f"[data] 全库空知识点 {total_empty} 道；本次判断 {len(questions)} 道")
        print(f"[pool] 知识点科目：" + "，".join(
            f"{s}={len(v)}" for s, v in sorted(kps_by_subject.items(), key=lambda kv: -len(kv[1]))))
        print(f"[model] {args.model} @ {OLLAMA_URL}  threshold={args.threshold} "
              f"timeout={args.timeout}s  mode={'APPLY' if apply else 'DRY-RUN'}")

        records: list[dict] = []
        for i, q in enumerate(questions, 1):
            kps = kps_by_subject.get(q["subject"], [])
            preview = " ".join(q["content"].split())[:48] or "(题干为空)"
            if not kps:
                rec = {"id": q["id"], "subject": q["subject"], "status": "pending",
                       "kp": None, "confidence": 0.0, "reason": "该科目无知识点候选",
                       "error": "no_candidates", "preview": preview, "elapsed": 0.0,
                       "calls": 0, "mode": "skip", "chapter": None, "candidates": 0,
                       "model_kp": None}
                records.append(rec)
                print(f"  [{i}/{len(questions)}] q{q['id']} 跳过：科目「{q['subject']}」无候选")
                continue
            if looks_cross_domain(q, kps):
                rec = {"id": q["id"], "subject": q["subject"], "status": "pending",
                       "kp": None, "confidence": 0.0,
                       "reason": f"章节「{q['chapter']}」属自控原理，本学科无对应知识点（疑似串科）",
                       "error": "cross_domain", "preview": preview, "elapsed": 0.0,
                       "calls": 0, "mode": "skip", "chapter": None, "candidates": 0,
                       "model_kp": None}
                records.append(rec)
                print(f"  [{i}/{len(questions)}] q{q['id']} 跳过：{rec['reason']}")
                continue

            res = decide(args.model, q, kps, args.timeout)
            kp = res["kp_obj"]
            if kp is None:
                status = "pending"
                reason = res["error"] or res["reason"] or "模型判定信息不足"
            elif res["confidence"] < args.threshold:
                status = "pending"
                reason = f"置信度 {res['confidence']:.2f} < {args.threshold}"
            else:
                status = "ok"
                reason = res["reason"]

            rec = {
                "id": q["id"], "subject": q["subject"], "status": status,
                "kp": kp["name"] if kp else None,
                "kp_id": kp["id"] if kp else None,
                "confidence": round(res["confidence"], 3),
                "reason": reason, "error": res["error"],
                "preview": preview, "model_kp": res["kp"],
                "mode": res["meta"]["mode"], "chapter": res["meta"]["chapter"],
                "candidates": res["candidates"], "elapsed": res["elapsed"],
                "calls": res["meta"]["calls"],
            }
            records.append(rec)
            mark = "OK " if status == "ok" else "-- "
            print(f"  [{i}/{len(questions)}] q{q['id']} {mark}{rec['subject']} | {preview}")
            print(f"        → {rec['kp'] or '(不写)'}  conf={rec['confidence']:.2f}  "
                  f"{rec['elapsed']}s  {reason[:70]}")

        ok = [r for r in records if r["status"] == "ok"]
        pending = [r for r in records if r["status"] != "ok"]
        cross = sum(1 for r in pending if r["error"] == "cross_domain")
        null_cnt = sum(1 for r in pending if r["error"] == "" and r["kp"] is None)
        lowconf = sum(1 for r in pending if r["error"] == "" and r["kp"] is not None)
        failed = len(pending) - cross - null_cnt - lowconf
        avg = sum(r["elapsed"] for r in records) / max(1, len(records))
        total_calls = sum(r["calls"] for r in records)

        print("\n" + "=" * 72)
        print(f"[result] 可写库 {len(ok)} / {len(records)}   待人工 {len(pending)}")
        print(f"         待人工构成：信息不足 {null_cnt}，章节串科 {cross}，"
              f"置信度不足 {lowconf}，调用/校验失败 {failed}")
        print(f"[perf]   单题平均 {avg:.1f}s，共 {total_calls} 次模型调用")
        by_subj: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for r in records:
            by_subj[r["subject"]][0 if r["status"] == "ok" else 1] += 1
        print("[by-subject] " + "；".join(f"{s}: 命中 {a} / 待人工 {b}"
                                          for s, (a, b) in sorted(by_subj.items())))

        if pending:
            print("\n[pending] 待人工清单（前 20）：")
            for r in pending[:20]:
                print(f"  q{r['id']:<4} [{r['subject']}] {r['preview'][:40]} — {r['reason'][:60]}")

        if args.json_out:
            out = Path(args.json_out)
            if not out.is_absolute():
                out = BASE / out
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "model": args.model, "threshold": args.threshold, "apply": apply,
                "total": len(records), "ok": len(ok), "pending": len(pending),
                "avg_seconds": round(avg, 2), "records": records,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[report] {out}")

        if not apply:
            print("\n[DRY-RUN] 未写库；确认无误后加 --apply 执行。")
            return 0

        if not ok:
            print("\n[SKIP] 没有达到阈值的结果，不写库、不备份。")
            return 0

        if not args.no_backup:
            from services.backup_service import create_backup

            path = create_backup()
            print(f"\n[backup] {path}")

        written = 0
        with conn.cursor() as cur:
            for r in ok:
                # 幂等：仍只在原值为空时写文本，避免覆盖并发写入的人工标签
                cur.execute(
                    "UPDATE quiz_questions SET knowledge_point = %s"
                    " WHERE id = %s AND btrim(coalesce(knowledge_point, '')) = ''",
                    (r["kp"], r["id"]),
                )
                if cur.rowcount == 0:
                    continue
                cur.execute(
                    "INSERT INTO question_knowledge_links"
                    " (question_id, knowledge_point_id, role, weight, is_verified)"
                    " VALUES (%s, %s, 'primary', %s, false)"
                    " ON CONFLICT (question_id, knowledge_point_id) DO UPDATE"
                    " SET role = 'primary', weight = EXCLUDED.weight, is_verified = false",
                    (r["id"], r["kp_id"], r["confidence"]),
                )
                written += 1
        conn.commit()

        with conn.cursor() as cur:
            filled, total = cur.execute("""
                SELECT count(*) FILTER (WHERE btrim(coalesce(knowledge_point, '')) <> ''),
                       count(*)
                FROM quiz_questions
            """).fetchone()
            linked = cur.execute(
                "SELECT count(DISTINCT question_id) FROM question_knowledge_links").fetchone()[0]
        print(f"[OK] 写入 {written} 道；knowledge_point {filled}/{total}；"
              f"有关联的题目 {linked}/{total}；仍待人工 {total - filled} 道")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
