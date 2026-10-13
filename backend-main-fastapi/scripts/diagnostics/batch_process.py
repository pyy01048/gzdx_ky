# -*- coding: utf-8 -*-
"""批量处理：解析文档 + 构建向量索引 + 网盘入库。"""

import sys
import os
import asyncio
import datetime
# 本文件位于 backend-main-fastapi/scripts/diagnostics/，需要把仓库根目录
# 加进 sys.path 才能 import database / models / services —— 原先只加了自身
# 所在目录，所以这个脚本一运行就在下一行 ImportError。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import SessionLocal, engine
from models import Document, KnowledgeChunk, NetdiskFile, Base


def clean_text(text):
    """清理文本中的非法Unicode字符（代理对、控制字符等）。"""
    if not text:
        return text
    # 移除代理对字符（\ud800-\udfff）
    text = ''.join(c for c in text if not ('\ud800' <= c <= '\udfff'))
    # 移除其他控制字符（保留换行、制表符）
    text = ''.join(c for c in text if c == '\n' or c == '\t' or c == '\r' or c >= ' ')
    return text


def parse_all_documents():
    """批量解析所有pending状态的文档。"""
    print("=" * 60)
    print("任务1：批量解析文档")
    print("=" * 60)

    db = SessionLocal()
    pending_docs = db.query(Document).filter(Document.index_status == "pending").all()
    print(f"待解析文档数: {len(pending_docs)}")

    if not pending_docs:
        print("没有待解析的文档")
        db.close()
        return 0

    from services.document_parser import DocumentParser
    from services.kb_service import has_searchable_chunks, ingest_text
    from services.smart_ingest import gate_for_write

    parser = DocumentParser()
    parsed_count = 0
    failed_count = 0
    rejected_count = 0

    for i, doc in enumerate(pending_docs):
        try:
            print(f"  [{i+1}/{len(pending_docs)}] 解析: {doc.file_name}")

            doc.index_status = "indexing"
            doc.parse_progress = 0.1
            db.commit()

            # 解析文本
            if doc.file_path and os.path.exists(doc.file_path):
                content_text = parser.parse(doc.file_path)
            else:
                content_text = f"[文件缺失] 文件名：{doc.file_name}"

            # 质量闸门：必须在 clean_text 之前。clean_text 会把控制字符全部
            # 抹掉，而「整份二进制当文本读」的坏文件正是靠连续控制字节识别的；
            # 先清洗等于销毁证据。
            verdict = gate_for_write(db, content_text,
                                     path=doc.file_path or "", doc_id=doc.id)
            if not verdict["ok"]:
                # 拒绝时不覆盖 doc.content（老正文可能仍有用），只置 failed。
                doc.index_status = "failed"
                doc.parse_progress = 1.0
                db.commit()
                print("    质量闸门拒绝入库：" + "；".join(verdict["reasons"]))
                rejected_count += 1
                continue

            # 清理非法字符
            content_text = clean_text(content_text)
            doc.content = content_text[:500000]
            doc.parse_progress = 0.5
            db.commit()

            # 分块入库。replace=True：重解析要先清掉本 doc 名下旧块，
            # 否则每跑一遍就多一整套重复 knowledge_chunks。
            chunks_count = ingest_text(
                db, doc.id, doc.file_name, content_text, doc.subject,
                replace=True,
            )
            print(f"    生成 {chunks_count} 个分块")

            # 状态口径：旧写法有两处谎报——
            #  * index_status="ready"：库里没有任何查询认这个值；
            #  * doc.parsed_at / doc.parse_error：Document 表没有这些列，赋值只是
            #    给实例挂了个不落库的属性，错误信息静默丢失。
            # indexed 必须真的有可检索分块，否则就是 RAG 搜不到的幽灵文档。
            doc.index_status = "indexed" if has_searchable_chunks(db, doc.id) else "failed"
            doc.knowledge_point_count = chunks_count
            doc.parse_progress = 1.0
            doc.updated_at = datetime.datetime.now()
            db.commit()
            parsed_count += 1

        except Exception as e:
            print(f"    解析失败: {e}")
            try:
                db.rollback()
                doc.index_status = "failed"
                db.commit()
            except Exception:
                pass
            failed_count += 1

    db.close()
    print(f"\n解析完成: 成功 {parsed_count}, 闸门拒绝 {rejected_count}, 失败 {failed_count}")
    return parsed_count


