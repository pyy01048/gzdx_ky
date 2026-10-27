# -*- coding: utf-8 -*-
"""全库缺口填充（PostgreSQL 版）。

只做 INSERT / UPDATE，不删除任何数据。幂等：所有写入前先查重，可重复执行。

填充范围（可自动生成的基础/配置数据）：
  1. subjects        —— 为核心 11 科补齐 short_name / description / sort_order（UPDATE）
  2. subject_discipline_links —— 建立 subjects ↔ disciplines 学科门类关联（INSERT）
  3. papers          —— 基于 quiz_questions 中 year+paper 字段生成考研真题卷（INSERT）
  4. paper_questions —— 为上述真题卷写入题目快照（INSERT）
  5. exam_blueprints —— 基于真题卷的题型分布生成考试蓝图（INSERT）
  6. code_tags / code_problem_tags —— 从 code_problems.tags 提取标签并建关联（INSERT）
  7. code_problem_testcases —— 从 code_problems.sample_input/sample_output 生成样例用例（INSERT）

用法：
    python scripts/fill_gap_tables_pg.py            # dry-run 预览
    python scripts/fill_gap_tables_pg.py --apply    # 写库
    python scripts/fill_gap_tables_pg.py --only subjects,papers   # 只跑部分模块
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DB = dict(
    host="127.0.0.1",
    port=5432,
    user="kaoyan",
    password="kaoyan_dev_2026",
    dbname="kaoyan",
)

# 核心 11 科规范化信息（short_name / description）
CORE_SUBJECTS = {
    "政治": {
        "short_name": "政治",
        "description": "全国硕士研究生招生考试思想政治理论（101），含马原、毛中特、史纲、思修法基、时政当代。",
        "sort_order": 1,
    },
    "英语": {
        "short_name": "英语",
        "description": "全国硕士研究生招生考试英语（201英语一/204英语二），含完形、阅读、新题型、翻译、写作。",
        "sort_order": 2,
    },
    "数学": {
        "short_name": "数学",
        "description": "全国硕士研究生招生考试数学（301数学一/302数学二/303数学三），含高数、线代、概率统计。",
        "sort_order": 3,
    },
    "数据结构": {
        "short_name": "数据结构",
        "description": "计算机考研核心专业课，含线性表、栈队列、树、图、查找、排序等。",
        "sort_order": 4,
    },
    "操作系统": {
        "short_name": "操作系统",
        "description": "计算机考研专业课，含进程线程、内存管理、文件系统、I/O、死锁等。",
        "sort_order": 5,
    },
    "计算机网络": {
        "short_name": "计网",
        "description": "计算机考研专业课，含物理层、数据链路层、网络层、传输层、应用层。",
        "sort_order": 6,
    },
    "计算机基础": {
        "short_name": "计算机基础",
        "description": "计算机学科基础综合，含计算机组成原理、数据结构、操作系统、计算机网络。",
        "sort_order": 7,
    },
    "模拟电子技术": {
        "short_name": "模电",
        "description": "电子类考研专业课，含半导体器件、放大电路、反馈、运放、功放、直流电源。",
        "sort_order": 8,
    },
    "数字电子技术": {
        "short_name": "数电",
        "description": "电子类考研专业课，含数制码制、逻辑门、组合逻辑、时序逻辑、A/D与D/A。",
        "sort_order": 9,
    },
    "电路": {
        "short_name": "电路",
        "description": "电气/电子类考研专业课，邱关源《电路》体系，含电阻电路、动态电路、正弦稳态、耦合与谐振。",
        "sort_order": 10,
    },
    "自动控制原理": {
        "short_name": "自控",
        "description": "自动化/控制类考研专业课，胡寿松《自动控制原理》体系，含时域、根轨迹、频域、校正。",
        "sort_order": 11,
    },
}

# 科目 → 学科门类 code 映射（subject_discipline_links）
SUBJECT_DISCIPLINE_MAP = {
    "政治": "03",            # 法学（马克思主义理论）
    "英语": "05",            # 文学（外国语言文学）
    "数学": "07",            # 理学（数学）
    "数据结构": "08",        # 工学（计算机科学与技术）
    "操作系统": "08",
    "计算机网络": "08",
    "计算机基础": "08",
    "模拟电子技术": "08",    # 工学（电子科学与技术）
    "数字电子技术": "08",
    "电路": "08",
    "自动控制原理": "08",    # 工学（控制科学与工程）
    "通信原理": "08",
    "数字信号处理": "08",
    "电磁场与电磁波": "08",
    "信号与系统": "08",
    "计算机学科专业基础408": "08",
    "电路分析": "08",
    "电气工程": "08",
    "电子科学与技术": "08",
    "控制科学与工程": "08",
    "软件工程": "08",
    "电子信息": "08",
    "信息与通信工程": "08",
    "计算机科学与技术": "08",
    "光学工程": "08",
    "光学与工程光学": "08",
    "普通物理": "07",
    "光学": "07",
}

# 考研核心科目（用于真题卷筛选）
KAOYAN_SUBJECTS = set(CORE_SUBJECTS.keys())

# 题型默认分值（与 paper_builder.DEFAULT_SCORES 对齐）
DEFAULT_SCORES = {
    "single": 2, "multiple": 4, "judge": 2, "fill": 3,
    "calc": 10, "essay": 15, "draw": 10, "proof": 10, "other": 5,
}


def connect():
    return psycopg.connect(**DB, row_factory=dict_row)


def now():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# 1. subjects 规范化
# --------------------------------------------------------------------------- #
def fill_subjects(cur, apply: bool) -> int:
    """为核心科目补齐 short_name / description / sort_order。"""
    count = 0
    for name, info in CORE_SUBJECTS.items():
        cur.execute("SELECT id, short_name, description, sort_order FROM subjects WHERE name = %s", (name,))
        row = cur.fetchone()
        if not row:
            print(f"  [warn] subjects 中不存在科目: {name}（跳过）")
            continue
        updates = []
        params = []
        if not row["short_name"] and info.get("short_name"):
            updates.append("short_name = %s")
            params.append(info["short_name"])
        if (not row["description"] or row["description"] == "") and info.get("description"):
            updates.append("description = %s")
            params.append(info["description"])
        if row["sort_order"] is None and info.get("sort_order"):
            updates.append("sort_order = %s")
            params.append(info["sort_order"])
        if not updates:
            continue
        params.append(row["id"])
        if apply:
            cur.execute(f"UPDATE subjects SET {', '.join(updates)} WHERE id = %s", params)
        count += 1
        print(f"  [subject] {name}: 补 {'/'.join(u.split(' = ')[0] for u in updates)}")
    return count


# --------------------------------------------------------------------------- #
# 2. subject_discipline_links
# --------------------------------------------------------------------------- #
def fill_subject_discipline_links(cur, apply: bool) -> int:
    count = 0
    for subject_name, disc_code in SUBJECT_DISCIPLINE_MAP.items():
        cur.execute("SELECT id FROM subjects WHERE name = %s", (subject_name,))
        subj = cur.fetchone()
        if not subj:
            print(f"  [warn] subjects 不存在: {subject_name}（跳过）")
            continue
        cur.execute("SELECT id, description FROM disciplines WHERE code = %s", (disc_code,))
        disc = cur.fetchone()
        if not disc:
            print(f"  [warn] disciplines 不存在 code={disc_code}（跳过 {subject_name}）")
            continue
        # 幂等
        cur.execute(
            "SELECT id FROM subject_discipline_links WHERE subject_id = %s AND discipline_id = %s",
            (subj["id"], disc["id"]),
        )
        if cur.fetchone():
            continue
        if apply:
            cur.execute(
                "INSERT INTO subject_discipline_links (subject_id, discipline_id, is_primary, created_at) "
                "VALUES (%s, %s, %s, %s)",
                (subj["id"], disc["id"], True, now()),
            )
        count += 1
        print(f"  [link] {subject_name}(id={subj['id']}) -> {disc_code} {disc['description']}")
    return count


# --------------------------------------------------------------------------- #
# 3. papers + 4. paper_questions（真题卷）
# --------------------------------------------------------------------------- #
def _load_question_rows(cur, subject: str, year: int, paper: str):
    cur.execute(
        """
        SELECT id, content, options, answer, analysis, question_type, difficulty, question_no
        FROM quiz_questions
        WHERE subject = %s AND year = %s AND paper = %s
        ORDER BY question_no NULLS LAST, id
        """,
        (subject, year, paper),
    )
    return cur.fetchall()


def fill_papers(cur, apply: bool) -> dict:
    """基于 quiz_questions 的 year+paper 生成考研真题卷。"""
    # 找出所有含"考研"的 year+paper 组合（仅考研核心科目）
    placeholders = ", ".join(["%s"] * len(KAOYAN_SUBJECTS))
    cur.execute(
        f"""
        SELECT subject, year, paper, COUNT(*) AS qcnt
        FROM quiz_questions
        WHERE year IS NOT NULL AND paper IS NOT NULL AND paper LIKE %s
          AND subject IN ({placeholders})
        GROUP BY subject, year, paper
        ORDER BY subject, year, paper
        """,
        ("%考研%",) + tuple(sorted(KAOYAN_SUBJECTS)),
    )
    groups = cur.fetchall()

    papers_created = 0
    questions_created = 0
    skipped = 0

    for g in groups:
        subject = g["subject"]
        year = g["year"]
        paper_title = g["paper"]
        qcnt = g["qcnt"]

        # 幂等：title 已存在则跳过（mock 卷与真题卷 title 不同，不会误判）
        cur.execute("SELECT id FROM papers WHERE title = %s", (paper_title,))
        if cur.fetchone():
            skipped += 1
            print(f"  [skip] 试卷已存在: {paper_title}")
            continue

        # 关联 subjects
        cur.execute("SELECT id FROM subjects WHERE name = %s", (subject,))
        subj = cur.fetchone()
        subject_id = subj["id"] if subj else None

        # 加载题目
        qs = _load_question_rows(cur, subject, year, paper_title)
        if not qs:
            print(f"  [warn] {paper_title} 无题目，跳过")
            skipped += 1
            continue

        # 计算总分（按题型默认分值）
        total_score = 0
        type_counter = Counter()
        for q in qs:
            qt = (q["question_type"] or "single").strip()
            type_counter[qt] += 1
            total_score += DEFAULT_SCORES.get(qt, 5)

        rules = {
            "subject": subject,
            "source_paper": paper_title,
            "year": year,
            "question_types": sorted(type_counter),
            "total_questions": len(qs),
            "is_real": True,
        }

        if not apply:
            print(f"  [paper] 将创建: {paper_title}（{subject} {year}，{len(qs)}题，总分{total_score}）")
            papers_created += 1
            questions_created += len(qs)
            continue

        cur.execute(
            """
            INSERT INTO papers (title, subject_id, subject, description, rules, total_score,
                                year, paper_type, is_mock, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'real', false, %s, %s)
            RETURNING id
            """,
            (
                paper_title,
                subject_id,
                subject,
                f"{paper_title}（自动组卷，源自题库 year={year}）",
                Jsonb(rules),
                total_score,
                year,
                now(),
                now(),
            ),
        )
        paper_id = cur.fetchone()["id"]

        # 写入 paper_questions
        for i, q in enumerate(qs, start=1):
            qt = (q["question_type"] or "single").strip()
            cur.execute(
                """
                INSERT INTO paper_questions
                    (paper_id, question_id, seq, content, options, answer, analysis,
                     question_type, difficulty, score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    paper_id,
                    q["id"],
                    i,
                    q["content"],
                    Jsonb(q["options"]) if q["options"] is not None else None,
                    q["answer"],
                    q["analysis"],
                    qt,
                    q["difficulty"] or 3,
                    DEFAULT_SCORES.get(qt, 5),
                ),
            )
            questions_created += 1

        papers_created += 1
        print(f"  [paper] 已创建: {paper_title}（id={paper_id}，{len(qs)}题，总分{total_score}）")

    return {"papers": papers_created, "questions": questions_created, "skipped": skipped}


