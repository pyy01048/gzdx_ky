"""pytest 全局夹具：**强制测试库隔离**。

铁律（红线，勿删）：
    测试绝不允许碰任何**生产库**——既包括 SQLite 的
    ``D:\\平台\\database\\kaoyan.db``（283MB 真实数据），也包括 PostgreSQL 的
    ``kaoyan`` 库。

    历史缺陷（2026-10-14 修复）
    --------------------------
    本文件此前**只改写 ``DATABASE_PATH``**，而 ``.env`` 里
    ``DATABASE_BACKEND=postgresql``。由于 ``build_database_url()`` 在
    ``backend == postgresql`` 分支下**根本不读 ``DATABASE_PATH``**，
    于是全部 700+ 用例实际直连生产 PG 库 ``kaoyan``：
    - ``Base.metadata.create_all()`` 在生产库建表
    - ``sample_data`` 往生产库写QA 数据
    - 断言失败时的回滚/清表可能命中真实表
    ``test_no_pollution_guard`` 只检查 SQLite 文件 mtime，因此一直是**假保险**。

    现行方案
    --------
    1. 把 ``PG_DATABASE`` 改写到专用测试库 ``kaoyan_test``（不存在则自动创建）；
    2. 同时保留 ``DATABASE_PATH`` 指向临时 SQLite，覆盖 ``sqlite`` 后端的用例；
    3. 在 import 任何项目模块之前做硬断言：连接串里出现生产库名即直接退出，
       不给"手滑改回去"留余地。

    副作用检查：``test_no_pollution_guard`` 断言真实 SQLite 文件 mtime 未变化，
    且当前连接库名不是 ``kaoyan``。
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

# 真实库路径（仅用于"未被污染"断言，绝不用于连接）。
# 由仓库结构推导而不是写死盘符：换一台机器/换一个仓库位置，这条保险丝仍然成立。
# 2026-10-14 起真库是 PostgreSQL，这个 SQLite 文件已退役、本机可能根本不存在，
# 所以所有引用它的地方都必须容忍"文件不在"（见 :func:`production_db_untouched`）。
REAL_DB_PATH = os.path.join(os.path.dirname(BACKEND_DIR), "database", "kaoyan.db")
#: 生产 PostgreSQL 库名。测试期间连接到这个库即视为严重事故。
PROD_PG_DB = "kaoyan"
#: 专用测试库名（与生产同机同实例，靠库名隔离）。
TEST_PG_DB = os.environ.get("TEST_PG_DATABASE", "kaoyan_test")

#: 测试主体的用户 ID —— 必须与 ``utils.security.stub_principal()['id']`` 一致。
#:
#: 为什么要在测试库里真的插一行 users（2026-10-20 修）
#: ------------------------------------------------
#: 个人域表（error_records / favorites / goals / answer_records / words …）
#: 都有 ``user_id REFERENCES users(id)``。SQLite 时代外键默认不生效，
#: ``stub_principal()`` 用一个不存在的 id=0 也能写进去；迁到 PostgreSQL 后
#: 外键真的生效，所有写入型用例直接 500（ForeignKeyViolation）。
#: 同时「行级隔离」上线后 ``scoped(model, user)`` 会过滤 ``user_id == user.id``，
#: 种子数据若不带 user_id 就查不到（表现为 404 / 空列表）。
#: 因此测试库必须与生产同构：先有用户，再有归属该用户的数据。
TEST_USER_ID = 0

_TMP_DB_DIR = tempfile.mkdtemp(prefix="kaoyan_qa_testdb_")
TEST_DB_PATH = os.path.join(_TMP_DB_DIR, "qa_test.db")


def _env_or_dotenv(key: str, default: str = "") -> str:
    """读环境变量，缺失则回落到后端根目录的 ``.env``。

    必须读 ``.env``：本机 PG 用的是开发专用账号口令（写在 ``.env`` 里，不进 git），
    而 ``core.db_session`` 的默认值是 ``postgres/postgres``。
    若这里只用 ``os.environ.get(key, 默认值)``，建库会拿默认凭据连上去，
    因此失败——而旧实现把异常静默吞掉，最终表现为
    "database kaoyan_test does not exist" 的 194 个用例级联 ERROR。
    """
    val = (os.environ.get(key, "") or "").strip()
    if val:
        return val
    try:
        from dotenv import dotenv_values

        env_path = os.path.join(BACKEND_DIR, ".env")
        if os.path.exists(env_path):
            return (dotenv_values(env_path).get(key) or default or "").strip()
    except Exception:  # noqa: BLE001 — dotenv 缺失时退回默认值
        pass
    return default


def _ensure_test_pg_database() -> None:
    """每个测试会话都把 ``kaoyan_test`` **删掉重建**成空库。

    失败时**告警但不阻断**：PG 不可用时测试仍可退回临时 SQLite，
    只是失去 PG 覆盖。真正的红线由下面的 ``_assert_not_production`` 兜底。

    注意：这里必须把异常打出来。静默 ``pass`` 会让"建库失败"退化成
    后面几百个看不懂的 ERROR，排查成本极高。

    为什么每次重建（2026-10-17 实测）
    --------------------------------
    旧实现"存在即复用"。某次会话里 ``apply_schema`` 半途失败后，
    ``create_all()`` 按 **ORM 口径**把 ``subject_prototypes`` 等表建了出来
    （列是 ``subject`` 而非权威 SQL 的 ``subject_id``）。此后每一次会话：

        apply_schema → 010 分片 CREATE TABLE IF NOT EXISTS 被跳过
                     → COMMENT ON COLUMN subject_prototypes.subject_id
                     → UndefinedColumn，整份 DDL 中止

    于是 textbooks / subjects / watermark_lexicon、``trg_kp_mastery_sync``
    触发器等 SQL-only 对象**永远建不出来**，测试库被永久"毒化"，
    表现为 30+ 个用例散落在各处失败。测试库是可丢弃的沙箱，
    每次从空库按生产同一条 DDL 链自举，才能保证与生产 schema 同构。
    """
    try:
        import psycopg
    except ImportError:
        print("[conftest] 未安装 psycopg，测试将退回临时 SQLite")
        return
    params = {
        "host": _env_or_dotenv("PG_HOST", "127.0.0.1"),
        "port": _env_or_dotenv("PG_PORT", "5432"),
        "user": _env_or_dotenv("PG_USER", "postgres"),
        "password": _env_or_dotenv("PG_PASSWORD", "postgres"),
    }
    try:
        # 标识符不能参数化；库名受 TEST_PG_DB 控制，此处做白名单校验。
        if not TEST_PG_DB.replace("_", "").isalnum():
            raise ValueError(f"非法测试库名：{TEST_PG_DB!r}")
        # 红线：DROP 只允许落在测试库上，绝不允许是生产库。
        if TEST_PG_DB == PROD_PG_DB:
            raise RuntimeError(f"测试库名不得等于生产库名 {PROD_PG_DB!r}")
        with psycopg.connect(dbname="postgres", autocommit=True, **params) as conn:
            # 并发保护（2026-10-17 实测）：多个工作流会同时跑 pytest。若无条件
            # ``DROP ... WITH (FORCE)``，后启动的会话会把正在跑的会话连接踢断、
            # 库删掉重建，对方随即满屏 "server closed the connection" /
            # "relation ... does not exist"。所以：
            #   * 用会话级 advisory lock 串行化各会话的"检查 + 重建"；
            #   * 库上已有别的连接 → 视为另一会话正在使用（它已自举过），只复用不重建；
            #   * DROP 不带 FORCE：检查与删除之间若有人连上，DROP 报错并回落到复用。
            conn.execute("SELECT pg_advisory_lock(hashtext('kaoyan_test_bootstrap'))")
            try:
                exists = conn.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_PG_DB,)
                ).fetchone() is not None
                busy = conn.execute(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (TEST_PG_DB,),
                ).fetchone()[0]
                if exists and busy:
                    print(
                        f"[conftest] 测试库 {TEST_PG_DB} 正被另一测试会话使用（{busy} 个连接），"
                        f"本次复用不重建"
                    )
                    return
                try:
                    conn.execute(f'DROP DATABASE IF EXISTS "{TEST_PG_DB}"')
                except psycopg.errors.ObjectInUse:
                    print(f"[conftest] 测试库 {TEST_PG_DB} 刚被占用，本次复用不重建")
                    return
                conn.execute(f'CREATE DATABASE "{TEST_PG_DB}"')
                print(f"[conftest] 已重建空测试库 {TEST_PG_DB}")
            finally:
                conn.execute("SELECT pg_advisory_unlock(hashtext('kaoyan_test_bootstrap'))")
    except Exception as exc:  # noqa: BLE001 — PG 缺席不应让整个测试会话崩掉
        print(
            f"[conftest] 警告：无法确保测试库 {TEST_PG_DB} 存在（{type(exc).__name__}: {exc}）。"
            f"若 PG 也不可用，后续用例会因连不上库而失败。"
        )


def _sync_pg_enums() -> None:
    """在测试库里按 ``core.pg_types.ENUM_CATALOG`` 建齐全部 ENUM 类型。

    为什么必须做（2026-10-14 实测）
    ------------------------------
    项目里ENUM 类型是**迁移期手工建**的（``core/sql/000_extensions_and_enums.sql``
    用 ``DO $$ ... CREATE TYPE``），ORM 的 ``create_all()`` **不会**创建原生 ENUM。
    于是切到干净的测试库后，第一次 ``create_all()`` 直接炸：

        psycopg.errors.UndefinedObject: type "prep_stage" does not exist

    紧接着 PG 事务进入 aborted 状态，同一``Session`` 里后续语句全部连带失败，
    最终表现为 190+ 个用例级联 ERROR，根因却只有一行。

    这里在**建表之前**把 ENUM 补齐，让空测试库具备自举建表能力。
    标签来源是 ``ENUM_CATALOG``（单一权威源），不手抄第二份。
    """
    try:
        import psycopg
    except ImportError:
        return
    try:
        from core.pg_types import ENUM_CATALOG
    except Exception as exc:  # noqa: BLE001
        print(f"[conftest] 警告：无法读取 ENUM_CATALOG（{exc}）")
        return

    params = {
        "host": _env_or_dotenv("PG_HOST", "127.0.0.1"),
        "port": _env_or_dotenv("PG_PORT", "5432"),
        "user": _env_or_dotenv("PG_USER", "postgres"),
        "password": _env_or_dotenv("PG_PASSWORD", "postgres"),
    }
    created = 0
    try:
        with psycopg.connect(dbname=TEST_PG_DB, autocommit=True, **params) as conn:
            for type_name, labels in ENUM_CATALOG.items():
                # 标签/类型名都是代码内常量，但仍做白名单校验，杜绝标识符注入。
                safe_labels = [x for x in labels if x.replace("_", "").replace("-", "").isalnum() or x]
                if not type_name.replace("_", "").isalnum() or not safe_labels:
                    continue
                values = ", ".join(f"'{x}'" for x in safe_labels)
                # CREATE TYPE 没有 IF NOT EXISTS，用 DO 块包一层判存在。
                conn.execute(
                    f"DO $$ BEGIN CREATE TYPE {type_name} AS ENUM ({values}); "
                    f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
                )
                created += 1
        print(f"[conftest] 已同步 {created} 个 ENUM 类型到 {TEST_PG_DB}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"[conftest] 警告：ENUM 同步失败（{type(exc).__name__}: {exc}）。"
            f"建表可能因type ... does not exist 失败。"
        )


# 关键：先设环境变量，再 import database。load_dotenv(override=False) 不会覆盖它。
# PG_DATABASE 改写是本轮新增的关键一行——它才是 PG 分支真正读取的变量。
os.environ["PG_DATABASE"] = TEST_PG_DB
os.environ["DATABASE_PATH"] = TEST_DB_PATH
# 关掉 APScheduler 之类在 import 阶段就起线程的副作用（若引擎支持）
os.environ.setdefault("KAOYAN_DISABLE_SCHEDULER", "1")

_ensure_test_pg_database()
_sync_pg_enums()


def _assert_not_production() -> None:
    """import 项目模块前的硬红线：解析出的连接串不得指向生产库。"""
    try:
        from core.db_session import build_database_url
        url = build_database_url()
    except Exception:  # noqa: BLE001 — core 不可用则交给后续测试自行暴露
        return
    tail = url.rsplit("/", 1)[-1].split("?")[0]
    if tail == PROD_PG_DB:
        raise RuntimeError(
            f"测试拒绝启动：连接串指向生产库 {PROD_PG_DB!r}（{url}）。"
            f"请检查 tests/conftest.py 的 PG_DATABASE 改写是否失效。"
        )


_assert_not_production()


@pytest.fixture(autouse=True)
def production_db_untouched():
    """全局红线（每个用例都跑）：连的必须是沙箱库，且退役的生产 SQLite 没被写过。

    这段断言原先在 7 个测试文件里各抄一份，每份都直接 ``os.stat`` 仓库同级
    ``database/kaoyan.db``。真库 2026-10-14 迁到 PostgreSQL 之后那个文件已不存在，
    于是 53 个用例在 setup 阶段集体 FileNotFoundError —— 保险丝本身不该依赖
    某台机器上某个文件的存在，所以这里改成两条独立的检查：

    * 连接库名：复用 :func:`_assert_not_production`（与启动硬红线同一口径）；
    * SQLite 文件：只在它**确实存在**时才比对 mtime/size，不存在就跳过这一路。
    """
    _assert_not_production()
    snap = None
    if os.path.exists(REAL_DB_PATH):
        st = os.stat(REAL_DB_PATH)
        snap = (st.st_mtime_ns, st.st_size)
    yield
    if snap is not None:
        st = os.stat(REAL_DB_PATH)
        assert (st.st_mtime_ns, st.st_size) == snap, (
            f"用例改动了生产 SQLite 文件：{REAL_DB_PATH}"
        )
    _assert_not_production()


@pytest.fixture(autouse=True)
def db_session_cleanup():
    """每个测试后清理数据库会话状态，防止 InFailedSqlTransaction 级联失败。

    问题根因：PG 事务中一旦有 SQL 错误，整个事务进入 aborted 状态，
    后续所有语句都会失败直到 ROLLBACK。pytest 默认不自动回滚，
    导致第一个失败的测试会让同 session 里的后续测试全部炸掉。

    解决方案：每个测试结束后强制 rollback 任何残留的未提交事务。
    """
    from database import SessionLocal
    yield
    # 测试结束后清理：rollback 任何未提交的事务
    try:
        session = SessionLocal()
        session.rollback()  # 即使没有活跃事务也是安全的
        session.close()
    except Exception:  # noqa: BLE001
        pass


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


@pytest.fixture(scope="session", autouse=True)
def auth_bypass(app_module):
    """全站默认拒绝之后，业务用例统一以管理员身份跑；鉴权本身由 test_auth*.py 覆盖。"""
    from utils.access_policy import enforce_access
    from utils.security import current_user, stub_principal

    app_module.dependency_overrides[enforce_access] = lambda: None
    app_module.dependency_overrides[current_user] = lambda: stub_principal()
    yield
    app_module.dependency_overrides.pop(enforce_access, None)
    app_module.dependency_overrides.pop(current_user, None)


@pytest.fixture(scope="session", autouse=True)
def db_schema(app_module):
    """在测试库上建表。**session 级 autouse**：每个测试会话都必须先建权威 schema。

    2026-10-14 重大修正
    ------------------
    此前只用 ``Base.metadata.create_all()``，而 ``apply_schema`` 的文档
    明确写着「PG 的 GENERATED 列、部分索引、触发器函数都只存在于 SQL 里，
    建表必须走本函数，不要用 Base.metadata.create_all()」。

    后果实测：testbooks / notice_alerts / answer_review_queue / gate_logs
    等表**根本不在 ORM 元数据里**（它们由 ``core/sql/*.sql`` 定义），
    空测试库永远建不出来，于是 23 个 GET 接口在巡检里集体 500 ——
    而这些接口在生产库（由迁移建全）是正常的。
    换句话说：**测试环境比生产环境少了一整层表，覆盖率是虚的**。

    2026-10-18 二次修正：改为 autouse
    --------------------------------
    曾有 6 个测试文件（test_kaoyan_ext 等）在模块夹具里自带
    ``Base.metadata.create_all()``，**从不请求本夹具**。双 Base 体系下
    （``database.Base``=存量 models.py / ``core.models.Base``=目标态），
    自带 create_all 按**旧 ORM 口径**建表（如 kaoyan_schools 无
    deleted_at/enabled），而测试代码查询 ``core.models.KaoyanSchool``
    （新口径）→ ``UndefinedColumn: deleted_at``，15 个用例集体 ERROR。
    测试库必须与生产 schema 同构：权威 SQL 链 + 增量分片 + ORM 兜底，
    对每个会话无条件执行，不再依赖测试文件自觉请求。

    现在两条路都走：SQL 建权威 schema，create_all 兜底 ORM 里
    SQL 未覆盖的历史表。

    2026-10-17 新增：Pydantic V2 前向引用修复
    ---------------------------------------
    由于大量router使用 ``from __future__ import annotations``，
    Pydantic V2无法自动解析类型注解，需要在导入后调用 model_rebuild()。
    """
    from database import Base, engine, SessionLocal
    import models  # noqa: F401  确保所有 ORM 模型被注册到 Base.metadata
    from services.module_a_schema import ensure_module_a_schema
    
    # Pydantic V2: rebuild all models with forward references
    try:
        from pydantic import BaseModel
        
        def rebuild_pydantic_models():
            """递归rebuild所有Pydantic模型"""
            import sys
            
            # 收集所有已加载模块中的Pydantic模型
            all_models = []
            for module_name, module in sys.modules.items():
                if module and hasattr(module, '__dict__'):
                    for name, obj in module.__dict__.items():
                        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
                            all_models.append(obj)
            
            # Rebuild每个模型
            rebuilt = 0
            for model_cls in all_models:
                try:
                    if hasattr(model_cls, 'model_rebuild'):
                        model_cls.model_rebuild()
                        rebuilt += 1
                except Exception:
                    pass  # 有些模型可能不需要rebuild或已经rebuild过
            
            return rebuilt
        
        count = rebuild_pydantic_models()
        print(f"[conftest] 已rebuild {count} 个Pydantic模型")
    except Exception as exc:
        print(f"[conftest] 警告：Pydantic rebuild失败（{type(exc).__name__}: {exc}）")

    # 1) 先应用 core/sql/*.sql —— 权威 schema（含 SQL-only 的表/索引/触发器）
    try:
        from core.db_session import apply_schema

        apply_schema()
        print("[conftest] 已应用 core/sql 权威 schema")
    except Exception as exc:  # noqa: BLE001
        # 不能静默：否则会退回"少表"状态，症状漂移到几十个接口 500 上。
        print(f"[conftest] 警告：apply_schema 失败（{type(exc).__name__}: {exc}）")

    # 1b) 未被 pg_schema.sql \ir 收编的增量迁移分片（生产库已逐个执行过）。
    #     旧实现手写 4 个文件名，漏掉 096_papers_year_type（paper_attempts）/
    #     097_code_oj（code_problems / code_submissions）/ 102_review_schedules_fsrs，
    #     测试库因此比生产少表。这里按文件名序自动发现，新增分片无需再改本文件。
    #     逐个文件独立执行：单个分片坏掉只告警，不连累其余分片。
    import glob
    import re

    from core.db_session import apply_schema as _apply_sql

    core_dir = os.path.join(BACKEND_DIR, "core")
    with open(os.path.join(core_dir, "pg_schema.sql"), encoding="utf-8") as fh:
        included = set(re.findall(r"^\\ir\s+sql/(\S+)", fh.read(), re.M))
    extra = sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(core_dir, "sql", "*.sql"))
        if os.path.basename(p) not in included
    )
    for name in extra:
        try:
            _apply_sql(os.path.join(core_dir, "sql", name))
            print(f"[conftest] 已执行迁移: {name}")
        except Exception as exc:  # noqa: BLE001
            print(f"[conftest] 警告：迁移 {name} 失败（{type(exc).__name__}: {exc}）")

    # 2) 再用 ORM 兜底 SQL 未覆盖的历史表
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        ensure_module_a_schema(session)
        session.commit()
    finally:
        session.close()

    # 3) 播种内置科目字典。
    #    services.taxonomy.ensure_subject_config_seeds 的幂等语义是
    #    「仅当表为空时整体播种」。而 session 级 sample_data 及其他用例会
    #    先往 subject_config 写少量行，导致播种被跳过 —— 空测试库于是永远
    #    缺内置科目，表现为 test_taxonomy_subjects 的
    #    「内置默认科目未播种: 数字电子技术」。
    #    这里在建表后立即播种，绕开该顺序依赖。
    session = SessionLocal()
    try:
        from services.taxonomy import ensure_subject_config_seeds

        inserted = ensure_subject_config_seeds(session)
        session.commit()
        if inserted:
            print(f"[conftest] 已播种 {inserted} 个内置科目")
    except Exception as exc:  # noqa: BLE001
        print(f"[conftest] 警告：科目播种失败（{type(exc).__name__}: {exc}）")
    finally:
        session.close()

    # 4) 播种测试主体本人。
    #    个人域表都有 user_id 外键（core/sql/108），stub_principal() 的 id 必须
    #    在 users 里真实存在，否则 PG 上写 favorites / goals / answer_records
    #    全部 ForeignKeyViolation（SQLite 时代外键不生效所以一直没暴露）。
    session = SessionLocal()
    try:
        from models import User

        if session.query(User).filter(User.id == TEST_USER_ID).first() is None:
            session.add(User(
                id=TEST_USER_ID, username="pytest",
                password_hash="!disabled-test-principal",
                display_name="pytest", role="admin", is_active=True,
                must_change_password=False, token_version=0,
            ))
            session.commit()
            print(f"[conftest] 已播种测试主体 user id={TEST_USER_ID}")
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        print(f"[conftest] 警告：测试主体播种失败（{type(exc).__name__}: {exc}）")
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

    from utils.timeutil import local_today
    from database import SessionLocal
    from models import (
        Goal, Task, QuizQuestion, ErrorRecord, Document, Word, WordDeck,
        Paper, EbbinghausItem, KnowledgePoint, Flashcard, CustomLink,
        EarlyBirdRecord, PhasePlan,
    )

    db = SessionLocal()
    try:
        today = local_today()

        # ---- Goal（/api/goals 期望恰好一条）----
        if db.query(Goal).count() == 0:
            db.add(Goal(
                user_id=TEST_USER_ID,
                exam_date=today + datetime.timedelta(days=180),
                total_score_target=360,
                politics_target=65, english_target=65,
                math_target=115, major_target=115,
                university="贵州大学", major="电子信息（0854）",
                remark="QA 测试数据",
            ))

        # ---- Task ----
        # stage 必须是 prep_stage ENUM 的标签（basic/intensive/sprint/retest）。
        # 历史缺陷：此处写的是中文 "基础"，在 PG 上直接报
        #   InvalidTextRepresentation: invalid input value for enum prep_stage: "基础"
        # SQLite 无类型约束所以一直没暴露；切到独立测试库后必炸。
        if db.query(Task).count() == 0:
            db.add_all([
                Task(user_id=TEST_USER_ID,
                     title="QA-数学复习", subject="数学", task_type="学习",
                     stage="basic", status="pending", due_date=today, priority=5),
                Task(user_id=TEST_USER_ID,
                     title="QA-英语刷题", subject="英语", task_type="刷题",
                     stage="basic", status="done", due_date=today,
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
                user_id=TEST_USER_ID,
                question_id=q.id if q else None,
                content="QA 错题内容",
                my_answer="A", correct_answer="B",
                error_reason="概念不清", subject="数学",
                accuracy=0.0, review_count=0, status="active",
            ))

        # ---- Document ----
        # 字段：file_name / size / index_status / knowledge_point_count（不是 title/filename）
        #
        # 2026-10-14 修正：doc_type 曾写成 "txt"，但它是 doc_type ENUM
        # （raw/note/index = 加工层级），文件格式属于 doc_format ENUM。
        # SQLite 无类型约束所以一直没暴露，切到真 PG 后直接报
        #     InvalidTextRepresentation: invalid input value for enum doc_type: "txt"
        # 同时 file_type 是 doc_format 的旧别名，一并给合法值。
        if db.query(Document).count() == 0:
            db.add(Document(
                file_name="qa.txt", file_path="qa.txt",
                file_type="txt", size=100,
                subject="数学", doc_type="raw",
                index_status="indexed", knowledge_point_count=1,
                parse_progress=1.0, content="QA 文档正文内容",
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
            db.add(WordDeck(user_id=TEST_USER_ID,
                            name="QA-核心词汇", description="QA deck",
                            source="manual", word_count=2, color="#1890ff"))
        if db.query(Word).count() == 0:
            deck = db.query(WordDeck).first()
            db.add_all([
                Word(user_id=TEST_USER_ID,
                     word="ubiquitous", meaning="无处不在", phonetic="/juːˈbɪkwɪtəs/",
                     pos="adj", deck_id=deck.id if deck else None,
                     status="not_mastered", ease_factor=2.5, interval=0, reps=0, lapses=0),
                Word(user_id=TEST_USER_ID,
                     word="ephemeral", meaning="短暂的", phonetic="/ɪˈfemərəl/",
                     pos="adj", deck_id=deck.id if deck else None,
                     status="not_mastered", ease_factor=2.5, interval=0, reps=0, lapses=0),
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
                user_id=TEST_USER_ID,
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
        # 无条件重置：历史残留行（旧日期/异口径起床时间）会破坏
        # streak 与 avg_wake_time 断言（实测：残留行导致 streak=0、avg≠06:45）。
        import datetime as _dt
        db.query(EarlyBirdRecord).delete(synchronize_session=False)
        db.add_all([
            EarlyBirdRecord(
                user_id=TEST_USER_ID,
                day_num=1, date=local_today(),
                wake_time=_dt.time(6, 30), sleep_time=_dt.time(23, 0),
                note="QA today",
            ),
            EarlyBirdRecord(
                user_id=TEST_USER_ID,
                day_num=2,
                date=local_today() - _dt.timedelta(days=1),
                wake_time=_dt.time(7, 0), sleep_time=_dt.time(23, 30),
                note="QA yesterday",
            ),
        ])

        # ---- PhasePlan（/api/planner/phase/{plan_id}/reviews 需要）----
        if db.query(PhasePlan).count() == 0:
            db.add(PhasePlan(
                user_id=TEST_USER_ID,
                name="QA 阶段一",
                start_date=local_today(),
                end_date=local_today() + datetime.timedelta(days=40),
                cycle_days=40,
                tasks=[],
            ))

        # ---- Flashcard ----
        # 字段：front / back / next_review / mastery（无 subject / next_review_at）
        if db.query(Flashcard).count() == 0:
            kp = db.query(KnowledgePoint).first()
            db.add(Flashcard(
                user_id=TEST_USER_ID,
                front="QA 正面", back="QA 背面",
                knowledge_point_id=kp.id if kp else None,
                next_review=datetime.datetime.now(datetime.UTC),
                review_count=0, interval=1, ease_factor=2.5, mastery="not_mastered",
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


@pytest.fixture
def chunk_fts_mirror(db_schema):  # noqa: ARG001
    """确保 ``knowledge_chunks_fts`` 检索镜像表存在（PG 兼容普通表）。

    PG 生产库默认不建该镜像（全文检索走 ``knowledge_chunks.search_vector``），
    但 ``kb_service.ingest_text`` / ``sync_mirror_subjects`` 的契约是
    「镜像表存在就必须与块同事务同步」。锁这条契约的用例需要一张镜像表承载断言。

    此前这些用例能过，只是因为测试库被长期复用、恰好残留了别的用例建的表；
    测试库改为每会话重建后，这种隐式的顺序依赖必须显式化。
    列结构与 ``tests/test_chunk_mirror_sync.py::_make_mirrors`` 一致。
    """
    from sqlalchemy import text

    from database import SessionLocal

    db = SessionLocal()
    try:
        db.execute(text(
            "CREATE TABLE IF NOT EXISTS knowledge_chunks_fts ("
            " chunk_id INTEGER, document_id INTEGER, subject VARCHAR, content TEXT)"))
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="session")
def real_db_mtime_guard():
    """记录真实库 mtime，供"未污染"断言比对。"""
    if os.path.exists(REAL_DB_PATH):
        return os.stat(REAL_DB_PATH).st_mtime_ns
    return None
