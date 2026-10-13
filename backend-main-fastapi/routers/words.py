"""单词词库路由：词库管理、单词CRUD、SM-2复习调度、批量导入。"""

import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Word, WordDeck

router = APIRouter(prefix="/api/words", tags=["单词词库"])


# --------------------------------------------------------------------------- #
# Pydantic 模型
# --------------------------------------------------------------------------- #
class WordDeckCreate(BaseModel):
    name: str
    description: Optional[str] = None
    source: Optional[str] = None
    color: Optional[str] = None


class WordDeckOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    source: Optional[str] = None
    word_count: int = 0
    color: Optional[str] = None
    created_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class WordCreate(BaseModel):
    deck_id: Optional[int] = None
    word: str
    phonetic: Optional[str] = None
    pos: Optional[str] = None
    meaning: str
    root: Optional[str] = None
    example: Optional[str] = None
    example_cn: Optional[str] = None
    tag: Optional[str] = None


class WordUpdate(BaseModel):
    deck_id: Optional[int] = None
    word: Optional[str] = None
    phonetic: Optional[str] = None
    pos: Optional[str] = None
    meaning: Optional[str] = None
    root: Optional[str] = None
    example: Optional[str] = None
    example_cn: Optional[str] = None
    tag: Optional[str] = None


class WordOut(BaseModel):
    id: int
    deck_id: Optional[int] = None
    word: str
    phonetic: Optional[str] = None
    pos: Optional[str] = None
    meaning: str
    root: Optional[str] = None
    example: Optional[str] = None
    example_cn: Optional[str] = None
    tag: Optional[str] = None
    status: str = "new"
    ease_factor: float = 2.5
    interval: int = 0
    reps: int = 0
    lapses: int = 0
    due_date: Optional[datetime.date] = None
    last_review: Optional[datetime.date] = None
    review_history: Optional[list] = None
    created_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class WordReview(BaseModel):
    grade: int  # 0-5，SM-2评分


class WordBatchImport(BaseModel):
    deck_id: Optional[int] = None
    words: List[WordCreate]


# --------------------------------------------------------------------------- #
# 词库管理
# --------------------------------------------------------------------------- #
@router.get("/decks", response_model=List[WordDeckOut])
def list_decks(db: Session = Depends(get_db)):
    """获取所有词库分类。"""
    decks = db.query(WordDeck).order_by(WordDeck.id).all()
    # 实时统计每个词库的单词数
    for d in decks:
        d.word_count = db.query(Word).filter(Word.deck_id == d.id).count()
    return decks


@router.post("/decks", response_model=WordDeckOut)
def create_deck(data: WordDeckCreate, db: Session = Depends(get_db)):
    """创建新词库。"""
    deck = WordDeck(**data.model_dump())
    db.add(deck)
    db.commit()
    db.refresh(deck)
    return deck


@router.delete("/decks/{deck_id}")
def delete_deck(deck_id: int, db: Session = Depends(get_db)):
    """删除词库（单词保留，deck_id置空）。"""
    deck = db.query(WordDeck).filter(WordDeck.id == deck_id).first()
    if not deck:
        raise HTTPException(404, "词库不存在")
    # 将该词库下的单词deck_id置空
    db.query(Word).filter(Word.deck_id == deck_id).update({Word.deck_id: None})
    db.delete(deck)
    db.commit()
    return {"ok": True, "message": "词库已删除"}


