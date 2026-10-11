"""pytest 全局夹具：**强制测试库隔离**。

铁律（红线，勿删）：
    测试绝不允许碰 ``D:\\平台\\database\\kaoyan.db``（283MB 真实数据）。
    本文件在**导入任何项目模块之前**把 ``DATABASE_PATH`` 环境变量改写到
    ``tempfile.mkdtemp()`` 下的临时库。因为 ``database.py`` 在 import 时就会
    ``load_dotenv(.env)`` 并读取 ``DATABASE_PATH``，而 ``load_dotenv`` 默认
    ``override=False``（不覆盖已存在的环境变量），所以此处的 ``setenv``
    优先级高于 ``.env`` 里的 ``DATABASE_PATH=D:\\平台\\database\\kaoyan.db``。

    副作用检查：``test_no_pollution_guard`` 会断言真实库文件在测试期间
    mtime 未变化。
"""
from __future__ import annotations

import os
import sys
import tempfile
import shutil

import pytest

# --------------------------------------------------------------------------- #
# 0. 路径准备 + 测试库隔离（必须在 import database / main 之前）
# --------------------------------------------------------------------------- #
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# 真实库路径（仅用于"未被污染"断言，绝不用于连接）
REAL_DB_PATH = r"D:\平台\database\kaoyan.db"

_TMP_DB_DIR = tempfile.mkdtemp(prefix="kaoyan_qa_testdb_")
TEST_DB_PATH = os.path.join(_TMP_DB_DIR, "qa_test.db")

