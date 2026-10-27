"""单词词库路由：词库管理、单词CRUD、SM-2复习调度、批量导入。"""

from utils.security import require_admin
import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Word, WordDeck, User
from sqlalchemy import or_
from utils.scope import owner_id, scoped  # B4 行级隔离：词库公共读，单词严格本人
from utils.security import current_user
from utils.timeutil import local_today

from utils.response import MAX_PAGE_SIZE

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

    model_config = ConfigDict(from_attributes=True)
class WordCreate(BaseModel):
    deck_id: Optional[int] = None
    word: str = Field(..., min_length=1)
    phonetic: Optional[str] = None
    pos: Optional[str] = None
    meaning: str = Field(..., min_length=1)
    root: Optional[str] = None
    example: Optional[str] = None
    example_cn: Optional[str] = None
    tag: Optional[str] = None
    # P0-1：来源标注（如「刷题生词」）。不传时行为完全不变；
    # 传入时若 tag 为空，则透传写入 tag 列（复用既有列，不加新列）。
    source_label: Optional[str] = None


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
    extra: Optional[dict] = None
    created_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
    from pydantic import field_validator

    @field_validator("status", mode="before")
    @classmethod
    def _map_db_status(cls, v):
        # DB 枚举 not_mastered -> API 契约 new（见 _api_status）
        return _api_status(v) if isinstance(v, str) else v

    @field_validator("review_history", mode="before")
    @classmethod
    def _normalize_review_history(cls, v):
        # 数据事故防线：历史导入曾把 JSONB 写成 {}（对象），API 契约是数组。
        # 序列化层直接归一，避免一行脏数据打挂整个 GET /api/words（实测 5492 行）。
        if v is None or isinstance(v, list):
            return v
        if isinstance(v, dict):
            return list(v.values())
        if isinstance(v, str):
            import json as _json
            try:
                parsed = _json.loads(v)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []
        return []


class WordReview(BaseModel):
    grade: int  # 0-5，SM-2评分


class SpellCheckRequest(BaseModel):
    word_id: int
    answer: str = Field(..., min_length=1, max_length=200)
    #: 拼写练习同时记录一次复习：正确=5（满分），错误=1（重来）
    record_review: bool = True


class SpellCheckOut(BaseModel):
    correct: bool
    word: str
    user_answer: str
    phonetic: Optional[str] = None
    pos: Optional[str] = None
    meaning: str
    #: 若 record_review=True，返回更新后的单词（SM-2/FSRS 调度结果）
    review: Optional[dict] = None


class WordBatchImport(BaseModel):
    deck_id: Optional[int] = None
    words: List[WordCreate]


#: DB 权威枚举 mastery_level = not_mastered/learning/reviewing/mastered，
#: 而 API/前端契约用 new/learning/reviewing/mastered（'new' 不是合法枚举值，
#: 直接落库会报 invalid input value for enum，实测）。路由边界统一映射。
_DB_TO_API_STATUS = {
    "not_mastered": "new",
    "learning": "learning",
    "reviewing": "reviewing",
    "mastered": "mastered",
}
_API_TO_DB_STATUS = {v: k for k, v in _DB_TO_API_STATUS.items()}


def _db_status(api_status: str) -> str:
    """API 状态词 -> DB 枚举值；未知值退 not_mastered（未学）。"""
    return _API_TO_DB_STATUS.get((api_status or "").strip().lower(), "not_mastered")


def _api_status(db_status: str) -> str:
    """DB 枚举值 -> API 状态词；未知值退 new。"""
    return _DB_TO_API_STATUS.get((db_status or "").strip().lower(), "new")


