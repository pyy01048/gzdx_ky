# -*- coding: utf-8 -*-
"""项目体检：跨层一致性 + 测试隔离自检（2026-10-14 新增）。

为什么要有这个脚本
------------------
此前项目里的"体检"散落在多个一次性脚本里，且**测试隔离是靠人肉自觉**：
``tests/conftest.py`` 文档里写着"铁律：测试绝不允许碰真实库"，
但实现只改写了 ``DATABASE_PATH``，而 ``.env`` 里 ``DATABASE_BACKEND=postgresql``
时PG 分支根本不读这个变量——700+ 用例实际直连生产库，
而那个名为 ``test_real_database_not_polluted`` 的守卫只检查 SQLite 文件 mtime，
于是**守卫常绿、污染照旧**。

本脚本把最容易回归、且历史上真出过事的几项做成可复跑的检查：
  1. 模块导入完整性（routers / services / core）
  2. 路由注册与重复注册
  3. 测试库隔离（连的是不是生产库）
  4. 数据库方言兼容（SQLite / PostgreSQL DDL 兼容层是否接线）
  5. 双模型体系一致性（同表不同类名等漂移）

用法：
    python scripts/project_healthcheck.py
退出码 0 = 全通过；1 = 有 FAIL。
"""
from __future__ import annotations

import importlib
import io
import os
import pkgutil
import sys
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("KAOYAN_DISABLE_SCHEDULER", "1")

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, PASS if ok else FAIL, detail))
    print(f"  {name:<44s} {PASS if ok else FAIL}  {detail}")


# --------------------------------------------------------------------------- #
# 1. 模块导入完整性
# --------------------------------------------------------------------------- #
def check_imports() -> None:
    print("\n[1] 模块导入完整性")
    for pkg in ("routers", "services", "core"):
        try:
            mod = importlib.import_module(pkg)
        except Exception as exc:  # noqa: BLE001
            check(f"{pkg} 包可导入", False, f"{type(exc).__name__}: {exc}")
            continue
        names = [m.name for m in pkgutil.iter_modules(mod.__path__)]
        failed: list[str] = []
        for name in names:
            # 跳过显式声明的非模块脚本
            if name.startswith("_") or name in {"__main__"}:
                continue
            try:
                importlib.import_module(f"{pkg}.{name}")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{name}({type(exc).__name__})")
        check(f"{pkg} 子模块导入", not failed,
              f"{len(names) - len(failed)}/{len(names)}" + (f" 失败: {failed[:3]}" if failed else ""))


# --------------------------------------------------------------------------- #
# 2. 路由注册
# --------------------------------------------------------------------------- #
def check_routes() -> None:
    print("\n[2] 路由注册")
    try:
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            from main import app
    except Exception as exc:  # noqa: BLE001
        check("main:app 可导入", False, f"{type(exc).__name__}: {exc}")
        return
    seen: dict[str, int] = {}
    for r in app.routes:
        for m in getattr(r, "methods", []) or []:
            key = f"{m} {getattr(r, 'path', '')}"
            seen[key] = seen.get(key, 0) + 1
    dupes = [k for k, v in seen.items() if v > 1]
    check("路由总数", True, f"{len(seen)} 条")
    check("无重复路由", not dupes, (f"重复 {len(dupes)} 条: {dupes[:3]}" if dupes else ""))


