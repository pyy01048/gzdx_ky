# -*- coding: utf-8 -*-
"""按修正后的分类器重新标注全部文档的学科。

背景：旧分类器把**文档类型词**（精讲册/逐词逐句/阅读…）当科目信号，
导致 187 篇电子技术资料被误标为「英语」。分类器已修，
这里把存量数据按新规则重刷一遍。

安全：先备份数据库；只改 documents.subject 与 knowledge_chunks.subject；
输出前后对比供核对。
"""
import collections
import shutil
import sqlite3
import sys
import datetime

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from services import taxonomy
from services.kb_service import classify_subject_confidence

DB = r"data\kaoyan.db"
BACKUP = DB + ".bak-subject-reclass"


def main(apply: bool = False) -> int:
    shutil.copy2(DB, BACKUP)
    print(f"已备份: {BACKUP}\n")

    db = sqlite3.connect(DB)
    rows = db.execute("select id, file_name, subject, content from documents").fetchall()
    print(f"待重新标注 {len(rows)} 篇\n")

    before = collections.Counter(r[2] or "(空)" for r in rows)
    changes = []
    skipped_lowconf = 0
    after = collections.Counter()

    for did, name, old, content in rows:
        new, confident = classify_subject_confidence(name or "", content or "")
        new = taxonomy.normalize_subject(new)
        old_n = taxonomy.normalize_subject(old or "")

        # 只采用**高置信**结果：低置信说明只是靠"真题/试卷"兜底，
        # 把它写回去会把原本合理的标注改成臆测值，越改越乱。
        # 但**归一化**必须始终生效 —— 否则历史别名（"电子技术基础"）
        # 会因为"低置信"被原样保留下来。
        if not confident and new != old_n:
            skipped_lowconf += 1
            new = old_n
        after[new] += 1
        if new != (old or ""):      # 与**原始值**比较，别名也能被改掉
            changes.append((did, name, old, new))

    print("=== 标注前 ===")
    for s, c in before.most_common():
        print(f"  {s:<24} {c}")
    print("\n=== 标注后 ===")
    for s, c in after.most_common():
        print(f"  {s:<24} {c}")

    print(f"\n=== 需要变更 {len(changes)} 篇（另有 {skipped_lowconf} 篇因置信不足保持原样）===")
    by_pair = collections.Counter((o or "(空)", n) for _, _, o, n in changes)
    for (o, n), c in by_pair.most_common():
        print(f"  {o:<18} → {n:<22} {c} 篇")

    print("\n  前 15 条明细：")
    for did, name, old, new in changes[:15]:
        print(f"    id={did:<6} {(old or '(空)'):<14} → {new:<16} {str(name)[:44]}")

    if not apply:
        print("\n[预览模式] 未写入。加 --apply 执行。")
        db.close()
        return 0

    # 写入
    for did, _name, _old, new in changes:
        db.execute("update documents set subject=? where id=?", (new, did))
        db.execute("update knowledge_chunks set subject=? where document_id=?", (new, did))
    db.commit()

    n_doc = db.execute("select count(*) from documents").fetchone()[0]
    n_chunk = db.execute("select count(*) from knowledge_chunks").fetchone()[0]
    print(f"\n已写入：documents {n_doc} 篇 / knowledge_chunks {n_chunk} 块")
    print("已同步 knowledge_chunks.subject（保持与文档一致）")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(apply="--apply" in sys.argv))
