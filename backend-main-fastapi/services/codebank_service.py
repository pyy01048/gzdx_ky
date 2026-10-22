# -*- coding: utf-8 -*-
"""复试代码题库服务（V15）：LeetCode 式题库 + 知识点全景 + 考频分析。

原生 DDL 幂等建表（code_problems / code_subjects），不动 ORM 基线。
考频口径：frequency 1-5 由真题/院校复试大纲人工标注；appear_years 记录
出现年份，全景视图聚合 tags → 题数/平均考频/最近出现年份。

2026-10 修正：真实数据在 PostgreSQL 的 code_problems 表（097_code_oj.sql，
600 行），code_questions 是 SQLite 时代残留空表。所有 SQL 改读
code_problems，并按列差异做字段映射：
  difficulty SMALLINT → 文本等级（1=easy / 2-3=medium / 4-5=hard）
  tags       JSONB    → list
  statement  ← description
  input_desc ← input_format
  output_desc← output_format
  examples   ← sample_input + sample_output 组合
  hint       ← hints
code_problems 无 frequency/appear_years/languages/source 列，由
ensure_schema 幂等补列（add_column_if_missing），保持 API 响应结构兼容。
"""
from __future__ import annotations

import json
from utils.timeutil import utcnow  # 写库时间统一 naive UTC（P1-C2）
from typing import Dict, List, Optional

from sqlalchemy.orm import Session
from services.dbapi_compat import wrap_conn  # noqa: E402  PG/SQLite 双底座连接适配

_DDL = """
CREATE TABLE IF NOT EXISTS code_problems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    subject TEXT,
    difficulty INTEGER NOT NULL DEFAULT 2,
    description TEXT NOT NULL,
    input_format TEXT,
    output_format TEXT,
    sample_input TEXT,
    sample_output TEXT,
    hints TEXT,
    time_limit_ms INTEGER NOT NULL DEFAULT 1000,
    memory_limit_kb INTEGER NOT NULL DEFAULT 256000,
    tags TEXT,
    is_public INTEGER NOT NULL DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
)
"""
_SUBJECT_DDL = """
CREATE TABLE IF NOT EXISTS code_subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    direction TEXT,
    is_builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT
)
"""
_BUILTIN_SUBJECTS = [
    ("数学", "公共课"), ("英语", "公共课"), ("政治", "公共课"),
    ("数电", "电子"), ("模电", "电子"), ("信号与系统", "通信"),
    ("光学", "光电"), ("408计算机", "计算机"),
    ("通信原理", "复试·通信"), ("数字信号处理", "复试·通信"),
    ("信息论与编码", "复试·通信"), ("工程光学", "复试·光电"),
    ("光电子技术", "复试·光电"), ("半导体物理", "复试·电子"),
    ("电机学", "复试·电气"), ("电力系统分析", "复试·电气"),
    ("电力电子技术", "复试·电气"), ("自动控制原理", "复试·电气"),
    ("数据结构与算法", "复试·上机"), ("C++编程", "复试·上机"),
    ("Python编程", "复试·上机"), ("计算机网络", "复试·通信"),
]

#: 补列清单：code_problems（097_code_oj.sql）没有的旧 API 字段，
#: 在 ensure_schema 里幂等 ALTER 补上，保证旧响应结构（languages/frequency/
#: appear_years/source）在新数据源下仍可用。PG 侧用 add_column_if_missing 自动
#: 生成 IF NOT EXISTS。
_EXTRA_COLUMNS = [
    ("frequency", "INTEGER NOT NULL DEFAULT 3"),
    ("appear_years", "TEXT"),
    ("languages", "TEXT"),
    ("source", "TEXT"),
]

#: difficulty SMALLINT → 文本等级（与旧 API 的 easy/medium/hard 兼容）。
#: 097_code_oj.sql 注释为 1-5 难度等级，这里按三档收敛：
#: 1 → easy，2/3 → medium，4/5 → hard。
_DIFFICULTY_MAP = {1: "easy", 2: "medium", 3: "medium", 4: "hard", 5: "hard"}


def _difficulty_text(v) -> str:
    """把 smallint 难度映射为旧 API 的文本等级。"""
    try:
        return _DIFFICULTY_MAP.get(int(v), "medium")
    except (TypeError, ValueError):
        return "medium"


def _parse_tags(v) -> List:
    """解析 tags 列：PG 的 JSONB 列由 psycopg 直接反序列化为 list，
    SQLite 的 TEXT 列返回字符串 —— 两者都要兼容。"""
    if v is None or v == "":
        return []
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    if isinstance(v, list):
        return v
    return []


