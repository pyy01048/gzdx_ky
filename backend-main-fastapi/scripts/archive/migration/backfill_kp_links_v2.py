# -*- coding: utf-8 -*-
"""题目↔知识点关联增强回填 v2（M1-1，2026-10）。

背景（实测）：
    question_knowledge_links 原仅 6288 条、覆盖 5911/9171 题；旧脚本
    ``backfill_kp_links.py`` 只做「同科同名精确匹配」，对
    ``quiz_questions.knowledge_point`` 为空或与知识点名不一致的 3,260 题无解。

本脚本**不修改**旧脚本，新增三层策略，规则优先、LLM 兜底：
    第 1 层（规则·高置信）：沿用旧脚本「同科同名」精确匹配
        → role=primary, weight=1.0, is_verified=1。
    第 2 层（规则·中置信）：复用 error_linker 的匹配思路
        （_named_hits / _keyword_hits / _lexical_overlap），用**题干文本**
        匹配**同科目**知识点名 / 章名 / 领域术语
        → role=related, weight=0.6, is_verified=0。阈值可配。
    第 3 层（LLM 兜底）：仅对前两层仍未链上的题，把「题干 + 该科目全部
        知识点名候选」交给项目已有 LLM 入口（services.model_gateway），
        让它输出 JSON 判定归属（最多 top_k 个 KP）
        → role=related, weight=0.5, is_verified=0。
        当 Ollama 不可用且无云端供应商时自动跳过并如实报告。

设计要点：
    * 幂等：已存在的 (question_id, knowledge_point_id) 一律跳过，重跑只补增量；
    * 默认 dry-run（预览），`--apply` 才写库，且**先备份真库**（sqlite backup API）；
    * `--layer rule|llm|all`、`--limit N`、`--sample N` 便于分批与抽查；
    * 完成后回填 knowledge_points.question_count = 实际 primary 关联题数；
    * 不改表结构、不用 source 列（表无该列），来源差异靠 role/weight 区分。

用法：
    python scripts/backfill_kp_links_v2.py                       # 预览三层命中
    python scripts/backfill_kp_links_v2.py --layer rule          # 只预览规则层
    python scripts/backfill_kp_links_v2.py --layer llm --limit 200
    python scripts/backfill_kp_links_v2.py --apply               # 写库（先自动备份）
    python scripts/backfill_kp_links_v2.py --sample 100          # 抽 100 条可读核对
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
from datetime import datetime

# --------------------------------------------------------------------------- #
# 路径与常量
# --------------------------------------------------------------------------- #
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 以脚本方式运行时（python scripts/xxx.py），sys.path[0] 是 scripts/，
# 导致 `import services.*` 失败——把项目根加入 sys.path，让第 3 层能复用项目内 LLM 入口。
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
# 独立运行时 .env 不会被自动加载：显式载入，保证 DATABASE_PATH 指向真库
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, ".env"))
except Exception:
    pass
DB_PATH = os.environ.get("DATABASE_PATH", "").strip() or os.path.join(
    os.path.dirname(BASE_DIR), "database", "kaoyan.db"
)

#: 第 2 层阈值（默认值，CLI 可覆盖）
LEXICAL_MIN = 0.30          # 章名模糊匹配时要求的最低字面重合度
CH_UNIQUE_MIN_LEN = 4       # 参与「章名包含于题干」匹配的最短章名长度
CROSS_NAME_MIN_LEN = 6      # 跨科兜底时要求的知识点整名最短长度（防误挂）
#: 是否启用跨科兜底。默认 **关闭**：M1-1 精度要求「只在同科内匹配，避免跨科误挂」，
#: 跨科仅在显式传 --cross-subject 时开启（用于排查科目字段写错的题）。
ENABLE_CROSS_SUBJECT = False
RELATED_MAX_PER_Q = 3       # 每题最多保留的中置信相关链

#: 第 3 层 LLM 兜底
LLM_MAX_KP = 3              # LLM 每题最多判定的知识点数
LLM_CAND_LIMIT = 60         # 送给 LLM 的候选知识点上限（控制 prompt 长度）
LLM_MODEL_OVERRIDE = os.environ.get("KP_BACKFILL_LLM_MODEL", "").strip() or None


# --------------------------------------------------------------------------- #
# 通用工具（与 error_linker 保持同口径）
# --------------------------------------------------------------------------- #
def _compact(text: str) -> str:
    """去掉空格/全角空格，便于名称直击（'JK 触发器' == 'JK触发器'）。"""
    if not text:
        return ""
    return text.replace(" ", "").replace("\u3000", "")


def _lexical_overlap(text: str, name: str) -> float:
    """题干与知识点名的字面字符集重合度 0-1（复用 error_linker 口径）。"""
    if not text or not name:
        return 0.0
    n = set(name)
    t = set(text)
    return round(len(n & t) / max(len(n), 1), 4)


# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #
#: 拆词分隔符：知识点名常写成「数据结构·线性表」「栈队列与数组」这类复合短语，
#  按这些分隔符切开后，各片段才可能真实出现在题干里（整名往往不会）。
_NAME_SPLIT_RE = None  # 惰性编译

#: 泛词/结构词停用表（**不参与匹配**）。命中这些词不能证明题考查该 KP，
#  是第 2 层误挂的主要来源（如"电路/放大/逻辑/方法"在几乎每道题里都出现）。
_SEGMENT_STOPWORDS = {
    "的", "与", "和", "及", "或", "等", "之", "对", "为",
    "基本", "主要", "重要", "一般", "各种", "一些", "有关", "以下", "下列",
    "概念", "特点", "性质", "原理", "方法", "方式", "过程", "步骤", "条件",
    "分析", "计算", "求解", "应用", "作用", "影响", "意义", "关系", "区别",
    "电路", "系统", "结构", "组成", "工作", "状态", "模型", "特性", "性能",
    "电路图", "放大电路", "滤波器", "信号", "输入", "输出", "电压", "电流",
    "逻辑", "门电路", "触发器", "计数器", "寄存器", "编码器", "译码器",
    "判断", "选择", "设计", "实现", "分类", "类型", "种类", "情况", "问题",
    "定义", "含义", "说明", "简述", "举例", "下列", "关于", "什么是", "如何",
}

#: 参与匹配的「实词片段」最短长度：太短的片段噪声大，要求 >= 3 字
STRONG_SEG_MIN_LEN = 3
#: 命中可成链所需的最少「不同强片段」数（单一实词不足以成链）
STRONG_HITS_MIN = 2
#: 无章题的更严判据：整名须 >= 该长度；强片段须 >= 该数量
NO_CHAP_NAME_MIN_LEN = 6
NO_CHAP_HITS_MIN = 3

#: 过于宽泛、单独出现不足以定位考点的 KP 名（常见于"每道题都提"的概念）。
#: 当题目**没有章信息**时，仅凭这些 KP 名不得成链（需更多强片段佐证）。
_GENERIC_KP_NAMES = {
    "放大倍数", "输入电阻", "输出电阻", "功率放大", "电压放大", "电流放大",
    "放大电路", "运算电路", "逻辑函数", "逻辑表达式", "半导体器件",
    "信号转换", "整流电路", "滤波电路", "静态工作点", "频率响应",
    "反馈", "振荡", "电压", "电流", "电阻", "电容", "电感", "逻辑",
}


def _split_name_segments(name: str) -> list[str]:
    """把知识点名拆成可匹配的短片段。

    例：「数据结构·栈队列与数组」→ ['数据结构', '栈队列', '数组']
        「反馈的判断方法、负反馈放大电路的四种基本组态」→ ['负反馈放大电路', '四种基本组态', ...]
    仅保留长度 >= 2 且非泛词的片段（后续再按 STRONG_SEG_MIN_LEN 分强/弱）。
    """
    global _NAME_SPLIT_RE
    if _NAME_SPLIT_RE is None:
        import re

        _NAME_SPLIT_RE = re.compile(r"[·•\.、，,;；:：/\-—_()（）\[\]【】\s]+")
    parts: list[str] = []
    for seg in _NAME_SPLIT_RE.split(name or ""):
        seg = seg.strip()
        if len(seg) >= 2 and seg not in _SEGMENT_STOPWORDS:
            parts.append(seg)
        # 长片段再按「的/与/和」二次切分，取子片段
        if len(seg) >= 6:
            for sub in _re_split_connectors(seg):
                if len(sub) >= 2 and sub not in _SEGMENT_STOPWORDS and sub not in parts:
                    parts.append(sub)
    return parts


def _strong_segments(segments: list[str]) -> list[str]:
    """从片段中筛出「实词强片段」：长度 >= STRONG_SEG_MIN_LEN 且非泛词。"""
    out = []
    for s in segments:
        if len(s) >= STRONG_SEG_MIN_LEN and s not in _SEGMENT_STOPWORDS:
            out.append(s)
    return out


def _re_split_connectors(seg: str) -> list[str]:
    """把长片段按连接词（的/与/和/及）切成子串（仅用于补充，不破坏原段）。"""
    import re

    return [s for s in re.split(r"[的与和及之]", seg) if s]


def _load_points(cur: sqlite3.Cursor) -> list[dict]:
    """加载全部非空名知识点（含预拆分的名称片段，供第 2 层匹配）。"""
    rows = cur.execute(
        "SELECT id, name, subject, chapter, exam_frequency FROM knowledge_points "
        "WHERE name IS NOT NULL AND TRIM(name) != ''"
    ).fetchall()
    out = []
    for r in rows:
        name = (r[1] or "").strip()
        chapter = r[3]
        # 强片段仅来自**知识点名本身**（章名片段不并入，否则"题里出现章名"就滥挂该章所有 KP）
        segs = _split_name_segments(name)
        out.append({
            "id": r[0],
            "name": name,
            "compact": _compact(name),
            "subject": r[2],
            "chapter": chapter,
            "segments": [s for s in segs if len(s) >= 2],
            "strong": _strong_segments(segs),
        })
    return out


def _load_questions(cur: sqlite3.Cursor) -> list[dict]:
    """加载全部题目（含 content/knowledge_point/subject/chapter/question_type）。"""
    rows = cur.execute(
        "SELECT id, content, knowledge_point, subject, chapter, question_type "
        "FROM quiz_questions"
    ).fetchall()
    return [
        {
            "id": r[0],
            "content": r[1] or "",
            "kp_text": (r[2] or "").strip(),
            "subject": r[3],
            "chapter": r[4],
            "qtype": r[5],
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# 第 1 层：规则·高置信（同科同名）
# --------------------------------------------------------------------------- #
def layer_rule_exact(questions: list[dict], points: list[dict]) -> list[tuple]:
    """同科目 + 知识点名精确同名 → [(qid, kp_id)]。"""
    name_subj: dict[tuple, int] = {
        (p["name"], p["subject"]): p["id"] for p in points
    }
    out: list[tuple] = []
    for q in questions:
        if not q["kp_text"]:
            continue
        kid = name_subj.get((q["kp_text"], q["subject"]))
        if kid is not None:
            out.append((q["id"], kid))
    return out


# --------------------------------------------------------------------------- #
# 第 2 层：规则·中置信（题干文本匹配，同科目）
# --------------------------------------------------------------------------- #
def _points_by_subject(points: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in points:
        out.setdefault(p["subject"], []).append(p)
    return out


def build_chapter_table(points: list[dict]) -> dict[str, set[str]]:
    """章节名 → 科目集合（用于按科目限定章名匹配）。"""
    tbl: dict[str, set[str]] = {}
    for p in points:
        ch = (p["chapter"] or "").strip()
        if ch:
            tbl.setdefault(ch, set()).add(p["subject"])
    return tbl


def _domain_terms() -> list[str]:
    """领域术语表（复用 error_linker.ERR_TERMS + search_service.CORE_TERMS）。"""
    terms: list[str] = []
    try:
        from services.search_service import CORE_TERMS  # type: ignore

        terms = list(CORE_TERMS) if CORE_TERMS else []
    except Exception:
        terms = []
    try:
        from services.error_linker import ERR_TERMS

        terms.extend(t for t in ERR_TERMS if t not in terms)
    except Exception:
        pass
    return [t for t in terms if t]


def match_question_rule(
    q: dict,
    subj_points: list[dict],
    *,
    lexical_min: float = LEXICAL_MIN,
) -> dict[int, float]:
    """对单题做第 2 层匹配，返回 {kp_id: score}（仅限传入的同科知识点）。

    **严判据（M1-1 精度修订）**——只认两种可靠信号：
      1) 知识点**整名**出现在题干（length>=3）——最强；
      2) 命中该 KP 的 **>=2 个不同实词强片段**（>=3 字、非泛词）——较强。
    并强制**同章约束**：当题目与 KP 都有 chapter 值时，必须完全一致；
    若题目无 chapter，则要求更强（整名命中，或 >=3 个强片段）。
    单一泛词（电路/放大/逻辑/方法…）一律不成链。
    跨章、跨科的弱信号一律不采纳（历史误挂的根因就在于此）。
    """
    text = q["content"] or ""
    if not text or not subj_points:
        return {}
    compact_text = _compact(text)
    q_chapter = (q["chapter"] or "").strip()
    scores: dict[int, float] = {}
    # 无章题（本库未链题绝大多数无 chapter，且多为"科目/章节字段缺失"的题）
    # 无法用同章约束，必须用更严的字面判据：整名更长或强片段更多。
    no_chapter = not q_chapter

    for p in subj_points:
        p_chapter = (p["chapter"] or "").strip()
        # ---- 同章约束：两者都有章值时，必须一致 ----
        if q_chapter and p_chapter and q_chapter != p_chapter:
            continue
        same_chapter = bool(q_chapter and p_chapter and q_chapter == p_chapter)

        # ---- 信号 1：整名直击 ----
        # 有章题：整名 >=3 字即可；无章题：整名须 >=5 字且非常见泛概念名。
        name_ok = (
            len(p["name"]) >= (3 if not no_chapter else NO_CHAP_NAME_MIN_LEN)
            and p["compact"]
            and p["compact"] in compact_text
        )
        if name_ok and no_chapter and p["name"] in _GENERIC_KP_NAMES:
            name_ok = False
        if name_ok:
            scores[p["id"]] = 1.00 + min(len(p["name"]), 30) * 0.01 + (
                0.10 if same_chapter else 0.0
            )
            continue

        # ---- 信号 2：>=2 个不同实词强片段命中 ----
        hits = [s for s in p["strong"] if s and s in compact_text]
        uniq = sorted(set(hits), key=len, reverse=True)
        need = STRONG_HITS_MIN if not no_chapter else NO_CHAP_HITS_MIN
        if len(uniq) >= need:
            base = 0.45 + min(len(uniq[0]), 20) * 0.01 + 0.02 * len(uniq)
            scores[p["id"]] = round(min(base, 0.95), 4) + (
                0.10 if same_chapter else 0.0
            )

    return scores


def match_question_cross_subject(
    q: dict,
    all_points: list[dict],
    own_subject_ids: set[int],
    *,
    min_name_len: int = CROSS_NAME_MIN_LEN,
) -> dict[int, float]:
    """跨科兜底（**严格限缩**）。返回 {kp_id: score}。

    实测动机：库中存在**科目字段写错**的题（如政治栏下放的是模电半导体内容）。
    但跨科匹配也是误挂重灾区（本题无同科 KP，容易命中它科泛概念名）。
    因此只接受**两个条件同时满足**的强信号：
      1) 其它科目知识点的**整名长度 >= min_name_len（默认 6）**出现在题干；
      2) 该 KP 的**强片段中 >= 2 个**也出现在题干。
    低于此标准一律不挂（宁可漏，不可错）。仍标记 related / is_verified=0 待核。
    """
    text = q["content"] or ""
    if not text:
        return {}
    compact_text = _compact(text)
    scores: dict[int, float] = {}
    for p in all_points:
        if p["id"] in own_subject_ids:
            continue
        if len(p["name"]) < min_name_len or not p["compact"]:
            continue
        if p["compact"] not in compact_text:
            continue
        # 再要求 >=2 个强片段佐证，滤掉"长但偶然命中"的名字
        seg_hits = {s for s in p["strong"] if s and s in compact_text}
        if len(seg_hits) < 2:
            continue
        scores[p["id"]] = 0.80 + min(len(p["name"]), 30) * 0.01
    return scores


def layer_rule_text(
    questions: list[dict],
    points: list[dict],
    *,
    lexical_min: float = LEXICAL_MIN,
    max_per_q: int = RELATED_MAX_PER_Q,
    enable_cross_subject: bool = ENABLE_CROSS_SUBJECT,
) -> list[tuple[int, int, float]]:
    """第 2 层：返回 [(qid, kp_id, weight)]。

    默认**只在同科目内**匹配（M1-1 精度要求）。同科目命不中且显式开启跨科时，
    才做跨科整名兜底（应对科目字段写错的题）；跨科命中权重略低，仍标
    role=related / is_verified=0 待人工核验。
    """
    by_subj = _points_by_subject(points)
    out: list[tuple[int, int, float]] = []
    for q in questions:
        own = by_subj.get(q["subject"], [])
        own_ids = {p["id"] for p in own}
        cand = match_question_rule(q, own, lexical_min=lexical_min)
        cross = False
        if not cand and enable_cross_subject:
            # 跨科兜底：只接受其它科目知识点的整名直击（长度>=6 且有强片段佐证）
            cand = match_question_cross_subject(q, points, own_ids)
            cross = bool(cand)
        if not cand:
            continue
        top = sorted(cand.items(), key=lambda kv: -kv[1])[:max_per_q]
        for kid, sc in top:
            # 归一到 0.45~0.60 作为 related 权重；跨科略降 0.05
            w = round(min(0.60, 0.45 + min(sc, 1.5) * 0.10) - (0.05 if cross else 0.0), 2)
            out.append((q["id"], kid, w))
    return out


# --------------------------------------------------------------------------- #
# 第 3 层：LLM 兜底（批量，走项目已有 LLM 调用入口）
# --------------------------------------------------------------------------- #
#: 兜底优先使用的快模型（非思考模型）。可用环境变量覆盖。
#: 实测：qwen2.5:1.5b 快但易乱；kaoyan-assistant（本库微调）JSON 规范但偏保守；
#: qwen3:4b 质量较好但慢（思考模型）。默认用 kaoyan-assistant。
FAST_LLM_MODEL = os.environ.get("KP_BACKFILL_LLM_MODEL", "").strip() or "kaoyan-assistant"
LLM_BATCH = 8               # 每次调用包含的题目数（批量降低往返开销）
#: 是否接受「LLM 判定但题干无字面佐证」的链。默认 False（保精度）：
#: 实测本机小模型无佐证时误判率高，宁可少挂也不挂错。加 --llm-uncorroborated 打开。
LLM_REQUIRE_CORROBORATION = True


def _llm_cfg() -> dict:
    """构造本地 Ollama 的调用配置（复用 model_gateway._chat_openai_compat）。"""
    base = os.environ.get("OLLAMA_BASE") or os.environ.get("OLLAMA_HOST") \
        or "http://127.0.0.1:11434"
    from utils.ollama_host import resolve_ollama_host

    base = resolve_ollama_host(base)
    return {
        "kind": "local", "provider": "ollama", "name": "KP兜底快模型",
        "base_url": base.rstrip("/"), "api_key": "ollama",
        "model": FAST_LLM_MODEL, "temperature": 0.0, "priority": 0,
    }


def _llm_available() -> tuple[bool, str]:
    """探测本地 LLM 是否可用：优先复用 model_gateway 的 Ollama 探针。

    返回 (可用?, 说明)。任何异常均视为不可用（第 3 层跳过，不报错）。
    """
    try:
        from services.model_gateway import _ollama_installed

        installed = _ollama_installed()
        if not installed:
            return False, "本机 Ollama 未运行或无已下载模型"
        if FAST_LLM_MODEL in installed:
            return True, FAST_LLM_MODEL
        # 退而求其次：任一已装模型可用于兜底
        return True, f"{FAST_LLM_MODEL}(未装,将退用 {installed[0]})"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:120]}"


def _resolve_model(installed: list[str]) -> str:
    """选一个已安装、且适合做批量 JSON 分类的模型。"""
    if FAST_LLM_MODEL in installed:
        return FAST_LLM_MODEL
    # 退用顺序：微调模型 > 规范 JSON 的小模型 > 任意已装
    for pref in ("kaoyan-assistant", "qwen3:4b", "qwen2.5-coder:7b", "qwen2.5:1.5b"):
        if pref in installed:
            return pref
    return installed[0] if installed else FAST_LLM_MODEL


def _batch_prompt(batch: list[tuple[int, dict]], cand_names: list[str], max_kp: int) -> str:
    """构造批量分类 prompt。batch 为 [(自增序号, 题目)]。"""
    lines = [
        "你是考研题目归类助手。为下面每道题从【候选知识点】中挑选最相关的最多 "
        f"{max_kp} 个（必须原样复制候选中的名称，不得自造）；若都不相关则该题返回空数组。",
        "",
        "候选知识点：" + json.dumps(cand_names, ensure_ascii=False),
        "",
        "题目列表：",
    ]
    for idx, q in batch:
        snippet = (q["content"] or "").replace("\n", " ")[:220]
        lines.append(f"[{idx}] （{q['subject']}｜{q['chapter'] or '未知章'}）{snippet}")
    lines += [
        "",
        "只输出 JSON 数组，每项形如 {\"i\": 题号, \"points\": [\"知识点名\", ...]}，"
        "按题号顺序给出，不要解释、不要多余文字。",
    ]
    return "\n".join(lines)


def _extract_json_objects(text: str) -> list[dict]:
    """从模型输出里抽取所有形如 {...} 的 JSON 对象（容错代码块/多余文字）。"""
    import re

    if not text:
        return []
    cleaned = text.replace("```json", "```")
    # 去掉代码块围栏
    if "```" in cleaned:
        parts = cleaned.split("```")
        cleaned = max(parts, key=len)
    objs: list[dict] = []
    # 宽松匹配：从每个 '{' 起尝试解析到匹配的 '}'
    for m in re.finditer(r"\{", cleaned):
        start = m.start()
        depth = 0
        for j in range(start, len(cleaned)):
            if cleaned[j] == "{":
                depth += 1
            elif cleaned[j] == "}":
                depth -= 1
                if depth == 0:
                    frag = cleaned[start:j + 1]
                    try:
                        obj = json.loads(frag)
                        if isinstance(obj, dict):
                            objs.append(obj)
                    except Exception:
                        pass
                    break
    return objs


def _name_to_id(nm: str, name2id: dict[str, int]) -> int | None:
    """把模型给出的名称映射回知识点 id（容错：精确 → 包含）。"""
    nm = (nm or "").strip()
    if not nm:
        return None
    if nm in name2id:
        return name2id[nm]
    for k, v in name2id.items():
        if nm in k or k in nm:
            return v
    return None


def llm_classify_batch(
    questions: list[dict],
    subj_points: list[dict],
    *,
    model: str,
    max_kp: int = LLM_MAX_KP,
    batch_size: int = LLM_BATCH,
    require_corroboration: bool = LLM_REQUIRE_CORROBORATION,
) -> list[tuple[int, int, float]]:
    """对一批「同科目」题目做 LLM 批量分类，返回 [(qid, kp_id, weight)]。

    复用项目已有 HTTP 调用 `services.model_gateway._chat_openai_compat`，
    不另写 HTTP 逻辑。任一子批失败只跳过该子批，不影响整体。

    require_corroboration=True（默认）时，只接受「被判定知识点名或其拆分片段
    真实出现在题干」的链——实测本机小模型无佐证时误判率高，此闸门保证精度。
    """
    if not questions or not subj_points:
        return []
    from services.model_gateway import _chat_openai_compat

    name2id = {p["name"]: p["id"] for p in subj_points}
    id2kp = {p["id"]: p for p in subj_points}
    cand_names = [p["name"] for p in subj_points][:LLM_CAND_LIMIT]
    cand_ids = {name2id[n] for n in cand_names}

    cfg = _llm_cfg()
    cfg["model"] = model

    def corroborated(q: dict, kid: int) -> bool:
        """被判定知识点名（或拆词片段）是否出现在题干——精度闸门。"""
        p = id2kp.get(kid)
        if not p:
            return False
        t = _compact(q["content"] or "")
        if p["compact"] and p["compact"] in t:
            return True
        return any(s and s in t for s in p.get("segments", []))

    out: list[tuple[int, int, float]] = []
    for b0 in range(0, len(questions), batch_size):
        chunk = questions[b0:b0 + batch_size]
        numbered = list(enumerate(chunk, start=1))
        prompt = _batch_prompt(numbered, cand_names, max_kp)
        msgs = [
            {"role": "system", "content": "你是严谨的学科分类助手，只输出合法 JSON。"},
            {"role": "user", "content": prompt},
        ]
        try:
            resp = _chat_openai_compat(cfg, msgs, timeout=120.0)
            text = resp.get("text") or ""
        except Exception:  # noqa: BLE001
            continue
        for obj in _extract_json_objects(text):
            try:
                i = int(obj.get("i"))
            except (TypeError, ValueError):
                continue
            if not (1 <= i <= len(chunk)):
                continue
            q = chunk[i - 1]
            picked = obj.get("points")
            if isinstance(picked, str):
                picked = [picked]
            if not isinstance(picked, list):
                continue
            seen: set[int] = set()
            for nm in picked:
                kid = _name_to_id(str(nm), name2id)
                # 仅接受命中 id 且该 id 在送出的候选内（防幻觉/越界）
                if kid is None or kid not in cand_ids or kid in seen:
                    continue
                if require_corroboration and not corroborated(q, kid):
                    continue
                seen.add(kid)
                out.append((q["id"], kid, 0.50))
                if len(seen) >= max_kp:
                    break
    return out


# --------------------------------------------------------------------------- #
# 统计与预览
# --------------------------------------------------------------------------- #
def _coverage(cur: sqlite3.Cursor) -> tuple[int, int, int]:
    """返回 (links 总数, 覆盖题目数, 题目总数)。"""
    links = cur.execute("SELECT COUNT(*) FROM question_knowledge_links").fetchone()[0]
    linked_q = cur.execute(
        "SELECT COUNT(DISTINCT question_id) FROM question_knowledge_links"
    ).fetchone()[0]
    total_q = cur.execute("SELECT COUNT(*) FROM quiz_questions").fetchone()[0]
    return links, linked_q, total_q


def _existing_pairs(cur: sqlite3.Cursor) -> set[tuple[int, int]]:
    return {
        (r[0], r[1])
        for r in cur.execute(
            "SELECT question_id, knowledge_point_id FROM question_knowledge_links"
        )
    }


def _print_samples(
    links: list[tuple], q_by_id: dict[int, dict], kp_by_id: dict[int, dict], n: int
) -> None:
    """打印 n 条「题目摘要 → 知识点」可读样例。"""
    if not links:
        print("（无样例）")
        return
    rnd = random.Random(42)
    picks = rnd.sample(links, min(n, len(links)))
    for i, (qid, kid, *_rest) in enumerate(picks, 1):
        q = q_by_id.get(qid, {})
        kp = kp_by_id.get(kid, {})
        snippet = (q.get("content") or "").replace("\n", " ")[:70]
        print(
            f"  [{i:>3}] Q{qid}（{q.get('subject')}）「{snippet}」\n"
            f"        → KP{kid} [{kp.get('subject')}] {kp.get('name')}"
            f"（{kp.get('chapter') or '-'}）"
        )


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="题目↔知识点关联增强回填 v2")
    ap.add_argument("--apply", action="store_true", help="实际写库（默认仅预览）")
    ap.add_argument(
        "--layer",
        choices=["rule", "llm", "all"],
        default="all",
        help="执行层：rule=仅规则层(1+2)，llm=规则+LLM兜底，all=全部(默认)",
    )
    ap.add_argument("--limit", type=int, default=0, help="每题数上限（0=不限），便于分批")
    ap.add_argument("--sample", type=int, default=30, help="预览/抽查样例条数")
    ap.add_argument("--lexical-min", type=float, default=LEXICAL_MIN, help="第2层字面重合阈值")
    ap.add_argument("--max-related", type=int, default=RELATED_MAX_PER_Q, help="每题最多相关链数")
    ap.add_argument("--llm-model", default=None, help="第3层使用的本地模型名（默认 kaoyan-assistant）")
    ap.add_argument(
        "--cross-subject", action="store_true",
        help="启用跨科兜底（默认关闭；仅用于排查科目字段写错的题）",
    )
    ap.add_argument(
        "--llm-uncorroborated", action="store_true",
        help="关闭第3层字面佐证闸门（不推荐：本机小模型会大幅误挂）",
    )
    return ap.parse_args()


def main() -> int:
    args = _parse_args()
    global FAST_LLM_MODEL
    if args.llm_model:
        FAST_LLM_MODEL = args.llm_model
    require_corr = not args.llm_uncorroborated
    do_rule = args.layer in ("rule", "all", "llm")   # llm 层也先跑规则层缩小范围
    do_llm = args.layer in ("llm", "all")

    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    points = _load_points(cur)
    questions = _load_questions(cur)
    q_by_id = {q["id"]: q for q in questions}
    kp_by_id = {p["id"]: p for p in points}

    links0, linked0, total0 = _coverage(cur)
    print(f"数据库: {DB_PATH}")
    print(f"题目 {total0} 题 / 知识点 {len(points)} 个 / 现有 links {links0} 条 "
          f"（覆盖 {linked0}/{total0} = {linked0 / total0 * 100:.1f}%）")

    existing = _existing_pairs(cur)
    linked_now = {r[0] for r in cur.execute(
        "SELECT DISTINCT question_id FROM question_knowledge_links")}

    # ---- 第 1 层 ----（全量精确匹配，--limit 不裁剪它，保证幂等口径一致）
    l1 = layer_rule_exact(questions, points)
    new_l1 = [x for x in l1 if x not in existing]
    print(f"[第1层·高置信 同科同名] 命中 {len(l1)} 条，其中新增 {len(new_l1)} 条")

    # 第 2/3 层只处理**尚未链上**的题（M1-1 精度要求：已由第 1 层同科同名链上的题
    # 不再重复挂，避免命中率虚高与噪声）。--limit 进一步限制处理量，便于分批。
    untouched = [q for q in questions if q["id"] not in linked_now]
    if args.limit and args.limit > 0:
        todo = untouched[: args.limit]
        print(f"本次处理未链题目（--limit={args.limit}）: {len(todo)}/{len(untouched)} 题；层={args.layer}\n")
    else:
        todo = untouched
        print(f"本次处理未链题目: {len(todo)}/{len(questions)} 题；层={args.layer}\n")

    # ---- 第 2 层 ----
    l2_raw: list[tuple[int, int, float]] = []
    if do_rule:
        l2_raw = layer_rule_text(
            todo, points, lexical_min=args.lexical_min, max_per_q=args.max_related,
            enable_cross_subject=args.cross_subject,
        )
        # 去掉与第 1 层同题的重复挂靠 + 已存在的 pair
        new_l1_pairs = set(new_l1)
        l2_cand = [
            (q, k, w) for (q, k, w) in l2_raw
            if (q, k) not in existing and (q, k) not in new_l1_pairs
        ]
        print(f"[第2层·中置信 题干文本] 命中 {len(l2_raw)} 条，其中新增 {len(l2_cand)} 条")
    else:
        l2_cand = []
        print("[第2层·中置信 题干文本] 已跳过（--layer=llm 之外）")

    # ---- 第 3 层：LLM 兜底（仅对前两层后仍未链上的题）----
    l3_cand: list[tuple[int, int, float]] = []
    llm_ok, llm_info = False, "未尝试"
    llm_skipped = 0
    if do_llm:
        covered = set(linked_now) | {q for q, _ in l1} | {q for q, _, _ in l2_cand}
        remain = [q for q in todo if q["id"] not in covered]
        llm_skipped = len(remain)
        print(f"[第3层·LLM 兜底] 待判题目 {len(remain)} 题")
        llm_ok, llm_info = _llm_available()
        print(f"[第3层·LLM 可用性] {'可用' if llm_ok else '不可用'} —— {llm_info}")
        if llm_ok and remain:
            from services.model_gateway import _ollama_installed

            model = _resolve_model(_ollama_installed())
            by_subj = _points_by_subject(points)
            # 按科目分组批量处理（候选=该科目全部 KP，避免跨科误判）
            groups: dict[str, list[dict]] = {}
            for q in remain:
                groups.setdefault(q["subject"], []).append(q)
            done = 0
            for subj, qs2 in groups.items():
                pts = by_subj.get(subj, [])
                if not pts:
                    continue
                got = llm_classify_batch(
                    qs2, pts, model=model, max_kp=LLM_MAX_KP,
                    require_corroboration=require_corr,
                )
                for qid, kid, w in got:
                    if (qid, kid) not in existing:
                        l3_cand.append((qid, kid, w))
                done += len(qs2)
                print(f"    LLM[{subj}] {len(qs2)} 题完成，累计新增 {len(l3_cand)} 条…")
            print(f"[第3层·LLM 兜底] 新增 {len(l3_cand)} 条（模型 {model}）")
    else:
        print("[第3层·LLM 兜底] 已跳过（未选 llm/all 层）")

    # ---- 汇总预览 ----
    proj_pairs = set(existing) | set(new_l1) | {(q, k) for q, k, _ in l2_cand} | {
        (q, k) for q, k, _ in l3_cand
    }
    proj_links = len(proj_pairs)
    proj_linked = len({q for q, _ in proj_pairs})
    print("\n===== 预览汇总 =====")
    print(f"新增：第1层 {len(new_l1)} + 第2层 {len(l2_cand)} + 第3层 {len(l3_cand)}"
          f" = {len(new_l1) + len(l2_cand) + len(l3_cand)} 条")
    print(f"覆盖率：{linked0}/{total0} = {linked0 / total0 * 100:.1f}%  →  "
          f"{proj_linked}/{total0} = {proj_linked / total0 * 100:.1f}%")
    print(f"links 总数：{links0} → {proj_links}")

    if args.sample > 0:
        print(f"\n----- 新增样例（随机 {args.sample} 条）-----")
        all_new = (
            [(q, k) for q, k in new_l1]
            + [(q, k, w) for q, k, w in l2_cand]
            + [(q, k, w) for q, k, w in l3_cand]
        )
        _print_samples(all_new, q_by_id, kp_by_id, args.sample)

    if not args.apply:
        print("\n[DRY-RUN] 未写库。确认无误后加 --apply 执行。")
        con.close()
        return 0

    # ---- 备份 ----
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_kplink_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )
    with sqlite3.connect(bak) as dest:
        con.backup(dest)
    print(f"\n已备份 → {bak}")

    # ---- 写库 ----
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.executemany(
        "INSERT INTO question_knowledge_links "
        "(question_id, knowledge_point_id, role, weight, is_verified, created_at) "
        "VALUES (?, ?, 'primary', 1.0, 1, ?)",
        [(q, k, now) for q, k in new_l1],
    )
    cur.executemany(
        "INSERT INTO question_knowledge_links "
        "(question_id, knowledge_point_id, role, weight, is_verified, created_at) "
        "VALUES (?, ?, 'related', ?, 0, ?)",
        [(q, k, w, now) for q, k, w in l2_cand],
    )
    cur.executemany(
        "INSERT INTO question_knowledge_links "
        "(question_id, knowledge_point_id, role, weight, is_verified, created_at) "
        "VALUES (?, ?, 'related', ?, 0, ?)",
        [(q, k, w, now) for q, k, w in l3_cand],
    )

    # ---- 回填知识点真实题数 ----
    # 口径：该知识点下**去重后的关联题目数**（primary + related 都算，
    # 让知识地图的"题数"反映本次回填带来的全部新增关联）。
    cur.execute(
        """
        UPDATE knowledge_points SET question_count = (
            SELECT COUNT(DISTINCT l.question_id) FROM question_knowledge_links l
            WHERE l.knowledge_point_id = knowledge_points.id
        )
        """
    )
    con.commit()

    links1, linked1, total1 = _coverage(cur)
    kps_with_q = cur.execute(
        "SELECT COUNT(*) FROM knowledge_points WHERE question_count > 0"
    ).fetchone()[0]
    print("\n===== 写库完成 =====")
    print(f"links 总数：{links0} → {links1}")
    print(f"覆盖题目：{linked0} → {linked1} / {total1}"
          f"（{linked0 / total0 * 100:.1f}% → {linked1 / total1 * 100:.1f}%）")
    print(f"有题的知识点：{kps_with_q}/{len(points)}")
    if not llm_ok:
        print(f"⚠️ 第3层 LLM 未执行（{llm_info}）—— 如需提升覆盖率请启动 Ollama 或配置云端 Key 后重跑。")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