# --------------------------------------------------------------------------- #
# 单词 CRUD
# --------------------------------------------------------------------------- #
@router.get("")
def list_words(
    deck_id: Optional[int] = None,
    status: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """获取单词列表，支持按词库/状态/标签/关键词筛选和分页。"""
    q = db.query(Word)
    if deck_id is not None:
        q = q.filter(Word.deck_id == deck_id)
    if status:
        q = q.filter(Word.status == status)
    if tag:
        q = q.filter(Word.tag == tag)
    if search:
        q = q.filter(Word.word.like(f"%{search}%"))
    q = q.order_by(Word.id)

    # 统一分页响应
    total = q.count()
    offset = (page - 1) * page_size
    items = q.offset(offset).limit(page_size).all()
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/stats")
def word_stats(db: Session = Depends(get_db)):
    """单词统计：总数、各状态数量、今日待复习。"""
    total = db.query(Word).count()
    new_count = db.query(Word).filter(Word.status == "new").count()
    learning_count = db.query(Word).filter(Word.status == "learning").count()
    reviewing_count = db.query(Word).filter(Word.status == "reviewing").count()
    mastered_count = db.query(Word).filter(Word.status == "mastered").count()
    today = datetime.date.today()
    # V12 修复：新词（status='new'，从未学习）不计入"今日待复习"。
    # 旧逻辑把 due_date IS NULL 的新词也算作今日到期 → 全站复习调度显示
    # "4568/4569 今日待复习"，学习数据失真。复习队列只包含已学过的词。
    due_today = db.query(Word).filter(
        Word.due_date <= today
    ).filter(Word.status.in_(["learning", "reviewing"])).count()
    return {
        "total": total,
        "new": new_count,
        "learning": learning_count,
        "reviewing": reviewing_count,
        "mastered": mastered_count,
        "due_today": due_today,
    }


@router.get("/due", response_model=List[WordOut])
def due_words(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """获取今日待复习单词（含新词）。"""
    today = datetime.date.today()
    # V12 修复：due 队列排除新词（new）——新词走"学习"流程而非"复习"队列
    words = db.query(Word).filter(
        Word.due_date <= today
    ).filter(Word.status.in_(["learning", "reviewing"])).order_by(Word.status, Word.id).limit(limit).all()
    return words


@router.get("/{word_id}", response_model=WordOut)
def get_word(word_id: int, db: Session = Depends(get_db)):
    """获取单个单词详情。"""
    w = db.query(Word).filter(Word.id == word_id).first()
    if not w:
        raise HTTPException(404, "单词不存在")
    return w


@router.post("", response_model=WordOut)
def create_word(data: WordCreate, db: Session = Depends(get_db)):
    """添加单个单词。"""
    w = Word(**data.model_dump())
    w.due_date = datetime.date.today()
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


@router.put("/{word_id}", response_model=WordOut)
def update_word(word_id: int, data: WordUpdate, db: Session = Depends(get_db)):
    """更新单词信息。"""
    w = db.query(Word).filter(Word.id == word_id).first()
    if not w:
        raise HTTPException(404, "单词不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
    db.commit()
    db.refresh(w)
    return w


@router.delete("/{word_id}")
def delete_word(word_id: int, db: Session = Depends(get_db)):
    """删除单词。"""
    w = db.query(Word).filter(Word.id == word_id).first()
    if not w:
        raise HTTPException(404, "单词不存在")
    db.delete(w)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# SM-2 复习调度
# --------------------------------------------------------------------------- #
@router.post("/{word_id}/review", response_model=WordOut)
def review_word(word_id: int, data: WordReview, db: Session = Depends(get_db)):
    """SM-2 复习评分，更新调度状态（使用统一的 ReviewScheduler 算法）。"""
    from services.review_scheduler import ReviewScheduler

    w = db.query(Word).filter(Word.id == word_id).first()
    if not w:
        raise HTTPException(404, "单词不存在")

    grade = data.grade
    today = datetime.date.today()

    # 使用统一的 SM-2 算法
    _, new_reps, new_interval, new_ef, new_status = ReviewScheduler.calculate_next_review(
        quality=grade,
        repetitions=w.reps or 0,
        interval=w.interval or 0,
        ef=w.ease_factor or 2.5,
    )

    w.reps = new_reps
    w.interval = new_interval
    w.ease_factor = new_ef
    w.status = new_status if new_status != "review" else "reviewing"
    w.lapses = w.lapses + (1 if grade < 3 else 0)

    w.due_date = today + datetime.timedelta(days=new_interval)
    w.last_review = today

    # 记录复习历史
    if not w.review_history:
        w.review_history = []
    w.review_history.append({"date": today.isoformat(), "grade": grade})
    if len(w.review_history) > 100:
        w.review_history = w.review_history[-100:]

    db.commit()
    db.refresh(w)
    return w


# --------------------------------------------------------------------------- #
# 批量导入
# --------------------------------------------------------------------------- #
@router.post("/batch-import")
def batch_import_words(data: WordBatchImport, db: Session = Depends(get_db)):
    """批量导入单词。"""
    count = 0
    today = datetime.date.today()
    for w_data in data.words:
        w = Word(**w_data.model_dump())
        if data.deck_id is not None:
            w.deck_id = data.deck_id
        w.due_date = today
        db.add(w)
        count += 1
    db.commit()
    return {"ok": True, "imported": count}


# --------------------------------------------------------------------------- #
# V3.0 文本批量导入（一行一个单词，自动解析）
# --------------------------------------------------------------------------- #
class TextImportRequest(BaseModel):
    text: str
    deck_id: Optional[int] = None
    delimiter: Optional[str] = None  # 自定义分隔符，默认自动识别


@router.post("/import-text")
def import_words_from_text(data: TextImportRequest, db: Session = Depends(get_db)):
    """从文本批量导入单词，支持多种格式：
    - "apple 苹果"
    - "apple n. 苹果"
    - "apple /ˈæpl/ n. 苹果"
    - "apple 苹果；苹果树"
    """
    import re
    lines = data.text.strip().split("\n")
    imported = 0
    skipped = 0
    errors = []
    today = datetime.date.today()

    # 已存在的单词集合（去重）
    existing_words = {w.word for w in db.query(Word.word).all()}

    for idx, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        try:
            # 解析格式：单词 [音标] [词性] 释义
            # 匹配音标：/.../ 或 [...]
            phonetic_match = re.search(r'[/\[]([^/\]]+)[/\]]', line)
            phonetic = phonetic_match.group(1) if phonetic_match else None

            # 移除音标部分
            remaining = re.sub(r'[/\[][^/\]]+[/\]]', '', line).strip()

            # 匹配词性：n. v. adj. adv. prep. conj. pron. num. art. int. 等
            pos_match = re.match(r'^([a-z]+\.)\s+', remaining, re.IGNORECASE)
            pos = pos_match.group(1) if pos_match else None

            # 移除词性部分
            if pos:
                remaining = remaining[pos_match.end():].strip()

            # 分割单词和释义
            parts = remaining.split(None, 1)
            if len(parts) < 2:
                # 尝试用自定义分隔符
                if data.delimiter:
                    parts = line.split(data.delimiter, 1)
                if len(parts) < 2:
                    skipped += 1
                    errors.append(f"第{idx}行：无法解析 '{line[:50]}'")
                    continue

            word = parts[0].strip()
            meaning = parts[1].strip() if len(parts) > 1 else ""

            # 校验
            if not word or not meaning:
                skipped += 1
                errors.append(f"第{idx}行：单词或释义为空")
                continue

            if word in existing_words:
                skipped += 1
                continue

            # 创建单词
            w = Word(
                deck_id=data.deck_id,
                word=word[:100],
                phonetic=phonetic[:100] if phonetic else None,
                pos=pos[:50] if pos else None,
                meaning=meaning[:2000],
                status="new",
                due_date=today,
            )
            db.add(w)
            existing_words.add(word)
            imported += 1

        except Exception as e:
            skipped += 1
            errors.append(f"第{idx}行：{str(e)}")

    db.commit()

    # 更新词库数量
    if data.deck_id:
        deck = db.query(WordDeck).filter(WordDeck.id == data.deck_id).first()
        if deck:
            deck.word_count = db.query(Word).filter(Word.deck_id == data.deck_id).count()
            db.commit()

    return {
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "total_lines": len(lines),
        "errors": errors[:20],  # 只返回前20个错误
    }


# --------------------------------------------------------------------------- #
# V3.0 Excel批量导入
# --------------------------------------------------------------------------- #
@router.post("/import-excel")
async def import_words_from_excel(
    file: bytes = File(...),
    deck_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """从Excel批量导入单词。
    支持列：单词、音标、词性、释义、词根、例句、例句翻译、标签
    """
    import io
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(status_code=500, detail="请先安装openpyxl: pip install openpyxl")

    wb = openpyxl.load_workbook(io.BytesIO(file), read_only=True)
    ws = wb.active

    # 读取表头
    headers = []
    for cell in next(ws.iter_rows(min_row=1, max_row=1, values_only=True)):
        headers.append(str(cell).strip() if cell else "")

    # 列映射
    col_map = {}
    for i, h in enumerate(headers):
        h_lower = h.lower()
        if h in ("单词", "word", "英文"):
            col_map["word"] = i
        elif h in ("音标", "phonetic", "发音"):
            col_map["phonetic"] = i
        elif h in ("词性", "pos", "part of speech"):
            col_map["pos"] = i
        elif h in ("释义", "meaning", "中文", "意思"):
            col_map["meaning"] = i
        elif h in ("词根", "root", "助记", "词缀"):
            col_map["root"] = i
        elif h in ("例句", "example", "英文例句"):
            col_map["example"] = i
        elif h in ("例句翻译", "example_cn", "中文例句", "例句中文"):
            col_map["example_cn"] = i
        elif h in ("标签", "tag", "分类", "频率"):
            col_map["tag"] = i

    if "word" not in col_map or "meaning" not in col_map:
        raise HTTPException(status_code=400, detail="Excel必须包含'单词'和'释义'列")

    # 读取数据
    imported = 0
    skipped = 0
    errors = []
    today = datetime.date.today()
    existing_words = {w.word for w in db.query(Word.word).all()}

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        try:
            word = str(row[col_map["word"]]).strip() if row[col_map["word"]] else ""
            meaning = str(row[col_map["meaning"]]).strip() if row[col_map["meaning"]] else ""

            if not word or not meaning:
                skipped += 1
                continue

            if word in existing_words:
                skipped += 1
                continue

            w = Word(
                deck_id=deck_id,
                word=word[:100],
                phonetic=str(row[col_map["phonetic"]]).strip()[:100] if "phonetic" in col_map and row[col_map["phonetic"]] else None,
                pos=str(row[col_map["pos"]]).strip()[:50] if "pos" in col_map and row[col_map["pos"]] else None,
                meaning=meaning[:2000],
                root=str(row[col_map["root"]]).strip()[:300] if "root" in col_map and row[col_map["root"]] else None,
                example=str(row[col_map["example"]]).strip() if "example" in col_map and row[col_map["example"]] else None,
                example_cn=str(row[col_map["example_cn"]]).strip() if "example_cn" in col_map and row[col_map["example_cn"]] else None,
                tag=str(row[col_map["tag"]]).strip()[:50] if "tag" in col_map and row[col_map["tag"]] else None,
                status="new",
                due_date=today,
            )
            db.add(w)
            existing_words.add(word)
            imported += 1

        except Exception as e:
            skipped += 1
            errors.append(f"第{row_idx}行：{str(e)}")

    db.commit()
    wb.close()

    # 更新词库数量
    if deck_id:
        deck = db.query(WordDeck).filter(WordDeck.id == deck_id).first()
        if deck:
            deck.word_count = db.query(Word).filter(Word.deck_id == deck_id).count()
            db.commit()

    return {
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:20],
    }
