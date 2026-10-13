# -*- coding: utf-8 -*-
"""Chunk 级三路融合分类器（docx/14 方案的执行核心）。

## 为什么不是"文档整体打一个标签"

`kb_service.classify_subject_confidence()` 是**文档级**关键词打分：一份 PDF
前半高数后半大物时只能出一个标签，`KnowledgeChunk.subject` 又只是文档标签的
冗余拷贝。本模块把判定单元下沉到 chunk：

    路1 学科原型质心  bge 真模型 embedding × subject_prototypes 余弦相似度
    路2 关键词计分    复用 kb_service（16 科词表，零成本、可解释）
    路3 LLM 判定      仅在低置信 / 两路分歧时触发，一次输出 l1+l2+l3

三路加权融合 → chunk 三层标签 + 置信度 + 来源留痕；文档级再按 chunk 占比聚合。

## 与外部草案的差异（已在 docx/14 §2 裁定）

* 草案的"RoBERTa+LoRA 小分类模型"不落地：8GB 显存 + 几百条标注训不稳，
  路2 由现有关键词打分承担；评估闭环（scripts/chunk_classify_eval.py）
  证明两路 F1 不达标后再议。
* 学科枚举不采用草案 8 科表，以 `taxonomy` + `doc_lock_subjects` 为唯一事实源，
  并沿用 `kp_extract` 的压平标签黑名单（"数模电/公共课"绝不落库）。

## 向量口径红线（实测踩出来的，不要"优化"掉）

`knowledge_chunks_vec` 里 bge 与离线哈希向量**同为 512 维**、dim 列不区分引擎，
哈希向量做相似度=噪声。因此：
1. 质心与 chunk 编码都**只用 bge 真模型**（`generate_local_embeddings`），
   不可用就整路降级为关键词+LLM，source 留痕 `no_bge`；
2. **绝不读取 `knowledge_chunks_vec` 已存向量**凑数；
3. `subject_prototypes` 以 (subject, engine) 联合主键锁死口径。

## 模型调用

沿用 `kp_extract` 的实测教训：本机 Ollama 走 `urllib` 且必须
`ProxyHandler({})` 绕开 `http_proxy`；进程级信号量限制同时打模型的请求数。

## 开关

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `CHUNK_CLASSIFY_ENABLED` | `1` | 置 `0` 时入库钩子不打标 |
| `CHUNK_W_VECTOR` | `0.45` | 路1 权重 |
| `CHUNK_W_KEYWORD` | `0.45` | 路2 权重 |
| `CHUNK_W_LLM` | `0.10` | 路3 权重（参与融合的部分） |
| `CHUNK_CONF_THRESHOLD` | `0.40` | 低于此置信 → 触发 LLM（实测 147 样本：conf≥0.4 时域内精度 0.979、覆盖 80%） |
| `CHUNK_CLASSIFY_MODEL` | `kaoyan-assistant` | 路3 本地模型 |
| `CHUNK_LLM_SLOTS` | `2` | 同时打模型请求上限 |
| `CHUNK_LLM_MAX_PER_DOC` | `10` | 单文档 LLM 调用上限（成本闸门） |
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import sqlalchemy
from sqlalchemy.orm import Session

logger = logging.getLogger("chunk_classifier")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() not in ("0", "false", "off", "no")


CLASSIFY_ENABLED = _env_bool("CHUNK_CLASSIFY_ENABLED", True)
W_VECTOR = _env_float("CHUNK_W_VECTOR", 0.45)
W_KEYWORD = _env_float("CHUNK_W_KEYWORD", 0.45)
W_LLM = _env_float("CHUNK_W_LLM", 0.10)
CONF_THRESHOLD = _env_float("CHUNK_CONF_THRESHOLD", 0.40)
LLM_MAX_PER_DOC = _env_int("CHUNK_LLM_MAX_PER_DOC", 10)

LLM_MODEL = os.environ.get("CHUNK_CLASSIFY_MODEL", "kaoyan-assistant")
_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
_LLM_SEM = threading.BoundedSemaphore(_env_int("CHUNK_LLM_SLOTS", 2))

#: 幂等补列（沿用 kp_extract.ensure_kp_trace_columns 的模式）
CHUNK_LABEL_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("l2_chapter", "ALTER TABLE knowledge_chunks ADD COLUMN l2_chapter VARCHAR(200)"),
    ("l3_content_type", "ALTER TABLE knowledge_chunks ADD COLUMN l3_content_type VARCHAR(30)"),
    ("classify_confidence", "ALTER TABLE knowledge_chunks ADD COLUMN classify_confidence FLOAT"),
    ("classify_source", "ALTER TABLE knowledge_chunks ADD COLUMN classify_source VARCHAR(30)"),
)

#: 只允许出现在文档级的桶标签：块级选中它会吞掉真题卷里的非核心学科
#: （实测 147 样本人工判分：块级预测"真题综合" 32 次仅 3 次正确，
#:   其余全是医学/法硕/教育学等域外真题被硬塞进来的）
DOC_LEVEL_ONLY_LABELS: Tuple[str, ...] = ("真题综合",)

#: L3 内容语义类型候选集（docx/14 第一节问题 3）
L3_TYPES: Tuple[str, ...] = ("定义", "定理", "理论陈述", "例题", "习题", "证明", "公式", "实验步骤", "其他")

#: 非学科标签（融合结果不允许落这些值当学科）
_VACUOUS = {"其他", "其它", "未知", "未分类", "", None}


# --------------------------------------------------------------------------- #
# 垃圾块识别：PDF 指令残留 / 编译宏噪声 / 乱码 / 重复字符
#
# 只在"这块文本对检索没有任何价值"时弃权（写学科=其他，不进学科池、不参与文档聚合）。
# 实测口径（scripts/recognition_policy_eval.py 147 条人工判分 + scripts/junk_corpus_scan.py 全库）：
#   * pdf_operator / compile_noise：样本命中 4 条全是域外、域内误伤 0，
#     全库命中 1380 条（2.3%）→ 弃权让学科池精确率 0.755→0.771，域外污染 90.9%→81.8%。
#   * mojibake（私用区符号/生僻字符）**绝不弃权**：公式型 PDF 的数学块大量含符号字体残留，
#     全库命中 11068 条（18%，其中 4664 条是数学），实测弃权会把域内可检索率
#     0.947→0.842，是净亏损。这类块交给 OCR 侧重灌，不交给打标侧猜。
#   * repeat：全库 1685 条里有 1201 条是英文长篇/下划线练习位，样本上分不清好坏，暂不弃权。
# --------------------------------------------------------------------------- #
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
#: 正常中文文档里会出现的非 CJK 字符（全角标点/引号/破折号等），不计入乱码
_NONASCII_ALLOWED = "，。；：、！？（）《》〈〉“”‘’…—–·・～｜【】〔〕＂＇％＋－×÷°±℃"
_JUNK_PDF_OP_RE = re.compile(r"(?:/[A-Za-z]{1,6}[0-9a-fA-F]{1,4}\s*){4,}")
_JUNK_MACRO_RE = re.compile(r"(attribute__|__weak|__real|__FILE__|__LINE__)")
_JUNK_REPEAT_RE = re.compile(r"([^\s])(?:\s*\1){19,}")
#: 乱码阈值：16 个"非 ASCII、非 CJK、非常见标点"字符
JUNK_EXOTIC_MIN = _env_int("CHUNK_JUNK_EXOTIC_MIN", 16)
#: 或私用区符号残留占比 ≥10%
JUNK_PUA_SHARE_MIN = _env_float("CHUNK_JUNK_PUA_SHARE_MIN", 0.10)

#: 真正执行弃权的垃圾类型（其余只记录原因，不改标签）
JUNK_ABSTAIN_REASONS: Tuple[str, ...] = ("empty", "pdf_operator", "compile_noise")


def _exotic_count(text: str) -> int:
    n = 0
    for ch in text[:600]:
        if ch.isascii() or _CJK_RE.match(ch) or ch in _NONASCII_ALLOWED:
            continue
        n += 1
    return n


def _pua_share(text: str) -> float:
    """PDF 符号字体残留（私用区 U+E000–U+F8FF）占前 600 字符的比例。"""
    head = text[:600]
    if not head:
        return 0.0
    return sum(1 for ch in head if "\ue000" <= ch <= "\uf8ff") / len(head)


def junk_reason(text: str) -> str:
    """垃圾块类型（mojibake/pdf_operator/compile_noise/repeat/empty），正常块返回空串。"""
    t = text or ""
    if not t.strip():
        return "empty"
    if _JUNK_PDF_OP_RE.search(t):
        return "pdf_operator"
    if _JUNK_MACRO_RE.search(t):
        return "compile_noise"
    if _exotic_count(t) >= JUNK_EXOTIC_MIN or _pua_share(t) >= JUNK_PUA_SHARE_MIN:
        return "mojibake"
    if _JUNK_REPEAT_RE.search(t):
        return "repeat"
    return ""


def is_junk_chunk(text: str) -> bool:
    """该块是否应当弃权（不写学科）。"""
    return junk_reason(text) in JUNK_ABSTAIN_REASONS


def ensure_chunk_label_columns(db) -> List[str]:
    """给 `knowledge_chunks` 补齐三层标签列，返回本次新增列名。幂等。"""
    added: List[str] = []
    try:
        existing = {c["name"] for c in sqlalchemy.inspect(db).get_columns("knowledge_chunks")}
    except Exception:  # noqa: BLE001
        existing = set()
    for col, ddl in CHUNK_LABEL_COLUMNS:
        if col in existing:
            continue
        try:
            db.execute(sqlalchemy.text(ddl))
            added.append(col)
        except Exception as e:  # noqa: BLE001
            if "duplicate column" in str(e).lower():
                continue
            logger.warning("knowledge_chunks 加列 %s 失败: %s", col, e)
    if added:
        try:
            db.commit()
            logger.info("knowledge_chunks 新增标签列: %s", ", ".join(added))
        except Exception:  # noqa: BLE001
            db.rollback()
    return added


# --------------------------------------------------------------------------- #
# 学科候选集（taxonomy + doc_lock 为唯一事实源）
# --------------------------------------------------------------------------- #
def subject_candidates() -> Tuple[str, ...]:
    """chunk 学科候选 = CORE_SUBJECTS ∪ DOC_LOCK_ALLOWLIST（归一、去压平标签）。"""
    try:
        from services.taxonomy import CORE_SUBJECTS
        from services.doc_lock_subjects import DOC_LOCK_ALLOWLIST
    except Exception:  # noqa: BLE001
        return ("数字电子技术", "模拟电子技术", "数学", "英语", "政治", "真题综合")
    cands = []
    for s in (*CORE_SUBJECTS, *sorted(DOC_LOCK_ALLOWLIST)):
        if s not in cands:
            cands.append(s)
    return tuple(cands)


def _normalize_subject(raw: str) -> str:
    """归一到合法学科；压平标签/非法值返回空串（交给其他路决定，绝不猜）。"""
    from services.taxonomy import normalize_subject

    s = (raw or "").strip()
    if not s:
        return ""
    try:
        from services.kp_extract import _FLATTENED_LABELS

        if s in _FLATTENED_LABELS:
            return ""
    except Exception:  # noqa: BLE001
        pass
    std = normalize_subject(s)
    return std if std in subject_candidates() else ""


# --------------------------------------------------------------------------- #
# 路1：学科原型质心
# --------------------------------------------------------------------------- #
_PROTO_CACHE: Dict[str, object] = {"key": None, "protos": None}


def load_prototypes(db: Session) -> Dict[str, np.ndarray]:
    """读取 bge 质心（进程内缓存，按最新 built_at 失效重载）。

    只认 engine='bge'；缺失/维度不齐一律不加载（口径红线）。
    """
    try:
        from models import SubjectPrototype

        rows = (
            db.query(SubjectPrototype)
            .filter(SubjectPrototype.engine == "bge")
            .all()
        )
    except Exception:  # noqa: BLE001
        return {}
    if not rows:
        return {}
    key = max(r.built_at for r in rows if r.built_at)
    if _PROTO_CACHE["key"] == key and _PROTO_CACHE["protos"] is not None:
        return _PROTO_CACHE["protos"]  # type: ignore[return-value]
    protos: Dict[str, np.ndarray] = {}
    for r in rows:
        vec = np.frombuffer(r.vector, dtype=np.float32)
        if r.dim and vec.size != r.dim:
            continue
        protos[r.subject] = vec
    _PROTO_CACHE["key"] = key
    _PROTO_CACHE["protos"] = protos
    return protos


def _l2norm(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def encode_texts(texts: Sequence[str]) -> Optional[np.ndarray]:
    """bge 批量编码（同步）；模型不可用返回 None → 调用方整路降级。"""
    try:
        from services.embedding_service import (
            generate_local_embeddings, is_local_model_available,
        )

        if not is_local_model_available():
            return None
        vecs = generate_local_embeddings(list(texts))
        return np.vstack(vecs)
    except Exception as e:  # noqa: BLE001
        logger.info("bge 编码不可用，路1 降级: %s", e)
        return None


def vector_scores(embedded: Optional[np.ndarray], protos: Dict[str, np.ndarray]) -> Dict[str, float]:
    """单块向量 × 各科质心余弦 → softmax 加权分布。无输入返回 {}。"""
    if embedded is None or not protos:
        return {}
    q = _l2norm(np.asarray(embedded, dtype=np.float32))
    sims = {s: float(np.dot(q, _l2norm(p))) for s, p in protos.items()}
    if not sims:
        return {}
    vals = np.array(list(sims.values()), dtype=np.float64)
    w = np.exp(vals * 6.0)          # beta=6：拉开相邻科的差距
    w /= w.sum()
    return {s: float(x) for s, x in zip(sims.keys(), w)}


# --------------------------------------------------------------------------- #
# 路2：关键词计分（复用 kb_service）
# --------------------------------------------------------------------------- #
def keyword_scores(file_name: str, text: str) -> Tuple[str, float]:
    """返回 (学科, 权重系数 0~1)。低置信给半票，与文档级口径一致但下沉到块。"""
    try:
        from services.kb_service import classify_subject_confidence

        subj, confident = classify_subject_confidence(file_name, text or "", allow_weak=True)
        subj = _normalize_subject(subj)
        if not subj:
            return "", 0.0
        return subj, (1.0 if confident else 0.5)
    except Exception:  # noqa: BLE001
        return "", 0.0


# --------------------------------------------------------------------------- #
# L3 内容语义类型：规则速判（LLM 缺席时兜底；LLM 在场时以其输出为准）
# --------------------------------------------------------------------------- #
_L3_RULES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("习题", re.compile(r"(习题|练习|课后题|作业|思考题|题\s*\d|[（(]\d+[)）].{0,12}(求|证|计算)|\bA[．.、]\s*\S+.*\bB[．.、]\s*\S+.*(C[．.、]|D[．.、]))")),
    ("例题", re.compile(r"(【?例\s*[一二三四五六七八九十\d]+】?|典型题|例题)")),
    ("证明", re.compile(r"(证明如下|证\s*明[:：]|试证|求证)")),
    ("定理", re.compile(r"(定理|推论|性质\s*\d|拉格朗日|洛必达|泰勒公式)")),
    ("定义", re.compile(r"(定义[:：]|称为|记作|定\s*义|称之为)", re.S)),
    ("公式", re.compile(r"(公式[:：]|\\frac|\\sum|=.*\\[a-zA-Z]+)")),
    ("实验步骤", re.compile(r"(实验目的|实验器材|实验步骤|仪器|接线|测量记录表)")),
)


def l3_rules(text: str) -> str:
    t = (text or "")[:800]
    for label, pat in _L3_RULES:
        if pat.search(t):
            return label
    return "其他"


# --------------------------------------------------------------------------- #
# 路3：LLM 判定（低置信兜底；一次输出三层标签）
# --------------------------------------------------------------------------- #
def _build_opener() -> "urllib.request.OpenerDirector":
    """绕代理的 opener —— 同 kp_extract._build_opener，实测教训不要优化掉。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


