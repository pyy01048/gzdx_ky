# -*- coding: utf-8 -*-
"""重复文档合并 · 只读检视（--inspect）。

对 content_hash 相同的文档组输出：
  1. 组内每行的规模（chunks/vectors/KP/题目溯源/错误链路）
  2. 数据库真实 FK 级联规则（pg_constraint.confdeltype）
  3. 迁移计划预览：KP 镜像映射、题目溯源重定向所需的一切

用法::

    python scripts/dedup_doc_kp.py --inspect
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import bindparam, text  # noqa: E402

DEL_RULE = {"c": "CASCADE", "n": "SET NULL", "r": "RESTRICT", "a": "NO ACTION", "N": "SET DEFAULT"}


def inspect(db) -> None:
    groups = db.execute(text("""
        select content_hash, count(*) from documents
        group by 1 having count(*)>1 order by 2 desc
    """)).all()
    print(f"== 同 hash 文档组: {len(groups)} 组 ==")

    doc_ids = []
    for gh, n in groups:
        rows = db.execute(text("""
            select id, file_name, file_path, chunk_count, knowledge_point_count,
                   coalesce(index_status::text,''), coalesce(source_kind::text,''),
                   length(coalesce(canonical_content,'')) as canon_len
            from documents where content_hash=:h order by id
        """), {"h": gh}).all()
        ids = [r[0] for r in rows]
        doc_ids.extend(ids)
        print(f"\n组 x{n}  hash={gh[:16]}…")
        for r in rows:
            print(f"  doc={r[0]:>4} chunks={r[3]:>3} kp_count={r[4]:>2} "
                  f"index={r[5]:<8} canon={r[6]:>7} {r[1][:58]}")

        # 每个成员挂载的数据
        for rid in ids:
            chunks = db.execute(text(
                "select count(*) from knowledge_chunks where document_id=:d"),
                {"d": rid}).scalar()
            vecs = db.execute(text(
                "select count(*) from chunk_vectors where document_id=:d"),
                {"d": rid}).scalar()
            kps = db.execute(text(
                "select count(*) from knowledge_points where document_id=:d"),
                {"d": rid}).scalar()
            qs = db.execute(text(
                "select count(*) from quiz_questions where origin_document_id=:d"),
                {"d": rid}).scalar()
            err = db.execute(text(
                "select count(*) from error_knowledge_links where document_id=:d"),
                {"d": rid}).scalar()
            qkl = db.execute(text("""
                select count(*)
                from question_knowledge_links l
                join knowledge_points k on k.id=l.knowledge_point_id
                where k.document_id=:d
            """), {"d": rid}).scalar()
            print(f"    doc={rid}: chunks={chunks} vectors={vecs} kps={kps} "
                  f"题目溯源={qs} 错误链={err} 题目-知识链(经由KP)={qkl}")

        # KP 镜像：keep-candidate 与其他成员的同名对照 + 非/镜像标记
        keep = rows[0][0]
        for r in rows[1:]:
            dup = r[0]
            same = db.execute(text("""
                select k.id, m.id
                from knowledge_points k
                join knowledge_points m
                  on m.subject=k.subject and m.name=k.name and coalesce(m.chapter,'')=coalesce(k.chapter,'')
                 and m.document_id=:keep and k.document_id=:dup
                where k.document_id=:dup
            """), {"keep": keep, "dup": dup}).all()
            kps_dup_total = db.execute(text(
                "select count(*) from knowledge_points where document_id=:d"), {"d": dup}).scalar()
            print(f"    doc={dup} vs keep={keep}: 镜像KP {len(same)}/{kps_dup_total}")
            pair_ids = [s[0] for s in same]
            uniq = db.execute(text("""
                select id, name, coalesce(chapter,''), question_count
                from knowledge_points where document_id=:d order by id
            """), {"d": dup}).all()
            for kid, name, chap, qn in uniq:
                mark = "镜像→合并" if kid in pair_ids else "非镜像→重定向"
                print(f"      kp={kid:>5} qn={qn} [{mark}] {chap[:20]}:{name[:24]}")

    # —— FK 真实级联规则 ——
    print("\n== 引用 documents / knowledge_chunks / knowledge_points 的真实 FK 删除规则 ==")
    fks = db.execute(text("""
        select c.conname, c.conrelid::regclass as child, c.confrelid::regclass as parent,
               c.confdeltype
        from pg_constraint c
        where c.contype='f'
          and c.confrelid in ('documents'::regclass,'knowledge_chunks'::regclass,'knowledge_points'::regclass)
        order by c.confrelid, c.conname
    """)).all()
    for name, child, parent, rule in fks:
        print(f"  {child} → {parent}  ondelete={DEL_RULE.get(rule, rule)}  ({name})")


BACKUP_SUFFIX = "_dedup_backup_20261021"


def apply(db) -> None:
    groups = db.execute(text("""
        select content_hash, count(*) from documents
        group by 1 having count(*)>1 order by 2 desc
    """)).all()
    total_docs = total_chunks = total_vecs = total_kp = 0
    plan: list[dict] = []

    # —— 1) 只读定计划 ——
    for gh, n in groups:
        ids = [r[0] for r in db.execute(text(
            "select id from documents where content_hash=:h order by id"), {"h": gh}).all()]
        keep, dups = ids[0], ids[1:]
        merged: list[tuple[int, int]] = []       # (dup_kp, keep_kp)
        redirected: list[int] = []
        kps = db.execute(text(
            "select id, name, chapter, subject from knowledge_points "
            "where document_id in :ids"
        ).bindparams(bindparam("ids", expanding=True)), {"ids": tuple(dups)}).all()
        for kid, name, chap, subj in kps:
            fp = db.execute(text("""
                select id from knowledge_points
                where document_id=:k and name=:n
                  and coalesce(chapter,'')=coalesce(:c,'')
                  and coalesce(subject,'')=coalesce(:s,'')
            """), {"k": keep, "n": name, "c": chap or "", "s": subj or ""}).first()
            (merged.append((kid, fp[0])) if fp else redirected.append(kid))
        plan.append({"hash": gh, "keep": keep, "dups": dups, "merged": merged,
                     "redirected": redirected})

    # —— 2) 校验：删除集上不得挂题干溯源（有则中止） ——
    risk: list[str] = []
    for p in plan:
        qs = db.execute(text(
            "select count(*) from quiz_questions where origin_document_id = any(:ids)"
        ), {"ids": list(p["dups"])}).scalar()
        if qs:
            risk.append(f"doc{p['dups']} 挂题目溯源 {qs}")
    if risk:
        print("发现危险数据，不执行：", risk)
        return

    # —— 3) 备份（drop+create 分开执行） ——
    all_dups = [d for p in plan for d in p["dups"]]
    all_merged_kp = [m[0] for p in plan for m in p["merged"]]
    jobs = [
        ("documents", "id", all_dups),
        ("knowledge_chunks", "document_id", all_dups),
        ("chunk_vectors", "document_id", all_dups),
        ("knowledge_points", "id", all_merged_kp),
    ]
    for tname, col, rowids in jobs:
        if not rowids:
            continue
        db.execute(text(f"drop table if exists {tname}{BACKUP_SUFFIX}"))
        db.execute(text(
            f"create table {tname}{BACKUP_SUFFIX} as "
            f"select * from {tname} where {col} = any(:ids)"
        ), {"ids": rowids})
    print("备份完成: " + ", ".join(t + BACKUP_SUFFIX for t, _, r in jobs if r))

    # —— 4) 迁移：非镜像 KP 重定向 + 镜像 KP 题链转移 ——
    for p in plan:
        for kid in p["redirected"]:
            db.execute(text(
                "update knowledge_points set document_id=:k where id=:i"),
                {"k": p["keep"], "i": kid})
        for src, tgt in p["merged"]:
            db.execute(text("""
                update question_knowledge_links
                set knowledge_point_id=:t where knowledge_point_id=:s
            """), {"t": tgt, "s": src})

    # —— 5) 删镜像 KP（重定向后其题链已转移/为 0） ——
    if all_merged_kp:
        db.execute(text(
            "delete from knowledge_points where id = any(:ids)"), {"ids": all_merged_kp})

    # —— 6) 删文档（CASCADE 清 chunks / vectors） ——
    db.execute(text("delete from documents where id = any(:ids)"), {"ids": all_dups})

    # —— 7) 修正 keep 文档的 KP 统计 ——
    for p in plan:
        real = db.execute(text(
            "select count(*) from knowledge_points where document_id=:k"),
            {"k": p["keep"]}).scalar()
        db.execute(text(
            "update documents set knowledge_point_count=:c where id=:i"),
            {"c": real, "i": p["keep"]})
        print(f"keep=doc{p['keep']}: 删文档{len(p['dups'])} 镜像KP{len(p['merged'])} "
              f"重定向KP{len(p['redirected'])} → knowledge_point_count={real}")
        total_docs += len(p["dups"])
        total_kp += len(p["merged"])
    total_chunks = int(db.execute(text(
        "select count(*) from knowledge_chunks_dedup_backup_20261021")).scalar())
    total_vecs = int(db.execute(text(
        "select count(*) from chunk_vectors_dedup_backup_20261021")).scalar())
    db.commit()
    print(f"\n[APPLIED] 删文档 {total_docs}（级联 chunks {total_chunks} / vectors {total_vecs}），"
          f"镜像合并 KP {total_kp}；盘上重复文件未动（可人工清理）")


def main() -> int:
    from database import SessionLocal

    db = SessionLocal()
    try:
        if "--apply" in sys.argv:
            apply(db)
        else:
            print("(dry-run，加 --apply 执行)\n")
            inspect(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
