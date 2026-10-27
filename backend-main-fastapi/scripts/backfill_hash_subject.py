# -*- coding: utf-8 -*-
"""零破坏回填（backfill-only，只填 NULL，不改不删已有值）。

三件事：
  1. documents.content_hash + size：对盘上真实文件算 SHA256/字节数
     （当前 0/705 有 hash → 哈希去重机制完全失效；size 缺 135）
  2. quiz_questions.subject_id：按 subjects.code / name 文本回填外键
     （当前仅 53/386 有外键，但 subject 文本 100% 可匹配 subjects 表）
  3. 副本文档检测（只报告不删除）：hash 相同 / 文件名 `_N` 后缀 + 同大小

用法::

    python scripts/backfill_hash_subject.py            # dry-run，打印计划
    python scripts/backfill_hash_subject.py --apply    # 落库
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

COPY_SUFFIX = re.compile(r"(_\d+)(?=\.[A-Za-z0-9]+$)")  # 文件名里的 _1 / _2 副本后缀


def sha256_of(path: Path) -> int | None:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def backfill_documents(db, apply: bool) -> list[tuple[str, str]]:
    print("\n== 1) documents.content_hash / size 回填 ==")
    rows = db.execute(text(
        "select id, file_path, file_name, content_hash, size from documents "
        "where content_hash is null or size is null order by id"
    )).all()
    print(f"  待回填 {len(rows)} 行")

    plan: list[tuple[int, str, int]] = []   # (doc_id, hash, size)
    missing: list[str] = []
    for doc_id, fp, fname, _h, _sz in rows:
        p = Path(fp) if fp else None
        if not p or not p.is_file():
            missing.append(f"doc={doc_id} {fname} path={fp}")
            continue
        digest = sha256_of(p)
        if digest is None:
            missing.append(f"doc={doc_id} {fname} 读取失败 path={fp}")
            continue
        plan.append((doc_id, digest, p.stat().st_size))
        if len(plan) % 100 == 0:
            print(f"    ... 已计算 {len(plan)}")

    print(f"  可回填 {len(plan)} 行；盘上缺文件/读失败 {len(missing)} 行（跳过）")
    for m in missing[:12]:
        print(f"    [缺文件] {m[:120]}")
    if len(missing) > 12:
        print(f"    ... 共 {len(missing)} 条")

    if apply and plan:
        db.execute(text(
            "update documents set content_hash=:h, size=:s where id=:i"
        ), [{"h": h, "s": s, "i": i} for i, h, s in plan])
        db.commit()
        print(f"  [APPLIED] 已写入 {len(plan)} 行")
    elif plan:
        print("  [DRY-RUN] 未落库（--apply 执行）")

    # 副本检测：hash 相同
    dup_by_hash = db.execute(text("""
        select content_hash, count(*), string_agg(id::text, ',') from documents
        where content_hash is not null group by 1 having count(*)>1 order by 2 desc
    """)).all()
    print(f"\n  副本检测 · 同 hash 组数: {len(dup_by_hash)}")
    names = {r[0]: r[1] for r in db.execute(text(
        "select id, file_name from documents"))}
    for h, n, ids in dup_by_hash[:15]:
        sample = [names.get(int(i), "?") for i in ids.split(",")]
        print(f"    x{n} ids={ids} files={sample}")

    # 副本检测：文件名去掉 _N 后缀后相同 + size 相同（hash 缺失时的兜底）
    by_key: dict[tuple[str, int], list[int]] = defaultdict(list)
    for doc_id, fp, fname, _h, sz in rows:
        if not fname or sz is None:
            continue
        norm = COPY_SUFFIX.sub("", fname)
        by_key[(norm, sz)].append(doc_id)
    cand = {k: v for k, v in by_key.items() if len(v) > 1}
    print(f"\n  副本检测 · 同(规范名+大小)候选组数: {len(cand)}")
    for (norm, sz), ids in list(cand.items())[:15]:
        print(f"    x{len(ids)} {norm[:60]} size={sz} ids={ids}")

    return [(h, ids) for _h, _n, ids in ((r[0], r[1], r[2]) for r in dup_by_hash)]


def backfill_subject_id(db, apply: bool) -> None:
    print("\n== 2) quiz_questions.subject_id 外键回填 ==")
    subjects = db.execute(text("select id, code, name from subjects")).all()
    by_code = {r[1]: r[0] for r in subjects if r[1]}
    by_name: dict[str, list[int]] = defaultdict(list)
    for sid, _code, name in subjects:
        if name:
            by_name[name].append(sid)

    # 已有外键的题目，核对文本是否一致（只报告）
    mismatch = db.execute(text("""
        select count(*) from quiz_questions q join subjects s on s.id=q.subject_id
        where q.subject is not null and q.subject<>s.name and q.subject<>s.code
    """)).scalar()
    print(f"  已有外键但文本与科目不一致: {mismatch} 行（不动，仅报告）")

    rows = db.execute(text(
        "select id, subject from quiz_questions where subject_id is null"
    )).all()
    plan: list[tuple[int, int]] = []
    ambiguous: list[tuple[int, str]] = []
    unmatched: list[tuple[int, str]] = []
    for qid, subj in rows:
        if not subj:
            unmatched.append((qid, "(空)"))
            continue
        if subj in by_code:
            plan.append((qid, by_code[subj]))
            continue
        cands = by_name.get(subj, [])
        if len(cands) == 1:
            plan.append((qid, cands[0]))
        elif len(cands) > 1:
            ambiguous.append((qid, subj))
        else:
            unmatched.append((qid, subj))

    print(f"  待回填 {len(rows)} 行 → 可回填 {len(plan)}，"
          f"歧义(同名多科目) {len(ambiguous)}，无匹配 {len(unmatched)}")
    for qid, s in ambiguous[:8]:
        print(f"    [歧义] qid={qid} subject={s!r}")
    for qid, s in unmatched[:8]:
        print(f"    [无匹配] qid={qid} subject={s!r}")

    if apply and plan:
        db.execute(text(
            "update quiz_questions set subject_id=:s where id=:i and subject_id is null"
        ), [{"s": s, "i": i} for i, s in plan])
        db.commit()
        print(f"  [APPLIED] 已写入 {len(plan)} 行")
    elif plan:
        print("  [DRY-RUN] 未落库（--apply 执行）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正落库（默认 dry-run）")
    args = ap.parse_args()

    from database import SessionLocal

    db = SessionLocal()
    try:
        print(f"模式: {'APPLY 落库' if args.apply else 'DRY-RUN 只读'}")
        backfill_documents(db, args.apply)
        backfill_subject_id(db, args.apply)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
