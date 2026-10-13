# -*- coding: utf-8 -*-
"""建立「考研专业 ↔ 知识库文档」L1 精确关联表。

设计要点
--------
1. **新建独立表 `kaoyan_major_kb_link`，不改 `kaoyan_majors` 表结构**
   （notice-read-track 同事可能正在动相关结构，避免冲突）。
2. **只落 L1（专业课名 == 知识库 subject，零误判）**
   L2（别名归一）需人工过别名表，L3（弱信号包含关系）不上。
3. **只用专业课（第 3 门）匹配，绝不用数学/英语/政治**。
   825/832 条专业都考数学+英语，公共课人人必考，拿它匹配必然虚高到 98%+，
   零信息量——这是本脚本第一版的实测教训。
4. 库内 `exam_subjects` 存的是**用' | ' 拼接的 JSON 字符串**（不是 JSON 数组），
   必须 json.loads 后再按 `|` 切分。

用法
----
    python scripts/build_major_kb_link.py            # dry-run，只报告
    python scripts/build_major_kb_link.py --apply    # 写库（先 backup() 再写）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\data\backups"

# 专业课别名表（L2 用）。本次只跑 L1，此表保留供后续人工审核后启用。
SUBJECT_ALIAS: dict[str, list[str]] = {
    "408": ["计算机统考408", "计算机学科专业基础综合"],
    "数电": ["数字电子技术"],
    "模电": ["模拟电子技术"],
    "数模电": ["数字电子技术", "模拟电子技术"],
    "电子技术基础": ["数字电子技术", "模拟电子技术", "数模电"],
    "电路": ["电路"],
    "信号与系统": ["信号与系统"],
    "通信原理": ["通信原理"],
    "数据结构": ["数据结构"],
    "计算机网络": ["计算机网络"],
    "操作系统": ["操作系统"],
    "软件工程": ["软件工程"],
    "自动控制原理": ["自动控制原理"],
    "机械原理": ["机械原理"],
    "理论力学": ["理论力学"],
    "材料力学": ["材料力学"],
    "电磁场与电磁波": ["电磁场与电磁波"],
    "半导体物理": ["半导体物理"],
    "微机原理": ["微机原理与接口技术"],
}

# 公共课：人人必考，不能用于匹配（否则匹配率虚高到 98%）
PUBLIC_SUBJECTS = {
    "政治", "英语", "英语一", "英语二", "数学", "数学一", "数学二", "数学三",
    "英语或俄语", "英语或俄语或日语", "日语", "俄语",
}

_CODE_RE = re.compile(r"[（(]\s*\d{3,5}\s*[）)]")
_NOISE_RE = re.compile(r"[（(][^）)]*[）)]")
_WS_RE = re.compile(r"\s+")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS kaoyan_major_kb_link (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    major_id      INTEGER NOT NULL,          -- kaoyan_majors.id
    school_id     INTEGER NOT NULL,          -- 冗余，便于按院校聚合查询
    school_name   TEXT NOT NULL DEFAULT '',
    major_name    TEXT NOT NULL DEFAULT '',
    major_code    TEXT,
    subject_name  TEXT NOT NULL,             -- 专业课名（已剥离科目代码）
    match_level   TEXT NOT NULL DEFAULT 'L1',
    match_type    TEXT NOT NULL DEFAULT 'exact',
    kb_doc_count  INTEGER NOT NULL DEFAULT 0,
    confidence    REAL NOT NULL DEFAULT 1.0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (major_id, subject_name)
);
CREATE INDEX IF NOT EXISTS idx_mkb_major   ON kaoyan_major_kb_link (major_id);
CREATE INDEX IF NOT EXISTS idx_mkb_school  ON kaoyan_major_kb_link (school_id);
CREATE INDEX IF NOT EXISTS idx_mkb_subject ON kaoyan_major_kb_link (subject_name);
"""


def decode_subjects(raw) -> list[str]:
    """把 kaoyan_majors.exam_subjects 解析成科目名列表。

    库内格式陷阱：存的是 **一个用 ' | ' 拼接的 JSON 字符串**，例如
    '"(301)数学（一） | (201)英语（一） | (802)通信类专业综合"'。
    """
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, str):
        data = [data]
    if not isinstance(data, list):
        return []
    flat: list[str] = []
    for item in data:
        for seg in re.split(r"\s*\|\s*", str(item)):
            if seg.strip():
                flat.append(seg)
    out: list[str] = []
    for seg in flat:
        seg = _CODE_RE.sub("", seg).strip()   # 剥 (301) 科目代码前缀
        seg = _NOISE_RE.sub("", seg).strip()  # 剥（含..）等括注
        seg = _WS_RE.sub("", seg)
        if seg:
            out.append(seg)
    return out


def professional_subject(subjects: list[str]) -> str | None:
    """取出专业课（非公共课）。返回第一条专业课，无则 None。"""
    for s in subjects:
        if s not in PUBLIC_SUBJECTS:
            return s
    return None


