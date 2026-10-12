# -*- coding: utf-8 -*-
"""题目↔知识点关联回填 v3（M1-1，2026-10）。

与 v2 的关系：v2 主要服务「按规则补 related 链」，本脚本聚焦
**提升 knowledge_points 的覆盖率**（当前 1067 个知识点里仅约 300 个有链路，
导致全景页 `?kp_id=X` 返回 0 题而降级为章级刷题）。

三层策略（全部限定**同 subject**，优先**同 chapter**）：
  第 1 层 字面值精确：`quiz_questions.knowledge_point` == 知识点名（现有基线能力）
  第 2 层 字面值归一化：去空格 / 全半角统一 / 剥离括号内容后再比（救"卡诺图(化简)"等）
  第 3 层 题面整名命中：知识点**整名**出现在题干，且：
            - 题与知识点**章名都可信**时要求同章；
            - 否则要求整名长度 >= CONTENT_NAME_MIN_LEN；
            - 泛名（输出电压/放大倍数…）永不单独成链。

只写 `question_knowledge_links`；**不改动任何题目正文/答案**。
安全：默认 dry-run；--apply 前用 **SQLite backup() API** 备份（WAL 安全）；幂等可重跑。

用法：
    python scripts/backfill_kp_links_v3.py                 # 预览
    python scripts/backfill_kp_links_v3.py --sample 30     # 抽查
    python scripts/backfill_kp_links_v3.py --apply         # 写库（先备份）
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
DB_PATH = os.environ.get("DATABASE_PATH", "").strip() or os.path.join(
    os.path.dirname(BASE_DIR), "database", "kaoyan.db"
)
REPO_ROOT = os.path.dirname(BASE_DIR)

# --------------------------------------------------------------------------- #
# 可调参数
# --------------------------------------------------------------------------- #
CONTENT_NAME_MIN_LEN = 5      # 题面匹配：知识点整名最短长度（低于此不采信）
MAX_LINKS_PER_Q = 3           # 单题最多新增链路数（防一题挂满）
ROLE = "primary"              # 本脚本产出的链角色
WEIGHT_PRIMARY = 1.0

#: 泛名黑名单：这些名字几乎出现在每道题里，命中不足以证明"考了这个知识点"
GENERIC_NAMES = {
    "输出电压", "输入电压", "输出电压值", "放大倍数", "输入电阻", "输出电阻",
    "电压放大倍数", "电流放大倍数", "静态工作点", "频率响应", "通频带",
    "截止频率", "上限频率", "下限频率", "反馈", "电路", "信号", "电压", "电流",
}

#: chapter 是否"可信"（形如 第N章 xxx / 高等数学·xxx / 数据结构-xxx）。
#: 库里存在把题干片段误当 chapter 的知识点（如 "8.8 电路如图 P8.8 所示"），
#: 这类章值不能用于同章约束。
_TRUSTED_CHAPTER_RE = re.compile(r"^(第\s*\d+\s*章|[0-9]+\.\d+\s*[\u4e00-\u9fff]|[\u4e00-\u9fff]{2,}(·|-|—)[\u4e00-\u9fff]{2,})")

#: 题面匹配时，若**题目没有可信章值**，则要求更长的整名（<=5 字太容易偶然命中）
CONTENT_NAME_MIN_LEN_NO_CH = 6

# --------------------------------------------------------------------------- #
# 归一化
# --------------------------------------------------------------------------- #
_FULL2HALF = {ord(ch): ord(ch) - 0xFEE0 for ch in
              "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
              "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
              "０１２３４５６７８９"}
_BRACKET_RE = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]")


def normalize(text: str) -> str:
    """归一化：去空白 → 全角转半角 → 剥离括号内容 → 小写。

    例："卡诺图（化简）" → "卡诺图"；"Ｄ／Ａ 转换器" → "d/a转换器"。
    """
    if not text:
        return ""
    t = str(text).replace("\u3000", "").replace(" ", "").replace("\t", "")
    t = t.translate(_FULL2HALF)
    t = _BRACKET_RE.sub("", t)
    return t.strip().lower()


def compact(text: str) -> str:
    """仅去空白 + 全角转半角（保留括号内容，用于"整名出现在题干"判定）。"""
    if not text:
        return ""
    t = str(text).replace("\u3000", "").replace(" ", "").replace("\t", "")
    return t.translate(_FULL2HALF)


def trusted_chapter(ch: str | None) -> bool:
    """章名是否可信（可用于同章约束）。"""
    if not ch:
        return False
    return bool(_TRUSTED_CHAPTER_RE.match(str(ch).strip()))


# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #
def load_points(cur: sqlite3.Cursor) -> list[dict]:
    rows = cur.execute(
        "SELECT id, name, subject, chapter FROM knowledge_points "
        "WHERE name IS NOT NULL AND TRIM(name) != ''"
    ).fetchall()
    return [
        {"id": r[0], "name": str(r[1]).strip(), "norm": normalize(r[1]),
         "compact": compact(r[1]), "subject": r[2], "chapter": r[3],
         "chapter_trusted": trusted_chapter(r[3])}
        for r in rows
    ]


def load_questions(cur: sqlite3.Cursor, require_answer: bool) -> list[dict]:
    """只取**可作答**题目：排除 is_junk=1（端点已过滤，链了也没用）。"""
    sql = (
        "SELECT id, subject, chapter, knowledge_point, content, answer, is_junk "
        "FROM quiz_questions WHERE is_junk IS NULL OR is_junk = 0"
    )
    rows = cur.execute(sql).fetchall()
    out = []
    for r in rows:
        ans = (r[5] or "").strip()
        if require_answer and not ans:
            continue
        out.append({
            "id": r[0], "subject": r[1], "chapter": r[2],
            "kp_text": (r[3] or "").strip(),
            "content": compact(r[4] or ""),
            "chapter_trusted": trusted_chapter(r[2]),
        })
    return out


def load_alias() -> dict[str, list[str]]:
    """可选别名表：{知识点名小写: [别名, ...]}。文件不存在则为空。"""
    path = os.path.join(REPO_ROOT, "tools", "datasource", "kp_alias.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k.lower(): v for k, v in (data or {}).items() if isinstance(v, list)}
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# 覆盖率统计
# --------------------------------------------------------------------------- #
def coverage(cur: sqlite3.Cursor, require_answer: bool) -> tuple[int, int, float]:
    """返回 (有链路的知识点数, 知识点总数, 覆盖率%)。只统计**可作答**题。"""
    total = cur.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]
    cond = "q.is_junk IS NULL OR q.is_junk = 0"
    if require_answer:
        cond += " AND q.answer IS NOT NULL AND TRIM(q.answer) != ''"
    n = cur.execute(
        f"SELECT COUNT(DISTINCT l.knowledge_point_id) FROM question_knowledge_links l "
        f"JOIN quiz_questions q ON q.id = l.question_id WHERE {cond}"
    ).fetchone()[0]
    return n, total, (n / total * 100) if total else 0.0


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="题目↔知识点关联回填 v3")
    ap.add_argument("--apply", action="store_true", help="实际写库（默认仅预览）")
    ap.add_argument("--sample", type=int, default=20, help="抽查样例条数")
    ap.add_argument("--require-answer", action="store_true",
                    help="只统计/只链接有答案的题（更严的'可作答'口径）")
    ap.add_argument("--max-links-per-q", type=int, default=MAX_LINKS_PER_Q)
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    points = load_points(cur)
    questions = load_questions(cur, args.require_answer)
    alias = load_alias()

    cov_before, kp_total, cov_pct = coverage(cur, args.require_answer)
    existing = {(r[0], r[1]) for r in cur.execute(
        "SELECT question_id, knowledge_point_id FROM question_knowledge_links")}

    print(f"数据库: {DB_PATH}")
    print(f"知识点 {kp_total} 个 / 可作答题目 {len(questions)} 题 / 现有链路 {len(existing)} 条")
    print(f"回填前覆盖率（有链路知识点）：{cov_before}/{kp_total} = {cov_pct:.1f}%\n")

    # ---- 清洗：名字等于科目名的"知识点"不是真知识点（如 KP1119 就叫「数字电子技术」）----
    subject_names = {str(s[0]).strip() for s in cur.execute(
        "SELECT DISTINCT subject FROM knowledge_points WHERE subject IS NOT NULL")}
    subject_norms = {normalize(s) for s in subject_names}
    dropped = [p for p in points if p["norm"] in subject_norms]
    points = [p for p in points if p["norm"] not in subject_norms]
    if dropped:
        print(f"剔除「名字==科目名」的伪知识点 {len(dropped)} 个"
              f"（如 {dropped[0]['name']}）")

    # ---- 索引 ----
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for p in points:
        by_subject[p["subject"] or ""].append(p)
    norm_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for p in points:
        if p["norm"]:
            norm_index[(p["subject"] or "", p["norm"])].append(p)
        for al in alias.get(p["name"].lower(), []):
            na = normalize(al)
            if na:
                norm_index[(p["subject"] or "", na)].append(p)

    # ---- 三层匹配 ----
    new_links: list[tuple[int, int, str]] = []   # (qid, kpid, 层标记)
    stat = defaultdict(int)
    per_q: dict[int, int] = defaultdict(int)
    # 幂等：单题"已有链路数"也计入上限，否则每次重跑都会再补最多 N 条，永不收敛
    existing_per_q: dict[int, int] = defaultdict(int)
    for qid, _k in existing:
        existing_per_q[qid] += 1

    def q_full(qid: int) -> bool:
        """该题是否已达链路上限（已有 + 本次新增）。"""
        return existing_per_q.get(qid, 0) + per_q[qid] >= args.max_links_per_q

    for q in questions:
        if q_full(q["id"]):
            continue
        cand = by_subject.get(q["subject"] or "", [])

        # 第 1 层：字面值精确（同科同名）
        if q["kp_text"]:
            for p in cand:
                if p["name"] == q["kp_text"]:
                    if (q["id"], p["id"]) not in existing and not q_full(q["id"]):
                        new_links.append((q["id"], p["id"], "L1_字面值精确"))
                        per_q[q["id"]] += 1
                        stat["L1_字面值精确"] += 1
                    break

        # 第 2 层：字面值归一化（含别名、剥离括号）
        if q["kp_text"]:
            key = (q["subject"] or "", normalize(q["kp_text"]))
            for p in norm_index.get(key, []):
                if (q["id"], p["id"]) in existing or q_full(q["id"]):
                    continue
                # 泛名（放大倍数/输出电压…）即使字面值命中也不成链——同 L3 口径
                if p["name"] in GENERIC_NAMES or len(p["name"]) < 2:
                    continue
                # 同章优先：题章可信且知识点章可信但不相同 → 跳过
                if q["chapter_trusted"] and p["chapter_trusted"] and q["chapter"] != p["chapter"]:
                    continue
                new_links.append((q["id"], p["id"], "L2_字面值归一化"))
                per_q[q["id"]] += 1
                stat["L2_字面值归一化"] += 1

        # 第 3 层：题面整名命中
        text = q["content"]
        if not text:
            continue
        # 题目无可信章值时要求更长的整名，避免短名偶然命中
        need_len = CONTENT_NAME_MIN_LEN if q["chapter_trusted"] else CONTENT_NAME_MIN_LEN_NO_CH
        for p in cand:
            if q_full(q["id"]):
                break
            nm = p["compact"]
            if len(p["name"]) < need_len or not nm or nm not in text:
                continue
            if p["name"] in GENERIC_NAMES:
                continue
            if (q["id"], p["id"]) in existing:
                continue
            # 同章约束：两边章名都可信时必须一致
            if q["chapter_trusted"] and p["chapter_trusted"] and q["chapter"] != p["chapter"]:
                continue
            new_links.append((q["id"], p["id"], "L3_题面整名"))
            per_q[q["id"]] += 1
            stat["L3_题面整名"] += 1

    # ---- 去重（同一对可能多层命中）----
    seen = set()
    uniq_links = []
    for qid, kpid, layer in new_links:
        key = (qid, kpid)
        if key in seen or key in existing:
            continue
        seen.add(key)
        uniq_links.append((qid, kpid, layer))

    newly_kps = {k for _, k, _ in uniq_links}
    cov_after = len({r[0] for r in cur.execute(
        "SELECT DISTINCT knowledge_point_id FROM question_knowledge_links")} | newly_kps)
    # 按可作答口径重算（新增链路均指向可作答题，故直接相加安全的条件是题本身可作答）
    cov_after_strict = cov_before + len(newly_kps - {
        r[0] for r in cur.execute("SELECT DISTINCT knowledge_point_id FROM question_knowledge_links")})

    print("== 拟新增（dry-run）==")
    for layer, n in sorted(stat.items()):
        print(f"  {layer}: {n}")
    print(f"  去重后新增链路：{len(uniq_links)} 条")
    print(f"  新增覆盖知识点：{len(newly_kps)} 个")
    print(f"  覆盖率：{cov_before}/{kp_total} = {cov_pct:.1f}%  →  "
          f"{cov_after_strict}/{kp_total} = {cov_after_strict / kp_total * 100:.1f}%")

    if args.sample > 0 and uniq_links:
        print(f"\n----- 抽查样例（随机 {args.sample} 条）-----")
        kp_by_id = {p["id"]: p for p in points}
        q_by_id = {q["id"]: q for q in questions}
        random.seed(42)
        for qid, kpid, layer in random.sample(uniq_links, min(args.sample, len(uniq_links))):
            q = q_by_id.get(qid, {})
            p = kp_by_id.get(kpid, {})
            snippet = (q.get("content") or "")[:44]
            print(f"  [{layer}] Q{qid} → KP{kpid}「{p.get('name', '')}」"
                  f"（{p.get('chapter') or '-'}）")
            print(f"      「{snippet}」")

    # ---- 0 链路知识点清单 ----
    _write_zero_link_kps(cur, points, newly_kps, args.require_answer)

    if not args.apply:
        print("\n[DRY-RUN] 未写库。确认后加 --apply（会自动用 SQLite backup() 备份）。")
        con.close()
        return 0

    # ---- 备份（SQLite backup API，WAL 安全）----
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_kplink_v3_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    with sqlite3.connect(bak) as dest:
        con.backup(dest)
    print(f"\n已备份 → {bak}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.executemany(
        "INSERT INTO question_knowledge_links "
        "(question_id, knowledge_point_id, role, weight, is_verified, created_at) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        [(q, k, ROLE, WEIGHT_PRIMARY, now) for q, k, _ in uniq_links],
    )
    con.commit()

    cov_now, kp_tot, cov_now_pct = coverage(cur, args.require_answer)
    print("\n===== 写库完成 =====")
    print(f"新增链路 {len(uniq_links)} 条")
    print(f"覆盖率：{cov_before}/{kp_total} = {cov_pct:.1f}%  →  "
          f"{cov_now}/{kp_tot} = {cov_now_pct:.1f}%")
    con.close()
    return 0


def _write_zero_link_kps(cur: sqlite3.Cursor, points: list[dict],
                         newly: set[int], require_answer: bool) -> None:
    """产出回填后仍为 0 链路的知识点清单（CSV + JSON），供人工优先补齐。"""
    linked = {r[0] for r in cur.execute(
        "SELECT DISTINCT knowledge_point_id FROM question_knowledge_links")}
    zero = [p for p in points if p["id"] not in linked and p["id"] not in newly]
    out_dir = os.path.join(REPO_ROOT, "tools", "datasource")
    os.makedirs(out_dir, exist_ok=True)
    jpath = os.path.join(out_dir, "zero_link_knowledge_points.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(zero),
            "items": [{"id": p["id"], "name": p["name"], "subject": p["subject"],
                       "chapter": p["chapter"]} for p in zero],
        }, f, ensure_ascii=False, indent=2)
    cpath = os.path.join(out_dir, "zero_link_knowledge_points.csv")
    with open(cpath, "w", encoding="utf-8-sig") as f:
        f.write("id,name,subject,chapter\n")
        for p in zero:
            f.write(f'{p["id"]},{p["name"]},{p["subject"] or ""},{p["chapter"] or ""}\n')
    print(f"\n0 链路知识点清单（回填后仍为空）：{len(zero)} 个")
    print(f"  → {jpath}")
    print(f"  → {cpath}")


if __name__ == "__main__":
    raise SystemExit(main())
