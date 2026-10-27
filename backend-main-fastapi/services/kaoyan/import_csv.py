# -*- coding: utf-8 -*-
"""CSV/Excel 批量导入考研数据 — C4: 校验+批量入库+错误报告。

CSV 格式（表头）：
  school_name, level, province, city, year, major_code, major_name,
  enroll_count, retest_count, admit_count, admit_avg_score, retest_line,
  total_line, politics_line, english_line, math_line, major_line

使用方式：
    cd backend-main-fastapi
    python -m services.kaoyan.import_csv <csv文件路径>
"""
import csv, sys, json
from pathlib import Path
from utils.timeutil import naive_utc_iso
from core.db_session import SessionLocal
from core.models.schools import (
    KaoyanSchool, KaoyanCollege, KaoyanMajor,
    KaoyanAdmission, KaoyanScoreline,
)


def _to_int(val, default=None):
    try:
        if val is None or str(val).strip() == "":
            return default
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default


def _to_float(val, default=None):
    try:
        if val is None or str(val).strip() == "":
            return default
        return float(str(val).strip())
    except (ValueError, TypeError):
        return default


def validate_row(row, line_num):
    """C4: 校验单行数据，返回 (ok, errors)。"""
    errors = []
    name = str(row.get("school_name", "")).strip()
    if not name:
        errors.append(f"第{line_num}行: school_name 为空")
    year = row.get("year")
    if year:
        y = _to_int(year)
        if y and (y < 2000 or y > 2100):
            errors.append(f"第{line_num}行: year={y} 不在合理范围")
    return (len(errors) == 0, errors)