# --------------------------------------------------------------------------- #
# 例句 / 词根增强（P1：word_examples / word_roots 数据在独立表，words 主表列空）
#
# 背景：words.root / words.example 列在批量导入时大多为空（example 全空、
# root 仅 1476 词非空），而真实语料在 word_examples（26842 行，覆盖 5390 词）
# 和 word_roots（611 条词根词典）两张独立表。GET /api/words 直接序列化主表列
# → root/example 恒为 null，前端「例句/词根词缀」区域空白（docx/50 P1）。
#
# 修复方案：在**序列化层**做只读增强，不写库、不改表结构：
#   - example：取 word_examples 中该词的第一条句子（优先有中文翻译的）；
#   - root：主表 root 列非空则原样返回；否则用 word_roots.example_words 反查
#     命中该词的词根，拼成「morpheme（中文含义）」。
# 兼容性：word_examples / word_roots 表在 SQLite 回退库可能不存在，
# 查询包 try/except，缺表时退化为原有（null）行为，不影响其它字段。
# --------------------------------------------------------------------------- #
def _load_word_examples(db, word_ids) -> dict:
    """批量取一批单词的推荐例句。

    Args:
        db: SQLAlchemy Session。
        word_ids: 单词 ID 列表（可空）。

    Returns:
        ``{word_id: {"en": str, "cn": str|None}}``，每词一条，优先带中文翻译。
    """
    ids = [int(i) for i in (word_ids or []) if i is not None]
    if not ids:
        return {}
    from sqlalchemy import text

    try:
        rows = db.execute(
            text(
                "SELECT word_id, sentence_en, sentence_cn FROM word_examples "
                "WHERE word_id = ANY(:ids) ORDER BY word_id, id"
            ),
            {"ids": ids},
        ).fetchall()
    except Exception:  # noqa: BLE001 - 表不存在（SQLite 回退库）时静默降级
        return {}
    out: dict = {}
    for word_id, en, cn in rows:
        word_id = int(word_id)
        if word_id not in out:
            out[word_id] = {"en": en or "", "cn": cn or None}
        elif not out[word_id].get("cn") and cn:
            out[word_id] = {"en": en or "", "cn": cn or None}
    return out


def _load_word_roots(db) -> dict:
    """把 word_roots 全量装载为「例词 → 词根条目」反查索引。

    Returns:
        ``{example_word_lower: {"morpheme": str, "meaning_cn": str}}``。
    """
    from sqlalchemy import text

    try:
        rows = db.execute(
            text("SELECT morpheme, meaning, meaning_cn, example_words FROM word_roots")
        ).fetchall()
    except Exception:  # noqa: BLE001 - 表不存在（SQLite 回退库）时静默降级
        return {}
    by_example_word: dict = {}
    for morpheme, meaning, meaning_cn, example_words in rows:
        entry = {
            "morpheme": morpheme or "",
            "meaning_cn": (meaning_cn or meaning or "").strip(),
        }
        for ew in (example_words or []):
            key = str(ew).strip().lower()
            if key and key not in by_example_word:
                by_example_word[key] = entry
    return by_example_word


def _build_root(w, root_by_word: dict):
    """生成词根展示串：主表 root 列优先，否则用 word_roots 反查。"""
    if w.root and str(w.root).strip():
        return w.root
    entry = root_by_word.get((w.word or "").strip().lower())
    if not entry:
        return None
    morpheme = entry.get("morpheme") or ""
    cn = entry.get("meaning_cn") or ""
    return f"{morpheme}（{cn}）" if morpheme and cn else (morpheme or None)


def _word_out(w, db, examples: dict = None, root_by_word: dict = None) -> dict:
    """序列化单词并做例句/词根增强（只读，不修改 ORM 行，避免隐式写库）。

    基础字段仍走 WordOut 校验（status 枚举映射、review_history 归一），
    再在返回字典上覆盖 example / example_cn / root 三个增强字段。
    """
    data = WordOut.model_validate(w).model_dump(mode="json")
    if not data.get("example") and examples:
        ex = examples.get(int(w.id))
        if ex and ex.get("en"):
            data["example"] = ex["en"]
            data["example_cn"] = ex.get("cn")
    if not data.get("root") and root_by_word is not None:
        data["root"] = _build_root(w, root_by_word)
    return data


