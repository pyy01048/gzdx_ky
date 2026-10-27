# -*- coding: utf-8 -*-
"""数据填充正确性审计（--full）。

四段检查，逐域输出问题清单：
  1. 外键孤儿：子表指向不存在的父行
  2. 跨表一致性：文档↔分块↔向量、题目↔答案↔知识点、学校↔分数线 等
  3. 业务键重复：核心业务表的候选唯一键冗余
  4. README 口径对照：宣传数字 vs 真实计数

用法::

    python scripts/diagnostics/data_audit.py --full
    python scripts/diagnostics/data_audit.py --inventory
"""
from __future__ import annotations

import sys
from pathlib import Path

# 控制台默认 GBK 无法编码 emoji/部分 CJK → 强制 UTF-8，避免审计中途崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

OK = "[OK]"
BAD = "[X]"


def cnt(db, sql: str, **p) -> int:
    return int(db.execute(text(sql), p).scalar() or 0)


def section(title: str) -> None:
    print(f"\n{'='*66}\n{title}\n{'='*66}")


def has_col(db, table: str, col: str) -> bool:
    return bool(
        db.execute(
            text(
                "select 1 from information_schema.columns "
                "where table_schema='public' and table_name=:t and column_name=:c"
            ),
            {"t": table, "c": col},
        ).first()
    )


def cols_of(db, table: str) -> list[str]:
    return [
        r[0]
        for r in db.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema='public' and table_name=:t order by ordinal_position"
            ),
            {"t": table},
        )
    ]


# ---------------------------------------------------------------- 1. 外键
def fk_orphans(db) -> None:
    section("1. 外键孤儿（子行指向缺失父行）")
    fks = db.execute(text(
        "select tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name "
        "from information_schema.table_constraints tc "
        "join information_schema.key_column_usage kcu "
        "  on tc.constraint_name=kcu.constraint_name and tc.table_schema=kcu.table_schema "
        "join information_schema.constraint_column_usage ccu "
        "  on tc.constraint_name=ccu.constraint_name and tc.table_schema=ccu.table_schema "
        "where tc.constraint_type='FOREIGN KEY' and tc.table_schema='public' "
        "order by tc.table_name"
    )).all()
    found = 0
    for child, ccol, parent, pcol in fks:
        try:
            n = cnt(db, f"""
                select count(*) from "{child}" c
                left join "{parent}" p on p."{pcol}"=c."{ccol}"
                where c."{ccol}" is not null and p."{pcol}" is null
            """)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            print(f"  [跳过] {child}.{ccol}->{parent}: {type(e).__name__}")
            continue
        if n:
            found += 1
            print(f"  {BAD} {child}.{ccol} → {parent}.{pcol}: {n} 孤儿行")
    if not found:
        print(f"  {OK} 共查 {len(fks)} 个外键，无孤儿")


