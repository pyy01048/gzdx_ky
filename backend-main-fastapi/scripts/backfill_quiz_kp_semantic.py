# -*- coding: utf-8 -*-
"""题目 → 知识点 语义回填（PG + 本地 bge-small-zh-v1.5）。

### 背景
`quiz_questions` 386 道里 312 道 `knowledge_point` 为空，且题干多为 OCR 残缺
（"设随机变量，记，则…"），纯文本匹配（scripts/backfill_quiz_kp_text.py）
只能覆盖十几道。本脚本改用语义相似度：题干+选项 vs 知识点名+释义。

### 关键约束
- 复用项目既有 embedding 基建：``services.embedding_service.generate_local_embeddings``
  （fastembed + ``data/embedding_models`` 里已缓存的 BAAI/bge-small-zh-v1.5，512 维），
  不下载、不新装模型。向量与 ``chunk_vectors`` 同一空间。
- 只在**同科目**知识点内比较，避免跨科误配；同科目无候选则记「待人工」。
  同科目知识点数 < ``--min-pool``（默认 30）时整科跳过——候选太少时 top1 必然
  被少数几个宽泛知识点吸走（模拟电子技术只有 14 条知识点 / 95 道题）。
- 知识点文本只用 ``name + description[:150]``：拼 chapter 会让「线性代数」「第一章」
  变成通用锚点，实测把同科目所有题都往同一批宽泛知识点上带。
- 排序分 = 0.85*余弦 + 0.15*「知识点名在题干/选项里原样出现」加成；**阈值只卡余弦**，
  这样 weight 列存的是真实语义相似度。实测该加成为 74 道已有标签题带来
  ~58% → ~78% 的 top1 一致率。
- 只算题干 + 选项，**不用答案/解析**（答案列不参与 embedding，避免泄题式匹配）。
- 余弦 < 阈值不写库，只记「待人工」，宁缺勿错。

### 写库行为（幂等）
- ``quiz_questions.knowledge_point``：仅在该列**原本为空**时写入 top1 名称，不覆盖已有值。
- ``question_knowledge_links``：先按 (question_id, knowledge_point_id) 删除再插入
  （表上有 uq_qkl 唯一约束），因此重复执行结果一致。
- role 只能取 ``primary`` / ``secondary``——DB 约束 ck_qkl_role 明确限定，无法写
  ``semantic``；语义来源由 ``weight``（相似度）+ ``is_verified=false`` 表达。

用法：
    python scripts/backfill_quiz_kp_semantic.py --dry-run
    python scripts/backfill_quiz_kp_semantic.py --dry-run --threshold 0.62
    python scripts/backfill_quiz_kp_semantic.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402
from services.embedding_service import (  # noqa: E402
    generate_local_embeddings,
    get_local_model_info,
)

DEFAULT_THRESHOLD = 0.70
#: 需求里的默认阈值是 0.62，但 2026-10-20 dry-run 实测 0.62-0.66 这一段
#: 人工抽查准确率只有三到四成（相角裕量→arccos(x)、开环增益→递增函数 之类），
#: 0.66-0.70 约五成，0.70 以上才稳定在七成以上，故默认取 0.70；
#: 需要更高覆盖时用 --threshold 0.62 显式降级。
MIN_POOL_SIZE = 30
KP_DESC_CHARS = 150
MAX_QUESTION_CHARS = 800
MIN_CJK_CHARS = 8
BATCH = 64
#: 名称在题干/选项里**原样出现**时给排序分的加成权重（只影响排序，不作阈值）。
#: 实测（74 道已有标签题回测）：纯余弦 top1 与人工标签软一致率约 58%，
#: 加 15% 名称命中加成后升到 78%，且几乎不损失覆盖（72/74 仍入选）。
NAME_HIT_WEIGHT = 0.15

#: 过于宽泛的知识点名：任何题干都可能「命中」，挂上去就是假关联（与
#: scripts/backfill_quiz_kp_text.py 的 STOP_NAMES 同源，只在完全同名时剔除）。
GENERIC_NAMES = {
    "函数", "连续", "极限", "概率", "矩阵", "向量", "导数", "积分", "级数",
    "电路", "电压", "电流", "电阻", "功率", "逻辑", "系统", "信号",
    "分析", "计算", "方法", "定理", "定义", "概念", "原理", "性质",
    "条件", "问题", "应用", "作用", "意义", "关系", "结构", "分类",
    "步骤", "内容", "特征", "基础", "理论", "模型", "公式", "方程",
    "运算", "求解", "结论", "总结", "概述", "引言", "小结",
}


def cjk_len(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def option_text(options) -> str:
    """jsonb options -> 纯选项文本（丢弃 A/B/C/D 键，避免噪声）。"""
    if not options:
        return ""
    if isinstance(options, str):
        import json

        try:
            options = json.loads(options)
        except Exception:
            return options
    if isinstance(options, dict):
        options = list(options.values())
    parts = []
    for opt in options:
        if isinstance(opt, dict):
            parts.append(str(opt.get("text") or opt.get("content") or ""))
        else:
            parts.append(str(opt))
    return " ".join(p.strip() for p in parts if p and p.strip())


def embed(texts: list[str]) -> np.ndarray:
    """批量编码并 L2 归一化（余弦 = 内积）。"""
    out: list[np.ndarray] = []
    for i in range(0, len(texts), BATCH):
        out.extend(generate_local_embeddings(texts[i:i + BATCH]))
    arr = np.asarray(out, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def load_data(cur):
    cur.execute("""
        SELECT id, name, subject, chapter, description
        FROM knowledge_points
        WHERE btrim(coalesce(name, '')) <> ''
    """)
    kps = []
    for kid, name, subject, chapter, desc in cur.fetchall():
        # 只用 name + description：把 chapter 拼进来会把「线性代数」「第一章」这类
        # 章节名变成通用语义锚点，实测会让同科目内所有题都被同一批宽泛知识点吸走。
        text = f"{name.strip()}。{(desc or '').strip()[:KP_DESC_CHARS]}"
        kps.append({
            "id": kid,
            "name": name.strip(),
            "subject": (subject or "").strip(),
            "chapter": chapter,
            "text": text,
        })

    cur.execute("""
        SELECT id, subject, content, options
        FROM quiz_questions
        WHERE btrim(coalesce(knowledge_point, '')) = ''
        ORDER BY id
    """)
    questions = []
    for qid, subject, content, options in cur.fetchall():
        body = (content or "").strip()
        opts = option_text(options)
        text = (body + " " + opts).strip()[:MAX_QUESTION_CHARS]
        questions.append({
            "id": qid,
            "subject": (subject or "").strip(),
            "content": body,
            "text": text,
            "cjk": cjk_len(body) + cjk_len(opts),
        })
    return kps, questions


def main() -> int:
    ap = argparse.ArgumentParser(description="题目知识点语义回填（bge-small-zh）")
    ap.add_argument("--dry-run", action="store_true", help="只打印样例，不写库（默认）")
    ap.add_argument("--apply", action="store_true", help="备份后写库")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"余弦相似度阈值，默认 {DEFAULT_THRESHOLD}")
    ap.add_argument("--min-pool", type=int, default=MIN_POOL_SIZE,
                    help="同科目知识点少于该数量则整科跳过（默认 %d，模拟电子技术仅 14 条）"
                         % MIN_POOL_SIZE)
    ap.add_argument("--no-backup", action="store_true", help="跳过备份（不建议）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 道（调试用）")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run
    if not args.apply and not args.dry_run:
        ap.error("必须指定 --dry-run 或 --apply")

    info = get_local_model_info()
    print(f"[model] {info['model_name']} dim={info['dim']} available={info['available']}")
    if not info["available"]:
        print("[FATAL] 本地 bge 模型不可用，终止（不联网、不下载）。")
        return 2

    with psycopg.connect(pg_database_url()) as conn:
        with conn.cursor() as cur:
            kps, questions = load_data(cur)
        if args.limit:
            questions = questions[:args.limit]

        print(f"[data] 知识点 {len(kps)} 条；空知识点题目 {len(questions)} 道")

        kp_idx_by_subject: dict[str, list[int]] = defaultdict(list)
        skipped_generic = 0
        for i, kp in enumerate(kps):
            if kp["name"] in GENERIC_NAMES:
                skipped_generic += 1
                continue
            kp_idx_by_subject[kp["subject"]].append(i)
        print(f"[pool] 剔除过泛知识点 {skipped_generic} 条（函数/电路/系统…）")
        thin = {s: len(v) for s, v in kp_idx_by_subject.items() if len(v) < args.min_pool}
        if thin:
            print("[pool] 知识点池过小、整科跳过（待补知识点数据）："
                  + "，".join(f"{s}({n}条)" for s, n in sorted(thin.items())))

        print("[encode] 知识点…")
        kp_vecs = embed([k["text"] for k in kps])
        print("[encode] 题目…")
        q_vecs = embed([q["text"] for q in questions])

        planned: list[dict] = []
        pending: list[dict] = []
        no_pool = 0
        for qi, q in enumerate(questions):
            idxs = kp_idx_by_subject.get(q["subject"], [])
            if not idxs:
                no_pool += 1
                pending.append({**q, "reason": f"科目「{q['subject']}」无知识点候选"})
                continue
            if len(idxs) < args.min_pool:
                pending.append({**q, "reason":
                                f"科目「{q['subject']}」知识点池仅 {len(idxs)} 条（< {args.min_pool}），"
                                "语义匹配不可靠，需先补知识点"})
                continue
            if q["cjk"] < MIN_CJK_CHARS:
                pending.append({**q, "reason": f"有效中文字符仅 {q['cjk']} 个，语义不足"})
                continue
            scores = kp_vecs[idxs] @ q_vecs[qi]
            names = [kps[i]["name"] for i in idxs]
            # 名称字面命中加成（题干+选项里原样出现知识点名）——只用于排序，
            # 阈值仍然卡**余弦**，这样 weight 列存的就是真实语义相似度。
            hits = np.array([1.0 if n and n in q["text"] else 0.0 for n in names], dtype=np.float32)
            rank = (1.0 - NAME_HIT_WEIGHT) * scores + NAME_HIT_WEIGHT * hits
            best = int(np.argmax(rank))
            score = float(scores[best])
            kp = kps[idxs[best]]
            if score >= args.threshold:
                planned.append({"q": q, "kp": kp, "score": score, "hit": bool(hits[best])})
            else:
                pending.append({**q, "reason": f"最高相似度 {score:.3f} < {args.threshold}",
                                "best_kp": kp["name"], "best_score": score})

        # ---- 统计 ----
        scores_all = np.array([p["score"] for p in planned]) if planned else np.array([])
        bins = [
            (">= 0.75", int((scores_all >= 0.75).sum())),
            ("0.70-0.75", int(((scores_all >= 0.70) & (scores_all < 0.75)).sum())),
            ("0.62-0.70", int(((scores_all >= 0.62) & (scores_all < 0.70)).sum())),
            ("0.55-0.62", int(((scores_all >= 0.55) & (scores_all < 0.62)).sum())),
            ("< 0.55", int((scores_all < 0.55).sum())),
        ]

        print(f"\n[result] 可写库 {len(planned)}/{len(questions)}"
              f"（{len(planned) / max(1, len(questions)):.1%}）；"
              f"待人工 {len(pending)}；无候选科目 {no_pool}")
        print("[dist] 命中余弦分布：" + "，".join(f"{k}: {v}" for k, v in bins))
        print(f"[dist] 其中知识点名在题干/选项里原样出现 {sum(1 for p in planned if p['hit'])} 道")

        by_subject_planned: dict[str, int] = defaultdict(int)
        by_subject_pending: dict[str, int] = defaultdict(int)
        for p in planned:
            by_subject_planned[p["q"]["subject"]] += 1
        for p in pending:
            by_subject_pending[p["subject"]] += 1
        print("[by-subject] " + "；".join(
            f"{s}: 命中 {by_subject_planned.get(s, 0)}/待人工 {by_subject_pending.get(s, 0)}"
            for s in sorted(set(by_subject_planned) | set(by_subject_pending))
        ))

        # ---- 样例 ----
        sample = sorted(planned, key=lambda p: -p["score"])[:15] + \
                 sorted(planned, key=lambda p: p["score"])[:15]
        seen = set()
        print("\n[sample] 前 30 条（高分 15 + 贴阈值 15）：")
        for p in sample:
            q, kp = p["q"], p["kp"]
            if q["id"] in seen:
                continue
            seen.add(q["id"])
            snippet = " ".join(q["content"].split())[:60] or "(题干为空)"
            tag = " [名称命中]" if p["hit"] else ""
            print(f"  q{q['id']:<4} [{q['subject']}] {snippet}")
            print(f"        → {kp['name']}  cos={p['score']:.3f}{tag}  kp#{kp['id']}")

        if pending:
            print("\n[pending] 待人工样例（含最高分候选，便于人工判断）：")
            for p in pending[:8]:
                snippet = " ".join((p["content"] or "").split())[:50]
                best = f"；最高候选「{p['best_kp']}」{p['best_score']:.3f}" if "best_kp" in p else ""
                print(f"  q{p['id']:<4} [{p['subject']}] {snippet} — {p['reason']}{best}")

        if not apply:
            print("\n[DRY-RUN] 未写库；加 --apply 执行。")
            return 0

        # ---- 写库 ----
        if not args.no_backup:
            from services.backup_service import create_backup

            path = create_backup()
            print(f"[backup] {path}")

        inserted = updated_q = 0
        with conn.cursor() as cur:
            for p in planned:
                qid, kp = p["q"]["id"], p["kp"]
                cur.execute(
                    "DELETE FROM question_knowledge_links"
                    " WHERE question_id = %s AND knowledge_point_id = %s",
                    (qid, kp["id"]),
                )
                cur.execute(
                    "INSERT INTO question_knowledge_links"
                    " (question_id, knowledge_point_id, role, weight, is_verified)"
                    " VALUES (%s, %s, 'primary', %s, false)",
                    (qid, kp["id"], round(p["score"], 4)),
                )
                inserted += 1
                cur.execute(
                    "UPDATE quiz_questions SET knowledge_point = %s"
                    " WHERE id = %s AND btrim(coalesce(knowledge_point, '')) = ''",
                    (kp["name"], qid),
                )
                updated_q += cur.rowcount
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("""
                SELECT count(*) FILTER (WHERE btrim(coalesce(knowledge_point, '')) <> ''),
                       count(*)
                FROM quiz_questions
            """)
            filled, total = cur.fetchone()
            cur.execute("SELECT count(DISTINCT question_id) FROM question_knowledge_links")
            linked = cur.fetchone()[0]
        print(f"\n[OK] 写入关联 {inserted} 条，回填题目文本 {updated_q} 道")
        print(f"[OK] knowledge_point: {filled}/{total}")
        print(f"[OK] 已关联题目: {linked}/{total}")
        print(f"[LEFT] 仍无知识点文本: {total - filled} 道")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
