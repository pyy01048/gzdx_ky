"""一次性数据修复：words.review_history 被历史导入写成 {}（JSON 对象），
而 API 契约是数组 —— 5492 行脏数据导致 GET /api/words 直接 500。

修复规则（幂等，可重复执行）：
- review_history 序列化后恰好是 '{}'（空对象）→ 置 '[]'（空数组，语义等价）；
- 非空 dict（如 {"0": {...}} 数字键形态）→ 取值组成数组，保留真实历史。
- 只处理 list/None 之外的行，正常数据零改动。
"""
from database import SessionLocal
from models import Word

db = SessionLocal()
emptied = 0
converted = 0
try:
    rows = db.query(Word).all()
    for w in rows:
        rh = w.review_history
        if rh is None or isinstance(rh, list):
            continue
        if isinstance(rh, dict):
            if rh:
                w.review_history = list(rh.values())
                converted += 1
            else:
                w.review_history = []
                emptied += 1
        else:
            w.review_history = []
            emptied += 1
    db.commit()
    print(f"empty-dict -> []: {emptied}, dict-with-keys -> values: {converted}")

    remaining = sum(1 for w in db.query(Word).all() if w.review_history is not None and not isinstance(w.review_history, list))
    print(f"remaining non-list rows: {remaining}")
finally:
    db.close()
