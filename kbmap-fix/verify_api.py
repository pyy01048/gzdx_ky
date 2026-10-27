# -*- coding: utf-8 -*-
"""直接调用端点函数验证（只读，不经过 HTTP 服务器）。"""
import sys, io, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, r"D:\平台\backend-main-fastapi")
from database import SessionLocal
from models import User
from routers.words import list_words, get_word
from routers.taxonomy import structure_tree, structure_coverage

db = SessionLocal()
try:
    user = db.query(User).filter(User.id == 1).first()
    print(f"user: {user.username} (id={user.id})")

    # words list
    resp = list_words(db=db, user=user, page=1, page_size=5)
    print("list_words total:", resp["total"])
    for it in resp["items"]:
        print(f"  id={it['id']} word={it['word']!r} root={it.get('root')!r} example={str(it.get('example'))[:55]!r} example_cn={str(it.get('example_cn'))[:30]!r}")

    # word detail
    d = get_word(6, db=db, user=user)
    print("get_word(6):", d["word"], "| root=", d.get("root"), "| example=", str(d.get("example"))[:60])

    # taxonomy tree (全部)
    tree_resp = asyncio.run(structure_tree(db=db))
    tree = tree_resp["tree"]
    subj_list = [s["subject"] for s in tree]
    print("tree subjects:", subj_list)
    missing = [s for s in ["信号与系统", "电路", "通信原理", "普通物理", "计算机学科专业基础408", "电磁场与电磁波", "数字信号处理"] if s not in subj_list]
    print("missing subjects:", missing)
    print("total kps in tree:", sum(s["knowledge_point_count"] for s in tree))
    for sname in ["信号与系统", "电磁场与电磁波", "数字信号处理", "计算机学科专业基础408", "数学"]:
        node = next((s for s in tree if s["subject"] == sname), None)
        if node:
            chs = node.get("chapters", [])
            kp_sum = sum(c["knowledge_point_count"] for c in chs)
            print(f"  subject={sname} kp_count={node['knowledge_point_count']} chapters={len(chs)} kp_in_chapters={kp_sum}")

    # coverage
    cov = asyncio.run(structure_coverage(db=db))
    cov_subjects = [s["subject"] for s in cov["subjects"]]
    print("coverage subjects:", cov_subjects)
    print("coverage includes 信号与系统:", "信号与系统" in cov_subjects)
    print("coverage includes 电磁场与电磁波:", "电磁场与电磁波" in cov_subjects)
finally:
    db.close()