def backup_db(tag: str) -> str:
    """SQLite WAL 模式下必须用 backup() API；cp 会丢未合并的 WAL 数据。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"kaoyan_pre_kblink_{stamp}_{tag}.db")
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def build_index(conn) -> dict[str, list[tuple[int, str]]]:
    """subject → [(document_id, file_name)]，供给侧索引。

    注意 documents 表没有 title 列，标题字段是 file_name。
    """
    idx: dict[str, list[tuple[int, str]]] = defaultdict(list)
    rows = conn.execute(
        "SELECT id, subject, file_name FROM documents WHERE subject IS NOT NULL "
        "AND TRIM(subject) <> ''"
    ).fetchall()
    for did, subj, name in rows:
        key = _WS_RE.sub("", str(subj))
        idx[key].append((did, name or ""))
    return idx


def collect_candidates(conn, idx) -> tuple[list[dict], Counter]:
    """扫描全部专业，只保留 L1 精确命中。"""
    rows = conn.execute(
        "SELECT m.id, m.school_id, s.name, m.name, m.code, m.exam_subjects "
        "FROM kaoyan_majors m "
        "LEFT JOIN kaoyan_schools s ON s.id = m.school_id"
    ).fetchall()
    stat: Counter = Counter()
    links: list[dict] = []
    for mid, sid, sname, mname, mcode, raw in rows:
        subs = decode_subjects(raw)
        stat["_total"] += 1
        ps = professional_subject(subs)
        if ps is None:
            stat["无专业课"] += 1
            continue
        key = _WS_RE.sub("", ps)
        if key in idx:
            links.append({
                "major_id": mid,
                "school_id": sid,
                "school_name": sname or "",
                "major_name": mname or "",
                "major_code": mcode,
                "subject_name": ps,
                "kb_doc_count": len(idx[key]),
            })
            stat["L1"] += 1
        else:
            stat["非L1"] += 1
    return links, stat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True) if not args.apply else sqlite3.connect(DB)
    try:
        idx = build_index(conn)
        print("=" * 70)
        print("知识库供给侧（documents.subject 去重）")
        print("=" * 70)
        for k, v in sorted(idx.items(), key=lambda kv: -len(kv[1]))[:20]:
            print(f"  {k:24s} {len(v):5d} 篇")

        links, stat = collect_candidates(conn, idx)
        total = stat["_total"]
        print()
        print("=" * 70)
        print("匹配统计（仅专业课）")
        print("=" * 70)
        print(f"  专业总数              {total}")
        print(f"  L1 精确命中           {stat['L1']}  ({stat['L1']/total*100:.1f}%)")
        print(f"  非 L1（本次不落）     {stat['非L1']}")
        print(f"  无专业课              {stat['无专业课']}")

        # 供给缺口：有多少专业考的科目在知识库完全没有对应 subject
        missing: Counter = Counter()
        for mid, sid, sname, mname, mcode, raw in conn.execute(
            "SELECT m.id, m.school_id, s.name, m.name, m.code, m.exam_subjects "
            "FROM kaoyan_majors m LEFT JOIN kaoyan_schools s ON s.id = m.school_id"
        ):
            ps = professional_subject(decode_subjects(raw))
            if ps is None:
                continue
            if _WS_RE.sub("", ps) not in idx:
                missing[ps] += 1
        print()
        print("=" * 70)
        print("供给缺口 TOP20（专业考它，但知识库无对应 subject 的文档）")
        print("=" * 70)
        for k, v in missing.most_common(20):
            print(f"  {k:28s} {v:3d} 个专业")

        by_subject: Counter = Counter(r["subject_name"] for r in links)
        print()
        print("L1 关联按专业课分布 TOP15")
        for k, v in by_subject.most_common(15):
            print(f"  {k:24s} {v:4d} 专业 / {idx[_WS_RE.sub('', k)][0] is not None} "
                  f"{len(idx[_WS_RE.sub('', k)])} 篇文档")

        if not args.apply:
            print()
            print("[dry-run] 未写库。加 --apply 执行。")
            return 0

        print()
        print("=" * 70)
        print("写库")
        print("=" * 70)
        print("已备份：", backup_db("real"))
        conn.executescript(SCHEMA_SQL)
        conn.execute("DELETE FROM kaoyan_major_kb_link")
        conn.executemany(
            "INSERT OR IGNORE INTO kaoyan_major_kb_link "
            "(major_id, school_id, school_name, major_name, major_code, "
            " subject_name, match_level, match_type, kb_doc_count, confidence) "
            "VALUES (?,?,?,?,?,?,'L1','exact',?,1.0)",
            [(r["major_id"], r["school_id"], r["school_name"], r["major_name"],
              r["major_code"], r["subject_name"], r["kb_doc_count"]) for r in links],
        )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM kaoyan_major_kb_link").fetchone()[0]
        print(f"kaoyan_major_kb_link 写入 {n} 行（L1 精确匹配，零误判）")
        print("抽样：")
        for r in conn.execute(
            "SELECT school_name, major_name, subject_name, kb_doc_count "
            "FROM kaoyan_major_kb_link ORDER BY kb_doc_count DESC LIMIT 8"
        ):
            print(f"  {r[0]} | {r[1]} → {r[2]}（{r[3]} 篇）")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())