# -*- coding: utf-8 -*-
"""测量修复后 tree 响应大小 + 验证每个知识点在树中可达（只读）。"""
import sys, io, asyncio, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, r"D:\平台\backend-main-fastapi")
from database import SessionLocal
from routers.taxonomy import structure_tree
from models import KnowledgePoint

db = SessionLocal()
try:
    resp = asyncio.run(structure_tree(db=db))
    raw = json.dumps(resp, ensure_ascii=False).encode('utf-8')
    print(f"tree response size: {len(raw)/1024:.1f} KB ({len(raw)} bytes)")

    tree = resp["tree"]
    total = sum(s["knowledge_point_count"] for s in tree)
    print("total kps in tree:", total)

    # 每个 subject 的 kps 是否都挂进 chapters
    unreachable = []
    for s in tree:
        if s["knowledge_point_count"] == 0:
            continue
        in_ch = sum(c["knowledge_point_count"] for c in s["chapters"])
        if in_ch != s["knowledge_point_count"]:
            unreachable.append((s["subject"], s["knowledge_point_count"], in_ch))
    print("subjects with kp not fully in chapters:", unreachable)

    # 全部 kp id 集合 vs 树中 kp id 集合
    tree_kp_ids = set()
    for s in tree:
        for c in s["chapters"]:
            for kp in c.get("knowledge_points", []):
                tree_kp_ids.add(int(kp["id"]))
    all_ids = {r[0] for r in db.query(KnowledgePoint.id).all()}
    missing = all_ids - tree_kp_ids
    print("kps missing from tree:", len(missing), sorted(list(missing))[:10])
finally:
    db.close()