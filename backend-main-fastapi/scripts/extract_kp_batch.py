"""对有正文的 documents批量调用后端真实模型抽取知识点。

必须真实跑模型：逐篇 POST /api/documents/{id}/extract-knowledge-points，
抽取后立即清洗噪声（复用 clean_knowledge_points 的判定），最后按主分类归一 subject。

用法：
    python scripts/extract_kp_batch.py --limit 10
    python scripts/extract_kp_batch.py --ids 2094,2085
    python scripts/extract_kp_batch.py --all
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from typing import List

import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clean_knowledge_points import _KEEP_SHORT, _RE_ONLY_NUM, _RE_ONLY_PUNCT, \
    _RE_ONLY_SEQ, _RE_SUBSCRIPT, _RE_CJK_MIN, _SUBJECT_MAP  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
API = "http://127.0.0.1:8000"

MIN_CHARS = 2000


def is_noise(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return True
    if n in _KEEP_SHORT:
        return False
    if _RE_ONLY_NUM.match(n) or _RE_ONLY_SEQ.match(n) or _RE_ONLY_PUNCT.match(n):
        return True
    if _RE_SUBSCRIPT.match(n) and not _RE_CJK_MIN.search(n):
        return True
    if len(n) <= 2 and not _RE_CJK_MIN.search(n):
        return True
    # OCR 崩坏长串：几乎无中文且含大量下划线/花括号
    if len(n) > 6 and not _RE_CJK_MIN.search(n) and n.count("{") + n.count("}") >= 2:
        return True
    return False


def extract(doc_id: int, timeout: int = 1800) -> dict:
    req = urllib.request.Request(
        f"{API}/api/documents/{doc_id}/extract-knowledge-points",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        import json
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--ids", type=str, default=None, help="逗号分隔 doc_id")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--skip-has", action="store_true",
                    help="跳过已有知识点的文档")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")

    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
        rows = [(i,) for i in ids]
        qmarks = ",".join("?" * len(ids))
        meta = dict(con.execute(
            f"SELECT id, file_name FROM documents WHERE id IN ({qmarks})",
            ids).fetchall())
    else:
        cond = ("subject_source='ima' AND file_type IN ('pdf','word') "
                "AND content IS NOT NULL AND length(content)>=?")
        rows = con.execute(
            f"SELECT id, file_name, length(content) FROM documents "
            f"WHERE {cond} ORDER BY (content_type='知识') DESC, id",
            (MIN_CHARS,)).fetchall()
        if args.skip_has:
            rows = [r for r in rows if not con.execute(
                "SELECT 1 FROM knowledge_points WHERE document_id=? LIMIT 1",
                (r[0],)).fetchone()]
        if not args.all:
            rows = rows[: args.limit]

    print(f"待抽取 {len(rows)} 篇\n")
    total_new = 0
    total_noise = 0
    ok_cnt = 0
    fail: List[str] = []

    for row in rows:
        doc_id = row[0]
        fname = row[1] if len(row) > 1 else str(doc_id)
        try:
            res = extract(doc_id)
        except Exception as e:  # noqa: BLE001
            msg = str(e)[:120]
            fail.append(f"{doc_id}: {msg}")
            print(f"✗ {doc_id} {fname[:30]} → {msg}")
            continue

        kps = res.get("knowledge_points") or []
        ids = [k["id"] for k in kps if not is_noise(k.get("name", ""))]
        noise_ids = [k["id"] for k in kps if is_noise(k.get("name", ""))]

        if noise_ids:
            con.execute(
                f"DELETE FROM knowledge_points WHERE id IN "
                f"({','.join('?' * len(noise_ids))})", noise_ids)
        for k in kps:
            if k["id"] in noise_ids:
                continue
            new_sub = _SUBJECT_MAP.get((k.get("subject") or "").strip())
            if new_sub:
                con.execute("UPDATE knowledge_points SET subject=? WHERE id=?",
                            (new_sub, k["id"]))
        con.commit()

        ok_cnt += 1
        total_new += len(ids)
        total_noise += len(noise_ids)
        print(f"✓ {doc_id} {fname[:30]} 抽{res.get('extracted')} "
              f"留{len(ids)} 删噪{len(noise_ids)}")
        time.sleep(1)

    print(f"\n完成: 成功{ok_cnt} 新增知识点{total_new} 清理噪声{total_noise} "
          f"失败{len(fail)}")
    for f in fail[:10]:
        print("  ", f)
    print("库中知识点总数:",
          con.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