# ------------------------------------------------------- 2. 跨表一致性
def consistency(db) -> None:
    section("2. 跨表一致性")
    checks: list[tuple[str, str, int, bool]] = []  # (表, 标签, 值, 是否越小越好)

    # --- 文档 → 分块 → 向量 ---
    checks.append(("documents", "文档总数", cnt(db, "select count(*) from documents"), False))
    checks.append(("knowledge_chunks", "分块总数", cnt(db, "select count(*) from knowledge_chunks"), False))
    checks.append(("chunk_vectors", "向量总数", cnt(db, "select count(*) from chunk_vectors"), False))
    checks.append(("knowledge_chunks", "分块指向缺失文档", cnt(db, """
        select count(*) from knowledge_chunks kc
        left join documents d on d.id=kc.document_id
        where kc.document_id is not null and d.id is null"""), True))
    checks.append(("knowledge_chunks", "分块无 document_id", cnt(db,
        "select count(*) from knowledge_chunks where document_id is null"), True))
    if has_col(db, "chunk_vectors", "chunk_id"):
        checks.append(("chunk_vectors", "分块缺向量", cnt(db, """
            select count(*) from knowledge_chunks kc
            left join chunk_vectors cv on cv.chunk_id=kc.id
            where cv.chunk_id is null"""), True))
        checks.append(("chunk_vectors", "向量指向缺失分块", cnt(db, """
            select count(*) from chunk_vectors cv
            left join knowledge_chunks kc on kc.id=cv.chunk_id
            where kc.id is null"""), True))

    # --- 题目 → 答案 / 知识点 ---
    qq_cols = cols_of(db, "quiz_questions")
    checks.append(("quiz_questions", "题目总数", cnt(db, "select count(*) from quiz_questions"), False))
    for col in ("answer", "correct_answer", "content", "subject", "year",
                "source_kind", "type", "question_type", "source", "analysis"):
        if col in qq_cols:
            filled = cnt(db, f"""select count(*) from quiz_questions
                where "{col}" is not null and btrim("{col}"::text)<>''""")
            checks.append(("quiz_questions", f"有 {col}", filled, False))
    # 关键：题目缺答案/解析
    for col in ("answer", "correct_answer"):
        if col in qq_cols:
            empty = cnt(db, f"""select count(*) from quiz_questions
                where "{col}" is null or btrim("{col}"::text)=''""")
            checks.append(("quiz_questions", f"缺 {col}", empty, True))

    checks.append(("question_knowledge_links", "题目-知识点链接",
                   cnt(db, "select count(*) from question_knowledge_links"), False))
    checks.append(("question_knowledge_links", "链接指向缺失题目", cnt(db, """
        select count(*) from question_knowledge_links l
        left join quiz_questions q on q.id=l.question_id where q.id is null"""), True))
    checks.append(("knowledge_points", "知识点总数",
                   cnt(db, "select count(*) from knowledge_points"), False))

    # --- 学校 → 分数线 / 专业 / 公告 ---
    checks.append(("kaoyan_schools", "学校总数", cnt(db, "select count(*) from kaoyan_schools"), False))
    checks.append(("kaoyan_scorelines", "分数线总数", cnt(db, "select count(*) from kaoyan_scorelines"), False))
    checks.append(("kaoyan_scorelines", "分数线指向缺失学校", cnt(db, """
        select count(*) from kaoyan_scorelines s
        left join kaoyan_schools k on k.id=s.school_id where k.id is null"""), True))
    checks.append(("kaoyan_scorelines", "有分数线的学校数",
                   cnt(db, "select count(distinct school_id) from kaoyan_scorelines"), False))
    checks.append(("kaoyan_majors", "专业总数", cnt(db, "select count(*) from kaoyan_majors"), False))
    checks.append(("kaoyan_majors", "专业指向缺失学校", cnt(db, """
        select count(*) from kaoyan_majors m
        left join kaoyan_schools k on k.id=m.school_id where k.id is null"""), True))
    checks.append(("kaoyan_notices", "公告总数", cnt(db, "select count(*) from kaoyan_notices"), False))
    if has_col(db, "kaoyan_notices", "school_id"):
        checks.append(("kaoyan_notices", "公告指向缺失学校", cnt(db, """
            select count(*) from kaoyan_notices n
            left join kaoyan_schools k on k.id=n.school_id where n.school_id is not null and k.id is null"""), True))

    # --- 单词 / 科目 ---
    checks.append(("words", "单词总数", cnt(db, "select count(*) from words"), False))
    checks.append(("subjects", "科目总数", cnt(db, "select count(*) from subjects"), False))

    w = max((len(t) for t, _, _, _ in checks), default=10)
    for t, label, v, smaller_better in checks:
        if smaller_better:
            flag = f"  {BAD}" if v else f"  {OK}"
        else:
            flag = ""
        print(f"  {t:{w}}  {label:24} {v:>10,}{flag}")


def _key_cols(db, table: str, key: str) -> bool:
    """校验 key 中引用的列都存在，避免整段事务中止。"""
    import re
    have = set(cols_of(db, table))
    for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", key):
        if ident.lower() in {"coalesce", "null", "text"}:
            continue
        if ident not in have:
            return False
    return True


