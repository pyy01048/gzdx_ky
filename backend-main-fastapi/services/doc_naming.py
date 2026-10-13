"""文档显示名命名规则（#27）—— **全项目唯一实现**。

入库路径（上传 / 网盘 / 批量导入 / 知识库 / 目录监听）和存量批量脚本
（`scripts/rename_docs_dryrun.py`、`scripts/rename_docs_apply.py`）都从这里取规则，
避免「新导入用一套、存量补改名用另一套」的漂移。

为什么长这样（都是实测逼出来的，别改回「正文抽《书名》+作者+版次」）：
`smart_ingest.extract_metadata` 扫全文，而正文里的《》绝大多数是**引用**
（「因新版《全国硕士研究生招生考试英语（-）考试大纲》已明确…」），作者正则命中
句子片段，实测产出过 `《答案解析》 先总述了`、`…英语（-）考试大纲》 自己的观`。
全库 2611 篇里文件名本身含《书名》的只有 51 篇。所以口径收敛成三条硬约束：

1. **只降低信息名**：剥掉 微信图片_/IMG_/扫描件_/时间戳 后中文 <4 字、拉丁词 <4，
   且没有年份（或年份只是残渣）才动手 —— 已经看得懂的名字不碰。
2. **只加不减**：原名有效部分当锚点留在前面，正文标题行追加在后面；同章节锚点自动去重。
   改名永远不会把「1998-2012年」「834考纲」这类既有信息弄丢。
3. **标题行必须逐字来自正文**，且过闸门：4–30 字、无句读/顿号、括号配对、
   不是选项题干（`A、` `答案：`）/图注（`图 9-1`）/分页标记（`--- 第 2 页 ---`）/
   APP 残渣（`新建试卷` `- PowerPoint`），并命中章节词或形态词。OCR 乱码行过不了这道闸。

改名只动显示名：`file_path` 与磁盘文件名一律不动，#26 的
`GET /api/documents/{id}/raw|download` 靠 `file_path` 定位原文。
"""
from __future__ import annotations

import os
import re
from typing import Dict, Optional, Tuple

#: Windows 显示名里不能出现的字符（含 OCR 正文里可能带进来的 C0 控制字符）
ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
#: 列表页一行的可读上限（Documents.jsx 现有列宽）
MAX_LEN = 60

#: 导入器留下的无语义前缀 / 时间戳，判「低信息名」前先剥掉
JUNK_PREFIX = re.compile(
    r"^(微信图片|wechat_temp|mmexport|IMG_|Screenshot|截图|扫描件|未命名|新建文件?|document|file)", re.I)
STAMP = re.compile(r"20\d{6,12}")
CJK = re.compile(r"[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-z]{4,}")
YEAR = re.compile(r"(?:19|20)\d{2}")

FORM = (r"真题|答案|解析|讲解|精讲|讲义|笔记|大纲|考纲|指南|教材|课件|习题|练习|月考"
        r"|模拟|模考|预测|冲刺|背诵|考点|单词|作文|阅读|翻译|套卷|试题|试卷|题库|手册"
        r"|全书|总结|导图|复习|指导|细解|逐句|逐题")
CHAPTER = r"第\s*[0-9０-９一二三四五六七八九十百]{1,3}\s*[章节讲部篇]"
FORM_RE = re.compile(FORM)
CHAPTER_RE = re.compile(CHAPTER)
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9}

#: 一眼就不是标题的行：选项题干、问答句、图注、列表序号、分页标记、APP 残渣、网页残渣
DENY = re.compile(
    r"(^[A-Ha-h][、.．\)])"          # A、B. 选项
    r"|(、)"                        # 顿号 = 并列句，不是标题
    r"|[。！？；;]"                 # 句读
    r"|(答案[：:])|(解析[：:])"
    r"|(^\W{0,3}(简述|试述|说明|请|为什么|如何|分析))"
    r"|(^\s*图\s*\d)|(^\s*表\s*\d)|(^\s*\d+\s*[)）.、])"
    r"|(^\s*[-—–])|(第\s*\d+\s*页)"  # 分隔线 / 「--- 第 1 页 ---」
    r"|(新建|登录|开通|会员|下载|扫一扫|二维码|水印|PowerPoint|WPS|OneNote|微信|文库|APP)"
    # 解析失败时各入库点写的占位串，绝不能反过来当标题来源
    r"|(未能提取到文本内容|文件缺失|未识别|未命名)"
    r"|(img |src=|width=|\.jpg|\.png|\.gif|https?://)", re.I)


