# -*- coding: utf-8 -*-
"""闪卡批量生成：从 knowledge_points 自动生成正反面闪卡。

正面 = 知识点名；背面 = 知识点定义（description，常含【考纲要求】标注），
无定义时退化为「科目｜章节」并附考频信息，保证每张卡背面有可复习内容。
默认跳过已有关联（knowledge_point_id 已存在）的卡片，避免重复生成。
"""
from types import SimpleNamespace
from typing import Optional

from sqlalchemy.orm import Session

from models import Flashcard, KnowledgePoint
from utils.scope import scoped


def _scoped_uid(model, user_id: Optional[int]):
    """B4：user_id 形式的行级过滤（复用 scoped()，开关 off / user_id 空 → 恒真）。"""
    return scoped(model, SimpleNamespace(id=user_id))


def _compose_back(kp: KnowledgePoint) -> str:
    desc = (kp.description or "").strip()
    if desc:
        return desc
    # 无定义时退化：科目｜章节 + 考频，仍构成可复习的背面
    parts = [p for p in (kp.subject or "", kp.chapter or "") if p]
    back = "｜".join(parts) if parts else kp.name
    if kp.exam_frequency is not None:
        back += f"\n\n【考频】{kp.exam_frequency}"
    return back


def generate_from_knowledge_points(
    db: Session,
    subject: Optional[str] = None,
    limit: Optional[int] = None,
    overwrite: bool = False,
    *,
    user_id: Optional[int] = None,
) -> dict:
    """批量生成闪卡。

    Args:
        db: SQLAlchemy Session
        subject: 仅生成指定科目（None = 全部科目）
        limit: 最多生成张数（None = 不限）
        overwrite: True 时对已有关联的 knowledge_point_id 重建卡片
        user_id: 归属用户（B4 行级隔离）；生成/查重/计数均按该用户，None = 旧行为

    Returns:
        {"generated": 新增数, "skipped_existing": 跳过数, "total": 生成后总数}
    """
    q = db.query(KnowledgePoint).order_by(KnowledgePoint.id)
    if subject:
        q = q.filter(KnowledgePoint.subject == subject)

    existing = {
        kp_id
        for (kp_id,) in db.query(Flashcard.knowledge_point_id)
        .filter(
            Flashcard.knowledge_point_id.isnot(None),
            _scoped_uid(Flashcard, user_id),
        )
        .all()
    }

    generated = 0
    skipped = 0
    for kp in q.all():
        if limit is not None and generated >= limit:
            break
        if kp.id in existing and not overwrite:
            skipped += 1
            continue
        if kp.id in existing and overwrite:
            db.query(Flashcard).filter(
                Flashcard.knowledge_point_id == kp.id,
                _scoped_uid(Flashcard, user_id),
            ).delete()
        db.add(
            Flashcard(
                front=kp.name,
                back=_compose_back(kp),
                knowledge_point_id=kp.id,
                user_id=user_id,
            )
        )
        generated += 1
        existing.add(kp.id)
        # 小批量提交，避免超长事务
        if generated % 100 == 0:
            db.commit()

    db.commit()
    total = db.query(Flashcard).filter(_scoped_uid(Flashcard, user_id)).count()
    return {"generated": generated, "skipped_existing": skipped, "total": total}
