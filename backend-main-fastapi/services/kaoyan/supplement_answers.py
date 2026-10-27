# -*- coding: utf-8 -*-
"""C6: 真题答案/解析批量补充 — 用 ModelGateway（本地 ollama 优先）为缺失解析的题目生成解析。

策略：
1. 选取 analysis 缺失或过短（<5 字）的题目
2. 逐条调用 ModelGateway.chat 生成解析（prefer=local，本地 qwen3:8b）
3. 清洗 <think> 噪音，写入 analysis + ai_generated=True + quality='B'(AI生成未人工校验)
4. 分批 commit，断点式记录（可续跑），输出汇总

使用：python services/kaoyan/supplement_answers.py [--limit N] [--resume]
"""
import logging
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from sqlalchemy import func
from database import SessionLocal
from models import QuizQuestion
from services.model_gateway import ModelGateway

# 断点状态同样不放包目录：部署包夹带过期 checkpoint 会让任务"假装已完成"。
# 与 spider_yz 保持同一约定：data/spider_state/ 运行时目录。
STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "spider_state" / "supplement_checkpoint.json"


def clean_answer(text: str) -> str:
    """去除 <think> 块与多余空白。"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text.strip(), flags=re.M)
    return text.strip()


def build_prompt(q) -> str:
    content = (q.content or "").strip()
    options = q.options or {}
    opt_text = ""
    if isinstance(options, dict) and options:
        opt_text = "\n".join(f"{k}. {v}" for k, v in options.items())
    elif options:
        opt_text = str(options)
    known = f"（已知答案：{q.answer}）" if q.answer else ""
    return (
        f"请为下面这道考研{ q.subject or '未知' }科目题目给出答案解析，中文简洁，80字以内，"
        f"说明解题思路与正确选项理由。{known}\n"
        f"题目：{content}\n{opt_text}\n仅输出解析正文，不要输出多余说明。"
    )


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as _exc:  # noqa: BLE001
            # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
            # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
            logging.getLogger(__name__).warning(
                '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
            )
    return {"done_ids": []}


def save_state(st):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多处理条数（0=全量）")
    ap.add_argument("--resume", action="store_true", help="跳过已完成记录")
    args = ap.parse_args()

    db = SessionLocal()
    gw = ModelGateway()
    try:
        query = db.query(QuizQuestion).filter(
            (QuizQuestion.analysis.is_(None))
            | (QuizQuestion.analysis == "")
            | (func.length(QuizQuestion.analysis) < 5)
        ).order_by(QuizQuestion.id)
        total = query.count()
        print(f"[C6] 待补解析题目：{total}", flush=True)
        if args.limit and args.limit < total:
            total = args.limit
            print(f"[C6] 本次限额处理：{total}", flush=True)

        st = load_state() if args.resume else {"done_ids": []}
        ok, fail = 0, 0
        t0 = time.time()
        processed = 0
        for q in query.all():
            if processed >= total:
                break
            if q.id in st["done_ids"]:
                continue
            processed += 1
            try:
                resp = gw.chat(
                    build_prompt(q),
                    subject=q.subject or "通用",
                    task="general",
                    system_prompt="你是考研专业课解析助手，直接给出简洁准确的答案解析。",
                    prefer="local",
                )
                ans = clean_answer(resp.get("answer") or "")
                if not ans or resp.get("error"):
                    print(f"[C6] 第{processed}题(id={q.id}) 失败: {resp.get('error')}", flush=True)
                    fail += 1
                    continue
                q.analysis = ans
                q.ai_generated = True
                if q.quality in (None, "C"):
                    q.quality = "B"
                db.add(q)
                ok += 1
            except Exception as e:
                print(f"[C6] 第{processed}题(id={q.id}) 异常: {e}", flush=True)
                fail += 1
            st["done_ids"].append(q.id)
            if ok % 10 == 0:
                db.commit()
                save_state(st)
                print(f"[C6] 进度 {ok}/{total} 成功，失败 {fail}，耗时 {int(time.time()-t0)}s", flush=True)
        db.commit()
        save_state(st)
        print(f"[C6] 完成：成功 {ok} 条，失败 {fail} 条，耗时 {int(time.time()-t0)}s", flush=True)
        print(f"[C6] 断点文件：{STATE_FILE}", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