def sanitize(name: str) -> str:
    name = ILLEGAL.sub(" ", name)
    return re.sub(r"\s{2,}", " ", name).strip()


def is_bracket_balanced(s: str) -> bool:
    for a, b in (("（", "）"), ("(", ")"), ("《", "》"), ("[", "]"), ("【", "】")):
        if s.count(a) != s.count(b):
            return False
    return True


def chapter_num(s: str) -> Optional[int]:
    """把「第N章/节」里的 N 归一成整数，用于识别锚点与标题是否同一章。"""
    m = CHAPTER_RE.search(s or "")
    if not m:
        return None
    tok = re.search(r"[0-9０-９]+|[一二三四五六七八九十]+", m.group(0))
    if not tok:
        return None
    t = tok.group(0).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if t.isdigit():
        return int(t)
    if t == "十":
        return 10
    if t.startswith("十"):
        return 10 + CN_NUM.get(t[1], 0)
    if t.endswith("十"):
        return CN_NUM.get(t[0], 0) * 10
    if "十" in t:
        return CN_NUM.get(t[0], 0) * 10 + CN_NUM.get(t[-1], 0)
    return CN_NUM.get(t)


def is_low_info(file_name: str) -> bool:
    """剥前缀/时间戳后：中文 <4 字且拉丁词 <4 → 现名没有信息量。

    年份单独算信息（`1998-2012年.pdf` 别再动它），但年份如果只是
    `扫描件_2026` 这类导入器残渣剩下的唯一内容，那仍然算没名字。
    """
    stem = os.path.splitext(file_name or "")[0]
    stripped = JUNK_PREFIX.sub("", stem)
    had_junk_prefix = stripped != stem
    stripped = STAMP.sub("", stripped)
    if len(CJK.findall(stripped)) >= 4:
        return False
    if LATIN.search(stripped):
        return False
    if YEAR.search(stripped) and not had_junk_prefix:
        return False
    return True


def anchor_of(file_name: str) -> str:
    """原名里能留下的锚点（只加不减）：先剥导入器残渣，剩下的才算信息。

    「微信图片_20260610234957_52_695」直接当锚点会产出
    `微信图片_20260610234 第三节 若干常用的组合逻辑电路` —— 锚点本身是垃圾，
    所以这里和 `is_low_info` 用同一套剥除口径，剥完没信息就没有锚点。
    """
    stem = sanitize(os.path.splitext(file_name or "")[0]).strip("-_.、 ")
    core = STAMP.sub("", JUNK_PREFIX.sub("", stem)).strip("-_.、 ")
    if not core or re.fullmatch(r"[\d\s\-_.（）()【】\[\]]{0,12}", core):
        return ""
    if len(CJK.findall(core)) < 2 and not LATIN.search(core) and not CHAPTER_RE.search(core):
        return ""
    return core[:16]


def head_title(text: str) -> Optional[Tuple[str, str]]:
    """取正文里第一行「像标题」的行，返回 (原文行, 清洗后行)；取不到返回 None。

    命名只用清洗后行，但原文行才是可核验依据 —— 逐字来自正文，只允许空白折叠和
    Windows 非法字符替换，不做任何改写或补全。
    """
    for raw in (text or "")[:1500].splitlines():
        s = raw.strip().strip("　•·*_#>】〕〗")
        if not (4 <= len(s) <= 30):
            continue
        if DENY.search(s) or not is_bracket_balanced(s):
            continue
        if not CJK.search(s):
            continue
        return raw.strip(), sanitize(s)
    return None


