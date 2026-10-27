# -*- coding: utf-8 -*-
"""把「配套题库」文档抽取出的选择题入库（PostgreSQL 版）。

由 scripts/import_exam_questions.py（SQLite 时代）移植到 PG 库 kaoyan：
数据源 documents、目标表 quiz_questions 均在 PG。质量门**原样保留**：

  1. 默认 dry-run；``--apply`` 才写库。写库前把 quiz_questions 现存行
     导出 JSONL 备份（insert-only 场景下的回退依据）。
  2. 候选文档筛选不变：documents 里 file_name LIKE '%配套题库%' OR '%真题精选%'
     且 content 长度 > 20000。
  3. 抽取率门：MIN_EXTRACTED=5、MIN_EXTRACT_RATE=0.05，不达标整篇跳过。
  4. 准确率门：题干/选项/答案错配率 > MAX_ANSWER_MISMATCH(0.01) 整篇拒绝。
  5. **按内容去重**：题干 + 选项文本指纹全同不重入（可重复执行）。
  6. 只插入，不修改、不删除任何已有行；单文档一事务，失败整篇回滚。
  7. 入库前逐题完整性自检（题干/选项/答案均须合规）。

字段映射（与 qa_foundation.import_qbank 的 PG 惯例对齐）：
  content=题干  options=[{key,text}] 规整数组（PG 触发器要求，dict 形态会炸）
  answer/analysis 原样  subject=文档 subject  question_type='single'
  answer_source='source_extract'  answer_confidence=0.85
  source_label=文档名  is_available=TRUE  is_junk=FALSE
  knowledge_point 留空（后续挂接管线负责）

凭据：从环境变量 / backend-main-fastapi/.env 读取 PG_*，不落任何明文密钥。

文本层归一化（2026-10-19 实测）：PG documents.content 是圣才 e-book 导出的
内联标签文本层（【答案】B查看答案 / 【解析】正文同行 / 题号题干同行），
与抽取器实测过的格式 A/B（标签独占行、答案独立成行）不同。本脚本在抽取
前用 normalize_exam_text() 做纯文本归一（只拆行/转全角字母，不改内容），
extract_from_text 本身只做了一处增量：SECTION_RE 小节词表补齐语料实测存在的
「分析计算题 / 计算分析题 / 解答题」三个非选择题小节名（否则选择题区不闭合）。
质量门与去重逻辑不受影响。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from pipeline.exam_bank_extractor import (  # noqa: E402
    ExtractStats,
    SECTION_RE,
    extract_from_text,
)

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DB_ROOT = BACKEND_ROOT.parent / "database"

#: 候选文档筛选：与 SQLite 版逐字一致
DOC_FILTER_SQL = """
    SELECT id, file_name, coalesce(nullif(subject, ''), '未分类') AS subject, content
    FROM documents
    WHERE (file_name LIKE '%配套题库%' OR file_name LIKE '%真题精选%')
      AND length(coalesce(content, '')) > 20000
    ORDER BY length(coalesce(content, '')) DESC
    LIMIT :limit
"""

#: 抽取率下限：低于此值说明文本层结构不可用，一律跳过
MIN_EXTRACT_RATE = 0.05
#: 最少抽取题数
MIN_EXTRACTED = 5
#: 答案与选项键的错配率上限（准确率红线：99%）
MAX_ANSWER_MISMATCH = 0.01
#: 单次最多处理的文档数
DEFAULT_DOC_LIMIT = 10

INSERT_SQL = """
    INSERT INTO quiz_questions
        (content, options, answer, analysis, subject, chapter, year, source_paper,
         source_label, question_type, answer_source, answer_confidence,
         is_available, is_junk)
    VALUES
        (:content, CAST(:options AS jsonb), :answer, :analysis, :subject, :chapter,
         :year, :source_paper, :source_label, 'single', 'source_extract', 0.85,
         TRUE, FALSE)
    RETURNING id