# --------------------------------------------------------------------------- #
# 词库管理
# --------------------------------------------------------------------------- #
def _ensure_personal_wordbook(db: Session, user: User) -> None:
    """B4 懒加载：为新用户自动分配内置词库副本。

    平台内置模板词库（word_decks user_id=1 名下的「考研核心词汇」「考研熟词僻义」等）
    历史上挂在 user_id=1 名下，新用户按 B4 行级隔离看到的是空词库（`/api/words` total=0）。
    这里在用户首次访问 /api/words/decks 时，把**全部内置模板词库**克隆到该用户
    自己的命名空间（词条内容复制、SM-2 调度字段重置为初始态），让「单词记忆」
    功能对每个用户开箱即用；复习进度仍按 B4 隔离在各自的行上。
    只做新增，不改动模板词库与既有用户数据；已有人词库则跳过。
    """
    uid = owner_id(user)
    if not uid:
        return
    # 已有个人词库（哪怕空库）则跳过，避免重复克隆
    if db.query(WordDeck.id).filter(WordDeck.user_id == uid).first():
        return
    # 内置模板词库：挂在 user_id=1（模板所有者）名下
    templates = (
        db.query(WordDeck)
        .filter(WordDeck.user_id == 1)
        .order_by(WordDeck.id)
        .all()
    )
    if not templates:
        return
    from sqlalchemy import text
    for template in templates:
        tpl_words = (
            db.query(Word)
            .filter(Word.deck_id == template.id, Word.user_id == template.user_id)
            .count()
        )
        if not tpl_words:
            continue
        deck = WordDeck(
            user_id=uid,
            name=template.name,
            description=(template.description or "内置词库自动分配"),
            source=template.source,
            word_count=0,
        )
        db.add(deck)
        db.flush()
        # 批量克隆词条：只复制内容字段，SM-2 调度重置（not_mastered / 2.5 / 0 / 空历史）
        db.execute(
            text(
                "INSERT INTO words (user_id, deck_id, word, phonetic, pos, meaning, root, "
                "example, example_cn, tag, status, ease_factor, interval_days, reps, lapses, "
                "due_date, last_review, review_history, created_at, updated_at) "
                "SELECT :uid, :deck_id, word, phonetic, pos, meaning, root, example, example_cn, "
                "tag, 'not_mastered', 2.5, 0, 0, 0, NULL, NULL, '[]'::jsonb, now(), now() "
                "FROM words WHERE user_id = :tpl_uid AND deck_id = :tpl_deck_id"
            ),
            {"uid": uid, "deck_id": deck.id,
             "tpl_uid": template.user_id, "tpl_deck_id": template.id},
        )
        deck.word_count = tpl_words
    db.commit()


