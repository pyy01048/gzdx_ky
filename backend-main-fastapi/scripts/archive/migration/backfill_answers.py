# -*- coding: utf-8 -*-
"""真题答案/解析批量回填（P0-1，2026-10）。

背景：quiz_questions 共 9171 题，answer 覆盖仅 33%。真题套卷（paper 非空）中
约 1029 题缺答案，其中贵大/贵州大学真题缺 587 题——这是「可练不可判」的主因。

做法：复用 qbank_builder.generate_answer_prompt（多角色互校提示词）+
ModelGateway（本地 Ollama 优先）生成答案与解析，写回 quiz_questions.answer/analysis，
并诚实标注 ai_generated=True、verified=False（人工/A6 交叉校验确认前不冒充真题原答案）。

优先级：贵大/贵州大学真题 → 其他真题套卷（按题号顺序）。
幂等：只处理缺答案的题，重跑自动跳过已补的，天然支持断点续跑。

用法：
    python scripts/backfill_answers.py --dry-run          # 预览本次将处理的题
    python scripts/backfill_answers.py --limit 20         # 补 20 题
    python scripts/backfill_answers.py --limit 200        # 大批量（建议后台跑）
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

from database import SessionLocal  # noqa: E402
from models import QuizQuestion   # noqa: E402
from services import qbank_builder  # noqa: E402


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def _strip_think(text: str) -> str:
    """剥离 qwen3 内联思考块（网关路径下 thinking 会泄漏进 content，见 services/llm_output.py）。

    同时处理未闭合的尾部 <think>：思考吃光输出预算时只剩半截思考，剥掉后为空，
    由调用方按失败处理，避免把思维链当答案写库。
    """
    t = _THINK_RE.sub("", text or "")
    if "<think>" in t:  # 未闭合：取 <think> 之前的正文
        t = t.split("<think>", 1)[0]
    return t.strip()


def _extract_json(text: str) -> dict:
    """从模型输出抽 JSON（先剥思考块；容忍 markdown 包裹与尾部逗号）。"""
    t = _strip_think(text)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return {}
    raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
        except Exception:
            return {}


def pick_targets(db, limit: int):
    """选目标题：贵大真题优先，其余真题次之；只取缺答案的。"""
    missing = (QuizQuestion.answer.is_(None)) | (QuizQuestion.answer == "")
    gui = QuizQuestion.paper.like("%贵大%") | QuizQuestion.paper.like("%贵州大学%")
    q1 = (
        db.query(QuizQuestion)
        .filter(QuizQuestion.paper.isnot(None), gui, missing)
        .order_by(QuizQuestion.paper, QuizQuestion.question_no)
        .limit(limit)
        .all()
    )
    if len(q1) < limit:
        got = {x.id for x in q1}
        q2 = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.paper.isnot(None), missing, ~QuizQuestion.id.in_(got))
            .order_by(QuizQuestion.paper, QuizQuestion.question_no)
            .limit(limit - len(q1))
            .all()
        )
        return q1 + q2
    return q1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20, help="本次处理的题数上限")
    ap.add_argument("--dry-run", action="store_true", help="只列出将处理的题，不调用模型")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        targets = pick_targets(db, args.limit)
        print(f"目标题数: {len(targets)}（优先贵大/贵州大学真题）")
        if args.dry_run:
            for q in targets:
                print(f"  id={q.id:<6} [{q.question_type or '?':<7}] {q.paper} #{q.question_no}  {(q.content or '')[:40]}")
            return 0

        from services.model_gateway import get_gateway

        gw = get_gateway()
        ok = failed = 0
        t0 = time.time()
        fails = []
        for i, q in enumerate(targets, 1):
            # 选项只传选择题：填空/简答的 options 常为 OCR 噪声，会误导模型
            qtype = q.question_type or "single"
            opts = q.options if qtype in ("single", "multiple") else None
            prompt = qbank_builder.generate_answer_prompt({
                "content": q.content,
                "options": opts,
                "question_type": q.question_type,
                "subject": q.subject,
            })
            try:
                resp = gw.chat(prompt, subject=None, task="json_gen", prefer="local")
                data = _extract_json(resp.get("answer") or "")
                ans = (data.get("answer") or "").strip()
                ana = (data.get("analysis") or "").strip()
                if not ans and not ana:
                    raise ValueError("模型输出无有效答案")
                # OCR 残缺题（如只剩电路图参数"1KΩ 100Ω"）模型会自认无法作答，
                # 这种答案写库只会污染题库，按失败跳过，留待人工处理
                if re.search(r"无法作答|无法确定|信息不完整|题目不完整|无法回答", ans + ana):
                    raise ValueError(f"模型判定题目不可答: {ans[:40]}")
                q.answer = ans[:2000] or None
                q.analysis = ana[:3000] or None
                q.ai_generated = True
                q.verified = False
                ok += 1
                dt = time.time() - t0
                print(f"[{i}/{len(targets)}] ok id={q.id} {q.paper}#{q.question_no} "
                      f"ans={ans[:30]!r} ({dt:.0f}s 累计, 均 {dt/i:.1f}s/题)")
            except Exception as e:
                failed += 1
                fails.append({"id": q.id, "err": str(e)[:120]})
                print(f"[{i}/{len(targets)}] FAIL id={q.id}: {str(e)[:100]}")
            db.commit()  # 每题一提交：断点续跑不丢进度

        report = {
            "ok": ok, "failed": failed, "seconds": round(time.time() - t0, 1),
            "avg_sec_per_q": round((time.time() - t0) / max(1, len(targets)), 2),
            "fails": fails,
        }
        out = os.path.join(os.environ.get("TEMP_DIR", BASE_DIR), "backfill_answers_result.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n完成: 成功 {ok} / 失败 {failed}，用时 {report['seconds']}s "
              f"(均 {report['avg_sec_per_q']}s/题)。报告: {out}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