"""


# --------------------------------------------------------------------------- #
# 文本层归一化（PG 语料适配，2026-10-19 实测）
# --------------------------------------------------------------------------- #
# PG documents.content 与 SQLite 时代实测语料的文本层形态不同：圣才 e-book
# 导出把标签/答案/题号都内联在行内——
#     【答案】B查看答案        ← 标签+答案+水印同一行（10 篇中共 826 处，主流）
#     【解析】-6 的原码为……    ← 标签与正文同一行
#     1．十进制数(-6)10的…     ← 题号与题干同一行（全角『．』4985 处）
# 而 exam_bank_extractor 只认「标签独占行 + 答案独立成行」的实测格式 A/B。
# 此处把内联形态归一为抽取器已支持的形态：抽取器本身零改动，
# 质量门、去重与入库逻辑完全不受影响。题号行仅用全角『．』识别，
# 避免把正文里的小数（3.5V，半角点）误切。
ANSWER_INLINE_RE = re.compile(r"^【答案】\s*([Ａ-ＤA-D]{1,8})?\s*(?:查看答案)?\s*$")
ANALYSIS_INLINE_RE = re.compile(r"^【解析】(\S.*)$")
QNUM_INLINE_RE = re.compile(r"^(\d{1,3})\s*．\s*(\S.*)$")


def _fw_to_ascii(s: str) -> str:
    """全角 Ａ-Ｄ → ASCII（语料中存在少量『Ｄ查看答案』）。"""
    return "".join(chr(ord(ch) - 0xFEE0) if "Ａ" <= ch <= "Ｄ" else ch for ch in s)


def normalize_exam_text(content: str) -> str:
    """把圣才 e-book 内联标签文本层归一为抽取器的格式 A/B。

    纯函数：逐行重写，不改任何字符内容（只拆行 / 转全角字母 / 插空行硬边界）。
    空行硬边界的目的：抽取器的 _merge_fragmented_lines 会把以 -/＝/＋ 等开头的
    续行拼到上一行（PDF 碎片行重建逻辑）；本语料是规整整行，拼接全是有害的——
    以负号开头的解析行会拼进「【解析】」标签行、破坏答案邻接；以负号开头的
    题干会拼进上一题的解析尾。无法识别的行原样保留，交给抽取器与质量门。
    """
    out: list[str] = []

    def sep() -> None:
        """硬边界：阻断 _merge_fragmented_lines 的跨行拼接。"""
        if out and out[-1] != "":
            out.append("")

    for raw in (content or "").splitlines():
        s = raw.strip()
        if not s:
            sep()
            continue
        m = ANSWER_INLINE_RE.match(s)
        if m:
            out.append("【答案】")
            if m.group(1):
                # 答案字母必须与标签紧邻（抽取器格式 B 读 tag 的下一行）
                out.append(_fw_to_ascii(m.group(1)))
                sep()  # 防止后续解析正文拼到答案字母上
            continue
        m = ANALYSIS_INLINE_RE.match(s)
        if m:
            out.append("【解析】")
            out.append("")  # 解析正文不得拼到标签上
            out.append(m.group(1).strip())
            sep()
            continue
        m = QNUM_INLINE_RE.match(s)
        if m:
            out.append(m.group(1))  # 独立题号行 → 抽取器在此 flush 上一题
            out.append("")
            out.append(m.group(2).strip())
            sep()
            continue
        if SECTION_RE.match(s):
            out.append(s)
            continue  # 真小节标题后不加空行，避免 [""] 幻影块干扰抽取率
        out.append(s)
        sep()
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# 连接与凭据（全部脱敏输出）
# --------------------------------------------------------------------------- #
def _load_env_file() -> dict:
    env: dict = {}
    env_file = BACKEND_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def build_pg_url() -> tuple[str, str]:
    """返回 (sqlalchemy url, 脱敏展示串)。进程环境变量优先于 .env。"""
    cfg = {**_load_env_file(),
           **{k: v for k, v in os.environ.items() if k.startswith("PG_")}}
    url = (
        f"postgresql+psycopg://{cfg.get('PG_USER', 'kaoyan')}:"
        f"{cfg.get('PG_PASSWORD', '')}@{cfg.get('PG_HOST', '127.0.0.1')}:"
        f"{cfg.get('PG_PORT', '5432')}/{cfg.get('PG_DATABASE', 'kaoyan')}"
    )
    masked = (
        f"postgresql://{cfg.get('PG_USER', 'kaoyan')}:***@"
        f"{cfg.get('PG_HOST', '127.0.0.1')}:{cfg.get('PG_PORT', '5432')}/"
        f"{cfg.get('PG_DATABASE', 'kaoyan')}"
    )
    return url, masked


# --------------------------------------------------------------------------- #
# 去重指纹（与 SQLite 版逐字一致）
# --------------------------------------------------------------------------- #
def content_fingerprint(stem: str, options: list) -> str:
    """题干 + 选项文本指纹，用于跨文档去重。"""
    raw = stem.strip() + "|" + "|".join(
        (o["text"] if isinstance(o, dict) else str(o)).strip() for o in options
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _options_texts(raw) -> list:
    """兼容 jsonb（psycopg 反序列化为 list）/ JSON 字符串两种形态。"""
    if raw is None:
        return []
    opts = raw
    if isinstance(raw, str):
        try:
            opts = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(opts, list):
        return []
    texts = []
    for o in opts:
        if isinstance(o, dict):
            texts.append(str(o.get("text", "")).strip())
        elif isinstance(o, str):
            texts.append(o.strip())
    return texts


def load_existing_fingerprints(conn) -> set:
    """已入库题目的指纹集合（题干+选项）。"""
    got: set = set()
    for content, options in conn.execute(
        text("SELECT content, options FROM quiz_questions")
    ):
        got.add(content_fingerprint(content or "",
                                    [{"text": t} for t in _options_texts(options)]))
    return got


# --------------------------------------------------------------------------- #
# 质量门与候选构建
# --------------------------------------------------------------------------- #
def build_plan(conn, doc_limit: int) -> tuple[list, list]:
    """抽题 + 逐篇质量门判定（不写库）。返回 (通过文档的插入计划, 跳过文档)。"""
    existing = load_existing_fingerprints(conn)
    print(f"  库内已有题目指纹：{len(existing)}\n")

    plan: list = []
    skipped: list = []
    for row in conn.execute(text(DOC_FILTER_SQL), {"limit": doc_limit}):
        doc_id, file_name, subject, content = (
            row.id, row.file_name, row.subject, row.content or ""
        )
        # 判据是文件名后缀而非内容：PDF 碎片文本层与规整 TXT 层形态完全不同（实测）
        # 本批候选全为 .docx（内联标签文本层），先归一化再抽取。
        is_pdf = (file_name or "").lower().endswith(".pdf")
        stats: ExtractStats = extract_from_text(
            normalize_exam_text(content), chapter_hint="", is_pdf_layer=is_pdf
        )

        # ---- 门禁 1：抽取率过低 → 文本层结构不可用 ----
        rate = stats.extracted / max(stats.blocks_seen, 1)
        if stats.extracted < MIN_EXTRACTED or rate < MIN_EXTRACT_RATE:
            skipped.append({
                "doc_id": doc_id, "file_name": file_name,
                "extracted": stats.extracted, "blocks_seen": stats.blocks_seen,
                "rate": round(rate, 4),
                "reason": "抽取率过低（文本层换行不可靠）",
            })
            continue

        # ---- 门禁 2：准确率自检（用户红线 99%）----
        # 题干与选项错配、答案不在选项内 → 说明块切分错误，直接拒绝整篇
        bad = [q for q in stats.questions
               if not q.answer
               or not set(q.answer) <= {o["key"] for o in q.options}
               or len(q.stem) > 400]
        mismatch_rate = len(bad) / max(len(stats.questions), 1)
        if mismatch_rate > MAX_ANSWER_MISMATCH:
            skipped.append({
                "doc_id": doc_id, "file_name": file_name,
                "extracted": stats.extracted, "blocks_seen": stats.blocks_seen,
                "rate": round(rate, 4), "mismatch_rate": round(mismatch_rate, 4),
                "reason": (f"准确率不达标"
                           f"（错配 {mismatch_rate:.1%} > {MAX_ANSWER_MISMATCH:.0%}）"),
            })
            continue

        # ---- 门禁 3：内容指纹去重（跨文档 + 篇内）----
        rows, dup_cnt = [], 0
        multi_cnt = 0
        for q in stats.questions:
            if len(q.answer) > 1:
                multi_cnt += 1
            fp = content_fingerprint(q.stem, q.options)
            if fp in existing:
                dup_cnt += 1
                continue
            existing.add(fp)
            rows.append({
                "doc_id": doc_id,
                "content": q.stem,
                "options": q.options,
                "answer": q.answer,
                "analysis": q.analysis,
                "subject": subject,
                "chapter": q.chapter or None,
                "year": q.year,
                "source_paper": q.source_paper or None,
                "source_label": (file_name or "")[:200],
            })
        plan.append({
            "doc_id": doc_id, "file_name": file_name, "subject": subject,
            "extracted": stats.extracted, "blocks_seen": stats.blocks_seen,
            "rate": round(rate, 4), "mismatch_rate": round(mismatch_rate, 4),
            "dup_skipped": dup_cnt, "multi_answer": multi_cnt,
            "rows": rows,
            "samples": [
                {"stem": q.stem[:80], "answer": q.answer,
                 "options": {o["key"]: o["text"][:40] for o in q.options}}
                for q in stats.questions[:3]
            ],
        })
        print(f"  {stats.extracted:>4} 题 / 新增 {len(rows):>4}"
              f"（去重弃 {dup_cnt}，错配 {mismatch_rate:.1%}）  {file_name[:44]}")
    return plan, skipped


def self_check(r: dict) -> bool:
    """入库前逐题完整性自检（与抽取器 is_valid 同口径，缺一即拒）。"""
    opts = r["options"]
    return (len(r["content"].strip()) >= 6
            and len(opts) >= 2
            and all(isinstance(o, dict) and o.get("key") and str(o.get("text", "")).strip()
                    for o in opts)
            and bool(r["answer"])
            and set(r["answer"]) <= {o["key"] for o in opts})


# --------------------------------------------------------------------------- #
# 写库（--apply）：单文档一事务，失败整篇回滚
# --------------------------------------------------------------------------- #
def apply_plan(eng, plan: list) -> tuple[int, int]:
    inserted, failed_docs = 0, 0
    for p in plan:
        if not p["rows"]:
            continue
        try:
            with eng.begin() as conn:  # 单文档一事务：异常自动 ROLLBACK
                n = 0
                for r in p["rows"]:
                    if not self_check(r):
                        raise ValueError(
                            f"完整性自检未过：{r['content'][:40]!r}")
                    conn.execute(text(INSERT_SQL), {
                        "content": r["content"],
                        "options": json.dumps(r["options"], ensure_ascii=False),
                        "answer": r["answer"],
                        "analysis": r["analysis"],
                        "subject": r["subject"],
                        "chapter": r["chapter"],
                        "year": r["year"],
                        "source_paper": r["source_paper"],
                        "source_label": r["source_label"],
                    })
                    n += 1
            inserted += n
            print(f"  + {n:>4} 题  {p['file_name'][:44]}")
        except Exception as exc:  # noqa: BLE001
            failed_docs += 1
            print(f"  × 整篇回滚 {p['file_name'][:40]}：{str(exc)[:120]}")
    return inserted, failed_docs


def backup_quiz_questions(eng) -> tuple[str, int]:
    """写库前把 quiz_questions 现存行导出 JSONL（insert-only 的回退依据）。"""
    DB_ROOT.mkdir(exist_ok=True)
    target = DB_ROOT / f"quiz_questions_pg_backup_{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    n = 0
    with eng.connect() as conn:
        cols = ["id", "content", "options", "answer", "analysis", "subject",
                "question_type", "answer_source", "answer_confidence",
                "source_label", "is_available", "is_junk"]
        with target.open("w", encoding="utf-8") as fh:
            for row in conn.execute(text(
                    "SELECT " + ",".join(cols) + " FROM quiz_questions ORDER BY id")):
                fh.write(json.dumps(
                    {c: getattr(row, c) for c in cols},
                    ensure_ascii=False, default=str) + "\n")
                n += 1
    return str(target), n


# --------------------------------------------------------------------------- #
# 落库后复核
# --------------------------------------------------------------------------- #
def verify(eng, tag: str) -> dict:
    out: dict = {}
    with eng.connect() as conn:
        out["total"] = conn.execute(
            text("SELECT count(*) FROM quiz_questions")).scalar()
        out["by_subject"] = dict(conn.execute(text(
            "SELECT coalesce(nullif(subject,''),'未分类'), count(*) "
            "FROM quiz_questions GROUP BY 1 ORDER BY 2 DESC")).all())
        out["usable"] = conn.execute(text("""
            SELECT count(*) FROM quiz_questions
            WHERE question_type IN ('single','multiple','judge')
              AND options IS NOT NULL AND jsonb_typeof(options) = 'array'
              AND jsonb_array_length(options) >= 2
              AND coalesce(trim(answer), '') <> ''
              AND is_available AND NOT is_junk""")).scalar()
        # 重复率：同指纹（题干+选项全同）行数
        fps: dict = {}
        for content, options in conn.execute(
                text("SELECT content, options FROM quiz_questions")):
            fps.setdefault(content_fingerprint(content or "",
                                               [{"text": t} for t in _options_texts(options)]),
                           0)
            fps[content_fingerprint(content or "",
                                    [{"text": t} for t in _options_texts(options)])] += 1
        dup_rows = sum(c for c in fps.values() if c > 1)
        out["dup_rows"] = dup_rows
        out["dup_rate"] = round(dup_rows / out["total"], 4) if out["total"] else 0.0
        out["samples"] = [
            {"id": r.id, "subject": r.subject, "content": r.content[:80],
             "answer": r.answer,
             "options": {o["key"]: o["text"][:40] for o in (r.options or [])[:4]}}
            for r in conn.execute(text(
                "SELECT id, subject, content, answer, options FROM quiz_questions "
                "WHERE options IS NOT NULL ORDER BY id LIMIT 3"))
        ]
    print(f"\n{'=' * 66}\n落库复核（{tag}）\n{'=' * 66}")
    print(f"  quiz_questions 总数：{out['total']}（可刷 {out['usable']}）")
    print(f"  按 subject：{out['by_subject']}")
    print(f"  指纹重复行：{out['dup_rows']}（重复率 {out['dup_rate']:.2%}）")
    for s in out["samples"]:
        print(f"  样例 #{s['id']} [{s['subject']}] {s['content'][:50]}")
        print(f"      选项：{s['options']}")
        print(f"      答案：{s['answer']}")
    return out


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="真题选择题入库（PostgreSQL 版）")
    ap.add_argument("--apply", action="store_true", help="真实写库（默认 dry-run）")
    ap.add_argument("--report", default="", help="JSON 计划报告输出路径")
    ap.add_argument("--limit", type=int, default=DEFAULT_DOC_LIMIT,
                    help=f"最多处理文档数（默认 {DEFAULT_DOC_LIMIT}）")
    args = ap.parse_args()

    url, masked = build_pg_url()
    eng = create_engine(url)

    print("=" * 66)
    print("真题选择题入库计划（PostgreSQL）")
    print(f"目标库：{masked}  模式：{'APPLY' if args.apply else 'DRY-RUN'}")
    print("=" * 66)

    if args.apply:
        bak, bak_n = backup_quiz_questions(eng)
        print(f"写前备份：{bak}（{bak_n} 行）")

    with eng.connect() as conn:
        plan, skipped = build_plan(conn, args.limit)
        total_new = sum(len(p["rows"]) for p in plan)
        print(f"\n  待入库（去重后）：{total_new} 题，来自 {len(plan)} 篇文档")
        print(f"  跳过文档：{len(skipped)} 篇")
        for s in skipped[:6]:
            print(f"    × {s['file_name'][:44]}"
                  f"（抽 {s['extracted']}/{s['blocks_seen']}，{s['reason']}）")

        print("\n-- 样例题（每篇前 3 题，dry-run 供人工核验）--")
        for p in plan:
            print(f"  ▸ {p['file_name'][:48]}  [subject={p['subject']}]")
            for s in p["samples"]:
                print(f"      Q: {s['stem'][:60]}")
                print(f"         {s['options']}")
                print(f"         答案：{s['answer']}")

        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(json.dumps({
                "mode": "apply" if args.apply else "dry-run",
                "target_db": masked,
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "plan": plan, "skipped_docs": skipped,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n  计划报告：{args.report}")

    if not args.apply:
        print("\n[预览模式] 未写库。")
        verify(eng, "dry-run 前状态")
        return 0

    if total_new == 0:
        print("\n没有需要新增的题目。")
        return 0

    print(f"\n开始写库（单文档一事务）...")
    inserted, failed = apply_plan(eng, plan)
    print(f"已入库 {inserted} 题；回滚文档 {failed} 篇")
    verify(eng, "apply 后")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
