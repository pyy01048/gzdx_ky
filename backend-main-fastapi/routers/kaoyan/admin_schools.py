"""院校后台管理接口。

提供院校/学院/专业的CRUD、软删除、启用/禁用功能。
所有写操作自动记录审计日志。
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from core.db_session import get_db
from core.models.schools import KaoyanSchool, KaoyanCollege, KaoyanMajor, AuditLog
from utils.security import require_admin

router = APIRouter(prefix="/api/admin/schools", tags=["admin-schools"], dependencies=[Depends(require_admin)])


# --- Pydantic Schemas ---

class SchoolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    level: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    logo_url: Optional[str] = None
    intro: Optional[str] = None
    tags: list = []
    official_url: Optional[str] = None
    type: Optional[str] = None
    region: Optional[str] = None


class SchoolUpdate(BaseModel):
    name: Optional[str] = None
    level: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    logo_url: Optional[str] = None
    intro: Optional[str] = None
    tags: Optional[list] = None
    official_url: Optional[str] = None
    type: Optional[str] = None
    region: Optional[str] = None
    enabled: Optional[bool] = None


class CollegeCreate(BaseModel):
    school_id: int
    name: str = Field(..., min_length=1, max_length=200)


class CollegeUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None


class MajorCreate(BaseModel):
    school_id: int
    college_id: Optional[int] = None
    code: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=200)
    research_direction: Optional[str] = None
    subject_code: Optional[str] = None
    exam_subjects: list = []
    reference_books: list = []
    degree_type: str = "unknown"


class MajorUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    college_id: Optional[int] = None
    research_direction: Optional[str] = None
    subject_code: Optional[str] = None
    exam_subjects: Optional[list] = None
    reference_books: Optional[list] = None
    degree_type: Optional[str] = None
    enabled: Optional[bool] = None


# --- Helper Functions ---

def _get_client_ip(request: Request) -> str:
    """获取客户端IP地址"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _soft_delete_filter(query, model):
    """添加软删除过滤：只查询未删除的记录"""
    return query.filter(model.deleted_at.is_(None))


# --- School CRUD ---

@router.get("")
async def list_schools(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    province: Optional[str] = None,
    level: Optional[str] = None,
    include_disabled: bool = False,
):
    """列出院校（支持筛选、分页）"""
    q = db.query(KaoyanSchool)
    
    if not include_disabled:
        q = q.filter(KaoyanSchool.enabled == True)
    
    q = _soft_delete_filter(q, KaoyanSchool)
    
    if keyword:
        q = q.filter(KaoyanSchool.name.ilike(f"%{keyword}%"))
    if province:
        q = q.filter(KaoyanSchool.province == province)
    if level:
        q = q.filter(KaoyanSchool.level == level)
    
    total = q.count()
    items = q.order_by(KaoyanSchool.name).offset((page - 1) * limit).limit(limit).all()
    
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": s.id,
                "name": s.name,
                "level": s.level,
                "province": s.province,
                "city": s.city,
                "type": s.type,
                "region": s.region,
                "enabled": s.enabled,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in items
        ]
    }


