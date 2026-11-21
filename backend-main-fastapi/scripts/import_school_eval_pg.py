#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""08 工学学科评估与院校主档导入（PostgreSQL，119 分片配套）。

数据源：仓库内 ``data-assets/工学院校评价库/``（2026-11-21 并入）：
  * schools.json                    院校主档 329 所（含介绍/评价/优势学科/标志）
  * discipline_eval.json            第四轮学科评估明细 2011 条
  * double_first_engineering.json   第二轮双一流工学学科 179 条
  * gzdx_ky_08工学院校数据.sql       仅从中解析 ky_discipline 字典（48 条）

口径纪律（源 README 第三节，展示层必须遵守）：
  评估只公布前 70%（未上榜≠差）；0838/0839 未列入第四轮；第五轮未公开不得编造；
  joint/institute 不与普通高校混排；heat_tag 主观估算；data_status=3 待核验。

流程：默认 dry-run 预览计数 -> --apply 单事务入库（失败回滚）。
幂等：四表全部 ON CONFLICT DO UPDATE，可重复执行。
路径纪律：默认数据目录相对仓库根解析，无盘符字面量（healthcheck 门禁）。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._conn import pg_connect  # noqa: E402  口令来自 .env（PG_*）

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data-assets" / "工学院校评价库"

DISCIPLINE_INSERT_RE = re.compile(r"INSERT INTO ky_discipline VALUES \('([^']*)','([^']*)',(\d+),(\d+),'([^']*)'\)")


