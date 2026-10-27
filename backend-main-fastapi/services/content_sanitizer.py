"""全站共享内容清洗服务（题库 / 文档 / 错题本唯一入口）——智能水印识别版。

定位
----
平台数据地基的**单一清洗来源**：题库导入、文档导入、错题归集、展示前都过本模块。

水印识别策略（不写死 vendor 名，三条智能路径 + 自学习词库）
------------------------------------------------------------
1. **结构规律识别**（与内容无关的通用模式）：
   - 联系方式模式：微信号/QQ号/手机号/公众号/URL/邮箱（正则模式，非具体人名）
   - 分页标记：第 N 页 / (OCR) / 共 N 页
   - 引流话术模式：扫码/关注/免费分享/领取/更多…资料 等动词组合
2. **乱码特征识别**：Latin-1 符号区/U+FFFD 聚集且无正常英文词
3. **跨文档高频重复行识别**（核心智能能力）：
   同一条短行（<=30字）在**不同文档**的页眉/页脚位置重复出现 >= N 次，
   且几乎从不出现在题干中部 —— 它是水印的概率极高。由
   ``learn_watermark_lexicon()`` 从语料自动学习，沉淀进
   ``watermark_lexicon`` 表，之后所有清洗自动生效，**零代码改动吸收新水印**。
4. **文档内页眉页脚位置检测**：同一文档内，位于每页首行/末行且跨页重复的行。

设计原则
--------
- 不猜内容：只剥噪声、不做 OCR 字符纠错；任何可能改错正文的操作都不做。
- 幂等可重跑；所有剔除记录 issues 可审计。
- 词库自学习：``learn_watermark_lexicon`` 可定期重跑，越用越准。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "sanitize_text",
    "sanitize_question_fields",
    "normalize_options",
    "extract_inline_options",
    "validate_question",
    "learn_watermark_lexicon",
    "WatermarkHit",
    "get_learned_patterns",
]

# --------------------------------------------------------------------------- #
# 一、结构规律识别（通用模式，不含任何具体机构/人名）
# --------------------------------------------------------------------------- #

#: 联系方式与引流模式（行级命中即剔除）
#: 注意「公众号」必须带冒号或出现在引流动词后 —— 否则会误伤"公众号召力"
#: （"公众/号召力"）这类正常词（实测踩坑）。
_CONTACT_LINE_PATTERNS: Tuple[re.Pattern, ...] = tuple(re.compile(p) for p in (
    r"微\s*信\s*(公众号|号)?\s*[：:]",
    r"公众号\s*[：:]",
    r"公众号\s*$",
    r"扫码关注|扫一扫|扫码领取|扫码添加",
    r"QQ\s*[：:]\s*\d{5,}",
    r"[1][3-9]\d{9}",                      # 手机号
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",  # 邮箱
    r"https?://|www\.",
    r"免费分享|免费领取|免费获取",
    r"更多.{0,6}资料|资料.{0,4}分享",
    r"关注.{0,8}(公众号|即可|获取)",
))

#: 分页/试卷标记
_PAGINATION_PATTERNS: Tuple[re.Pattern, ...] = tuple(re.compile(p) for p in (
    r"^[-—–=*_]{2,}\s*第?\s*\d{1,3}\s*页?\s*\(?OCR\)?\s*[-—–=*_]{2,}$",
    r"^\s*第?\s*\d{1,3}\s*页\s*[（(]?\s*(共\s*\d{1,3}\s*页)?\s*[)）]?\s*(\(OCR\))?\s*$",
    r"^\s*[（(]\s*OCR\s*[)）]\s*$",
    r"^\s*第?\s*\d{1,3}\s*/\s*\d{1,3}\s*$",
))

#: 绝密/启用前等试卷头（通用试卷格式，非机构名）
_EXAM_HEADER_PATTERNS: Tuple[re.Pattern, ...] = tuple(re.compile(p) for p in (
    r"^\s*绝密[★☆●]?\s*启用前\s*$",
    r"^\s*启封前\s*$",
    r"^\s*密封线\s*$",
    r"^\s*考生?\s*不得\s*填涂\s*$",
))

#: 纯数字短行（页码残留）
_PAGE_NUM_ONLY = re.compile(r"^\s*\d{1,3}\s*$")

#: 行内挖除模式（水印与正文同行时挖 fragment，不删整行）
_CONTACT_INLINE_PATTERNS: Tuple[re.Pattern, ...] = tuple(re.compile(p) for p in (
    r"微\s*信\s*(公众号|号)?\s*[：:]?\s*[A-Za-z0-9_\-—－]{3,}",
    r"公众号\s*[：:]\s*\S{2,}",
    r"扫码\S{0,12}",
    r"[1][3-9]\d{9}",
    r"免费(分享|领取|获取)\S{0,10}",
    r"更多.{0,6}资料",
))

# --------------------------------------------------------------------------- #
# 二、乱码 / 控制字符（通用特征）
# --------------------------------------------------------------------------- #

#: 必须排除常见数学/单位符号（×÷±°²³¼½¾µ 等）——它们落在 U+00C0-00FF 区间内，
#: 不排除会把公式行整行误判为乱码删掉（实测：
#: "= 0.7 X(51 + 47×2)×103 ×910 X10-9" 因 3 个 × 被判乱码）。
_MATH_SAFE_CHARS = set("×÷±°²³¹¼½¾µ‰·–—‘’“”…−") 
_MOJIBAKE_CHARS = re.compile(
    "[\ufffd\u00ff\u0160\u0161\u017d\u017e\u0178\u0152\u0153\u00c0-\u00ff]")
_ENGLISH_WORD = re.compile(r"[a-z]{4}")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff\u2060]")
_INLINE_SPACE = re.compile(r"[ \t]{2,}")
_CJK_SPACE = re.compile(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])")


def _mojibake_chars_in(line: str) -> list:
    """行内乱码字符（已剔除数学/单位符号）。"""
    return [c for c in _MOJIBAKE_CHARS.findall(line) if c not in _MATH_SAFE_CHARS]


def _is_garbled_line(line: str) -> bool:
    """乱码行：含 mojibake 字符、无正常英文词、乱码字符 >=3 个。

    数学/单位符号（×÷±°²³ 等）不计入乱码证据 —— 公式行不能因含乘号被删。
    """
    bad = _mojibake_chars_in(line)
    if not bad:
        return False
    if _ENGLISH_WORD.search(line) is not None:
        return False
    return len(bad) >= 3


# --------------------------------------------------------------------------- #
# 三、自学习水印词库（DB 持久化 + 进程缓存）
# --------------------------------------------------------------------------- #

_LEARNED_PATTERNS: List[re.Pattern] = []
#: 行内短片段（词库学到的子串，用于挖除）
_LEARNED_FRAGMENTS: List[str] = []

#: 进程内缓存策略。
#: 成功 —— 词库变动不频繁（人工在后台点"启用"），5 分钟足够及时；
#: 失败 —— **绝不能永久降级**。旧实现在 except 里把空结果连同
#: ``_LEARNED_LOADED=True`` 一起定死：一旦启动那一刻数据库抖动，
#: 整个进程生命周期内学到的水印全部失效，而且**没有任何日志**
#: （项目血泪教训 #1：静默吞异常是最贵的 bug）。这里改成失败走短 TTL
#: 并显式告警，库恢复后自动重新加载。
_LEARNED_OK_TTL = 300.0
_LEARNED_FAIL_TTL = 60.0
_LEARNED_TS = 0.0
_LEARNED_STATE = 0  # 0=从未加载成功 1=正常 2=降级中


def _learned_cache_expired() -> bool:
    if _LEARNED_STATE == 0:
        return True
    ttl = _LEARNED_OK_TTL if _LEARNED_STATE == 1 else _LEARNED_FAIL_TTL
    return (time.time() - _LEARNED_TS) >= ttl


def get_learned_patterns() -> Tuple[List[re.Pattern], List[str]]:
    """加载自学习词库（进程内带 TTL 缓存）。返回 (整行模式列表, 行内片段列表)。

    调用极其频繁（清洗时**每行一次**），所以缓存必须既便宜又可靠：
    命中时零开销；失败时降级但**留痕**，并在 TTL 后重试，而不是一次
    失败就锁死到进程结束。
    """
    global _LEARNED_PATTERNS, _LEARNED_FRAGMENTS
    global _LEARNED_STATE, _LEARNED_TS

    if not _learned_cache_expired():
        return _LEARNED_PATTERNS, _LEARNED_FRAGMENTS

    logger = logging.getLogger(__name__)
    try:
        from database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            rows = db.execute(text(
                "SELECT phrase FROM watermark_lexicon WHERE enabled = TRUE"
            )).fetchall()
        finally:
            db.close()
        pats: List[re.Pattern] = []
        frags: List[str] = []
        for (phrase,) in rows:
            p = (phrase or "").strip()
            if not p:
                continue
            frags.append(p)
            # 含正则元字符的按原样编译，普通文本转义
            pats.append(re.compile(p if any(c in p for c in r"\[]()*+?{}|^$")
                                   else re.escape(p)))
        _LEARNED_PATTERNS = pats
        _LEARNED_FRAGMENTS = frags
        _LEARNED_STATE, _LEARNED_TS = 1, time.time()
        return _LEARNED_PATTERNS, _LEARNED_FRAGMENTS
    except Exception as exc:  # noqa: BLE001
        # 词库表不存在 / 数据库掉线：降级为内置规则，但必须告警 + 允许重试
        _LEARNED_PATTERNS, _LEARNED_FRAGMENTS = [], []
        if _LEARNED_STATE != 2:
            logger.warning(
                "自学习水印词库加载失败，降级为内置规则（%ss 后重试）：%s",
                int(_LEARNED_FAIL_TTL), str(exc)[:200],
            )
        _LEARNED_STATE, _LEARNED_TS = 2, time.time()
        return _LEARNED_PATTERNS, _LEARNED_FRAGMENTS


def invalidate_learned_cache() -> None:
    """词库更新后调用，强制下次重新加载。"""
    global _LEARNED_STATE, _LEARNED_TS
    _LEARNED_STATE, _LEARNED_TS = 0, 0.0


# --------------------------------------------------------------------------- #
# 四、核心清洗
# --------------------------------------------------------------------------- #

class WatermarkHit:
    """一次水印命中记录（可审计）。"""

    __slots__ = ("kind", "pattern", "line")

    def __init__(self, kind: str, pattern: str, line: str) -> None:
        self.kind = kind        # line / inline / learned
        self.pattern = pattern
        self.line = line[:80]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WatermarkHit {self.kind} {self.pattern} {self.line!r}>"


def _strip_contact_inline(s: str) -> str:
    """挖掉行内的联系方式/引流片段，返回残留（用于判定是否整行丢弃）。

    同时剥离**行级模式**的匹配片段：否则"公众号：考研君"这类没有对应行内
    模式的串会原样保留，导致残留长度 >= 6 而整行被误保留（实测踩坑）。
    只剥离水印后残留的分隔符与空白，**保留句末标点**（。？！是正文内容）。
    """
    for p in _CONTACT_INLINE_PATTERNS:
        s = p.sub("", s)
    for p in _CONTACT_LINE_PATTERNS:
        s = p.sub("", s)
    return s.strip(" \t，,;；、-—|·　")


def _hit_line(s: str, hits: Optional[List[WatermarkHit]],
              drop_standalone_numbers: bool = True) -> bool:
    """整行命中"确定性剔除"规则 -> True。

    ``drop_standalone_numbers``：是否剔除"纯 1~3 位数字"行（页码残留）。
    文档域**必须按上下文决定**——数学/电路文档里独立的数字行可能是公式值或
    表格数据，无脑删会伤数据；只有在该文档确实带页标记（``(OCR)``/``第N页``）
    时才判定为页码。题库字段默认 True（题干里独立数字行基本是噪声）。

    注意：联系方式/引流模式**不在此判定整行丢弃**——正文可能带水印尾巴
    （如"施密特触发器有两个稳定状态。微信：abc12345"）。这种情况由调用方
    用 ``_strip_contact_inline`` 计算残留：残留足够长则只挖片段、保留正文；
    残留近乎空才删整行。
    """
    for p in _PAGINATION_PATTERNS:
        if p.search(s):
            if hits is not None:
                hits.append(WatermarkHit("line", p.pattern, s))
            return True
    for p in _EXAM_HEADER_PATTERNS:
        if p.search(s):
            if hits is not None:
                hits.append(WatermarkHit("line", p.pattern, s))
            return True
    if drop_standalone_numbers and _PAGE_NUM_ONLY.match(s):
        if hits is not None:
            hits.append(WatermarkHit("line", "page_num", s))
        return True
    if _is_garbled_line(s):
        if hits is not None:
            hits.append(WatermarkHit("line", "mojibake", s))
        return True
    learned, _frags = get_learned_patterns()
    for p in learned:
        if p.search(s):
            if hits is not None:
                hits.append(WatermarkHit("learned", p.pattern, s))
            return True
    return False


#: 页标记特征（用于判定"纯数字行"是否真的是页码）
_PAGE_MARKER_RE = re.compile(r"\(OCR\)|（OCR）|第\s*\d{1,3}\s*页|共\s*\d{1,3}\s*页")


def document_has_page_markers(text: Optional[str]) -> bool:
    """文档是否带 OCR 页标记——决定"纯数字行"能否按页码剔除。

    实测（2026-10-15）：无脑删纯数字行会让文档丢 ~2.7% 字符，
    其中含电路/数学文档里本是公式值或表格数据的独立数字行。
    仅当文档确有页标记时，独立数字行才按页码噪声处理。
    """
    if not text:
        return False
    return len(_PAGE_MARKER_RE.findall(text)) >= 2


def sanitize_text(raw: Optional[str], *, hits: Optional[List[WatermarkHit]] = None,
                  collapse_blank: bool = True,
                  drop_standalone_numbers: bool = True) -> str:
    """清洗任意文本（题干/解析/文档正文/错题内容）。

    控制字符 -> 零宽 -> 行级剔除（结构规律+乱码+自学习词库）
    -> 行内挖除（联系方式碎片+自学习片段）-> U+FFFD 删除 -> 空白规整。

    ``drop_standalone_numbers``：文档域请传 ``document_has_page_markers(text)``，
    避免把数学/电路文档里本是数据的独立数字行当页码删掉。
    """
    if not raw:
        return ""
    text = _CTRL.sub("", str(raw))
    text = _ZERO_WIDTH.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    _pats, learned_frags = get_learned_patterns()

    out_lines: List[str] = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            out_lines.append("")
            continue
        if _hit_line(s, hits, drop_standalone_numbers):
            continue
        # 联系方式 / 引流：先算挖掉片段后的残留
        if any(p.search(s) for p in _CONTACT_LINE_PATTERNS):
            residue = _strip_contact_inline(s)
            if hits is not None:
                hits.append(WatermarkHit("line", "contact", s))
            if len(residue) < 6:
                continue  # 整行几乎就是水印
            s = residue  # 保留正文，只挖掉水印片段
        # 行内挖除：联系方式碎片
        for p in _CONTACT_INLINE_PATTERNS:
            new_s, n = p.subn("", s)
            if n and hits is not None:
                hits.append(WatermarkHit("inline", p.pattern, s))
            s = new_s.strip()
        # 行内挖除：自学习片段
        for frag in learned_frags:
            if frag in s:
                s = s.replace(frag, "").strip()
                if hits is not None:
                    hits.append(WatermarkHit("learned", frag[:24], s))
        if not s:
            continue
        s = _INLINE_SPACE.sub(" ", s)
        out_lines.append(s)

    text = "\n".join(out_lines)
    text = text.replace("\ufffd", "")
    text = _CJK_SPACE.sub(r"\1\2", text)
    if collapse_blank:
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# 五、选项结构规整
# --------------------------------------------------------------------------- #

_OPT_KEY_RE = re.compile(r"^\s*[\[（(]?\s*([A-H])\s*[\]）)]?\s*[.、．:：]?\s*")
#: 选项键定位（只匹配键本身，正文由切片取得，避免贪婪吞行）。
#: 键可起始于行首/换行/空白之后（OCR 常把 ABCD 压在一行）。
_OPT_KEY_AT = re.compile(
    r"(?:^|\n|(?<=\s)|(?<=[。？！；：）】」》\])]))"
    r"[\[（(]?\s*([A-H])\s*[\]）)]?\s*[.、．:：]\s*")
#: 宽松键定位（无分隔符：OCR 写成"A斯密特 B单稳态"）。
#: 证据要求严格：必须凑齐从 A 起连续 >=3 个键才采用（见 _extract_loose_options），
#: 避免把 "A4纸"/"D55" 之类误当选项。
_OPT_KEY_LOOSE = re.compile(
    r"(?:^|\s|[（(])([A-H])\s*(?=[\u4e00-\u9fff]|\d{1,3}\s*[\u4e00-\u9fff])")


def _extract_loose_options(content: str) -> Tuple[str, List[Dict[str, str]]]:
    """无分隔符选项抽取（严格证据）：须从 A 起连续 >=3 键才认。"""
    keys = list(_OPT_KEY_LOOSE.finditer(content))
    if len(keys) < 3:
        return content, []
    letters = [m.group(1) for m in keys]
    # 找最长的从 A 开始的连续序列
    try:
        start = letters.index("A")
    except ValueError:
        return content, []
    run = ["A"]
    for ch in letters[start + 1:]:
        if ord(ch) == ord(run[-1]) + 1:
            run.append(ch)
        else:
            break
    if len(run) < 3:
        return content, []
    seq = keys[start:start + len(run)]
    stem = content[:seq[0].start()].strip()
    if len(stem) > _MAX_EXTRACT_STEM:
        return content, []
    opts: List[str] = []
    for i, m in enumerate(seq):
        body_start = m.end()
        body_end = seq[i + 1].start() if i + 1 < len(seq) else len(content)
        body = content[body_start:body_end].split("\n", 1)[0]
        body = re.sub(r"\s+", " ", body).strip(" 、．,，")
        if body:
            opts.append(body)
    if len(opts) < 3 or any(len(o) > _MAX_OPTION_TEXT for o in opts):
        return content, []
    out = [{"key": chr(ord("A") + i), "text": t} for i, t in enumerate(opts)]
    return stem, out


def _clean_option_text(s: str) -> str:
    """选项文本专用清洗：只做字符级净化，**绝不整行丢弃**。

    选项常是极短片段（"3"、"4"、"-1"、"a"），走通用 sanitize_text 会被
    页码规则（纯 1~3 位数字）或其它行级规则整行删掉 —— 实测把
    `["3","4","5","6"]` 洗成空数组，题目选项直接丢失。
    """
    if not s:
        return ""
    t = _CTRL.sub("", str(s))
    t = _ZERO_WIDTH.sub("", t)
    t = t.replace("\ufffd", "")
    for p in _CONTACT_INLINE_PATTERNS:
        t = p.sub("", t)
    t = _INLINE_SPACE.sub(" ", t)
    return t.strip()


def normalize_options(options: Any) -> Tuple[List[Dict[str, str]], List[str]]:
    """把任意形态 options 规整为 [{key,text}]（对齐 DB is_canonical_options）。"""
    issues: List[str] = []
    items: List[str] = []

    if options is None:
        return [], ["options_missing"]
    if isinstance(options, str):
        parts = re.split(r"[\n;；]+", options)
        items = [p for p in (x.strip() for x in parts) if p]
    elif isinstance(options, (list, tuple)):
        for o in options:
            if isinstance(o, str):
                t = o.strip()
                if t:
                    items.append(t)
            elif isinstance(o, dict):
                t = str(o.get("text") or o.get("content") or "").strip()
                k = str(o.get("key") or "").strip().upper()[:1]
                if t:
                    items.append(f"{k}.{t}" if k else t)
    else:
        return [], ["options_bad_type"]

    if not items:
        return [], ["options_empty"]

    cleaned: List[str] = []
    for it in items:
        s = _clean_option_text(it)
        if not s:
            continue
        m = _OPT_KEY_RE.match(s)
        if m:
            s = s[m.end():].strip()
        if s:
            cleaned.append(s)
    if len(cleaned) < 2:
        return [], [f"options_too_few({len(cleaned)})"]

    # 去重（OCR 重复行）保持顺序；但 DB 约束要求 >=2 选项，
    # 若去重后不足 2（全是重复项）则保留原样并标记，交给校验门/复核处理。
    seen = set()
    uniq: List[str] = []
    for c in cleaned:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    if len(uniq) < 2:
        issues.append("options_all_duplicate")
        uniq = cleaned
    cleaned = uniq

    out = [{"key": chr(ord("A") + i), "text": c} for i, c in enumerate(cleaned)]
    if len(out) > 4:
        issues.append(f"options_many({len(out)})")
    return out, issues


#: 选项抽取护栏（防"整页大题块"被误拆成选项）：真选项正文很短；
#: 超长必是大题块/多题粘连，放弃抽取，交由复核处理。
_MAX_OPTION_TEXT = 120
_MAX_EXTRACT_STEM = 400


def extract_inline_options(content: str) -> Tuple[str, List[Dict[str, str]]]:
    """从题干抽取内联选项（"A. xx B. xx"），返回 (题干, 选项)；不足 2 个不抽。

    实现：先用 ``_OPT_KEY_AT`` 定位所有键，再取相邻键之间的切片为选项正文，
    避免 "A. xx B. xx" 同行时首选项 ``[^\\n]+`` 贪婪吞掉整行导致后续键漏配。
    """
    if not content:
        return content or "", []
    keys = list(_OPT_KEY_AT.finditer(content))
    if len(keys) < 2:
        return content, []
    stem = content[:keys[0].start()].strip()
    if len(stem) > 400:
        return content, []  # 题干超长 = 大题块/多题粘连，放弃抽取
    opts: List[str] = []
    for i, m in enumerate(keys):
        body_start = m.end()
        body_end = keys[i + 1].start() if i + 1 < len(keys) else len(content)
        body = content[body_start:body_end]
        # 选项正文到行尾为止（下一行可能是题干补充或其他内容）
        body = body.split("\n", 1)[0]
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            opts.append(body)
    if len(opts) < 2:
        return content, []
    # 长度护栏：真选项正文很短；超长必是大题块/多题粘连误拆，放弃
    if any(len(o) > 120 for o in opts):
        return content, []
    out = [{"key": chr(ord("A") + i), "text": t} for i, t in enumerate(opts)]
    return stem, out


# --------------------------------------------------------------------------- #
# 六、题目级清洗 + 校验门
# --------------------------------------------------------------------------- #

def sanitize_question_fields(fields: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """清洗一道题（content/options/answer/analysis/rubric）。返回 (副本, issues)。"""
    issues: List[str] = []
    hits: List[WatermarkHit] = []
    out = dict(fields)

    content = sanitize_text(fields.get("content"), hits=hits)
    inline_opts: List[Dict[str, str]] = []
    if content:
        content, inline_opts = extract_inline_options(content)
        if len(inline_opts) < 2:
            # 无分隔符选项（OCR："A斯密特 B单稳态"）——严格证据版兜底
            content, inline_opts = _extract_loose_options(content)
        content = sanitize_text(content)
    out["content"] = content

    opts, opt_issues = normalize_options(fields.get("options"))
    issues.extend(opt_issues)
    if len(opts) < 2 and len(inline_opts) >= 2:
        opts = inline_opts
        issues.append("options_from_inline")
    out["options"] = opts if opts else None
    # 注意：不输出 option_count —— 它是 DB 生成列（GENERATED ALWAYS），
    # ORM 不接受该关键字，写入由 options 派生。

    for key in ("answer", "analysis", "rubric"):
        v = fields.get(key)
        if v:
            out[key] = sanitize_text(v, hits=hits)

    if hits:
        kinds = sorted({h.kind for h in hits})
        issues.append(f"watermark_removed({len(hits)}:{'+'.join(kinds)})")
    if not content:
        issues.append("content_empty")
    return out, issues


def validate_question(fields: Dict[str, Any]) -> List[str]:
    """结构校验门：空列表 = 达标可入库。"""
    issues: List[str] = []
    content = (fields.get("content") or "").strip()
    if not content:
        issues.append("content_empty")
    elif len(content) < 8:
        issues.append("content_too_short")

    # 乱码题干（PDF 抽取失败的 mojibake，不猜着改，直接下线）
    if len(_mojibake_chars_in(content)) >= 3:
        issues.append("content_mojibake")

    blob = "\n".join(str(fields.get(k) or "") for k in ("content", "answer", "analysis"))
    for p in _CONTACT_LINE_PATTERNS:
        if p.search(blob):
            issues.append("watermark_residual")
            break

    opts = fields.get("options")
    qtype = (fields.get("question_type") or "").lower()
    if qtype in ("single", "multiple", "multi", "choice") and not opts:
        issues.append("choice_without_options")

    if not fields.get("answer"):
        issues.append("answer_missing")
    return issues


# --------------------------------------------------------------------------- #
# 七、词库自学习
# --------------------------------------------------------------------------- #

LEXICON_DDL = """
CREATE TABLE IF NOT EXISTS watermark_lexicon (
    phrase      TEXT PRIMARY KEY,
    doc_count   INTEGER NOT NULL DEFAULT 0,
    hit_count   INTEGER NOT NULL DEFAULT 0,
    confidence  REAL NOT NULL DEFAULT 0.5,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    auto_learned BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


#: 试卷/教材结构标记（通用格式，非 vendor 名）——自学习时必须排除，
#: 否则 "Part A"/"Section I"/"《数字电子技术基础》" 会被误当水印删掉。
_STRUCTURAL_LABEL_RE = re.compile(
    r"^(Part|Section|Text|Passage|Article|Unit|Lesson|Chapter|Section)\s*[A-Z0-9IVX]{1,4}\s*[.、．]?$"
    r"|^《[^》]{2,40}》$"
    r"|^[A-Z]{1,2}\s*[.、．]\s*$"
    r"|^第[一二三四五六七八九十\d]+[章节部分篇]\s*[.、．]?$",
    re.IGNORECASE,
)


_PAGE_MARK_RE = re.compile(r"^\s*-{2,}\s*第?\s*\d{1,3}\s*页?\s*\(?OCR\)?\s*-{2,}\s*$|^\s*第?\s*\d{1,3}\s*页\s*[（(]?\s*(共\s*\d{1,3}\s*页)?\s*[)）]?\s*(\(OCR\))?\s*$")


def _boundary_ratio(db, phrase: str, max_len: int, sample: int = 400) -> Tuple[int, int]:
    """测量 phrase 作为整行出现在"页边界"（页标记相邻行）的比例。

    实测依据（2026-10-15，400 篇文档采样）：
    - 页脚水印（"…考研专家"）b_ratio≈0.75
    - 试卷结构（Directions:/词汇注释/Li Ming）b_ratio≈0.00~0.12
    页边界率是区分"水印"与"正文结构"的有效信号。
    """
    from sqlalchemy import text
    rows = db.execute(text("""
        SELECT content FROM documents
        WHERE content LIKE '%(OCR)%' AND length(content) > 500
        LIMIT :lim
    """), {"lim": sample}).fetchall()
    boundary = middle = 0
    for (content,) in rows:
        lines = str(content).split("\n")
        marks = {i for i, l in enumerate(lines) if _PAGE_MARK_RE.match(l.strip())}
        for i, l in enumerate(lines):
            if l.strip() != phrase:
                continue
            is_bound = (i - 1) in marks or (i + 1) in marks
            if is_bound:
                boundary += 1
            else:
                middle += 1
    return boundary, middle


def learn_watermark_lexicon(db, *, min_docs: int = 3, min_per_doc: float = 3.0,
                            max_len: int = 40, apply_ddl: bool = True,
                            min_boundary_ratio: float = 0.6) -> Dict[str, Any]:
    """从 documents 语料自学习水印词库（保守自动启用 + 候选队列）。

    智能判据（无需任何 vendor 名单，三条证据链）：
    1. **通用模式强命中**（联系方式/引流话术）→ 无条件自动启用；
    2. **跨页高频**（篇均 >= min_per_doc 次、跨 >= min_docs 篇）且
       **页边界率 >= min_boundary_ratio**（贴在页眉页脚，实测可区分正文结构）
       且非试卷结构标记、且不在题干中出现 → 自动启用；
    3. 其余统计可疑项 → 候选队列（enabled=FALSE），供人工一键审核后启用。

    新机构水印出现后：跑一次本函数即进候选队列，人工点一次即全站生效，
    **零代码改动**。返回统计 {learned, candidates, scanned}。
    """
    from sqlalchemy import text
    if apply_ddl:
        db.execute(text(LEXICON_DDL))
        db.commit()

    rows = db.execute(text("""
        SELECT line, count(DISTINCT document_id) AS nd, avg(cnt) AS avg_per_doc
        FROM (
            SELECT id AS document_id,
                   trim(regexp_split_to_table(coalesce(content,''), E'\\n')) AS line,
                   count(*) OVER (PARTITION BY id, trim(regexp_split_to_table(coalesce(content,''), E'\\n'))) AS cnt
            FROM documents
            WHERE content IS NOT NULL AND length(content) > 50
        ) t
        WHERE length(line) BETWEEN 4 AND :max_len
        GROUP BY line
        HAVING count(DISTINCT document_id) >= :min_docs
        ORDER BY nd DESC
        LIMIT 1000
    """), {"max_len": max_len, "min_docs": min_docs}).fetchall()

    learned = 0
    candidates = 0
    for line, nd, avg_per_doc in rows:
        line = (line or "").strip()
        if not line or len(line) < 4 or len(line) > max_len:
            continue
        if _STRUCTURAL_LABEL_RE.match(line):
            continue  # 试卷结构标记，永不当水印
        strong = any(p.search(line) for p in _CONTACT_LINE_PATTERNS)
        high_freq = (avg_per_doc or 0) >= min_per_doc
        # 页边界率（仅对高频候选测量，控制开销）
        b_ratio = 0.0
        if not strong and high_freq:
            b, m = _boundary_ratio(db, line, max_len)
            b_ratio = b / (b + m) if (b + m) else 0.0
        # 已被内置规则覆盖的（分页标记等）不必进队列减噪
        covered = (any(p.search(line) for p in _PAGINATION_PATTERNS)
                   or _PAGE_NUM_ONLY.match(line) is not None)
        if covered:
            continue
        auto = strong or (high_freq and b_ratio >= min_boundary_ratio)
        if auto:
            conf = 0.95 if strong else min(0.9, 0.5 + 0.05 * nd + 0.2 * b_ratio)
            db.execute(text("""
                INSERT INTO watermark_lexicon (phrase, doc_count, hit_count, confidence, enabled, auto_learned)
                VALUES (:p, :nd, 0, :conf, TRUE, TRUE)
                ON CONFLICT (phrase) DO UPDATE SET
                    doc_count = EXCLUDED.doc_count,
                    confidence = GREATEST(watermark_lexicon.confidence, EXCLUDED.confidence),
                    enabled = TRUE,
                    updated_at = now()
            """), {"p": line, "nd": int(nd), "conf": round(conf, 3)})
            learned += 1
        else:
            db.execute(text("""
                INSERT INTO watermark_lexicon (phrase, doc_count, hit_count, confidence, enabled, auto_learned)
                VALUES (:p, :nd, 0, 0.3, FALSE, TRUE)
                ON CONFLICT (phrase) DO UPDATE SET
                    doc_count = EXCLUDED.doc_count,
                    updated_at = now()
            """), {"p": line, "nd": int(nd)})
            candidates += 1
    db.commit()
    invalidate_learned_cache()
    return {"learned": learned, "candidates": candidates, "scanned": len(rows)}
