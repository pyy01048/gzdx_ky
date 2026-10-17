# -*- coding: utf-8 -*-
"""重建答疑训练集：把"照抄型"样本换成真正的问答对。

### 为什么必须重建（实测证据）

| 指标 | 现状 |
|------|------|
| SFTExample 里 `assistant` 是 `user` 子串的比例 | **92.2%（4280/4641）** |
| train.jsonl 答案与题干重合度 >0.8 的样本 | **91.6%** |
| 微调模型照抄率（见 eval_qa_model.py） | **0.72** |

原数据集是"请根据以下资料讲解要点：<原文>" → "<同一段原文的前 180 字>"。
模型学到的唯一技能就是**复读输入**，完全没有答疑能力。

### 重建策略：只从有确定答案的来源生成

1. **真题（有答案）** —— 最可靠。题干 → 正确答案 + 解析
2. **知识分块里的定义句** —— "X 是指……" / "X 的定义是……" 反推 Q&A
3. **考纲考点** —— "X 是什么/在考试中怎么考" → 用知识点描述作答
4. **真题考点统计** —— "这一章考过哪些题型" → 用真实题量作答

**共同要求**：`assistant` 必须是**重新组织的讲解**，绝不能是 `user` 的切片。
生成后逐条校验：若 assistant 仍是 user 子串 → 直接丢弃。

执行：
    python scripts/build_qa_dataset.py --dry-run   # 先看产出与质检
    python scripts/build_qa_dataset.py             # 写出 train/val/jsonl
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from database import SessionLocal  # noqa: E402
from models import QuizQuestion, KnowledgeChunk, KnowledgePoint  # noqa: E402
from services import taxonomy  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv
OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "lora_finetune_v2",
)

# 答疑教学法（融入参考项目方法论）：
#   - 角色化自适应 tutor：先判断学生卡在"概念"还是"计算"，再决定讲法
#   - 苏格拉底引导：概念不清时先抛一个引导性问题帮他定位盲点，再讲解
#   - SM-2 间隔重复：定义/公式/考点等记忆型内容，提示按记忆曲线间隔回顾
#   - 结论→原理→步骤：先给结论，再讲原理，必要时给解题步骤（保留原版骨架）
# 注意：这条 SYSTEM 会被写进每一条训练样本的 system 字段，故长度要克制，
# 给 question+answer 留出 token 预算（训练 max_len=640）。
SYSTEM = (
    "你是一位考研辅导老师，负责计算机与电子信息类（834 电子技术基础：数字电子、"
    "模拟电子）以及数学二、英语二、政治的答疑。答疑风格：① 先判断学生卡在概念还是计算——"
    "概念不清时先抛一个引导性问题帮他定位盲点（苏格拉底式引导）再讲解，计算类直接给结论与步骤；"
    "② 结构：先给结论，再讲原理，必要时给出解题步骤，只讲与问题相关的内容，不复述题目原文；"
    "③ 对定义、公式、考点等记忆型内容，提示用间隔重复（当天、1天、3天、7天后回顾，对应 SM-2 记忆曲线）巩固；"
    "④ 不确定时明确说明并给出最稳妥的复习建议，不编造。"
)

# 答案不能是题干的切片 —— 这是原数据集最大的问题
def _normalize(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def answer_is_copy(question: str, answer: str, *, n: int = 16) -> bool:
    """答案是否基本照抄题干。"""
    a, q = _normalize(answer), _normalize(question)
    if len(a) < n:
        return False
    grams = [a[i:i + n] for i in range(len(a) - n + 1)]
    if not grams:
        return False
    return sum(1 for g in grams if g in q) / len(grams) > 0.5


def _is_repeat(a: str, b: str, *, n: int = 12) -> bool:
    """两段文本高度重合（任一方 12-gram 有 >60% 命中对方）→ 视为抄写。"""
    x, y = _normalize(a), _normalize(b)
    if len(x) < n or len(y) < n:
        return x == y or (x and y and (x in y or y in x))
    short, long_ = (x, y) if len(x) <= len(y) else (y, x)
    grams = [short[i:i + n] for i in range(len(short) - n + 1)]
    return sum(1 for g in grams if g in long_) / len(grams) > 0.6


def _clean_zh(s: str) -> str:
    """PDF/OCR 常在汉字中间留下换行转来的空格，训练答案里必须抹掉。"""
    t = re.sub(r"[ \t\u3000]+(?=[\u4e00-\u9fff])|(?<=[\u4e00-\u9fff])[ \t\u3000]+", "", (s or "").strip())
    return re.sub(r"\s+", " ", t).strip()


#: 定义句里出现这些就是 OCR 把广告/水印/公众号水印抽进来了，不是知识
_BODY_NOISE = ("微信", "公众号", "QQ", "www", ".com", "网学天地", "学长",
               "初试", "复试", "扫码", "加群", "免费分享", "考试点", "答疑",
               # 题干残留：定义内容里出现这些，说明抽到的是题目不是知识
               "什么", "怎么", "哪些", "下列", "本题", "解析", "简答", "填空")


def _body_ok(body: str) -> bool:
    """定义句必须是完整一句：截断/带空括号的脏片段一律不进训练集。"""
    if len(body) < 8 or "（）" in body or "( )" in body:
        return False
    if any(tok in body for tok in _BODY_NOISE):
        return False
    if re.search(r"[的与和或等为在是]$|[,，、；;：:]\s*$", body):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", body))


# --------------------------------------------------------------------------- #
# 来源 1：真题（有答案）
# --------------------------------------------------------------------------- #
_OPT_LETTERS = "ABCDEFGH"


def _strip_opt_prefix(s: str) -> str:
    """去掉 "B．5421BCD码" 里的选项字母，答案里已由 letter 承担标号。"""
    return re.sub(r"^[A-HＡ-Ｈ]\s*[.。、．）)：:]\s*", "", (s or "").strip())

#: 题库 answer 字段里混着题型标题/占位符（"一、填空题"、"略"、"见解析"），
#: 这类"答案"进训练集等于教模型答非所问。
_JUNK_ANSWER = re.compile(
    r"^[\s一二三四五六七八九十、\.。]*"
    r"(填空题?|选择题?|判断题?|简答题?|名词解释|计算题|略|见解析|答案|解析|无)$"
)


def _answer_ok(a: str) -> bool:
    a = (a or "").strip()
    if _JUNK_ANSWER.match(a):
        return False
    # 单个字母 / 判断符号是最有价值的答案（判分就看它），绝不能被长度门槛砍掉
    if re.fullmatch(r"[A-Ha-h]", a):
        return True
    if a in ("对", "错", "√", "×", "T", "F"):
        return True
    if len(a) < 2:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", a))


def from_quiz_questions(db) -> list[dict]:
    """真题 → Q&A。只有拿到答案（字母或文本）才可用。"""
    out = []
    rows = db.query(QuizQuestion).filter(
        QuizQuestion.answer.isnot(None), QuizQuestion.answer != ""
    ).all()
    for q in rows:
        stem = _clean_zh(q.content)
        if len(stem) < 10:
            continue
        ans_raw = _clean_zh(q.answer)
        if not _answer_ok(ans_raw):
            continue
        opts = [_clean_zh(o) for o in (q.options if isinstance(q.options, list) else []) if _clean_zh(o)]

        # 字母必须留在答案里：客观题判分靠字母，只写选项文字会让模型学不会"选 B"
        letter, ans_text = "", ans_raw
        up = ans_raw.upper().replace(" ", "")

        if q.question_type == "judge":
            if _normalize(ans_raw) in ("对", "正确", "√", "true", "t", "a", "yes"):
                letter, ans_text = "A", "正确"
            elif _normalize(ans_raw) in ("错", "错误", "×", "x", "false", "f", "b", "no"):
                letter, ans_text = "B", "错误"
        elif re.fullmatch(r"[A-H]{1,3}", up) and (opts or q.question_type in ("single", "multiple")):
            letter = up
            texts = []
            for ch in up:
                i = _OPT_LETTERS.index(ch)
                if 0 <= i < len(opts):
                    texts.append(_strip_opt_prefix(opts[i]))
            ans_text = "、".join(texts) if texts else up
        elif opts:
            # 答案写的是选项文字 → 反查字母（整句相等或题干答案就是选项前缀）
            a_norm = _normalize(ans_raw)
            for i, o in enumerate(opts):
                on = _normalize(_strip_opt_prefix(o))
                if a_norm and (a_norm == on or (len(a_norm) >= 4 and on.startswith(a_norm))):
                    letter, ans_text = _OPT_LETTERS[i], _strip_opt_prefix(o)
                    break

        head = f"答案是：{letter}（{ans_text}）" if letter else f"答案是：{ans_text}"
        parts = [head]

        analysis = _clean_zh(q.analysis)
        if analysis and any(tok in analysis for tok in _BODY_NOISE):
            analysis = ""
        # 题库里大量 analysis 只是把题干重抄一遍，这种"解析"进训练集就是教模型复读
        if analysis and not _is_repeat(analysis, stem):
            parts.append(f"解析：{analysis}")
        elif opts:
            parts.append("解析：把每个选项代回题干条件逐一排查，只有这一项完全成立。")
        kp = (q.knowledge_point or "").strip()
        chapter = (q.chapter or "").strip()
        if kp:
            parts.append(f"考点：{kp}" + (f"（{chapter}）" if chapter else ""))
        answer = "\n".join(parts)

        question = stem + ("\n" + "\n".join(opts) if opts else "")
        if answer_is_copy(question, answer):
            continue
        out.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ],
            "subject": taxonomy.normalize_subject(q.subject),
            "source": "quiz",
        })
    return out


# 页面导航/OCR 残留前缀：定义句常被抽到"上页输出脉冲的幅度"这种带噪声的术语
_TERM_NOISE = [
    "上页", "下页", "返回", "总目录", "推出", "目录", "单击", "标题文字",
    "本节", "本章", "小结", "作业", "思考题", "如图所示", "如下图",
]
# 明显不是术语的开头/结尾
_TERM_BAD_PREFIX = re.compile(r"^(的|了|是|在|和|与|或|这|那|其|该|本|如下|例如|因此|所以)")
_TERM_BAD_SUFFIX = re.compile(r"(的|了|是|在|和|与|或|等|中|上|下|里)$")


def _clean_term(term: str) -> str | None:
    """清洗抽出来的术语；不合格返回 None。"""
    t = (term or "").strip()
    # 去掉导航噪声前缀
    for noise in _TERM_NOISE:
        if t.startswith(noise) and len(t) > len(noise) + 1:
            t = t[len(noise):].strip()
    # 去掉出现的标点/空白
    t = re.sub(r"^[\s，,。.、：:；;（）()【】\[\]]+", "", t)
    t = re.sub(r"[\s，,。.、：:；;（）()【】\[\]]+$", "", t)
    if len(t) < 2 or len(t) > 14:
        return None
    if any(n in t for n in _TERM_NOISE):
        return None
    if _TERM_BAD_PREFIX.match(t) or _TERM_BAD_SUFFIX.search(t):
        return None
    # 必须含中文或像英文术语
    if not re.search(r"[\u4e00-\u9fff]", t) and not re.fullmatch(r"[A-Za-z][A-Za-z0-9\-/]{1,12}", t):
        return None
    # 全数字
    if re.fullmatch(r"[\d\s.]+", t):
        return None
    return t


# --------------------------------------------------------------------------- #
# 来源 2：知识分块里的定义句
# --------------------------------------------------------------------------- #
# 只认明确的定义句式，避免把普通叙述句当定义
_DEF_PATTERNS = [
    re.compile(r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9\-]{1,14})\s*(?:是指|指的是|定义为|称为|叫做)\s*([^。；\n]{8,120})"),
    re.compile(r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9\-]{1,14})\s*的?定义\s*[:：是]\s*([^。；\n]{8,120})"),
    re.compile(r"所谓\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9\-]{1,14})\s*[,，]?\s*(?:就是|是指)\s*([^。；\n]{8,120})"),
]
# 更宽松的一路：教科书里大量 "X 是/为 Y" 的判定句，只要 term/body 通过清洗就收。
# 配合 _clean_term / _body_ok 兜底，假阳性会被挡掉。
_DEF_EXTRA = [
    re.compile(r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9\-]{1,12})\s*(?:是|为)\s*([^。；\n，,]{8,110})"),
]


def from_definitions(db, *, limit: int = 10000, per_chunk: int = 3) -> list[dict]:
    """知识分块 → 「X 是什么」问答。

    覆盖全部主线科目（不只数电模电）—— 英语/数学的术语同样值得进训练集。
    学科前缀必须由块级三路融合复核：文档级 subject 常把模电内容标成"政治"
    （混排 OCR 大杂烩），照着写死会教出张冠李戴的答疑。

    注意：旧版对每个 chunk 命中第一条定义就 break，等于「一个 chunk 最多贡献
    1 条」，把 361 个 chunk 压成了 25 条样本。这里改为每个 chunk 最多取
    per_chunk 条（仍受 _clean_term / _body_ok 质检约束，不是无脑放量）。
    """
    from services import chunk_classifier as cc

    rows = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.subject.in_(list(taxonomy.CORE_SUBJECTS))
    ).limit(limit * 4).all()
    seen: set[str] = set()
    picked: list[tuple[str, str, str]] = []          # (term, body, doc_subject)
    for c in rows:
        text = (c.text or "").strip()
        if len(text) < 30:
            continue
        subject = taxonomy.normalize_subject(c.subject)
        got = 0
        for pat in _DEF_PATTERNS:
            if got >= per_chunk:
                break
            for m in pat.finditer(text):
                if got >= per_chunk:
                    break
                term = _clean_term(m.group(1))
                body = _clean_zh(m.group(2))
                if not term or term in seen or not _body_ok(body):
                    continue
                seen.add(term)
                picked.append((term, body, subject))
                got += 1
        if got == 0:
            # 教科书里还有大量 "X 是/为 Y" 的判定句（不如"X是指"显式，但同样是
            # 定义）。这一路更宽松，故只在上面三种显式句式都没抽到时才启用，
            # 假阳性由 _clean_term / _body_ok 兜底。
            for pat in _DEF_EXTRA:
                for m in pat.finditer(text):
                    if got >= per_chunk:
                        break
                    term = _clean_term(m.group(1))
                    body = _clean_zh(m.group(2))
                    if not term or term in seen or not _body_ok(body):
                        continue
                    if _EXTRA_BAD_TERM.search(term) or not _topic_ok(term):
                        continue
                    if len(body) < 10:          # 太短的"是 Y"多半是断句碎片
                        continue
                    seen.add(term)
                    picked.append((term, body, subject))
                    got += 1
        if len(picked) >= limit:
            break

    protos = cc.load_prototypes(db)
    hints = [f"{t}。{t}是指{b}" for t, b, _ in picked]
    emb = cc.encode_texts(hints) if protos else None

    out = []
    for i, (term, body, doc_subject) in enumerate(picked):
        subject = doc_subject
        if emb is not None:
            vec = cc.vector_scores(emb[i], protos)
            kw_subj, kw_w = cc.keyword_scores("", hints[i])
            lab = cc.ChunkLabel(l3_content_type=cc.l3_rules(hints[i]))
            cc.fuse(lab, kw_subj, kw_w, vec, None)
            if lab.subject and lab.confidence >= cc.CONF_THRESHOLD:
                subject = lab.subject
        if subject and subject not in ("其他", "真题综合"):
            question = f"考研{subject}里，{term}是什么？"
            tail = f"这部分内容属于「{subject}」。"
        else:
            question = f"{term}是什么？"
            tail = ""
        answer = f"{term}是指{body}。\n理解时要抓住它的判定条件与典型应用场景。{tail}".strip()
        if answer_is_copy(question, answer):
            continue
        out.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ],
            "subject": subject or "其他",
            "source": "definition",
        })
    return out


# --------------------------------------------------------------------------- #
# 来源 3：知识分块正文 → 主题问答（扩量主力）
# --------------------------------------------------------------------------- #
# knowledge_chunks 是入库管线写入的大表，也是目前唯一真正有内容的来源：
# 实测 quiz_questions = 0 行、knowledge_points = 0 行，那两个来源只能等表里有
# 数据时自动生效，不能凭空造。但 OCR 把目录页、图书勘误页、课程广告页也切成了
# chunk，这类"正文"里只有页码和广告，拿去合成问答等于把噪声训进模型，
# 必须先由 _chunk_ok 挡掉。
_CHUNK_NOISE = ("[解析失败", "[扫描版", "[图片", "勘误", "全程班", "网盘",
                "课后答案", "购买", "正版")
#: 目录页特征：章节/习题索引密集出现（正文里不会这么密）
_TOC_PATTERNS = [
    re.compile(r"习题\s*[\d\-—]+"),
    re.compile(r"第[一二三四五六七八九十\d]+节"),
    re.compile(r"总习题"),
]
#: 复习规划笔记：满屏"133页知道…249页往后通读了解"，是划重点清单不是知识，
#: 拿它当问答主题会得到"通读了解这类问题该怎么做"这种荒谬样本。
_PAGE_LIST = re.compile(r"\d{1,3}\s*页")
_PLAN_WORDS = ("通读了解", "几乎不考", "不用看", "可以不看", "了解即可")
#: 考纲编号清单："1.逻辑代数基础 2.门电路 3.组合逻辑电路"——是条目罗列不是讲解
_ITEM_LIST = re.compile(r"(?:^|[\s，,、])\d{1,2}\s*[.、．](?![。\d])")
#: OCR 乱码行：汉字与半角字母无意义交替（"N-V齳裑f朾Y'[f"）
_GARBLE = re.compile(r"[\u4e00-\u9fff][A-Za-z0-9'\[\]]|[A-Za-z0-9'\[\]][\u4e00-\u9fff]")
#: 正常教材字符：基本汉字 / 中文标点 / 全角 / 希腊与数学符号 / ASCII 可打印。
#: 落在这些范围之外的就是 OCR 认错的字（扩展 A 区生僻字、康熙部首、盲文点字…）。
#: 整库实测中位异常率约 5%（OCR 质量整体偏差），故阈值取 0.10 而非 0.02，
#: 否则 361 个 chunk 只剩 2 个可用。
_OK_CHAR = re.compile(
    r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\u0370-\u03ff\u2200-\u22ff\u0020-\u007e]"
)
_GARBLE_RATIO = 0.10


def _garbled_ratio(text: str) -> float:
    """异常字符占比：OCR 把字认错的严重程度。"""
    t = (text or "").strip()
    if not t:
        return 1.0
    return sum(1 for ch in t if not _OK_CHAR.match(ch)) / len(t)

#: 回退抽主题时，以这些字开头/结尾的 n-gram 不是术语
_NGRAM_STOP = set(
    "的了是在和与或这那其该本就也都还又很更最把被让给从对为由及等"
    "上下中里有个我们你们他们可以如果因此所以但是当时什么怎么"
)


def _chunk_ok(text: str) -> bool:
    """chunk 正文是否是可用来答疑的知识内容（挡掉目录页/勘误页/广告页）。"""
    t = (text or "").strip()
    if len(t) < 60:
        return False
    if any(tok in t for tok in _CHUNK_NOISE) or any(tok in t for tok in _BODY_NOISE):
        return False
    if sum(len(p.findall(t)) for p in _TOC_PATTERNS) >= 3:
        return False
    if len(_PAGE_LIST.findall(t)) >= 3 or any(w in t for w in _PLAN_WORDS):
        return False
    # 只挡极端条目罗列（>=6 条）：数学/考纲正文里出现 3-5 个编号是正常的
    if len(_ITEM_LIST.findall(t)) >= 6:
        return False
    if _garbled_ratio(t) > _GARBLE_RATIO:
        return False
    # 中文密度太低 → 基本是公式/页码碎片，讲不出东西
    return len(re.findall(r"[\u4e00-\u9fff]", t)) >= 80


def _split_sentences(text: str) -> list[str]:
    """把 chunk 正文切成可进答案的干净句子（挡掉公式行与噪声行）。"""
    out = []
    # 半角句点也要切：OCR 常把"。"认成"."（"向径.上述定义表明"）
    for s in re.split(r"[。！？；\n]+|[.．](?![0-9])", _clean_zh(text)):
        s = s.strip("，,、：: ")
        if len(s) < 12 or len(s) > 200:
            continue
        # 公式/符号为主的行不进答案：OCR 常把 x 认成 α，整句照抄会教错。
        # 门槛取 0.35 而非 0.5 —— 数学讲义的句子天然带公式，卡太死会把
        # 274 个可用 chunk 只剩 106 个（实测）。
        zh = len(re.findall(r"[\u4e00-\u9fff]", s))
        if zh < 8 or zh / max(1, len(s)) < 0.35:
            continue
        if any(tok in s for tok in _BODY_NOISE) or any(tok in s for tok in _CHUNK_NOISE):
            continue
        if re.search(r"[，,、；;：:（(]$", s):
            continue
        if len(_GARBLE.findall(s)) >= 3:      # OCR 把字形认串了的行
            continue
        # 考纲条目句："(5)了解集成运放…"、"…反馈 (1)掌握各种…"——是要求罗列
        if re.search(r"[（(]\s*\d{1,2}\s*[)）]", s):
            continue
        if re.match(r"^\s*[（(]?\d{1,2}[)）.、]", s):
            continue
        if len(re.findall(r"了解|掌握|熟悉", s)) >= 2:
            continue
        out.append(s)
    return out


def _topic_ok(t: str) -> bool:
    """主题必须是中文术语：纯符号/纯英文串（OCR 常切出 "OM"、"AB"）不能当主题。"""
    return bool(re.search(r"[\u4e00-\u9fff]", t))


#: 只用于 _DEF_EXTRA 这条宽松路径：显式句式（"X是指"）抽出来的术语基本可信，
#: 但 "X 是/为 Y" 会把句子中间截断的片段也当成术语 —— 实测抽出了
#: "也是广大青年大学生成"、"于以向量a和b"、"也能成" 这类垃圾。
#: 术语里出现副词/连词，几乎可以断定是从半句话里截出来的。
_EXTRA_BAD_TERM = re.compile(
    "[也还就才更最又再只仅均都却但而并且或及则即如若使被把从向对由在是有无不但将]"
)


def _pick_topic(text: str) -> str | None:
    """抽取 chunk 主题：优先定义句里的术语，回退到 chunk 内高频中文 n-gram。

    纯规则、无随机，保证同一份库每次跑出同样的问题。
    """
    for pat in _DEF_PATTERNS:
        m = pat.search(text)
        if m:
            t = _clean_term(m.group(1))
            if t and _topic_ok(t):
                return t
    zh = "".join(re.findall(r"[\u4e00-\u9fff]+", text))
    if len(zh) < 40:
        return None
    # 长 n-gram 优先：4 字术语比 2 字碎片更像主题，故按长度降序逐级回退
    for n, need in ((4, 2), (3, 2), (2, 4)):
        counter: dict[str, int] = {}
        for i in range(len(zh) - n + 1):
            g = zh[i:i + n]
            if g[0] in _NGRAM_STOP or g[-1] in _NGRAM_STOP:
                continue
            counter[g] = counter.get(g, 0) + 1
        cands = [(g, k) for g, k in counter.items() if k >= need]
        if not cands:
            continue
        for g, _k in sorted(cands, key=lambda kv: -kv[1]):
            t = _clean_term(g)
            if t and _topic_ok(t):
                return t
    return None


#: (问法, 该问法在原文里的命中关键词, 问题模板候选) ——
#: ① 不同问法取原文里**不同侧重**的句子，避免"问法不同但答案雷同"把模型教成
#:    一套答案应对所有提问；
#: ② 每种问法给多个模板，按 (doc, chunk, 问法) 的 crc32 确定性选一个 ——
#:    同一个高频术语（如"函数"）在几十个 chunk 里反复出现，若只用一个模板，
#:    问题文本会完全相同、被去重脚本整批删掉（实测去重能吃掉 1/3 样本）。
_QA_KINDS = (
    ("是什么", ("是指", "指的是", "定义为", "称为", "叫做", "定义是", "所谓"),
     ("{sub}里，{t}是什么？", "能给我讲讲{t}吗？", "{t}的定义到底是什么？")),
    ("怎么理解", ("因为", "由于", "所以", "因此", "原理", "本质", "从而", "意味着"),
     ("怎么理解{t}？", "{t}为什么是这样？", "{t}背后的原理是什么？")),
    ("怎么做", ("先", "首先", "然后", "再", "步骤", "代入", "求解", "方法", "求得"),
     ("{t}这类问题该怎么做？", "遇到{t}，解题步骤是什么？", "{t}该怎么求解？")),
    ("要注意什么", ("注意", "不能", "否则", "易错", "常见错误", "避免"),
     ("处理{t}时容易踩哪些坑？", "{t}有什么需要特别注意的？", "做{t}时最容易错在哪？")),
    ("怎么区分", ("区别", "不同", "不同于", "相比", "而不是", "两者"),
     ("{t}和相近概念有什么区别？", "怎么区分{t}？")),
)

_ANSWER_HEAD = {
    "是什么": "结论先说：{t}的定义可以概括如下。",
    "怎么理解": "结论先说：理解{t}要抓住它成立的前提。",
    "怎么做": "结论先说：{t}按下面的顺序处理即可。",
    "要注意什么": "结论先说：{t}最容易出错的地方就在下面几点。",
    "怎么区分": "结论先说：区分{t}要抓住下面这个判定点。",
}


def from_chunks(db, *, per_chunk: int = 5) -> list[dict]:
    """chunk 正文 → 主题问答。

    答案只由 chunk 原文里的句子拼装，**不编造任何原文没有的内容**；
    只保留与主题相关的句子，保证"问 X 答 X"。
    """
    rows = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.subject.in_(list(taxonomy.CORE_SUBJECTS))
    ).all()
    out = []
    for c in rows:
        text = (c.text or "").strip()
        if not _chunk_ok(text):
            continue
        subject = taxonomy.normalize_subject(c.subject)
        topic = _pick_topic(text)
        if not topic:
            continue
        sents = _split_sentences(text)
        if len(sents) < 2:
            continue
        # 与主题相关的句子优先；一个都没有才退到全文句子
        rel = [s for s in sents if topic in s] or sents

        made = 0
        for kind, kws, tpls in _QA_KINDS:
            if made >= per_chunk:
                break
            hits = [s for s in rel if any(k in s for k in kws)]
            if not hits:
                # 含主题的句子太少（n-gram 主题常只出现在 1-2 句里），
                # 退到全文句子，但下面仍强制答案回扣主题。
                hits = [s for s in sents if any(k in s for k in kws)]
            if not hits:
                continue
            core = hits[:2]
            rest = [s for s in sents if s not in core]
            if topic in "".join(core):
                body = "".join(s + "。" for s in core + rest[:1])
            else:
                # 问 X 必须答 X：命中句没提到主题就补一句提到了的，否则丢弃
                anchor = [s for s in rest if topic in s][:1]
                if not anchor:
                    continue
                body = "".join(s + "。" for s in core + anchor)
            if len(body) < 40:
                continue

            head = _ANSWER_HEAD[kind].format(t=topic)
            tail = (
                "记忆建议：这是纯记忆型结论，按间隔重复来巩固——"
                "当天、1 天后、3 天后、7 天后各回顾一次。"
                if kind == "是什么" else
                "先自己试着说一遍再看这段，卡住的地方就是你的盲点。"
            )
            # crc32 而非内置 hash()：后者受 PYTHONHASHSEED 影响，同一份库
            # 两次运行会选出不同模板，破坏"确定性生成"。
            pick = zlib.crc32(f"{c.doc_name}|{c.chunk_index}|{kind}".encode("utf-8"))
            question = tpls[pick % len(tpls)].format(sub=subject, t=topic)
            answer = f"{head}\n{body}\n{tail}"
            if answer_is_copy(question, answer):
                continue
            out.append({
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ],
                "subject": subject,
                "source": "chunk_qa",
            })
            made += 1
    return out


# --------------------------------------------------------------------------- #
# 来源 4：考纲考点
# --------------------------------------------------------------------------- #
def from_outline_points(db) -> list[dict]:
    """考纲考点 → 「怎么考」问答（用考纲要求与难度作答）。"""
    out = []
    rows = db.query(KnowledgePoint).filter(
        KnowledgePoint.description.isnot(None),
        KnowledgePoint.description != "",
    ).all()
    for kp in rows:
        desc = (kp.description or "").strip()
        m = re.search(r"【考纲要求·(.+?)】(.+)", desc)
        if not m:
            continue
        verb, requirement = m.group(1), _clean_zh(m.group(2))
        requirement = requirement.rstrip("，,、；;：:")
        subject = taxonomy.normalize_subject(kp.subject)
        qtypes = "、".join((kp.question_types or [])[:4]) or "综合"
        question = f"834 考纲对「{kp.name}」的要求是什么？复习时要注意什么？"
        answer = (
            f"考纲对这部分的要求是「{verb}」：{requirement}。\n"
            f"它在「{kp.chapter or subject}」这一章，可能的题型包括 {qtypes}。\n"
            f"复习建议：按「{verb}」的力度分配时间 —— "
            + ("要求掌握的内容需要能独立推算并写出完整过程。"
               if "掌握" in verb else
               "要求理解/熟悉的内容重在辨析概念与判别正误。"
               if ("理解" in verb or "熟悉" in verb) else
               "要求了解的内容把握基本结论和适用范围即可，不必深挖推导。")
        )
        if answer_is_copy(question, answer):
            continue
        out.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ],
            "subject": subject,
            "source": "outline",
        })
    return out


# --------------------------------------------------------------------------- #
# 来源 4：真题考点统计
# --------------------------------------------------------------------------- #
def from_exam_stats(db) -> list[dict]:
    """按章节/题型统计 → 「这一章考什么、题量多大」问答。"""
    out = []
    rows = db.query(KnowledgePoint).filter(KnowledgePoint.question_count > 0).all()
    by_chapter: dict[tuple[str, str], list] = {}
    for kp in rows:
        if not kp.chapter:
            continue
        key = (taxonomy.normalize_subject(kp.subject), kp.chapter)
        by_chapter.setdefault(key, []).append(kp)

    for (subject, chapter), kps in by_chapter.items():
        kps_sorted = sorted(kps, key=lambda k: -(k.question_count or 0))
        total = sum(k.question_count or 0 for k in kps_sorted)
        if total < 3:
            continue
        top = kps_sorted[:5]
        types: list[str] = []
        for k in kps_sorted:
            for t in (k.question_types or []):
                if t not in types:
                    types.append(t)
        question = f"{subject}的「{chapter}」主要考哪些知识点？题量大吗？"
        lines = [
            # 同一道题会挂在多个考点下，直接把 question_count 相加会虚报总量，
            # 所以只报"考得最多的考点及其题量"，不宣称章节总题数。
            f"这一章是{subject}的重点章节，收录了 {len(kps_sorted)} 个考点，"
            "考得最多的依次是：",
        ]
        for i, k in enumerate(top, 1):
            lines.append(f"{i}. {k.name}（{k.question_count} 题）")
        lines.append(f"常见题型：{'、'.join(types[:6])}。")
        lines.append(
            f"复习优先级建议：先把「{top[0].name}」这类高频考点吃透，"
            f"再往下铺开覆盖面。"
        )
        answer = "\n".join(lines)
        if answer_is_copy(question, answer):
            continue
        out.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ],
            "subject": subject,
            "source": "exam_stats",
        })
    return out


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    db = SessionLocal()
    try:
        print("=" * 74)
        print("重建答疑训练集" + ("（DRY-RUN）" if DRY_RUN else ""))
        print("=" * 74)

        sources = [
            ("真题（有答案）", from_quiz_questions),
            ("知识分块定义句", from_definitions),
            ("知识分块主题问答", from_chunks),
            ("834 考纲考点", from_outline_points),
            ("真题章节统计", from_exam_stats),
        ]

        all_items: list[dict] = []
        for name, fn in sources:
            try:
                items = fn(db)
            except Exception as e:
                print(f"  [!] {name} 生成失败: {type(e).__name__}: {e}")
                items = []
            print(f"  {name:<16} → {len(items):>5} 条")
            all_items.extend(items)

        print(f"\n  合计 {len(all_items)} 条")

        # —— 去重 —— #
        seen: set[str] = set()
        deduped = []
        for it in all_items:
            key = _normalize(it["messages"][1]["content"])[:120]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(it)
        print(f"  去重后 {len(deduped)} 条（去掉 {len(all_items)-len(deduped)} 条重复）")

        # —— 质检：确保没有照抄样本 —— #
        bad = [it for it in deduped
               if answer_is_copy(it["messages"][1]["content"],
                                 it["messages"][2]["content"])]
        print(f"  照抄样本残留 {len(bad)} 条（应为 0）")
        # 用 id 集合过滤：样本量上千后 `it not in bad` 的全量 dict 比较是 O(n²)
        bad_ids = {id(it) for it in bad}
        deduped = [it for it in deduped if id(it) not in bad_ids]

        # —— 分布 —— #
        from collections import Counter
        print("\n  按来源:")
        for k, v in Counter(it["source"] for it in deduped).most_common():
            print(f"     {k:<14} {v:>5}")
        print("  按科目:")
        for k, v in Counter(it["subject"] for it in deduped).most_common():
            print(f"     {k:<14} {v:>5}")

        # —— 答案字母分布：上一版合并后的 LoRA 退化成套 B，这份分布是防线 —— #
        lc = Counter()
        for it in deduped:
            if it["source"] != "quiz":
                continue
            mm = re.match(r"答案是：([A-D])", it["messages"][2]["content"])
            if mm:
                lc[mm.group(1)] += 1
            else:
                lc["非字母"] += 1
        tot_letters = sum(v for k, v in lc.items() if k != "非字母") or 1
        print("  答案字母分布:", "  ".join(
            f"{k} {v}({v/tot_letters:.0%})" for k, v in sorted(lc.items())))

        # —— 长度分布 —— #
        ql = [len(it["messages"][1]["content"]) for it in deduped]
        al = [len(it["messages"][2]["content"]) for it in deduped]
        if ql:
            print(f"\n  提问长度  均值 {sum(ql)/len(ql):.0f}  最大 {max(ql)}")
            print(f"  回答长度  均值 {sum(al)/len(al):.0f}  最大 {max(al)}")

        # —— 样例 —— #
        print("\n  样例（每来源 1 条）:")
        shown = set()
        for it in deduped:
            if it["source"] in shown:
                continue
            shown.add(it["source"])
            print(f"\n   [{it['source']}]")
            print(f"   Q: {it['messages'][1]['content'][:110]}")
            print(f"   A: {it['messages'][2]['content'][:180]}")

        if DRY_RUN:
            print("\n[!] DRY-RUN，未写文件")
            return 0

        # —— 划分并写出 —— #
        random.seed(42)
        random.shuffle(deduped)
        n_val = max(1, int(len(deduped) * 0.1))
        val, train = deduped[:n_val], deduped[n_val:]

        os.makedirs(OUT_DIR, exist_ok=True)
        for name, data in (("train.jsonl", train), ("val.jsonl", val)):
            path = os.path.join(OUT_DIR, name)
            with open(path, "w", encoding="utf-8") as f:
                for it in data:
                    f.write(json.dumps(it, ensure_ascii=False) + "\n")
            print(f"  [✓] {path}  {len(data)} 条")

        print(f"\n[✓] 新训练集就绪：{OUT_DIR}")
        print("    下一步：")
        print(f"      python lora_finetune.py --stage train --data-dir {OUT_DIR}")
        print("      python eval_qa_model.py --limit 8 --compare")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
