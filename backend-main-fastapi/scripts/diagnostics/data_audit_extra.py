# -*- coding: utf-8 -*-
"""数据审计 · 重复定性的三个补充细节（--extra）。

1. documents 134/135 是什么（知识点 x7 重复的根源）
2. quiz id=319/320/321 同题干不同答案 → options 是否不同
3. readme_counts.py 的 questions 表口径问题
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402


def main() -> int:
    from database import SessionLocal

    db = SessionLocal()
    try:
        print("== documents 134 / 135 ==")
        for r in db.execute(text(
            "select id, file_name, file_path, content_hash, size, chunk_count, doc_type, subject "
            "from documents where id in (134,135)")):
            print(f"  id={r[0]} name={r[1]!r}")
            print(f"       path={r[2]}")
            print(f"       hash={r[3]} size={r[4]} chunks={r[5]} type={r[6]} subj={r[7]!r}")

        print("\n== quiz 319/320/321（同题干 答案 A/A/C）options 对比 ==")
        for r in db.execute(text(
            "select id, answer, option_count, options, analysis, difficulty "
            "from quiz_questions where id in (319,320,321) order by id")):
            opts = (r[3] or "")[:220]
            print(f"  id={r[0]} ans={r[1]!r} opt_count={r[2]} diff={r[5]!r}")
            print(f"       options={opts!r}")
            print(f"       analysis={(r[4] or '')[:80]!r}")

        print("\n== documents content_hash 填充率（去重键是否可用）==")
        for r in db.execute(text(
            "select count(*) total, count(content_hash) with_hash, "
            "count(*) filter (where size is null) no_size from documents")):
            print(f"  总数={r[0]} 有hash={r[1]} 无size={r[2]}"
                  + ("  ⚠ hash大面积缺失→哈希去重不可用" if r[1] < r[0] else ""))

        print("\n== 其余重复题的题干长度 + 选项是否一致（伪重复判定）==")
        for content in db.execute(text(
            "select content from quiz_questions group by 1 having count(*)>1 limit 12")):
            c = content[0]
            rows = db.execute(text(
                "select id, answer, option_count, options::text from quiz_questions "
                "where content=:c order by id"), {"c": c}).all()
            opts_set = {r[3] for r in rows}
            ans_set = {r[1] for r in rows}
            verdict = ("选项全同→真重复" if len(opts_set) == 1 else "选项不同→不同题(伪重复)")
            print(f"  题干长={len(c):>4} ids={[r[0] for r in rows]} 答案={sorted(ans_set)} "
                  f"选项集={len(opts_set)} → {verdict}  {c[:30]!r}")

        print("\n== readme_counts.py 实际跑一遍 ==")
        db.close()
        import subprocess
        r = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "readme_counts.py")],
            capture_output=True, encoding="utf-8", errors="replace",
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        print(r.stdout or r.stderr)
        return 0
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
