# -*- coding: utf-8 -*-
"""验证 words API 增强逻辑：直接调用 routers.words 的辅助函数（只读，不写库）。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, r"D:\平台\backend-main-fastapi")
from database import SessionLocal
from models import Word
from routers.words import _load_word_examples, _load_word_roots, _word_out, _build_root

db = SessionLocal()
try:
    rows = db.query(Word).filter(Word.user_id == 1).order_by(Word.id).limit(8).all()
    examples = _load_word_examples(db, [w.id for w in rows])
    root_by_word = _load_word_roots(db)
    print(f"word_roots index size: {len(root_by_word)}")
    print(f"examples loaded for: {sorted(int(k) for k in examples)}")
    for w in rows:
        data = _word_out(w, db, examples, root_by_word)
        print(f"id={w.id} word={w.word!r} root={data['root']!r} example={str(data['example'])[:60]!r} example_cn={str(data['example_cn'])[:40]!r}")
finally:
    db.close()