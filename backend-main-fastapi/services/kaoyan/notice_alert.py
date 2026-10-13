"""通知重要性分级 + 关键日期抽取 + 主动提醒服务。

设计要点
--------
1. **规则外置**：关键词/分级/日期语义全部放在 ``notice_rules.yaml``，
   本模块只负责解释规则，用户改 YAML 即可生效（按 mtime 缓存，无需重启）。
2. **零侵入**：`kaoyan_notices` 只做 **增量加列**（``ALTER TABLE ADD COLUMN``），
   且只加本模块自己的字段（importance_* / deadline_* / events_*），
   **绝不触碰已读相关列**（is_read / read_at 等由notice-read-track 负责）。
3. **时区安全**：Windows 上 APScheduler 缺 tzdata 会静默不注册 job。
   本模块统一走 :func:`cn_now`，用固定 ``+08:00`` 偏移构造 tzinfo，
   不依赖 zoneinfo 数据库，因此绝对不会再出现
   ``No time zone found with key Asia/Shanghai``。
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from sqlalchemy import text

logger = logging.getLogger(__name__)

# 中国标准时间：固定偏移，避免 Windows 缺 tzdata 导致 zoneinfo 查找失败
CN_TZ = timezone(timedelta(hours=8), "CST")

DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "notice_rules.yaml"

LEVEL_URGENT = "urgent"
LEVEL_IMPORTANT = "important"
LEVEL_NORMAL = "normal"

LEVEL_ORDER = {LEVEL_URGENT: 3, LEVEL_IMPORTANT: 2, LEVEL_NORMAL: 1}
LEVEL_LABEL_CN = {LEVEL_URGENT: "紧急", LEVEL_IMPORTANT: "重要", LEVEL_NORMAL: "普通"}


# --------------------------------------------------------------------------- #
# 时间工具（时区安全）
# --------------------------------------------------------------------------- #
def cn_now() -> datetime:
    """当前北京时间（aware, +08:00）。"""
    return datetime.now(CN_TZ)


def cn_today() -> date:
    """今天（北京时间口径的日期）。"""
    return cn_now().date()


def to_cn(aware_dt: datetime) -> datetime:
    """把任意 aware datetime 归一到 +08:00；naive 视为已是北京时间。"""
    if aware_dt.tzinfo is None:
        return aware_dt.replace(tzinfo=CN_TZ)
    return aware_dt.astimezone(CN_TZ)


def parse_date_loose(value: Any) -> Optional[date]:
    """宽松解析日期字符串/对象为 ``date``。

    支持 ``2026-03-20`` / ``2026/03/20`` / ``2026.3.20`` / ``20260320`` /
    ``2026年3月20日`` / ``3月20日``（缺年份时按 ``default_year`` 补）。
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None

    m = re.search(r"(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    m = re.search(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
    if m:
        year = datetime.now(CN_TZ).year
        try:
            return date(year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------- #
# 规则加载（带mtime 缓存）
# --------------------------------------------------------------------------- #
_rules_cache: Dict[str, Any] = {}
_rules_mtime: float = -1.0


def rules_path() -> Path:
    """规则文件路径（可用 ``NOTICE_ALERT_RULES`` 环境变量覆盖）。"""
    env = os.environ.get("NOTICE_ALERT_RULES", "").strip()
    return Path(env) if env else DEFAULT_RULES_PATH


def load_rules(force: bool = False) -> Dict[str, Any]:
    """加载规则 YAML（按 mtime 缓存，文件改动自动热加载）。"""
    global _rules_cache, _rules_mtime
    p = rules_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        logger.warning("通知规则文件不存在: %s，使用内置兜底规则", p)
        _rules_cache = _FALLBACK_RULES
        _rules_mtime = -1.0
        return _rules_cache
    if not force and _rules_cache and abs(mtime - _rules_mtime) < 1e-6:
        return _rules_cache
    with open(p, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    _rules_cache = data
    _rules_mtime = mtime
    logger.info("已加载通知分级规则: %s (version=%s)", p, data.get("version"))
    return data


# 规则文件缺失时的最小兜底（保证服务永不崩）
_FALLBACK_RULES: Dict[str, Any] = {
    "thresholds": {"urgent_score": 40, "important_score": 15},
    "type_weight": {"调剂": 30, "复试": 25, "录取": 28, "简章": 15, "目录": 15},
    "default_type_weight": 0,
    "keyword_rules": [
        {"level": "urgent", "score": 45, "reason": "关键节点",
         "keywords": ["复试", "拟录取", "调剂", "报名截止", "考试时间"]},
        {"level": "important", "score": 20, "reason": "政策文件",
         "keywords": ["招生简章", "专业目录", "参考书目"]},
    ],
    "date_extraction": {
        "enabled": True,
        "deadline_kinds": ["deadline_signup", "deadline_exam"],
        "event_keywords": {
            "deadline_signup": ["报名截止", "截止", "之前"],
            "deadline_exam": ["考试时间", "初试"],
            "event_retest": ["复试"],
            "event_score": ["成绩"],
            "event_adjust": ["调剂"],
        },
        "deadline_suffixes": ["截止", "之前", "前"],
    },
    "alert": {"deadline_within_days": 21, "new_notice_within_days": 7,
              "subscription_feed_days": 3, "daily_hour": 7, "daily_minute": 40},
}


# --------------------------------------------------------------------------- #
# 重要性分级
# --------------------------------------------------------------------------- #
def _safe_re(pattern: str):
    try:
        return re.compile(pattern)
    except re.error:
        logger.warning("规则正则有误已跳过: %s", pattern)
        return None


def classify_importance(
    title: str,
    notice_type: Optional[str] = None,
    body: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """按 ``notice_type`` + 标题/正文关键词给通知打重要性等级。

    Args:
        title: 通知标题。
        notice_type: 通知类型（公告/简章/复试/调剂/录取/目录/大纲…）。
        body: 正文（可选，部分通知标题不含日期，正文里有）。
        rules: 规则字典，默认从 YAML 读取。

    Returns:
        ``{"level","level_label","score","reasons":[...],"matched_keywords":[...]}``
    """
    rules = rules or load_rules()
    thresholds = rules.get("thresholds") or {}
    urgent_min = float(thresholds.get("urgent_score", 40))
    important_min = float(thresholds.get("important_score", 15))

    title = (title or "").strip()
    haystack = title
    if body:
        haystack = f"{title}\n{body}"

    reasons: List[str] = []
    matched: List[str] = []
    best_level = LEVEL_NORMAL

    # 1) 类型基础分
    type_w = rules.get("type_weight") or {}
    ntype = (notice_type or "").strip()
    base = float(type_w.get(ntype, rules.get("default_type_weight", 0)))
    if base > 0:
        reasons.append(f"类型[{ntype}]基础分 {base:.0f}")

    # 2) 关键词 / 正则规则
    for kr in rules.get("keyword_rules") or []:
        level = kr.get("level", LEVEL_NORMAL)
        score = float(kr.get("score", 0))
        reason = kr.get("reason", "")
        excludes = kr.get("not_contains") or []
        excludes_re = kr.get("not_contains_regex") or []
        matched_in_rule: List[str] = []
        for kw in kr.get("keywords") or []:
            clean = kw.strip()
            if not clean:
                continue
            if clean.startswith("-") and clean[1:] in haystack:
                continue
            if clean in haystack:
                matched_in_rule.append(clean)
        # 正则规则（比字面关键词更适合「(初试)」「考试.时间」这类变体）
        for pat in kr.get("regex") or []:
            rx = _safe_re(pat)
            if rx and rx.search(title):
                matched_in_rule.append(f"/{pat}/")
        if not matched_in_rule:
            continue
        # 命中了纯排除词（说明是被排除的组合，如「招生录取」）则整条规则不算
        if any(e in title for e in excludes):
            continue
        if any((_safe_re(p) or re.compile("(?!)")).search(title)
               for p in excludes_re if _safe_re(p)):
            continue
        matched.extend(matched_in_rule)
        reasons.append(f"命中「{reason}」({'/'.join(matched_in_rule[:3])}) "
                       f"{'+%.0f' % score if score else ''}")
        if score >= 10 and LEVEL_ORDER.get(level, 0) > LEVEL_ORDER.get(best_level, 0):
            best_level = level
        # force_level=true 的规则直接定档并短路（如「纯博士通知降为普通」）
        if kr.get("force_level"):
            forced = level
            return {
                "level": forced,
                "level_label": LEVEL_LABEL_CN.get(forced, "普通"),
                "score": 0.0,
                "reasons": reasons,
                "matched_keywords": sorted(set(matched)),
                "forced": True,
            }
        # max_score（默认 1）= 同一条规则最多计几次分，
        # 避免长标题把分数刷爆。
        gain = score * max(1, int(kr.get("max_score", 1)))
        #非紧急规则（重要/普通）的加分设上限：多条重要规则叠加也**不该**升到紧急。
        # 例：「专业目录初试科目调整」同时命中「招生政策」(+22) 与「科目调整」(+18)
        # 累计 40 恰好等于紧急阈值，会把政策变更误报成急件 —— 必须挡住。
        if level != LEVEL_URGENT:
            headroom = max(0, urgent_min - 1 - base)
            gain = min(gain, headroom)
        base += gain
        if base >= urgent_min:
            # 分数已过紧急阈值，后续规则无需再叠加（省 CPU + 避免误升级）
            break

    # 3) 阈值定档
    if base >= urgent_min:
        level = LEVEL_URGENT
    elif base >= important_min:
        level = LEVEL_IMPORTANT
    else:
        level = best_level if LEVEL_ORDER.get(best_level, 0) > 1 else LEVEL_NORMAL

    return {
        "level": level,
        "level_label": LEVEL_LABEL_CN.get(level, "普通"),
        "score": round(base, 1),
        "reasons": reasons,
        "matched_keywords": sorted(set(matched)),
    }


# --------------------------------------------------------------------------- #
# 关键日期抽取
# --------------------------------------------------------------------------- #
# 中文数字 → 阿拉伯（覆盖常见写法，够用即可，不追求全量）
_CN_NUM = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
    "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}

# 日期短语：带年份 / 纯月日 / 中文数字月日
_DATE_RE = re.compile(
    r"(?P<year>\d{4})\s*年\s*(?P<month>\d{1,2}|十[一二]?|[一二三四五六七八九])\s*月\s*"
    r"(?P<day>\d{1,2}|十[一二]?|[一二三四五六七八九十])\s*[日号]"
    r"|(?P<month2>\d{1,2})\s*月\s*(?P<day2>\d{1,2})\s*[日号]"
    r"|(?P<cn_month>十[一二]?|[一二三四五六七八九])\s*月\s*"
    r"(?P<cn_day>十[一二]?|[一二三四五六七八九十])\s*[日号]"
)


def _to_int(token: Optional[str]) -> Optional[int]:
    if not token:
        return None
    if token.isdigit():
        return int(token)
    return _CN_NUM.get(token)


# 零宽/不可见字符（Zero-width & format characters）
# 库里有标题带这类字符（实测 5 条：#388「王敬宇」、#830、#1754、#1781、#1802），
# 会**静默**破坏两类判据，且不报错、只是抽不出来：
#   1. 日期正则本身 —— Python 的 ``\s`` 只认 Unicode 空白类（Zs/Zl/Zp），
#      而 U+200B 的 Unicode 类别是 **Cf**（格式字符），不是空白。所以
#      「2027\u200b年10月」匹配不上 ``(?P<year>\d{4})\s*年``，年份直接丢失；
#   2. 语义关键词回看 —— 「王\u200b敬宇」里 ``before.rfind("王敬宇")`` 失败，
#      before 里找不到任何事件词，kind 退化成 date_other，deadline 判定一起失效。
# 在入口统一剥掉，比在每个正则里加 ``\u200b?`` 可靠：不可见字符不止一种，
# 逐个补等于永远在追。剥掉后 ``date_text``/``context`` 也不含不可见字符，
# 前端不会渲染出空白占位。
_INVISIBLE_RE = re.compile(
    "[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u00ad\u180e"
    "\u202a\u202b\u202c\u202d\u202e"
    "\u2066\u2067\u2068\u2069]"
)


def _guess_year(text: str, ref_year: Optional[int]) -> int:
    """从上下文推断年份（取**离日期最近**的那个年份词）。

    为什么必须是"最近"而不是"第一个"：一条通知里常有多个年份词，且招生届别
    年份与实际事件年份经常不同。例::

        网上报名时间为2026年10月5日至10月25日

    其中裸「10月25日」的上下文里既有标题的「2027年」（招生届别），
    也有正文的「2026年」（事件年份）。若取**第一个**会得到 2027，
    凭空把截止日推到一年后，用户会收到一个"还有 365 天"的假临期提醒。
    取**最后一个**（最近）才符合"就近修饰"的中文语义。
    """
    # 先剥不可见字符：「2027\u200b年」不剥的话连年份词都找不到
    years = re.findall(r"(20\d{2})\s*年", _INVISIBLE_RE.sub("", text or ""))
    if years:
        return int(years[-1])
    if ref_year:
        return ref_year
    return cn_now().year


# 日期区间连接词：「10月5日至10月25日」「10月5日-25日」「10月5日—25日」
# 区间的**起点不是截止日**（是"开始"），只有终点才是。
_RANGE_JOIN_RE = re.compile(
    r"\s*(?:至|到|—|–|-|~|～)\s*(?=\d{1,2}\s*月|[一二三四五六七八九十]{1,3}\s*月)"
)

# 日期**之后**的后缀型截止表述：「9月20日前完成」「10月25日前寄到」
# 中文里"X前Y"的截止语义在日期之后，只看日期前的上下文会漏。
#
# 为什么不再限定动词白名单：公文里「X前」**本身就是**截止语义，与后面跟什么
# 动词无关。第一版限定 (完成|提交|寄到|…) 时漏了「请于6月20日前**登录**系统
# 完成填报」——动词是「登录」，不在白名单里，而「完成」又离得太远够不着。
# 限定动词是脆弱的方向，改为「前 + 任意非标点内容」即可。
_SUFFIX_AFTER_RE = re.compile(r"^\s*之?前\s*\S")

# 往年/已结束标记：命中则说明该日期描述的是**过去周期**，不能当待办截止
_PAST_MARKERS = ("去年", "往年", "上一年", "上年度", "已结束", "已截止", "已关闭",
                 "现已截止", "已过期")

# 「已于2025年9月25日截止」——截止语义跨在日期两侧（前"已于"、后"截止"），
# 单纯在 before 或 after 里找「已截止」匹配不到，需要组合判定。
_CLOSED_AFTER_RE = re.compile(r"^\s*(?:截止|结束|关闭|终止|过期)")


def extract_dates(
    text: str,
    ref_date: Optional[date] = None,
    rules: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """从标题/正文抽取关键事件日期。

    对每个日期短语，向前回看 24 个字符寻找语义词（报名/复试/成绩/调剂/考试…），
    判定事件类型；命中「截止/之前/前」等后缀词则归为 deadline 类。

    Args:
        text: 标题 + 正文（调用方一般传``title + "\\n" + body``）。
        ref_date: 参考日期（一般取 publish_date），用于缺年份补全。
        rules: 规则字典。

    Returns:
        ``[{"kind","label","date","date_text","is_deadline","context"}]``
    """
    rules = rules or load_rules()
    de = rules.get("date_extraction") or {}
    if not de.get("enabled", True):
        return []
    ev_kw: Dict[str, List[str]] = de.get("event_keywords") or {}
    deadlines: List[str] = de.get("deadline_kinds") or []
    # 注：deadline_suffixes 现由 _SUFFIX_AFTER_RE 承担（截止语义在日期之后的句式），
    # YAML 里的该键保留作文档说明，不再从这里读取，避免两套判定逻辑打架。

    text = text or ""
    if not text.strip():
        return []
    # 剥零宽/不可见字符：必须在**任何匹配之前**，否则
    # 「2027\u200b年10月25日」这类标题会因 \s 不认 Cf 类字符而整条漏抽。
    # 位置全部基于剥离后的文本计算，因此 date_text/context 也不含不可见字符。
    text = _INVISIBLE_RE.sub("", text)
    if not text:
        return []

    ref_year = ref_date.year if ref_date else None
    found: List[Dict[str, Any]] = []
    seen: set = set()

    for m in _DATE_RE.finditer(text):
        start = m.start()
        # 取日期前 26 字作为语义上下文
        ctx_start = max(0, start - 26)
        before = text[ctx_start:start]
        after = text[m.end():m.end() + 12]
        date_text = m.group(0)

        #年份优先级：日期自带的年份 > 上下文最近出现的年份 > 参考年 > 当前年
        if m.group("year"):
            year = int(m.group("year"))
        else:
            year = _guess_year(text[:start], ref_year)
        month = _to_int(m.group("month") or m.group("month2") or m.group("cn_month"))
        day = _to_int(m.group("day") or m.group("day2") or m.group("cn_day"))
        if not month or not day:
            continue
        # 无年份信息且参考日期已过该月日 -> 认为是明年（跨年招生周期）
        if not (m.group("year")) and ref_date is not None:
            try:
                candidate = date(ref_year or year, month, day)
            except ValueError:
                continue
            if candidate < ref_date - timedelta(days=180):
                year += 1
        try:
            parsed = date(year, month, day)
        except ValueError:
            continue

        # 语义判定：before 里最后命中的关键词优先
        kind = "date_other"
        best_pos = -1
        for k, kws in ev_kw.items():
            for kw in kws:
                pos = before.rfind(kw)
                if pos > best_pos:
                    best_pos = pos
                    kind = k

        # ---- 修正1：区间起点不是截止日 ----
        # 「网上报名时间为10月5日至10月25日」：10月5日是**开始**，10月25日才是截止。
        # 若不区分，会把开始日当成 deadline，用户提前 20 天就收到"即将截止"的假警报。
        is_range_start = bool(_RANGE_JOIN_RE.match(text[m.end():]))

        # ---- 修正2：截止语义在日期**之后**（「9月20日前完成」）----
        # 只看 before 会漏掉这类句式，补一次 after 探测。
        suffix_after = bool(_SUFFIX_AFTER_RE.match(after))

        # ---- 修正3：往年/已结束的日期不当截止 ----
        # 「去年报名截止时间为2025年10月25日」描述的是过去周期，
        # 抽出来会变成一个永远"已过期"的假截止，用户每次打开都看到过期告警。
        past_ctx = before[-14:] + after[:6]
        is_past = any(p in past_ctx for p in _PAST_MARKERS)
        # 「已于9月25日截止」：标记跨在日期两侧，需组合判定
        if not is_past and _CLOSED_AFTER_RE.match(after) and "已" in before[-6:]:
            is_past = True
        if not is_past and ref_date is not None:
            # 日期自带年份早于参考年，且早 180 天以上 → 视为往年事件
            is_past = parsed < ref_date - timedelta(days=180)

        is_deadline = kind in deadlines
        if is_range_start:
            # 区间起点：保留事件类型供展示，但**绝不**当截止。
            # 单独标成 event_start，前端才能区分「报名开始」与「报名截止」。
            is_deadline = False
            kind = "event_start"
        elif suffix_after and kind not in deadlines:
            # 「X前完成/提交」这类后缀型截止，允许升级为 deadline_signup
            is_deadline = True
            if kind == "date_other":
                kind = "deadline_signup"
        if is_past:
            # 往年事件：可展示，但不可作为待办截止
            is_deadline = False

        label = {
            "deadline_signup": "报名/提交截止",
            "deadline_exam": "考试日期",
            "event_retest": "复试日期",
            "event_score": "成绩公布",
            "event_adjust": "调剂开放",
            "event_start": "开始日期",
            "date_other": "相关日期",
        }.get(kind, kind)

        key = (kind, parsed.isoformat())
        if key in seen:
            continue
        seen.add(key)
        found.append({
            "kind": kind,
            "label": label,
            "date": parsed.isoformat(),
            "date_text": date_text,
            "is_deadline": is_deadline,
            "context": text[ctx_start:m.end() + 10].strip().replace("\n", " ")[:120],
        })

    # deadline 优先排前，再按日期升序
    found.sort(key=lambda d: (0 if d["is_deadline"] else 1, d["date"]))
    return found


def pick_deadline(dates: List[Dict[str, Any]]) -> Optional[str]:
    """从抽取结果里挑出「最近的一个截止日」，没有则 None。"""
    d = [x for x in dates if x.get("is_deadline") and x.get("date")]
    if not d:
        return None
    d.sort(key=lambda x: x["date"])
    return d[0]["date"]


# --------------------------------------------------------------------------- #
# DB Schema（幂等，只加自己的列/表）
# --------------------------------------------------------------------------- #
ALERT_COLUMNS = [
    ("importance_level", "TEXT"),
    ("importance_score", "REAL"),
    ("importance_reason", "TEXT"),
    ("deadline_date", "TEXT"),
    ("events_json", "TEXT"),
    ("classified_at", "TEXT"),
]

_DDL = """
-- 通知订阅（用户关注的院校/专业/类型/关键词）
-- 注意：UNIQUE 里各列都带 NOT NULL DEFAULT ''（SQLite 的 UNIQUE 视 NULL 互不相等，
-- 用 NULL 会导致重复订阅），插入时用 '' 表示「该维度不适用」。
CREATE TABLE IF NOT EXISTS kaoyan_subscriptions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scope         TEXT NOT NULL,              -- school | major | notice_type | keyword
    school_id     INTEGER NOT NULL DEFAULT 0,
    school_name   TEXT NOT NULL DEFAULT '',
    major_name    TEXT NOT NULL DEFAULT '',
    notice_type   TEXT NOT NULL DEFAULT '',
    keyword       TEXT NOT NULL DEFAULT '',
    level_min     TEXT NOT NULL DEFAULT 'normal',  -- 只关心 >= 该等级的通知
    enabled       INTEGER NOT NULL DEFAULT 1,
    remark        TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE(scope, school_id, school_name, major_name, notice_type, keyword)
);
CREATE INDEX IF NOT EXISTS idx_sub_scope ON kaoyan_subscriptions(scope);

-- 每日提醒流水（同一notice + kind 不重复提醒）
CREATE TABLE IF NOT EXISTS kaoyan_alert_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id     INTEGER NOT NULL,
    alert_kind    TEXT NOT NULL,             -- deadline_soon | new_urgent | new_important | subscribed_new
    alert_date    TEXT NOT NULL,             -- YYYY-MM-DD（北京时间）
    title         TEXT,
    school_name   TEXT,
    notice_type   TEXT,
    importance_level TEXT,
    deadline_date TEXT,
    days_left     INTEGER,
    message       TEXT NOT NULL,
    acked         INTEGER NOT NULL DEFAULT 0,
    acked_at      TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE(notice_id, alert_kind)
);
CREATE INDEX IF NOT EXISTS idx_alert_date ON kaoyan_alert_records(alert_date);
CREATE INDEX IF NOT EXISTS idx_alert_acked ON kaoyan_alert_records(acked);

-- 扫描运行日志（排查定时任务是否静默失败）
CREATE TABLE IF NOT EXISTS kaoyan_alert_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at        TEXT NOT NULL,
    trigger       TEXT,                      -- schedule | manual
    scanned       INTEGER DEFAULT 0,
    created_alerts INTEGER DEFAULT 0,
    skipped_dup   INTEGER DEFAULT 0,
    elapsed_ms    INTEGER DEFAULT 0,
    detail        TEXT
);
"""


def raw_conn(db):
    """拿到底层 DBAPI（sqlite3）连接。

    注意：SQLAlchemy 1.4/2.0 的 ``db.connection()`` 返回 ``Connection``，
    其 ``.connection`` 是 ``_ConnectionFairy`` 代理 —— **惰性连接**，在真正执行
    第一条语句之前它内部的 ``dbapi_connection`` 是 ``None``，
    此时调 ``.execute()`` 会报::

        AttributeError: 'NoneType' object has no attribute 'execute'

    另外 ``db.commit()`` 之后 fairy 会被释放/换新，旧引用同样失效。
    所以这里统一：先执行一条 ``SELECT 1`` 把连接拉起来，再取 fairy。
    所有调用方都应在commit 后**重新调用本函数**拿新连接，不要缓存。
    """
    conn = db.connection()
    conn.execute(text("SELECT 1"))  # 强制建立底层连接
    return conn.connection


def scalar(conn, sql: str, args: Tuple[Any, ...] = ()) -> Any:
    """取**标量聚合**的第一列值，统一入口。

    团队规范（见 notice-read-track 的复盘）：``PRAGMA``/``COUNT(*)`` 这类查询
    在裸 ``sqlite3`` 游标上返回 tuple，下标 ``row[0]`` 能过；
    一旦连接被改成 ``row_factory = sqlite3.Row`` 就变成 ``KeyError``，
    在包装类里还会炸 ``not iterable``。统一走这里，取值方式对两种游标都成立。
    """
    row = conn.execute(sql, args).fetchone()
    if row is None:
        return None
    try:
        return row[0]
    except (KeyError, IndexError, TypeError):
        return next(iter(row.values()), None)


def table_columns(conn, table: str) -> Dict[str, Any]:
    """取表结构（列名 -> PRAGMA 行），统一入口，禁止在 router 层裸迭代 ``PRAGMA``。"""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    cols: Dict[str, Any] = {}
    for r in rows:
        try:
            cols[r[1]] = r
        except (KeyError, IndexError, TypeError):
            cols[r["name"]] = r
    return cols


def _migrate_subscriptions(conn) -> None:
    """``kaoyan_subscriptions`` 结构迁移。

    v1（初版）的问题：各维度列可空，且 ``UNIQUE`` 不含 ``school_name``。
    SQLite 里UNIQUE 认为 NULL 互不相等，所以「同一院校订阅两次」或
    「只填 school_name 的订阅」都拦不住重复，插入会撞
    ``UNIQUE constraint failed``。

    v2：所有维度列改为 ``NOT NULL DEFAULT ''``，UNIQUE 补上 ``school_name``，
    并对齐 ``level_min`` 的默认值。

    ``CREATE TABLE IF NOT EXISTS`` 不会改动已存在的表，所以这里显式检测旧结构并
    重建（数据量是用户级订阅，几十条量级，重建零成本）。
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='kaoyan_subscriptions'"
    ).fetchone()
    if not row:
        return
    sql = row[0] or ""
    cols = table_columns(conn, "kaoyan_subscriptions")
    need = []
    for name in ("school_id", "school_name", "major_name", "notice_type", "keyword",
                 "level_min"):
        info = cols.get(name)
        # 期望：school_id NOT NULL DEFAULT 0；其余 TEXT NOT NULL DEFAULT ''
        if info is not None and not info[3]:  # info[3] == notnull
            need.append(name)
    uniq_ok = "school_name" in sql.split("UNIQUE(", 1)[1].split(")", 1)[0] \
        if "UNIQUE(" in sql else False
    if not need and uniq_ok:
        return

    logger.warning("kaoyan_subscriptions 结构过旧(%s)，执行迁移重建", need or "UNIQUE 缺列")
    # 备份旧数据到临时表 -> 重建 -> 回填（NULL 归一为 ''/0）
    conn.executescript(
        """
        DROP TABLE IF EXISTS _kaoyan_subscriptions_old;
        CREATE TEMPORARY TABLE _kaoyan_subs_backup AS
            SELECT * FROM kaoyan_subscriptions;
        DROP TABLE kaoyan_subscriptions;
        """
    )
    conn.executescript(_DDL)
    conn.execute(
        "INSERT OR IGNORE INTO kaoyan_subscriptions (id, scope, school_id, school_name, "
        "major_name, notice_type, keyword, level_min, enabled, remark, created_at) "
        "SELECT id, scope, IFNULL(school_id, 0), IFNULL(school_name, ''), "
        "       IFNULL(major_name, ''), IFNULL(notice_type, ''), IFNULL(keyword, ''), "
        "       IFNULL(level_min, 'normal'), IFNULL(enabled, 1), remark, created_at "
        "FROM _kaoyan_subs_backup"
    )
    conn.execute("DROP TABLE IF EXISTS _kaoyan_subscriptions_old")
    logger.info("kaoyan_subscriptions 迁移完成")


def ensure_alert_schema(db) -> None:
    """幂等建表 + 结构迁移 + 给 ``kaoyan_notices`` 增量加列。

    只加 ``importance_*`` / ``deadline_*`` / ``events_json`` / ``classified_at``，
    **不触碰任何已读相关列**。
    """
    conn = raw_conn(db)
    conn.executescript(_DDL)
    _migrate_subscriptions(conn)
    existing = set(table_columns(conn, "kaoyan_notices").keys())
    for col, typ in ALERT_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE kaoyan_notices ADD COLUMN {col} {typ}")
            logger.info("kaoyan_notices 新增列: %s %s", col, typ)
    db.commit()


# --------------------------------------------------------------------------- #
# 分级回填 / 单条分类
# --------------------------------------------------------------------------- #
def classify_and_store(db, notice_id: int) -> Optional[Dict[str, Any]]:
    """对单条通知做分级 + 日期抽取并落库，返回结果字典。

    **必须读 `content` 列**（2026-10-12 修复，school-data-quality 预警）：
    本函数的 UPDATE 同时写 `deadline_date`。若只按标题抽取，那么
    「用户通过 `/import` 粘贴正文导入、当场抽出截止日」的成果会在下一次
    `backfill_all()` 里被**静默覆盖成 NULL** —— 标题没有月日，
    按标题重算的结果就是空。这是抽取链路自身造成的数据丢失，
    与谁触发 backfill 无关，所以在源头修。

    `content` 列可能尚未迁移（`scripts/notice_content_migration.py`），
    因此用列探测：缺列时退化为标题口径，行为与迁移前一致。
    """
    conn = raw_conn(db)
    cols = table_columns(conn, "kaoyan_notices")
    has_content = "content" in cols
    sel = ("SELECT id, title, notice_type, publish_date"
           + (", content" if has_content else "") + " FROM kaoyan_notices WHERE id = ?")
    row = conn.execute(sel, (notice_id,)).fetchone()
    if not row:
        return None
    nid, title, ntype, pub = row[0], row[1], row[2], row[3]
    body = row[4] if has_content else None
    ref = parse_date_loose(pub)
    rules = load_rules()
    cls = classify_importance(title, ntype, rules=rules)
    # 标题 + 正文双口径：正文里才有真实截止日（研招网报名窗口写在正文）
    dates = extract_dates(f"{title or ''}\n{body or ''}", ref_date=ref, rules=rules)
    deadline = pick_deadline(dates)
    now_iso = cn_now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE kaoyan_notices SET importance_level=?, importance_score=?, "
        "importance_reason=?, deadline_date=?, events_json=?, classified_at=? WHERE id=?",
        (cls["level"], cls["score"], "；".join(cls["reasons"])[:500],
         deadline, json.dumps(dates, ensure_ascii=False), now_iso, nid),
    )
    db.commit()
    return {"notice_id": nid, **cls, "dates": dates, "deadline_date": deadline}


def backfill_all(db, limit: int = 0, log_every: int = 300) -> Dict[str, Any]:
    """全量回填所有通知的分级与日期抽取。"""
    ensure_alert_schema(db)
    conn = raw_conn(db)
    sql = "SELECT id, title, notice_type, publish_date FROM kaoyan_notices"
    args: List[Any] = []
    if limit:
        sql += " LIMIT ?"
        args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    rules = load_rules()
    stats = {"total": len(rows), "urgent": 0, "important": 0, "normal": 0,
             "with_deadline": 0, "with_dates": 0}
    now_iso = cn_now().strftime("%Y-%m-%d %H:%M:%S")
    for i, (nid, title, ntype, pub) in enumerate(rows, 1):
        ref = parse_date_loose(pub)
        cls = classify_importance(title, ntype, rules=rules)
        dates = extract_dates(title or "", ref_date=ref, rules=rules)
        deadline = pick_deadline(dates)
        stats[cls["level"]] = stats.get(cls["level"], 0) + 1
        if dates:
            stats["with_dates"] += 1
        if deadline:
            stats["with_deadline"] += 1
        conn.execute(
            "UPDATE kaoyan_notices SET importance_level=?, importance_score=?, "
            "importance_reason=?, deadline_date=?, events_json=?, classified_at=? WHERE id=?",
            (cls["level"], cls["score"], "；".join(cls["reasons"])[:500],
             deadline, json.dumps(dates, ensure_ascii=False), now_iso, nid),
        )
        if i % log_every == 0:
            db.commit()
            # commit 会释放底层连接，fairy 失效 —— 必须重新获取
            conn = raw_conn(db)
            logger.info("分级回填进度 %d/%d", i, len(rows))
    db.commit()
    logger.info("分级回填完成: %s", stats)
    return stats


# --------------------------------------------------------------------------- #
# 订阅匹配
# --------------------------------------------------------------------------- #
def _load_subscriptions(db) -> List[Dict[str, Any]]:
    conn = raw_conn(db)
    rows = conn.execute(
        "SELECT id, scope, school_id, school_name, major_name, notice_type, keyword, level_min "
        "FROM kaoyan_subscriptions WHERE enabled = 1"
    ).fetchall()
    return [
        {"id": r[0], "scope": r[1], "school_id": r[2], "school_name": r[3],
         "major_name": r[4], "notice_type": r[5], "keyword": r[6],
         "level_min": r[7] or "normal"}
        for r in rows
    ]


def notice_matches_subscription(notice: Dict[str, Any], sub: Dict[str, Any]) -> bool:
    """判断单条通知是否命中某条订阅。

    ``level_min`` 作为「噪音过滤」：等级低于订阅门槛的通知不推送，
    避免用户订阅了「某校」却被上百条普通公告刷屏。
    """
    if LEVEL_ORDER.get(notice.get("importance_level") or LEVEL_NORMAL, 1) < \
       LEVEL_ORDER.get(sub.get("level_min") or LEVEL_NORMAL, 1):
        return False
    scope = sub["scope"]
    if scope == "school":
        if sub.get("school_id"):
            return int(notice.get("school_id") or 0) == int(sub["school_id"])
        return bool(sub.get("school_name")) and sub["school_name"] == notice.get("school_name")
    if scope == "major":
        kw = (sub.get("major_name") or "").strip()
        return bool(kw) and (kw in (notice.get("title") or "") or
                            kw in (notice.get("school_name") or ""))
    if scope == "notice_type":
        return bool(sub.get("notice_type")) and sub["notice_type"] == notice.get("notice_type")
    if scope == "keyword":
        kw = (sub.get("keyword") or "").strip()
        return bool(kw) and kw in ((notice.get("title") or "") + (notice.get("school_name") or ""))
    return False


# --------------------------------------------------------------------------- #
# 提醒扫描（核心：产出「今日待办提醒」）
# --------------------------------------------------------------------------- #
def _notice_rows_since(db, since: date, limit: int = 4000) -> List[Dict[str, Any]]:
    conn = raw_conn(db)
    rows = conn.execute(
        "SELECT id, school_id, school_name, title, notice_type, publish_date, url, "
        "       importance_level, importance_score, deadline_date, events_json "
        "FROM kaoyan_notices WHERE publish_date IS NOT NULL AND publish_date >= ? "
        "ORDER BY publish_date DESC LIMIT ?",
        (since.isoformat(), limit),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "school_id": r[1], "school_name": r[2], "title": r[3],
            "notice_type": r[4], "publish_date": r[5], "url": r[6],
            "importance_level": r[7] or LEVEL_NORMAL, "importance_score": r[8] or 0,
            "deadline_date": r[9], "events_json": r[10],
        })
    return out


def purge_orphan_alerts(db) -> int:
    """删除指向**已不存在通知**的提醒记录，返回清理条数。

    背景：本库的通知数据会被噪声清洗流程 ``DELETE``（实测1504 -> 1004），
    ``kaoyan_alert_records`` 没有外键级联，会留下指向已删通知的死提醒，
    前端点进去404。这里做幂等自愈，不需要外部手工干预。
    """
    try:
        conn = raw_conn(db)
        cur = conn.execute(
            "DELETE FROM kaoyan_alert_records WHERE notice_id NOT IN "
            "(SELECT id FROM kaoyan_notices)"
        )
        n = cur.rowcount or 0
        if n:
            db.commit()
            logger.info("清理孤儿提醒记录 %d 条", n)
        return int(n)
    except Exception as exc:  # 清理是「锦上添花」，失败不应阻断扫描
        logger.warning("清理孤儿提醒失败: %s", exc)
        return 0


def scan_alerts(db, trigger: str = "manual", now: Optional[datetime] = None) -> Dict[str, Any]:
    """扫描并生成提醒记录。

    四类提醒：
      1. ``deadline_soon``   —— 截止日在 N 天内（含今天），最需要行动
      2. ``new_urgent``     —— 新发布的高等级通知
      3. ``subscribed_new`` —— 命中用户订阅的新通知
      4. ``new_important``  —— 新发布的重要通知（仅当有订阅时才生成，避免全站噪声）

    去重：``UNIQUE(notice_id, alert_kind)`` 落库层保证同一通知同一类型只提醒一次；
    用户 ack 后不再打扰。
    """
    import time as _t

    t0 = _t.time()
    ensure_alert_schema(db)
    # 先清孤儿提醒（上游数据清洗可能 DELETE 掉通知），避免提醒列表出现死链
    purged = purge_orphan_alerts(db)
    rules = load_rules()
    acfg = rules.get("alert") or {}
    now = to_cn(now or cn_now())
    today = now.date()

    deadline_days = int(acfg.get("deadline_within_days", 21))
    new_days = int(acfg.get("new_notice_within_days", 7))
    feed_days = int(acfg.get("subscription_feed_days", 3))

    # 回看窗口要足够覆盖最长临期期（否则截止日远的通知永远进不了候选集）
    window_start = today - timedelta(days=max(new_days, feed_days, 1) + 7)
    notices = _notice_rows_since(db, window_start)
    subs = _load_subscriptions(db)
    conn = raw_conn(db)

    candidates: List[Tuple[int, str, str]] = []  # (notice_id, alert_kind, message)
    scanned = 0

    for n in notices:
        scanned += 1
        pub = parse_date_loose(n["publish_date"])
        level = n["importance_level"] or LEVEL_NORMAL
        label = LEVEL_LABEL_CN.get(level, "普通")

        # --- 1) 临期截止 ---
        dl = parse_date_loose(n["deadline_date"])
        if dl:
            days_left = (dl - today).days
            if -3 <= days_left <= deadline_days:
                if days_left < 0:
                    msg = f"【已过期】{n['school_name'] or ''}｜{n['title']}（截止 {dl.isoformat()}，已过 {-days_left} 天）"
                elif days_left == 0:
                    msg = f"【今天截止】{n['school_name'] or ''}｜{n['title']}"
                else:
                    msg = f"【剩{days_left}天】{n['school_name'] or ''}｜{n['title']}（{dl.isoformat()} 截止）"
                candidates.append((n["id"], "deadline_soon", msg))
                n["_days_left"] = days_left

        # --- 2) 新发布的高等级通知 ---
        if pub and (today - pub).days <= new_days and level in (LEVEL_URGENT,):
            when = "今天" if pub == today else pub.isoformat()
            candidates.append((
                n["id"], "new_urgent",
                f"【紧急·{when}发布】{n['school_name'] or ''}｜{n['title']}",
            ))

        # --- 3) 订阅命中 ---
        if subs and pub and (today - pub).days <= feed_days and (today - pub).days >= 0:
            if any(notice_matches_subscription(n, s) for s in subs):
                candidates.append((
                    n["id"], "subscribed_new",
                    f"【订阅更新·{(today - pub).days}天内】{n['school_name'] or ''}｜{n['title']}",
                ))

    # --- 4) 重要级（仅当用户有订阅，平衡噪音）---
    if subs:
        for n in notices:
            pub = parse_date_loose(n["publish_date"])
            if pub and (today - pub).days <= new_days and n["importance_level"] == LEVEL_IMPORTANT:
                candidates.append((
                    n["id"], "new_important",
                    f"【重要·{pub.isoformat()}】{n['school_name'] or ''}｜{n['title']}",
                ))

    # --- 去重落库 ---
    now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
    created = 0
    dup = 0
    seen_in_batch: set = set()
    for notice_id, kind, msg in candidates:
        if (notice_id, kind) in seen_in_batch:
            dup += 1
            continue
        seen_in_batch.add((notice_id, kind))
        n = next((x for x in notices if x["id"] == notice_id), None)
        dl = parse_date_loose(n["deadline_date"]) if n else None
        days_left = (dl - today).days if dl else None
        exists = conn.execute(
            "SELECT id, acked FROM kaoyan_alert_records WHERE notice_id=? AND alert_kind=?",
            (notice_id, kind),
        ).fetchone()
        if exists:
            dup += 1
            continue
        conn.execute(
            "INSERT INTO kaoyan_alert_records (notice_id, alert_kind, alert_date, title, "
            "school_name, notice_type, importance_level, deadline_date, days_left, message, "
            "acked, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,?)",
            (notice_id, kind, today.isoformat(),
             (n or {}).get("title"), (n or {}).get("school_name"),
             (n or {}).get("notice_type"), (n or {}).get("importance_level"),
             dl.isoformat() if dl else None, days_left, msg, now_iso),
        )
        created += 1

    elapsed = int((_t.time() - t0) * 1000)
    conn.execute(
        "INSERT INTO kaoyan_alert_runs (ran_at, trigger, scanned, created_alerts, "
        "skipped_dup, elapsed_ms, detail) VALUES (?,?,?,?,?,?,?)",
        (now_iso, trigger, scanned, created, dup, elapsed,
         json.dumps({"today": today.isoformat(), "subs": len(subs),
                     "candidates": len(candidates)}, ensure_ascii=False)),
    )
    db.commit()
    result = {"trigger": trigger, "today": today.isoformat(), "scanned": scanned,
              "candidates": len(candidates), "created": created, "skipped_dup": dup,
              "elapsed_ms": elapsed, "subscriptions": len(subs),
              "purged_orphan": purged}
    logger.info("[通知提醒扫描] %s", json.dumps(result, ensure_ascii=False))
    return result
