# -*- coding: utf-8 -*-
"""空表分析与治理建议。

对 data_audit.py --full 输出的 60 张空表，逐表给出：
    (table_name, model_class, business_purpose, recommendation)

recommendation 取值：
    keep       — 功能表，运行时按需填充，无需预置数据
    needs_data — 功能表，需导入数据才能启用
    deprecated — 废弃表 / 历史遗留 / 未启用功能

只读分析，不写库，幂等。模型类名通过反射 models.py 的 SQLAlchemy Base 获取；
未在 ORM 中定义的表 model_class 为 "(none)"。

用法：
    python scripts/governance/analyze_empty_tables.py
    python scripts/governance/analyze_empty_tables.py --verify   # 连库校验空表清单
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
MODELS_PATH = BACKEND_DIR / "models.py"


# 60 张空表的 (business_purpose, recommendation) 元数据。
# 分类依据：是否有 ORM 模型 + 表名语义 + 是否运行时表。
EMPTY_TABLE_META: dict[str, tuple[str, str]] = {
    # --- keep: 有模型类，运行时按需生成 ---
    "annotation_samples": ("标注样本表，按需生成标注数据", "keep"),
    "crawl_dead_letters": ("爬虫死信队列，运行时记录失败投递", "keep"),
    "crawl_jobs": ("爬虫任务表，按需创建抓取任务", "keep"),
    "crawl_pages": ("爬虫页面表，运行时记录已抓页面", "keep"),
    "daily_plans": ("日计划表，用户运行时生成", "keep"),
    "document_blocks": ("文档分块表，文档处理时生成", "keep"),
    "document_classify_queue": ("文档分类队列，按需入队", "keep"),
    "document_pages": ("文档页表，文档处理时生成", "keep"),
    "early_bird_records": ("早打卡记录表，运行时生成", "keep"),
    "knowledge_point_relations": ("知识点关系表，可后续补建", "keep"),
    "memory_facts": ("记忆事实表，记忆系统运行时生成", "keep"),
    "memory_synthesis": ("记忆合成表，记忆系统运行时生成", "keep"),
    "memory_traces": ("记忆轨迹表，记忆系统运行时生成", "keep"),
    "phase_plans": ("阶段计划表，用户运行时生成", "keep"),
    "question_evidence_links": ("题目证据链接表，运行时生成", "keep"),
    "quiz_attempts": ("测验尝试表，运行时生成", "keep"),
    "quiz_question_set_items": ("题集项表，运行时生成", "keep"),
    "quiz_question_sets": ("题集表，运行时生成", "keep"),
    "quiz_question_states": ("题目状态表，运行时生成", "keep"),
    "quiz_session_questions": ("会话题目表，运行时生成", "keep"),
    "quiz_sessions": ("测验会话表，运行时生成", "keep"),
    "review_records": ("复习记录表，运行时生成", "keep"),
    "study_sessions": ("学习会话表，运行时生成", "keep"),
    "study_stats": ("学习统计表，运行时生成", "keep"),
    "subject_prototypes": ("科目原型表，可后续补建", "keep"),
    "task_checkins": ("任务签到表，运行时生成", "keep"),
    "task_modules": ("任务模块字典表，运行时生成", "keep"),
    "tasks": ("任务表，运行时生成", "keep"),
    "week_plans": ("周计划表，用户运行时生成", "keep"),
    # --- needs_data: 有模型类，需预置数据 ---
    "sft_examples": ("SFT 训练样本表，需导入训练数据", "needs_data"),
    # --- needs_data: 无模型类，用户/业务功能待启用 ---
    "code_questions": ("编程题表，需导入编程题库", "needs_data"),
    "code_submissions": ("编程提交表，需用户提交数据", "needs_data"),
    "code_submission_results": ("编程提交结果表，需评测数据", "needs_data"),
    "exam_answers": ("考试答案表，需考试作答数据", "needs_data"),
    "exam_sessions": ("考试会话表，需考试数据", "needs_data"),
    "favorites": ("收藏表，需用户收藏数据", "needs_data"),
    "focus_sessions": ("专注会话表，需用户专注数据", "needs_data"),
    "kaoyan_alert_records": ("考研提醒记录表，需订阅触发数据", "needs_data"),
    "kaoyan_subscriptions": ("考研订阅表，需用户订阅数据", "needs_data"),
    "netdisk_file_cache": ("网盘文件缓存表，需网盘接入数据", "needs_data"),
    "netdisk_operation_logs": ("网盘操作日志表，需网盘操作数据", "needs_data"),
    "paper_answers": ("真题答案表，需真题作答数据", "needs_data"),
    "paper_attempts": ("真题作答表，需用户作答数据", "needs_data"),
    "pending_questions": ("待处理问题表，需导入待处理题", "needs_data"),
    "subject_removals": ("科目移除记录表，需移除操作数据", "needs_data"),
    "third_party_accounts": ("第三方账号表，需用户绑定数据", "needs_data"),
    "user_profiles": ("用户档案表，需用户档案数据", "needs_data"),
    "watermark_lexicon": ("水印词典表，需导入水印词库", "needs_data"),
    "weak_knowledge": ("薄弱知识点表，需学习诊断数据", "needs_data"),
    # --- deprecated: 未启用功能 / 历史遗留 ---
    "answer_candidates": ("答案候选表，未启用功能", "deprecated"),
    "answer_review_queue": ("答案审核队列，未启用功能", "deprecated"),
    "checkin_logs": ("签到日志表，被 task_checkins 替代", "deprecated"),
    "coin_accounts": ("金币账户表，未启用金币系统", "deprecated"),
    "coin_ledger": ("金币账本表，未启用金币系统", "deprecated"),
    "conflict_review_queue": ("冲突审核队列，未启用功能", "deprecated"),
    "phase_daily_reviews": ("阶段日复习表，未启用功能", "deprecated"),
    "preview_sessions": ("预览会话表，未启用功能", "deprecated"),
    "redemptions": ("兑换记录表，未启用兑换功能", "deprecated"),
    "retrieval_gate_logs": ("检索门控日志表，未启用功能", "deprecated"),
    "universities_legacy": ("院校遗留表，被 kaoyan_schools 替代", "deprecated"),
}


def load_model_class_map() -> dict[str, str]:
    """从 models.py 反射 table_name → model_class 映射。

    用正则解析而非 import，避免触发 ORM 副作用（引擎绑定、metadata 注册等）。
    """
    src = MODELS_PATH.read_text(encoding="utf-8")
    pairs = re.findall(
        r"^class (\w+)\(Base\).*?__tablename__\s*=\s*[\"'](\w+)[\"']",
        src,
        re.MULTILINE | re.DOTALL,
    )
    return {tbl: cls for cls, tbl in pairs}


def verify_empty_tables() -> list[str] | None:
    """连库校验空表清单，返回实际空表名列表；连接失败返回 None。"""
    try:
        from scripts._conn import pg_connect
    except Exception:  # noqa: BLE001
        return None
    try:
        with pg_connect() as conn:
            cur = conn.execute(
                "select c.relname from pg_class c "
                "join pg_namespace n on n.oid=c.relnamespace and n.nspname='public' "
                "where c.relkind='r' order by c.relname"
            )
            all_tables = [r[0] for r in cur.fetchall()]
            empties: list[str] = []
            for t in all_tables:
                cnt = conn.execute(f'select count(*) from "{t}"').fetchone()[0]
                if cnt == 0:
                    empties.append(t)
            return empties
    except Exception:  # noqa: BLE001
        return None


def analyze() -> list[tuple[str, str, str, str]]:
    """返回 [(table_name, model_class, business_purpose, recommendation), ...]。"""
    tbl2cls = load_model_class_map()
    return [(table, tbl2cls.get(table, "(none)"), purpose, rec) for table, (purpose, rec) in EMPTY_TABLE_META.items()]


def main() -> int:
    parser = argparse.ArgumentParser(description="空表分析与治理建议")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="连库校验空表清单与实际是否一致",
    )
    args = parser.parse_args()

    rows = analyze()

    if args.verify:
        actual = verify_empty_tables()
        if actual is None:
            print("[warn] 无法连接数据库，跳过空表清单校验")
        else:
            expected = set(EMPTY_TABLE_META)
            actual_set = set(actual)
            only_in_meta = expected - actual_set
            only_in_db = actual_set - expected
            if not only_in_meta and not only_in_db:
                print(f"[ok] 空表清单与数据库一致（{len(actual)} 张）")
            else:
                if only_in_meta:
                    print(f"[warn] 元数据中有但数据库非空（{len(only_in_meta)}）: {sorted(only_in_meta)}")
                if only_in_db:
                    print(f"[warn] 数据库空但元数据未收录（{len(only_in_db)}）: {sorted(only_in_db)}")
            print()

    # 输出四元组表格
    print(f"{'table_name':36} {'model_class':28} {'recommendation':12} business_purpose")
    print("-" * 100)
    for table, cls, purpose, rec in rows:
        print(f"{table:36} {cls:28} {rec:12} {purpose}")

    # 汇总
    counts: dict[str, int] = {}
    for _, _, _, rec in rows:
        counts[rec] = counts.get(rec, 0) + 1
    print("-" * 100)
    print(
        f"共 {len(rows)} 张空表："
        f"keep={counts.get('keep', 0)} "
        f"needs_data={counts.get('needs_data', 0)} "
        f"deprecated={counts.get('deprecated', 0)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
