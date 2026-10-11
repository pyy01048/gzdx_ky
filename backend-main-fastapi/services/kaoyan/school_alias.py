# -*- coding: utf-8 -*-
"""院校名称别名归一化服务（动态数据源 D4）。

提供：
- normalize_alias(db, name_or_alias) -> dict | None：将简称/别名解析为标准院校
- match_aliases(db, keyword) -> List[KaoyanSchool]：按别名/标准名/模糊名查询院校
"""
from sqlalchemy.orm import Session
from models import KaoyanSchool, SchoolAlias


def normalize_alias(db: Session, name_or_alias: str):
    """别名归一化：输入简称（如"清华"/"贵大"）返回标准院校。

    返回 None 表示未命中别名（不一定是错误，可能是标准全名）。
    """
    if not name_or_alias:
        return None
    name_or_alias = name_or_alias.strip()
    # 1) 别名表精确命中
    row = db.query(SchoolAlias).filter(SchoolAlias.alias == name_or_alias).first()
    if row:
        school = db.query(KaoyanSchool).filter(KaoyanSchool.id == row.school_id).first()
        if school:
            return {
                "matched": True,
                "alias": row.alias,
                "alias_type": row.alias_type,
                "school": school,
            }
    # 2) 标准全名命中
    school = db.query(KaoyanSchool).filter(KaoyanSchool.name == name_or_alias).first()
    if school:
        return {"matched": False, "alias": None, "alias_type": None, "school": school}
    return None


def match_aliases(db: Session, keyword: str, limit: int = 20):
    """按关键词匹配院校（标准名模糊 + 别名精确/前缀），用于列表搜索命中简称。"""
    if not keyword:
        return []
    keyword = keyword.strip()
    # 别名命中（精确或前缀，防止"清华"被 LIKE %清华% 扫出噪声）
    alias_rows = db.query(SchoolAlias).filter(
        (SchoolAlias.alias == keyword) | (SchoolAlias.alias.like(f"{keyword}%"))
    ).limit(limit).all()
    schools = []
    seen_ids = set()
    for ar in alias_rows:
        if ar.school_id in seen_ids:
            continue
        s = db.query(KaoyanSchool).filter(KaoyanSchool.id == ar.school_id).first()
        if s:
            seen_ids.add(s.id)
            schools.append(s)
    return schools[:limit]