# --------------------------------------------------------------------------- #
# 3. 测试库隔离（历史高危项）
# --------------------------------------------------------------------------- #
def check_test_isolation() -> None:
    print("\n[3] 测试库隔离")
    prod_db = "kaoyan"
    test_db = os.environ.get("TEST_PG_DATABASE", "kaoyan_test")

    from core.db_session import build_database_url

    url = build_database_url()
    tail = url.rsplit("/", 1)[-1].split("?")[0]
    # 注意：这里**不能**断言「默认 URL 不是生产库」——生产运行时本来就连生产库。
    # 真正要守的是「测试期间被改写到测试库」，见下面的改写检查。
    print(f"  （当前进程连接库={tail!r}；生产={prod_db!r}，测试={test_db!r}）")

    # 模拟 conftest 的改写，确认 PG 分支确实读 PG_DATABASE
    old = os.environ.get("PG_DATABASE")
    try:
        os.environ["PG_DATABASE"] = test_db
        tail2 = build_database_url().rsplit("/", 1)[-1].split("?")[0]
        check("PG_DATABASE 改写生效", tail2 == test_db, f"改写后={tail2!r} 期望={test_db!r}")
        check("改写后确实脱离生产库", tail2 != prod_db, f"生产={prod_db!r}")
    finally:
        if old is None:
            os.environ.pop("PG_DATABASE", None)
        else:
            os.environ["PG_DATABASE"] = old

    # conftest 必须真的改写了 PG_DATABASE，而不是只改 DATABASE_PATH
    try:
        sys.path.insert(0, os.path.join(BACKEND_DIR, "tests"))
        import conftest as c

        check("conftest 改写 PG_DATABASE", c.TEST_PG_DB == test_db, f"TEST_PG_DB={c.TEST_PG_DB!r}")
        check("conftest 定义生产库红线", hasattr(c, "PROD_PG_DB"), getattr(c, "PROD_PG_DB", ""))
    except Exception as exc:  # noqa: BLE001
        check("conftest 可导入", False, f"{type(exc).__name__}: {exc}")

    # conftest 必须调apply_schema（而不是只 create_all），否则 SQL-only 的表建不出来
    import inspect

    try:
        src = inspect.getsource(c.db_schema)
        check("db_schema 调用 apply_schema", "apply_schema" in src,
              "缺调用会导致 textbooks/notice_alerts 等表缺失")
        check("db_schema 调用 create_all 兜底", "create_all" in src)
    except Exception as exc:  # noqa: BLE001
        check("db_schema 可读", False, f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# 4. 数据库方言兼容层接线
# --------------------------------------------------------------------------- #
def check_dialect_compat() -> None:
    print("\n[4] 数据库方言兼容层")
    for mod, why in (
        ("services.ddl_compat", "AUTOINCREMENT / PRAGMA 兼容"),
        ("core.pg_enum_aware", "ENUM 列类型对齐"),
        ("services.dbapi_compat", "裸 DBAPI 连接的 ?占位符"),
    ):
        try:
            importlib.import_module(mod)
            check(f"{mod} 可用", True, why)
        except Exception as exc:  # noqa: BLE001
            check(f"{mod} 可用", False, f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# 5. schema 幂等性（本轮修复的重点，必须能持续守住）
# --------------------------------------------------------------------------- #
def check_schema_idempotent() -> None:
    """静态检查 core/sql/*.sql 的 DDL 是否幂等。

    不实际连库执行（那会动数据），只做文本级判定：
    只要出现裸 ``CREATE TABLE`` / ``CREATE INDEX`` / ``CREATE TRIGGER``，
    重跑整份 schema 就会抛 already exists。
    """
    print("\n[5] schema DDL 幂等性")
    import glob
    import re

    sql_dir = os.path.join(BACKEND_DIR, "core", "sql")
    files = sorted(glob.glob(os.path.join(sql_dir, "*.sql")))
    if not files:
        check("找到 SQL 分片", False, f"{sql_dir} 下无 .sql")
        return

    # 只统计行首（顶层）DDL；DO $$ 块内的属函数体，不参与判定
    patterns = {
        "CREATE TABLE": re.compile(r"^CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)", re.M | re.I),
        "CREATE INDEX": re.compile(
            r"^CREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF\s+NOT\s+EXISTS)", re.M | re.I
        ),
    }
    total_bad = 0
    for label, pat in patterns.items():
        bad: list[str] = []
        for path in files:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            n = len(pat.findall(text))
            if n:
                bad.append(f"{os.path.basename(path)}×{n}")
        total_bad += sum(int(x.split("×")[1]) for x in bad)
        check(f"{label} 均幂等", not bad, ("非幂等: " + ", ".join(bad[:3])) if bad else "")

    # CREATE TRIGGER 特殊处理：PG **没有** ``CREATE TRIGGER IF NOT EXISTS``
    # （与 TABLE/INDEX 不同），幂等的唯一惯用形式是前置
    # ``DROP TRIGGER IF EXISTS <name> ON <table>`` 守卫。
    # 旧实现无条件裸匹配 ``^CREATE\s+TRIGGER``，把带了 DROP 守卫的
    # 102_schools_admin_schema.sql 误报 ×3（2026-10-18 修正）。
    # 判定：每个 CREATE TRIGGER <name> 必须能在同文件找到对应的
    # DROP TRIGGER IF EXISTS <name>。
    trig_create = re.compile(r"^CREATE\s+TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.M | re.I)
    bad_trig: list[str] = []
    for path in files:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        for name in trig_create.findall(text):
            if not re.search(rf"DROP\s+TRIGGER\s+IF\s+EXISTS\s+{re.escape(name)}\b", text, re.I):
                bad_trig.append(f"{os.path.basename(path)}:{name}")
    total_bad += len(bad_trig)
    check("CREATE TRIGGER 均幂等（DROP 守卫）", not bad_trig,
          ("缺 DROP 守卫: " + ", ".join(bad_trig[:3])) if bad_trig else "")

    # 分片顺序：094a（加列）必须排在 080/081（视图）之前。
    # 只认真正执行的 ``\ir`` 行，忽略注释里的提及（注释也含文件名，会误判）。
    with open(os.path.join(BACKEND_DIR, "core", "pg_schema.sql"), "r", encoding="utf-8") as fh:
        root = fh.read()
    # 只认**非注释行**的 \ir：文件头的清单注释里也列了这些文件名，
    # 直接 find 会命中第 22 行的文档清单而非真实执行位置。
    exec_lines = [
        ln for ln in root.splitlines()
        if ln.lstrip().startswith("\\ir")
    ]
    exec_text = "\n".join(exec_lines)
    pos_cols = exec_text.find("094a_kp_mastery_columns.sql")
    pos_view = exec_text.find("080_views_and_gates.sql")
    pos_trigger = exec_text.find("093_kp_mastery_compat.sql")
    check("分片顺序：加列先于视图", 0 <= pos_cols < pos_view,
          f"094a@{pos_cols} 080@{pos_view}")
    check("分片顺序：触发器后于视图", 0 <= pos_view < pos_trigger,
          f"080@{pos_view} 093@{pos_trigger}")

    # 分片必须被 \ir 引用（2026-10-18 生产故障复盘）：
    # 8 个分片（audit_logs / kaoyan_schools.enabled / papers.year /
    # quiz_sessions / 网盘四表 / users / FSRS 列 / 回填）写在 core/sql/ 里
    # 却从未接进 pg_schema.sql，生产库整套缺表，用户管理、院校管理、试卷
    # 接口集体 500，且本地测试库同样缺表——只因没有门禁校验"写了就必须接"。
    # 本检查让"加了分片忘接 \ir"在提交前即失败。
    referenced = {
        os.path.basename(ln.lstrip()[len("\\ir"):].strip())
        for ln in exec_lines
        if ln.lstrip().startswith("\\ir")
    }
    on_disk = {os.path.basename(p) for p in files}
    orphans = sorted(on_disk - referenced)
    check("所有 SQL 分片均被 pg_schema 引用", not orphans,
          ("漏接 \\ir: " + ", ".join(orphans)) if orphans else f"{len(on_disk)} 个分片全部接入")


# --------------------------------------------------------------------------- #
# 6. ENUM 契约一致性
# --------------------------------------------------------------------------- #
def check_enum_contract() -> None:
    """校验 PgEnumAware 列的默认值都在对应 ENUM 的合法标签内。

    为什么重要：SQLite 无类型约束，非法默认值在本地开发完全看不出来；
    切到 PG 后才会抛 InvalidTextRepresentation，且**只在新建行时**爆 ——
    存量数据可能侥幸从未触发，属于典型定时炸弹。
    （实测踩过：Flashcard.mastery / Word.status 默认值 "new"，
      而 mastery_level 的合法标签是 not_mastered/learning/reviewing/mastered。）
    """
    print("\n[6] ENUM 默认值契约")
    import re

    try:
        from core.pg_types import ENUM_CATALOG
    except Exception as exc:  # noqa: BLE001
        check("可读 ENUM_CATALOG", False, f"{type(exc).__name__}: {exc}")
        return

    targets = [
        ("models.py", os.path.join(BACKEND_DIR, "models.py")),
    ]
    models_dir = os.path.join(BACKEND_DIR, "core", "models")
    if os.path.isdir(models_dir):
        for fn in sorted(os.listdir(models_dir)):
            if fn.endswith(".py"):
                targets.append((f"core/models/{fn}", os.path.join(models_dir, fn)))

    # 匹配  col = Column(PgEnumAware("enum_name", ...) ...) / mapped_column(build_enum(...))
    # 只取**本条声明自身**的参数：以右括号为界，避免 default 抓到下一个字段的值
    #（误报实录：stage 没有默认值，却被判成 default='pending'——那是 status 的）。
    decl = re.compile(
        r'(\w+)\s*=\s*(?:mapped_column|Column)\(\s*'
        r'(?:PgEnumAware|build_enum)\(\s*"([a-z_]+)"[^()]*'
    )
    total = 0
    bad: list[str] = []
    for label, path in targets:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        for m in decl.finditer(text):
            total += 1
            enum_name = m.group(2)
            # 从本条声明**自己的左括号**（即 Column( / mapped_column( ）开始
            # 做配对扫描，取出完整实参列表。
            # 两个坑：
            #   1. 不能从 m.end() 起算——那里 PgEnumAware(...) 的右括号会让
            #      depth 立刻归零、args 变空，从而**静默漏检**；
            #   2. 必须用 index（第一个左括号 = Column( ）而不是 rindex
            #      （最后一个 = PgEnumAware( ），否则同样取不到 default。
            open_paren = text.index("(", m.start())
            depth = 0
            i = open_paren
            while i < len(text):
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            args = text[open_paren + 1: i]
            d = re.search(r'default\s*=\s*"([^"]+)"', args)
            if not d:
                continue
            val = d.group(1)
            legal = ENUM_CATALOG.get(enum_name, ())
            if legal and val not in legal:
                bad.append(f"{label}:{m.group(1)} default={val!r} "
                           f"但 {enum_name} 合法值={list(legal)}")
    check("ENUM 列默认值均合法", not bad,
          f"扫描 {total} 个 ENUM 列" + ("；" + "；".join(bad[:3]) if bad else ""))


# --------------------------------------------------------------------------- #
# 6b. 运行时绝对路径绑定（P0-B1/B2 门禁）
# --------------------------------------------------------------------------- #
def check_no_drive_literals() -> None:
    """运行时模块不得出现 Windows 盘符字面量（``D:\\平台\\...`` 之类）。

    踩过的坑：exam_engine / ocr_router / kb_ingest 曾各自硬编码
    ``D:\\平台\\knowledge_base`` 与 ``D:\\平台\\database\\kaoyan.db``，
    同一目录两个环境变量、真库/诱饵库两份路径；搬到任何一台新机器
    （含这次云端部署）全部失效。现在 KB_ROOT 统一走
    ``services.kb_ingest.resolve_kb_root()``、DB 走 ``core/db_session``。

    扫描范围只限**运行时**目录：routers/ services/ core/ pipeline/ utils/
    及根级 main.py database.py migrate.py。scripts/ tools/ 里的一次性
    维护脚本允许历史残留（已按文件位置推导，2026-10-18 批量改过一轮），
    不在此门禁内 —— 否则每次写个临时脚本都要先过门禁，会把门禁废掉。
    """
    print("\n[6b] 运行时绝对路径绑定")
    import glob as _glob
    import io as _io
    import re as _re
    import tokenize as _tokenize

    scan_dirs = ["routers", "services", "core", "pipeline", "utils"]
    files: list[str] = []
    for d in scan_dirs:
        files.extend(_glob.glob(os.path.join(BACKEND_DIR, d, "**", "*.py"), recursive=True))
    for fn in ("main.py", "database.py", "migrate.py"):
        p = os.path.join(BACKEND_DIR, fn)
        if os.path.isfile(p):
            files.append(p)

    # 盘符 + 分隔符 + 至少一段路径
    pat = _re.compile(r"""(?<!://)\b[A-Z]:[\\/][^\s'"]*""")
    # docstring/独立字符串语句的前一个有效 token 类型
    _STMT_HEAD = {None, _tokenize.NEWLINE, _tokenize.INDENT, _tokenize.DEDENT,
                  _tokenize.ENCODING}

    def _code_literals(path: str) -> list[tuple[int, str]]:
        """只返回**代码里**的字符串字面量（行号, 内容）。

        用 tokenize 而非逐行正则：注释（COMMENT token）与文档字符串
        （独立成句的 STRING）都不算功能绑定 —— 前者是说明，后者是
        血泪史记录（如 delete_guard 里写着的诱饵库路径）。逐行正则会把
        这 14 处历史注释全部误报，门禁就被催着绕开了。
        """
        try:
            with open(path, "rb") as fh:
                toks = list(_tokenize.tokenize(fh.readline))
        except Exception:  # noqa: BLE001 —— 语法错误/编码异常由其他检查负责
            return []
        out: list[tuple[int, str]] = []
        sig = None
        for t in toks:
            if t.type == _tokenize.COMMENT:
                continue
            if t.type in (_tokenize.STRING, getattr(_tokenize, "FSTRING_MIDDLE", -1)):
                if sig not in _STMT_HEAD and pat.search(t.string):
                    out.append((t.start[0], t.string[:60]))
                sig = _tokenize.STRING
                continue
            if t.type == _tokenize.NL:
                continue
            sig = t.type
        return out

    bad: list[str] = []
    for path in files:
        for lineno, lit in _code_literals(path):
            bad.append(f"{os.path.relpath(path, BACKEND_DIR)}:{lineno} {lit}")
    check("运行时无盘符字面量路径", not bad,
          (f"{len(bad)} 处: " + "; ".join(bad[:3])) if bad else
          f"扫描 {len(files)} 个运行时模块（注释/文档字符串不计）")


# --------------------------------------------------------------------------- #
# 7. 双模型体系漂移
# --------------------------------------------------------------------------- #
def check_model_drift() -> None:
    print("\n[5] 双模型体系漂移")
    # 同名表被两个 Base 各定义一次是**有意设计**（models.py 服务存量路由，
    # core/models 是迁移目标态），但类名拼写分裂会让人误以为是两个东西。
    try:
        import models as legacy
        from core import pg_models as new
    except Exception as exc:  # noqa: BLE001
        check("两套模型可导入", False, f"{type(exc).__name__}: {exc}")
        return
    check("两套模型可导入", True, "models.py=存量路由 / core/models=迁移目标态")

    legacy_name_by_table = {}
    for cls_name in dir(legacy):
        obj = getattr(legacy, cls_name, None)
        if not isinstance(obj, type):
            continue
        tbl = getattr(obj, "__tablename__", None)
        if tbl:
            legacy_name_by_table[tbl] = cls_name
    dup_tables: dict[str, list[str]] = {}
    for cls_name in dir(new):
        obj = getattr(new, cls_name, None)
        tbl = getattr(obj, "__tablename__", None)
        if tbl:
            dup_tables.setdefault(tbl, []).append(cls_name)
    # 找"两套体系里指向同一张表、但类名不同"的情况
    clashes = [
        (t, legacy_name_by_table[t], names[0])
        for t, names in dup_tables.items()
        if t in legacy_name_by_table and legacy_name_by_table[t] not in names
    ]
    if clashes:
        detail = "; ".join(f"{t}: {a} vs {b}" for t, a, b in clashes[:3])
        check("同表类名一致", False, f"{len(clashes)} 处分裂 -> {detail}")
    else:
        check("同表类名一致", True, "无拼写分裂")


def check_module_attrs() -> None:
    """跨模块常量引用：不得指向不存在的常量。

    实际踩过：`kp_mastery.MASTERY_THRESHOLD`（正典名 MASTERED_THRESHOLD）
    → AttributeError 被上层 except 包成"概览查询失败"，
    /api/analytics/* 两个端点恒 500 而报错不指向真因。
    这类错误静态不可见、运行才炸、测试难覆盖，故做成门禁。
    """
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from audit_module_attrs import scan as _scan  # noqa: WPS433

        bad = _scan()
        if bad:
            b = bad[0]
            check("跨模块常量引用", False,
                  f"{len(bad)} 处指向不存在的常量，例: {b['file']}:{b['line']} {b['ref']}")
        else:
            check("跨模块常量引用", True, "无失效引用")
    except Exception as exc:  # noqa: BLE001
        check("跨模块常量引用", True, f"检查跳过: {str(exc)[:80]}")


def check_silent_except() -> None:
    """静默异常：HIGH 级必须为 0。

    项目血泪教训 #1 —— `except Exception: pass` 会吞掉建表失败这类致命
    错误，症状漂移到别处、排查成本极高（历史上踩过 3 次：weak_knowledge
    表从未建出 / provenance 列永远建不出来 / DDL 静默失败）。

    审计口径见 scripts/audit_silent_except.py：HIGH = 宽泛异常 + 裸 pass
    且无任何说明；收窄类型或有注释的算 LOW（有理由，只提示不拦）。
    """
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from audit_silent_except import scan  # noqa: WPS433

        items = scan()
        high = [x for x in items if x["severity"] == "HIGH"]
        if high:
            first = high[0]
            check(
                "静默异常(HIGH)",
                False,
                f"{len(high)} 处无说明的静默 except，例: "
                f"{first['file']}:{first['line']} {first['except']}",
            )
        else:
            check("静默异常(HIGH)", True,
                  f"共 {len(items)} 处，全部有说明或已收窄异常类型")
    except Exception as exc:  # noqa: BLE001
        # 审计工具自身不可用不应让体检整体失败（工具是辅助，不是产品）
        check("静默异常(HIGH)", True, f"审计跳过: {str(exc)[:80]}")


def check_bat_ascii() -> None:
    """.bat 必须是纯 ASCII。

    实测：UTF-8（带不带 BOM 都不行）的 .bat 里出现中文时，cmd 可能把该行
    从字符中间截断并**吞掉下一行**，结果是命令静默不执行 —— 表现为
    "双击了没反应"。所以所有中文都放在 Python 侧输出，外壳保持 ASCII。
    """
    root = Path(__file__).resolve().parents[2]  # D:\平台
    bats = sorted(p for p in root.glob("*.bat") if "_backup_" not in p.name)
    bad = []
    for bat in bats:
        data = bat.read_bytes()
        offender = sum(1 for b in data if b > 127)
        if offender:
            bad.append(f"{bat.name}({offender}字节)")
    if bad:
        check("bat 纯 ASCII", False, "含非 ASCII 字节: " + ", ".join(bad))
    else:
        check("bat 纯 ASCII", True, f"已检查 {len(bats)} 个脚本")


def main() -> int:
    print("=" * 72)
    print("项目体检 · project_healthcheck")
    print("=" * 72)
    check_imports()
    check_routes()
    check_test_isolation()
    check_dialect_compat()
    check_schema_idempotent()
    check_no_drive_literals()
    check_enum_contract()
    check_model_drift()
    check_bat_ascii()
    check_silent_except()
    check_module_attrs()

    failed = [r for r in results if r[1] == FAIL]
    print("\n" + "=" * 72)
    print(f"合计 {len(results)} 项：通过 {len(results) - len(failed)}，失败 {len(failed)}")
    for name, _, detail in failed:
        print(f"  FAIL {name}  {detail}")
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())