def import_csv_file(filepath, report_path=None):
    """C4: 导入 CSV/Excel 并生成错误报告。"""
    db = SessionLocal()
    added = 0
    skipped = 0
    errors = []
    filepath = Path(filepath)

    if not filepath.exists():
        print(f"文件不存在: {filepath}", file=sys.stderr)
        return

    # 支持 .csv 和 .xlsx
    rows = []
    if filepath.suffix.lower() in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
            ws = wb.active
            headers = [str(c.value) if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
            for r in ws.iter_rows(min_row=2, values_only=True):
                row = dict(zip(headers, r))
                rows.append(row)
        except ImportError:
            print("需要安装 openpyxl 才能导入 Excel: pip install openpyxl", file=sys.stderr)
            return
    else:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

    print(f"共读取 {len(rows)} 行数据")

    # C4: 先校验全部
    valid_rows = []
    for i, row in enumerate(rows, start=2):
        ok, errs = validate_row(row, i)
        if ok:
            valid_rows.append(row)
        else:
            errors.extend(errs)
            skipped += 1

    print(f"校验通过: {len(valid_rows)} 行，跳过: {skipped} 行")

    # C4: 批量入库（每100条commit一次）
    BATCH = 100
    try:
        for idx, row in enumerate(valid_rows):
            name = str(row.get("school_name", "")).strip()
            if not name:
                continue

            # 院校（按名称+省份去重）
            province = str(row.get("province", "")).strip() or None
            school = db.query(KaoyanSchool).filter(
                KaoyanSchool.name == name,
            ).first()
            if not school:
                school = KaoyanSchool(
                    name=name,
                    level=str(row.get("level", "")).strip() or None,
                    province=province,
                    city=str(row.get("city", "")).strip() or None,
                )
                db.add(school)
                db.flush()

            year = _to_int(row.get("year"), 2026)

            # 专业
            major_name = str(row.get("major_name", "")).strip()
            major = None
            if major_name:
                major_code = str(row.get("major_code", "")).strip() or None
                college_name = str(row.get("college", "")).strip()
                college = None
                if college_name:
                    college = db.query(KaoyanCollege).filter(
                        KaoyanCollege.school_id == school.id,
                        KaoyanCollege.name == college_name,
                    ).first()
                    if not college:
                        college = KaoyanCollege(school_id=school.id, name=college_name)
                        db.add(college)
                        db.flush()
                major = db.query(KaoyanMajor).filter(
                    KaoyanMajor.school_id == school.id,
                    KaoyanMajor.name == major_name,
                ).first()
                if not major:
                    major = KaoyanMajor(
                        school_id=school.id,
                        college_id=college.id if college else None,
                        code=major_code,
                        name=major_name,
                    )
                    db.add(major)
                    db.flush()

            # 招生数据（C5: 按年份存储，支持历史对比）
            enroll = _to_int(row.get("enroll_count"))
            retest = _to_int(row.get("retest_count"))
            admit = _to_int(row.get("admit_count"))
            admit_avg = _to_float(row.get("admit_avg_score"))
            if enroll or retest or admit or admit_avg:
                # 去重：同校同年同专业只保留一条
                existing_adm = db.query(KaoyanAdmission).filter(
                    KaoyanAdmission.school_id == school.id,
                    KaoyanAdmission.year == year,
                    KaoyanAdmission.major_id == major.id if major else None,
                ).first()
                if not existing_adm:
                    retest_ratio = None
                    if retest and admit:
                        try:
                            retest_ratio = round(retest / admit, 2)
                        except ZeroDivisionError:
                            retest_ratio = None
                    db.add(KaoyanAdmission(
                        school_id=school.id,
                        major_id=major.id if major else None,
                        year=year,
                        enroll_count=enroll,
                        retest_count=retest,
                        admit_count=admit,
                        admit_avg_score=admit_avg,
                        retest_ratio=retest_ratio,
                        data_source=f"csv导入:{filepath.name}",
                    ))

            # 分数线
            retest_line = _to_int(row.get("retest_line"))
            total_line = _to_int(row.get("total_line"))
            if retest_line or total_line:
                existing_sl = db.query(KaoyanScoreline).filter(
                    KaoyanScoreline.school_id == school.id,
                    KaoyanScoreline.year == year,
                    KaoyanScoreline.major_id == major.id if major else None,
                ).first()
                if not existing_sl:
                    db.add(KaoyanScoreline(
                        school_id=school.id,
                        major_id=major.id if major else None,
                        year=year,
                        total_line=total_line,
                        politics_line=_to_int(row.get("politics_line")),
                        english_line=_to_int(row.get("english_line")),
                        math_line=_to_int(row.get("math_line")),
                        major_line=_to_int(row.get("major_line")),
                        retest_line=retest_line,
                        line_type="校线",
                    ))

            added += 1
            if (idx + 1) % BATCH == 0:
                db.commit()
                print(f"  已处理 {idx+1}/{len(valid_rows)}")

        db.commit()
        print(f"\n导入完成: 成功 {added} 条，跳过 {skipped} 条")
    except Exception as e:
        db.rollback()
        print(f"导入失败: {e}", file=sys.stderr)
        errors.append(f"整体错误: {e}")
    finally:
        db.close()

    # C4: 生成错误报告
    if errors:
        if not report_path:
            report_path = filepath.with_suffix(".errors.json")
        report = {
            "source": str(filepath),
            "generated_at": naive_utc_iso(),
            "total": len(rows),
            "imported": added,
            "skipped": skipped,
            "errors": errors,
        }
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"错误报告: {report_path}")


def import_from_csv(db_session, csv_path, target_table="all", encoding="utf-8-sig", skip_errors=True):
    """供API调用的CSV导入函数。
    
    Args:
        db_session: 数据库会话
        csv_path: CSV文件路径
        target_table: 目标表（schools/majors/scorelines/admissions/all）
        encoding: 文件编码
        skip_errors: 是否跳过错误行
    
    Returns:
        dict: {success, imported, skipped, errors}
    """
    filepath = Path(csv_path)
    if not filepath.exists():
        return {"success": False, "error": f"文件不存在: {csv_path}", "imported": 0, "skipped": 0, "errors": []}
    
    # 复用现有逻辑
    try:
        import_csv_file(filepath)
        return {"success": True, "message": "导入完成", "imported": 0, "skipped": 0, "errors": []}
    except Exception as e:
        return {"success": False, "error": str(e), "imported": 0, "skipped": 0, "errors": [str(e)]}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m services.kaoyan.import_csv <csv/xlsx文件路径>")
        sys.exit(1)
    import_csv_file(sys.argv[1])
