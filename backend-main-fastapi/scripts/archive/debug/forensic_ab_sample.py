# -*- coding: utf-8 -*-
"""A/B 两类字母答案题的回源取证与清单落盘（只读，不写库）。

背景（team-lead 裁定）：
  * A 类 = options 为空的字母答案题（190 条）—— 唯一能解锁「第 2 处修复」的工作。
    需回答：原文档本来就没选项，还是真的丢了？丢了丢在哪一行？
  * B 类 = options 完好的字母答案题（285 条）—— 库内健康，**不需要重新切题、
    不需要隔离**，只需前端把 options 显示出来。落盘清单交前端。

输出：
  data/diagnostics/bclass_options_manifest.json   B 类完整清单
  stdout                                        A 类抽样统计 + B 类计数

用法：python scripts/forensic_ab_sample.py [--n 30]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import qbank_builder as qb  # noqa: E402
from services import extraction_noise as E  # noqa: E402

DB = r"D:\平台\database\kaoyan.db"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "diagnostics")

#: 答案形如 A/B/C/D（可含多个字母，如 ABC、AB）
_LETTER_ANS_RE = re.compile(r"^[A-F]{1,6}$")
_CN = re.compile(r"[^一-鿿]")
_OPT_LABEL_RE = re.compile(r"(?:^|[\s，,。；;：:、（(\[\]【】])[A-F]\s*[、.．)）]")

#: 宽松标签：无分隔符紧贴汉字（「A斯密特触发器」「D555定时器」）。
#: OCR/纯文本卷面里这种写法极常见，若只认严格标签会把「选项就在题干里」
#: 误判成「源文档无选项」。
_OPT_LABEL_LOOSE_RE = re.compile(
    r"(?:^|[\s，,。；;：:、（(\[\]【】])([A-F])(?=\s*[、.．)）]|[一-鿿0-9])"
)

#: 空格分隔的孤立字母标签（PDF/OCR 常见：「占空比为（） A B C D」）。
#: 仅当出现 >=3 个且按 A→B→C 递增时才算选项，避免把公式里的 A、B 当选项。
_OPT_SPACED_RE = re.compile(r"(?:^|\s)([A-F])(?=\s|$|\s)")

#: 依赖原书插图的题（如图 X 所示 / 见图 / 下图中）
_FIGURE_DEP_RE = re.compile(r"如图\s*\d|见图|下图中|图\s*\d+\s*所示|上图|右图|下图")


def cn_key(s: str, n: int = 10) -> str:
    return _CN.sub("", s or "")[:n]


def load_options(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


#: 下一个题号（1./1、/12．）——用于把回源片段截到本题边界，
#: 否则 500 字窗口会把下一题的选项一并计入，虚高「源文档有选项」。
_NEXT_QNUM_RE = re.compile(r"\n\s*\d{1,3}\s*[、.．)）]\s*")


def clip_to_question(seg: str) -> str:
    """把回源片段截到本题边界（下一个题号出现处）。"""
    m = _NEXT_QNUM_RE.search(seg)
    return seg[: m.start()] if m else seg


def label_count(text: str) -> int:
    """选项标签数，取三种口径的最大值（严格 / 紧贴汉字 / 空格分隔递增）。"""
    t = text or ""
    strict = len(_OPT_LABEL_RE.findall(t))
    loose = len(_OPT_LABEL_LOOSE_RE.findall(t))
    spaced = 0
    seq = [m.group(1) for m in _OPT_SPACED_RE.finditer(t)]
    run, expect = 0, 0
    for ch in seq:
        if ch == chr(ord("A") + expect):
            run += 1
            expect += 1
        elif ch == "A":
            run, expect = 1, 1
        else:
            run, expect = max(run, 0), 0
        spaced = max(spaced, run)
    return max(strict, loose, spaced)


def build_doc_index(db: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """返回 [(file_name, content, file_type)]，供题目回源。"""
    rows = db.execute(
        "SELECT file_name, content, file_type FROM documents WHERE length(content) > 0"
    ).fetchall()
    return [(r["file_name"] or "", r["content"] or "", r["file_type"] or "") for r in rows]


def find_source_doc(index, source: str, stem: str, content: str):
    """按 source 名优先、题干汉字键兜底，在源文档中定位题目片段。

    Returns ``(doc_name, doc_type, segment)``；找不到返回 ``("", "", "")``。
    """
    src = (source or "").split(":", 1)[-1]
    stemname = src.rsplit(".", 1)[0]

    # 1) 按 file_name 命中（stemname 足够长才用，避免误匹配）。
    #    source 写的是 .pdf 时，同名 .txt 版本往往才是真正入库的正文，故不限扩展名。
    if len(stemname) >= 6:
        cands = [t for (fn, t, ft) in index if stemname in fn]
        if cands:
            for n in (10, 8, 6, 4):
                key = cn_key(content, n)
                if len(key) < n:
                    break
                i = cands[0].find(key)
                if i >= 0:
                    for fn, t, ft in index:
                        if t is cands[0]:
                            return fn, ft, t[i: i + 500]
                    return "", "", ""

    # 2) 兜底：全库按题干汉字键搜
    for n in (12, 10, 8, 6, 4):
        key = cn_key(content, n)
        if len(key) < n:
            continue
        for (fn, t, ft) in index:
            i = t.find(key)
            if i >= 0:
                return fn, ft, t[i: i + 500]
    return "", "", ""


def sec_type_at(doc_text: str, pos: int) -> str:
    sec = ""
    for ln in doc_text[:pos].splitlines():
        m = qb._SECTION_RE.match(ln.strip())
        if m and qb._is_real_section_title(m.group(1)):
            sec = qb._norm_section(m.group(1))
    return sec


def classify_a(q, doc_text: str, seg: str, sec: str) -> tuple[str, str]:
    """判定 A 类某条的性质，返回 (类别, 说明)。

    类别取值：
      no_option_src   源文档本就无选项（填空题/简答题/计算题）
      opt_lost_split  源文档有选项，但切题丢在「选项未切出」
      opt_lost_gate   源文档有选项，切出了但被闸门拦掉
      answer_trunc    题是填空/简答，真实问题是答案内容不全（非选项丢失）
      unlocated       源文档未匹配到，无法判定
    """
    n_src = label_count(clip_to_question(seg))
    # 先看题干字段本身：选项文字是否只是「混在 content 里没拆出去」
    n_content = label_count(clip_to_question(q["content"]))
    if n_content >= 2:
        return "opt_inline_in_content", (
            f"选项文字就在 content 里（{n_content} 个标签），只是没被拆到 options 字段 —— "
            "文字没丢，缺的是结构化；与 B 类的区别是 B 类已拆好、只差前端展示"
        )
    if not seg:
        # 未匹配到源文档时，若答案本身就是「正文误匹配」特征（多字母乱序、
        # 题干是知识点编号正文），归为伪答案而非选项丢失
        ans = (q["answer"] or "").strip()
        if len(ans) >= 3 and re.match(r"^\d+\.\d", (q["content"] or "").strip()):
            return "pseudo_letter_answer", (
                f"答案 {ans!r} 是切题时把正文误当答案（答案字母乱序无对应选项），"
                "题干本身是知识点正文 —— 既非选项丢失，也非答案内容不全"
            )
        return "unlocated", "源文档未匹配到该题，无法判定"

    if n_src >= 2:
        # 源文档有选项
        om = list(qb._OPTION_RE.finditer(seg))
        old_split = bool(om) and sec in ("选择", "多选", "判断")
        _, opts_new = E.split_stem_and_options(seg, sec)
        if old_split:
            return "opt_lost_gate", "源文档有选项且旧逻辑本可切出，但入库 options 为空 → 疑似闸门/入库环节丢失"
        if opts_new:
            return "opt_lost_gate", "源文档有选项，新逻辑可切出，入库却为空 → 疑似闸门/入库环节丢失"
        return "opt_lost_split", "源文档有选项但两道判据均未切出 → 切题阶段丢失"
    # 源文档无选项标签
    if sec and sec not in ("选择", "多选", "判断"):
        return "answer_trunc", f"源文档无选项（题型={sec}），真实问题是答案内容不全，非选项丢失"
    return "no_option_src", "源文档本就无选项"


def pos_ok(seg: str) -> bool:  # noqa: D401 - 占位，无副作用
    """占位：保留结构清晰，实际判定在 classify_a 内联完成。"""
    return bool(seg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30, help="A 类抽样条数")
    args = ap.parse_args()

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row

    rows = db.execute(
        "SELECT id, content, options, answer, source, subject, question_type, is_junk"
        " FROM quiz_questions WHERE is_junk=0"
    ).fetchall()

    a_cls, b_cls = [], []
    for r in rows:
        ans = (r["answer"] or "").strip()
        if not _LETTER_ANS_RE.match(ans):
            continue
        opts = load_options(r["options"])
        if opts:
            b_cls.append((r, opts))
        else:
            a_cls.append(r)

    print(f"字母答案题（is_junk=0）：{len(a_cls) + len(b_cls)}")
    print(f"  B 类 options 完好：{len(b_cls)}")
    print(f"  A 类 options 为空：{len(a_cls)}")

    # ---------- B 类清单落盘 ----------
    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {
        "生成说明": (
            "B 类 = quiz_questions 中答案为字母、且 options 字段完好的题。"
            "这些题在库里是健康的，**不需要重新切题、不需要隔离**，"
            "只需前端把 options 字段显示出来。"
        ),
        "总数": len(b_cls),
        "含选项题数": len(b_cls),
        "可见可答题会从": sum(1 for _ in b_cls) and 0,  # 占位，下面覆盖
        "条目": [],
    }
    manifest.pop("可见可答题会从")
    for r, opts in b_cls:
        manifest["条目"].append({
            "id": r["id"],
            "题干": r["content"],
            "options": opts,
            "answer": r["answer"],
            "subject": r["subject"],
            "source": r["source"],
        })
    path = os.path.join(OUT_DIR, "bclass_options_manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\nB 类清单已落盘：{path}（{len(b_cls)} 条）")

    # ---------- A 类抽样回源 ----------
    index = build_doc_index(db)
    # 分层抽样：.txt / .pdf 两通道，各占一半；真题: / 知识库: 两入库通道各占一半
    def chan(src: str) -> str:
        s = (src or "")
        if s.startswith("真题:"):
            return "真题"
        if s.startswith("知识库:"):
            return "知识库"
        return "其他"

    def ftype(src: str) -> str:
        s = (src or "").split(":", 1)[-1].rsplit(".", 1)[-1].lower()
        return s if s in ("txt", "pdf") else "其他"

    buckets: dict[tuple[str, str], list] = {}
    for r in a_cls:
        buckets.setdefault((ftype(r["source"]), chan(r["source"])), []).append(r)

    target_total = min(args.n, len(a_cls))
    per = max(1, target_total // max(1, len(buckets)))
    sample = []
    for k in sorted(buckets):
        sample.extend(buckets[k][:per])
    sample = sample[:target_total]

    print(f"\nA 类抽样 {len(sample)} 条 / 覆盖 {len(buckets)} 个 (文件类型 × 入库通道) 组合：")
    for k in sorted(buckets):
        print(f"    {k}: 池 {len(buckets[k])} 条，抽样 {min(per, len(buckets[k]))} 条")

    stats: dict[str, int] = {}
    details = []
    for r in sample:
        doc_name, doc_type, seg = find_source_doc(index, r["source"], None, r["content"])
        sec = ""
        if seg:
            full = None
            for (fn, t, ft) in index:
                if fn == doc_name:
                    full = t
                    break
            if full:
                key = cn_key(r["content"], 10)
                pos = full.find(key) if key else -1
                sec = sec_type_at(full, pos) if pos >= 0 else ""
        cat, why = classify_a(r, "", seg, sec)
        stats[cat] = stats.get(cat, 0) + 1
        details.append({
            "id": r["id"], "cat": cat, "why": why, "sec": sec,
            "doc": doc_name, "src_label": label_count(seg),
            "题干": r["content"][:60], "答案": r["answer"],
        })
        print(f"\n  #{r['id']} [{cat}] sec={sec!r} 源选项标签={label_count(seg)} doc={doc_name[:34]}")
        print(f"      {why}")
        print(f"      题干: {r['content'][:64]}")

    print("\n" + "=" * 70)
    print("A 类抽样结论：")
    tot = max(1, len(sample))
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"    {k:16s} {v:3d} 条  {v * 100.0 / tot:5.1f}%")
    lost = sum(v for k, v in stats.items() if k.startswith("opt_lost"))
    print(f"    → 真·选项丢失合计 {lost} 条 = {lost * 100.0 / tot:.1f}%")

    # ---------- 附：8 组「如图X所示」题现状（team-lead 上一轮【五】遗留）----------
    fig_rows = db.execute(
        "SELECT id, content, options, answer, is_junk FROM quiz_questions"
        " WHERE is_junk=0 AND content LIKE '%如图%'"
    ).fetchall()
    fig_dep = [r for r in fig_rows if _FIGURE_DEP_RE.search(r["content"] or "")]
    print("\n" + "=" * 70)
    print(f"依赖原书插图的题（如图/见图/下图）：is_junk=0 共 {len(fig_dep)} 条")
    have_ans = sum(1 for r in fig_dep if (r["answer"] or "").strip())
    print(f"    其中有答案：{have_ans} 条（{have_ans * 100.0 / max(1, len(fig_dep)):.1f}%）")

    out = {
        "a_class_total": len(a_cls),
        "b_class_total": len(b_cls),
        "a_sample_size": len(sample),
        "a_sample_stats": stats,
        "b_manifest_path": path,
        "figure_dependent": {
            "total": len(fig_dep),
            "has_answer": have_ans,
            "ids": [r["id"] for r in fig_dep][:60],
        },
    }
    p2 = os.path.join(OUT_DIR, "ab_forensic_summary.json")
    with open(p2, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n汇总落盘：{p2}")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
