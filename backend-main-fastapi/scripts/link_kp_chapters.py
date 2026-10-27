# -*- coding: utf-8 -*-
"""知识点 → 章节挂接（knowledge_points.chapter_id 回填）。

匹配原则（宁缺勿滥，只挂唯一命中）：
  1. 标题核匹配：kp.chapter 去掉「第X章/节」前缀后的标题核（≥4 字），与章节标题核
     双向包含 或 字符 bigram 重合率达标 → 候选；同科内唯一最高分才挂。
  2. 小节号推断：「1.2.6 十进制编码」这类小节号，第一段就是章号 → 直接挂该章。
  3. 政治模块关键词： kp 标题含模块关键词（马原/习思想/史纲/思修/形势）唯一命中即挂。
  4. 纯章号（「第6章」，无标题核）与 OCR 噪声：一律不挂，留人工清单。

用法：
    python scripts/link_kp_chapters.py            # dry-run，只输出匹配统计与样例
    python scripts/link_kp_chapters.py --apply    # 落库（只更新 chapter_id/chapter）
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402
from pipeline.config import pg_database_url  # noqa: E402

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
          "八": 8, "九": 9, "十": 10}

# 政治模块关键词 → 章节标题关键词（chapters：马原/毛中特与习思想/史纲/思修/形势）
POLITICS_RULES = [
    ("马克思主义|唯物|辩证|剩余价值|认识论", "马克思主义基本原理"),
    ("习近平|新思想|中国特色|毛中特|四个全面|五位一体|人民为中心|社会主义", "毛泽东思想和中国特色社会主义理论体系"),
    ("史纲|近现代|辛亥|五四|建党|抗战", "中国近现代史纲要"),
    ("思修|法治|宪法|道德|人生观|价值观", "思想道德与法治"),
    ("形势|政策|热点|时政", "形势与政策"),
]

_NUM_FULL = re.compile(r"第\s*([0-9一二三四五六七八九十]+)\s*章")
_SEC_FULL = re.compile(r"第\s*([0-9一二三四五六七八九十]+)\s*节")
_SUB_NUM = re.compile(r"^(\d+)(?:\.\d+)+")          # 1.2.6 → 章 1
_NOISE_RE = re.compile(r"^[\s0-9.。,，、;；:：!！?？\-—~×xXoOIll]+$")


def cn2int(s: str) -> int | None:
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in CN_NUM:
        return CN_NUM[s]
    if s.startswith("十") and len(s) == 2:
        return 10 + CN_NUM.get(s[1], 0)
    if s.endswith("十") and len(s) == 2:
        return CN_NUM.get(s[0], 0) * 10
    if "十" in s and len(s) >= 3:
        a, _, b = s.partition("十")
        return CN_NUM.get(a, 0) * 10 + CN_NUM.get(b, 0)
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or ""))


def parse_kp_chapter(raw: str) -> dict:
    """解析 kp.chapter → {num, core, subnum, noise}"""
    t = _norm(raw or "")
    if not t or _NOISE_RE.match(t):
        return {"num": None, "core": "", "subnum": None, "noise": True}
    num = None
    core = t
    m = _NUM_FULL.search(t)
    if m:
        num = cn2int(m.group(1))
        core = t[m.end():]
    elif _SEC_FULL.search(t):
        # 第X节 → 章号未知，交给标题核；剥前缀
        m2 = _SEC_FULL.search(t)
        core = t[m2.end():]
    else:
        m3 = _SUB_NUM.match(t)
        if m3:
            return {"num": int(m3.group(1)), "core": t[m3.end():], "subnum": True, "noise": False}
        m4 = re.match(r"^([0-9一二三四五六七八九十]+)[、.．]", t)
        if m4:
            num = cn2int(m4.group(1))
            core = t[m4.end():]
    core = core.strip("。 ，,、;；:：-—()（）·.．")
    if _NOISE_RE.match(core) or (len(core) < 4 and num is None):
        core = ""
    return {"num": num, "core": core, "subnum": False, "noise": False}


def chapter_core(title: str) -> tuple[int | None, str]:
    """章节表 title（如「第1章 数制和码制」）→ (num, core)"""
    t = _norm(title)
    m = _NUM_FULL.search(t)
    if m:
        return cn2int(m.group(1)), t[m.end():]
    m = re.match(r"^ch0*(\d+)", t)
    if m:
        return int(m.group(1)), t[m.end():].strip("·.．")
    return None, t


def bigram_sim(a: str, b: str) -> float:
    if len(a) < 2 or len(b) < 2:
        return 1.0 if (a and b and (a in b or b in a)) else 0.0
    ga = {a[i:i + 2] for i in range(len(a) - 1)}
    gb = {b[i:i + 2] for i in range(len(b) - 1)}
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    return inter / min(len(ga), len(gb))


def main() -> int:
    apply = "--apply" in sys.argv
    conn = psycopg.connect(pg_database_url())
    with conn.cursor() as cur:
        cur.execute("""SELECT s.name, s.id, c.id, c.title FROM subject_chapters c
                       JOIN subjects s ON c.subject_id = s.id WHERE c.is_active ORDER BY s.name, c.sort_order""")
        chapters_by_subject: dict[str, list] = {}
        for sname, sid, cid, title in cur.fetchall():
            n, core = chapter_core(title)
            chapters_by_subject.setdefault(sname, []).append(
                {"id": cid, "num": n, "core": _norm(core), "title": title})

        cur.execute("""SELECT id, subject, COALESCE(chapter,'') FROM knowledge_points
                       WHERE chapter_id IS NULL ORDER BY id""")
        kps = cur.fetchall()

        stats: Counter[str] = Counter()
        updates: list[tuple[int, int, str]] = []
        unmatched: list[tuple[int, str, str]] = []
        for kid, subject, raw in kps:
            info = parse_kp_chapter(raw)
            if info["noise"]:
                stats["噪声跳过"] += 1
                unmatched.append((kid, raw, "噪声"))
                continue
            chs = chapters_by_subject.get(subject or "", [])
            if not chs:
                stats["无同科章节"] += 1
                unmatched.append((kid, raw, f"无同科章节({subject})"))
                continue

            # —— 政治模块关键词 ——
            if subject == "政治" and info["core"]:
                hits = {c["id"]: c for c in chs
                        for pat, key in POLITICS_RULES
                        if re.search(pat, info["core"]) and key in c["title"]}
                if len(hits) == 1:
                    c = next(iter(hits.values()))
                    updates.append((kid, c["id"], c["title"]))
                    stats["政治规则挂接"] += 1
                    continue

            core = info["core"]
            # —— 1) 标题核匹配 ——
            if len(core) >= 4:
                scored = []
                for c in chs:
                    cc = c["core"]
                    if not cc:
                        continue
                    contain = (core in cc) or (cc in core)
                    sim = bigram_sim(core, cc)
                    if contain or sim >= 0.55:
                        scored.append((max(sim, 0.99 if contain else sim), c))
                if scored:
                    scored.sort(key=lambda x: -x[0])
                    if len(scored) == 1 or scored[0][0] - scored[1][0] > 0.15:
                        c = scored[0][1]
                        updates.append((kid, c["id"], c["title"]))
                        stats["标题核挂接"] += 1
                        continue
                    stats["多候选放弃"] += 1
                    unmatched.append((kid, raw, f"多候选：{[c['title'] for _, c in scored[:3]]}"))
                    continue

            # —— 2) 小节号推断（1.2.6 → 章1） ——
            if info["subnum"] and info["num"]:
                cand = [c for c in chs if c["num"] == info["num"]]
                if len(cand) == 1:
                    updates.append((kid, cand[0]["id"], cand[0]["title"]))
                    stats["小节号挂接"] += 1
                    continue

            stats["未匹配"] += 1
            unmatched.append((kid, raw, "无可靠信号"))

        print(f"知识点 {len(kps)} 个：拟挂接 {len(updates)}，明细 {dict(stats)}")
        show = Counter()
        for kid, raw, why in unmatched:
            key = why.split("：")[0]
            show[key] += 1
            if show[key] <= 8:
                print(f"  [未挂] kp#{kid} 「{(raw or '')[:36]}」 {why}")
        print("--- 拟挂接样例 ---")
        for kid, cid, title in updates[:15]:
            print(f"  kp#{kid} → ch#{cid} {title}")

        if apply and updates:
            cur.executemany(
                "UPDATE knowledge_points SET chapter_id=%s, chapter=%s WHERE id=%s",
                [(cid, title, kid) for kid, cid, title in updates])
            conn.commit()
            print(f"已落库 {cur.rowcount} 条")
        else:
            conn.rollback()
            print("dry-run：未写库（加 --apply 落库）")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
