"""院校数据自动采集接口。

整合现有爬虫服务:
- spider_yz: 研招网院校/专业采集
- spider_school: 院校官网分数线抓取
- collector: 工科定向采集编排
- import_csv: CSV批量导入
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from core.db_session import get_db
from services.kaoyan import collector, spider_yz, spider_school
from services.scheduler import scheduler
from utils.security import require_admin

router = APIRouter(prefix="/api/admin/schools/crawler", tags=["admin-schools-crawler"], dependencies=[Depends(require_admin)])


# --- Pydantic Schemas ---

class CrawlConfig(BaseModel):
    """爬取配置"""
    province_codes: Optional[list] = Field(None, description="省份代码列表，如['11','12']")
    subject_codes: Optional[list] = Field(["07", "08"], description="学科门类代码，默认理学+工学")
    max_pages: int = Field(50, ge=1, le=200, description="每省最大页数")
    dry_run: bool = Field(False, description="仅预览不入库")


class SchoolCrawlConfig(BaseModel):
    """单校爬取配置"""
    school_name: str = Field(..., min_length=1, description="院校名称")
    crawl_scorelines: bool = Field(True, description="是否抓取分数线")
    crawl_admissions: bool = Field(True, description="是否抓取录取名单")


class ImportCSVConfig(BaseModel):
    """CSV导入配置"""
    file_path: str = Field(..., description="CSV文件路径")
    target_table: str = Field(..., description="目标表：schools/majors/scorelines/admissions")
    encoding: str = Field("utf-8", description="文件编码")
    skip_errors: bool = Field(True, description="跳过错误行继续导入")


# --- Crawler Status ---

@router.get("/status")
async def crawler_status(db: Session = Depends(get_db)):
    """查看爬虫运行状态"""
    from models import KaoyanCollectionRun
    
    # 最近10次运行记录
    runs = (
        db.query(KaoyanCollectionRun)
        .order_by(KaoyanCollectionRun.created_at.desc())
        .limit(10)
        .all()
    )
    
    return {
        "scheduler_running": scheduler.running if scheduler else False,
        "recent_runs": [
            {
                "id": r.id,
                "source": r.source,
                "scope": r.scope,
                "item_type": r.item_type,
                "row_count": r.row_count,
                "status": r.status,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ]
    }


# --- Manual Trigger ---

@router.post("/yz-crawl")
async def trigger_yz_crawl(
    config: CrawlConfig,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """手动触发研招网爬取（后台任务）"""
    
    def run_crawl():
        try:
            result = collector.collect_engineering(
                db_session=db,
                provinces=config.province_codes,
                dry_run=config.dry_run,
            )
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    if config.dry_run:
        # 同步执行返回预览
        result = run_crawl()
        return result
    else:
        # 异步后台任务
        background_tasks.add_task(run_crawl)
        return {"message": "爬取任务已加入后台队列", "config": config.model_dump()}


@router.post("/school-crawl")
async def trigger_school_crawl(
    config: SchoolCrawlConfig,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """手动触发单校数据采集"""
    
    def run_school_crawl():
        try:
            # 调用spider_school模块
            result = spider_school.crawl_school(config.school_name)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    background_tasks.add_task(run_school_crawl)
    return {"message": f"已开始爬取 {config.school_name}", "school_name": config.school_name}


@router.post("/import-csv")
async def import_csv_data(
    config: ImportCSVConfig,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """CSV批量导入"""
    
    def run_import():
        try:
            from services.kaoyan.import_csv import import_from_csv
            
            result = import_from_csv(
                db_session=db,
                csv_path=config.file_path,
                target_table=config.target_table,
                encoding=config.encoding,
                skip_errors=config.skip_errors,
            )
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    background_tasks.add_task(run_import)
    return {"message": "CSV导入任务已加入后台队列", "config": config.model_dump()}


# --- Scheduled Tasks ---

@router.post("/schedule/toggle")
async def toggle_scheduled_task(
    task_name: str = Query(..., description="任务名：engineering/national_line/notices"),
    enable: bool = Query(..., description="启用/禁用"),
):
    """启用/禁用定时采集任务"""
    
    task_map = {
        "engineering": "collect_engineering_daily",
        "national_line": "backfill_national_lines_weekly",
        "notices": "collect_notices_hourly",
    }
    
    if task_name not in task_map:
        raise HTTPException(status_code=400, detail=f"未知任务: {task_name}")
    
    job_id = task_map[task_name]
    
    if enable:
        # 重新添加调度任务
        from services.scheduler import add_scheduled_jobs
        add_scheduled_jobs(scheduler)
        return {"message": f"任务 {task_name} 已启用"}
    else:
        # 移除调度任务
        if scheduler and scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            return {"message": f"任务 {task_name} 已禁用"}
        return {"message": f"任务 {task_name} 不存在或已禁用"}


@router.get("/schedule/list")
async def list_scheduled_tasks():
    """列出所有定时采集任务"""
    
    if not scheduler:
        return {"tasks": [], "scheduler_running": False}
    
    jobs = scheduler.get_jobs()
    
    return {
        "scheduler_running": scheduler.running,
        "tasks": [
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
            for job in jobs
        ]
    }


# --- Data Quality ---

@router.get("/coverage")
async def data_coverage_stats(db: Session = Depends(get_db)):
    """查看数据采集覆盖率统计"""
    # models 里的类名是 KaoyanScoreLine（大写 L）；KaoyanScoreline 只存在于
    # core.models 新口径里，从 models 导入会 ImportError → 本接口恒 500。
    from models import KaoyanSchool, KaoyanMajor, KaoyanAdmission
    from models import KaoyanScoreLine as KaoyanScoreline
    
    total_schools = db.query(KaoyanSchool).count()
    schools_with_majors = (
        db.query(KaoyanSchool)
        .join(KaoyanMajor, KaoyanMajor.school_id == KaoyanSchool.id)
        .distinct()
        .count()
    )
    schools_with_scorelines = (
        db.query(KaoyanSchool)
        .join(KaoyanScoreline, KaoyanScoreline.school_id == KaoyanSchool.id)
        .distinct()
        .count()
    )
    schools_with_admissions = (
        db.query(KaoyanSchool)
        .join(KaoyanAdmission, KaoyanAdmission.school_id == KaoyanSchool.id)
        .distinct()
        .count()
    )
    
    return {
        "total_schools": total_schools,
        "schools_with_majors": schools_with_majors,
        "majors_coverage_rate": round(schools_with_majors / total_schools * 100, 2) if total_schools > 0 else 0,
        "schools_with_scorelines": schools_with_scorelines,
        "scorelines_coverage_rate": round(schools_with_scorelines / total_schools * 100, 2) if total_schools > 0 else 0,
        "schools_with_admissions": schools_with_admissions,
        "admissions_coverage_rate": round(schools_with_admissions / total_schools * 100, 2) if total_schools > 0 else 0,
    }