def _parse_json_list(v) -> List:
    """解析 TEXT 列存的 JSON 数组（appear_years/languages）。"""
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return v
    try:
        parsed = json.loads(v)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _examples_from_row(sample_input, sample_output) -> List[Dict]:
    """把 code_problems 的 sample_input/sample_output 组合成旧 API examples 数组。"""
    examples = []
    inp = (sample_input or "").strip()
    out = (sample_output or "").strip()
    if inp or out:
        examples.append({"input": inp, "output": out})
    return examples


def ensure_schema(db: Session) -> None:
    conn = wrap_conn(db.connection().connection)
    from services.ddl_compat import adapt_ddl
    conn.execute(adapt_ddl(_DDL, conn))
    conn.execute(adapt_ddl(_SUBJECT_DDL, conn))
    # 幂等补列：code_problems 权威表缺的旧 API 字段
    from services.dbapi_compat import add_column_if_missing
    for col, ddl_type in _EXTRA_COLUMNS:
        add_column_if_missing(conn, "code_problems", col, ddl_type)
    for name, direction in _BUILTIN_SUBJECTS:
        conn.execute(
            "INSERT OR IGNORE INTO code_subjects (name, direction, is_builtin, created_at) "
            "VALUES (?,?,1,?)", (name, direction, utcnow().isoformat()))
    conn.commit()


def list_questions(db: Session, subject: Optional[str] = None,
                   difficulty: Optional[str] = None, tag: Optional[str] = None,
                   q: Optional[str] = None, min_frequency: int = 0,
                   limit: int = 50, offset: int = 0) -> Dict:
    """LeetCode 式列表：过滤 + 分页，返回 {total, items}。"""
    ensure_schema(db)
    conn = wrap_conn(db.connection().connection)
    where, args = ["is_public = TRUE"], []
    if subject:
        where.append("subject=?"); args.append(subject)
    if difficulty:
        # 文本难度 → smallint 区间：easy=1, medium=2/3, hard=4/5
        diff = (difficulty or "").strip().lower()
        if diff in ("easy", "1"):
            where.append("difficulty = 1")
        elif diff in ("hard", "4", "5"):
            where.append("difficulty >= 4")
        else:
            where.append("difficulty IN (2,3)")
    if min_frequency:
        where.append("frequency>=?"); args.append(min_frequency)
    if q:
        where.append("(title LIKE ? OR description LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%"])
    if tag:
        # code_problems.tags 是 JSONB；CAST(... AS TEXT) 在 SQLite/PG 都可用
        where.append("CAST(tags AS TEXT) LIKE ?"); args.append(f'%"{tag}"%')
    w = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM code_problems WHERE {w}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT id, title, subject, difficulty, tags, frequency, appear_years "
        f"FROM code_problems WHERE {w} ORDER BY frequency DESC, id LIMIT ? OFFSET ?",
        [*args, limit, offset]).fetchall()
    return {"total": total, "items": [
        {"id": r[0], "title": r[1], "subject": r[2],
         "difficulty": _difficulty_text(r[3]),
         "tags": _parse_tags(r[4]), "frequency": r[5],
         "appear_years": _parse_json_list(r[6])} for r in rows]}


def get_question(db: Session, qid: int) -> Optional[Dict]:
    ensure_schema(db)
    conn = wrap_conn(db.connection().connection)
    r = conn.execute(
        "SELECT id, title, subject, difficulty, tags, languages, description, "
        "input_format, output_format, sample_input, sample_output, hints, source, "
        "frequency, appear_years "
        "FROM code_problems WHERE id=? AND is_public = TRUE", (qid,)).fetchone()
    if not r:
        return None
    return {"id": r[0], "title": r[1], "subject": r[2],
            "difficulty": _difficulty_text(r[3]),
            "tags": _parse_tags(r[4]), "languages": _parse_json_list(r[5]),
            "statement": r[6], "input_desc": r[7], "output_desc": r[8],
            "examples": _examples_from_row(r[9], r[10]),
            "hint": r[11], "source": r[12],
            "frequency": r[13], "appear_years": _parse_json_list(r[14])}


def panorama(db: Session, subject: Optional[str] = None) -> Dict:
    """知识点全景：subject → tag → 题数/平均考频/最高考频题。对标 codebrick panorama。"""
    ensure_schema(db)
    conn = wrap_conn(db.connection().connection)
    rows = conn.execute(
        "SELECT subject, tags, title, frequency FROM code_problems WHERE is_public = TRUE"
        + (" AND subject=?" if subject else ""), (subject,) if subject else ()).fetchall()
    tree: Dict[str, Dict] = {}
    for subj, tags, title, freq in rows:
        for t in _parse_tags(tags):
            node = tree.setdefault(t, {"subject": subj, "total": 0,
                                       "freq_sum": 0, "hot": None})
            node["total"] += 1
            node["freq_sum"] += freq or 0
            if node["hot"] is None or (freq or 0) > node["hot"]["frequency"]:
                node["hot"] = {"title": title, "frequency": freq}
    items = [{"tag": t, **{k: v for k, v in n.items() if k != "freq_sum"},
              "avg_frequency": round(n["freq_sum"] / max(1, n["total"]), 1)}
             for t, n in tree.items()]
    items.sort(key=lambda x: (-x["avg_frequency"], -x["total"]))
    return {"subjects": sorted({r[0] for r in rows}), "items": items}


