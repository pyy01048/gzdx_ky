# -*- coding: utf-8 -*-
"""清理 knowledge_chunks 中的垃圾块（引流水印 / 编码乱码 / 纯符号）。

背景
----
`knowledge_chunks` 75122 行里，唯一 text 仅 68915。冗余 6207 行的成因已定位：
    B 跨 doc 同 text 冗余 = 5411 (87.2%) —— 444 组同名 documents 重复入库
    A 同 doc 内同 text    =  796 (12.8%)
而重复的 text 本身绝大多数是**垃圾**：PDF 文本层提取失败，只抓到封面水印/引流文字，
于是 chunk_text 对同一段短文本反复切出相同的块。

实测垃圾占比（全库 75122 行）：
    含 'QQ' 5366 (7.1%) | 含 '微信公众号' 1216 (1.6%) | 含 'MOOC' 814 (1.1%)
    含 '扫码' 227 | 含 '二维码' 81
    高频重复 text top：x80 / x68 / x43 / x24，全部是引流水印
    编码乱码：'bZeHz.z sVfYoH,2M t HtUNYLiwH'（doc=759 字体编码失败）

安全策略
--------
1. **dry-run 默认开**，必须显式 `--apply` 才写库。
2. `--apply` 时强制先用 SQLite `backup()` API 备份（**禁止 shutil.copy2/cp**，WAL 会丢数据）。
3. 连带清理 knowledge_chunks_vec / knowledge_chunks_fts / error_knowledge_links。
4. 删除顺序：_vec / _fts / error_knowledge_links → knowledge_chunks（避免外键约束失败）。
5. 保守：只删「**明确是垃圾**」的，不碰任何正常学习内容。宁可漏删不可误删。

用法
----
    python scripts/clean_junk_chunks.py                      # dry-run
    python scripts/clean_junk_chunks.py --show-samples 30     # dry-run，多看样本
    python scripts/clean_junk_chunks.py --apply              # 真删（自动先备份）
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from services.delete_guard import require_physical_delete_enabled  # noqa: E402

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

DEP_TABLES = ("knowledge_chunks_vec", "knowledge_chunks_fts", "error_knowledge_links")

# --------------------------------------------------------------------------- #
# 判据 1：引流/水印特征（命中即判垃圾）
# 注意用「强特征」而非泛词，避免误杀正常教材内容。
#   "QQ群" 单独出现可能在讲题；但 "学长QQ：" / "QQ：764312801" 一定是引流。
# --------------------------------------------------------------------------- #
_SPAM_PATTERNS: tuple[tuple[str, str], ...] = (
    ("学长QQ", "学长引流"),
    ("QQ：", "QQ号引流"),
    ("QQ:", "QQ号引流"),
    ("微信公众号", "公众号引流"),
    ("关注微信", "公众号引流"),
    ("扫码", "扫码引流"),
    ("二维码", "二维码"),
    ("中国大学MOOC", "MOOC水印"),
    ("大学MOOC", "MOOC水印"),
    ("MOOC", "MOOC水印"),
    ("慕课", "MOOC水印"),
    ("淘宝", "店铺广告"),
    ("认准", "店铺广告"),
    ("仅供学习交流", "版权声明"),
    ("请勿转载", "版权声明"),
    ("侵权", "版权声明"),
    ("加QQ", "引流"),
    ("微信同号", "引流"),
    ("扫码获取", "引流"),
    ("资料仅供", "引流"),
    ("付费资料", "引流"),
    ("加vx", "引流"),
    ("vx：", "引流"),
)

# --------------------------------------------------------------------------- #
# 判据 2：正常字符占比过低（编码乱码）
# 正常字符 = ASCII 可打印 + 中文基本区。实测乱码串该值约 0.3~0.5，正常中文 >0.95。
# 阈值 0.5 是实测挑的：正常中文/英文都远超它，乱码明显低于它。
# --------------------------------------------------------------------------- #
_RE_COMMON = re.compile(r"[ -~一-鿿]")
_GARBAGE_RATIO = 0.5

# --------------------------------------------------------------------------- #
# 判据 3：纯符号/纯换行/纯点号（无任何实义）
# --------------------------------------------------------------------------- #
_RE_CJK_OR_LATIN = re.compile(r"[一-鿿A-Za-z]")

# --------------------------------------------------------------------------- #
# 判据 4：极端高频重复（同一条 text 出现 >= N 次）
# 真实学习内容不会一字不差重复几十遍；水印会。
# --------------------------------------------------------------------------- #
HIGH_FREQ_THRESHOLD = 8


def classify(text: str | None) -> tuple[bool, str]:
    """判定单个块是否为**纯垃圾**（可直接删除）。

    返回 (是否纯垃圾, 原因)。
    注意：这里只判「整块删掉也不可惜」的情况。
    「真实内容 + 尾部水印」的混合体由 truncate_spam_tail() 处理，不走删除路径。
    """
    if text is None:
        return True, "text为NULL"
    t = text.strip()
    if not t:
        return True, "空白块"

    # 判据 0：混合体先剥离水印尾部，剥离后仍够长就**不算纯垃圾**
    cleaned = truncate_spam_tail(t)
    if cleaned is not None and len(cleaned) >= _MIN_KEEP_CHARS:
        return False, ""

    # 判据 0b：**中文字量护栏** —— 内容充实就不删（最多只能被截尾）
    # 实测：待删候选里曾有 3354 块含 60+ 中文字，是真实题目/解析，删掉白丢真题。
    if _cjk_count(t) >= _PROTECT_CJK:
        return False, ""

    # 判据 2a：ASCII 乱码（PDF 字体编码失败，中文为 0 且英文全是碎片）
    if _looks_like_gibberish(t):
        return True, "编码乱码"

    # 判据 1：引流水印（剥离后剩下的内容太短，等于全是水印）
    for kw, reason in _SPAM_PATTERNS:
        if kw in t:
            return True, reason

    # 判据 2：编码乱码（正常字符占比过低）
    if len(t) >= 20:
        common = len(_RE_COMMON.findall(t))
        if common / len(t) < _GARBAGE_RATIO:
            return True, "编码乱码"

    # 判据 3：没有任何实义字符（纯符号/换行/点号）
    if not _RE_CJK_OR_LATIN.search(t):
        return True, "无实义字符"

    return False, ""


# --------------------------------------------------------------------------- #
# 「真实内容 + 尾部引流水印」混合体的处理：**截尾保留**，不整块删
# 实测 4546 个块含水印特征，其中 2339 块剥掉尾部水印后仍有 >=200 字有效内容
# （比如 '状态下，其"关"态和"开"态…13、n沟道增强型mos管…' 后接 '观畴考研…微信:…'）。
# 整块删会白丢大量真题与解析，所以这里只砍掉尾部水印。
# --------------------------------------------------------------------------- #
_TRUNCATE_MARKS: tuple[str, ...] = (
    "微信公众号",
    "学长QQ",
    "QQ：",
    "QQ:",
    "观畴考研",
    "中国大学MOOC",
    "大学MOOC",
    "扫码",
    "二维码",
    "淘宝",
    "认准",
    "仅供学习交流",
    "加QQ",
    "微信同号",
    "vx：",
)

# 剥掉尾部水印后，至少要留下这么多字才值得保留
_MIN_KEEP_CHARS = 200


# 尾部水印段的**白名单词元**。只有全部由这些片段拼成的尾部才判定为水印段。
# 关键：水印本身是中文（"观畴考研""微信公众号"），所以不能用「是否含中日韩字符」
# 来区分水和正文——必须用词元白名单。
_TAIL_SEGMENTS: tuple[str, ...] = (
    "微信公众号", "公众号", "观畴考研", "学长", "合工大电物院", "考研资料",
    "你的考研专家", "东坡哥", "haidongpo3", "电子与通信工程考研",
    "中国大学MOOC", "大学MOOC", "MOOC", "慕课",
    "二维码", "扫码", "淘宝", "认准", "店铺",
    "仅供学习交流", "请勿转载", "侵权", "加QQ", "微信同号", "vx",
    "考研", "资料", "获取", "关注", "更多",
    "QQ", "qq", "vx", "VX", "v信", "威信",
)

_SPAM_PUNCT = set(" \t\r\n。．.，,、；;：:！!？?（）()【】[]《》<>\"'“”‘’-—_/\\|*#@~·…")

# --------------------------------------------------------------------------- #
# **防误杀护栏**（实测得出，必不可放宽）
# 实测发现：大量块是「真实题目/解析 + 尾部或首部引流水印」的混合体，
# 例如 id=2757 有 493 个中文字，内容是完整的三极管/MOS管选择题，
# 只是末尾跟了一句 '观畴考研…微信:haidongpo3QQ:3428047568'。
# 如果只按「含引流特征」整块删，会白丢几千道真题。
# 因此：**中文字数 >= 该阈值的块一律不删，只做截尾。**
# --------------------------------------------------------------------------- #

# 中文字数护栏：达到此值的块，无论是否含水印都不删（只截尾）
# 阈值依据实测：真题目块常有 90~650 中文字（如 id=2757 有 493 字，是完整选择题）。
# 纯水印块普遍 < 40 中文字（'学长QQ' '合工大电物院' 等引流话术）。
# 取 60 作为分界：>=60 视为有实质中文内容，一律不删。
_PROTECT_CJK = 60

# 实义词护栏（覆盖没有中文的乱码）。
# 背景：像 'bZeHz.z sVfYoH,2M t HtUNYLiwH ) VrV0?UsL .Z6xX ew![!yo!wrwh:' 这种
# 字体编码失败的乱码，**全是 ASCII 字母数字**，所以「正常字符占比」判据对它无效
# （占比 = 1.0，看着完全正常）。
# 但它有个明显特征：**存在大量形近但读不通的碎片串**，既不成词也不成句。
# 判据：中文 < 30 字 且 平均"词长"异常（连续字母串多但缺少中文/常用英文词结构）。
# 简化实现：中文极少（<30）时，用「是否含足够长的自然英文词或中文」来区分。
_PROTECT_MEANINGFUL_EN = 6  # 至少要有这么长的英文词


def _is_mixed(w: str) -> bool:
    """真·大小写混排：同一个词里既有大写又有小写。

    排除三种正常形态：
        全大写缩写  FPGA / TTL / EMBED
        全小写单词  the / gate / configuration
        首字母大写  Document / FluMist（专有名词）
    只有 'bZeHz' 'sVfYoH' 'HtUNYLiwH' 这类**词内跳变**才算乱码。
    """
    has_up = any(c.isupper() for c in w)
    has_lo = any(c.islower() for c in w)
    if not (has_up and has_lo):
        return False
    return not (w[0].isupper() and w[1:].islower())


def _looks_like_gibberish(t: str) -> bool:
    """检测 PDF 字体编码失败产生的乱码（中文为 0，全是 ASCII 碎片）。

    判据：乱码词的大小写**逐字符跳变**
        'bZeHz' 'sVfYoH' 'HtUNYLiwH' 'N0 NROMTRAMvb0' 'JKHCJOJPJQJ'
    而正常文本的词要么全小写（the/output/spraytype）、
    要么全大写缩写（TTL/PCB/PAL）、要么首字母大写（Document/Word）。

    **只看前若干个词**（实测踩坑）：
    真实英语阅读文章（如考研英语真题原文）里会出现成片的缩写与专有名词
    （'FPGA' 'EMPROM' 'DocumentSummaryInformation'），全量统计时
    混排比例能到 50%（59/119），跟乱码一个量级。
    但乱码的**开头几个词几乎全是混排**，正常文本开头是大片通顺小写词。
    所以只取前 12 个词来判定，避免误杀真英语语料。
    """
    if _cjk_count(t) >= 30:
        return False
    words = re.findall(r"[A-Za-z]{3,}", t)
    if len(words) < 3:
        return False

    mixed = sum(1 for w in words if _is_mixed(w))

    # 实测标定（比例判据，分离度很干净）：
    #   乱码   'bZeHz.z sVfYoH,2M t HtUNYLiwH'          混排 5/6  = 0.83
    #          'RrbjbjVVcrrh XXXlll8%Lle HJJJJJJcfnXnr' 混排 6/7  = 0.86
    #          'JKHCJOJPJQJJKHCJOJPJQJ'                 混排 4/4  = 1.00
    #   正常   'ere of the FluMist nasal spraytype…'    混排 1/15 = 0.07
    #          'The TTL gate output stage uses…'       混排 0/15 = 0.00
    # 取 0.5 做阈值，两侧都有 0.4 以上的安全余量。
    return mixed / len(words) >= 0.5


def _cjk_count(text: str) -> int:
    return len(re.findall(r"[一-鿿]", text))


def _is_spam_tail(tail: str) -> bool:
    """判断一段文本是否**完全**由引流词元 + 标点拼成（即纯水印段）。

    实现：把尾部所有词元都归一化成「是/否」两类——
      - 命中白名单词元 → 消耗掉
      - 标点 → 忽略
      - 其它字符（残留实义中文/字母）→ 判定失败
    只要有任何一个实义字符没被词元吃掉，就说明这段不是纯水印，不能裁。
    """
    rest = tail
    # 反复剥离白名单词元
    changed = True
    while changed:
        changed = False
        for seg in _TAIL_SEGMENTS:
            if seg in rest:
                rest = rest.replace(seg, "", 1)
                changed = True
    # 剩余只能是标点/空白
    leftover = [ch for ch in rest if ch not in _SPAM_PUNCT]
    # 允许少量数字（QQ号/微信号）
    digits = sum(1 for ch in leftover if ch.isdigit())
    if digits / max(len(leftover), 1) > 0.5 and len(leftover) <= 24:
        return True
    return not leftover


def truncate_spam_tail(text: str) -> str | None:
    """剥掉尾部连续的引流水印文字。

    返回剥干净的正文；若找不到可裁剪点或剥离后太短，返回 None（交给 classify 走删除）。

    关键约束：**只裁剪「整段都是水印」的尾巴**。
    如果水印后面还有正常内容（或水印混在正文中间），一律不裁。
    """
    if not text:
        return None

    # 定位最后一个可裁剪点（取最靠前的那次出现，保证尾巴完整）
    cut = None
    for mark in _TRUNCATE_MARKS:
        p = text.rfind(mark)
        if p < 0:
            continue
        if cut is None or p < cut:
            cut = p

    if cut is None or cut <= 0:
        return None

    tail = text[cut:]
    # 从尾部往前扫「连续可剥离的水印片段」，支持行内水印（无换行）与多行水印。
    # 逐个 _TRUNCATE_MARKS 从尾往头试：若某段尾巴能被判定为纯水印，就砍掉它，
    # 继续处理新的尾巴，直到剩下的尾巴不再是水印。
    body = text
    while True:
        marks = [m for m in _TRUNCATE_MARKS if m in body]
        if not marks:
            break
        # 取最靠前的一次出现作为候选裁剪点
        cut2 = min(body.rfind(m) for m in marks)
        if cut2 <= 0:
            break
        tail = body[cut2:]
        if not _is_spam_tail(tail):
            break
        body = body[:cut2].rstrip()
        # 剩余尾巴太短就不用再剥了
        if len(body) < _MIN_KEEP_CHARS:
            break

    if len(body) < _MIN_KEEP_CHARS or body == text:
        return None
    return body


def find_junk_ids(conn: sqlite3.Connection, *, high_freq: int) -> tuple[list[int], dict[str, int], list, list]:
    """扫描全表，返回 (垃圾 id 列表, 原因分布, 高频重复组, 需截尾的 (id, 新正文))。"""
    hi_groups = conn.execute(
        """SELECT text, COUNT(*) c FROM knowledge_chunks
           WHERE text IS NOT NULL GROUP BY text HAVING c >= ? ORDER BY c DESC""",
        (high_freq,),
    ).fetchall()
    hi_texts = {t for t, _ in hi_groups}

    junk_ids: list[int] = []
    reasons: dict[str, int] = {}
    samples: list[tuple[int, int, str, int, str]] = []
    truncates: list[tuple[int, str]] = []

    cur = conn.execute("SELECT id, document_id, doc_name, text FROM knowledge_chunks")
    for cid, doc_id, doc_name, text in cur:
        t = (text or "").strip()
        # 先看能否只截掉尾部水印（保住正文）
        body = truncate_spam_tail(t) if t else None
        if body is not None:
            truncates.append((cid, body))
            continue

        is_junk, reason = classify(text)
        # 高频重复也判垃圾（即使单看内容不算垃圾）
        if not is_junk and text in hi_texts:
            is_junk, reason = True, "高频重复"
        if is_junk:
            junk_ids.append(cid)
            reasons[reason] = reasons.get(reason, 0) + 1
            samples.append((cid, doc_id, (doc_name or "")[:36],
                            len(text or ""), (text or "").replace("\n", "\\n")[:58]))
    return junk_ids, reasons, hi_groups, truncates


def backup_db(src_path: str, dst_path: str) -> str:
    """SQLite 官方 backup() API —— 唯一正确的备份方式（copy2/cp 会丢 WAL 数据）。"""
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dst_path


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    def one(sql: str) -> int:
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.Error:
            return -1

    return {
        "knowledge_chunks": one("SELECT COUNT(*) FROM knowledge_chunks"),
        "documents": one("SELECT COUNT(*) FROM documents"),
        "vec": one("SELECT COUNT(*) FROM knowledge_chunks_vec"),
        "fts": one("SELECT COUNT(*) FROM knowledge_chunks_fts"),
        "ekl": one("SELECT COUNT(*) FROM error_knowledge_links"),
        "spam_qq": one("SELECT COUNT(*) FROM knowledge_chunks WHERE text LIKE '%QQ%'"),
        "spam_wechat": one("SELECT COUNT(*) FROM knowledge_chunks WHERE text LIKE '%微信公众号%'"),
        "spam_mooc": one("SELECT COUNT(*) FROM knowledge_chunks WHERE text LIKE '%MOOC%'"),
        "spam_qr": one("SELECT COUNT(*) FROM knowledge_chunks WHERE text LIKE '%二维码%' OR text LIKE '%扫码%'"),
    }


def selftest() -> int:
    """用固定用例锁死判据行为，防回归。

    重点验证「不误杀真题目」这条底线。
    """
    cases: list[tuple[str, str, str]] = [
        # (说明, 文本, 期望: 'delete' 删 / 'keep' 留 / 'truncate' 截尾)
        ("纯引流水印",
         "料，学长QQ：764312801合工大电物院初试、复试专业课资料，学长QQ：764312801合工大电物院",
         "delete"),
        ("MOOC水印重复",
         "大学MOOC中国大学MOOC中国大学MOOC中国大学MOOC中国大学MOOC中国大学MOOC",
         "delete"),
        ("编码乱码",
         "bZeHz.z sVfYoH,2M t HtUNYLiwH ) VrV0?UsL .Z6xX ew![!yo!wrwh:",
         "delete"),
        ("纯符号点号",
         "\n.\n.\n.\n.\n.\n.\n.\n.\n.\n.\n.\n.\n.\n.\n.\n.\n",
         "delete"),
        ("空白", "   \n  \n ", "delete"),
        ("正常正文无水印",
         "肖克莱互补对称输出电路的静态工作点计算方法是：先求出静态基极电流，"
         "再求集电极电压。这是最典型的甲乙类功率放大电路的静态分析。",
         "keep"),
        # 实测踩坑：真实考研英语阅读原文里全是 FPGA/EMPROM 这类缩写，
        # 全量统计混排词能到 59/119，跟乱码一个量级。判据必须只看前几个词。
        ("真实英语阅读原文（含FPGA/EMPROM缩写，绝不能误杀）",
         "ere of the FluMist nasal spraytype, which is not 18 for pregnant women, "
         "peop le should avoid this vaccine. The EMPROM read ROM contains FPGA "
         "FPGA CPLD GAL PAL configuration data and the DocumentSummaryInformation "
         "block. Root Entry DocumentSummaryInformation WordDocument TableData.",
         "keep"),
        ("真实英文技术文档",
         "The TTL gate output stage uses a push-pull configuration with "
         "complementary transistors to drive the load capacitor.",
         "keep"),
        ("含水印但中文量大（必须留，绝不能删）",
         "状态下，其关态和开态，分别指三极管的。A.截止状态和饱和状态B.截止状态和放大状态"
         "C.放大状态和饱和状态D.饱和状态和截止状态13、n沟道增强型mos管开态是指"
         "（），关态是指（A、截止区B、可变电阻区C、饱和区D、放大区"
         "观畴考研，你身边的考研专家东坡哥微信:haidongpo3QQ:3428047568",
         "keep"),
    ]

    print("=" * 68)
    print("SELF TEST：垃圾块判据（防误杀优先）")
    print("=" * 68)
    failed = 0
    for desc, text, expect in cases:
        tr = truncate_spam_tail(text)
        if tr is not None:
            got = "truncate"
        else:
            j, _ = classify(text)
            got = "delete" if j else "keep"
        ok = got == expect
        # 关键底线：含大量中文的块绝不能被判 delete
        if _cjk_count(text) >= _PROTECT_CJK and got == "delete":
            ok = False
        mark = "✓" if ok else "✗ FAIL"
        print(f"  [{mark}] {desc}")
        print(f"         期望={expect} 实际={got} 中文字数={_cjk_count(text)}")
        if not ok:
            failed += 1

    print()
    print(f"  通过 {len(cases) - failed}/{len(cases)}")
    print("  SELFTEST: " + ("PASS" if failed == 0 else f"FAIL ({failed} 项)"))
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="清理 knowledge_chunks 垃圾块（dry-run 默认开）")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--apply", action="store_true", help="真正写库")
    ap.add_argument("--selftest", action="store_true", help="只跑判据自检（不碰数据库）")
    ap.add_argument("--high-freq", type=int, default=HIGH_FREQ_THRESHOLD,
                    help=f"同 text 出现 >= N 次即判垃圾（默认 {HIGH_FREQ_THRESHOLD}）")
    ap.add_argument("--show-samples", type=int, default=20)
    ap.add_argument("--backup", default=None)
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not os.path.isfile(args.db):
        print(f"数据库不存在: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    try:
        before = stats(conn)
        junk_ids, reasons, hi_groups, truncates = find_junk_ids(
            conn, high_freq=args.high_freq
        )
        n = len(junk_ids)

        print("=" * 72)
        print("垃圾块清理" + ("（DRY-RUN，不写库）" if not args.apply else "（APPLY）"))
        print("=" * 72)
        print(f"  扫描判据：引流特征 {len(_SPAM_PATTERNS)} 条 | "
              f"正常字符占比<{_GARBAGE_RATIO} | 无实义字符 | 同text出现>={args.high_freq}次")
        print()
        print("  清理前行数：")
        for k, v in before.items():
            print(f"    {k:<20} {v}")
        print()
        print(f"  判定为**纯垃圾**（整块删除）的块 = {n}")
        print("  原因分布：")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {r:<22} {c}")
        print()
        print(f"  判定为**混合体**（仅截掉尾部水印，保留正文）的块 = {len(truncates)}")
        if truncates:
            print("    截尾样例：")
            for cid, body in truncates[:3]:
                print(f"      #{cid}: 保留 {len(body)} 字 … {body[-40:]!r}")
        print()
        if hi_groups:
            print(f"  高频重复组（>={args.high_freq}次）共 {len(hi_groups)} 组，前10：")
            for t, c in hi_groups[:10]:
                print(f"    x{c:<5} {t[:56].replace(chr(10), ' ')!r}")
            print()
        if junk_ids[: args.show_samples]:
            print(f"  待删样本（前 {min(args.show_samples, n)} 条）：")
            ph = ",".join("?" * min(args.show_samples, n))
            for r in conn.execute(
                f"SELECT id, document_id, doc_name, length(text), substr(text,1,58) "
                f"FROM knowledge_chunks WHERE id IN ({ph})", junk_ids[: args.show_samples]
            ):
                print(f"    id={r[0]:<7} doc={r[1]:<6} len={str(r[3]):<6} "
                      f"{str(r[4])[:44]!r}")
        print()

        if not args.apply:
            print(f">>> DRY-RUN 结束，未做任何改动。")
            print(f">>>   删除 {n} 行（约 {n * 100.0 / max(before['knowledge_chunks'], 1):.1f}%，全是纯垃圾）")
            print(f">>>   截尾 {len(truncates)} 行（保住正文，只去掉尾部引流水印）")
            print(">>> 确认无误后加 --apply 执行（会自动先备份）。")
            return 0

        if n == 0 and not truncates:
            print(">>> 无需清理。")
            return 0

        bk = args.backup or (args.db + ".junk.bak")
        print(f">>> 备份中（SQLite backup() API）→ {bk}")
        backup_db(args.db, bk)
        print(f">>> 备份完成（{os.path.getsize(bk) / 1e6:.1f} MB）")

        # --- 1) 截尾：保留正文，去掉尾部水印（同步 FTS 内容）---
        trunc_done = 0
        for cid, body in truncates:
            cur_upd = conn.execute(
                "UPDATE knowledge_chunks SET text=? WHERE id=?", (body, cid)
            )
            if cur_upd.rowcount:
                try:
                    conn.execute(
                        "UPDATE knowledge_chunks_fts SET content=? WHERE chunk_id=?",
                        (body, cid),
                    )
                except sqlite3.Error:
                    pass
                trunc_done += 1

        # --- 2) 整块删除纯垃圾 ---
        dep_done: dict[str, Any] = {}
        if n:
            # 物理删除闸门：knowledge_chunks 物理删除不可逆。垃圾块判定
            # 误判会直接吃掉真实知识内容，必须显式放行。
            require_physical_delete_enabled("knowledge_chunks")
            ph = ",".join("?" * n)
            for t in DEP_TABLES:
                try:
                    dep_done[t] = conn.execute(
                        f"DELETE FROM {t} WHERE chunk_id IN ({ph})", junk_ids
                    ).rowcount
                except sqlite3.Error as e:
                    dep_done[t] = f"SKIP({e})"
            deleted = conn.execute(
                f"DELETE FROM knowledge_chunks WHERE id IN ({ph})", junk_ids
            ).rowcount
        else:
            deleted = 0
        conn.commit()

        after = stats(conn)
        print(f">>> 已截尾 {trunc_done} 块（保住正文，剔除尾部水印）")
        print(f">>> 已删除 knowledge_chunks {deleted} 行（纯垃圾）")
        for t, v in dep_done.items():
            print(f"    {t:<24} {v}")
        print()
        print("  清理前后对比：")
        for k in before:
            b, a = before[k], after[k]
            if k.startswith("spam_"):
                flag = " ✓" if a == 0 else (" ↓" if a < b else " ✗未降")
                print(f"    {k:<20} {b:>7} → {a:>7}{flag}")
            else:
                print(f"    {k:<20} {b:>7} → {a:>7}  (减少 {b - a})")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())