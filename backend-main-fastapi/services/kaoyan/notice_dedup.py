"""通知标题归一化与入库幂等工具.

本模块是kaoyan_notices 去重的**单一事实来源**:
- `spider_notices.py` 的入库路径使用 `upsert_notice` 保证幂等;
- `scripts/dedupe_notices.py` 的清理逻辑使用 `normalize_notice_title` 判定重复组。

两处复用同一实现, 避免归一化规则漂移导致"清了又脏".

合规说明: 本模块只做本地数据的判重与幂等写入, 不含任何主动抓取逻辑.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

# 括号内"代码:NNNN"后缀, 如「(代码:10614)」「（代码：10614）」「[代码 10614]」
_CODE_SUFFIX_RE = re.compile(
    r"[（(\[【]?\s*代\s*码\s*[:：]?\s*[0-9A-Za-z]{4,8}\s*[)）\]】]?"
)
# 内部所有空白（NBSP / 全角空格 / 制表符等统一先转半角再删）
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_notice_title(raw: Optional[str]) -> str:
    """归一化通知标题, 用于判重键.

    处理项:
    1. None/空串 -> 空串
    2. Unicode NFKC: 全角字符转半角（Ａ->A, （->(, ：->: 等）
    3. 去除「(代码:10614)」这类括号内代码后缀
    4. 去除所有内部空白字符
    5. 去掉首尾残留的孤立括号/连字符

    >>> normalize_notice_title("电子科技大学（代码：10614）2027年招生公告")
    '电子科技大学2027年招生公告'
    >>> normalize_notice_title("  2027年 硕士研究生 招生简章 ")
    '2027年硕士研究生招生简章'
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", str(raw))
    text = _CODE_SUFFIX_RE.sub("", text)
    text = _WHITESPACE_RE.sub("", text)
    # 清理因去后缀而残留的孤立括号
    text = text.replace("(", "").replace(")", "")
    text = text.replace("[", "").replace("]", "")
    return text.strip()


def normalize_notice_url(raw: Optional[str]) -> str:
    """归一化 URL, 用于判重键.

    处理: 剥离 http/https 协议 -> 剥离 www. 前缀 -> 去查询串与锚点 -> 去尾部斜杠 -> 小写.
    协议差异(http vs https)、www 前缀、末尾斜杠、追踪参数都视为同一资源.
    """
    if not raw:
        return ""
    url = str(raw).strip()
    url = re.sub(r"^https?://", "", url, flags=re.I)
    url = re.sub(r"^www\.", "", url, flags=re.I)
    url = url.split("#", 1)[0].split("?", 1)[0]
    url = url.rstrip("/")
    return url.lower()


def notice_dedup_key(school_id: Any, title: Optional[str], url: Optional[str]) -> Tuple[Any, str]:
    """构造通知的严格判重键: (school_id, 归一化URL).

    URL 是通知的唯一身份标识; URL 缺失时退化为归一化标题.
    """
    norm_url = normalize_notice_url(url)
    if norm_url:
        return (school_id, norm_url)
    return (school_id, "title:" + normalize_notice_title(title))


def notice_title_key(school_id: Any, title: Optional[str]) -> Tuple[Any, str]:
    """构造弱判重键: (school_id, 归一化标题). 用于识别标题变体."""
    return (school_id, normalize_notice_title(title))


def upsert_notice(
    conn: sqlite3.Connection,
    school_id: Any,
    school_name: str,
    title: str,
    notice_type: Optional[str] = None,
    publish_date: Optional[str] = None,
    url: Optional[str] = None,
    source: Optional[str] = None,
    fetched_at: Optional[str] = None,
) -> str:
    """幂等写入一条通知.

    冲突时执行 UPDATE 而非 INSERT, 并且**永不覆盖用户状态字段**
    (is_read / is_starred / read_at / starred_at).

    返回 "inserted" / "updated" / "skipped".

    skipped 的第三种情形（前两种是 INSERT 冲突与 SQLite 报错）：
    **URL 归一化后为空**。空锚点不是可访问的通知，见下方防护说明。
    """
    norm_url = normalize_notice_url(url)
    norm_title = normalize_notice_title(title)

    # ---- 空锚点防护：URL 归一化后为空 → 拒绝写入 ----
    # 背景（2026-10-12 实测事故）：桂林电子科技大学同一处 ``<a href="#">``
    # 空锚点被采集了两次，写成 id=419（锚点文本「博士专业学位授权类别」）
    # 与 id=945（锚点文本字面量「#」）两行。
    #
    # 为什么会写成两行：``normalize_notice_url('#')`` 剥协议后按 ``#`` 切分
    # 得到空串，于是 ``notice_dedup_key`` 退化成按标题判重；而两条空锚点的
    # **锚点文本不同**，标题判重也匹配不上，于是同一处锚点落成两行。
    #
    # 为什么这道防护是安全的：实测存量 1002 条通知中 ``url`` 归一化后为空的
    # 共 **0 条**（全部 1002 条都是 ``http://`` 或 ``https://`` 开头），
    # 因此"归一化为空就拒写"不会挡掉任何合法写入。
    #
    # 已知边界（刻意不扩大范围）：``javascript:void(0)`` 归一化后非空，
    # 仍会被接受；库内当前 0 条此类数据，如将来出现需另加一条判据。
    if not norm_url:
        return "skipped"

    def _find_by_url() -> Optional[tuple]:
        if not norm_url:
            return None
        return next(
            (
                r
                for r in conn.execute(
                    "SELECT id, url FROM kaoyan_notices "
                    "WHERE school_id IS ? AND url IS NOT NULL AND url <> ''",
                    (school_id,),
                )
                if normalize_notice_url(r[1]) == norm_url
            ),
            None,
        )

    row = _find_by_url()

    if row is None and not norm_url and norm_title:
        # 仅在 URL 缺失时退化为按归一化标题判重。
        # 有 URL 时**不做标题兜底** —— 同校同标题不同栏目 URL 是真实存在的多条
        # 通知（如西电 info/1074/20804 与 info/1072/20814 均为
        # 「2027年硕士研究生招生简章」），按标题合并会误删真通知。
        row = next(
            (
                r
                for r in conn.execute(
                    "SELECT id, title FROM kaoyan_notices WHERE school_id IS ?",
                    (school_id,),
                )
                if normalize_notice_title(r[1]) == norm_title
            ),
            None,
        )

    if row is not None:
        notice_id = row[0]
        conn.execute(
            "UPDATE kaoyan_notices SET url = COALESCE(?, url), "
            "publish_date = COALESCE(?, publish_date), "
            "notice_type = COALESCE(?, notice_type), "
            "importance_level = COALESCE(importance_level, ?), "
            "fetched_at = COALESCE(?, fetched_at) "
            "WHERE id = ?",
            (url, publish_date, notice_type, None, fetched_at, notice_id),
        )
        return "updated"

    try:
        conn.execute(
            "INSERT OR IGNORE INTO kaoyan_notices "
            "(school_id, school_name, title, notice_type, publish_date, url, source, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (school_id, school_name, title, notice_type, publish_date, url, source, fetched_at),
        )
        return "inserted"
    except Exception as exc:  # noqa: BLE001
        # 跨方言：原实现只捕 sqlite3.Error。PG 底层的 psycopg.Error 直接穿透，
        # 一条冲突/约束异常会让整轮抓取中断。此处统一兜住并**留痕**
        # （项目血泪教训 #1：静默吞异常是最贵的 bug）。
        logging.getLogger(__name__).warning(
            "upsert_notice 写入失败，跳过该条：%s", str(exc)[:200]
        )
        return "skipped"


def dedupe_table(
    conn: sqlite3.Connection,
    keep_predicate=None,
) -> Dict[str, Any]:
    """在给定连接上计算去重计划（不执行 DELETE）.

    返回 {"groups": [...], "redundant": n}, 每组含 keep_id 与 drop_ids.
    保留策略优先级: is_read/is_starred 有标记 > fetched_at 最早 > id 最小.
    """
    from collections import defaultdict

    rows = conn.execute(
        "SELECT id, school_id, title, url, publish_date, source, fetched_at, "
        "is_read, is_starred, read_at, starred_at "
        "FROM kaoyan_notices ORDER BY id"
    ).fetchall()

    groups: Dict[Tuple[Any, str], list] = defaultdict(list)
    for r in rows:
        key = notice_dedup_key(r[1], r[2], r[3])
        groups[key].append(r)

    def _rank(row) -> tuple:
        """保留优先级排序键: 越小越优先保留."""
        interacted = 0
        if row[7]:  # is_read
            interacted += 2
        if row[8]:  # is_starred
            interacted += 1
        return (
            0 if interacted else 1,          # 有交互的排最前
            str(row[6] or "9999"),            # fetched_at 最早优先
            row[0],                           # id 最小优先
        )

    plan = []
    redundant = 0
    for key, members in groups.items():
        if len(members) <= 1:
            continue
        ordered = sorted(members, key=_rank)
        keep, drops = ordered[0], ordered[1:]
        plan.append({"key": key, "keep_id": keep[0], "drop_ids": [d[0] for d in drops]})
        redundant += len(drops)

    return {"groups": plan, "redundant": redundant}