def propose(file_name: str, text: str) -> Dict[str, str]:
    """返回 {"proposed","anchor","basis","verbatim"} 或 {"reason":..., 可选 "note"}。"""
    file_name = file_name or ""
    if "《" in file_name:
        return {"reason": "现名已含《书名》，不改"}
    if not is_low_info(file_name):
        return {"reason": "现名已能看懂（中文/英文/年份标识足够），不改"}
    if not text:
        return {"reason": "正文为空（未解析或解析失败），无依据可改"}

    anchor = anchor_of(file_name)
    hit = head_title(text)
    if not hit:
        return {"reason": "正文首行不像标题（超长/含句读/选项题干/乱码），不改"}
    raw, title = hit
    if not (CHAPTER_RE.search(title) or FORM_RE.search(title) or CHAPTER_RE.search(anchor)):
        return {"reason": "标题行无章节词/形态词，不敢断定是标题", "note": title}

    dup_chapter = (CHAPTER_RE.search(anchor) is not None
                   and chapter_num(anchor) == chapter_num(title))
    if anchor and anchor not in title and not dup_chapter:
        full = sanitize(f"{anchor} {title}")
    else:
        full = title
    if len(full) > MAX_LEN:
        full = _clip(f"{anchor} {title}" if anchor and not dup_chapter else title)

    ext = os.path.splitext(file_name)[1]
    proposed = full + ext
    if proposed == file_name:
        return {"reason": "拟改名与现名一致"}
    basis = "/".join(x.group(0) for x in
                     [CHAPTER_RE.search(title) or CHAPTER_RE.search(proposed),
                      FORM_RE.search(title)] if x)
    return {"proposed": proposed, "anchor": anchor, "basis": basis,
            "verbatim": "yes" if raw == title else "yes（已折叠空白/替换非法字符）",
            "reason": ""}


def _clip(name: str) -> str:
    """超长时按词边界截，绝不把扩展名截掉、也不留半个词。"""
    stem, ext = os.path.splitext(name)
    budget = MAX_LEN - len(ext)
    if len(stem) <= budget:
        return stem + ext
    cut = stem[:budget]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return (cut or stem[:budget].rstrip()).rstrip() + ext


def auto_rename(file_name: str, text: str, taken_names=None) -> Optional[str]:
    """该改名就返回新名，否则返回 None。

    `taken_names(name) -> bool` 用于撞车判定：批量脚本可以交人判，自动入库路径没有
    人可问，撞车只能保持原名。
    """
    got = propose(file_name, text)
    if got.get("reason"):
        return None
    name = got["proposed"]
    if taken_names is not None and taken_names(name):
        return None
    return name


def apply_display_name(db, doc, text) -> str:
    """入库路径的统一调用点：正文刚落库时按规则定显示名，返回最终名字。

    规则不达标或撞库里已有名字 → **保持原名**（自动入库没有人可问，宁可不改）。
    只改 `doc.file_name`，绝不动 `doc.file_path`；若该文档已有分块，同事务写穿
    `knowledge_chunks.doc_name`，免得答疑引用（`ai_service` 用 `c.doc_name`）挂旧名。
    调用方负责 commit。
    """
    from sqlalchemy import func

    from models import Document, KnowledgeChunk

    current = doc.file_name or ""
    new = auto_rename(current, text, taken_names=lambda n: db.query(Document.id).filter(
        func.lower(Document.file_name) == n.lower(), Document.id != doc.id).first() is not None)
    if not new:
        return current
    doc.file_name = new
    if doc.id:
        # synchronize_session="fetch"：bulk UPDATE 会绕过 SQLAlchemy 身份映射，
        # 用 False 时若会话里已躺着同一文档的分块实例，它随后 flush 会把旧
        # doc_name 写回去，静默抵消这次写穿。
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).update(
            {KnowledgeChunk.doc_name: new}, synchronize_session="fetch")
    return new