# --------------------------------------------------------- 3. 业务键重复
def dup_keys(db) -> None:
    section("3. 业务键重复（候选唯一键冗余）")
    specs = [
        ("kaoyan_notices", "school_id, coalesce(title,''), coalesce(publish_date::text,'')", "校+标题+发布日"),
        ("kaoyan_notices", "coalesce(url, '#'||id::text)", "URL"),
        ("kaoyan_majors", "school_id, code, name", "校+专业代码+名"),
        ("kaoyan_colleges", "school_id, coalesce(name,'')", "校+名称"),
        ("kaoyan_admission_details", "school_id, year, coalesce(exam_no,''), coalesce(name,'')", "校+年+考号+姓名"),
        ("subjects", "code", "科目代码"),
        ("subject_configs", "subject_id", "科目ID"),
        ("subject_chapters", "subject_id, coalesce(title,'')", "科目+章名"),
        ("documents", "coalesce(content_hash, '#'||id::text)", "内容哈希"),
        ("documents", "coalesce(file_path, '#'||id::text)", "文件路径"),
        ("quiz_questions", "coalesce(subject,''), content, coalesce(options::text,'')", "科目+题干+选项"),
        ("words", "word", "单词"),
        ("knowledge_points", "coalesce(subject,''), coalesce(name,'')", "科目+名称"),
        ("textbooks", "coalesce(isbn, '#'||id::text)", "ISBN"),
        ("textbooks", "coalesce(title,''), coalesce(edition,'')", "书名+版次"),
        ("kaoyan_scorelines",
         "school_id, year, coalesce(major_code,''), line_type, coalesce(depart_name,''), coalesce(degree_type,'')",
         "校+年+专业码+线型+院系+学位"),
    ]
    for table, key, label in specs:
        if not db.execute(text(
            "select 1 from information_schema.tables where table_schema='public' and table_name=:t"
        ), {"t": table}).first():
            continue
        total = cnt(db, f'select count(*) from "{table}"')
        if not total:
            continue
        if key is None or not _key_cols(db, table, key or ""):  # 列缺失 → 自动探测
            best = None
            cand = [c for c in cols_of(db, table) if c.endswith("_id") or c in ("code", "name", "title", "source_id")]
            for c in cand:
                try:
                    d = cnt(db, f'select count(distinct "{c}") from "{table}"')
                except Exception:  # noqa: BLE001
                    db.rollback()
                    continue
                if best is None or d > best[1]:
                    best = (c, d)
            if not best:
                continue
            key, label = f"coalesce({best[0]}::text,'')", f"列 {best[0]}"
        try:
            ng, ex = db.execute(text(f"""
                select count(*), coalesce(sum(cnt-1),0) from
                  (select count(*) cnt from "{table}" group by {key}) t
            """)).one()
            ng, ex = int(ng), float(ex)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            print(f"  [跳过] {table}: {type(e).__name__} {str(e).splitlines()[0][:80]}")
            continue
        flag = f"  {BAD}" if ex else f"  {OK}"
        print(f"  {table:24} 按({label}) 组={ng:>7,} 冗余={ex:>7,.0f}/{total:,}{flag}")


# --------------------------------------------------------- 4. README 对照
def readme_check(db) -> None:
    section("4. README 口径对照（宣传 vs 真实）")
    claims = [
        ("题目", 386, "select count(*) from quiz_questions"),
        ("单词", 20, "select count(*) from words"),
        ("文档", 705, "select count(*) from documents"),
        ("分块", 20676, "select count(*) from knowledge_chunks"),
        ("向量化", 20676, "select count(*) from chunk_vectors"),
        ("知识点", 1860, "select count(*) from knowledge_points"),
        ("院校", 818, "select count(*) from kaoyan_schools"),
        ("条目", 128, "select count(*) from kaoyan_colleges"),
        ("公告", 1258, "select count(*) from kaoyan_notices"),
        ("分数线", 88315, "select count(*) from kaoyan_scorelines"),
        ("专业", None, "select count(*) from kaoyan_majors"),
    ]
    for name, claim, sql in claims:
        actual = cnt(db, sql)
        if claim is None:
            mark = "  (README未列)"
        elif actual == claim:
            mark = f"  {OK}"
        else:
            mark = f"  {BAD} 差 {actual-claim:+,}"
        c = "-" if claim is None else f"{claim:,}"
        print(f"  {name:6} README={c:>10}  实际={actual:>10,}{mark}")


# --------------------------------------------------------- 0. 全库清单
def inventory(db) -> None:
    tbls = [
        r[0]
        for r in db.execute(text(
            "select c.relname from pg_class c "
            "join pg_namespace n on n.oid=c.relnamespace and n.nspname='public' "
            "where c.relkind='r' order by c.relname"
        ))
    ]
    counts = {}
    for t in tbls:
        try:
            counts[t] = cnt(db, f'select count(*) from "{t}"')
        except Exception:  # noqa: BLE001
            counts[t] = -1
    order = sorted(tbls, key=lambda t: counts[t], reverse=True)
    total = sum(c for c in counts.values() if c > 0)
    nonempty = sum(1 for c in counts.values() if c > 0)
    print(f"== 真实计数（{len(tbls)} 张表，非空 {nonempty} 张，合计 {total:,} 行）==")
    for t in order:
        print(f"  {t:44} {counts[t]:>10,}")


