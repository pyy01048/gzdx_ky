# -*- coding: utf-8 -*-
"""入库时知识点抽取（挂在 `services.smart_ingest` 上的钩子）。

## 为什么需要这个模块

`knowledge_chunks` 有 3.4 万条，但 `knowledge_points` 只有 1050 条 —— 教材正文
进了检索层，却没有长出结构化的知识点节点，「知识地图」是空心的。
本模块让**新文档在入库的同一时刻**长出知识点节点，而不是事后再补。

## 复用既有能力（不重写）

* 分块：`services.document_analyzer.smart_chunk_text`（章节标题优先的分块）
* 提示词：`services.document_analyzer.KNOWLEDGE_POINT_PROMPT`（在其上加约束，
  不替换原文，避免与既有抽取口径漂移）
* 噪声判定：`scripts/clean_knowledge_points` 的保守规则（此处等价内联，
  见 `is_noise_name`，因为 services 层不应反向依赖 scripts 层）
* 学科词表：`services.taxonomy.CORE_SUBJECTS` —— **6 个细分学科，绝不压平**

## 三条硬约束

1. **溯源**：每个知识点写 `document_id`（已有外键）+ `source_chunk_id`
   + `source_chunk_index`，可反查来自哪篇文档的哪一块。
2. **学科双路判定**：关键词推断（`kb_service.classify_subject_confidence`）
   与模型判定并跑；不一致时**以模型为准**，但把判定来源写进 `subject_source`
   列留痕（`model` / `keyword` / `model_over_keyword` / `fallback`）。
3. **质量门禁**：名称噪声 / 纯标题 / 释义过短 / 无实质释义 / 重复 → 丢弃并计数。

## 并发

模型调用是 IO 密集，**必须并发**，否则 6 个 ingest worker 会被串行模型调用拖死。
本模块对单文档内的 chunk 用 `ThreadPoolExecutor` 并发；跨文档用一个**进程级信号量**
（`_MODEL_SEM`）限制同时打到本地模型的请求数，避免把 Ollama 打爆。

## 开关

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `SMART_INGEST_KP` | `1` | 置 `0` 关闭入库时知识点抽取 |
| `SMART_INGEST_KP_CONCURRENCY` | `2` | 单文档内 chunk 级并发度（8GB 单卡别调高） |
| `SMART_INGEST_KP_MODEL_SLOTS` | `3` | 全局同时打模型的请求上限 |
| `SMART_INGEST_KP_MODEL` | `qwen2.5-coder:7b` | 抽取用本地模型（见上方选型注释） |
| `SMART_INGEST_KP_TIMEOUT` | `420` | 单次模型调用超时（秒） |
| `SMART_INGEST_KP_MAX_PER_DOC` | `15` | 单文档知识点上限 |
| `SMART_INGEST_KP_MAX_CHUNKS` | `8` | 单文档最多抽多少块（封顶模型负载，均匀取样） |
| `SMART_INGEST_KP_MIN_DOC_CHARS` | `800` | 正文短于此值不抽（省模型负载） |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | 本地模型地址；缺 scheme 会自动补，通配监听地址（`0.0.0.0`）自动换 `127.0.0.1` |

## 网络注意

本机Ollama 在 `127.0.0.1:11434`，但很多环境设了 `http_proxy`。`urllib` 默认读这些
变量，会把**本机**请求也塞进代理导致超时/空响应。因此 `_OPENER` 显式
`ProxyHandler({})` 绕过 —— 这一点是实测踩出来的，不要"优化"掉。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

import sqlalchemy
from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


#: 入库时是否自动抽取知识点（默认开；关掉即退回「事后批量补」的老路）
KP_EXTRACT_ENABLED = _env_bool("SMART_INGEST_KP", True)
#: 单文档内 chunk 级并发度。
#: ⚠️ 别调高：本机是 8GB 显存单卡，Ollama 对同一模型**串行**排队，
#: 并发只会让每个请求都变慢并撞 timeout（实测 concurrency=3 时 2/4 块超时）。
#: 实测稳的组合：并发 2 + 全局槽位 3。
KP_CONCURRENCY = max(1, _env_int("SMART_INGEST_KP_CONCURRENCY", 2))
#: 全局模型并发槽位（跨文档共享）
KP_MODEL_SLOTS = max(1, _env_int("SMART_INGEST_KP_MODEL_SLOTS", 3))
#: 抽取用本地模型。
#: ⚠️ 实测选型结论（别改回kaoyan-assistant）：`kaoyan-assistant` 是**问答微调**模型，
#: 对「抽取知识点」这类指令一律回 `[]`（6/6 块全空，实测）；`qwen2.5-coder:7b`
#: 能正常产出结构化 JSON 并通过门禁。qwen3 系列是思维链模型，长 prompt 下极慢，不适合批量。
KP_MODEL = os.environ.get("SMART_INGEST_KP_MODEL", "qwen2.5-coder:7b")
#: 单次模型调用超时。实测 qwen2.5-coder:7b 在 7B/8GB 卡上处理 4000 字块
#: 需要 150–250秒，180秒偏紧（实测有超时），抬到 420。
KP_TIMEOUT = _env_float("SMART_INGEST_KP_TIMEOUT", 420.0)
#: 单文档知识点上限
KP_MAX_PER_DOC = max(1, _env_int("SMART_INGEST_KP_MAX_PER_DOC", 15))
#: 正文短于此值不抽
KP_MIN_DOC_CHARS = _env_int("SMART_INGEST_KP_MIN_DOC_CHARS", 800)
#: 单文档最多抽多少个 chunk —— 给本地模型**封顶负载**。
#: 教材动辄 90+ 块，全抽既慢又无必要（知识点边际收益递减）。
KP_MAX_CHUNKS_PER_DOC = _env_int("SMART_INGEST_KP_MAX_CHUNKS", 8)
#: 交给模型的单块字符上限
KP_CHUNK_CHARS = 4000

def _resolve_ollama_host() -> str:
    """规范化 Ollama 地址。

    实测踩到的坑：本机**用户级**环境变量 `OLLAMA_HOST=0.0.0.0:11434`（为开放局域网
    访问而设）。它是**监听地址**（服务端语义），直接当客户端目标用有两处硬伤：
      1. 缺 `http://` scheme → `urllib` 抛 `unknown url type: 0.0.0.0`，
         模型调用**秒败**（0.1–0.4s），表现为 `knowledge_points` 恒为 0 且无超时告警；
      2. 即便补了 scheme，Windows 上连 `0.0.0.0` 也不可达（Linux 才等价 localhost）。

    这里曾是全后端**唯一**正确实现；现算法下沉到 `utils/ollama_host.py` 供
    ai_service / ai_router / retrieval_enhance / chunk_classifier / circuit_analysis /
    routers.ai 等模块共用，本函数保留为兼容壳（`scripts/kp_backfill_batch.py` 等
    仍引用 `kp._OLLAMA_HOST`）。
    """
    from utils.ollama_host import resolve_ollama_host

    return resolve_ollama_host()


_OLLAMA_HOST = _resolve_ollama_host()

#: **进程级**模型并发闸门 —— 6 个 ingest worker 共用，避免把本地模型打爆
_MODEL_SEM = threading.BoundedSemaphore(KP_MODEL_SLOTS)

#: 新增列（幂等 ALTER，见 `ensure_kp_trace_columns`）。
#: 关键：必须带 `IF NOT EXISTS` —— PG（与 SQLite 3.30+）都支持。否则在已迁移的库上
#: 重复 ALTER 会抛 DuplicateColumn，且不回滚会污染整条事务（InFailedSqlTransaction）。
KP_TRACE_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("source_chunk_id", "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS source_chunk_id INTEGER"),
    ("source_chunk_index", "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS source_chunk_index INTEGER"),
    ("extract_source", "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS extract_source TEXT"),
    ("subject_source", "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS subject_source TEXT"),
)


# --------------------------------------------------------------------------- #
# 噪声 / 质量判定
# --------------------------------------------------------------------------- #
# 与 scripts/clean_knowledge_points.py 的保守规则保持等价：
# 宁可漏删不可误删 ——「栈」「栅」这类短词是真知识点。
_RE_ONLY_NUM = re.compile(r"^[\d\s]+$")
_RE_ONLY_SEQ = re.compile(r"^[（(【\[]?\s*\d{1,2}\s*[)）】\].、,，]?$")
_RE_SUBSCRIPT = re.compile(r"^[\(（]?\d+[\)）]?[\(（]?[\d\.\{\}_a-zA-Z]{0,12}[\)）]?_\{?\d+\}?$")
_RE_ONLY_PUNCT = re.compile(r"^[\W_]+$", re.U)
_RE_CJK = re.compile(r"[\u4e00-\u9fa5]")
_RE_LATIN = re.compile(r"[A-Za-z]{3,}")

#: 短但确有专业含义的符号/单字，不按「过短」丢弃
_KEEP_SHORT = {
    "栈", "队列", "树", "图", "网", "串", "堆", "表",
    "fH", "fL", "d", "q", "cp", "clk", "en", "oe", "wr", "rd", "cs",
    "熵", "码", "阵", "群", "环", "域", "积", "和", "差", "角", "相", "态",
    "键", "路", "门", "栅", "极", "阻", "容", "感", "场", "位", "线", "面",
    "体", "点", "段", "区", "层", "序", "率", "幅", "频", "谱", "波", "峰",
    "谷", "阶", "弧", "隙", "耗", "散", "增益", "带宽",
}

#: 纯标题类词（只有这些词构成的「知识点」是标题而非知识点）
_TITLE_WORDS = re.compile(
    r"^(第[一二三四五六七八九十\d]+[章节篇讲]|[一二三四五六七八九十]+、|"
    r"知识点|考点|重点|难点|例题|习题|小结|总结|概述|引言|绪论|目录|"
    r"前言|附录|参考文献|习题答案|答案|解析)$")


def is_noise_name(name: str) -> bool:
    """知识点名称是否为噪声（纯序号/纯数字/下标残片/纯标点/OCR 崩坏串）。"""
    n = (name or "").strip()
    if not n:
        return True
    if n in _KEEP_SHORT:
        return False
    if _RE_ONLY_NUM.match(n) or _RE_ONLY_SEQ.match(n) or _RE_ONLY_PUNCT.match(n):
        return True
    if _RE_SUBSCRIPT.match(n) and not _RE_CJK.search(n):
        return True
    if len(n) <= 2 and not _RE_CJK.search(n):
        return True
    # OCR 崩坏长串：几乎无中文且含大量下划线/花括号
    if len(n) > 6 and not _RE_CJK.search(n) and n.count("{") + n.count("}") >= 2:
        return True
    return False


def name_is_title_only(name: str, chapter: str = "") -> bool:
    """纯标题：本身就是章节号/「知识点」「小结」这类结构词。"""
    n = (name or "").strip()
    if not n:
        return True
    if _TITLE_WORDS.match(n):
        return True
    if chapter and n == chapter.strip():
        return True
    return False


#: 释义最短长度。实测 `串`→"字符序列，用于存储字符串数据。"（14字）这种
#: 敷衍释义能过 15 字门槛却毫无价值；抬到 24 字。
MIN_DESC_CHARS = 24


def desc_is_substantive(desc: str, name: str) -> bool:
    """释义是否有实质内容（长度够 + 有实义文字 + 不是把名称复读一遍）。

    中英文都算实义文字 —— 考研英语/408 资料的释义是英文，不能被中文字门禁误杀。
    """
    d = (desc or "").strip()
    if len(d) < MIN_DESC_CHARS:
        return False
    if not _RE_CJK.search(d) and not _RE_LATIN.search(d):
        return False   # 无中文也无成词拉丁字母 → 多为公式/乱码
    # 释义 = 名称（可带标点）的复读 → 无实质信息
    core = re.sub(r"[\s\W]", "", name or "")
    body = re.sub(r"[\s\W]", "", d)
    if core and body and (core == body or body.startswith(core)
                          and len(body) - len(core) < 12):
        return False
    return True


#: 「正常」字符 = ASCII + CJK 基本区（U+4E00–U+9FFF，简体与繁体都在此区间）。
#:
#: 天书检测不靠枚举坏区间（造字机字形散落在几十个区，靠枚举必漏），而是反过来数
#: **正常字符占比**：PDF 字体缺失时标题会变成 `10.2.1 ⭘䰘⭥䐟㓴ᡀⲴᯭᇶ⢩䀖`，
#: 这些字符全落在 CJK 扩展区/谚文/古马拉地/卡纳达等区，正常字符占比极低。
_RE_COMMON_CHARS = re.compile(r"[ -~一-鿿]")


def text_is_mojibake(text: str, *, thresh: float = 0.6) -> bool:
    """文本是否天书（正常字符占比过低）。

    Args:
        thresh: 正常字符占比下限。中文正常句子接近 1.0；上面那串天书约 0.38。
    """
    t = (text or "").strip()
    if not t:
        return False
    good = len(_RE_COMMON_CHARS.findall(t))
    return good / len(t) < thresh


def sanitize_chapter(chapter: str, fallback: str = "") -> str:
    """章节名清洗：天书章节名丢掉，退回可用兜底；都没有则空串。

    实测踩到：某PDF 字体缺失，章节标题成`10.2.1 ⭘䰘⭥䐟㓴ᡀⲴᯭᇶ⢩䀖`，
    直接入库会让知识地图出现乱码节点。
    """
    c = (chapter or "").strip()
    if c and not text_is_mojibake(c):
        return c[:200]
    fb = (fallback or "").strip()
    if fb and not text_is_mojibake(fb):
        return fb[:200]
    return ""


#: 出版/网课**宣传与版权页噪声** —— 教材 txt/PDF 前几页常带这类内容，
#: 模型会当成知识点抽出来（实测抓到「数字课程资源」「课程有效期」
#!「自测题和参考答案」「拓展阅读资料」「硬件限制」）。必须拦掉。
_BOILERPLATE_PATTERNS = (
    "数字课程", "课程资源", "课程有效期", "配套课程", "学习网站", "配套资源",
    "扫描全能王", "CamScanner", "仅供学习", "请勿传播", "内部资料", "盗版必究",
    "二维码", "扫一扫", "关注公众号", "点击查看", "配套答案", "答案速查",
    "电子书", "在线阅读", "下载App", "app下载", "客服", "微信", "QQ群",
    "Copyright", "版权所有", "未经许可", "出版社", "印刷厂", "ISBN",
    "自测题", "参考答案", "拓展阅读", "拓展习题", "模拟试卷", "教学课件",
    "扫码", "视频讲解", "PPT电子教案", "版权声明",
    # —— 数字教材前言里的「阅读器/终端限制」说明（实测抽到「硬件限制」）——
    "硬件限制", "手机端", "手机阅读", "无法在手机", "请按提示", "电脑访问",
    "浏览器", "最佳阅读", "推荐使用", "阅读进度", "书签功能", "字体大小",
)


#: **泛化元词** —— 不是知识点本身，而是「讲述知识点的套路」。
#: 实测抓到：把线性表合并算法的具体步骤归纳成「算法描述」。
#: 这类词做知识点毫无复习价值。
_GENERIC_META_TERMS = frozenset({
    "算法描述", "算法步骤", "算法思想", "解题思路", "解题步骤", "分析过程",
    "详细说明", "具体步骤", "实现方法", "实现步骤", "过程描述", "步骤如下",
    "本章小结", "本章小结", "知识梳理", "内容概述", "问题分析", "案例分析",
    "算法分析", "算法实现", "方法说明", "结论", "总结", "概述", "简介",
})


def name_is_generic(name: str) -> bool:
    """名称是否泛化元词（讲述套路而非知识本身）。"""
    n = re.sub(r"[\s\W_]+", "", (name or "").lower())
    if not n:
        return True
    if n in _GENERIC_META_TERMS:
        return True
    # 「XX算法描述」「XX的具体步骤」这类后缀也算泛化
    for suffix in ("算法描述", "算法步骤", "算法思想", "具体步骤", "实现步骤",
                   "步骤如下", "详细说明"):
        if n.endswith(suffix):
            return True
    return False


def is_boilerplate(*texts: str) -> bool:
    """是否命中宣传/版权页噪声（名称或释义里出现即拦）。"""
    for t in texts:
        if not t:
            continue
        low = t.lower()
        for pat in _BOILERPLATE_PATTERNS:
            if pat.lower() in low:
                return True
    return False


def normalize_name_key(name: str) -> str:
    """去重键：去空白与标点、转小写。"""
    return re.sub(r"[\s\W_]+", "", (name or "").lower())


def _bigrams(s: str) -> Set[str]:
    """字符二元组集合 —— 用于「释义高度重叠」的近似去重。"""
    t = re.sub(r"[\s\W_]+", "", (s or "").lower())
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def jaccard(a: Set[str], b: Set[str]) -> float:
    """Jaccard 相似度（两个空集视为不相似）。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / float(len(a) + len(b) - inter)


