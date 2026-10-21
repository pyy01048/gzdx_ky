"""修复题库解析（``quiz_questions.analysis``）的「跨题边界错位」。

背景
----
题库共 386 道题，其中 **12 道**的解析字段把**下一道题**的整块内容（题干 +
选项 + ``【答案】`` + ``【解析】``）吞了进来。实测样例（id=154，313 字）：:

    本题运用排除法，取$f(x) = |x|, f(0) = 0$，但$f ^ { \\prime } ( 0 )$不存在……
    \\left(1+h\\right)}=f^{\\prime}\\left(0\\right)$存在．
    9．[[F:5230]]          ← 下一题（第 9 题）的题干从这里开始
    【答案】B查看答案       ← 下一题的答案
    【解析】逐次求导，      ← 下一题的解析

最夸张的是 id=200：一条 1373 字的「解析」里吞了后面 5 道题（7~11 题）。
解析是用户刷题时直接读的，错位等于把别人的答案摆在本题目下面，必须修。

## 三种坏法（不能一刀切，先分类再动手）

**一、截断型**（多数）。从某个位置往后的整块内容都属于下一题，正确做法是
把那一整块砍掉、保留前面本题的解析。起始位置通常是行首/空白后的题号
（``9．`` ``2.`` ``13.``）、章节标题（``二、多项选择题``），个别题目题号在
入库时丢了，只剩 ``【答案】`` 或 ``【解析】`` 裸开头。

> 判据（**这条最关键**）：准备砍掉的那一段里必须含 ``【答案】`` 或
> ``【解析】`` 或 ``查看答案``。因为正常解析里也有「1. 2. 3.」这类编号步骤，
> 一律按题号砍会把真解析砍断——宁可不修，也不能砍错。

**二、只剩解析型**。``analysis`` 前面那截其实是**本题的题干/选项**（不是解析），
或者混进了上一题解析的尾巴，真正的解析在最后一个 ``【解析】`` 之后。

> 判据：``【解析】`` 之前的文本 < 20 字（像被切碎的题干），**或者** 那截里出现
> ≥2 个选项行（``A．`` ``B．``…）且本题 ``content`` 的开头确实出现在其中
> （用题干正文做交叉验证，避免把「下一题的选项」误认成「本题的题干」）。

**三、多余标记型**。``【解析】`` 是插在句子中间的多余标记，**两边都是真解析**，
只需要删掉这个标记、两边都保留：

    方法一：分别在[a，c]，[c，b]上用拉格朗日中值定理……使得 【解析】 方法二：举例否定错误命题……

> 判据：全段只有 1 个 ``【答案】``/``【解析】`` 结构标记（即只有孤零零一个
> ``【解析】``），且它前后都 ≥ 20 字。

## 安全检查

* **默认干跑**，加 ``--apply`` 才写库；写库前先 ``create_backup()`` 并把备份
  路径打出来，出了问题能立刻回滚。
* 新文本长度为 0 或 < 10 字的一律 ``skip_too_short`` 跳过——**绝不写空解析**。
  空解析在前端就是一块空白，比错位的解析更让人困惑，也更难事后发现。

用法
----
```
python scripts/repair_quiz_analysis_boundary.py                # 干跑 12 条
python scripts/repair_quiz_analysis_boundary.py --quiz-id 268  # 只看一道
python scripts/repair_quiz_analysis_boundary.py --report out.json
python scripts/repair_quiz_analysis_boundary.py --apply        # 真写库
```
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 已实测确认的 12 道边界错位题。不放进 SQL 扫描、而是写死清单，是因为
# 「解析里出现题号」这个特征在正常解析里也大量存在（分步骤讲解），
# 全库扫描必然误伤；这 12 条是逐条比对过题干与解析内容的。
KNOWN_BAD_IDS: List[int] = [46, 54, 72, 120, 154, 194, 200, 249, 260, 262, 268, 300]

ANSWER_TAG = "【答案】"
ANALYSIS_TAG = "【解析】"
SEE_ANSWER = "查看答案"
# 砍掉的那一段必须含这三个之一，否则视为「正常编号步骤」，不砍
CUT_GUARD = (ANSWER_TAG, ANALYSIS_TAG, SEE_ANSWER)

MIN_KEEP_LEN = 10  # 新解析短于这个长度就跳过，绝不写空

_WS_RE = re.compile(r"\s+")
# 选项行：行首或空白后的 A．/B、/C. 之类
_OPTION_RE = re.compile(r"(?:^|(?<=\n)|[ \t　])([A-E])[．.、]")
# 题号边界：2. / 9． / 13、；以及章节标题「二、多项选择题」
_QNUM_RE = re.compile(
    r"(?:^|(?<=\n)|[ \t　])"
    r"(\d{1,2}[．.、]|[一二三四五六七八九十]{1,3}、)"
    r"[ \t　]*(?=[^\d]|$)"
)


def norm(text: str) -> str:
    """去掉所有空白（含全角空格），用于跨格式比对。"""
    return _WS_RE.sub("", (text or "").replace("　", ""))


def brief(text: str, limit: int = 120) -> str:
    """把多行片段压成一行预览，方便干跑时人工核对。"""
    t = (text or "").replace("\n", " ⏎ ")
    t = _WS_RE.sub(" ", t).strip()
    return t if len(t) <= limit else t[:limit] + "…"


def count_option_lines(text: str) -> int:
    return len({m.group(1) for m in _OPTION_RE.finditer(text or "")})


def head_holds_stem(content: str, head: str) -> bool:
    """判断 ``head`` 里是否混进了本题题干（而不是下一题的题干）。

    拿 ``content`` 开头 12 个非空白字符做探针：命中说明这段是**本题**题干，
    属于「只剩解析型」；不命中才可能真是下一题的整块内容，属于「截断型」。
    12 字足够长到不会撞车（数学/电路题干前 12 字基本唯一），也足够短到
    不怕题干中途丢公式。
    """
    probe = norm(content)[:12]
    return bool(probe) and probe in norm(head)


def classify(text: str, content: str) -> dict:
    """给一条解析判类并算出新文本。

    返回 dict: category / new_text / removed / boundary / note
    category ∈ {extra_marker, analysis_only, truncate, none}
    """
    text = text or ""

    # ---- 坏法三：多余标记型（只有孤立一个【解析】，两边都是真解析）----
    n_ans = text.count(ANSWER_TAG)
    n_ana = text.count(ANALYSIS_TAG)
    if n_ana == 1 and n_ans == 0:
        p = text.index(ANALYSIS_TAG)
        head, tail = text[:p], text[p + len(ANALYSIS_TAG):]
        if len(head.strip()) >= 20 and len(tail.strip()) >= 20:
            new_text = (head.rstrip() + "\n" + tail.lstrip()).strip()
            return {
                "category": "extra_marker",
                "new_text": new_text,
                "removed": ANALYSIS_TAG,
                "boundary": "孤立的【解析】标记",
                "note": "两边都是真解析，只删中间的多余标记",
            }

    # ---- 坏法二：只剩解析型（真解析在最后一个【解析】之后）----
    # 前提：这截「假解析」里**没有题号**。一旦出现 ``2.`` ``二、`` 这种题号，
    # 说明它其实是下一题的整块内容，该走截断型——否则会把下一题的解析留下、
    # 把本题正确的解析砍掉（id=46 就是这样：本题和第 2 题都是「LC 正弦波振荡
    # 电路」题干高度相似，只靠题干探针必然误判）。
    last = text.rfind(ANALYSIS_TAG)
    if last > 0 and not _QNUM_RE.search(text[:last]):
        head, tail = text[:last], text[last + len(ANALYSIS_TAG):]
        head_len = len(head.strip())
        opt_n = count_option_lines(head)
        stripped_head = head_len < 20
        flagged = stripped_head or (opt_n >= 2 and head_holds_stem(content, head))
        if tail.strip() and flagged:
            return {
                "category": "analysis_only",
                "new_text": tail.strip(),
                "removed": head,
                "boundary": "最后一个【解析】",

                "note": (
                    f"【解析】前只有 {head_len} 字，像被切碎的题干"
                    if stripped_head
                    else f"【解析】前有 {opt_n} 个选项行且命中本题题干"
                ),
            }

    # ---- 坏法一：截断型（砍掉下一题的整块内容）----
    cut = _find_cut(text)
    if cut:
        pos, boundary, removed = cut
        return {
            "category": "truncate",
            "new_text": text[:pos].strip(),
            "removed": removed,
            "boundary": boundary,
            "note": "砍掉下一题整块内容",
        }

    return {"category": "none", "new_text": text, "removed": "",
            "boundary": "", "note": "未命中任何错位特征，保持原样"}


def _find_cut(text: str):
    """找「下一题从哪里开始」，返回 (位置, 边界描述, 被砍掉的片段) 或 None。

    先找题号（信号最强）；题号在入库时丢了的情况下，退回用【答案】/【解析】
    裸开头做边界。无论哪种，**tail 里必须含 CUT_GUARD**，否则不认。
    """
    for m in _QNUM_RE.finditer(text):
        pos = m.start(1)
        if pos < MIN_KEEP_LEN:
            continue
        tail = text[pos:]
        if any(k in tail for k in CUT_GUARD):
            return pos, f"题号 {m.group(1)!r}", tail

    for tag in (ANSWER_TAG, ANALYSIS_TAG, SEE_ANSWER):
        p = text.find(tag)
        if p < MIN_KEEP_LEN:
            continue
        tail = text[p:]
        if any(k in tail for k in CUT_GUARD):
            return p, f"{tag}裸开头", tail
    return None


def repair_one(qid: int, text: str, content: str) -> dict:
    info = classify(text, content or "")
    new_text = info["new_text"]
    item = {
        "id": qid,
        "category": info["category"],
        "old_len": len(text or ""),
        "new_len": len(new_text or ""),
        "boundary": info["boundary"],
        "note": info["note"],
        "removed": brief(info["removed"]),
        "old_head": brief(text, 100) if info["category"] != "none" else "",
        "new_head": brief(new_text, 160),
        "status": "ok",
        "_new_text": new_text,  # 写库用全文，打印/报告前会被 pop 掉
    }
    if info["category"] == "none":
        item["status"] = "unclassified"
    elif item["new_len"] < MIN_KEEP_LEN:
        # 宁可留着错位的解析让人工看，也不写空解析
        item["status"] = "skip_too_short"
    return item


def main() -> int:
    ap = argparse.ArgumentParser(description="修复题库解析的跨题边界错位")
    ap.add_argument("--quiz-id", type=int, action="append", default=[],
                    help="只处理指定题（可多次；默认处理已确认的 12 道）")
    ap.add_argument("--apply", action="store_true", help="真写库（默认干跑）")
    ap.add_argument("--report", help="导出 JSON 报告")
    args = ap.parse_args()

    from database import SessionLocal
    from models import QuizQuestion

    qids = args.quiz_id or KNOWN_BAD_IDS
    db = SessionLocal()
    try:
        rows = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.id.in_(qids))
            .order_by(QuizQuestion.id)
            .all()
        )
        found = {q.id for q in rows}
        missing = [i for i in qids if i not in found]
        if missing:
            print(f"[警告] 库里没有这些题：{missing}")

        print(f"[修复] 待处理 {len(rows)} 道，模式={'写库' if args.apply else '干跑'}")
        results: List[dict] = []
        payload: dict = {}  # id -> 完整新文本（报告里只放预览，写库要全文）
        for i, q in enumerate(rows, 1):
            item = repair_one(q.id, q.analysis or "", q.content or "")
            results.append(item)
            payload[item["id"]] = item.pop("_new_text", "")
            print(
                f"\n[{i}/{len(rows)}] id={item['id']}  分类={item['category']}"
                f"  {item['old_len']} → {item['new_len']} 字  状态={item['status']}"
            )
            if item["category"] == "none":
                print(f"      {item['note']}")
                continue
            print(f"      边界: {item['boundary']}（{item['note']}）")
            print(f"      删/砍: {item['removed']!r}")
            print(f"      保留 : {item['new_head']!r}")

        # 分类统计
        buckets: dict = {}
        for r in results:
            buckets[r["category"]] = buckets.get(r["category"], 0) + 1
        shorts = [r["id"] for r in results if r["status"] == "skip_too_short"]
        print("\n[汇总] " + " / ".join(f"{k}={v}" for k, v in sorted(buckets.items())))
        print(f"[汇总] skip_too_short: {shorts or '无'}")

        if args.report:
            with open(args.report, "w", encoding="utf-8") as fh:
                json.dump(results, fh, ensure_ascii=False, indent=2)
            print(f"[修复] 报告已写 {args.report}")

        todo = [r for r in results if r["status"] == "ok"]
        if not todo:
            print("[修复] 没有可写的条目")
            return 0

        if not args.apply:
            print(f"\n[修复] 干跑结束，可写 {len(todo)} 道；加 --apply 才会写库")
            return 0

        from services.backup_service import create_backup

        backup = create_backup()
        print(f"[修复] 已备份: {backup}")

        n = 0
        for r in todo:
            q = db.get(QuizQuestion, r["id"])
            if not q:
                continue
            q.analysis = payload[r["id"]]
            db.commit()  # 逐条提交：中途失败不会把已修好的题一起回滚
            n += 1
        print(f"[修复] 已写库 {n} 道")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