# --------------------------------------------------------- 5. 空表清单
def empty_tables(db) -> None:
    section("5. 空表清单（0 行 → 待填充/待确认是否废弃）")
    tbls = [
        r[0]
        for r in db.execute(text(
            "select c.relname from pg_class c "
            "join pg_namespace n on n.oid=c.relnamespace and n.nspname='public' "
            "where c.relkind='r' order by c.relname"
        ))
    ]
    empties = []
    for t in tbls:
        if cnt(db, f'select count(*) from "{t}"') == 0:
            empties.append(t)
    print(f"  共 {len(empties)}/{len(tbls)} 张空表：")
    for i in range(0, len(empties), 4):
        print("   " + "  ".join(f"{t:34}" for t in empties[i:i + 4]))


# --------------------------------------------------- 6. 重复组抽样定性
def dup_samples(db) -> None:
    section("6. 重复组抽样（定性：真重复 vs 合法并存）")

    print("-- 公告 URL 重复（前 5 组，看标题/日期是否也一致）--")
    for url, n in db.execute(text("""
        select coalesce(url,'(null)'), count(*) from kaoyan_notices
        where url is not null group by 1 having count(*)>1 order by 2 desc limit 5""")):
        rows = db.execute(text(
            "select id, school_id, title, publish_date, fetched_at from kaoyan_notices "
            "where url=:u order by id limit 4"), {"u": url}).all()
        print(f"  x{n} {url[:70]}")
        for r in rows:
            print(f"      id={r[0]} school={r[1]} {str(r[3])[:10]} {str(r[2])[:38]}")

    print("\n-- 题目 同科目+题干 重复（全部 12 组）--")
    for subj, content, n in db.execute(text("""
        select coalesce(subject,''), content, count(*) from quiz_questions
        group by 1,2 having count(*)>1 order by 3 desc""")):
        rows = db.execute(text(
            "select id, question_type, left(coalesce(answer,''),16), source_kind, year "
            "from quiz_questions where subject=:s and content=:c order by id"),
            {"s": subj, "c": content}).all()
        print(f"  x{n} [{subj}] {content[:44]!r}")
        for r in rows:
            print(f"      id={r[0]} type={r[1]} ans={r[2]!r} src={r[3]} year={r[4]}")

    print("\n-- 知识点 同科目+名称 重复（全部 7 组）--")
    for subj, name, n in db.execute(text("""
        select coalesce(subject,''), name, count(*) from knowledge_points
        group by 1,2 having count(*)>1 order by 3 desc""")):
        rows = db.execute(text(
            "select id, coalesce(chapter,''), coalesce(document_id,0), question_count "
            "from knowledge_points where coalesce(subject,'')=:s and name=:n order by id"),
            {"s": subj, "n": name}).all()
        print(f"  x{n} [{subj}] {name[:44]}")
        for r in rows:
            print(f"      id={r[0]} chapter={r[1][:30]!r} doc={r[2]} qn={r[3]}")

    print("\n-- 教材 同书名+版次 重复（全部 3 组）--")
    for title, ed, n in db.execute(text("""
        select title, coalesce(edition,''), count(*) from textbooks
        group by 1,2 having count(*)>1 order by 3 desc""")):
        rows = db.execute(text(
            "select id, coalesce(isbn,''), coalesce(publisher,''), coalesce(authors,'') "
            "from textbooks where title=:t and coalesce(edition,'')=:e order by id"),
            {"t": title, "e": ed}).all()
        print(f"  x{n} {title[:44]!r} ed={ed!r}")
        for r in rows:
            print(f"      id={r[0]} isbn={r[1]} pub={r[2][:24]} auth={r[3][:24]}")


