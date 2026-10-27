# -*- coding: utf-8 -*-
"""建立「考研专业 ↔ 知识库科目」关联表（PostgreSQL 版）。

数据基础：kaoyan_majors.exam_subjects 已由 fill_major_exam_subjects_pg.py 填充。

策略：
1. 从 exam_subjects 中剥离公共课（政治/英语/数学），剩余为专业课。
2. 专业课名与知识库 subjects.name 精确匹配（含别名归一）。
3. 命中则写入 kaoyan_major_kb_link，并统计该科目在 knowledge_points 中的知识点数作为 kb_doc_count。
4. 幂等：先清空旧表再写入（该表原本为 0 条）。

用法：
    python scripts/build_major_kb_link_pg.py --dry-run
    python scripts/build_major_kb_link_pg.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict

import psycopg
from psycopg.types.json import Jsonb

sys.stdout.reconfigure(encoding="utf-8")

DB = dict(host="127.0.0.1", port=5432, dbname="kaoyan", user="kaoyan", password="kaoyan_dev_2026")

# 公共课：不参与专业匹配
PUBLIC_SUBJECTS = {
    "思想政治理论", "英语（一）", "英语（二）", "英语", "数学（一）", "数学（二）", "数学（三）",
    "数学", "日语", "俄语", "英语或俄语", "英语或俄语或日语", "法硕联考专业基础", "法硕联考综合",
}

# 专业课名 → 知识库 subject name 的别名映射（归一化）
SUBJECT_ALIAS = {
    "通信原理": "通信原理",
    "信号与系统": "信号与系统",
    "电路": "电路",
    "电路原理": "电路",
    "电路分析": "电路分析",
    "数字电路": "数字电子技术",
    "数字电子技术": "数字电子技术",
    "模拟电子技术": "模拟电子技术",
    "模拟电路": "模拟电子技术",
    "数模电": "数字电子技术",
    "电子线路": "模拟电子技术",
    "半导体物理": "电子科学与技术",
    "电磁场与电磁波": "电磁场与电磁波",
    "电磁场理论": "电磁场与电磁波",
    "计算机网络": "计算机网络",
    "数据结构": "数据结构",
    "操作系统": "操作系统",
    "软件工程": "软件工程",
    "自动控制原理": "自动控制原理",
    "自动控制": "自动控制原理",
    "控制原理": "自动控制原理",
    "计算机学科专业基础": "计算机学科专业基础408",
    "计算机专业基础综合": "计算机学科专业基础408",
    "计算机基础": "计算机基础",
    "普通物理": "普通物理",
    "普通物理学": "普通物理",
    "量子力学": "普通物理",
    "工程光学": "光学与工程光学",
    "光学": "光学",
    "数字信号处理": "数字信号处理",
    "数字信号处理基础": "数字信号处理",
    "微机原理": "计算机基础",
    "微机原理与接口技术": "计算机基础",
    "管理学": "管理类联考综合",
    "心理学专业基础综合": "心理学专业基础",
    "心理学专业基础": "心理学专业基础",
    "教育学专业基础综合": "教育学专业基础",
    "教育学专业基础": "教育学专业基础",
    "法律硕士专业基础": "法律硕士专业基础",
    "西医综合": "西医综合",
    "中医综合": "中医综合",
    "经济类联考综合": "经济类联考综合",
    "管理类联考综合": "管理类联考综合",
    "电气工程": "电气工程",
    "电子科学与技术": "电子科学与技术",
    "信息与通信工程": "信息与通信工程",
    "计算机科学与技术": "计算机科学与技术",
    "光学工程": "光学工程",
    "电子信息": "电子信息",
}

# 科目代码剥离正则：如 "(801)机械原理" -> "机械原理"
_CODE_RE = re.compile(r"^[（(]\s*\d{2,4}[A-Za-z]?\s*[）)]\s*")


def strip_code(subject: str) -> str:
    """剥离科目代码前缀。如 '(801)机械原理' -> '机械原理'。"""
    s = subject.strip()
    s = _CODE_RE.sub("", s)
    # 去掉剩余括注
    s = re.sub(r"[（(][^）)]*[）)]", "", s).strip()
    return s


def normalize_subject(subject: str) -> str | None:
    """把专业课名归一到知识库 subject.name。匹配不到返回 None。"""
    s = strip_code(subject)
    if not s:
        return None
    # 直接匹配
    if s in SUBJECT_ALIAS:
        return SUBJECT_ALIAS[s]
    # 包含匹配（如 "数据结构与算法" -> "数据结构"）
    for pat, target in SUBJECT_ALIAS.items():
        if pat in s or s in pat:
            return target
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = psycopg.connect(**DB)
    cur = conn.cursor()

    # 知识库科目及其内容量（文档 + 知识点 + 分块）
    cur.execute("""
        SELECT s.id, s.name,
               (SELECT count(*) FROM knowledge_points kp WHERE kp.subject_id = s.id) AS kp_cnt,
               (SELECT count(*) FROM knowledge_chunks c WHERE c.subject_id = s.id) AS chunk_cnt,
               (SELECT count(*) FROM documents d WHERE d.subject_id = s.id) AS doc_cnt
        FROM subjects s
    """)
    subject_info = {}
    for r in cur.fetchall():
        subject_info[r[1]] = {
            "id": r[0],
            "kp_cnt": r[2] if r[2] else 0,
            "chunk_cnt": r[3] if r[3] else 0,
            "doc_cnt": r[4] if r[4] else 0,
        }

    # 学校名映射
    cur.execute("SELECT id, name FROM kaoyan_schools WHERE deleted_at IS NULL")
    school_names = {r[0]: r[1] for r in cur.fetchall()}

    # 读取全部专业及其考试科目
    cur.execute("""
        SELECT id, school_id, name, code, subject_code, exam_subjects
        FROM kaoyan_majors
        WHERE deleted_at IS NULL
    """)
    rows = cur.fetchall()

    links: list[tuple] = []
    stats = Counter()
    matched_majors = 0
    unmatched_subjects = Counter()

    for mid, school_id, name, code, subject_code, exam_subjects in rows:
        if not exam_subjects:
            continue
        subjects = [x for x in exam_subjects if isinstance(x, str)]
        # 只取专业课（非公共课）
        prof_subjects = []
        for s in subjects:
            core = strip_code(s)
            if not core:
                continue
            if core in PUBLIC_SUBJECTS or any(p in core for p in PUBLIC_SUBJECTS if len(p) > 2):
                continue
            prof_subjects.append(s)

        found_any = False
        for s in prof_subjects:
            target = normalize_subject(s)
            if not target:
                unmatched_subjects[s] += 1
                continue
            info = subject_info.get(target)
            if info is None:
                unmatched_subjects[s] += 1
                continue
            # 生成关联（10 列）
            kb_count = info["kp_cnt"] + info["chunk_cnt"] + info["doc_cnt"]
            links.append((
                mid,                                  # major_id
                school_id or 0,                        # school_id
                school_names.get(school_id, "") or "", # school_name
                name or "",                            # major_name
                code or subject_code or "",            # major_code
                target,                                # subject_name
                "L1", "exact",                         # match_level, match_type
                kb_count,                               # kb_doc_count
                1.0,                                   # confidence
            ))
            found_any = True
            stats[target] += 1
        if found_any:
            matched_majors += 1

    # 去重：唯一约束 (major_id, subject_name)
    seen = set()
    dedup_links = []
    for link in links:
        key = (link[0], link[5])
        if key in seen:
            continue
        seen.add(key)
        dedup_links.append(link)

    print(f"总专业: {len(rows)}")
    print(f"成功关联专业数: {matched_majors}")
    print(f"生成关联记录数（去重前）: {len(links)}")
    print(f"生成关联记录数（去重后）: {len(dedup_links)}")
    print()
    print("=== 关联科目分布 TOP30 ===")
    for k, v in stats.most_common(30):
        print(f"  {k}: {v}")
    print()
    print("=== 未匹配专业课 TOP15 ===")
    for k, v in unmatched_subjects.most_common(15):
        print(f"  {k}: {v}")

    if not args.apply:
        print("\n[dry-run] 未写入数据库。加 --apply 执行。")
        conn.close()
        return

    try:
        # 清空旧表
        cur.execute("DELETE FROM kaoyan_major_kb_link")
        print(f"已清空旧表: {cur.rowcount}")
        # 批量写入（去重后）
        with conn.cursor() as cur2:
            cur2.executemany(
                """
                INSERT INTO kaoyan_major_kb_link
                    (major_id, school_id, school_name, major_name, major_code, subject_name,
                     match_level, match_type, kb_doc_count, confidence, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                dedup_links,
            )
            print(f"写入关联记录: {cur2.rowcount}")
        conn.commit()
        print("提交成功！")
    except Exception as exc:
        conn.rollback()
        print(f"写入失败，已回滚: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()