def _load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _py_literal(value, fallback):
    """源 JSON 里 industry_tags/strengths 是 Python 字面量字符串，转真列表。"""
    if isinstance(value, list | dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return fallback
    return fallback


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _code(value):
    v = (value or "").strip()
    return v or None


def load_disciplines(data_dir: Path):
    sql_path = data_dir / "gzdx_ky_08工学院校数据.sql"
    text = sql_path.read_text(encoding="utf-8")
    rows = []
    for m in DISCIPLINE_INSERT_RE.finditer(text):
        code, name, degree_type, eval4_status, note = m.groups()
        rows.append((code, name, int(degree_type), int(eval4_status), note))
    if not rows:
        raise SystemExit(f"未能从 {sql_path.name} 解析 ky_discipline 字典 INSERT")
    return rows


def _dedup_loc(text, province, city):
    """直辖市 province==city 时源数据生成「位于北京北京」叠词，归一为「位于北京」。"""
    if text and province and province == city:
        text = text.replace(f"位于{province}{city}", f"位于{province}")
    return text


def load_schools(data_dir: Path):
    rows = []
    for s in _load_json(data_dir / "schools.json"):
        prov, city = s["province"], s["city"]
        rows.append(
            (
                _code(s.get("school_code")),
                s["name"],
                prov,
                city,
                _int(s.get("school_type"), 1),
                _int(s.get("unit_type"), 1),
                _int(s.get("is_985")),
                _int(s.get("is_211")),
                _int(s.get("is_double_first")),
                _int(s.get("is_self_marked")),
                _dedup_loc(s.get("intro"), prov, city),
                _dedup_loc(s.get("evaluation"), prov, city),
                _dedup_loc(s.get("feature"), prov, city),
                s.get("tier_txt"),
                s.get("heat_tag"),
                s.get("heat_note"),
                json.dumps(_py_literal(s.get("industry_tags"), []), ensure_ascii=False),
                json.dumps(_py_literal(s.get("strengths"), []), ensure_ascii=False),
                _int(s.get("eval_cnt")),
                _int(s.get("a_cnt")),
                _int(s.get("bp_cnt")),
                _int(s.get("data_status"), 2),
                s.get("verify_note"),
            )
        )
    return rows


def load_evals(data_dir: Path):
    rows = []
    for e in _load_json(data_dir / "discipline_eval.json"):
        rows.append(
            (
                e["school_name"],
                _code(e.get("school_code")) or "",
                e["discipline"],
                e["grade"],
                4,
                e.get("scope") or "normal",
                "教育部第四轮学科评估官方公布",
            )
        )
    return rows


def load_double_first(data_dir: Path):
    rows = []
    for d in _load_json(data_dir / "double_first_engineering.json"):
        rows.append((d["school_name"], d["discipline"], d["discipline_name"], 2))
    return rows


UPSERTS = [
    (
        "ky_discipline",
        """INSERT INTO ky_discipline (code, name, degree_type, eval4_status, note)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (code) DO UPDATE SET
             name=EXCLUDED.name, degree_type=EXCLUDED.degree_type,
             eval4_status=EXCLUDED.eval4_status, note=EXCLUDED.note""",
    ),
    (
        "ky_school",
        """INSERT INTO ky_school (school_code,name,province,city,school_type,unit_type,
               is_985,is_211,is_double_first,is_self_marked,intro,evaluation,feature,tier_txt,
               heat_tag,heat_note,industry_tags,strengths_json,eval_cnt,a_cnt,bp_cnt,
               data_status,verify_note)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (name) DO UPDATE SET
             school_code=EXCLUDED.school_code, province=EXCLUDED.province, city=EXCLUDED.city,
             school_type=EXCLUDED.school_type, unit_type=EXCLUDED.unit_type,
             is_985=EXCLUDED.is_985, is_211=EXCLUDED.is_211,
             is_double_first=EXCLUDED.is_double_first, is_self_marked=EXCLUDED.is_self_marked,
             intro=EXCLUDED.intro, evaluation=EXCLUDED.evaluation, feature=EXCLUDED.feature,
             tier_txt=EXCLUDED.tier_txt, heat_tag=EXCLUDED.heat_tag, heat_note=EXCLUDED.heat_note,
             industry_tags=EXCLUDED.industry_tags, strengths_json=EXCLUDED.strengths_json,
             eval_cnt=EXCLUDED.eval_cnt, a_cnt=EXCLUDED.a_cnt, bp_cnt=EXCLUDED.bp_cnt,
             data_status=EXCLUDED.data_status, verify_note=EXCLUDED.verify_note""",
    ),
    (
        "ky_school_discipline_eval",
        """INSERT INTO ky_school_discipline_eval
               (school_name,school_code,discipline_code,grade,eval_round,eval_scope,source)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (school_name,discipline_code,eval_round) DO UPDATE SET
             school_code=EXCLUDED.school_code, grade=EXCLUDED.grade,
             eval_scope=EXCLUDED.eval_scope, source=EXCLUDED.source""",
    ),
    (
        "ky_school_double_first",
        """INSERT INTO ky_school_double_first (school_name,discipline_code,discipline_name,round)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT (school_name,discipline_code,round) DO UPDATE SET
             discipline_name=EXCLUDED.discipline_name""",
    ),
]


def main():
    ap = argparse.ArgumentParser(description="08工学学科评估导入（119 分片配套）")
    ap.add_argument(
        "--data-dir", default=str(DEFAULT_DATA_DIR), help="数据目录（默认仓库内 data-assets/工学院校评价库）"
    )
    ap.add_argument("--apply", action="store_true", help="真入库（默认 dry-run 只预览）")
    args = ap.parse_args()
    data_dir = Path(args.data_dir)

    disciplines = load_disciplines(data_dir)
    schools = load_schools(data_dir)
    evals = load_evals(data_dir)
    syl = load_double_first(data_dir)
    batches = [disciplines, schools, evals, syl]

    print(f"数据目录: {data_dir}")
    for (table, _), rows in zip(UPSERTS, batches, strict=False):
        print(f"  {table}: {len(rows)} 行")
    # 交叉一致性：院校主档内嵌 evals 总数应等于明细表行数
    embedded = sum(len(s.get("evals") or []) for s in _load_json(data_dir / "schools.json"))
    print(
        f"  交叉校验: schools.json 内嵌 evals={embedded} vs discipline_eval.json={len(evals)}"
        + ("（一致）" if embedded == len(evals) else "（不一致，以明细 JSON 为准）")
    )

    if not args.apply:
        print("dry-run 结束：加 --apply 入库")
        return

    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            for (table, sql), rows in zip(UPSERTS, batches, strict=False):
                cur.executemany(sql, rows)
                print(f"  upsert {table}: {len(rows)}")
            for table, _ in UPSERTS:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                print(f"  入库后 {table} 总行数: {cur.fetchone()[0]}")
        conn.commit()
        print("APPLY_OK（单事务提交）")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