def is_near_duplicate(name: str, desc: str, seen_names: Dict[str, str],
                      seen_grams: List[Set[str]], *, sim_thresh: float = 0.82,
                      name_prefix_thresh: int = 6) -> bool:
    """近似重复判定（比纯名称去重更严）。

    实测踩到的坑：同一段正文里模型会吐出两条名字完全一样的知识点，
    甚至「脉冲整形」+「脉冲波形的产生和整形」这种**名字不同但释义几乎相同**的。
    光比名称抓不住后者，所以再加两层：
      1. 名称前缀包含（`脉冲整形` vs `脉冲波形的产生…` 共享 4 字前缀）
      2. 释义二元组 Jaccard 相似度

    Args:
        seen_names: 已入库名称（归一键 → 原名）。
        seen_grams: 已入库释义的二元组集合。
    """
    key = normalize_name_key(name)
    if key and key in seen_names:
        return True
    # 1) 名称前缀包含（限长度，避免「数」这类单字误伤）
    if len(key) >= name_prefix_thresh:
        for other in seen_names:
            if abs(len(other) - len(key)) <= 12 and (
                    other.startswith(key) or key.startswith(other)):
                return True
    # 2) 释义近似重复
    g = _bigrams(desc)
    if g:
        for prev in seen_grams:
            if jaccard(g, prev) >= sim_thresh:
                return True
    return False