def exam_strategy(db: Session) -> Dict:
    """考频分析（对标 codebrick exam-strategy）：高频题 TOP + 科目分布 + 复试方向权重。"""
    ensure_schema(db)
    conn = wrap_conn(db.connection().connection)
    top = conn.execute(
        "SELECT id, title, subject, difficulty, frequency, appear_years FROM code_problems "
        "WHERE is_public = TRUE ORDER BY frequency DESC LIMIT 10").fetchall()
    by_subject = conn.execute(
        "SELECT subject, COUNT(*), AVG(frequency) FROM code_problems "
        "WHERE is_public = TRUE GROUP BY subject ORDER BY 2 DESC").fetchall()
    by_direction = conn.execute(
        "SELECT s.direction, COUNT(c.id) FROM code_subjects s "
        "LEFT JOIN code_problems c ON c.subject=s.name AND c.is_public = TRUE "
        "WHERE s.direction IS NOT NULL GROUP BY s.direction ORDER BY 2 DESC").fetchall()
    return {
        "top_questions": [{"id": r[0], "title": r[1], "subject": r[2],
                           "difficulty": _difficulty_text(r[3]), "frequency": r[4],
                           "appear_years": _parse_json_list(r[5])} for r in top],
        "by_subject": [{"subject": r[0], "count": r[1],
                        "avg_frequency": round(r[2] or 0, 1)} for r in by_subject],
        "by_direction": [{"direction": r[0], "count": r[1]} for r in by_direction],
    }


def list_subjects(db: Session) -> List[Dict]:
    ensure_schema(db)
    conn = wrap_conn(db.connection().connection)
    rows = conn.execute(
        "SELECT s.id, s.name, s.direction, s.is_builtin, COUNT(c.id) FROM code_subjects s "
        "LEFT JOIN code_problems c ON c.subject=s.name AND c.is_public = TRUE "
        "GROUP BY s.id ORDER BY s.is_builtin DESC, s.id").fetchall()
    return [{"id": r[0], "name": r[1], "direction": r[2], "is_builtin": bool(r[3]),
             "question_count": r[4]} for r in rows]


def add_subject(db: Session, name: str, direction: Optional[str] = None) -> Dict:
    """用户自添加科目（可随时加：信号与系统/光学/408/任何复试科目）。"""
    ensure_schema(db)
    conn = wrap_conn(db.connection().connection)
    try:
        conn.execute(
            "INSERT INTO code_subjects (name, direction, is_builtin, created_at) "
            "VALUES (?,?,0,?)", (name.strip(), direction, utcnow().isoformat()))
        conn.commit()
    except Exception:
        return {"added": False, "reason": "科目已存在"}
    return {"added": True, "name": name.strip()}


def upsert_question(db: Session, item: Dict) -> int:
    """导入/新增代码题（幂等：同科同题干跳过）。"""
    ensure_schema(db)
    conn = wrap_conn(db.connection().connection)
    dup = conn.execute(
        "SELECT id FROM code_problems WHERE subject=? AND title=? LIMIT 1",
        (item.get("subject", "通用"), item["title"])).fetchone()
    if dup:
        return dup[0]
    cur = conn.execute(
        "INSERT INTO code_problems (title, subject, difficulty, tags, languages, "
        "description, input_format, output_format, sample_input, sample_output, "
        "hints, source, frequency, appear_years, is_public, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,TRUE,?,?)",
        (item["title"], item.get("subject", "通用"),
         {"easy": 1, "medium": 2, "hard": 5}.get((item.get("difficulty") or "medium").lower(), 2),
         json.dumps(item.get("tags", []), ensure_ascii=False),
         json.dumps(item.get("languages", []), ensure_ascii=False),
         item.get("statement", ""), item.get("input_desc", ""),
         item.get("output_desc", ""),
         (item.get("examples") or [{}])[0].get("input", "") if isinstance(item.get("examples"), list) and item.get("examples") else "",
         (item.get("examples") or [{}])[0].get("output", "") if isinstance(item.get("examples"), list) and item.get("examples") else "",
         item.get("hint", ""), item.get("source", ""),
         item.get("frequency", 3),
         json.dumps(item.get("appear_years", []), ensure_ascii=False),
         utcnow().isoformat(), utcnow().isoformat()))
    conn.commit()
    # PG 迁移修正：psycopg 无 lastrowid，PG 侧靠 RETURNING id 取回主键
    from services.dbapi_compat import is_sqlite
    if is_sqlite(conn):
        return cur.lastrowid
    return int(cur.fetchone()[0]) if cur.description else None