# 关键：先设环境变量，再 import database。load_dotenv(override=False) 不会覆盖它。
os.environ["DATABASE_PATH"] = TEST_DB_PATH
# 关掉 APScheduler 之类在 import 阶段就起线程的副作用（若引擎支持）
os.environ.setdefault("KAOYAN_DISABLE_SCHEDULER", "1")


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """会话结束清理临时库目录（best-effort，Windows 上文件句柄可能延迟释放）。"""
    try:
        shutil.rmtree(_TMP_DB_DIR, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# 1. 应用 / 客户端夹具
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def app_module():
    """导入 main 模块（此时 database 已指向临时库）。"""
    from main import app as fastapi_app

    return fastapi_app


@pytest.fixture(scope="session")
def db_schema(app_module):
    """在临时库上建表（含 Module A 附加表 + FTS/vec 表）。"""
    from database import Base, engine, SessionLocal
    import models  # noqa: F401  确保所有 ORM 模型被注册到 Base.metadata
    from services.module_a_schema import ensure_module_a_schema

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        ensure_module_a_schema(session)
        session.commit()
    finally:
        session.close()
    return engine


@pytest.fixture(scope="session")
def client(app_module, db_schema):  # noqa: ARG001
    """会话级同步 ASGI 客户端（不触发 startup 事件，避免起后台线程）。"""
    from asgi_client import ASGIClient

    with ASGIClient(app_module) as c:
        yield c


@pytest.fixture(scope="session")
def sample_data(db_schema):  # noqa: ARG001
    """写入最小可用的示例数据，让带路径参数的接口有真实 id 可用。

    只写"读接口需要"的表：goals / tasks / quiz_questions / error_records /
    documents / words / papers / ebbinghaus_items / exam_blueprints 等。
    幂等：重复执行不会重复插入（先查后插）。
    """
    import datetime
    from database import SessionLocal
    from models import (
        Goal, Task, QuizQuestion, ErrorRecord, Document, Word, WordDeck,
        Paper, EbbinghausItem, KnowledgePoint, Flashcard, CustomLink,
        EarlyBirdRecord, PhasePlan,
    )

    db = SessionLocal()
    try:
        today = datetime.date.today()

        # ---- Goal（/api/goals 期望恰好一条）----
        if db.query(Goal).count() == 0:
            db.add(Goal(
                exam_date=today + datetime.timedelta(days=180),
                total_score_target=360,
                politics_target=65, english_target=65,
                math_target=115, major_target=115,
                university="贵州大学", major="电子信息（0854）",
                remark="QA 测试数据",
            ))

        # ---- Task ----
        if db.query(Task).count() == 0:
            db.add_all([
                Task(title="QA-数学复习", subject="数学", task_type="学习",
                     stage="基础", status="pending", due_date=today, priority=5),
                Task(title="QA-英语刷题", subject="英语", task_type="刷题",
                     stage="基础", status="done", due_date=today,
                     priority=3,
                     completed_at=datetime.datetime.now(datetime.UTC)),
            ])

        # ---- QuizQuestion ----
        if db.query(QuizQuestion).count() == 0:
            db.add_all([
                QuizQuestion(
                    content="QA 测试题：1+1=?", options=["1", "2", "3", "4"],
                    answer="B", analysis="QA analysis", subject="数学",
                    chapter="QA-章节", knowledge_point="QA-知识点",
                    difficulty=2, source="真题", question_type="single",
                ),
                QuizQuestion(
                    content="QA 测试题：word 'ubiquitous' means?",
                    options=["rare", "everywhere", "invisible", "dangerous"],
                    answer="B", analysis="everywhere present", subject="英语",
                    chapter="QA-阅读", knowledge_point="QA-词汇",
                    difficulty=2, source="模拟", question_type="single",
                ),
            ])

        # ---- ErrorRecord ----
        # 字段口径见 models.py:143 —— 没有 chapter / knowledge_point / error_type /
        # user_answer，而是 content / my_answer / correct_answer / error_reason。
        if db.query(ErrorRecord).count() == 0:
            q = db.query(QuizQuestion).filter(QuizQuestion.subject == "数学").first()
            db.add(ErrorRecord(
                question_id=q.id if q else None,
                content="QA 错题内容",
                my_answer="A", correct_answer="B",
                error_reason="概念不清", subject="数学",
                accuracy=0.0, review_count=0, status="active",
            ))

        # ---- Document ----
        # 字段：file_name / size / index_status / knowledge_point_count（不是 title/filename）
        if db.query(Document).count() == 0:
            db.add(Document(
                file_name="qa.txt", file_path="qa.txt",
                file_type="txt", size=100,
                subject="数学", doc_type="txt",
                index_status="completed", knowledge_point_count=1,
                parse_progress=100, content="QA 文档正文内容",
            ))

        # ---- KnowledgePoint ----
        # 字段：mastery / exam_frequency / difficulty（不是 level / importance）
        if db.query(KnowledgePoint).count() == 0:
            db.add(KnowledgePoint(
                name="QA-知识点", subject="数学", chapter="QA-章节",
                mastery=0, exam_frequency=1, difficulty=2,
                question_count=1,
            ))

        # ---- WordDeck / Word ----
        # WordDeck 字段：word_count（不是 total_words）
        if db.query(WordDeck).count() == 0:
            db.add(WordDeck(name="QA-核心词汇", description="QA deck",
                            source="manual", word_count=2, color="#1890ff"))
        if db.query(Word).count() == 0:
            deck = db.query(WordDeck).first()
            db.add_all([
                Word(word="ubiquitous", meaning="无处不在", phonetic="/juːˈbɪkwɪtəs/",
                     pos="adj", deck_id=deck.id if deck else None,
                     status="new", ease_factor=2.5, interval=0, reps=0, lapses=0),
                Word(word="ephemeral", meaning="短暂的", phonetic="/ɪˈfemərəl/",
                     pos="adj", deck_id=deck.id if deck else None,
                     status="new", ease_factor=2.5, interval=0, reps=0, lapses=0),
            ])

        # ---- Paper ----
        # 字段：title / subject / description / rules / total_score（无 year/paper_type）
        if db.query(Paper).count() == 0:
            db.add(Paper(
                title="QA 测试试卷", subject="数学",
                description="QA paper", rules="{}", total_score=100,
            ))

        # ---- EbbinghausItem（planner due 计算需要）----
        # 注意字段口径：learn_date/content 为 NOT NULL；复习节点是
        # review_5min/30min/12h/1d/2d/4d/7d/15d/1m 九个独立列，
        # **没有** next_review_at / interval / repetitions / knowledge_point_id。
        if db.query(EbbinghausItem).count() == 0:
            now = datetime.datetime.now(datetime.UTC)
            past = now - datetime.timedelta(days=2)
            db.add(EbbinghausItem(
                seq=1,
                learn_date=past,
                content="QA 艾宾浩斯条目",
                subject="数学",
                # 5min/1d 节点已过期 → 应出现在 due 列表
                review_5min=past + datetime.timedelta(minutes=5),
                review_30min=past + datetime.timedelta(minutes=30),
                review_12h=past + datetime.timedelta(hours=12),
                review_1d=past + datetime.timedelta(days=1),
                # 7d 节点未到期 → 不应出现
                review_7d=now + datetime.timedelta(days=5),
                mastered=False,
            ))

        # ---- EarlyBirdRecord（streak 计算需要，今天 + 昨天）----
        if db.query(EarlyBirdRecord).count() == 0:
            import datetime as _dt
            db.add_all([
                EarlyBirdRecord(
                    day_num=1, date=_dt.date.today(),
                    wake_time=_dt.time(6, 30), sleep_time=_dt.time(23, 0),
                    note="QA today",
                ),
                EarlyBirdRecord(
                    day_num=2,
                    date=_dt.date.today() - _dt.timedelta(days=1),
                    wake_time=_dt.time(7, 0), sleep_time=_dt.time(23, 30),
                    note="QA yesterday",
                ),
            ])

        # ---- PhasePlan（/api/planner/phase/{plan_id}/reviews 需要）----
        if db.query(PhasePlan).count() == 0:
            db.add(PhasePlan(
                name="QA 阶段一",
                start_date=datetime.date.today(),
                end_date=datetime.date.today() + datetime.timedelta(days=40),
                cycle_days=40,
                tasks=[],
            ))

        # ---- Flashcard ----
        # 字段：front / back / next_review / mastery（无 subject / next_review_at）
        if db.query(Flashcard).count() == 0:
            kp = db.query(KnowledgePoint).first()
            db.add(Flashcard(
                front="QA 正面", back="QA 背面",
                knowledge_point_id=kp.id if kp else None,
                next_review=datetime.datetime.now(datetime.UTC),
                review_count=0, interval=1, ease_factor=2.5, mastery="new",
            ))

        # ---- CustomLink ----
        # 字段：name / url / category / icon / sort_order（不是 title / order）
        if db.query(CustomLink).count() == 0:
            db.add(CustomLink(name="QA 链接", url="https://example.com",
                              category="工具", icon="link", sort_order=1))

        db.commit()

        # 回读真实 id 供带路径参数的用例使用
        def _id(model):
            obj = db.query(model).first()
            return obj.id if obj else 1

        ids = {
            "task_id": _id(Task),
            "question_id": _id(QuizQuestion),
            "error_id": _id(ErrorRecord),
            "doc_id": _id(Document),
            "word_id": _id(Word),
            "paper_id": _id(Paper),
            "kp_id": _id(KnowledgePoint),
            "flashcard_id": _id(Flashcard),
            "deck_id": _id(WordDeck),
            "plan_id": _id(PhasePlan),
            "ebbinghaus_id": _id(EbbinghausItem),
        }
        return ids
    finally:
        db.close()


@pytest.fixture(scope="session")
def real_db_mtime_guard():
    """记录真实库 mtime，供"未污染"断言比对。"""
    if os.path.exists(REAL_DB_PATH):
        return os.stat(REAL_DB_PATH).st_mtime_ns
    return None
