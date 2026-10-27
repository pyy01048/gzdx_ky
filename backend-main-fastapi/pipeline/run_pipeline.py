# -*- coding: utf-8 -*-
"""管线 CLI 入口。

用法
----
    python -m pipeline.run_pipeline --dry-run --limit 200
    python -m pipeline.run_pipeline --limit 2000 --emit-ddl
    python -m pipeline.run_pipeline --verify-only
    python -m pipeline.run_pipeline --selftest
    python -m pipeline.run_pipeline --show-samples 20

``--dry-run`` 不落任何文件；``--selftest`` 用真实脏数据形态当 fixtures 做回归断言
（含金标准：比 Options 修复前后的期望值），断言全部来自 kaoyan.db 实测，不是编造。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline import verify as ver                      # noqa: E402
from pipeline.config import (                           # noqa: E402
    DEFAULT_ACCURACY_THRESHOLD, DEFAULT_LIMIT, DEFAULT_SAMPLE_SIZE, DEFAULT_SEED,
    read_only_sqlite_uri,
)
from pipeline.etl_sqlite_to_pg import run_etl           # noqa: E402
from pipeline.question_schema import normalize_options, validate_question, CanonicalQuestion  # noqa: E402
from pipeline import watermark as wm                    # noqa: E402
from pipeline.classifier import classify_origin, normalize_subject  # noqa: E402

__all__ = ["build_parser", "selftest", "print_report", "main"]


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    p = argparse.ArgumentParser(prog="pipeline", description="考研数据治理 ETL 管线")
    p.add_argument("--dry-run", action="store_true", help="只统计不写文件")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="每类源处理的最大行数")
    p.add_argument("--verify-only", action="store_true", help="只读回产物做验收")
    p.add_argument("--emit-ddl", action="store_true", help="同时生成 PostgreSQL DDL")
    p.add_argument("--out-dir", default=None, help="产物输出目录")
    p.add_argument("--db", default=None, help="SQLite 路径（只读）")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help="抽样随机种子")
    p.add_argument("--threshold", type=float, default=DEFAULT_ACCURACY_THRESHOLD, help="准确率门禁")
    p.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE, help="抽样条数")
    p.add_argument("--selftest", action="store_true", help="跑内置回归断言（用真实脏样本）")
    p.add_argument("--show-samples", type=int, default=0, help="打印 N 条清洗前后对比")
    p.add_argument("--enforce-gate", action="store_true", help="不达标则以非 0 退出码退出")
    return p


# --------------------------------------------------------------------------- #
# 内置回归断言：全部来自 kaoyan.db 实测脏样本
# --------------------------------------------------------------------------- #
_GOLDEN_OPTIONS = [
    # (说明, 原始 options, 期望 options 数量, 期望首项 key)
    ("id=18 题干碎片混入：取最长递增段",
     ["A、", "B）当成反相器使用，则", "A、B 端应________ 连接。",
      "A.A 或B 中有一个接1", "B.A 或B 中有一个接0", "C.A 和B 并联使用", "D.不能实现"],
     4, "A"),
    ("id=21 首项为上题残留题干",
     ["C）＝∑m（0，1，2，6），则它的最大项表达式是F＝ （ ）",
      "A、πM（0,1,2,6）", "B、πM（0,1,2）", "C、πM（3,4,5,7）", "D、πM（4,5,7）"],
     4, "A"),
    ("id=22 末项粘连下一题型标题",
     ["A、输出电压和输入电压", "B、输出电压与输出电流",
      "C、电路的抗干扰能力 二、填空题（每题5 分，共30 分）"],
     3, "A"),
    ("id=58 仅 1 项且无 A：整体回退为题干碎片",
     ["D）工作时需加反向电压，才能发出特定波长的光。"], 0, None),
    ("正常四选项应原样保留",
     ["A．奇偶校验码", "B．5421BCD 码", "C．余三码", "D．格雷码"], 4, "A"),
    ("字符串 null 代表无选项",
     "null", 0, None),
]

_GOLDEN_WATERMARK = [
    ("OCR 页标记整行", "--- 第1页(OCR) ---\n真正的正文内容在这里。", "真正的正文内容在这里。"),
    ("品牌行内水印", "判断反馈组态 东坡哥微信:haidongpo8 第 3 页", "判断反馈组态"),
    (" Colon 联系方式", "电子通信考研择校、精品课程联系东坡哥：", ""),
    # 只保证「行内片段被剔除」，同行的正文必须原样保留（宁可漏删不可误杀）
    ("考研专家残片", "电路如惠斯顿电桥 你身边的考研专家！ 接下来是正文内容",
     "电路如惠斯顿电桥 接下来是正文内容"),
    # 防误杀回归：正常行文里的「公众号召力」绝不能被当成公众号水印删掉
    ("正常行文不得误杀", "不可否认的是，偶像具有强大的公众号召力，因为从人性的弱点方面来说",
     "不可否认的是，偶像具有强大的公众号召力，因为从人性的弱点方面来说"),
    ("带冒号的公众号仍需清除", "习题详解 微信公众号:电子与通信工程考研 更多资料",
     "习题详解 更多资料"),
    # 作答空位不是噪声：________ 必须原样保留
    ("保留作答空位", "2、已知F=ABC+CD，选出下列可以肯定使F=0 的取值________________。",
     "2、已知F=ABC+CD，选出下列可以肯定使F=0 的取值________________。"),
    ("扫描App连写尾巴", "扫描全能王 创建扫描全能王 创建这是正文", "这是正文"),
]


def selftest() -> int:
    """跑内置回归断言。返回失败数（0 表示全通过）。"""
    failures = 0
    bundle = wm.load_rules()

    print("[1/3] 选项修复断言")
    for desc, raw, want_n, want_key in _GOLDEN_OPTIONS:
        opts, diag = normalize_options(raw)
        got_n = len(opts)
        got_key = opts[0]["key"] if opts else None
        ok = got_n == want_n and (want_key is None or got_key == want_key)
        print(f"    {'PASS' if ok else 'FAIL'}  {desc} -> {got_n} 项, 首项 {got_key}")
        if not ok:
            failures += 1
            print(f"          期望 {want_n} 项 / 首项 {want_key}；诊断={diag}")

    print("[2/3] 水印清洗断言")
    for desc, raw, want in _GOLDEN_WATERMARK:
        clean, hits = wm.strip_watermark(raw, bundle)
        ok = clean.strip() == want.strip()
        print(f"    {'PASS' if ok else 'FAIL'}  {desc} -> {clean!r}")
        if not ok:
            failures += 1
            print(f"          期望 {want!r}；命中={[h['rule_id'] for h in hits]}")

    print("[3/3] 分类与科目断言")
    cases = [
        ("知识库前缀但文件名是真题 -> 提升", "知识库:贵大16-25真题.pdf", None, "past_exam"),
        ("真题前缀但文件名是章题库 -> 降级", "真题:数字电子技术基础章节题库.pdf", None, "exercise"),
        ("纯知识库 -> textbook", "知识库:模拟电子技术基础 第6版 .txt", None, "textbook"),
    ]
    for desc, source, _fname, want in cases:
        origin, conf, ev = classify_origin(source, None, None)
        ok = origin == want
        print(f"    {'PASS' if ok else 'FAIL'}  {desc} -> {origin} ({conf:.2f})")
        if not ok:
            failures += 1
    canonical, bucket, alias = normalize_subject("法律硕士专业基础", None, None)
    ok = canonical == "法律硕士专业基础" and bucket == "off_target"
    print(f"    {'PASS' if ok else 'FAIL'}  法硕应判为无关科目 -> {canonical}/{bucket}")
    if not ok:
        failures += 1

    # 变异定向加固：把「正常四选项」的样本拿去校验，不该出现 hard error
    opts, _ = normalize_options(["A．奇偶校验码", "B．5421BCD 码", "C．余三码", "D．格雷码"])
    v = validate_question(CanonicalQuestion(stem="下列代码中属于无权码的是？", options=opts,
                                            answer="C", question_type="single",
                                            origin="textbook", subject_norm="数字电子技术"))
    ok = v["ok"] is True
    print(f"    {'PASS' if ok else 'FAIL'}  完好题目应通过校验门 -> {v}")
    if not ok:
        failures += 1

    print(f"\n结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return failures


def _diff_window(before: str, after: str, matched: str, window: int = 32) -> None:
    """打印变更点的局部对照，而不是整行从头截断（长行看不出改在哪）。"""
    if not after.strip():
        print(f"    前: ...{before[-min(len(before), 90):]}...")
        print("    后: (整行丢弃)")
        return
    pos = before.find(matched) if matched else -1
    if pos < 0:
        print(f"    前: {before[:100]}")
        print(f"    后: {after[:100]}")
        return
    start = max(0, pos - window)
    end = min(len(before), pos + len(matched) + window)
    print(f"    前: ...{before[start:end]}...")
    cut = after.replace(matched, "")
    head = max(0, cut.find(before[max(0, start):pos][-12:]) if start > 0 else 0)
    tail_start = max(0, head)
    print(f"    后: ...{cut[tail_start:tail_start + (end - start) + window]}...")


def show_samples(n: int, db_path: str | None = None) -> int:
    """打印真实数据的「清洗前 / 清洗后」对比，供用户抽查。

    这是落实用户「不管导入什么都要去验证准确率」诉求的关键动作：
    每条都给出命中了哪条规则，方便人工复核是否误杀。

    Args:
        n: 打印条数。
        db_path: SQLite 路径（只读）。

    Returns:
        打印出的条数。
    """
    import sqlite3

    from pipeline.config import read_only_sqlite_uri

    bundle = wm.load_rules()
    conn = sqlite3.connect(read_only_sqlite_uri(db_path), uri=True)
    printed = 0
    seen_rules: set[str] = set()
    try:
        rows = conn.execute(
            "SELECT id, doc_name, text FROM knowledge_chunks "
            "WHERE text IS NOT NULL AND TRIM(text) <> '' "
            "ORDER BY id LIMIT 5000"
        )
        for cid, doc_name, raw in rows:
            if printed >= n:
                break
            clean, hits = wm.strip_watermark(raw, bundle)
            if not hits:
                continue
            # 逐条规则展示：优先展示还没展示过的规则，保证样本多样性
            rule_ids = sorted({h["rule_id"] for h in hits})
            if seen_rules.issuperset(rule_ids) and printed > 0:
                continue
            seen_rules.update(rule_ids)
            printed += 1
            print("-" * 72)
            print(f"chunk #{cid}  {doc_name or ''}   命中规则: {rule_ids}")
            # 只展示真正发生变化的原始行与其清洗结果，逐行对齐便于肉眼判断有无误杀
            shown = 0
            for h in hits:
                line_no = h["line_no"]
                raw_line = raw.split("\n")[line_no - 1]
                after_line, _ = wm.strip_watermark(raw_line, bundle)
                if after_line == raw_line:
                    continue
                print(f"  [{h['rule_id']}]")
                _diff_window(raw_line, after_line, h["matched"])
                shown += 1
                if shown >= 3:
                    break
    finally:
        conn.close()
    print(f"\n共展示 {printed} 条；覆盖规则 {sorted(seen_rules)}")
    print("每条均给出命中的规则 id 与逐行对照，可按 id 回溯到 watermark_rules.json 复核。")
    return printed


def print_report(result: dict) -> None:
    """打印易读的结果摘要。"""
    v = result.get("verification") or {}
    print()
    print("=" * 62)
    print("ETL 结果摘要")
    print("=" * 62)
    if "questions_total" in result:
        print(f"  题目    总 {result['questions_total']:>6}  干净 {result['questions_clean']:>6}  "
              f"待修复 {result['questions_repair']:>6}  答案回填 {result.get('answers_enriched', 0):>5}")
        print(f"  文档    干净 {result['documents_clean']:>6}  待修复 {result['documents_repair']:>6}")
        print(f"  分块    干净 {result['chunks_clean']:>6}  待修复 {result['chunks_repair']:>6}")
    if v:
        print("-" * 62)
        print(f"  抽样 {v['total']}  通过 {v['passed']}  失败 {v['failed']}")
        print(f"  准确率  {v['accuracy']:.2%}  门禁阈值 {v['threshold']:.2%}  "
              f"{'PASS' if v['gate_passed'] else 'REJECT'}")
        m = v.get("metrics") or {}
        print(f"  水印残留率 {m.get('watermark_residue_rate')}   "
              f"选项修复率 {m.get('option_fix_rate')}   结构达标率 {m.get('structure_pass_rate')}")
        print(f"  各项通过率 {v.get('check_summary')}")
        print(f"  写文件   {result.get('written', False)}   目录 {result.get('out_dir')}")
    print("=" * 62)


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数。"""
    args = build_parser().parse_args(argv)

    if args.selftest:
        return 1 if selftest() else 0
    if args.show_samples:
        show_samples(args.show_samples, args.db)
        return 0

    try:
        result = run_etl(
            db_path=args.db, out_dir=args.out_dir, limit=args.limit,
            dry_run=args.dry_run, emit_ddl=args.emit_ddl, verify_only=args.verify_only,
            seed=args.seed, threshold=args.threshold, sample_size=args.sample_size,
        )
    except FileNotFoundError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    print_report(result)
    v = result.get("verification") or {}
    if args.enforce_gate and not v.get("gate_passed", False):
        print("[门禁] 准确率未达阈值，拒绝进入下一阶段。", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
