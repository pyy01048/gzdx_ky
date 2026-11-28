# -*- coding: utf-8 -*-
"""知识点掌握度**四态模型**（未学 / 学习中 / 薄弱 / 已掌握）。

背景（2026-10 修复"1067 个知识点全标薄弱、已掌握为 0"）
----------------------------------------------------
旧口径只有"已掌握（mastery≥70）/ 其余全算薄弱（mastery<40）"两档，
未学习的知识点 mastery=0 被误算进薄弱 —— 知识库 1067 个知识点里
1065 个没有任何学习记录，于是薄弱数永远≈总数，"薄弱"指标失去意义。

三态口径（2026-10-16）：
  - 未学 unlearned（灰）：无任何学习记录 —— 从未复习、无关联答题/错题
  - 薄弱 weak（黄）：有学习记录但掌握度 < MASTERED_THRESHOLD
    （正确率低 / 复习到期未过）
  - 已掌握 mastered（绿）：有学习记录且掌握度 ≥ MASTERED_THRESHOLD

四态口径（2026-10-17，任务 #14）：
  - 未学 unlearned（灰）：同上
  - 学习中 learning（蓝）：有学习记录，掌握度在 (0, LEARNING_THRESHOLD) 区间
    —— 刚开始接触，正在积累正确率
  - 薄弱 weak（黄）：有学习记录，掌握度在 [LEARNING_THRESHOLD, MASTERED_THRESHOLD) 区间
    —— 已有一定基础但仍需巩固
  - 已掌握 mastered（绿）：同上

未学知识点不计入薄弱统计 —— 它们不是"薄弱"，是"还没开始"。

本模块是四态口径的唯一事实源：review_service / taxonomy / learner_profile /
learning_analytics 都从这里取阈值与判定，禁止在别处再写一套。
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Union

# 已掌握阈值（与历史口径一致：mastery ≥ 70）
MASTERED_THRESHOLD = 70
# 学习中→薄弱分界点：掌握度达到 30 即脱离"学习中"进入"薄弱"
LEARNING_THRESHOLD = 30

STATE_UNLEARNED = "unlearned"
STATE_LEARNING = "learning"
STATE_WEAK = "weak"
STATE_MASTERED = "mastered"

# 四态 → 中文标签（前端色阶：未学=灰 / 学习中=蓝 / 薄弱=黄 / 已掌握=绿）
STATE_LABELS = {
    STATE_UNLEARNED: "未学",
    STATE_LEARNING: "学习中",
    STATE_WEAK: "薄弱",
    STATE_MASTERED: "已掌握",
}

# 「有学习记录」的判定 SQL：任一路径有记录即算学过。
# 路径：复习回写(review_count/review_records) / 关联答题 / 关联错题 /
#       错题知识点直链 / 错题RAG链 / 学习事件埋点。
# UNION 自动去重；各子查询都走已有索引，1067 个知识点下为毫秒级。
LEARNED_KP_SQL = """
SELECT id FROM knowledge_points WHERE review_count > 0
UNION
SELECT item_id FROM review_records WHERE item_type IN ('knowledge', 'knowledge_point')
UNION
SELECT l.knowledge_point_id FROM question_knowledge_links l
  WHERE l.question_id IN (SELECT question_id FROM answer_records)
UNION
SELECT l.knowledge_point_id FROM question_knowledge_links l
  WHERE l.question_id IN (SELECT question_id FROM error_records)
UNION
SELECT knowledge_point_id FROM error_knowledge_links WHERE knowledge_point_id IS NOT NULL
UNION
SELECT knowledge_point_id FROM error_records WHERE knowledge_point_id IS NOT NULL
UNION
SELECT knowledge_point_id FROM study_events WHERE knowledge_point_id IS NOT NULL
"""

# 按用户口径的「有学习记录」判定（B4 隔离）：
# - 个人流水表（review_records/answer_records/error_records/study_events）全部按
#   user_id 过滤，他人行为不算「我学过」；
# - error_knowledge_links 经 error_records 联表判归属（冗余 user_id 列存量可能为 NULL）；
# - 刻意**不含** knowledge_points.review_count>0 路径：那是全局镜像字段，
#   个人复习不再回写它（权威在 review_schedules 用户行），也不能拿它判「我学过」。
LEARNED_KP_SQL_USER = """
SELECT item_id FROM review_records
  WHERE user_id = :uid AND item_type IN ('knowledge', 'knowledge_point')
UNION
SELECT l.knowledge_point_id FROM question_knowledge_links l
  WHERE l.question_id IN (
      SELECT question_id FROM answer_records WHERE user_id = :uid AND is_correct IS NOT NULL
  )
