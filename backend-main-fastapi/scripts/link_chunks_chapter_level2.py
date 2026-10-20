# -*- coding: utf-8 -*-
"""分块章节挂接二期：用「二级标记」给剩余无章节分块补 chapter_id（PG，幂等）。

### 背景
`scripts/link_chunks_chapter_propagate.py` 只认「第 X 章」，已挂 14,356/20,676。
剩余 6,320 块集中在没有章标记的讲义 / 题库 / 笔记里。

### 实测结论（2026-10-20）
高置信命中仅 116 块（占剩余 6,320 的 1.8%），远低于 5% 的验收线，
因此**未 apply**。剩下的块大多是扫描件 OCR 乱码（数电试题库 503 块、
数电期末题库 176 块）或「例 1.1 / 第 9 讲」编号的做题本，无法可靠定章。

### 本期规则（只在同一文档内生效，宁缺勿错）
1. **文件名强匹配章节**（最稳）：如「14.【第14节】电路定理二.pdf」→ 第4章 电路定理。
   要求文件名与章标题的二元组重合 ≥2 且唯一，且文档内标记不冲突。
2. **小节编号**：行首 `3.1` / `3.1.2`，首位数字即章号。
   - 只认行首（含换行后行首），要求编号后紧跟 2 个以上汉字标题，
     且不是 `例1.1` `图3-4` `7.5，得` 这类题号/引用/小数。
   - 标题必须与目标章标题有词面交集（≥2 个二元组；块首位置可放宽到 1）。
   - 该文档的编号必须能被「科目章节表」接住，否则整篇不认（防止把
     「第 9 讲」当成「第 9 章」）。
3. **章标记**：`第 N 章` 必须出现在块首 40 字内，用**标题相似度**校准到具体章节，
   不再按数字硬映射（避免「同济高数下册第 9 章」误挂到「ch09 向量与方程组」）。
4. **科目门槛**：只处理章节表是「教材式编号」的科目（数学 8 特判；其余要求
   至少 5 章且 50% 以上标题形如「第 N 章」）。政治/英语/真题的章节是课程大类，
   和书里的「第 N 章」无关，整科跳过。
5. **校准**：
   - 文件名含「线代 / 线性代数」且科目是数学 → 本地章号 + 线代偏移（6）；
   - 文件名含「概率」→ 数学章节表里没有概率章，整篇跳过；
   - 文件名含「做题本 / 八套卷 / 1000题 / 660 / 严选题」→ 章号是「例/讲」编号，
     整篇不认节号（这是本期最大的误挂来源）。
6. **传播（默认关闭）**：`--propagate` 才按 `chunk_index` 向后继承。
   实测该语料的分块经常跨章、且 OCR 页序错乱，传播会把「第 6 章」推到
   「第 1 章」的题上，因此不作为默认行为。
7. **节号（第 X 节）**：只计数供人工参考，不单独定章（不可靠）。

### 幂等
只处理 `chapter_id IS NULL` 的块；已有 chapter_id 的块既不覆盖，也不作为传播起点。

用法：
    python scripts/link_chunks_chapter_level2.py --dry-run
    python scripts/link_chunks_chapter_level2.py --dry-run --propagate   # 含继承，精度下降
    python scripts/link_chunks_chapter_level2.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402

# ---------------------------------------------------------------- 基础工具

CN_DIGIT = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
    "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
}

#: 全角数字 → 半角（康华光讲义里大量使用）
_FW_MAP = str.maketrans("０１２３４５６７８９．", "0123456789.")

#: 第 N 章 / CHAPTER N
RE_CHAPTER = re.compile(
    r"第\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*章"
    r"|CHAPTER\s*([0-9]{1,2})",
    re.IGNORECASE,
)
#: 小节编号：行首 3.1 / 3.1.2（只取前两段）
RE_SECTION = re.compile(
    r"(?:^|\n)[ \t]*([0-9]{1,2})\.([0-9]{1,2})(?![0-9.])[ \t]*([^\s0-9])"
)
#: 第 N 节（仅作校准用，不单独定章）
RE_JIE = re.compile(r"第\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*节")

#: 题号/图表/表格等非标题前缀（编号后紧跟这些字 → 不是小节标题）
BAD_HEAD_CHARS = set("例图题表式解答页注文个的是为得则应若且即可能并见设已求")
#: 标题截断符
TITLE_STOP = "。，,、；;：:？?！!（）()【】[]《》\n\t"

#: 这些文件名里的编号是「例 1.1 / 第 9 讲」，不是「第 9 章」
BAD_FILENAME_TOKENS = ("做题本", "八套卷", "1000题", "660", "严选题", "模拟卷", "预测卷", "真题卷")
#: 数学科目 id（含高数 6 章 + 线代 4 章，没有概率章）
MATH_SUBJECT_IDS = {8}
LINEAR_ALGEBRA_CHAPTERS = 4


def normalize(text: str) -> str:
    """全角数字/小数点转半角，便于统一正则。"""
    return (text or "").translate(_FW_MAP)


def is_cjk(ch: str) -> bool:
    return bool(ch) and "\u4e00" <= ch <= "\u9fff"


def heading_fragment(text: str, start: int, maxlen: int = 30) -> str:
    """截取标记后的标题片段（到标点/换行为止）。"""
    frag = text[start:start + maxlen]
    out = []
    for ch in frag:
        if ch in TITLE_STOP:
            break
        out.append(ch)
    return "".join(out).strip()


def bigrams(s: str) -> set[str]:
    """只取汉字二元组，用于标题相似度。"""
    chars = [c for c in s if is_cjk(c)]
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def chapter_core(title: str) -> str:
    """'高等数学·一元微分学' → '一元微分学'。"""
    return (title or "").split("·")[-1].strip()


def title_score(heading: str, title: str) -> int:
    return len(bigrams(heading) & bigrams(chapter_core(title)))


def looks_like_title(text: str, pos: int) -> bool:
    """编号后是否是一段像标题的汉字（≥2 个连续汉字，且不是题号/图表）。"""
    seg = text[pos:pos + 24]
    seg = seg.lstrip(" \t")
    if not seg or seg[0] in BAD_HEAD_CHARS or not is_cjk(seg[0]):
        return False
    run = 0
    for ch in seg:
        if is_cjk(ch):
            run += 1
        elif ch.isdigit() or ch in ".-" and run == 0:
            return False
        else:
            break
        if run >= 4:
            break
    return run >= 2


def is_toc_chunk(text: str) -> bool:
    """目录页（点线引导）不是正文，不挂章；但也不允许它当传播起点。"""
    return "......" in text or "．．．．" in text


# ---------------------------------------------------------------- 主流程


class ChapterIndex:
    def __init__(self, rows):
        # subject_id -> {chapter_no: (chapter_id, title)}
        self.by_no: dict[int, dict[int, tuple[int, str]]] = defaultdict(dict)
        self.by_id: dict[int, tuple[int, str]] = {}
        for cid, sid, code, title in rows:
            m = re.fullmatch(r"ch0*([0-9]{1,2})", (code or "").strip(), re.IGNORECASE)
            if m:
                self.by_no[sid][int(m.group(1))] = (cid, title or "")
                self.by_id[cid] = (sid, title or "")

    def get(self, sid: int, no: int):
        return self.by_no.get(sid, {}).get(no)

    def eligible(self, sid: int) -> bool:
        """该科目的章节是否「教材式编号」——只有这种才允许按数字映射。

        数学(8)的章节是主题式（高数 6 章 + 线代 4 章），单独放行；
        政治(10)/英语(9)/真题(54) 的章节是课程大类，和书里的「第 N 章」无关，
        必须整科跳过，否则「第十二章 生态文明」会被硬挂到「毛中特」。
        """
        if sid in MATH_SUBJECT_IDS:
            return True
        items = self.by_no.get(sid) or {}
        if len(items) < 5:
            return False
        numbered = sum(1 for _n, (_c, t) in items.items() if re.match(r"^第\s*\d+\s*章", t))
        return numbered / len(items) >= 0.5

    def match_title(self, sid: int, heading: str):
        """按标题相似度找章节；返回 (chapter_id, score, unique)。"""
        scored = []
        for no, (cid, title) in self.by_no.get(sid, {}).items():
            sc = title_score(heading, title)
            if sc:
                scored.append((sc, cid, no))
        if not scored:
            return None
        scored.sort(reverse=True)
        best = scored[0]
        unique = len(scored) == 1 or scored[1][0] < best[0]
        return best[1], best[0], unique


def doc_local_offset(doc_name: str, sid: int, chapters: ChapterIndex) -> int | None:
    """数学文档的本地章号偏移；返回 None 表示整篇不认节号。"""
    if sid not in MATH_SUBJECT_IDS:
        return 0
    name = doc_name or ""
    if "概率" in name:
        return None
    if "线代" in name or "线性代数" in name:
        total = len(chapters.by_no.get(sid, {}))
        return max(0, total - LINEAR_ALGEBRA_CHAPTERS)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="分块章节挂接二期（二级标记）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=10)
    ap.add_argument("--debug-doc", type=int, default=0, help="打印指定文档的挂接明细")
    ap.add_argument("--propagate", action="store_true",
                    help="允许文档内向后继承（默认关闭：OCR 题库顺序错乱时会被污染）")
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        ap.error("必须指定 --dry-run 或 --apply")

    with psycopg.connect(pg_database_url(), autocommit=False) as pg, pg.cursor() as cur:
        cur.execute(
            "SELECT id, subject_id, code, title FROM subject_chapters "
            "WHERE is_active IS NOT FALSE"
        )
        chapters = ChapterIndex(cur.fetchall())
        print(f"章节索引：{sum(len(v) for v in chapters.by_no.values())} 条")

        cur.execute("""
            SELECT k.id, k.document_id, k.chunk_index, k.subject_id, k.chapter_id,
                   d.file_name, k.text
            FROM knowledge_chunks k
            JOIN documents d ON d.id = k.document_id
            WHERE k.document_id IN (
                SELECT DISTINCT document_id FROM knowledge_chunks WHERE chapter_id IS NULL
            )
            ORDER BY k.document_id, k.chunk_index
        """)
        rows = cur.fetchall()
        print(f"涉及文档：{len({r[1] for r in rows})} 篇，分块：{len(rows)}")

        updates: dict[int, tuple[int, str, int]] = {}
        stats = Counter()
        per_rule = Counter()
        per_doc = Counter()
        samples: list[tuple[int, int, str, str]] = []
        debug_rows: list[tuple[int, int | None, str, str]] = []
        cur_doc = None
        offset: int | None = 0
        doc_name = ""
        doc_markers: list[tuple[int, int, str]] = []   # (chunk_id, chapter_id, rule)
        doc_rows: list[tuple[int, int | None]] = []     # (chunk_id, own chapter)
        file_chapter: int | None = None                 # 文件名强匹配到的章节

        def flush_doc() -> None:
            """文档扫完后统一决策。

            - 文件名强匹配章节（如「…电路定理二.pdf」）且文档内标记不冲突
              → 整篇同章，可挂全篇；这是电路/高数单节讲义最稳的信号。
            - 否则只挂「本块自带标记」的块；`--propagate` 才允许向后继承。
            """
            if not doc_rows:
                return
            prop = args.propagate and len({m[1] for m in doc_markers}) >= 2
            use_file = (
                file_chapter is not None
                and all(ch is None or ch == file_chapter for _c, ch in doc_rows)
            )
            if use_file:
                for cid, ch in doc_rows:
                    if ch is None:
                        updates[cid] = (file_chapter, "filename", 0)
                        per_rule["filename"] += 1
                        per_doc[cur_doc] += 1
            elif prop:
                current = None
                for cid, ch in doc_rows:
                    if ch is not None:
                        current = ch
                        continue
                    if current is not None:
                        updates[cid] = (current, "propagate", 0)
                        per_rule["propagate"] += 1
                        per_doc[cur_doc] += 1
            for cid, ch, rule in doc_markers:
                updates[cid] = (ch, rule, 0)
                per_rule[rule] += 1
                per_doc[cur_doc] += 1
            if args.debug_doc and cur_doc == args.debug_doc:
                print(f"\n[debug] doc {cur_doc} markers={len(doc_markers)} "
                      f"file_chapter={chapters.by_id[file_chapter][1] if file_chapter else '-'} "
                      f"prop={prop}")
                for cid, ch, rule, snip in debug_rows:
                    tag = chapters.by_id[ch][1] if ch else "-"
                    assigned = updates.get(cid)
                    mark = "*" if assigned else " "
                    if assigned and rule == "":
                        tag = chapters.by_id[assigned[0]][1]
                        rule = assigned[1]
                    print(f"  {mark}{cid:<6} [{rule or 'prop':9s}] {tag}  | {snip[:36]}")

        for cid, doc_id, idx, sid, existing_chapter, fname, text in rows:
            if doc_id != cur_doc:
                flush_doc()
                cur_doc = doc_id
                doc_name = fname or ""
                offset = doc_local_offset(doc_name, sid, chapters) if sid else None
                file_chapter = None
                if sid and chapters.eligible(sid) and not any(
                    tok in doc_name for tok in BAD_FILENAME_TOKENS
                ):
                    hit = chapters.match_title(sid, doc_name)
                    if hit and hit[1] >= 2 and hit[2]:
                        file_chapter = hit[0]
                        stats["file_chapter_doc"] += 1
                doc_markers = []
                doc_rows = []
                debug_rows = []
                stats["docs"] += 1

            if existing_chapter is not None:
                # 老传播法留下的结果可信度存疑（会把章首标记一路推到文末），
                # 既不覆盖也不拿它当新传播的起点，避免把老错误放大。
                continue

            raw = normalize(text)
            own: int | None = None
            rule = ""

            if sid is None:
                doc_rows.append((cid, None))
                continue
            if not chapters.eligible(sid):
                stats["subject_skipped"] += 1
                doc_rows.append((cid, None))
                continue

            bad_doc = any(tok in doc_name for tok in BAD_FILENAME_TOKENS)
            toc = is_toc_chunk(raw)

            # --- 规则 1：第 N 章（块首 200 字内，标题相似度校准）
            # 分块常常跨章：前半段是上一章习题、后半段才是「第 7 章」新章标题。
            # 这里只取「离块首最近」的标记，深处的新章标题留给下一块自己识别。
            chapter_cand: tuple[int, int, str] | None = None  # (pos, chapter_id, rule)
            for m in RE_CHAPTER.finditer(raw[:120]):
                if m.start() > 40:
                    break
                no = m.group(1) or m.group(2)
                if no is None:
                    continue
                num = int(no) if no.isdigit() else CN_DIGIT.get(no)
                if not num:
                    continue
                heading = heading_fragment(raw, m.end())
                if len(heading) < 2:
                    continue
                hit = chapters.match_title(sid, heading)
                if hit and hit[1] >= 2 and hit[2]:
                    chapter_cand = (m.start(), hit[0], "chapter")
                    break
                # 标题对不上就退回「数字 + 同号章节」的同名一致性校验
                cand = chapters.get(sid, num)
                if cand and title_score(heading, cand[1]) >= 1:
                    chapter_cand = (m.start(), cand[0], "chapter")
                    break
                stats["chapter_reject"] += 1

            # --- 规则 2：行首小节编号 N.M（首位数字 = 章号）
            section_cand: tuple[int, int] | None = None
            if offset is not None and not bad_doc and not toc:
                for m in RE_SECTION.finditer(raw[:800]):
                    num = int(m.group(1))
                    if num < 1 or num > 30:
                        continue
                    if not looks_like_title(raw, m.start(3)):
                        stats["section_reject"] += 1
                        continue
                    local = num + (offset or 0)
                    cand = chapters.get(sid, local)
                    if not cand:
                        stats["section_out_of_range"] += 1
                        continue
                    heading = heading_fragment(raw, m.start(3))
                    # 标题必须和章节主题有交集，否则纯数字编号不可信
                    sc = title_score(heading, cand[1])
                    if sc >= 2 or (sc >= 1 and m.start() <= 20):
                        section_cand = (m.start(), cand[0])
                        break
                    stats["section_weak_title"] += 1

            # 两种标记都命中时，取离块首更近的那个（章标记同位置优先）
            if chapter_cand and (not section_cand or chapter_cand[0] <= section_cand[0]):
                own, rule = chapter_cand[1], chapter_cand[2]
            elif section_cand:
                own, rule = section_cand[1], "section"
            if own is not None:
                stats[rule + "_hit"] += 1

            # --- 规则 3：第 N 节（只作上下文确认，不单独定章）
            if own is None:
                m = RE_JIE.search(raw[:1200])
                if m:
                    stats["jie_seen"] += 1

            doc_rows.append((cid, own))
            if args.debug_doc and cur_doc == args.debug_doc:
                debug_rows.append((cid, own, rule, (text or "").replace("\n", " ")[:44]))
            if own is not None:
                doc_markers.append((cid, own, rule))
                if len(samples) < args.sample * 4:
                    samples.append((cid, own, rule, (text or "")[:60].replace("\n", " ")))

        flush_doc()

        total_null = sum(1 for r in rows if r[4] is None)
        linked_now = 0
        cur.execute("SELECT count(*) FILTER (WHERE chapter_id IS NOT NULL), count(*) FROM knowledge_chunks")
        linked_now, total = cur.fetchone()

        print("\n=== 命中统计 ===")
        print(f"待处理 NULL 块：{total_null}")
        for k in ("chapter_hit", "section_hit", "filename",
                  "chapter_reject", "section_reject",
                  "section_out_of_range", "section_weak_title", "jie_seen",
                  "subject_skipped"):
            print(f"  {k:22s} {stats.get(k, 0) if k != 'filename' else per_rule.get(k, 0)}")
        print(f"  {'propagate':22s} {per_rule.get('propagate', 0)}")
        gain = len(updates) / max(1, total_null)
        print(f"可挂接块数：{len(updates)}  "
              f"（占剩余未挂 {gain:.2%}，占总块 {len(updates) / max(1, total):.2%}）")
        print(f"预计总覆盖率：{(linked_now + len(updates)) / max(1, total):.2%}  "
              f"({linked_now + len(updates)}/{total})")

        print("\n=== 命中 top 文档 ===")
        doc_names = {r[1]: r[5] for r in rows}
        for doc_id, n in per_doc.most_common(12):
            print(f"  {n:4d}  doc {doc_id:<5} {(doc_names.get(doc_id) or '')[:50]}")

        print("\n=== 样例 ===")
        shown = 0
        for cid, ch, rule, snippet in samples:
            sid, title = chapters.by_id[ch]
            print(f"  chunk {cid:<6} [{rule:9s}] → {title}  | {snippet[:45]}")
            shown += 1
            if shown >= args.sample:
                break

        if args.dry_run:
            print("\n[DRY-RUN] 未写库；加 --apply 执行。")
            return 0

        if not updates:
            print("\n无可写入数据，退出。")
            return 0

        # ---- 写库前强制备份
        from services.backup_service import create_backup
        path = create_backup()
        print(f"\n[backup] {path}")

        BATCH = 1000
        items = [(ch, cid) for cid, (ch, _rule, _x) in updates.items()]
        total_written = 0
        for i in range(0, len(items), BATCH):
            chunk = items[i:i + BATCH]
            cur.executemany(
                "UPDATE knowledge_chunks SET chapter_id=%s, updated_at=now() "
                "WHERE id=%s AND chapter_id IS NULL",
                chunk,
            )
            total_written += cur.rowcount
            print(f"  写入 {total_written}/{len(items)}")
        pg.commit()

        cur.execute("SELECT count(*) FILTER (WHERE chapter_id IS NOT NULL), count(*) FROM knowledge_chunks")
        linked, alln = cur.fetchone()
        print(f"\n[OK] 分块章节覆盖：{linked}/{alln}（{linked / alln:.2%}）")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