@router.get("/decks", response_model=List[WordDeckOut])
def list_decks(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取词库分类（B4：本人词库 + 内置公共词书 user_id NULL）。"""
    _ensure_personal_wordbook(db, user)  # 新用户首访自动分配内置词库副本
    decks = db.query(WordDeck).filter(
        or_(scoped(WordDeck, user), WordDeck.user_id.is_(None))
    ).order_by(WordDeck.id).all()
    # 实时统计每个词库的单词数（B4：只统计本人单词）
    for d in decks:
        d.word_count = db.query(Word).filter(Word.deck_id == d.id, scoped(Word, user)).count()
    return decks


@router.post("/decks", response_model=WordDeckOut, dependencies=[Depends(require_admin)])
def create_deck(data: WordDeckCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """创建新词库。"""
    deck = WordDeck(**data.model_dump())
    deck.user_id = owner_id(user)  # B4：归属当前用户
    db.add(deck)
    db.commit()
    db.refresh(deck)
    return deck


@router.delete("/decks/{deck_id}", dependencies=[Depends(require_admin)])
def delete_deck(deck_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """删除词库（单词保留，deck_id置空；B4：仅本人词库，内置公共词书不可删）。"""
    deck = db.query(WordDeck).filter(WordDeck.id == deck_id, scoped(WordDeck, user)).first()
    if not deck:
        raise HTTPException(404, "词库不存在")
    # 将该词库下本人单词的deck_id置空
    db.query(Word).filter(Word.deck_id == deck_id, scoped(Word, user)).update({Word.deck_id: None})
    db.delete(deck)
    db.commit()
    return {"ok": True, "message": "词库已删除"}


# --------------------------------------------------------------------------- #
# 单词 CRUD
# --------------------------------------------------------------------------- #
@router.get("", dependencies=[Depends(require_admin)])
def list_words(
    deck_id: Optional[int] = None,
    status: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """获取单词列表，支持按词库/状态/标签/关键词筛选和分页（B4：只看本人单词）。"""
    q = db.query(Word).filter(scoped(Word, user))
    if deck_id is not None:
        q = q.filter(Word.deck_id == deck_id)
    if status:
        q = q.filter(Word.status == status)
    if tag:
        q = q.filter(Word.tag == tag)
    if search:
        q = q.filter(Word.word.like(f"%{search}%"))
    q = q.order_by(Word.id)

    # 统一分页响应。items 必须走 WordOut 序列化：直接塞 ORM 行会绕过
    # WordOut.status 的 field_validator（not_mastered → new），DB 枚举原值漏到前端。
    # dogfood ISSUE-004 的真凶：前端复习队列只认 new / learning+reviewing 两个桶，
    # not_mastered 两边都接不住 → 导入后队列恒空，页面却显示「已全部复习完成」。
    total = q.count()
    offset = (page - 1) * page_size
    rows = q.offset(offset).limit(page_size).all()
    # P1 增强：例句/词根来自独立表（word_examples / word_roots），序列化层合并
    examples = _load_word_examples(db, [w.id for w in rows])
    root_by_word = _load_word_roots(db)
    items = [_word_out(w, db, examples, root_by_word) for w in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/stats")
def word_stats(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """单词统计：总数、各状态数量、今日待复习（B4：只统计本人单词）。"""
    _scope = scoped(Word, user)  # B4：以下 6 处 count 全部按本人过滤
    total = db.query(Word).filter(_scope).count()
    # DB 权威枚举里没有 'new'，未学状态是 not_mastered
    new_count = db.query(Word).filter(_scope, Word.status == "not_mastered").count()
    learning_count = db.query(Word).filter(_scope, Word.status == "learning").count()
    reviewing_count = db.query(Word).filter(_scope, Word.status == "reviewing").count()
    mastered_count = db.query(Word).filter(_scope, Word.status == "mastered").count()
    today = local_today()
    # V12 修复：新词（status='new'，从未学习）不计入"今日待复习"。
    # 旧逻辑把 due_date IS NULL 的新词也算作今日到期 → 全站复习调度显示
    # "4568/4569 今日待复习"，学习数据失真。复习队列只包含已学过的词。
    due_today = db.query(Word).filter(
        _scope,
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
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """获取今日待复习单词（含新词；B4：只看本人）。"""
    today = local_today()
    # V12 修复：due 队列排除新词（new）——新词走"学习"流程而非"复习"队列
    words = db.query(Word).filter(
        scoped(Word, user),
        Word.due_date <= today
    ).filter(Word.status.in_(["learning", "reviewing"])).order_by(Word.status, Word.id).limit(limit).all()
    # P1 增强：例句/词根合并（与列表接口同一序列化层）
    examples = _load_word_examples(db, [w.id for w in words])
    root_by_word = _load_word_roots(db)
    return [_word_out(w, db, examples, root_by_word) for w in words]


@router.get("/export-pdf")
def export_words_pdf(
    deck_id: Optional[int] = None,
    status: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """单词本 PDF 导出（对标「不背单词」纸质导出；B4：仅导出本人单词）。

    支持与列表页一致的筛选参数（deck_id / status / tag / search），
    导出结果为中文 PDF，前端直接以 blob 下载。

    P2 增强：
    - 标题自动使用词库名（不再硬编码「考研核心词汇」）；
    - 单次上限提升到 5000 词，超过部分在封面明确提示（不静默截断）；
    - 输出 words.extra 中的同近义/短语（KyleBing 词库结构化数据）。
    """
    from fastapi.responses import Response
    from services import pdf_export

    q = db.query(Word).filter(scoped(Word, user))
    if deck_id is not None:
        q = q.filter(Word.deck_id == deck_id)
    if status:
        q = q.filter(Word.status == _db_status(status))
    if tag:
        q = q.filter(Word.tag == tag)
    if search:
        q = q.filter(Word.word.like(f"%{search}%"))
    rows = q.order_by(Word.id).limit(5000).all()
    truncated = False
    # 全量计数（不加载正文），用于封面提示截断
    total = q.count()
    if total > len(rows):
        truncated = True

    # 词库名（标题用）
    deck_name = None
    if deck_id is not None:
        deck = db.query(WordDeck).filter(WordDeck.id == deck_id).first()
        if deck:
            deck_name = deck.name
    title = deck_name or "考研词汇"

    words = []
    for w in rows:
        item = {
            "word": w.word,
            "phonetic": w.phonetic,
            "pos": w.pos,
            "meaning": w.meaning,
            "root": w.root,
            "example": w.example,
            "example_cn": w.example_cn,
            "tag": w.tag,
            "status": _api_status(w.status),
            "reps": w.reps,
            "extra": w.extra,
        }
        words.append(item)

    pdf_bytes = pdf_export.build_words_pdf(
        words,
        title=title,
        subtitle=f"FSRS 间隔重复 · 真题例句 · 共 {total} 词",
        truncated=truncated,
    )
    from urllib.parse import quote
    filename = f"单词本_{local_today().isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.get("/{word_id}", response_model=WordOut)
def get_word(word_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取单个单词详情。"""
    w = db.query(Word).filter(Word.id == word_id, scoped(Word, user)).first()
    if not w:
        raise HTTPException(404, "单词不存在")
    # P1 增强：例句/词根合并（与列表接口同一序列化层）
    examples = _load_word_examples(db, [w.id])
    root_by_word = _load_word_roots(db)
    return _word_out(w, db, examples, root_by_word)


@router.post("", response_model=WordOut, dependencies=[Depends(require_admin)])
def create_word(data: WordCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """添加单个单词。

    P0-1：创建前按当前用户查重（全库按 user_id 过滤）。若该用户已有相同
    word，返回 409，且 detail 为 ``{"exists": true, "word": ..., "id": 已有id}``，
    避免重复入库。``source_label`` 若传入且 ``tag`` 为空，则写入 ``tag`` 列。
    """
    # —— P0-1 查重（仅针对当前用户）——
    existing = (
        db.query(Word)
        .filter(Word.word == data.word.strip(), scoped(Word, user))
        .order_by(Word.id.asc())
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "exists": True,
                "word": existing.word,
                "id": existing.id,
                "message": "该单词已在词库中",
            },
        )

    data_dict = data.model_dump()
    if data_dict.get("status"):
        data_dict["status"] = _db_status(data_dict["status"])
    # P0-1：来源标注复用 tag 列（tag 为空时）
    source_label = data_dict.pop("source_label", None)
    if source_label and not data_dict.get("tag"):
        data_dict["tag"] = source_label[:50]
    w = Word(**data_dict)
    w.user_id = owner_id(user)  # B4：归属当前用户
    w.due_date = local_today()
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


@router.put("/{word_id}", response_model=WordOut, dependencies=[Depends(require_admin)])
def update_word(word_id: int, data: WordUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """更新单词信息。"""
    w = db.query(Word).filter(Word.id == word_id, scoped(Word, user)).first()
    if not w:
        raise HTTPException(404, "单词不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
    db.commit()
    db.refresh(w)
    return w


@router.delete("/{word_id}", dependencies=[Depends(require_admin)])
def delete_word(word_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """删除单词。"""
    w = db.query(Word).filter(Word.id == word_id, scoped(Word, user)).first()
    if not w:
        raise HTTPException(404, "单词不存在")
    db.delete(w)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# SM-2 复习调度
# --------------------------------------------------------------------------- #
def _apply_review(db: Session, w: Word, grade: int, user: User) -> Word:
    """SM-2 复习评分统一逻辑（review 接口与拼写练习共用），更新调度状态。

    使用统一的 ReviewScheduler 算法 + FSRS 统一调度表；SM-2 字段保留兼容快照。
    """
    from services.review_scheduler import ReviewScheduler
    from services.srs import fsrs

    today = local_today()

    _, new_reps, new_interval, new_ef, new_status = ReviewScheduler.calculate_next_review(
        quality=grade,
        repetitions=w.reps or 0,
        interval=w.interval or 0,
        ef=w.ease_factor or 2.5,
    )

    w.reps = new_reps
    w.interval = new_interval
    w.ease_factor = new_ef
    # 调度器返回的 'new'（从未掌握）在 DB 枚举里不存在；复习过至少算 learning
    w.status = _db_status(new_status) if new_status not in ("review", "new") else "learning"
    w.lapses = w.lapses + (1 if grade < 3 else 0)

    # FSRS：统一调度表为准；SM-2 字段保留为兼容快照
    sched = fsrs.schedule(
        db,
        item_type="word",
        item_id=int(w.id),
        rating=fsrs.rating_from_grade(grade),
        user_id=owner_id(user),  # B4：复习排程跟随操作者
    )
    w.due_date = today + datetime.timedelta(days=int(sched["interval_days"]))
    w.interval = int(sched["interval_days"])
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


@router.post("/{word_id}/review", response_model=WordOut)
def review_word(word_id: int, data: WordReview, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """SM-2 复习评分，更新调度状态（使用统一的 ReviewScheduler 算法）。"""
    w = db.query(Word).filter(Word.id == word_id, scoped(Word, user)).first()
    if not w:
        raise HTTPException(404, "单词不存在")

    _apply_review(db, w, data.grade, user)
    # P1 增强：例句/词根合并（与列表接口同一序列化层）
    examples = _load_word_examples(db, [w.id])
    root_by_word = _load_word_roots(db)
    return _word_out(w, db, examples, root_by_word)


# --------------------------------------------------------------------------- #
# 拼写练习（对标「不背单词」拼写模式）
# --------------------------------------------------------------------------- #
@router.post("/spell-check", response_model=SpellCheckOut)
def spell_check_word(
    data: SpellCheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """拼写练习：给出释义/音标，用户输入英文单词，服务端判对错。

    - 大小写不敏感、忽略首尾空白；
    - 默认自动记录一次复习：正确 → SM-2 grade=5，错误 → grade=1（重来），
      拼写练习因此同时推进间隔重复调度；
    - record_review=False 时可纯练习不干扰调度。
    """
    w = db.query(Word).filter(Word.id == data.word_id, scoped(Word, user)).first()
    if not w:
        raise HTTPException(404, "单词不存在")

    user_answer = (data.answer or "").strip()
    correct = bool(user_answer) and user_answer.lower() == (w.word or "").strip().lower()

    review_out: Optional[dict] = None
    if data.record_review:
        _apply_review(db, w, 5 if correct else 1, user)
        examples = _load_word_examples(db, [w.id])
        root_by_word = _load_word_roots(db)
        review_out = _word_out(w, db, examples, root_by_word)

    return SpellCheckOut(
        correct=correct,
        word=w.word,
        user_answer=user_answer,
        phonetic=w.phonetic,
        pos=w.pos,
        meaning=w.meaning,
        review=review_out,
    )


# --------------------------------------------------------------------------- #
# 批量导入
# --------------------------------------------------------------------------- #
@router.post("/batch-import", dependencies=[Depends(require_admin)])
def batch_import_words(data: WordBatchImport, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """批量导入单词。

    P0-1：每个词条透传 ``source_label``——若传入且 ``tag`` 为空，写入 ``tag`` 列。
    """
    count = 0
    today = local_today()
    for w_data in data.words:
        w_dict = w_data.model_dump()
        source_label = w_dict.pop("source_label", None)
        if source_label and not w_dict.get("tag"):
            w_dict["tag"] = source_label[:50]
        w = Word(**w_dict)
        w.user_id = owner_id(user)  # B4：归属当前用户
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
    # P0-1：来源标注（如「刷题生词」），透传写入 tag 列
    source_label: Optional[str] = None


@router.post("/import-text", dependencies=[Depends(require_admin)])
def import_words_from_text(data: TextImportRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
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
    today = local_today()

    # 已存在的单词集合（去重，B4：只查本人单词）
    existing_words = {
        w.word for w in db.query(Word.word).filter(scoped(Word, user)).all()
    }

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
                user_id=owner_id(user),  # B4：归属当前用户
                deck_id=data.deck_id,
                word=word[:100],
                phonetic=phonetic[:100] if phonetic else None,
                pos=pos[:50] if pos else None,
                meaning=meaning[:2000],
                status="not_mastered",  # DB 枚举无 'new'，未学即 not_mastered
                due_date=today,
                # P0-1：来源标注复用 tag 列
                tag=(data.source_label[:50] if data.source_label else None),
            )
            db.add(w)
            existing_words.add(word)
            imported += 1

        except Exception as e:
            skipped += 1
            errors.append(f"第{idx}行：{str(e)}")

    db.commit()

    # 更新词库数量（B4：校验本人词库，只统计本人单词）
    if data.deck_id:
        deck = db.query(WordDeck).filter(WordDeck.id == data.deck_id, scoped(WordDeck, user)).first()
        if deck:
            deck.word_count = db.query(Word).filter(Word.deck_id == data.deck_id, scoped(Word, user)).count()
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
@router.post("/import-excel", dependencies=[Depends(require_admin)])
async def import_words_from_excel(
    file: bytes = File(...),
    deck_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
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
    today = local_today()
    existing_words = {
        w.word for w in db.query(Word.word).filter(scoped(Word, user)).all()
    }

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
                user_id=owner_id(user),  # B4：归属当前用户
                deck_id=deck_id,
                word=word[:100],
                phonetic=str(row[col_map["phonetic"]]).strip()[:100] if "phonetic" in col_map and row[col_map["phonetic"]] else None,
                pos=str(row[col_map["pos"]]).strip()[:50] if "pos" in col_map and row[col_map["pos"]] else None,
                meaning=meaning[:2000],
                root=str(row[col_map["root"]]).strip()[:300] if "root" in col_map and row[col_map["root"]] else None,
                example=str(row[col_map["example"]]).strip() if "example" in col_map and row[col_map["example"]] else None,
                example_cn=str(row[col_map["example_cn"]]).strip() if "example_cn" in col_map and row[col_map["example_cn"]] else None,
                tag=str(row[col_map["tag"]]).strip()[:50] if "tag" in col_map and row[col_map["tag"]] else None,
                status="not_mastered",  # DB 枚举无 'new'，未学即 not_mastered
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

    # 更新词库数量（B4：校验本人词库，只统计本人单词）
    if deck_id:
        deck = db.query(WordDeck).filter(WordDeck.id == deck_id, scoped(WordDeck, user)).first()
        if deck:
            deck.word_count = db.query(Word).filter(Word.deck_id == deck_id, scoped(Word, user)).count()
            db.commit()

    return {
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:20],
    }