UNION
SELECT l.knowledge_point_id FROM question_knowledge_links l
  WHERE l.question_id IN (SELECT question_id FROM error_records WHERE user_id = :uid)
UNION
SELECT l.knowledge_point_id FROM error_knowledge_links l
  JOIN error_records e ON e.id = l.error_id
  WHERE e.user_id = :uid AND l.knowledge_point_id IS NOT NULL
UNION
SELECT knowledge_point_id FROM error_records
  WHERE user_id = :uid AND knowledge_point_id IS NOT NULL
UNION
SELECT knowledge_point_id FROM study_events
  WHERE user_id = :uid AND knowledge_point_id IS NOT NULL
"""


def classify_state(mastery: Union[int, None], has_records: bool) -> str:
    """按（掌握度, 有无学习记录）判四态。

    >>> classify_state(None, False)
    'unlearned'
    >>> classify_state(0, True)
    'learning'
    >>> classify_state(29, True)
    'learning'
    >>> classify_state(30, True)
    'weak'
    >>> classify_state(69, True)
    'weak'
    >>> classify_state(70, True)
    'mastered'
    """
    if not has_records:
        return STATE_UNLEARNED
    m = int(mastery or 0)
    if m >= MASTERED_THRESHOLD:
        return STATE_MASTERED
    if m >= LEARNING_THRESHOLD:
        return STATE_WEAK
    return STATE_LEARNING


#: 错题"已毕业"状态标记（error_records.status 的终态值），与
#: services/review_scheduler / routers/errors.py 的用法保持一致。
STATE_MASTERED_MARK = "graduated"


def error_mastery_state(
    accuracy: Union[float, None],
    review_count: Union[int, None],
    status: Union[str, None],
) -> str:
    """**错题记录**的掌握度四态（复用同一四态口径，不另立档位）。

    背景：错题本的"掌握度"此前是写死的两档（active=未掌握 / graduated=已掌握），
    没有"未学"这一档 —— 新收录、一次都没复习过的错题被打成"未掌握"，
    与知识点的三态口径（未学=灰 / 薄弱=黄 / 已掌握=绿）割裂。

    与 :func:`classify_state` 共用同一阈值（``MASTERED_THRESHOLD`` / ``LEARNING_THRESHOLD``）与标签，
    只把错题的字段折算成四态模型需要的两个入参：

    - ``accuracy``（0-1 正确率，``error_records.accuracy``）→ 折成 0-100 分；
    - "有学习记录"= 复习过（``review_count>0``）或已毕业（``status=='graduated'``）：
      前者是真实复习留痕；后者是"已掌握"的终态标记，直接归 mastered。

    于是：从未复习的新错题 → 未学（灰）；复习过但正确率 < 70 → 薄弱（黄）；
    已毕业 / 正确率 ≥ 70 → 已掌握（绿）。

    >>> error_mastery_state(0.0, 0, "active")
    'unlearned'
    >>> error_mastery_state(0.0, 1, "active")
    'learning'
    >>> error_mastery_state(0.29, 1, "active")
    'learning'
    >>> error_mastery_state(0.3, 1, "active")
    'weak'
    >>> error_mastery_state(0.9, 1, "active")
    'mastered'
    >>> error_mastery_state(0.0, 0, "graduated")
    'mastered'
    """
    if status == STATE_MASTERED_MARK:  # "graduated"
        return STATE_MASTERED
    if not review_count:
        return STATE_UNLEARNED
    score = round(float(accuracy or 0) * 100)
    return classify_state(score, True)


def touch_mastery(session, kp_ids=None) -> int:
    """触发 knowledge_points.mastery 的派生重算，返回受影响行数。

    ## 为什么需要这个函数

    ``mastery`` 是派生列，但**只在 knowledge_points 行被 UPDATE 时**由
    BEFORE UPDATE 触发器 ``sync_kp_mastery()`` 刷新。只写
    ``review_records`` / ``answer_records`` **不会**自动刷新 ——
    于是"复习完掌握度纹丝不动"（答题链路是靠 routers/quiz 里那句
    ``UPDATE knowledge_points SET mastery = mastery`` touch 补上的）。

    ## 为什么不能靠 ORM 赋值

    直觉写法 ``kp.review_count = kp.review_count`` 是无效的：值没变化时
    SQLAlchemy 不会发出 UPDATE，触发器自然不跑（实测 mastery 永远停在 0）。
    必须用 SQL 发一条自赋值 UPDATE 把触发器叫起来。

    ``SET mastery = mastery`` 看着像空操作，但 PG 确实会执行 UPDATE
    并跑 BEFORE UPDATE 触发器，后者把 NEW.mastery 改写成派生值。

    Args:
        kp_ids: 指定知识点 ID；传 None 表示全量重算（慎用）。
    """
    from sqlalchemy import text as _text

    if kp_ids:
        ids = [int(i) for i in kp_ids]
        if not ids:
            return 0
        res = session.execute(
            _text("UPDATE knowledge_points SET mastery = mastery WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
    else:
        res = session.execute(_text("UPDATE knowledge_points SET mastery = mastery"))
    return res.rowcount or 0


def learned_kp_ids(session, user_id=None) -> set:
    """有学习记录的知识点 ID 集合（SQLAlchemy Session）。

    ``user_id`` 传入时按该用户的学习流水判定（B4 隔离）；
    不传（默认 None）保持旧的全库口径，兼容尚未接线的调用方。
    """
    from sqlalchemy import text

    if user_id is None:
        return {row[0] for row in session.execute(text(LEARNED_KP_SQL))}
    return {row[0] for row in session.execute(text(LEARNED_KP_SQL_USER), {"uid": int(user_id)})}


def user_mastery(session, user_id: int) -> dict[int, int]:
    """按用户聚合 30 天衰减加权正确率，未产生已判定流水的知识点不返回。"""
    from sqlalchemy import text
    from utils.timeutil import utcnow

    if session.bind.dialect.name == "sqlite":
        age_seconds = "(julianday(:now) - julianday(at)) * 86400.0"
    else:
        age_seconds = "EXTRACT(EPOCH FROM (:now - at))"
    sql = f"""
    WITH answered AS (
        SELECT qkl.knowledge_point_id AS kp_id,
               ar.created_at AS at,
               CASE WHEN ar.is_correct THEN 1 ELSE 0 END AS ok,
               qkl.weight AS kweight
          FROM answer_records ar
          JOIN question_knowledge_links qkl ON qkl.question_id = ar.question_id
         WHERE ar.user_id = :uid AND ar.is_correct IS NOT NULL
           AND ar.question_id IS NOT NULL
    ), reviewed AS (
        SELECT rr.item_id AS kp_id,
               rr.created_at AS at,
               CASE WHEN rr.result IN ('good','easy') THEN 1 ELSE 0 END AS ok,
               1.0 AS kweight
          FROM review_records rr
         WHERE rr.user_id = :uid
           AND rr.item_type IN ('knowledge', 'knowledge_point')
           AND rr.result IS NOT NULL
    ), merged AS (
        SELECT kp_id, ok, kweight,
               exp(-{age_seconds} / (30.0 * 86400.0)) AS decay
          FROM answered
        UNION ALL
        SELECT kp_id, ok, kweight,
               exp(-{age_seconds} / (30.0 * 86400.0)) AS decay
          FROM reviewed
    ), agg AS (
        SELECT kp_id,
               COALESCE(SUM(ok * decay * kweight), 0) AS weighted_correct,
               COALESCE(SUM(decay * kweight), 0) AS weighted_total
          FROM merged
         GROUP BY kp_id
    )
    SELECT kp_id,
           CASE WHEN weighted_total = 0 THEN 0
                ELSE ROUND(100.0 * weighted_correct / weighted_total)
           END AS mastery
      FROM agg
    """
    return {int(row[0]): int(row[1]) for row in session.execute(text(sql), {"uid": int(user_id), "now": utcnow()})}


def learned_kp_ids_raw(conn: sqlite3.Connection) -> set:
    """有学习记录的知识点 ID 集合（裸 sqlite3 连接）。"""
    return {row[0] for row in conn.execute(LEARNED_KP_SQL)}


def tally(rows: Iterable, learned_ids: set, mastery_by_id: dict[int, int] | None = None) -> dict:
    """对一批 KnowledgePoint 对象做四态计数。

    返回 {"total", "unlearned", "learning", "weak", "mastered", "mastery_sum",
          "learned_mastery_sum"}，其中 mastery_sum/learned_mastery_sum
          供调用方算均值（未学不计入已学均值）。``mastery_by_id`` 传入时使用
          个人掌握度，不读取全库派生值。
    """
    out = {
        "total": 0,
        "unlearned": 0,
        "learning": 0,
        "weak": 0,
        "mastered": 0,
        "mastery_sum": 0,
        "learned_mastery_sum": 0,
    }
    for kp in rows:
        mastery = int(mastery_by_id.get(kp.id, 0) if mastery_by_id is not None else (kp.mastery or 0))
        state = classify_state(mastery, kp.id in learned_ids)
        out["total"] += 1
        out["mastery_sum"] += mastery
        out[state] += 1
        if state != STATE_UNLEARNED:
            out["learned_mastery_sum"] += mastery
    return out
