# -*- coding: utf-8 -*-
"""从 txkyer.cn 提取种子数据导入数据库（222校通信电子类初始数据）。
使用方式：
    cd backend-main-fastapi
    python -c "from services.kaoyan.seed_txkyer import run; run()"
"""
import re, json, urllib.request, sys
from database import SessionLocal
# 注意：学科种子写入 **Discipline**（disciplines 表），而不是 KaoyanSubject——
# kaoyan_subjects 是 PG 视图（SELECT ... FROM disciplines），对视图 INSERT 会失败。
from core.models import KaoyanSchool, Discipline

BASE = "http://www.txkyer.cn/"

SEED_SUBJECTS = [
    {"code": "0803", "name": "光学工程", "category": "工学", "exam_overlap": "数电/模电/物理光学"},
    {"code": "0808", "name": "电气工程", "category": "工学", "exam_overlap": "电路/电机学"},
    {"code": "0809", "name": "电子科学与技术", "category": "工学", "exam_overlap": "数电/模电/半导体"},
    {"code": "0810", "name": "信息与通信工程", "category": "工学", "exam_overlap": "信号与系统/通信原理"},
    {"code": "0811", "name": "控制科学与工程", "category": "工学", "exam_overlap": "自动控制原理/电路"},
    {"code": "0812", "name": "计算机科学与技术", "category": "工学", "exam_overlap": "408/数据结构"},
    {"code": "0835", "name": "软件工程", "category": "工学", "exam_overlap": "408/软件工程"},
    {"code": "0854", "name": "电子信息(专硕)", "category": "工学", "exam_overlap": "数电/模电/信号"},
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def extract_schools_from_js():
    """从 txkyer.cn 的 data/kaoyan_data.js 提取院校列表。

    实际数据结构：window.KAOYAN_DATA = {"records":[[省份, 校名, 学院,
    专业代码, 专业名, ..., 院校级别], ...]}（数组形式，非 name/level/province 字段）。
    按院校名去重，级别从最后一位字段映射（985/211/双一流/双非）。
    """
    try:
        js = fetch(BASE + "data/kaoyan_data.js")
    except Exception as e:
        print(f"[WARN] 无法获取 kaoyan_data.js: {e}")
        return []
    m = re.search(r"window\.KAOYAN_DATA\s*=\s*(\{.*?\})\s*;?\s*$", js, re.S)
    if not m:
        print("[WARN] kaoyan_data.js 中未找到 KAOYAN_DATA 对象")
        return []
    try:
        data = json.loads(m.group(1))
    except Exception as e:
        print(f"[WARN] KAOYAN_DATA JSON 解析失败: {e}")
        return []
    schools = {}
    for rec in data.get("records", []):
        if not rec or len(rec) < 2:
            continue
        name = str(rec[1]).strip()
        if not name or name in schools:
            continue
        province = str(rec[0]).strip() if rec[0] else None
        level_raw = str(rec[-1]).strip() if rec[-1] else ""
        # 权威映射：985 / 211 / 双一流 / 双非 四档齐全。
        # 历史 bug：这里只认 ("985", "211", "双一流")，把「双非」丢成 None，
        # 导致大批双非院校 level 为空、前端层次筛选漏项。现已补齐。
        level = level_raw if level_raw in ("985", "211", "双一流", "双非") else None
        schools[name] = {"name": name, "level": level, "province": province}
    return list(schools.values())


def run():
    db = SessionLocal()
    try:
        # 导入学科（写入 disciplines 表，见模块头注释）
        existing = {s.code for s in db.query(Discipline).all()}
        added = 0
        for i, sub in enumerate(SEED_SUBJECTS):
            if sub["code"] not in existing:
                db.add(Discipline(sort_order=i, **sub))
                added += 1
        if added:
            db.commit()
            print(f"学科: 新增 {added} 个")
        else:
            print("学科: 已存在，跳过")

        # 导入院校种子
        schools = extract_schools_from_js()
        existing_schools = {s.name for s in db.query(KaoyanSchool).all()}
        added_schools = 0
        for sc in schools:
            if sc["name"] not in existing_schools:
                db.add(KaoyanSchool(
                    name=sc["name"],
                    level=sc.get("level"),
                    province=sc.get("province"),
                ))
                added_schools += 1
        if added_schools:
            db.commit()
            print(f"院校: 新增 {added_schools} 所")
        else:
            print("院校: 已存在，跳过")

        total = db.query(KaoyanSchool).count()
        print(f"完成。当前数据库共 {total} 所院校")
    finally:
        db.close()


if __name__ == "__main__":
    run()