_OPENER = _build_opener()

_LLM_PROMPT = """任务：对下面文本块做内容打标，只从给定候选集中选择。
候选L1学科：{subjects}
候选L3类型：定义|定理|理论陈述|例题|习题|证明|公式|实验步骤|其他
输出 JSON（不要输出其他内容）：
{{"l1_subject":"","l2_chapter":"","l3_content_type":"","confidence":0.0,"reason":""}}
约束：
- l2_chapter 只能取自文本内出现的小节/章节标题原文；没有依据就留空字符串。
- 文本块可能是单个知识点片段，选择主体所属学科；无法判断时 confidence 给 0.3 以下。
- 禁止输出"数模电/公共课"这类合并标签，必须细分到候选学科。
文本块（来自《{file_name}》，第 {chunk_no} 块）：
{text}"""


def _chat_local(messages: Sequence[Dict[str, str]], *, timeout: float = 90.0) -> str:
    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": list(messages),
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 8192},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{_OLLAMA_HOST}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with _OPENER.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


_JSON_RE = re.compile(r"\{[\s\S]*\}")

# 严格 JSON 失败时的宽松字段抽取（先带引号形式，再裸值形式）。故意不含 reason：
# 实测 3B 模型最爱在 reason 里写未转义的中文引号
# （`"reason": "文本属于"生理学"范畴"`），正是它让 json.loads 报错；
# reason 只是留痕字段，丢了不影响判定。
_LLM_FIELD_RE: Dict[str, Tuple["re.Pattern[str]", "re.Pattern[str]"]] = {
    k: (re.compile('"' + k + r'"\s*:\s*"([^"]*)"'),
         re.compile('"' + k + r'"\s*:\s*([^,\n}\s][^,\n}]*)'))
    for k in ("l1_subject", "l2_chapter", "l3_content_type", "confidence")
}