# --------------------------------------------------- 7. 填充覆盖度
def coverage(db) -> None:
    section("7. 填充覆盖度（补数据底账）")

    def line(label: str, n: int, total: int) -> None:
        pct = f"{n*100.0/total:.1f}%" if total else "-"
        print(f"  {label:44} {n:>7,}/{total:<7,} {pct}")

    # 学校维度
    schools = cnt(db, "select count(*) from kaoyan_schools")
    line("学校 有公告", cnt(db, "select count(distinct school_id) from kaoyan_notices"), schools)
    line("学校 有专业", cnt(db, "select count(distinct school_id) from kaoyan_majors"), schools)
    line("学校 有分数线", cnt(db, "select count(distinct school_id) from kaoyan_scorelines"), schools)
    line("学校 有录取明细", cnt(db, "select count(distinct school_id) from kaoyan_admission_details"), schools)

    # 题目维度
    qq = cnt(db, "select count(*) from quiz_questions")
    line("题目 有知识点链接", cnt(db, "select count(distinct question_id) from question_knowledge_links"), qq)
    line("题目 有年份", cnt(db, "select count(*) from quiz_questions where year is not null"), qq)
    line("题目 有解析", cnt(db, "select count(*) from quiz_questions where analysis is not null and btrim(analysis)<>''"), qq)
    line("题目 有来源文档", cnt(db, "select count(*) from quiz_questions where origin_document_id is not null"), qq)

    # 知识点维度
    kp = cnt(db, "select count(*) from knowledge_points")
    line("知识点 关联了题目(qn>0)", cnt(db, "select count(*) from knowledge_points where question_count>0"), kp)
    line("知识点 有文档溯源", cnt(db, "select count(*) from knowledge_points where document_id is not null"), kp)

    # 文档/科目维度
    docs = cnt(db, "select count(*) from documents")
    line("文档 有哈希", cnt(db, "select count(*) from documents where content_hash is not null"), docs)
    line("文档 有大小", cnt(db, "select count(*) from documents where size is not null"), docs)
    line("文档 有科目", cnt(db, "select count(*) from documents where subject is not null and btrim(subject)<>''"), docs)
    line("文档 已分块(chunk_count>0)", cnt(db, "select count(*) from documents where coalesce(chunk_count,0)>0"), docs)

    subj = cnt(db, "select count(*) from subjects")
    line("题目 有 subject_id 外键", cnt(db, "select count(*) from quiz_questions where subject_id is not null"), qq)
    line("科目 有配置", cnt(db, "select count(distinct subject_id) from subject_configs"), subj)
    line("科目 有章节", cnt(db, "select count(distinct subject_id) from subject_chapters"), subj)
    line("科目 有题目", cnt(db, "select count(distinct subject_id) from quiz_questions where subject_id is not null"), subj)
    # 题目 subject 文本 vs subjects.name/code 能否对上
    line("题目 subject文本 能匹配 subjects", cnt(db, """
        select count(*) from quiz_questions q
        join subjects s on s.name=q.subject or s.code=q.subject
        where q.subject is not null"""), qq)

    # 录取维度
    adm = cnt(db, "select count(*) from kaoyan_admissions")
    line("录取(admissions) 有明细", cnt(db, "select count(distinct admission_id) from kaoyan_admission_details"), adm)

    # 公告维度
    notices = cnt(db, "select count(*) from kaoyan_notices")
    line("公告 有URL", cnt(db, "select count(*) from kaoyan_notices where url is not null and url<>''"), notices)
    line("公告 有发布日期", cnt(db, "select count(*) from kaoyan_notices where publish_date is not null"), notices)
    line("公告 有正文", cnt(db, "select count(*) from kaoyan_notices where content is not null and btrim(content)<>''"), notices)
    line("公告 标记为噪声", cnt(db, "select count(*) from kaoyan_notices where is_noise"), notices)


def main() -> int:
    from database import SessionLocal

    which = sys.argv[1] if len(sys.argv) > 1 else "--full"
    db = SessionLocal()
    try:
        if which == "--inventory":
            inventory(db)
        elif which == "--cols":
            for t in ("quiz_questions", "documents", "kaoyan_notices", "kaoyan_colleges",
                      "knowledge_points", "textbooks", "subject_chapters",
                      "kaoyan_admission_details", "words", "subjects"):
                print(f"== {t} ==")
                print("   " + ", ".join(cols_of(db, t)))
        elif which == "--samples":
            dup_samples(db)
        elif which == "--coverage":
            coverage(db)
        else:
            fk_orphans(db)
            consistency(db)
            dup_keys(db)
            readme_check(db)
            empty_tables(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