# --------------------------------------------------------------------------- #
# 学科双路判定
# --------------------------------------------------------------------------- #
def _core_subjects() -> Tuple[str, ...]:
    """6 个细分学科（延迟导入，避免模块加载期依赖 database 初始化）。"""
    try:
        from services.taxonomy import CORE_SUBJECTS

        return tuple(CORE_SUBJECTS)
    except Exception:  # noqa: BLE001
        return ("数字电子技术", "模拟电子技术", "数学", "英语", "政治", "真题综合")


def _keyword_subject(file_name: str, chunk_text: str,
                     doc_subject: str = "") -> Tuple[str, bool]:
    """关键词推断路：文件名 + 块正文 → (学科, 高置信)。"""
    try:
        from services.kb_service import classify_subject_confidence

        subj, confident = classify_subject_confidence(
            file_name, chunk_text or "")
        return subj, bool(confident)
    except Exception:  # noqa: BLE001
        return (doc_subject or ""), False


#: **压平标签黑名单** —— 这些是"数模电/公共课"式的合并标签，绝不能落库。
#:
#: 为什么要单独拦：`taxonomy.normalize_subject` 的别名/模糊匹配是**子串**规则，
#: `"模电" in "数模电"` 成立 → `"数模电"` 会被静默归一成 `模拟电子技术`。
#: 一旦入库，数字电子技术的知识点就被挂到模拟电子技术名下，整条匹配链路错位。
#: 所以模型给出这类标签时**不猜**，直接判为非法，交由关键词路/兜底决定。
_FLATTENED_LABELS = frozenset({
    "数模电", "数电模电", "模电数电", "电类", "电子类", "电子技术",
    "公共课", "公共基础课", "统考", "全部", "综合", "其他", "其它",
})