def _parse_llm_output(raw: str) -> Optional[Dict[str, object]]:
    """模型输出 → 字段字典；解析不出来返回 None。

    先按严格 JSON，失败再按字段名宽松抽取。实测同一篇 10 次调用里有 2 次
    （20%）只因 reason 里的裸引号而整块丢弃，这 20% 是本函数的存在理由。
    """
    if not raw:
        return None
    m = _JSON_RE.search(raw)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    lenient: Dict[str, object] = {}
    for key, (quoted, bare) in _LLM_FIELD_RE.items():
        for pat in (quoted, bare):
            fm = pat.search(raw)
            if fm:
                lenient[key] = fm.group(1).strip().strip('"')
                break
    return lenient or None


def llm_classify(file_name: str, text: str, chunk_no: int = 0) -> Optional[Dict[str, object]]:
    """单块 LLM 打标。失败/超时/非法 JSON → None（融合层自行降级，绝不抛）。"""
    clipped = (text or "")[:1200]
    if not clipped.strip():
        return None
    prompt = _LLM_PROMPT.format(
        subjects="|".join(subject_candidates()),
        file_name=(file_name or "")[:60],
        chunk_no=chunk_no,
        text=clipped,
    )
    try:
        with _LLM_SEM:
            raw = _chat_local([{"role": "user", "content": prompt}])
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 打标调用失败（%s）: %s", LLM_MODEL, e)
        return None
    obj = _parse_llm_output(raw)
    if obj is None:
        logger.warning("LLM 打标输出无法解析，丢弃: %r", (raw or "")[:120])
        return None
    try:
        subj = _normalize_subject(str(obj.get("l1_subject", "")))
        l3 = str(obj.get("l3_content_type", "")).strip()
        try:
            conf = float(obj.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            conf = 0.0
        return {
            "l1_subject": subj,           # 非法学科 → 空串，绝不落库
            "l2_chapter": str(obj.get("l2_chapter", "")).strip()[:200],
            "l3_content_type": l3 if l3 in L3_TYPES else "",
            "confidence": max(0.0, min(1.0, conf)),
            "reason": str(obj.get("reason", ""))[:200],
        }
    except Exception as e:  # noqa: BLE001
        # 实测教训：这里的一个 NameError（L3_TYPES 曾被并进 # 注释里，从未定义成功）
        # 直接把整篇回填打断在 classify_document 的 commit 之前，路3 因此从未生效。
        # 本函数的契约是"绝不抛"，异常块降级为 None 让融合层继续走两路。
        logger.warning("LLM 打标结果规整失败（丢弃该块）: %s", e)
        return None


# --------------------------------------------------------------------------- #
# 融合
# --------------------------------------------------------------------------- #
@dataclass
class ChunkLabel:
    subject: str = ""
    l2_chapter: str = ""
    l3_content_type: str = "其他"
    confidence: float = 0.0
    source: str = "fallback"
    votes: Dict[str, float] = field(default_factory=dict)


def fuse(label: ChunkLabel, kw_subj: str, kw_w: float,
         vec_dist: Dict[str, float], llm_out: Optional[Dict[str, object]]) -> ChunkLabel:
    """把三路证据合成最终标签。规则（对齐 kp_extract.resolve_subject 的留痕习惯）：

    * 两路都有且一致 → confidence 加成，source='fusion'
    * 不一致 → 加权取胜者，落败方保留在 votes 里供评估
    * LLM 合法且自信(≥0.6)而融合仍低置信 → 采信 LLM，source='llm'
    """
    total_w = 0.0
    scores: Dict[str, float] = {}

    if vec_dist:
        total_w += W_VECTOR
        for s, p in vec_dist.items():
            scores[s] = scores.get(s, 0.0) + W_VECTOR * p
    if kw_subj and kw_w > 0:
        total_w += W_KEYWORD
        scores[kw_subj] = scores.get(kw_subj, 0.0) + W_KEYWORD * kw_w
    if llm_out and llm_out.get("l1_subject"):
        total_w += W_LLM
        scores[str(llm_out["l1_subject"])] = (
            scores.get(str(llm_out["l1_subject"]), 0.0) + W_LLM * float(llm_out["confidence"])
        )

    label.votes = scores
    if not scores or total_w <= 0:
        label.source = "fallback"
        label.confidence = 0.0
        return label

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    while ranked and ranked[0][0] in DOC_LEVEL_ONLY_LABELS:
        ranked = ranked[1:]
    if not ranked:
        label.source = "fallback"
        label.confidence = 0.0
        return label
    top_subj, top_score = ranked[0]
    label.subject = top_subj
    # 分母沿用全量权重：真题综合被剔除后不重新归一化，
    # 让"证据本来分裂"的块继续留低置信，交给路3 判断而不是冒充高置信。
    label.confidence = round(top_score / total_w, 4)

    if llm_out and llm_out.get("l1_subject") == top_subj and kw_subj == top_subj and vec_dist:
        label.source = "fusion"
    elif llm_out and llm_out.get("l1_subject") and float(llm_out["confidence"]) >= 0.6 \
            and label.confidence < CONF_THRESHOLD:
        label.source = "llm"
    elif vec_dist and kw_subj == top_subj:
        label.source = "fusion"
    elif not vec_dist:
        label.source = "llm" if (llm_out and llm_out.get("l1_subject") == top_subj) else "keyword"
    else:
        label.source = "vector" if kw_subj != top_subj else "fusion"

    if llm_out:
        label.l2_chapter = str(llm_out.get("l2_chapter") or "") or label.l2_chapter
        if llm_out.get("l3_content_type"):
            label.l3_content_type = str(llm_out["l3_content_type"])
    return label


def needs_llm(label: ChunkLabel, kw_subj: str, vec_top: str) -> bool:
    """融合后是否值得花一次 LLM：低置信 或 两路头名分歧。"""
    if label.confidence < CONF_THRESHOLD:
        return True
    if vec_top and kw_subj and vec_top != kw_subj:
        return True
    return False


# --------------------------------------------------------------------------- #
# 批量打标 + 文档聚合
# --------------------------------------------------------------------------- #
#: 检索镜像表 → 其中指向 knowledge_chunks.id 的列
MIRROR_TABLES: Tuple[Tuple[str, str], ...] = (
    ("knowledge_chunks_fts", "chunk_id"),
    ("knowledge_chunks_vec", "chunk_id"),
)


def sync_mirror_subjects(db: Session,
                         chunk_ids: Optional[Sequence[int]] = None) -> Dict[str, int]:
    """把 `knowledge_chunks.subject` 同步进检索镜像（fts / vec），返回各表影响行数。

    为什么必须同步：检索的学科过滤打在**镜像列**上，而镜像列是入库时的拷贝，
    打标与弃权只改 chunk 表。全库实测漂移 9704/61032 = **15.9%**，其中 1235 块
    已判「其他」（junk 弃权）却仍挂在具体学科池里 —— 回填结果根本没被检索消费。

    为什么用单条关联子查询：FTS5 的 `chunk_id` 是 UNINDEXED、rowid 自增
    （rowid != chunk_id），逐行 `WHERE chunk_id=?` 每行都要全表扫描，实测 199 块
    耗时 3.1s（全库回填外推 ≈ 6600s）；改成整表关联更新 0.62s、限定块集合 0.03s。

    必须在 `db.commit()` 之后调用：镜像表可能尚未创建（新库/未跑检索），
    失败时回滚的只是本次同步，已提交的 chunk 标签不受影响。
    """
    from sqlalchemy import bindparam, text

    out: Dict[str, int] = {}
    ids: Optional[List[int]] = None
    if chunk_ids is not None:
        ids = [int(i) for i in chunk_ids]
        if not ids:
            return {tbl: 0 for tbl, _ in MIRROR_TABLES}

    for tbl, key in MIRROR_TABLES:
        # EXISTS 守卫：孤儿镜像行（chunk 已被删）不能被关联子查询刷成 NULL，
        # 否则体检脚本会把"孤儿行"误报成"学科漂移"。孤儿行由 --prune-orphans 显式处理。
        src = (f"SELECT kc.subject FROM knowledge_chunks kc "
               f"WHERE kc.id = {tbl}.{key}")
        sql = f"UPDATE {tbl} SET subject = ({src})"
        params: Dict[str, object] = {}
        ids_where = ""
        if ids is not None:
            ids_where = f" WHERE {key} IN :ids"
            params["ids"] = ids
            sql += ids_where + f" AND EXISTS ({src})"
        else:
            sql += f" WHERE EXISTS ({src})"
        stmt = text(sql)
        if ids is not None:
            stmt = stmt.bindparams(bindparam("ids", expanding=True))
        try:
            res = db.execute(stmt, params)
            updated = int(res.rowcount or 0)
            db.commit()
            out[tbl] = updated
            if ids is not None:
                # 镜像里**根本没有这些块**时 UPDATE 一行都不动 —— 打标改了个检索
                # 召不到的块，必须吼一声，否则 59 块未进 fts / 42925 块未进 vec 会一直被藏着。
                want = {int(i) for i in ids}
                found_stmt = text(f"SELECT DISTINCT {key} FROM {tbl}{ids_where}").bindparams(
                    bindparam("ids", expanding=True))
                found = {int(r[0]) for r in db.execute(found_stmt, params).fetchall()}
                missing = want - found
                if missing:
                    logger.warning(
                        "检索镜像 %s 缺 %d/%d 个块（chunk_ids=%s…），本次学科改动对检索无效；"
                        "需重建该镜像索引", tbl, len(missing), len(want),
                        ",".join(str(x) for x in sorted(missing)[:5]))
        except Exception as e:  # noqa: BLE001
            logger.warning("检索镜像 %s 学科同步失败（chunk 标签已提交，不受影响）: %s", tbl, e)
            db.rollback()
            out[tbl] = -1
    return out


def classify_document(db: Session, doc_id: int, *, use_llm: bool = True,
                      only_unlabeled: bool = False,
                      progress=None) -> Dict[str, object]:
    """对一篇文档的全部 chunk 三路打标 + 聚合回写文档学科。

    两遍结构省开销：先批量 bge 编码跑路1+路2，仅挑出的低置信块进路3。
    """
    from models import Document, KnowledgeChunk

    ensure_chunk_label_columns(db)
    doc = db.get(Document, doc_id)
    if doc is None:
        return {"ok": False, "message": f"document {doc_id} 不存在"}

    q = db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc_id)
    if only_unlabeled:
        q = q.filter(KnowledgeChunk.l3_content_type.is_(None))
    chunks = q.order_by(KnowledgeChunk.chunk_id).all()
    if not chunks:
        return {"ok": True, "chunks": 0, "stats": {}}

    protos = load_prototypes(db)
    emb = encode_texts([c.text or "" for c in chunks]) if protos else None
    vec_ok = emb is not None and bool(protos)

    # 第一遍：路1+路2 证据缓存（LLM 挑中的块第二遍直接复用，不重复算）
    kw_ev: List[Tuple[str, float]] = []
    vec_ev: List[Dict[str, float]] = []
    prelim: List[ChunkLabel] = []
    junk_ev: List[str] = []
    for i, c in enumerate(chunks):
        vec_dist = vector_scores(None if emb is None else emb[i], protos)
        kw_subj, kw_w = keyword_scores(doc.file_name, c.text or "")
        lab = ChunkLabel(l3_content_type=l3_rules(c.text or ""))
        fuse(lab, kw_subj, kw_w, vec_dist, None)
        kw_ev.append((kw_subj, kw_w))
        vec_ev.append(vec_dist)
        prelim.append(lab)
        junk_ev.append(junk_reason(c.text or ""))

    llm_done = llm_failed = junk_done = 0
    for i, c in enumerate(chunks):
        if junk_ev[i] in JUNK_ABSTAIN_REASONS:
            # 弃权：不猜学科，也省掉这次 LLM 调用
            c.subject = "其他"
            c.l2_chapter = None
            c.l3_content_type = "其他"
            c.classify_confidence = 0.0
            c.classify_source = f"junk:{junk_ev[i]}"
            junk_done += 1
            continue
        lab = prelim[i]
        kw_subj, kw_w = kw_ev[i]
        vec_top = max(vec_ev[i], key=lambda s: vec_ev[i][s]) if vec_ev[i] else ""
        # 上限按"发起次数"而非"成功次数"计：模型不可用时成功数恒为 0，
        # 按成功数封顶等于对每个低置信块无限重试。
        if use_llm and (llm_done + llm_failed) < LLM_MAX_PER_DOC and needs_llm(lab, kw_subj, vec_top):
            out = llm_classify(doc.file_name, c.text or "", c.chunk_id or i)
            if out:
                llm_done += 1
                lab2 = ChunkLabel(l3_content_type=l3_rules(c.text or ""))
                fuse(lab2, kw_subj, kw_w, vec_ev[i], out)
                if lab2.subject:
                    lab = lab2
            else:
                llm_failed += 1
        if not lab.subject:
            lab.subject = _normalize_subject(doc.subject or "") or ""
            if lab.subject:
                lab.source = "document"
        if lab.source == "fallback" and not vec_ok:
            lab.source = "no_bge"
        c.subject = lab.subject or c.subject
        c.l2_chapter = lab.l2_chapter or None
        c.l3_content_type = lab.l3_content_type
        c.classify_confidence = lab.confidence
        c.classify_source = lab.source

    db.commit()
    # 标签只有同步进检索镜像才会真正影响召回；镜像列是入库时的拷贝，不同步就一直漂移。
    mirror = sync_mirror_subjects(db, [c.id for c in chunks])
    agg = aggregate_document(db, doc_id)
    if progress:
        progress(len(chunks), len(chunks))
    return {
        "ok": True, "chunks": len(chunks), "llm_calls": llm_done,
        "llm_failed": llm_failed,
        "junk_skipped": junk_done, "no_bge": emb is None, "aggregate": agg,
        "mirror_synced": mirror,
    }