def build_embeddings():
    """构建知识分块的向量索引。"""
    print("\n" + "=" * 60)
    print("任务2：构建向量索引")
    print("=" * 60)

    db = SessionLocal()
    total_chunks = db.query(KnowledgeChunk).count()
    chunks_with_embedding = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.embedding != None,
        KnowledgeChunk.embedding != ""
    ).count()

    print(f"知识分块总数: {total_chunks}")
    print(f"已有向量: {chunks_with_embedding}")
    print(f"待构建: {total_chunks - chunks_with_embedding}")

    if total_chunks - chunks_with_embedding == 0:
        print("所有分块已有向量，无需构建")
        db.close()
        return

    from services.embedding_service import get_embedder, generate_embeddings

    embedder = get_embedder()
    print(f"使用嵌入模型: {embedder.__class__.__name__}")

    # 分批处理
    batch_size = 50
    offset = 0
    total_built = 0

    while True:
        chunks = db.query(KnowledgeChunk).filter(
            (KnowledgeChunk.embedding == None) | (KnowledgeChunk.embedding == "")
        ).offset(offset).limit(batch_size).all()

        if not chunks:
            break

        texts = [c.content for c in chunks if c.content]
        if not texts:
            offset += batch_size
            continue

        try:
            embeddings = generate_embeddings(texts)
            for chunk, emb in zip(chunks, embeddings):
                if emb:
                    chunk.embedding = str(emb)
                    chunk.embedding_model = embedder.__class__.__name__
                    chunk.embedded_at = datetime.datetime.now()
            db.commit()
            total_built += len(chunks)
            print(f"  已构建 {total_built}/{total_chunks - chunks_with_embedding}")
        except Exception as e:
            print(f"  批次构建失败: {e}")

        offset += batch_size

    db.close()
    print(f"\n向量构建完成: 共 {total_built} 个分块")


def netdisk_to_knowledge_base():
    """网盘文件自动下载、解析、入库到知识库。"""
    print("\n" + "=" * 60)
    print("任务3：网盘→知识库链路")
    print("=" * 60)

    db = SessionLocal()

    # 检查网盘文件
    netdisk_files = db.query(NetdiskFile).all()
    print(f"网盘文件数: {len(netdisk_files)}")

    if not netdisk_files:
        print("没有网盘文件，跳过")
        db.close()
        return

    from routers.netdisk import _ingest_netdisk_file

    imported_count = 0
    failed_count = 0

    # 这里原先自己复制了一遍「建 Document -> 解析 -> 分块 -> 标 ready」，用的列名
    # （Document.file_size / title / source / uploaded_at、NetdiskFile.local_path）
    # 两张表里都不存在，所以这个函数一执行就 TypeError，从未真正跑通过。
    # 网盘入库的唯一实现在 routers/netdisk.py（含质量闸门、只按 file_path 判重、
    # 「有可检索分块才算 indexed」）—— 脚本只批量调用它，不再复制一份会腐烂的逻辑。
    for nf in netdisk_files:
        print(f"  处理: {nf.file_name}")
        try:
            res = asyncio.run(_ingest_netdisk_file(db, nf))
        except Exception as e:
            print(f"    入库失败: {e}")
            failed_count += 1
            continue
        if res.get("success"):
            imported_count += 1
            print(f"    {res.get('message')}")
        else:
            failed_count += 1
            print(f"    未入库: {res.get('message')}")

    db.close()
    print(f"\n网盘入库完成: 入库 {imported_count} 个文档, 未入库/失败 {failed_count} 个")


def main():
    print("考研学习平台 - 批量处理脚本")
    print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 任务1：批量解析文档
    parse_all_documents()

    # 任务2：构建向量索引
    build_embeddings()

    # 任务3：网盘→知识库
    netdisk_to_knowledge_base()

    # 最终统计
    print("\n" + "=" * 60)
    print("最终统计")
    print("=" * 60)

    db = SessionLocal()
    total_docs = db.query(Document).count()
    # 状态口径：index_status 的合法取值是 pending/indexing/indexed/failed。
    # 这里原本写 "ready"（该值从不存在），导致统计恒为 0。
    ready_docs = db.query(Document).filter(Document.index_status == "indexed").count()
    total_chunks = db.query(KnowledgeChunk).count()
    chunks_with_embedding = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.embedding != None,
        KnowledgeChunk.embedding != ""
    ).count()

    print(f"文档总数: {total_docs}")
    print(f"已解析文档: {ready_docs}")
    print(f"知识分块总数: {total_chunks}")
    print(f"已有向量分块: {chunks_with_embedding}")
    print(f"向量覆盖率: {chunks_with_embedding/total_chunks*100:.1f}%" if total_chunks > 0 else "向量覆盖率: 0%")

    db.close()
    print(f"\n完成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("✓ 批量处理完成！")


if __name__ == "__main__":
    main()
