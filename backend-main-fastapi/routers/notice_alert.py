"""通知主动发现 / 订阅 / 提醒 API。

职责边界（与 notice-read-track 同事的已读标记严格分离）：
- 本模块：重要性分级、关键日期抽取、订阅、**待处理提醒**
- 同事模块：``is_read`` / ``read_at`` 等已读字段与标记

本模块所有写操作都 **不触碰** 已读字段；查询提醒时若发现库里已有 ``is_read``
列会做「已读则降级为不阻塞」的软过滤（只读，不写）。
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import SessionLocal
from services.kaoyan.notice_alert import (
    LEVEL_IMPORTANT,
    LEVEL_NORMAL,
    LEVEL_ORDER,
    LEVEL_URGENT,
    LEVEL_LABEL_CN,
    backfill_all,
    classify_and_store,
    classify_importance,
    cn_now,
    cn_today,
    ensure_alert_schema,
    extract_dates,
    load_rules,
    notice_matches_subscription,
    parse_date_loose,
    raw_conn,
    runs_trigger_column,
    scalar,
    table_columns,
    rules_path,
    scan_alerts,
)

logger = logging.getLogger(__name__)
from utils.response import MAX_PAGE_SIZE
from utils.timeutil import naive_utc_iso

router = APIRouter(prefix="/api/notice-alert", tags=["通知提醒"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Pydantic 模型
# --------------------------------------------------------------------------- #
class SubscriptionCreate(BaseModel):
    """新增订阅请求体。``scope`` 决定其余字段的语义。"""
    scope: str = Field(..., description="关注类型：school | major | notice_type | keyword")
    school_id: Optional[int] = Field(None, description="scope=school 时必填：院校 ID")
    school_name: Optional[str] = Field(None, description="scope=school 时可用院校名替代 ID")
    major_name: Optional[str] = Field(None, description="scope=major：专业/学院关键词，如「计算机」")
    notice_type: Optional[str] = Field(None, description="scope=notice_type：简章/复试/调剂/录取/目录/大纲/公告")
    keyword: Optional[str] = Field(None, description="scope=keyword：标题关键词，如「复试线」")
    level_min: str = Field("normal", description="噪音过滤：只关心 >= 该等级（normal/important/urgent）")
    remark: Optional[str] = Field(None, description="备注")


class ClassifyRequest(BaseModel):
    """分级预览请求（不落库，供前端实时预览 / 手工导入时打分）。"""
    title: str = Field(..., min_length=1, description="通知标题")
    notice_type: Optional[str] = Field(None, description="通知类型")
    body: Optional[str] = Field(None, description="正文（可选，提高日期抽取召回）")
    publish_date: Optional[str] = Field(None, description="发布日期 YYYY-MM-DD，用于缺年份补全")
    save: bool = Field(False, description="为true 时按 title 反查库里已有通知并落库分级结果")


class ImportNotice(BaseModel):
    """手动导入一条通知（数据来源：用户本地解析 PDF / 手工粘贴，非爬虫）。"""
    title: str = Field(..., min_length=1)
    school_id: Optional[int] = None
    school_name: Optional[str] = None
    notice_type: str = Field("公告", description="公告/简章/复试/调剂/录取/目录/大纲…")
    publish_date: Optional[str] = Field(None, description="YYYY-MM-DD，缺省用今天")
    url: Optional[str] = None
    source: str = Field("manual", description="manual / pdf_import / csv_import…")
    body: Optional[str] = Field(None, description="正文（用于日期抽取，可选）")
    importance_level: Optional[str] = Field(
        None, description="手工指定等级；留空则自动分级（允许用户纠正误判）")


# --------------------------------------------------------------------------- #
# 0. 规则自省（前端可据此渲染「分级说明」）
# --------------------------------------------------------------------------- #
@router.get("/rules")
def get_rules(db: Session = Depends(get_db)):
    """返回当前生效的分级规则 + 规则文件路径。

    用户想加关键词时，前端可展示本接口内容并引导编辑 YAML。
    """
    ensure_alert_schema(db)
    rules = load_rules()
    return {
        "rules_path": str(rules_path()),
        "version": rules.get("version"),
        "thresholds": rules.get("thresholds"),
        "type_weight": rules.get("type_weight"),
        "keyword_rules": rules.get("keyword_rules"),
        "date_extraction": rules.get("date_extraction"),
        "alert": rules.get("alert"),
    }


# --------------------------------------------------------------------------- #
# 1. 分级 / 日期抽取
# --------------------------------------------------------------------------- #
@router.post("/classify")
def classify(req: ClassifyRequest, db: Session = Depends(get_db)):
    """分级预览（默认不落库）。``save=true`` 时把结果写回已存在的同标题通知。"""
    ensure_alert_schema(db)
    rules = load_rules()
    ref = parse_date_loose(req.publish_date)
    cls = classify_importance(req.title, req.notice_type, body=req.body, rules=rules)
    dates = extract_dates(f"{req.title}\n{req.body or ''}", ref_date=ref, rules=rules)

    saved_id = None
    if req.save:
        conn = raw_conn(db)
        row = conn.execute(
            "SELECT id FROM kaoyan_notices WHERE title = ? ORDER BY id LIMIT 1",
            (req.title.strip(),),
        ).fetchone()
        if row:
            saved_id = row[0]
            classify_and_store(db, saved_id)
        else:
            logger.info("classify save=true 但库中未找到同标题通知: %s", req.title)

    return {
        **cls,
        "dates": dates,
        "deadline_date": next((d["date"] for d in dates if d["is_deadline"]), None),
        "saved_notice_id": saved_id,
    }


@router.get("/notices/{notice_id}")
def notice_detail(notice_id: int, db: Session = Depends(get_db)):
    """单条通知的分级 + 抽取出的全部事件日期（供「为什么提醒我」解释）。"""
    ensure_alert_schema(db)
    conn = raw_conn(db)
    row = conn.execute(
        "SELECT id, school_id, school_name, title, notice_type, publish_date, url, source, "
        "       importance_level, importance_score, importance_reason, deadline_date, events_json "
        "FROM kaoyan_notices WHERE id = ?",
        (notice_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, f"通知不存在: {notice_id}")
    dates = json.loads(row[12]) if row[12] else []
    return {
        "id": row[0], "school_id": row[1], "school_name": row[2], "title": row[3],
        "notice_type": row[4], "publish_date": row[5], "url": row[6], "source": row[7],
        "importance_level": row[8] or LEVEL_NORMAL,
        "importance_level_label": LEVEL_LABEL_CN.get(row[8] or LEVEL_NORMAL, "普通"),
        "importance_score": row[9], "importance_reason": row[10],
        "deadline_date": row[11], "events": dates,
    }


@router.post("/backfill")
def backfill(
    limit: int = Query(0, ge=0, le=100000, description="0 = 全量；调试时可限 100"),
    db: Session = Depends(get_db),
):
    """全量回填所有通知的等级与关键日期（幂等，可重复执行）。"""
    return backfill_all(db, limit=limit)


# --------------------------------------------------------------------------- #
# 2. 订阅管理
# --------------------------------------------------------------------------- #
def _validate_sub(payload: SubscriptionCreate) -> None:
    scope = payload.scope.strip().lower()
    if scope not in ("school", "major", "notice_type", "keyword"):
        raise HTTPException(400, "scope 必须是 school | major | notice_type | keyword")
    if scope == "school" and not (payload.school_id or payload.school_name):
        raise HTTPException(400, "scope=school 时必须给 school_id 或 school_name")
    if scope == "major" and not (payload.major_name or "").strip():
        raise HTTPException(400, "scope=major 时必须给 major_name")
    if scope == "notice_type" and not (payload.notice_type or "").strip():
        raise HTTPException(400, "scope=notice_type 时必须给 notice_type")
    if scope == "keyword" and not (payload.keyword or "").strip():
        raise HTTPException(400, "scope=keyword 时必须给 keyword")
    if (payload.level_min or "") not in LEVEL_ORDER:
        raise HTTPException(400, "level_min 必须是 normal | important | urgent")


@router.post("/subscriptions", status_code=201)
def create_subscription(payload: SubscriptionCreate, db: Session = Depends(get_db)):
    """新增订阅。重复订阅自动幂等（返回已有记录而非报错）。"""
    ensure_alert_schema(db)
    _validate_sub(payload)
    conn = raw_conn(db)
    now_iso = naive_utc_iso()
    # 各维度统一用 '' 兜底（表上NOT NULL DEFAULT ''，UNIQUE 才会真正生效）
    sid = payload.school_id or 0
    sname = (payload.school_name or "").strip()
    major = (payload.major_name or "").strip()
    ntype = (payload.notice_type or "").strip()
    kw = (payload.keyword or "").strip()
    existing = conn.execute(
        "SELECT id FROM kaoyan_subscriptions WHERE scope=? AND school_id=? AND school_name=? "
        "AND major_name=? AND notice_type=? AND keyword=?",
        (payload.scope.strip().lower(), sid, sname, major, ntype, kw),
    ).fetchone()
    if existing:
        return {"id": existing[0], "created": False, "message": "订阅已存在"}
    cur = conn.execute(
        "INSERT INTO kaoyan_subscriptions (scope, school_id, school_name, major_name, "
        "notice_type, keyword, level_min, enabled, remark, created_at) "
        "VALUES (?,?,?,?,?,?,?,1,?,?)",
        (payload.scope.strip().lower(), sid, sname, major, ntype, kw,
         payload.level_min or "normal", payload.remark, now_iso),
    )
    db.commit()
    return {"id": cur.lastrowid, "created": True, "message": "订阅创建成功"}


@router.get("/subscriptions")
def list_subscriptions(db: Session = Depends(get_db)):
    """我的订阅列表（含每个订阅当前会命中多少条通知，便于用户自查是否设太宽）。"""
    ensure_alert_schema(db)
    conn = raw_conn(db)
    rows = conn.execute(
        "SELECT id, scope, school_id, school_name, major_name, notice_type, keyword, "
        "       level_min, enabled, remark, created_at FROM kaoyan_subscriptions "
        "ORDER BY enabled DESC, id DESC"
    ).fetchall()
    items = []
    for r in rows:
        items.append({
            "id": r[0], "scope": r[1], "school_id": r[2], "school_name": r[3],
            "major_name": r[4], "notice_type": r[5], "keyword": r[6],
            "level_min": r[7], "enabled": bool(r[8]), "remark": r[9],
            "created_at": r[10],
        })
    return {"total": len(items), "items": items}


@router.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: int, db: Session = Depends(get_db)):
    """删除订阅。"""
    ensure_alert_schema(db)
    conn = raw_conn(db)
    cur = conn.execute("DELETE FROM kaoyan_subscriptions WHERE id = ?", (sub_id,))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, f"订阅不存在: {sub_id}")
    return {"deleted": sub_id}


@router.patch("/subscriptions/{sub_id}")
def toggle_subscription(
    sub_id: int,
    enabled: bool = Query(..., description="true=启用 false=停用"),
    db: Session = Depends(get_db),
):
    """启用/停用订阅（停用保留配置，不必删掉重建）。"""
    ensure_alert_schema(db)
    conn = raw_conn(db)
    cur = conn.execute(
        "UPDATE kaoyan_subscriptions SET enabled = ? WHERE id = ?",
        (1 if enabled else 0, sub_id),
    )
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, f"订阅不存在: {sub_id}")
    return {"id": sub_id, "enabled": enabled}


@router.get("/feed")
def subscription_feed(
    days: int = Query(14, ge=1, le=180, description="回看天数"),
    min_level: str = Query("normal", description="最低等级：normal | important | urgent"),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    """我的关注最近有什么新通知。

    只读：不依赖定时任务，用户随时打开就有结果（即使定时任务没跑过）。
    无订阅时返回空并提示，让前端引导用户先建订阅。
    """
    ensure_alert_schema(db)
    if min_level not in LEVEL_ORDER:
        raise HTTPException(400, "min_level 必须是 normal | important | urgent")
    conn = raw_conn(db)
    subs = [dict(zip(
        ("id", "scope", "school_id", "school_name", "major_name", "notice_type",
         "keyword", "level_min"),
        r,
    )) for r in conn.execute(
        "SELECT id, scope, school_id, school_name, major_name, notice_type, keyword, level_min "
        "FROM kaoyan_subscriptions WHERE enabled = TRUE"
    ).fetchall()]
    if not subs:
        return {"total": 0, "days": days, "items": [],
                "hint": "尚未创建订阅，请先 POST /api/notice-alert/subscriptions"}

    since = (cn_today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT id, school_id, school_name, title, notice_type, publish_date, url, "
        "       importance_level, importance_score, deadline_date, events_json "
        "FROM kaoyan_notices WHERE publish_date >= ? "
        "ORDER BY publish_date DESC, id DESC LIMIT ?",
        (since, limit * 4),
    ).fetchall()
    floor = LEVEL_ORDER[min_level]
    items: List[Dict[str, Any]] = []
    for r in rows:
        n = {"id": r[0], "school_id": r[1], "school_name": r[2], "title": r[3],
             "notice_type": r[4], "publish_date": r[5], "url": r[6],
             "importance_level": r[7] or LEVEL_NORMAL,
             "importance_score": r[8], "deadline_date": r[9],
             "events": json.loads(r[10]) if r[10] else []}
        if LEVEL_ORDER.get(n["importance_level"], 1) < floor:
            continue
        hit = [s for s in subs if notice_matches_subscription(n, s)]
        if not hit:
            continue
        n["matched_subscriptions"] = [
            {"id": s["id"], "scope": s["scope"],
             "label": s.get("school_name") or s.get("major_name") or
                      s.get("notice_type") or s.get("keyword")}
            for s in hit
        ]
        n["importance_level_label"] = LEVEL_LABEL_CN.get(n["importance_level"], "普通")
        items.append(n)
        if len(items) >= limit:
            break
    return {"total": len(items), "days": days, "min_level": min_level, "items": items}


# --------------------------------------------------------------------------- #
# 3. 待处理提醒
# --------------------------------------------------------------------------- #
@router.get("/alerts")
def pending_alerts(
    include_acked: bool = Query(False, description="是否包含已确认过的提醒"),
    kind: Optional[str] = Query(None, description="提醒类型过滤：deadline_soon | new_urgent | subscribed_new | new_important"),
    days: int = Query(7, ge=0, le=90, description="只看最近 N 天生成的提醒，0=不限"),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    """待处理提醒（默认只返回未 ack 的），按紧急程度 + 截止天数排序。

    排序规则：``deadline_soon`` 优先（days_left 小的在前）→ 紧急 → 重要 → 其他。
    """
    ensure_alert_schema(db)
    conn = raw_conn(db)
    where = ["1=1", "EXISTS (SELECT 1 FROM kaoyan_notices n WHERE n.id = kaoyan_alert_records.notice_id)"]
    args: List[Any] = []
    if not include_acked:
        where.append("acked = FALSE")
    if kind:
        where.append("alert_kind = ?")
        args.append(kind)
    if days:
        where.append("alert_date >= ?")
        args.append((cn_today() - timedelta(days=days)).isoformat())
    args.append(limit)

    rows = conn.execute(
        "SELECT id, notice_id, alert_kind, alert_date, title, school_name, notice_type, "
        "       importance_level, deadline_date, days_left, message, acked, acked_at "
        f"FROM kaoyan_alert_records WHERE {' AND '.join(where)} "
        "ORDER BY (CASE alert_kind WHEN 'deadline_soon' THEN 0 ELSE 1 END), "
        "         IFNULL(days_left, 9999), id DESC LIMIT ?",
        args,
    ).fetchall()
    items = []
    for r in rows:
        items.append({
            "id": r[0], "notice_id": r[1], "alert_kind": r[2], "alert_date": r[3],
            "title": r[4], "school_name": r[5], "notice_type": r[6],
            "importance_level": r[7],
            "importance_level_label": LEVEL_LABEL_CN.get(r[7] or LEVEL_NORMAL, "普通"),
            "deadline_date": r[8], "days_left": r[9], "message": r[10],
            "acked": bool(r[11]), "acked_at": r[12],
        })
    return {"total": len(items), "unacked": sum(1 for i in items if not i["acked"]), "items": items}


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, db: Session = Depends(get_db)):
    """标记「这条提醒我知道了」，之后不再出现在待处理列表。"""
    ensure_alert_schema(db)
    conn = raw_conn(db)
    row = conn.execute("SELECT acked FROM kaoyan_alert_records WHERE id = ?", (alert_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"提醒不存在: {alert_id}")
    if row[0]:
        return {"id": alert_id, "acked": True, "message": "已是已确认状态"}
    conn.execute(
        "UPDATE kaoyan_alert_records SET acked = TRUE, acked_at = ? WHERE id = ?",
        (naive_utc_iso(), alert_id),
    )
    db.commit()
    return {"id": alert_id, "acked": True, "message": "已确认"}


@router.post("/alerts/ack-all")
def ack_all_alerts(db: Session = Depends(get_db)):
    """一键全部确认（今日提醒清零）。"""
    ensure_alert_schema(db)
    conn = raw_conn(db)
    cur = conn.execute(
        "UPDATE kaoyan_alert_records SET acked = TRUE, acked_at = ? WHERE acked = FALSE",
        (naive_utc_iso(),),
    )
    db.commit()
    return {"acked_count": cur.rowcount}


@router.get("/alerts/stats")
def alert_stats(db: Session = Depends(get_db)):
    """提醒概览：未确认数、临期数、各等级分布。"""
    ensure_alert_schema(db)
    conn = raw_conn(db)
    unacked = scalar(conn, "SELECT COUNT(*) FROM kaoyan_alert_records WHERE acked = FALSE")
    soon = scalar(conn, "SELECT COUNT(*) FROM kaoyan_alert_records WHERE acked = FALSE "
                        "AND alert_kind = 'deadline_soon'")
    overdue = scalar(conn, "SELECT COUNT(*) FROM kaoyan_alert_records WHERE acked = FALSE "
                           "AND alert_kind = 'deadline_soon' AND IFNULL(days_left, 0) < 0")
    by_level = dict(conn.execute(
        "SELECT IFNULL(importance_level, 'normal'), COUNT(*) FROM kaoyan_alert_records "
        "WHERE acked = FALSE GROUP BY 1").fetchall())
    last_run = conn.execute(
        f"SELECT ran_at, {runs_trigger_column(conn)}, scanned, created_alerts, "
        "elapsed_ms FROM kaoyan_alert_runs "
        "ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "unacked": unacked,
        "deadline_soon": soon,
        "overdue": overdue,
        "by_level": by_level,
        "last_run": None if not last_run else {
            "ran_at": last_run[0], "trigger": last_run[1], "scanned": last_run[2],
            "created_alerts": last_run[3], "elapsed_ms": last_run[4],
        },
        "timezone": "Asia/Shanghai (UTC+8, 固定偏移，不依赖 tzdata)",
        "server_time": cn_now().isoformat(),
    }


@router.post("/scan")
def trigger_scan(trigger: str = Query("manual", description="manual | api"), db: Session = Depends(get_db)):
    """手动触发一次提醒扫描（与定时任务同一份逻辑，供前端「立即检查」按钮）。"""
    return scan_alerts(db, trigger=trigger)


@router.get("/runs")
def list_runs(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    """扫描运行日志——用来验证定时任务是否真的在跑（防止 Windows 时区静默失败）。"""
    ensure_alert_schema(db)
    conn = raw_conn(db)
    rows = conn.execute(
        f"SELECT id, ran_at, {runs_trigger_column(conn)}, scanned, created_alerts, "
        "skipped_dup, elapsed_ms, detail "
        f"FROM kaoyan_alert_runs ORDER BY id DESC LIMIT {int(limit)}"
    ).fetchall()
    return {"total": len(rows), "items": [
        {"id": r[0], "ran_at": r[1], "trigger": r[2], "scanned": r[3],
         "created_alerts": r[4], "skipped_dup": r[5], "elapsed_ms": r[6],
         "detail": json.loads(r[7]) if r[7] else None}
        for r in rows
    ]}


# --------------------------------------------------------------------------- #
# 4. 手动导入（数据源：用户本地 PDF 解析 / 手工粘贴，非爬虫）
# --------------------------------------------------------------------------- #
@router.post("/import")
def import_notice(payload: ImportNotice, db: Session = Depends(get_db)):
    """手动导入一条通知并自动分级/抽日期。

    数据来源限制：仅接受 **用户主动提交的公开信息**（本地 PDF 解析结果、
    手工粘贴、CSV 批量导入）。本平台不提供、也不调用任何爬虫。
    """
    ensure_alert_schema(db)
    conn = raw_conn(db)
    pub = parse_date_loose(payload.publish_date) or cn_today()
    title = payload.title.strip()

    exist = conn.execute(
        "SELECT id FROM kaoyan_notices WHERE title = ? AND IFNULL(school_name,'') = ?",
        (title, payload.school_name or ""),
    ).fetchone()
    if exist:
        raise HTTPException(409, f"同标题通知已存在: {exist[0]}（请直接编辑或用 /classify 重算）")

    cls = classify_importance(title, payload.notice_type, body=payload.body)
    dates = extract_dates(f"{title}\n{payload.body or ''}", ref_date=pub)
    deadline = next((d["date"] for d in dates if d["is_deadline"]), None)
    level = payload.importance_level if payload.importance_level in LEVEL_ORDER else cls["level"]
    now_iso = naive_utc_iso()

    # content 列由 scripts/notice_content_migration.py 显式迁移引入。
    # 这里做列探测：迁移前不写该列（INSERT 显式列清单，形状恒定），
    # 迁移后写入正文快照，供 dry-run 脚本按「标题+正文」口径重跑覆盖率。
    cols = table_columns(conn, "kaoyan_notices")
    if "content" in cols:
        sql = ("INSERT INTO kaoyan_notices (school_id, school_name, title, notice_type, "
               "publish_date, url, source, fetched_at, importance_level, importance_score, "
               "importance_reason, deadline_date, events_json, classified_at, content) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
        vals = (payload.school_id, payload.school_name, title, payload.notice_type,
                pub.isoformat(), payload.url, payload.source, now_iso,
                level, cls["score"], "；".join(cls["reasons"])[:500], deadline,
                json.dumps(dates, ensure_ascii=False), now_iso, payload.body)
    else:
        sql = ("INSERT INTO kaoyan_notices (school_id, school_name, title, notice_type, "
               "publish_date, url, source, fetched_at, importance_level, importance_score, "
               "importance_reason, deadline_date, events_json, classified_at) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
        vals = (payload.school_id, payload.school_name, title, payload.notice_type,
                pub.isoformat(), payload.url, payload.source, now_iso,
                level, cls["score"], "；".join(cls["reasons"])[:500], deadline,
                json.dumps(dates, ensure_ascii=False), now_iso)

    cur = conn.execute(sql, vals)
    db.commit()
    # 明确告知导入者「这条到底有没有截止日」——抽不到就如实说，不猜不填
    deadline_msg = (f"已识别截止日 {deadline}" if deadline
                    else "未识别到截止日，请人工确认（正文含多个日期时取最早的截止日）")
    return {
        "id": cur.lastrowid, "importance_level": level,
        "importance_level_label": LEVEL_LABEL_CN.get(level, "普通"),
        "score": cls["score"], "reasons": cls["reasons"],
        "dates": dates, "deadline_date": deadline,
        "deadline_message": deadline_msg,
        "content_saved": "content" in cols,
        "body_chars": len(payload.body or ""),
    }


@router.post("/import/batch")
def import_notices_batch(
    payload: List[ImportNotice],
    db: Session = Depends(get_db),
):
    """批量导入（CSV 解析结果 / 连续粘贴）。逐条独立处理，单条失败不影响其他。"""
    ensure_alert_schema(db)
    conn = raw_conn(db)
    now_iso = naive_utc_iso()
    # content 列探测（迁移前不写，迁移后写正文快照），见 import_notice 注释
    cols = table_columns(conn, "kaoyan_notices")
    has_content = "content" in cols
    if has_content:
        sql = ("INSERT INTO kaoyan_notices (school_id, school_name, title, notice_type, "
               "publish_date, url, source, fetched_at, importance_level, importance_score, "
               "importance_reason, deadline_date, events_json, classified_at, content) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    else:
        sql = ("INSERT INTO kaoyan_notices (school_id, school_name, title, notice_type, "
               "publish_date, url, source, fetched_at, importance_level, importance_score, "
               "importance_reason, deadline_date, events_json, classified_at) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    ok, failed = 0, []
    for i, p in enumerate(payload):
        try:
            pub = parse_date_loose(p.publish_date) or cn_today()
            title = p.title.strip()
            if conn.execute(
                "SELECT 1 FROM kaoyan_notices WHERE title=? AND IFNULL(school_name,'')=?",
                (title, p.school_name or ""),
            ).fetchone():
                failed.append({"index": i, "title": title, "reason": "已存在"})
                continue
            cls = classify_importance(title, p.notice_type, body=p.body)
            dates = extract_dates(f"{title}\n{p.body or ''}", ref_date=pub)
            deadline = next((d["date"] for d in dates if d["is_deadline"]), None)
            level = p.importance_level if p.importance_level in LEVEL_ORDER else cls["level"]
            base = (p.school_id, p.school_name, title, p.notice_type, pub.isoformat(),
                    p.url, p.source, now_iso, level, cls["score"],
                    "；".join(cls["reasons"])[:500], deadline,
                    json.dumps(dates, ensure_ascii=False), now_iso)
            vals = base + (p.body,) if has_content else base
            conn.execute(sql, vals)
            ok += 1
        except Exception as e:  # noqa: BLE001
            failed.append({"index": i, "title": getattr(p, "title", ""), "reason": str(e)})
    db.commit()
    return {"imported": ok, "failed": len(failed), "failures": failed,
            "content_saved": has_content}