def _model_subject(raw: str) -> str:
    """模型判定路：把模型给的科目名归一到细分学科；不合法返回空串。"""
    from services.taxonomy import normalize_subject

    s = (raw or "").strip()
    if not s:
        return ""
    if s in _FLATTENED_LABELS:
        return ""      # 压平标签 → 判非法，不走 normalize（防子串误归一）
    std = normalize_subject(s)
    return std if std in _core_subjects() else ""


#: 「无意义学科」—— 这些不是真学科，不能触发文档学科锁。
#: `其他` 在 `ALL_SUBJECTS` 里（枚举兜底值），若当学科用会导致
#: 文档学科=其他 时把知识点全锁成「其他」（实测踩到）。
_VACUOUS_SUBJECTS = frozenset({"其他", "其它", "未知", "未分类", "综合", "none", "null"})

#: 文档学科锁白名单 —— **叶子级真学科**，独立于 `ALL_SUBJECTS`。
#: 原因：`ALL_SUBJECTS` 混入了 408 的二级学科（数据结构/操作系统/计算机网络/
#: 软件工程）和一级学科名，同层级值会互相污染文档归属（一篇 408 真题 PDF
#: 被标成「数据结构」而不是「408」）。详见 services/doc_lock_subjects.py。
def _doc_lock_allowlist() -> FrozenSet[str]:
    """加载文档学科锁白名单（独立模块，便于其他服务复用与单测）。"""
    try:
        from services.doc_lock_subjects import DOC_LOCK_ALLOWLIST as _ALLOW

        return _ALLOW
    except Exception:  # noqa: BLE001
        return frozenset()