# --------------------------------------------------------------------------- #
# 5. exam_blueprints（基于真题卷题型分布）
# --------------------------------------------------------------------------- #
def fill_exam_blueprints(cur, apply: bool) -> int:
    """为已生成的真题卷生成考试蓝图（按题型统计）。"""
    cur.execute(
        """
        SELECT p.id AS paper_id, p.subject, p.subject_id, p.year, p.title AS paper,
               pq.question_type, COUNT(*) AS cnt
        FROM papers p
        JOIN paper_questions pq ON pq.paper_id = p.id
        WHERE p.paper_type = 'real'
        GROUP BY p.id, p.subject, p.subject_id, p.year, p.title, pq.question_type
        ORDER BY p.id, pq.question_type
        """
    )
    rows = cur.fetchall()

    created = 0
    skipped = 0
    # 按 paper 聚合
    from collections import defaultdict
    papers_map = defaultdict(list)
    for r in rows:
        papers_map[r["paper_id"]].append(r)

    for paper_id, items in papers_map.items():
        paper = items[0]["paper"]
        subject = items[0]["subject"]
        subject_id = items[0]["subject_id"]
        year = items[0]["year"]

        for idx, it in enumerate(items, start=1):
            qtype = it["question_type"]
            cnt = it["cnt"]
            # 幂等：同 paper + 题型 已存在则跳过
            cur.execute(
                """
                SELECT id FROM exam_blueprints
                WHERE paper = %s AND blueprint_question_type = %s
                """,
                (paper, qtype),
            )
            if cur.fetchone():
                skipped += 1
                continue
            if apply:
                cur.execute(
                    """
                    INSERT INTO exam_blueprints
                        (subject_id, subject, paper, year, section, blueprint_question_type,
                         count, score_per_question, time_limit_minutes, sort_order, kp_filters, is_active, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        subject_id,
                        subject,
                        paper,
                        year,
                        "全部",
                        qtype,
                        cnt,
                        DEFAULT_SCORES.get(qtype, 5),
                        180,
                        idx,
                        None,
                        True,
                        now(),
                    ),
                )
            created += 1
            print(f"  [blueprint] {paper} 题型={qtype} 题数={cnt}")

    return created


# --------------------------------------------------------------------------- #
# 6. code_tags / code_problem_tags
# --------------------------------------------------------------------------- #
def fill_code_tags(cur, apply: bool) -> int:
    cur.execute("SELECT id, tags FROM code_problems WHERE tags IS NOT NULL AND tags::text != 'null'")
    problems = cur.fetchall()

    tag_set = {}
    for p in problems:
        for tag in (p["tags"] or []):
            tag_set.setdefault(tag, 0)
            tag_set[tag] += 1

    created = 0
    tag_id_map = {}
    # 先读已有标签
    cur.execute("SELECT id, name FROM code_tags")
    for r in cur.fetchall():
        tag_id_map[r["name"]] = r["id"]

    for tag, freq in sorted(tag_set.items(), key=lambda x: -x[1]):
        if tag in tag_id_map:
            continue
        if apply:
            cur.execute("INSERT INTO code_tags (name, category, created_at) VALUES (%s, %s, %s) RETURNING id",
                        (tag, "algorithm", now()))
            tag_id = cur.fetchone()["id"]
        else:
            tag_id = None
        tag_id_map[tag] = tag_id
        created += 1
        print(f"  [tag] {tag}（出现 {freq} 次）")

    # 建立关联
    links = 0
    for p in problems:
        pid = p["id"]
        for tag in (p["tags"] or []):
            tid = tag_id_map.get(tag)
            if not tid:
                continue
            cur.execute(
                "SELECT 1 FROM code_problem_tags WHERE problem_id = %s AND tag_id = %s",
                (pid, tid),
            )
            if cur.fetchone():
                continue
            if apply:
                cur.execute(
                    "INSERT INTO code_problem_tags (problem_id, tag_id) VALUES (%s, %s)",
                    (pid, tid),
                )
            links += 1

    print(f"  [tag-link] 将建立 {links} 条题目-标签关联")
    return created


# --------------------------------------------------------------------------- #
# 7. code_problem_testcases
# --------------------------------------------------------------------------- #
def fill_code_testcases(cur, apply: bool) -> int:
    cur.execute(
        "SELECT id, sample_input, sample_output FROM code_problems "
        "WHERE sample_input IS NOT NULL AND sample_output IS NOT NULL "
        "AND sample_input != '' AND sample_output != ''"
    )
    problems = cur.fetchall()

    created = 0
    skipped = 0
    for p in problems:
        cur.execute(
            "SELECT id FROM code_problem_testcases WHERE problem_id = %s AND is_sample = true",
            (p["id"],),
        )
        if cur.fetchone():
            skipped += 1
            continue
        if apply:
            cur.execute(
                """
                INSERT INTO code_problem_testcases
                    (problem_id, input_data, expected_output, is_sample, score_weight, sort_order)
                VALUES (%s, %s, %s, true, 1.0, 1)
                """,
                (p["id"], p["sample_input"], p["sample_output"]),
            )
        created += 1

    print(f"  [testcase] 将创建 {created} 条样例用例（{skipped} 条已存在跳过）")
    return created


# --------------------------------------------------------------------------- #
# 8. question_images（同步 quiz_questions.images 中的配图路径）
# --------------------------------------------------------------------------- #
def fill_question_images(cur, apply: bool) -> int:
    cur.execute(
        """
        SELECT id, subject, images FROM quiz_questions
        WHERE images IS NOT NULL AND images::text != '[]' AND images::text != 'null'
        """
    )
    questions = cur.fetchall()

    created = 0
    skipped = 0
    for q in questions:
        qid = q["id"]
        for img in (q["images"] or []):
            # 幂等：同 question_id + image_path 已存在则跳过
            cur.execute(
                "SELECT id FROM question_images WHERE question_id = %s AND image_path = %s",
                (qid, img.get("path")),
            )
            if cur.fetchone():
                skipped += 1
                continue
            if apply:
                cur.execute(
                    """
                    INSERT INTO question_images
                        (question_id, document_id, page_no, image_path, image_kind,
                         image_hash, phash, bbox, caption, width, height, is_primary, created_at)
                    VALUES (%s, NULL, %s, %s, %s, NULL, NULL, NULL, NULL, NULL, NULL, %s, %s)
                    """,
                    (
                        qid,
                        img.get("page"),
                        img.get("path"),
                        img.get("kind"),
                        True,
                        now(),
                    ),
                )
            created += 1
            print(f"  [qimg] question_id={qid} path={img.get('path')} kind={img.get('kind')} page={img.get('page')}")

    print(f"  [qimg] 将创建 {created} 条配图记录（{skipped} 条已存在跳过）")
    return created


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
MODULES = {
    "subjects": fill_subjects,
    "subject_discipline_links": fill_subject_discipline_links,
    "papers": fill_papers,
    "exam_blueprints": fill_exam_blueprints,
    "code_tags": fill_code_tags,
    "code_testcases": fill_code_testcases,
    "question_images": fill_question_images,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="全库缺口填充")
    parser.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    parser.add_argument("--only", default="", help="只跑部分模块，逗号分隔")
    args = parser.parse_args()

    only = {m.strip() for m in args.only.split(",") if m.strip()}
    modules = {k: v for k, v in MODULES.items() if not only or k in only}

    print(f"模式: {'APPLY（写库）' if args.apply else 'DRY-RUN（不写库）'}")
    print(f"模块: {', '.join(modules)}")
    print("=" * 60)

    conn = connect()
    cur = conn.cursor()
    try:
        for name, fn in modules.items():
            print(f"\n--- 模块: {name} ---")
            fn(cur, args.apply)
            if args.apply:
                conn.commit()
                print(f"  [commit] {name} 已提交")
    finally:
        conn.close()

    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())