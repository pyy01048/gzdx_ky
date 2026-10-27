# -*- coding: utf-8 -*-
"""验证 due_words 增强（只读）。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, r"D:\平台\backend-main-fastapi")
from database import SessionLocal
from models import User
from routers.words import due_words

db = SessionLocal()
try:
    user = db.query(User).filter(User.id == 1).first()
    due = due_words(db=db, user=user, limit=5)
    print("due_words count:", len(due))
    for it in due:
        print(f"  word={it['word']!r} root={it.get('root')!r} example={str(it.get('example'))[:50]!r}")
finally:
    db.close()