#: 文档学科锁白名单（模块级常量，加载后不再变化）。
DOC_LOCK_ALLOWLIST: FrozenSet[str] = _doc_lock_allowlist()


def _is_known_subject(name: str) -> bool:
    """是否是可作为**文档归属标签**的叶子级真学科。

    与 `ALL_SUBJECTS` 的区别：后者是「知识点可挂载标签」全集，含 408 二级学科
    （数据结构/操作系统/计算机网络/软件工程）与一级学科名，不能直接用作文档锁。

    排除「其他/未知/未分类」这类枚举兜底值 —— 它们不是学科。
    """
    n = (name or "").strip()
    if not n or n.lower() in _VACUOUS_SUBJECTS:
        return False
    return n in DOC_LOCK_ALLOWLIST


def resolve_subject(model_subject: str, kw_subject: str,
                    kw_confident: bool, doc_subject: str) -> Tuple[str, str]:
    """合并双路判定结果 → `(最终学科, 判定来源留痕)`。

    规则（不一致时以模型为准，但要留痕）：
      * 模型给出合法细分学科 → 采用模型；关键词不同则 `model_over_keyword`
      * 模型未给/非法，关键词高置信 → 采用关键词，`keyword`
      * 都不行 → 回退文档学科，再不行 `真题综合`，标 `fallback`

    ⚠️ **文档学科优先锁**：若文档自身学科是已知的**非 CORE** 科目
    （408 / 电路 / 信号与系统 / 光学 / 通信原理…），则以文档学科为准，
    标 `document`。否则会把《数据结构》这种 408 教材的知识点强行挂到
    `数字电子技术` 名下（实测：串/数组/广义表/排序算法全被标成数电）——
    这正是「压平成数模电」的变体，比压平更隐蔽，因为它看着合规。
    """
    cores = _core_subjects()
    m = _model_subject(model_subject)
    k = kw_subject if kw_subject in cores else ""

    # 0) 文档学科锁：已知非 CORE 科目，直接采信文档学科
    ds = (doc_subject or "").strip()
    if ds and ds not in cores and _is_known_subject(ds):
        return ds, "document"

    if m and k and m != k:
        return m, "model_over_keyword"
    if m:
        return m, "model"
    if k and kw_confident:
        return k, "keyword"
    fallback = doc_subject if doc_subject in cores else (m or k or "真题综合")
    return fallback, "fallback"


# --------------------------------------------------------------------------- #
# 模型调用（本地 Ollama，OpenAI 兼容）
# --------------------------------------------------------------------------- #
def _build_opener() -> "urllib.request.OpenerDirector":
    """构造**不走代理**的 opener。

    本机Ollama 在 127.0.0.1:11434，但很多环境（含本项目开发沙箱）设置了
    `http_proxy` / `HTTP_PROXY`；`urllib` 默认会读这些变量并把**本机**请求
    也塞进代理，导致本地模型调用超时或返回空。必须显式 `ProxyHandler({})` 绕过。
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


#: 复用无代理 opener（线程安全）
_OPENER = _build_opener()


def _chat_local(messages: Sequence[Dict[str, str]], *, timeout: float,
                temperature: float = 0.2) -> str:
    """同步调用本地模型，返回文本。

    走 `urllib` 而不是 `services.ai_service.AIService`（后者是 async）——
    本模块在 ingest worker 的线程池里跑，需要同步语义；模型路由已由
    `KP_MODEL` 显式指定（默认 `kaoyan-assistant`，与 AIService 的本地兜底一致）。
    """
    payload = {
        "model": KP_MODEL,
        "messages": list(messages),
        "temperature": temperature,
        "stream": False,
        "options": {"num_ctx": 8192},
    }
    req = urllib.request.Request(
        f"{_OLLAMA_HOST}/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with _OPENER.open(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.S)


def _parse_json_array(text: str) -> List[Dict[str, Any]]:
    """从模型输出里抠出 JSON 数组（容忍 ```json 包裹与前后废话）。"""
    if not text:
        return []
    t = text.strip()
    if "```" in t:
        parts = t.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("["):
                t = p
                break
    m = _JSON_ARRAY_RE.search(t)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def _build_prompt(chunk_text: str, heading: str, file_name: str) -> str:
    """在既有 `KNOWLEDGE_POINT_PROMPT` 上追加硬约束，不改动原文。"""
    from services.document_analyzer import KNOWLEDGE_POINT_PROMPT

    cores = "、".join(_core_subjects())
    base = KNOWLEDGE_POINT_PROMPT.format(content=(chunk_text or "")[:KP_CHUNK_CHARS])
    return (
        f"{base}\n"
        f"【本次抽取的硬性约束】（优先于上文的一般性要求）\n"
        f"- subject 字段**必须**是以下之一，不得新造、不得压平：{cores}\n"
        f"- description 必须是真正解释「它是什么/为什么/怎么用」的实质释义，"
        f"不少于 30 个汉字；**禁止**只把 name 重复一遍\n"
        f"- name 是可独立复习的知识点术语，不要写成章节标题或「第X章」\n"
        f"- **只抽学科知识**。教材前言/数字课程说明/版权页/二维码/阅读器提示"
        f"（如「数字课程资源」「课程有效期」「自测题和参考答案」「硬件限制」）"
        f"一律不算知识点；宁可少抽也不要抽这些\n"
        f"- 若该片段没有可抽的知识点，返回 []\n"
        f"【本段上下文】文件名：{file_name or '未知'}；小节标题：{heading or '无'}\n"
    )


