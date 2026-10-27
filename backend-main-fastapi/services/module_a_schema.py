# -*- coding: utf-8 -*-
"""
模块 A 统一幂等 Schema 升级（V4.0）
==================================
红线：表结构仅允许「ALTER TABLE ... ADD COLUMN」与「CREATE TABLE IF NOT EXISTS」，
禁止重建表。所有 DDL 均可重复执行（列存在性检查 + IF NOT EXISTS）。

新增表：
  - retrieval_gate_logs   （A3 检索门控打点）
  - pending_questions     （A4 知识盲区池）
  - answer_candidates     （A6 答案交叉校验）
  - exam_blueprints       （A5 组卷蓝图）
  - exam_sessions         （A5 模考会话）
  - exam_answers          （A5 模考作答）
  - misconceptions        （A8 错因表）
  - question_knowledge_links（A1/A5 题目-知识点多对多）

ALTER 增强：
  - quiz_questions  +12 列（year/paper/external_id/source_paper/source_page/
                     question_no/confidence/answer_type/is_available/quality/
                     rubric/max_score）
  - error_records   +16 列（knowledge_point_id/error_category/pass_number/
                     ease_factor/interval/repetitions/lapses/next_review/
                     last_review/mastery_level/last_status/recent_weight/
                     prev_ease_factor/prev_interval/prev_repetitions/user_note）
"""
from __future__ import annotations

