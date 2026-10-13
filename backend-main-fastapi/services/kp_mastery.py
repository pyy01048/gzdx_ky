# -*- coding: utf-8 -*-
"""知识点掌握度**三态模型**（未学 / 薄弱 / 已掌握）。

背景（2026-10 修复"1067 个知识点全标薄弱、已掌握为 0"）
----------------------------------------------------
旧口径只有"已掌握（mastery≥70）/ 其余全算薄弱（mastery<40）"两档，
未学习的知识点 mastery=0 被误算进薄弱 —— 知识库 1067 个知识点里
1065 个没有任何学习记录，于是薄弱数永远≈总数，"薄弱"指标失去意义。

三态口径：
  - 未学 unlearned（灰）：无任何学习记录 —— 从未复习、无关联答题/错题
  - 薄弱 weak（黄）：有学习记录但掌握度 < MASTERED_THRESHOLD
    （正确率低 / 复习到期未过）
  - 已掌握 mastered（绿）：有学习记录且掌握度 ≥ MASTERED_THRESHOLD

未学知识点不计入薄弱统计 —— 它们不是"薄弱"，是"还没开始"。

本模块是三态口径的唯一事实源：review_service / taxonomy / learner_profile /
learning_analytics 都从这里取阈值与判定，禁止在别处再写一套。
"""
from __future__ import annotations

import sqlite3
from typing import Iterable, Union

# 已掌握阈值（与历史口径一致：mastery ≥ 70）
MASTERED_THRESHOLD = 70

STATE_UNLEARNED = "unlearned"
STATE_WEAK = "weak"
STATE_MASTERED = "mastered"

# 三态 → 中文标签（前端色阶：未学=灰 / 薄弱=黄 / 已掌握=绿）
STATE_LABELS = {
    STATE_UNLEARNED: "未学",
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
SELECT item_id FROM review_records WHERE item_type = 'knowledge'
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


def classify_state(mastery: Union[int, None], has_records: bool) -> str:
    """按（掌握度, 有无学习记录）判三态。

    >>> classify_state(None, False)
    'unlearned'
    >>> classify_state(0, True)
    'weak'
    >>> classify_state(69, True)
    'weak'
    >>> classify_state(70, True)
    'mastered'
    """
    if not has_records:
        return STATE_UNLEARNED
    return STATE_MASTERED if int(mastery or 0) >= MASTERED_THRESHOLD else STATE_WEAK


#: 错题"已毕业"状态标记（error_records.status 的终态值），与
#: services/review_scheduler / routers/errors.py 的用法保持一致。
STATE_MASTERED_MARK = "graduated"


def error_mastery_state(
    accuracy: Union[float, None],
    review_count: Union[int, None],
    status: Union[str, None],
) -> str:
    """**错题记录**的掌握度三态（复用同一三态口径，不另立档位）。

    背景：错题本的"掌握度"此前是写死的两档（active=未掌握 / graduated=已掌握），
    没有"未学"这一档 —— 新收录、一次都没复习过的错题被打成"未掌握"，
    与知识点的三态口径（未学=灰 / 薄弱=黄 / 已掌握=绿）割裂。

    与 :func:`classify_state` 共用同一阈值（``MASTERED_THRESHOLD``）与标签，
    只把错题的字段折算成三态模型需要的两个入参：

    - ``accuracy``（0-1 正确率，``error_records.accuracy``）→ 折成 0-100 分；
    - "有学习记录"= 复习过（``review_count>0``）或已毕业（``status=='graduated'``）：
      前者是真实复习留痕；后者是"已掌握"的终态标记，直接归 mastered。

    于是：从未复习的新错题 → 未学（灰）；复习过但正确率 < 70 → 薄弱（黄）；
    已毕业 / 正确率 ≥ 70 → 已掌握（绿）。

    >>> error_mastery_state(0.0, 0, "active")
    'unlearned'
    >>> error_mastery_state(0.0, 1, "active")
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


def learned_kp_ids(session) -> set:
    """有学习记录的知识点 ID 集合（SQLAlchemy Session）。"""
    from sqlalchemy import text

    return {row[0] for row in session.execute(text(LEARNED_KP_SQL))}


def learned_kp_ids_raw(conn: sqlite3.Connection) -> set:
    """有学习记录的知识点 ID 集合（裸 sqlite3 连接）。"""
    return {row[0] for row in conn.execute(LEARNED_KP_SQL)}


def tally(rows: Iterable, learned_ids: set) -> dict:
    """对一批 KnowledgePoint 对象做三态计数。

    返回 {"total", "unlearned", "weak", "mastered", "mastery_sum",
          "learned_mastery_sum"}，其中 mastery_sum/learned_mastery_sum
          供调用方算均值（未学不计入已学均值）。
    """
    out = {
        "total": 0,
        "unlearned": 0,
        "weak": 0,
        "mastered": 0,
        "mastery_sum": 0,
        "learned_mastery_sum": 0,
    }
    for kp in rows:
        mastery = int(kp.mastery or 0)
        state = classify_state(mastery, kp.id in learned_ids)
        out["total"] += 1
        out["mastery_sum"] += mastery
        out[state] += 1
        if state != STATE_UNLEARNED:
            out["learned_mastery_sum"] += mastery
    return out
