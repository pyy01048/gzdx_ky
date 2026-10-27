# -*- coding: utf-8 -*-
"""知识库数据体检（只读，可反复执行）——verify_kb_data.py

对 documents / knowledge_chunks / chunk_vectors / 知识树做结构化核对，
输出 [通过]/[警告]/[不通过] 三档结论，供导入批次结束后验证数据正确性。

用法：
    python scripts/verify_kb_data.py            # 全量体检
    python scripts/verify_kb_data.py --samples  # 额外打印每类问题的样例明细

红线：本脚本绝不写库。
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402
from pipeline.config import pg_database_url  # noqa: E402

# 文件夹 → 允许的学科归因（None = 宽松，只展示分布供人工复核）
FOLDER_SUBJECT_ALLOW = {
    "数学": {"数学"},
    "英语": {"英语"},
    "政治": {"政治"},
    "数字电子技术": {"数字电子技术"},
    "模拟电子技术": {"模拟电子技术"},
    # 电子技术基础文件夹里混收数电/模电两类教材，按书归因即可
    "电子技术基础": {"数字电子技术", "模拟电子技术", "电路", "电路分析"},
    "专业课-贵大834": {"电子信息", "数字电子技术", "模拟电子技术", "电路",
                       "信号与系统", "通信原理", "电磁场与电磁波"},
    "专业课-其他": None,
    "未分类": None,
    "学科": None,
}

RESULTS: list[tuple[str, str, str]] = []  # (级别, 检查名, 说明)


def _flag(level: str, name: str, msg: str) -> None:
    RESULTS.append((level, name, msg))
    print(f"[{level}] {name}：{msg}")


def _cols(cur, table: str) -> set[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name=%s",
        (table,),
    )
    return {r[0] for r in cur.fetchall()}


def _one(cur, sql: str, params=None):
    cur.execute(sql, params or ())
    return cur.fetchone()[0]


def _rows(cur, sql: str, params=None, limit: int | None = None):
    sql = sql + (f" LIMIT {int(limit)}" if limit else "")
    cur.execute(sql, params or ())
    return cur.fetchall()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", action="store_true", help="打印问题样例明细")
    args = ap.parse_args()

    conn = psycopg.connect(pg_database_url())
    show_samples = args.samples

    with conn.cursor() as cur:
        cols = {t: _cols(cur, t) for t in
                ("documents", "knowledge_chunks", "chunk_vectors",
                 "knowledge_points", "subject_chapters")}

        # ============ 1. 总量 ============ #
        print("=" * 68)
        n_doc = _one(cur, "SELECT COUNT(*) FROM documents")
        n_chunk = _one(cur, "SELECT COUNT(*) FROM knowledge_chunks")
        n_vec = _one(cur, "SELECT COUNT(*) FROM chunk_vectors")
        n_kp = _one(cur, "SELECT COUNT(*) FROM knowledge_points")
        print(f"总量：documents={n_doc}  chunks={n_chunk}  vectors={n_vec}  kps={n_kp}")

        # ============ 2. 文档健康 ============ #
        print("=" * 68)
        st = dict(_rows(cur, "SELECT index_status, COUNT(*) FROM documents GROUP BY 1"))
        _flag("通过", "文档 index_status 分布", str(st))
        bad_idx = sum(v for k, v in st.items() if k not in ("indexed",))
        if bad_idx:
            _flag("警告", "非 indexed 文档", f"{bad_idx} 篇（多为无分块可检索的解析失败件，"
                                              f"应进入重解析/下线流程）")
        else:
            _flag("通过", "全部文档 indexed", "")

        empty_docs = _one(cur, "SELECT COUNT(*) FROM documents "
                               "WHERE COALESCE(content,'')='' OR LENGTH(COALESCE(content,''))<100")
        if empty_docs:
            _flag("不通过", "空/超短正文文档", f"{empty_docs} 篇（正文 <100 字，不应作为知识入库）")
            if show_samples:
                for r in _rows(cur, "SELECT id, file_name, LENGTH(COALESCE(content,'')) FROM documents "
                                    "WHERE COALESCE(content,'')='' OR LENGTH(COALESCE(content,''))<100 "
                                    "ORDER BY id LIMIT 10"):
                    print(f"    doc#{r[0]} {r[1][:50]} ({r[2]}字)")
        else:
            _flag("通过", "无空/超短正文文档", "")

        n_junk = (_one(cur, "SELECT COUNT(*) FROM documents WHERE is_junk")
                  if "is_junk" in cols["documents"] else 0)
        _flag("通过", "is_junk 文档", f"{n_junk} 篇")

        dup_groups = _rows(cur, "SELECT content_hash, COUNT(*) c, MIN(id) FROM documents "
                                "WHERE content_hash IS NOT NULL GROUP BY content_hash "
                                "HAVING COUNT(*)>1 ORDER BY c DESC LIMIT 10")
        dup_total = _one(cur, "SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM documents "
                              "WHERE content_hash IS NOT NULL GROUP BY content_hash HAVING COUNT(*)>1) t")
        if dup_groups:
            _flag("警告", "同正文重复文档", f"{dup_total} 篇冗余（{len(dup_groups)} 组），"
                                              f"待清洗阶段合并；top 组 {dup_groups[0][1]} 篇")
            if show_samples:
                for r in dup_groups[:5]:
                    print(f"    hash={str(r[0])[:16]}… x{r[1]} (min_id={r[2]})")
        else:
            _flag("通过", "无同正文重复文档", "")

        no_subject = _one(cur, "SELECT COUNT(*) FROM documents "
                               "WHERE COALESCE(subject,'')=''")
        if no_subject:
            _flag("警告", "未归学科文档", f"{no_subject} 篇（subject 为空）")
        else:
            _flag("通过", "全部文档已归学科", "")

        # ============ 3. 学科归因核对（文件夹 vs subject） ============ #
        print("=" * 68)
        rows = _rows(cur, """
            SELECT split_part(split_part(file_path, 'knowledge_base', 2), '\\', 2) AS folder,
                   COALESCE(NULLIF(subject,''),'(空)'), COUNT(*)
            FROM documents WHERE file_path LIKE %s
            GROUP BY 1, 2 ORDER BY 1, 3 DESC""", ('%knowledge_base%',))
        folder_rows = defaultdict(list)
        for folder, subj, cnt in rows:
            folder_rows[(folder or "").strip()].append((subj, cnt))
        mism = 0
        for folder, dist in sorted(folder_rows.items()):
            allow = FOLDER_SUBJECT_ALLOW.get(folder, None)
            if allow is None:
                _flag("通过", f"归因·{folder}", f"{dist}（宽松文件夹，分布供复核）")
                continue
            bad = [(s, c) for s, c in dist if s not in allow]
            if bad:
                mism += sum(c for _, c in bad)
                _flag("警告", f"归因·{folder}",
                      f"疑似错归 {bad}（允许：{sorted(allow)}）")
            else:
                _flag("通过", f"归因·{folder}", f"{dist}")
        if mism:
            _flag("警告", "归因错配总数", f"{mism} 篇（清单见上；纠偏应改 documents.subject 而非重导）")

        # ============ 4. 分块健康 ============ #
        print("=" * 68)
        orphan = _one(cur, "SELECT COUNT(*) FROM knowledge_chunks c "
                           "LEFT JOIN documents d ON c.document_id=d.id WHERE d.id IS NULL")
        _flag("通过" if orphan == 0 else "不通过", "孤儿分块（无归属文档）", f"{orphan} 条")

        empty_chunks = _one(cur, "SELECT COUNT(*) FROM knowledge_chunks "
                                 "WHERE COALESCE(text,'')='' OR LENGTH(COALESCE(text,''))<20")
        if empty_chunks:
            _flag("警告", "空/超短分块", f"{empty_chunks} 条（<20 字，检索价值低，清洗阶段处理）")
        else:
            _flag("通过", "无空/超短分块", "")

        if "subject" in cols["knowledge_chunks"]:
            subj_mismatch = _one(cur, "SELECT COUNT(*) FROM knowledge_chunks c "
                                      "JOIN documents d ON c.document_id=d.id "
                                      "WHERE COALESCE(c.subject,'')<>'' AND c.subject<>d.subject")
            _flag("通过" if subj_mismatch == 0 else "警告",
                  "分块/文档学科一致（name）", f"{subj_mismatch} 条不一致")
        if {"subject_id", "document_id"} <= cols["knowledge_chunks"] and "subject_id" in cols["documents"]:
            sid_mismatch = _one(cur, "SELECT COUNT(*) FROM knowledge_chunks c "
                                     "JOIN documents d ON c.document_id=d.id "
                                     "WHERE c.subject_id IS NOT NULL AND c.subject_id<>d.subject_id")
            _flag("通过" if sid_mismatch == 0 else "警告",
                  "分块/文档学科一致（subject_id）", f"{sid_mismatch} 条不一致")

        if "chunk_count" in cols["documents"]:
            drift = _rows(cur, """
                SELECT d.id, d.file_name, d.chunk_count, REAL_COUNT.c
                FROM documents d
                JOIN (SELECT document_id, COUNT(*) c FROM knowledge_chunks GROUP BY document_id) REAL_COUNT
                  ON REAL_COUNT.document_id=d.id
                WHERE d.chunk_count <> REAL_COUNT.c ORDER BY 1 LIMIT 10""")
            if drift:
                _flag("警告", "chunk_count 字段漂移", f"至少 {len(drift)} 篇与实际分块数不符（显示为 {drift[0][2]}、实际 {drift[0][3]}）")
            else:
                _flag("通过", "chunk_count 字段与实际一致", "")

        # ============ 5. 向量健康 ============ #
        print("=" * 68)
        if n_chunk:
            cover = _one(cur, "SELECT COUNT(DISTINCT chunk_id) FROM chunk_vectors")
            rate = cover / n_chunk
            _flag("通过" if rate > 0.999 else ("警告" if rate > 0.9 else "不通过"),
                  "向量覆盖率", f"{cover}/{n_chunk} = {rate:.2%}"
                                f"{('（增量灌库在导入结束后自动执行）' if rate < 0.999 else '')}")
            vec_orphan = _one(cur, "SELECT COUNT(*) FROM chunk_vectors v "
                                   "LEFT JOIN knowledge_chunks c ON v.chunk_id=c.id WHERE c.id IS NULL")
            _flag("通过" if vec_orphan == 0 else "不通过", "孤儿向量", f"{vec_orphan} 条")
            try:
                bad_dim = _one(cur, "SELECT COUNT(*) FROM chunk_vectors "
                                    "WHERE embedding_f32 IS NOT NULL AND vector_dims(embedding_f32)<>512")
                _flag("通过" if bad_dim == 0 else "不通过", "向量维度一致性", f"{bad_dim} 条非 512 维")
            except Exception:
                _flag("警告", "向量维度一致性", "vector_dims 不可用（pgvector 未就绪？）跳过")
            ver = _rows(cur, "SELECT model_version, COUNT(*) FROM chunk_vectors GROUP BY 1")
            _flag("通过" if len(ver) <= 1 else "警告", "向量模型版本", str(ver))

        # ============ 6. 知识树 ============ #
        print("=" * 68)
        if "chapter_id" in cols["knowledge_points"]:
            kp_no_ch = _one(cur, "SELECT COUNT(*) FROM knowledge_points WHERE chapter_id IS NULL")
            _flag("通过" if kp_no_ch == 0 else "警告",
                  "知识点挂接", f"{kp_no_ch}/{n_kp} 个未挂章节"
                                f"（KbMap 树只显示已挂接节点）")
            if kp_no_ch and show_samples:
                for r in _rows(cur, "SELECT id, name FROM knowledge_points "
                                    "WHERE chapter_id IS NULL LIMIT 10"):
                    print(f"    kp#{r[0]} {r[1]}")
        rel = _one(cur, "SELECT COUNT(*) FROM knowledge_point_relations")
        _flag("警告" if rel == 0 else "通过", "知识点关系边", f"{rel} 条"
              + ("（知识图谱无边：KbMap 只能展示树状结构，无先修/关联连线）" if rel == 0 else ""))
        if {"chapter_id", "subject_id"} <= cols["knowledge_points"] and {"subject_id"} <= cols["subject_chapters"]:
            kp_ch_mismatch = _one(cur, "SELECT COUNT(*) FROM knowledge_points k "
                                       "JOIN subject_chapters c ON k.chapter_id=c.id "
                                       "WHERE k.subject_id<>c.subject_id")
            _flag("通过" if kp_ch_mismatch == 0 else "不通过",
                  "知识点/章节学科一致", f"{kp_ch_mismatch} 个知识点挂到了别的学科的章节下")

        # ============ 7. 总结 ============ #
        print("=" * 68)
        c = Counter(l for l, _, _ in RESULTS)
        print(f"体检结论：通过 {c['通过']} · 警告 {c['警告']} · 不通过 {c['不通过']}")
        for l, name, msg in RESULTS:
            if l in ("警告", "不通过"):
                print(f"  [{l}] {name}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