def _extract_from_chunk(chunk: Dict[str, Any], *, file_name: str,
                        doc_subject: str, doc_chapter: str,
                        doc_id: Optional[int],
                        chunk_row_id: Optional[int]) -> Dict[str, Any]:
    """对单个 chunk 调模型并做质量门禁。

    Returns: `{items, dropped, failed, error}`；`items` 已过门禁但**未**去重
    （去重需要跨 chunk 的全局视角，由调用方做）。
    """
    stat = {"items": [], "dropped": 0, "failed": 0, "error": ""}
    text = chunk.get("text") or ""
    heading = chunk.get("heading") or ""
    if len(text.strip()) < 120:
        # 太短的块不值得惊动模型
        stat["dropped"] += 1
        return stat

    messages = [
        {"role": "system", "content": "你是考研知识提取专家，只返回JSON数组，不要解释。"},
        {"role": "user", "content": _build_prompt(text, heading, file_name)},
    ]
    try:
        with _MODEL_SEM:
            raw = _chat_local(messages, timeout=KP_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        stat["failed"] = 1
        stat["error"] = f"{type(e).__name__}: {e}"[:200]
        return stat

    raw_items = _parse_json_array(raw)
    if not raw_items:
        stat["dropped"] += 1
        return stat

    kw_subject, kw_confident = _keyword_subject(file_name, text[:2000], doc_subject)
    for d in raw_items[:KP_MAX_PER_DOC]:
        name = (d.get("name") or "").strip()
        desc = (d.get("description") or "").strip()
        chapter_raw = str(d.get("chapter") or "").strip() or heading

        # ---- 质量门禁 ----
        if is_noise_name(name):
            stat["dropped"] += 1
            continue
        if name_is_generic(name):
            stat["dropped"] += 1
            continue
        if name_is_title_only(name, heading):
            stat["dropped"] += 1
            continue
        if not desc_is_substantive(desc, name):
            stat["dropped"] += 1
            continue
        #宣传/版权页噪声（教材前言、数字课程说明）
        if is_boilerplate(name, desc, chapter_raw):
            stat["dropped"] += 1
            continue

        subject, subject_source = resolve_subject(
            d.get("subject") or "", kw_subject, kw_confident, doc_subject)
        try:
            freq = int(d.get("exam_frequency", 3))
        except (TypeError, ValueError):
            freq = 3

        # 章节兜底链：模型给的章 → 块标题 → 文档级章节（逐级过天书门禁）
        chapter = sanitize_chapter(chapter_raw, doc_chapter)
        stat["items"].append({
            "name": name[:300],
            "description": desc[:2000],
            "subject": subject,
            "subject_source": subject_source,
            "chapter": chapter,
            "exam_frequency": min(5, max(1, freq)),
            "document_id": doc_id,
            "source_chunk_id": chunk_row_id,
            "source_chunk_index": chunk.get("index"),
            "extract_source": "smart_ingest",
        })
    return stat


# --------------------------------------------------------------------------- #
# 溯源列（幂等迁移）
# --------------------------------------------------------------------------- #
def ensure_kp_trace_columns(db) -> List[str]:
    """给 `knowledge_points` 补齐溯源/留痕列，返回本次新增的列名。

    幂等：已存在则跳过。用 `ALTER TABLE ADD COLUMN`，不动已有数据与索引。

    实现注意：**不能只依赖 inspector 缓存** —— inspector 会缓存 schema，
    同一进程内第二次调用仍会看到「列不存在」而重复 ALTER（报 duplicate column）。
    因此以「执行成功」为准，duplicate column 视为已存在。
    """
    added: List[str] = []
    try:
        inspector_cols = {
            c["name"] for c in sqlalchemy.inspect(db).get_columns(
                "knowledge_points")
        }
    except Exception:  # noqa: BLE001
        inspector_cols = set()
    for col, ddl in KP_TRACE_COLUMNS:
        if col in inspector_cols:
            continue
        try:
            db.execute(sqlalchemy.text(ddl))
            added.append(col)
        except Exception as e:  # noqa: BLE001
            # 任何异常都先回滚，否则 PG 事务进入 aborted 态会拖累后续 SELECT
            # （InFailedSqlTransaction），导致溯源/去重整体失效。
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            # 列已存在 = 幂等成功，不算失败（PG 报 duplicate column；
            # 老版本 SQLite 无 IF NOT EXISTS 时也会报 already exists）。
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                continue
            logger.warning("knowledge_points 加列 %s 失败: %s", col, e)
    if added:
        try:
            db.commit()
            logger.info("knowledge_points 新增溯源列: %s", ", ".join(added))
        except Exception:  # noqa: BLE001
            db.rollback()
    return added


# --------------------------------------------------------------------------- #
# 主管线
# --------------------------------------------------------------------------- #
def _norm_for_match(s: str) -> str:
    """溯源匹配用的归一化：去掉所有非字母数字/汉字的字符。"""
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


def _map_chunks_to_rows(db, doc_id: int,
                        chunks: Sequence[Dict[str, Any]]) -> Dict[int, int]:
    """把分析块映射到 `knowledge_chunks` 行 id（按内容匹配，非下标）。

    `smart_chunk_text` 与 `kb_service.chunk_text` 是两套分段，直接按下标对齐会
    指到无关原文。这里对每块取**最长的一段实义文本**（>=40 字）作为指纹，
    在该文档的 chunk 行里找包含该指纹的行。

    Returns:
        `{chunk_index: chunk_row_id}`；匹配不上的块不出现在字典里（降级为 None）。
    """
    out_map: Dict[int, int] = {}
    try:
        rows = db.execute(
            sql_text("SELECT id, text FROM knowledge_chunks "
                     "WHERE document_id=:d ORDER BY id"),
            {"d": doc_id}).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 knowledge_chunks 失败（溯源降级为仅 chunk_index）: %s", e)
        return out_map
    if not rows:
        return out_map

    # 预先归一化所有行文本，避免 O(块数×行数) 重复正则
    norm_rows = [(rid, _norm_for_match(txt or "")) for rid, txt in rows]
    for ch in chunks:
        body = _norm_for_match(ch.get("text") or "")
        if len(body) < 40:
            continue
        # 取中段120 字作指纹（避开块首尾的章节标题与重叠区）
        mid = len(body) // 2
        fingerprint = body[max(0, mid - 60): mid + 60]
        if len(fingerprint) < 40:
            fingerprint = body[:120]
        for rid, ntext in norm_rows:
            if fingerprint and fingerprint in ntext:
                out_map[int(ch.get("index", -1))] = rid
                break
    if chunks:
        hit = sum(1 for c in chunks if int(c.get("index", -1)) in out_map)
        logger.info("溯源映射: %d/%d 块命中 knowledge_chunks 行",
                    hit, len(chunks))
    return out_map


def extract_kps_for_document(
    db,
    *,
    doc_id: int,
    text: str,
    file_name: str,
    doc_subject: str = "",
    chapter: str = "",
    concurrency: Optional[int] = None,
    max_per_doc: Optional[int] = None,
    min_doc_chars: Optional[int] = None,
    max_chunks: Optional[int] = None,
    extra_existing_names: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """对一篇**已入库**文档的正文抽知识点并落库（并发 + 质量门禁 + 溯源）。

    这是 `smart_ingest_file` 调用的钩子，也被 `scripts/verify_kp_ingest` 复用。

    Args:
        db: SQLAlchemy Session（调用方负责其生命周期）。
        doc_id: 已入库的 document.id —— 写入 `knowledge_points.document_id` 溯源。
        text: 文档清洗后的正文。
        file_name: 用于学科关键词判定与提示词上下文。
        doc_subject: 管线已判定的文档学科，作为学科回退与兜底。
        chapter: 文档级章节，作为知识点 chapter 的兜底。
        concurrency: chunk 级并发度，默认 `KP_CONCURRENCY`。
        max_per_doc: 单文档知识点上限，默认 `KP_MAX_PER_DOC`。
        min_doc_chars: 正文长度门槛，默认 `KP_MIN_DOC_CHARS`。
        max_chunks: 本次最多抽多少块，默认 `KP_MAX_CHUNKS_PER_DOC`（封顶模型负载）。
        extra_existing_names: 额外的去重名集合（例如全库已有知识点）。

    Returns:
        `{enabled, skipped, reason, chunks, extracted, kept, dropped, failed,
          errors, subject_mix, seconds, sample}`
    """
    t0 = time.time()
    out: Dict[str, Any] = {
        "enabled": KP_EXTRACT_ENABLED, "skipped": False, "reason": "",
        "chunks": 0, "chunks_total": 0,
        "extracted": 0, "kept": 0, "dropped": 0, "failed": 0,
        "errors": [], "subject_mix": {}, "seconds": 0.0, "sample": [],
    }
    if not KP_EXTRACT_ENABLED:
        out["skipped"], out["reason"] = True, "SMART_INGEST_KP=0 已关闭"
        return out

    floor = KP_MIN_DOC_CHARS if min_doc_chars is None else min_doc_chars
    body = (text or "").strip()
    if len(body) < floor:
        out["skipped"] = True
        out["reason"] = f"正文过短({len(body)}字 < {floor})，跳过抽取"
        return out

    try:
        from services.document_analyzer import smart_chunk_text
    except Exception as e:  # noqa: BLE001
        out["skipped"], out["reason"] = True, f"分块模块不可用: {e}"
        return out

    chunks = smart_chunk_text(body, max_chunk_size=3000, overlap=200)
    # 均匀取样而非只取头部：头部往往是目录/定义，长文里中后段更有知识点价值。
    chunk_cap = KP_MAX_CHUNKS_PER_DOC if max_chunks is None else max_chunks
    total_chunks = len(chunks)
    if chunk_cap and total_chunks > chunk_cap:
        step = total_chunks / float(chunk_cap)
        chunks = [chunks[int(i * step)] for i in range(chunk_cap)]
    out["chunks"] = len(chunks)
    out["chunks_total"] = total_chunks
    if not chunks:
        out["skipped"], out["reason"] = True, "分块结果为空"
        return out

    # ---- 溯源列（幂等） ----
    ensure_kp_trace_columns(db)

    # ---- 建立「分析块 → knowledge_chunks 行」的映射 ----
    #⚠️ 不能按下标对齐：`smart_chunk_text`（按章节标题切，3000字）与
    # `kb_service.chunk_text`（按段落切，600字）是**两套不同的分段**，
    # 下标第 i 个根本不对应。必须按**文本内容**匹配，否则溯源指到无关原文。
    row_ids = _map_chunks_to_rows(db, doc_id, chunks)

    # ---- 去重基准：本库已有 + 本次已抽 ----
    # 名→归一键；已有释义的二元组不预载（全库 3 万+ 释义做 O(n²) 不现实，
    # 跨文档只按名称去重，近似重复只在本文档范围内判定）。
    seen: Dict[str, str] = {}
    try:
        for (nm,) in db.execute(
                sql_text("SELECT name FROM knowledge_points")).fetchall():
            k = normalize_name_key(nm)
            if k:
                seen[k] = nm
    except Exception as e:  # noqa: BLE001
        logger.warning("读取已有知识点名失败（本次仅做文档内去重）: %s", e)
    for nm in (extra_existing_names or ()):
        k = normalize_name_key(nm)
        if k:
            seen.setdefault(k, nm)

    cap = KP_MAX_PER_DOC if max_per_doc is None else max_per_doc
    workers = max(1, (KP_CONCURRENCY if concurrency is None else concurrency))

    # ---- 并发抽 chunk ----
    collected: List[Dict[str, Any]] = []
    per_chunk: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as pool:
        futs = [pool.submit(
            _extract_from_chunk, ch,
            file_name=file_name, doc_subject=doc_subject, doc_chapter=chapter,
            doc_id=doc_id,
            chunk_row_id=row_ids.get(int(ch.get("index", -1))),
        ) for ch in chunks]
        for fu in futs:
            try:
                per_chunk.append(fu.result())
            except Exception as e:  # noqa: BLE001
                per_chunk.append({"items": [], "dropped": 0, "failed": 1,
                                  "error": f"{type(e).__name__}: {e}"[:200]})

    # ---- 汇总 + 跨 chunk 去重（含近似重复）+ 落库 ----
    from models import KnowledgePoint

    created = 0
    kept_grams: List[Set[str]] = []
    for st in per_chunk:
        out["dropped"] += int(st.get("dropped") or 0)
        out["failed"] += int(st.get("failed") or 0)
        if st.get("error"):
            out["errors"].append(st["error"])
        for it in st.get("items") or []:
            if created >= cap:
                out["dropped"] += 1
                continue
            key = normalize_name_key(it["name"])
            if not key:
                out["dropped"] += 1
                continue
            #近似重复：同名 / 名前缀包含 / 释义高度重叠
            if is_near_duplicate(it["name"], it["description"], seen, kept_grams):
                out["dropped"] += 1
                continue
            seen[key] = it["name"]
            kept_grams.append(_bigrams(it["description"]))
            collected.append(it)
            created += 1

    out["extracted"] = sum(len(st.get("items") or []) for st in per_chunk)
    if collected:
        try:
            for it in collected:
                db.add(KnowledgePoint(**it))
            db.commit()
            out["kept"] = len(collected)
            out["sample"] = [
                {"name": it["name"][:40], "subject": it["subject"],
                 "subject_source": it["subject_source"],
                 "chapter": it["chapter"][:40]}
                for it in collected[:5]
            ]
            for it in collected:
                out["subject_mix"][it["subject"]] = \
                    out["subject_mix"].get(it["subject"], 0) + 1
        except Exception as e:  # noqa: BLE001
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            out["failed"] += len(collected)
            out["errors"].append(f"入库失败: {type(e).__name__}: {e}"[:200])

    out["seconds"] = round(time.time() - t0, 1)
    logger.info(
        "KP抽取 doc#%s《%s》块=%d 抽=%d 留=%d 丢弃=%d 失败=%d 学科=%s %.1fs",
        doc_id, (file_name or "")[:40], out["chunks"], out["extracted"],
        out["kept"], out["dropped"], out["failed"], out["subject_mix"],
        out["seconds"])
    return out