@router.post("")
async def create_school(
    payload: SchoolCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """创建院校"""
    # 检查名称唯一性
    existing = db.query(KaoyanSchool).filter(KaoyanSchool.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="院校名称已存在")
    
    school = KaoyanSchool(**payload.model_dump())
    db.add(school)
    db.commit()
    db.refresh(school)
    
    return {"id": school.id, "name": school.name, "message": "院校创建成功"}


# `:int` 路径转换器：只匹配纯数字段。否则本路由先于 GET /majors、/audit-logs 注册，
# 会把这两个列表接口吞掉并报 422「school_id 不是整数」，管理端永远拿不到数据。
@router.get("/{school_id:int}")
async def get_school(school_id: int, db: Session = Depends(get_db)):
    """获取院校详情"""
    school = db.query(KaoyanSchool).filter(KaoyanSchool.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="院校不存在")
    
    return {
        "id": school.id,
        "name": school.name,
        "level": school.level,
        "province": school.province,
        "city": school.city,
        "logo_url": school.logo_url,
        "intro": school.intro,
        "tags": school.tags,
        "official_url": school.official_url,
        "type": school.type,
        "region": school.region,
        "enabled": school.enabled,
        "deleted_at": school.deleted_at.isoformat() if school.deleted_at else None,
        "created_at": school.created_at.isoformat() if school.created_at else None,
        "updated_at": school.updated_at.isoformat() if school.updated_at else None,
    }


@router.put("/{school_id}")
async def update_school(
    school_id: int,
    payload: SchoolUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """更新院校信息"""
    school = db.query(KaoyanSchool).filter(KaoyanSchool.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="院校不存在")
    
    # 更新字段
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(school, key, value)
    
    db.commit()
    db.refresh(school)
    
    return {"id": school.id, "message": "院校更新成功"}


@router.delete("/{school_id}")
async def delete_school(
    school_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """软删除院校"""
    school = db.query(KaoyanSchool).filter(KaoyanSchool.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="院校不存在")
    
    from datetime import datetime, timezone
    school.deleted_at = datetime.now(timezone.utc)
    school.enabled = False
    db.commit()
    
    return {"id": school.id, "message": "院校已删除"}


@router.patch("/{school_id}/toggle-enabled")
async def toggle_school_enabled(
    school_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """切换院校启用状态"""
    school = db.query(KaoyanSchool).filter(KaoyanSchool.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="院校不存在")
    
    school.enabled = not school.enabled
    db.commit()
    
    return {"id": school.id, "enabled": school.enabled, "message": "状态已更新"}


# --- College CRUD ---

@router.get("/{school_id}/colleges")
async def list_colleges(
    school_id: int,
    db: Session = Depends(get_db),
    include_disabled: bool = False,
):
    """列出院校下属学院"""
    q = db.query(KaoyanCollege).filter(KaoyanCollege.school_id == school_id)
    
    if not include_disabled:
        q = q.filter(KaoyanCollege.enabled == True)
    
    q = _soft_delete_filter(q, KaoyanCollege)
    
    colleges = q.order_by(KaoyanCollege.name).all()
    
    return {
        "total": len(colleges),
        "items": [
            {
                "id": c.id,
                "name": c.name,
                "enabled": c.enabled,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in colleges
        ]
    }


@router.post("/colleges")
async def create_college(
    payload: CollegeCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """创建学院"""
    # 验证院校存在
    school = db.query(KaoyanSchool).filter(KaoyanSchool.id == payload.school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="院校不存在")
    
    college = KaoyanCollege(**payload.model_dump())
    db.add(college)
    db.commit()
    db.refresh(college)
    
    return {"id": college.id, "name": college.name, "message": "学院创建成功"}


@router.put("/colleges/{college_id}")
async def update_college(
    college_id: int,
    payload: CollegeUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """更新学院信息"""
    college = db.query(KaoyanCollege).filter(KaoyanCollege.id == college_id).first()
    if not college:
        raise HTTPException(status_code=404, detail="学院不存在")
    
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(college, key, value)
    
    db.commit()
    db.refresh(college)
    
    return {"id": college.id, "message": "学院更新成功"}


@router.delete("/colleges/{college_id}")
async def delete_college(
    college_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """软删除学院"""
    college = db.query(KaoyanCollege).filter(KaoyanCollege.id == college_id).first()
    if not college:
        raise HTTPException(status_code=404, detail="学院不存在")
    
    from datetime import datetime, timezone
    college.deleted_at = datetime.now(timezone.utc)
    college.enabled = False
    db.commit()
    
    return {"id": college.id, "message": "学院已删除"}


# --- Major CRUD ---

@router.get("/majors")
async def list_majors(
    db: Session = Depends(get_db),
    school_id: Optional[int] = None,
    college_id: Optional[int] = None,
    include_disabled: bool = False,
):
    """列出专业（支持按院校/学院筛选）"""
    q = db.query(KaoyanMajor)
    
    if school_id:
        q = q.filter(KaoyanMajor.school_id == school_id)
    if college_id:
        q = q.filter(KaoyanMajor.college_id == college_id)
    
    if not include_disabled:
        q = q.filter(KaoyanMajor.enabled == True)
    
    q = _soft_delete_filter(q, KaoyanMajor)
    
    majors = q.order_by(KaoyanMajor.code).all()
    
    return {
        "total": len(majors),
        "items": [
            {
                "id": m.id,
                "code": m.code,
                "name": m.name,
                "school_id": m.school_id,
                "college_id": m.college_id,
                "degree_type": m.degree_type,
                "enabled": m.enabled,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in majors
        ]
    }


@router.post("/majors")
async def create_major(
    payload: MajorCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """创建专业"""
    # 验证院校存在
    school = db.query(KaoyanSchool).filter(KaoyanSchool.id == payload.school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="院校不存在")
    
    major = KaoyanMajor(**payload.model_dump())
    db.add(major)
    db.commit()
    db.refresh(major)
    
    return {"id": major.id, "name": major.name, "message": "专业创建成功"}


@router.put("/majors/{major_id}")
async def update_major(
    major_id: int,
    payload: MajorUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """更新专业信息"""
    major = db.query(KaoyanMajor).filter(KaoyanMajor.id == major_id).first()
    if not major:
        raise HTTPException(status_code=404, detail="专业不存在")
    
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(major, key, value)
    
    db.commit()
    db.refresh(major)
    
    return {"id": major.id, "message": "专业更新成功"}


@router.delete("/majors/{major_id}")
async def delete_major(
    major_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """软删除专业"""
    major = db.query(KaoyanMajor).filter(KaoyanMajor.id == major_id).first()
    if not major:
        raise HTTPException(status_code=404, detail="专业不存在")
    
    from datetime import datetime, timezone
    major.deleted_at = datetime.now(timezone.utc)
    major.enabled = False
    db.commit()
    
    return {"id": major.id, "message": "专业已删除"}


# --- Audit Logs ---

@router.get("/audit-logs")
async def list_audit_logs(
    db: Session = Depends(get_db),
    table_name: Optional[str] = None,
    record_id: Optional[int] = None,
    action: Optional[str] = None,
    operator_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """查询审计日志（只读，不可修改删除）"""
    q = db.query(AuditLog)
    
    if table_name:
        q = q.filter(AuditLog.table_name == table_name)
    if record_id:
        q = q.filter(AuditLog.record_id == record_id)
    if action:
        q = q.filter(AuditLog.action == action)
    if operator_id:
        q = q.filter(AuditLog.operator_id == operator_id)
    
    total = q.count()
    logs = q.order_by(AuditLog.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": log.id,
                "table_name": log.table_name,
                "record_id": log.record_id,
                "action": log.action,
                "operator_id": log.operator_id,
                "operator_ip": str(log.operator_ip) if log.operator_ip is not None else None,
                "before_data": log.before_data,
                "after_data": log.after_data,
                "change_summary": log.change_summary,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ]
    }