import logging
from services.dbapi_compat import wrap_conn
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 新表 DDL（全部 CREATE TABLE IF NOT EXISTS，幂等）
# --------------------------------------------------------------------------- #
NEW_TABLES_SQL: list[str] = [
    # A3 检索门控打点（报告 6.1 SQL）
    """
    CREATE TABLE IF NOT EXISTS retrieval_gate_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT NOT NULL,
        is_complex INTEGER NOT NULL DEFAULT 0,
        decision TEXT NOT NULL,
        reason_codes TEXT,
        top1_score REAL, topk_mean REAL,
        top1_margin REAL,
        distinct_doc_count INTEGER,
        gate_mode TEXT,
        would_abstain INTEGER DEFAULT 0,
        latency_ms INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_gate_created ON retrieval_gate_logs(created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_gate_decision ON retrieval_gate_logs(decision)
    """,
    # A4 知识盲区池（报告 6.2 SQL）
    """
    CREATE TABLE IF NOT EXISTS pending_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        subject TEXT,
        asked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        have_basis TEXT,
        have_basis_ids TEXT,
        gap TEXT NOT NULL,
        gap_type TEXT,
        suggestion TEXT,
        suggested_action TEXT,
        status TEXT DEFAULT 'open',
        resolved_by TEXT,
        resolved_at DATETIME,
        occurrence_count INTEGER DEFAULT 1,
        last_occurred_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_questions(status, occurrence_count DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pending_subject ON pending_questions(subject)
    """,
    # A6 答案交叉校验（报告 6.3 SQL）
    """
    CREATE TABLE IF NOT EXISTS answer_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER NOT NULL,
        answer TEXT NOT NULL,
        explanation TEXT,
        confidence REAL NOT NULL DEFAULT 0.5,
        source TEXT NOT NULL,
        used_for_grading INTEGER NOT NULL DEFAULT 0,
        verified_by TEXT, verified_at DATETIME,
        FOREIGN KEY (question_id) REFERENCES quiz_questions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ansc_qid ON answer_candidates(question_id)
    """,
    # A5 组卷蓝图（报告 7.2 SQL）
    """
    CREATE TABLE IF NOT EXISTS exam_blueprints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        paper TEXT NOT NULL,
        year INTEGER,
        section TEXT NOT NULL,
        question_type TEXT NOT NULL,
        count INTEGER NOT NULL,
        score_per_question REAL NOT NULL,
        time_limit_minutes INTEGER,
        sort_order INTEGER NOT NULL,
        kp_filters TEXT,
        is_active INTEGER DEFAULT 1
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_exam_bp ON exam_blueprints(subject, paper, is_active)
    """,
    # A5 模考会话（报告 7.2 SQL）
    """
    CREATE TABLE IF NOT EXISTS exam_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        blueprint_key TEXT,
        subject TEXT NOT NULL, paper TEXT,
        mode TEXT DEFAULT 'normal',
        question_source TEXT DEFAULT 'all',
        config TEXT NOT NULL,
        total_count INTEGER, total_score REAL,
        correct_count INTEGER, score REAL,
        time_limit_minutes INTEGER,
        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME,
        submitted_at DATETIME,
        status TEXT DEFAULT 'ongoing',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_exam_sess_status ON exam_sessions(status)
    """,
    # A5 模考作答（报告 7.2 SQL）
    """
    CREATE TABLE IF NOT EXISTS exam_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        question_snapshot TEXT,
        section TEXT, order_no INTEGER,
        user_answer TEXT, is_correct INTEGER,
        time_spent INTEGER,
        ai_score REAL, self_score REAL, final_score REAL,
        scored_by TEXT,
        error_category TEXT,
        FOREIGN KEY (session_id) REFERENCES exam_sessions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_examans_sid ON exam_answers(session_id)
    """,
    # A8 错因表（报告 7.4 SQL）
    """
    CREATE TABLE IF NOT EXISTS misconceptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER,
        error_record_id INTEGER,
        knowledge_point_id INTEGER,
        pattern TEXT NOT NULL,
        category TEXT,
        suggestion TEXT,
        evidence TEXT,
        synced_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # 说明：knowledge_point_id 的索引由既有 idx_misconceptions_kp 提供，
    # 不再重复创建 idx_mis_kp（2026-10-24 优化：消除冗余索引/启动期竞态）。
    """
    CREATE INDEX IF NOT EXISTS idx_mis_cat ON misconceptions(category)
    """,
    # A1/A5 题目-知识点多对多（报告 7.1 SQL）
    """
    CREATE TABLE IF NOT EXISTS question_knowledge_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER NOT NULL,
        knowledge_point_id INTEGER NOT NULL,
        role TEXT DEFAULT 'primary',
        weight REAL DEFAULT 1.0,
        is_verified INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (question_id, knowledge_point_id),
        FOREIGN KEY (question_id) REFERENCES quiz_questions(id) ON DELETE CASCADE,
        FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_qkl_kp ON question_knowledge_links(knowledge_point_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_qkl_q ON question_knowledge_links(question_id)
    """,
    #阶段复习每日打卡明细表。
    # planner.py 的阶段复习接口（列表/创建/明细/打卡）直接读写本表，
    # 但历史上仅存在于 283MB 真实库中，代码里从未创建——空库或新部署必然
    # 500 OperationalError: no such table: phase_daily_reviews。
    # 列定义严格对齐 planner.py 的 INSERT/SELECT 字段清单。
    """
    CREATE TABLE IF NOT EXISTS phase_daily_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phase_plan_id INTEGER NOT NULL,
        day_num INTEGER NOT NULL,
        date TEXT,
        morning_reviews TEXT DEFAULT '[]',
        evening_reviews TEXT DEFAULT '[]',
        completed INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (phase_plan_id, day_num),
        FOREIGN KEY (phase_plan_id) REFERENCES phase_plans(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pdr_plan ON phase_daily_reviews(phase_plan_id)
    """,
]

# --------------------------------------------------------------------------- #
# ALTER TABLE ... ADD COLUMN（幂等：仅当列不存在时添加）
# --------------------------------------------------------------------------- #
QUIZ_QUESTIONS_ADD_COLUMNS: list[tuple[str, str]] = [
    ("year", "INTEGER"),
    ("paper", "TEXT"),
    ("external_id", "TEXT"),
    ("source_paper", "TEXT"),
    ("source_page", "INTEGER"),
    ("question_no", "INTEGER"),
    ("confidence", "TEXT DEFAULT 'medium'"),
    ("answer_type", "TEXT DEFAULT 'objective'"),
    ("is_available", "INTEGER DEFAULT 1"),
    ("quality", "TEXT"),
    ("rubric", "TEXT"),
    ("max_score", "REAL"),
    # M6-3：复试题标记。存量题默认 0（初试），不影响既有行为。
    ("is_retest", "INTEGER DEFAULT 0"),
    # 题目配图：OCR/人工录入产出的图片引用（URL/相对路径/{url,page,bbox,kind}）。
    ("images", "JSONB DEFAULT '[]'::jsonb"),
]

# IMA 知识库导入：documents 表需要承载「初试/复试」阶段 + IMA 溯源信息。
# stage        : 初试 / 复试（资料所属备考阶段）
# ima_media_id : IMA 侧条目 ID，用于后续按需 fetch 正文（内容不落库，只存指针）
# folder_path  : IMA 内的文件夹路径，保留原始组织结构，便于按目录浏览
DOCUMENTS_ADD_COLUMNS: list[tuple[str, str]] = [
    ("stage", "TEXT"),
    ("ima_media_id", "TEXT"),
    ("folder_path", "TEXT"),
    # 内容性质：知识 / 试题 / 单词。
    # 单独开列而**不复用 doc_type** —— doc_type 是既有语义(文档三层结构 raw/note/index)，
    # 两套语义混在同一列会破坏前端既有筛选，故严格分离。
    ("content_type", "TEXT"),
]

ERROR_RECORDS_ADD_COLUMNS: list[tuple[str, str]] = [
    ("knowledge_point_id", "INTEGER"),
    ("error_category", "TEXT"),
    ("pass_number", "INTEGER DEFAULT 1"),
    ("ease_factor", "REAL DEFAULT 2.5"),
    ("interval", "INTEGER DEFAULT 0"),
    ("repetitions", "INTEGER DEFAULT 0"),
    ("lapses", "INTEGER DEFAULT 0"),
    ("next_review", "DATE"),
    ("last_review", "DATE"),
    ("mastery_level", "TEXT DEFAULT 'not_mastered'"),
    ("last_status", "TEXT DEFAULT 'unreviewed'"),
    ("recent_weight", "REAL DEFAULT 1.0"),
    ("prev_ease_factor", "REAL"),
    ("prev_interval", "INTEGER"),
    ("prev_repetitions", "INTEGER"),
    ("user_note", "TEXT"),
]

_EXTRA_INDEX_SQL: list[str] = [
    # 说明（2026-10-24 优化）：external_id 已有唯一约束 uq_quiz_questions_external，
    # knowledge_point_id 已有 idx_error_kp 的同列索引 idx_error_kp（error_records 上
    # 既有 idx_error_kp），此处不再重复创建，消除冗余索引与启动期竞态。
    # 错题错因聚合（error_category 独立索引）
    "CREATE INDEX IF NOT EXISTS idx_err_cat ON error_records(error_category)",
]


def _is_sqlite(conn) -> bool:
    """连接是否为 SQLite（穿透 SQLAlchemy 连接池代理判断真实驱动）。"""
    from services.ddl_compat import is_sqlite
    return is_sqlite(conn)


def _adapt(stmt: str, conn) -> str:
    """把 SQLite 写法的 DDL 适配到当前连接方言（见 services.ddl_compat）。"""
    from services.ddl_compat import adapt_ddl
    return adapt_ddl(stmt, conn)


def _existing_columns(conn, table: str) -> set[str]:
    """读表已有列。

    方言差异：SQLite 用 `PRAGMA table_info`，PostgreSQL 必须查 information_schema
    （PRAGMA 在 PG 上直接语法错误）。

    注意：这里的 conn 是**底层 DBAPI 连接**（已穿透 SQLAlchemy 代理），
    不能传 SQLAlchemy 的 `text()` 对象 —— psycopg 会报
    `TypeError: object of type 'TextClause' has no len()`（实测踩坑）。
    因此用原生 SQL 字符串 + DBAPI 参数占位符（%s 对 PG、? 对 SQLite）。
    """
    if _is_sqlite(conn):
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r[1] for r in rows}
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def blueprint_question_type_col(conn) -> str:
    """返回 ``exam_blueprints`` 里**真实存在**的题型列名。

    PG 正典 schema 用 ``blueprint_question_type``（见 core/sql 与 orm_aliases 的
    兼容映射）；而本模块的 SQLite 兼容 DDL 用 ``question_type``。二者同名表但
    列名不同，硬写任一个都会在另一侧炸（实测：PG 上
    ``column "question_type" of relation "exam_blueprints" does not exist``）。

    这里不猜方言，直接内省表结构选存在的那个——表结构变了两边都不用改代码。
    """
    cols = _existing_columns(conn, "exam_blueprints")
    lower = {c.lower() for c in cols}
    if "blueprint_question_type" in lower:
        return "blueprint_question_type"
    if "question_type" in lower:
        return "question_type"
    return "question_type"  # 表尚未建好时的安全默认（后续 DDL 会建 question_type）


def _exec_with_retry(conn, stmt, retries: int = 6, wait: float = 2.0):
    """SQLite 写锁竞争（database is locked）重试。

    后端 uvicorn 进程常驻持有 DB 写锁，DDL 在短暂锁窗口内可能失败；
    通过 busy_timeout + 有限重试提升幂等迁移成功率，不影响红线。
    """
    import time

    for i in range(retries):
        try:
            conn.execute(stmt)
            return
        except Exception as e:
            if "locked" in str(e).lower() and i < retries - 1:
                time.sleep(wait)
                continue
            raise


def _alter_add_columns(conn, table: str, columns: list[tuple[str, str]]) -> list[str]:
    existing = _existing_columns(conn, table)
    added: list[str] = []
    for col, ddl in columns:
        if col in existing:
            continue
        # SQLite 没有 JSONB：降级为 JSON 文本列，保证测试/单机模式也能建列。
        if _is_sqlite(conn) and "JSONB" in ddl.upper():
            ddl = ddl.replace("JSONB", "JSON").replace("::jsonb", "")
        _exec_with_retry(conn, f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        added.append(col)
    return added


def ensure_module_a_schema(db: Optional[Session] = None) -> dict:
    """幂等执行模块 A 全部 Schema 变更。

    Returns:
        {"created_tables": [...], "altered": {"quiz_questions": [...], "error_records": [...]}}
    """
    if db is None:
        from database import SessionLocal
        db = SessionLocal()
        close = True
    else:
        close = False
    try:
        conn = wrap_conn(db.connection().connection)
        if _is_sqlite(conn):
            try:
                conn.execute("PRAGMA busy_timeout = 30000")
            except Exception as _exc:  # noqa: BLE001
                # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
                # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
                logging.getLogger(__name__).warning(
                    '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
                )
        created: list[str] = []
        for stmt in NEW_TABLES_SQL:
            _exec_with_retry(conn, _adapt(stmt, conn))
        altered_q = _alter_add_columns(conn, "quiz_questions", QUIZ_QUESTIONS_ADD_COLUMNS)
        altered_e = _alter_add_columns(conn, "error_records", ERROR_RECORDS_ADD_COLUMNS)
        # IMA 导入所需：documents + stage/ima_media_id/folder_path（幂等，列存在则跳过）
        altered_d = _alter_add_columns(conn, "documents", DOCUMENTS_ADD_COLUMNS)
        for stmt in _EXTRA_INDEX_SQL:
            try:
                _exec_with_retry(conn, _adapt(stmt, conn))
            except Exception as e:  # 唯一索引可能因既有重复数据失败，记录但不中断
                logger.warning("创建索引失败(可忽略): %s | %s", stmt[:60], e)
        db.commit()
        return {
            "created_tables": created,
            "altered": {
                "quiz_questions": altered_q,
                "error_records": altered_e,
                "documents": altered_d,
            },
        }
    except Exception as e:
        db.rollback()
        logger.exception("模块 A Schema 升级失败")
        raise
    finally:
        if close:
            db.close()


#: 组卷蓝图的题型词 → question_type 枚举值。
#: 预设沿用报告 7.2 的卷面术语（blank/solve/comprehensive/multi_choice），
#: 但 DB 列是 ``question_type`` ENUM（single/multiple/judge/fill/calc/essay/draw/proof/other），
#: 直接插会在 PG 报 invalid input value for enum（实测）。此处显式归一，
#: 保留术语可追溯、入库值合法。
_BLUEPRINT_QT_MAP: dict[str, str] = {
    "single": "single",
    "multi_choice": "multiple",   # 多项选择
    "blank": "fill",              # 填空
    "solve": "calc",              # 解答
    "comprehensive": "calc",      # 综合应用
    "judge": "judge",
    "essay": "essay",
    "calc": "calc",
    "draw": "draw",
    "proof": "proof",
}


def _normalize_blueprint_qt(qtype: str) -> str:
    """把卷面题型词归一到 question_type 枚举值；未知值退 ``other``。"""
    return _BLUEPRINT_QT_MAP.get((qtype or "").strip().lower(), "other")


def ensure_blueprints(db: Optional[Session] = None) -> int:
    """写入 4 科预置蓝图（幂等：仅当科目+paper 无任何蓝图时插入）。

    Returns:
        本次新增蓝图条数
    """
    if db is None:
        from database import SessionLocal
        db = SessionLocal()
        close = True
    else:
        close = False
    try:
        conn = wrap_conn(db.connection().connection)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS exam_blueprints ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " subject TEXT NOT NULL, paper TEXT NOT NULL, year INTEGER,"
            " section TEXT NOT NULL, question_type TEXT NOT NULL,"
            " count INTEGER NOT NULL, score_per_question REAL NOT NULL,"
            " time_limit_minutes INTEGER, sort_order INTEGER NOT NULL,"
            " kp_filters TEXT, is_active INTEGER DEFAULT 1)"
        )
        existing = conn.execute(
            "SELECT DISTINCT subject, paper FROM exam_blueprints"
        ).fetchall()
        have = {(r[0], r[1]) for r in existing}
        # 真实卷面结构（报告 7.2 表）
        presets = [
            # 数学二：10 选择×5 + 6 填空×5 + 6 解答×~10 = 150
            ("数学", "math2", "一、单项选择题", "single", 10, 5.0),
            ("数学", "math2", "二、填空题", "blank", 6, 5.0),
            ("数学", "math2", "三、解答题", "solve", 6, 10.0),
            # 408：40 选择×2 + 7 综合 = 150
            ("408", "cs408", "一、单项选择题", "single", 40, 2.0),
            ("408", "cs408", "二、综合应用题", "comprehensive", 7, 10.0),
            # 政治：16 单选×1 + 17 多选×2 = 50
            ("政治", "politics", "一、单项选择题", "single", 16, 1.0),
            ("政治", "politics", "二、多项选择题", "multi_choice", 17, 2.0),
            # 英语二：50 词汇四选一×2 = 100
            ("英语", "english2", "一、词汇与语法（四选一）", "single", 50, 2.0),
        ]
        added = 0
        # 题型列名按表结构内省（PG=blueprint_question_type / SQLite=question_type）
        qt_col = blueprint_question_type_col(conn)
        for subject, paper, section, qtype, count, score in presets:
            if (subject, paper) in have:
                continue
            # is_active 用绑定参数传 Python True：PG 列是 boolean、SQLite 是整数，
            # 写字面量 1 会在 PG 报 DatatypeMismatch（实测），绑定 bool 两边都对。
            conn.execute(
                f"INSERT INTO exam_blueprints (subject, paper, section, {qt_col},"
                " count, score_per_question, time_limit_minutes, sort_order, is_active)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (subject, paper, section, _normalize_blueprint_qt(qtype),
                 count, score, 180, added + 1, True),
            )
            added += 1
        db.commit()
        return added
    except Exception as e:
        db.rollback()
        logger.exception("预置蓝图写入失败")
        raise
    finally:
        if close:
            db.close()


if __name__ == "__main__":  # pragma: no cover
    import json
    from database import SessionLocal

    db = SessionLocal()
    try:
        r = ensure_module_a_schema(db)
        b = ensure_blueprints(db)
        print(json.dumps({"schema": r, "blueprints_added": b}, ensure_ascii=False, indent=2))
    finally:
        db.close()