def aggregate_document(db: Session, doc_id: int) -> Dict[str, object]:
    """文档聚合：chunk 学科占比 → 主学科。

    口径（docx/14 §2.3）：只回写"原学科为空/兜底值"的文档；已有标签不动
    （文档学科锁语义保持），但占比统计照常返回，供人工核查混合文档。
    """
    from models import Document, KnowledgeChunk
    from sqlalchemy import func

    doc = db.get(Document, doc_id)
    if doc is None:
        return {}
    # 弃权块（学科=其他）和未打标块不参与主学科投票，否则 OCR 垃圾会把文档判给"其他"
    rows = (
        db.query(KnowledgeChunk.subject, func.count(KnowledgeChunk.id))
        .filter(KnowledgeChunk.document_id == doc_id)
        .filter(KnowledgeChunk.subject.isnot(None))
        .filter(~KnowledgeChunk.subject.in_(tuple(v for v in _VACUOUS if v)))
        .group_by(KnowledgeChunk.subject)
        .all()
    )
    total = sum(cnt for _, cnt in rows)
    shares = {str(s or "其他"): cnt / max(total, 1) for s, cnt in rows}
    main = max(shares.items(), key=lambda kv: kv[1])[0] if shares else ""

    updated = False
    if doc and total and (not (doc.subject or "").strip() or (doc.subject or "").strip() in _VACUOUS):
        if main not in _VACUOUS and main in subject_candidates():
            doc.subject = main
            updated = True
            db.commit()
    return {
        "doc_id": doc_id, "chunks": total, "main_subject": main,
        "shares": {k: round(v, 4) for k, v in shares.items()},
        "mixed": bool(shares) and max(shares.values()) < 0.85,
        "subject_updated": updated,
    }
