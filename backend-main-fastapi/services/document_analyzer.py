# -*- coding: utf-8 -*-
"""文档智能分析服务（V2.0 新增）。

长文本识别 + 自动分类：
1. 超长文本智能分块（按章节/段落/句子，带重叠）
2. AI 自动识别知识点 → 存入 knowledge_points
3. AI 自动识别测试题/真题 → 分类存入 quiz_questions
4. 支持批量处理、进度回调、去重

这是实现"上传一份资料，自动生成知识库+题库"的核心服务。
"""
from __future__ import annotations

import re
import json
import logging
from typing import Optional, List, Dict, Any, Callable

from sqlalchemy.orm import Session

from models import Document, KnowledgePoint, QuizQuestion, KnowledgeChunk
from services.quiz_content_gate import admit as gate_admit
from services.quiz_content_gate import gate_log_summary
from services import quiz_dedupe

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 长文本智能分块
# --------------------------------------------------------------------------- #
def smart_chunk_text(
    text: str,
    max_chunk_size: int = 3000,
    overlap: int = 200,
    min_chunk_size: int = 200,
) -> List[Dict[str, Any]]:
    """智能分块：优先按章节标题，其次段落，最后句子。

    返回 [{index, text, start_pos, end_pos, heading}]
    """
    text = (text or "").strip()
    if not text:
        return []

    # 识别章节标题（支持多种格式）
    heading_patterns = [
        r'^第[一二三四五六七八九十百千\d]+[章节篇讲]\s*.*$',  # 第一章/第1节
        r'^\d+(\.\d+)*\s+[^\n]{2,50}$',  # 1.1 标题
        r'^[一二三四五六七八九十]+、[^\n]{2,50}$',  # 一、标题
        r'^【[^】]+】$',  # 【标题】
        r'^#{1,4}\s+.*$',  # Markdown 标题
    ]
    heading_re = re.compile('|'.join(heading_patterns), re.MULTILINE)

    # 按标题切分
    chunks = []
    current_heading = None
    current_start = 0
    matches = list(heading_re.finditer(text))

    if not matches:
        # 没有标题，按段落切分
        paragraphs = re.split(r'\n\s*\n', text)
        current = ""
        for i, para in enumerate(paragraphs):
            para = para.strip()
            if not para:
                continue
            if len(current) + len(para) <= max_chunk_size:
                current = (current + "\n\n" + para).strip() if current else para
            else:
                if current:
                    chunks.append({"text": current, "heading": None})
                # 超长段落按句子切分
                if len(para) > max_chunk_size:
                    sentences = re.split(r'(?<=[。！？；.!?;])', para)
                    buf = ""
                    for sent in sentences:
                        sent = sent.strip()
                        if not sent:
                            continue
                        if len(buf) + len(sent) <= max_chunk_size:
                            buf = (buf + sent).strip()
                        else:
                            if buf:
                                chunks.append({"text": buf, "heading": None})
                            buf = sent
                    if buf:
                        chunks.append({"text": buf, "heading": None})
                else:
                    current = para
        if current:
            chunks.append({"text": current, "heading": None})
    else:
        # 按标题切分
        for i, match in enumerate(matches):
            heading = match.group().strip()
            start = match.start()
            if i > 0:
                # 上一个标题到当前标题之间的内容
                prev_heading = matches[i - 1].group().strip()
                prev_start = matches[i - 1].start()
                section_text = text[prev_start:start].strip()
                if len(section_text) >= min_chunk_size:
                    # 超长章节再细分
                    if len(section_text) > max_chunk_size * 1.5:
                        sub_chunks = _split_long_section(section_text, max_chunk_size, overlap)
                        for sc in sub_chunks:
                            chunks.append({"text": sc, "heading": prev_heading})
                    else:
                        chunks.append({"text": section_text, "heading": prev_heading})
            current_heading = heading
            current_start = start

        # 最后一个章节
        if matches:
            last_heading = matches[-1].group().strip()
            last_start = matches[-1].start()
            section_text = text[last_start:].strip()
            if len(section_text) >= min_chunk_size:
                if len(section_text) > max_chunk_size * 1.5:
                    sub_chunks = _split_long_section(section_text, max_chunk_size, overlap)
                    for sc in sub_chunks:
                        chunks.append({"text": sc, "heading": last_heading})
                else:
                    chunks.append({"text": section_text, "heading": last_heading})

    # 添加索引和位置
    result = []
    pos = 0
    for i, chunk in enumerate(chunks):
        chunk_text = chunk["text"]
        result.append({
            "index": i,
            "text": chunk_text,
            "heading": chunk.get("heading"),
            "start_pos": pos,
            "end_pos": pos + len(chunk_text),
            "char_count": len(chunk_text),
        })
        pos += len(chunk_text)

    return result


def _split_long_section(text: str, max_size: int, overlap: int) -> List[str]:
    """超长章节按段落+句子细分，带重叠。"""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) <= max_size:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
            # 段落本身超长，按句子切
            if len(para) > max_size:
                sentences = re.split(r'(?<=[。！？；.!?;])', para)
                buf = ""
                for sent in sentences:
                    sent = sent.strip()
                    if not sent:
                        continue
                    if len(buf) + len(sent) <= max_size:
                        buf = (buf + sent).strip()
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = sent
                if buf:
                    current = buf
                else:
                    current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    # 添加重叠
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            prefix = prev[-overlap:] if len(prev) >= overlap else prev
            overlapped.append(prefix + "\n" + chunks[i])
        return overlapped
    return chunks


# --------------------------------------------------------------------------- #
# AI 识别知识点
# --------------------------------------------------------------------------- #
KNOWLEDGE_POINT_PROMPT = """你是一位考研知识提取专家。请从以下文档片段中提取关键知识点。

要求：
1. 提取 3-8 个核心知识点
2. 每个知识点包含：name（名称）、description（简要描述，50-200字）、subject（科目，如数学/英语/政治/数字电子技术/模拟电子技术等）、chapter（章节，如能判断）、exam_frequency（考频1-5，5为最高频）
3. 只返回 JSON 数组，不要其他文字
4. 如果片段中没有明确的知识点，返回空数组 []

文档片段：
{content}
"""


async def extract_knowledge_points(
    db: Session,
    document: Document,
    chunks: List[Dict],
    ai_service,
    progress_callback: Optional[Callable] = None,
) -> List[KnowledgePoint]:
    """从文档分块中AI提取知识点并入库（去重）。"""
    extracted = []
    existing_names = {
        kp.name for kp in db.query(KnowledgePoint).filter(
            KnowledgePoint.document_id == document.id
        ).all()
    }

    total = len(chunks)
    for i, chunk in enumerate(chunks):
        if progress_callback:
            progress_callback(f"知识点提取 {i+1}/{total}", i / total if total else 0)

        try:
            result = await ai_service.chat([
                {"role": "system", "content": "你是知识提取专家，只返回JSON。"},
                {"role": "user", "content": KNOWLEDGE_POINT_PROMPT.format(content=chunk["text"][:6000])}
            ])
            text = result.get("content", "")
            # 提取JSON
            start = text.find("[")
            end = text.rfind("]") + 1
            if start < 0 or end <= start:
                continue
            kps = json.loads(text[start:end])
            for kp_data in kps:
                name = (kp_data.get("name") or "").strip()
                if not name or name in existing_names:
                    continue
                kp = KnowledgePoint(
                    name=name[:300],
                    subject=(kp_data.get("subject") or document.subject or "其他")[:50],
                    chapter=(kp_data.get("chapter") or chunk.get("heading") or "")[:200],
                    document_id=document.id,
                    description=(kp_data.get("description") or "")[:2000],
                    exam_frequency=min(5, max(1, int(kp_data.get("exam_frequency", 3)))),
                    mastery=0,
                )
                db.add(kp)
                existing_names.add(name)
                extracted.append(kp)
        except Exception as e:
            logger.warning(f"知识点提取失败 chunk {i}: {e}")
            continue

    db.commit()
    return extracted


# --------------------------------------------------------------------------- #
# AI 识别测试题/真题
# --------------------------------------------------------------------------- #
QUESTION_EXTRACT_PROMPT = """你是一位考研题库建设专家。请从以下文档片段中识别并提取题目。

【极其重要的规则 - 必须严格遵守】
1. 绝对禁止把以下说明文字当成题目内容或选项：
   - 以"答案"、"答："、"参考答案"开头的行 → 这是答案，放到answer字段，不是选项！
   - 以"解析"、"分析"、"详解"开头的行 → 这是解析，放到analysis字段，不是选项！
   - 以"科目"、"学科"、"分类"开头的行 → 这是科目，放到subject字段，不是选项！
   - 以"知识点"、"考点"、"章节"开头的行 → 这是知识点，放到knowledge_point字段，不是选项！
   - 以"难度"、"来源"、"题型"开头的行 → 这是元数据，放到对应字段，不是选项！

2. 选择题的options数组只包含真正的选项（A/B/C/D/E），例如：
   正确：["先进先出", "后进先出", "随机存取", "顺序存取"]
   错误：["先进先出", "后进先出", "答案：B", "解析：栈是后进先出", "科目：专业课"] ← 绝对禁止！

3. answer字段单独存放正确答案字母（如"A"、"B"、"C"、"D"），不要把答案文字放到options里

4. 每个题目包含：
   - content（题干，完整描述，不包含选项和答案）
   - options（选项数组，选择题必填，判断题/填空/简答为空数组[]）
   - answer（正确答案：选择题用字母A/B/C/D，判断题用"对"/"错"，填空/简答用答案文本）
   - analysis（解析，如能判断，没有则为空字符串）
   - question_type（题型：single单选/multiple多选/judge判断/fill填空/essay简答/calc计算）
   - difficulty（难度1-5，默认3）
   - source（来源：真题/模拟题/课后习题/自建，如能判断）

5. 只返回 JSON 数组，不要其他文字，不要markdown代码块
6. 如果片段中没有题目，返回空数组 []

文档片段：
{content}
"""


async def extract_questions(
    db: Session,
    document: Document,
    chunks: List[Dict],
    ai_service,
    progress_callback: Optional[Callable] = None,
) -> List[QuizQuestion]:
    """从文档分块中AI识别题目并分类入库（去重）。"""
    extracted = []
    # 去重：基于题干内容前100字
    #
    # 【根因修复 2026-11】旧逻辑的判重集合被
    #   QuizQuestion.source.like(f"%{document.file_name}%")
    # 限死在**当前这一篇文档**内。同一道题（公共课跨考题最典型）承载在A 文档和
    # B 文档时，处理 B 的查询只匹配 source 含 B 的行，而那条题在库里 source 是 A
    #   → 不命中 → 同一题入库两次。
    # 现在叠加一层跨来源指纹判重（services/quiz_dedupe）：命中即合并溯源、不插入。
    # 开关：QUIZ_DEDUPE_CROSS_SOURCE（默认开，置 off 退回旧行为）。
    existing_contents = {
        (q.content or "")[:100] for q in db.query(QuizQuestion).filter(
            QuizQuestion.source.like(f"%{document.file_name}%")
        ).all()
    }
    cross_dedupe = quiz_dedupe.dedupe_enabled()
    dd_index = quiz_dedupe.build_index_from_db(db) if cross_dedupe else None
    dd_stats = quiz_dedupe.DedupeStats()

    total = len(chunks)
    for i, chunk in enumerate(chunks):
        if progress_callback:
            progress_callback(f"题目识别 {i+1}/{total}", i / total if total else 0)

        try:
            result = await ai_service.chat([
                {"role": "system", "content": "你是题库建设专家，只返回JSON。"},
                {"role": "user", "content": QUESTION_EXTRACT_PROMPT.format(content=chunk["text"][:6000])}
            ])
            text = result.get("content", "")
            start = text.find("[")
            end = text.rfind("]") + 1
            if start < 0 or end <= start:
                continue
            questions = json.loads(text[start:end])
            for q_data in questions:
                content = (q_data.get("content") or "").strip()
                if not content or len(content) < 10:
                    continue
                content_key = content[:100]
                if content_key in existing_contents:
                    continue

                # 判断题型
                q_type = (q_data.get("question_type") or "single").lower()
                options = q_data.get("options") or []
                if not isinstance(options, list):
                    options = []

                # ===== V3.0 强制后处理：过滤异常选项（解决答案/解析被当成选项的严重bug）=====
                # 1. 过滤掉以元数据关键词开头的选项
                metadata_prefixes = ["答案", "答：", "参考答案", "解析", "分析", "详解",
                                     "科目", "学科", "分类", "知识点", "考点", "章节",
                                     "难度", "来源", "题型", "正确答案", "错误原因"]
                cleaned_options = []
                for opt in options:
                    opt_str = str(opt).strip()
                    # 跳过空选项
                    if not opt_str:
                        continue
                    # 跳过以元数据关键词开头的选项
                    if any(opt_str.startswith(prefix) for prefix in metadata_prefixes):
                        continue
                    # 跳过明显是答案格式的选项（如"A. xxx"已经是选项，但"答案：A"不是）
                    if re.match(r'^答案[：:]\s*[A-E]', opt_str):
                        continue
                    cleaned_options.append(opt_str)

                # 2. 选项数量校验：选择题正常4-5个选项，超过6个说明AI识别错误，只保留前4个
                if q_type in ("single", "multiple") and len(cleaned_options) > 6:
                    cleaned_options = cleaned_options[:4]

                options = cleaned_options

                # 3. 答案校验：选择题答案必须是A/B/C/D/E之一
                answer = (q_data.get("answer") or "").strip()
                if q_type in ("single", "multiple") and options:
                    # 从答案中提取字母
                    answer_match = re.search(r'[A-E]', answer.upper())
                    if answer_match:
                        answer = answer_match.group()
                    else:
                        # 无法从答案提取字母，默认第一个选项（标记为待人工审核）
                        answer = "A"
                        # 在解析中标记答案异常
                        analysis_note = "【注意：原答案格式异常，已默认A，请人工审核】"
                        q_data["analysis"] = analysis_note + (q_data.get("analysis") or "")

                if not options and q_type == "single":
                    q_type = "essay"

                # 来源标记
                source = (q_data.get("source") or "").strip()
                if not source:
                    # 从内容判断是否为真题
                    if any(kw in content for kw in ["考研真题", "历年真题", "年考研", "真题"]):
                        source = "真题"
                    elif any(kw in content for kw in ["模拟", "冲刺", "押题"]):
                        source = "模拟题"
                    else:
                        source = f"文档提取：{document.file_name}"

                # ===== 入库前内容闸门（AI 抽取同样会把讲义正文当题）=====
                # source 已经定稿，闸门据此对"声称真题"的内容额外加严。
                gate_ok, gate_reason = gate_admit(
                    content,
                    options=options,
                    answer=answer,
                    source=source,
                )
                if not gate_ok:
                    logger.info(
                        "内容闸门拦截（source=%s）：%s | %s",
                        source[:40], gate_reason, content[:60],
                    )
                    continue

                q = QuizQuestion(
                    content=content[:5000],
                    options=options,  # 使用清洗后的选项
                    answer=answer[:500],  # 使用校验后的答案
                    analysis=(q_data.get("analysis") or "")[:2000],
                    subject=(document.subject or "其他")[:50],
                    chapter=(chunk.get("heading") or "")[:200],
                    knowledge_point="",
                    difficulty=min(5, max(1, int(q_data.get("difficulty", 3)))),
                    source=source[:200],
                    question_type=q_type[:50],
                )
                # ===== 跨来源判重（入库前最后一道闸）=====
                # 命中则不插入：把本源并入已有题的溯源（source_ids），
                # 并在已有题缺答案/解析时用本副本补齐。不静默丢弃。
                decision = quiz_dedupe.decide_insert(
                    db, content, source, dd_index,
                    answer=answer, analysis=analysis, options=options,
                    stats=dd_stats,
                )
                if not decision.is_insert:
                    logger.info(
                        "跨来源判重命中，合并溯源不入库：%s", decision.reason
                    )
                    continue

                db.add(q)
                existing_contents.add(content_key)
                extracted.append(q)
        except Exception as e:
            logger.warning(f"题目识别失败 chunk {i}: {e}")
            continue

    db.commit()
    gate_log_summary(logger)
    # 跨来源去重计数上报（不静默：重复被合并而非丢弃，可从日志核对）
    if cross_dedupe:
        logger.info(
            "跨来源去重：入库 %d / 合并重复 %d / 过短跳过 %d / 补齐 %s",
            dd_stats.inserted, dd_stats.merged, dd_stats.too_short,
            dd_stats.enriched or '无',
        )
    return extracted


# --------------------------------------------------------------------------- #
# 主入口：文档智能分析（知识点+题目一次性提取）
# --------------------------------------------------------------------------- #
async def analyze_document(
    db: Session,
    document: Document,
    ai_service,
    extract_kp: bool = True,
    extract_questions: bool = True,
    rebuild_chunks: bool = False,
    progress_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """对文档进行完整智能分析：分块 → 知识点提取 → 题目识别。

    返回 {chunks, knowledge_points, questions, duration_seconds}
    """
    import time
    start_time = time.time()

    if not document.content:
        return {"error": "文档尚未解析，无内容可分析"}

    # 1. 智能分块
    if progress_callback:
        progress_callback("智能分块中...", 0.05)
    chunks = smart_chunk_text(document.content, max_chunk_size=3000, overlap=200)

    # 如需重建知识库分块
    if rebuild_chunks:
        from services.kb_service import ingest_text
        ingest_text(db, document.id, document.file_name, document.content,
                    subject=document.subject, replace=True)

    result = {
        "chunks": len(chunks),
        "knowledge_points": 0,
        "questions": 0,
        "questions_by_type": {},
        "questions_by_source": {},
    }

    # 2. 知识点提取
    if extract_kp:
        kps = await extract_knowledge_points(db, document, chunks, ai_service, progress_callback)
        result["knowledge_points"] = len(kps)

    # 3. 题目识别
    if extract_questions:
        questions = await extract_questions(db, document, chunks, ai_service, progress_callback)
        result["questions"] = len(questions)
        # 按题型统计
        type_count = {}
        source_count = {}
        for q in questions:
            type_count[q.question_type] = type_count.get(q.question_type, 0) + 1
            source_count[q.source] = source_count.get(q.source, 0) + 1
        result["questions_by_type"] = type_count
        result["questions_by_source"] = source_count

    result["duration_seconds"] = round(time.time() - start_time, 1)

    if progress_callback:
        progress_callback("分析完成", 1.0)

    return result


# --------------------------------------------------------------------------- #
# 批量分析
# --------------------------------------------------------------------------- #
async def batch_analyze_documents(
    db: Session,
    doc_ids: List[int],
    ai_service,
    extract_kp: bool = True,
    extract_questions: bool = True,
    progress_callback: Optional[Callable] = None,
) -> List[Dict[str, Any]]:
    """批量分析多个文档。"""
    results = []
    total = len(doc_ids)
    for i, doc_id in enumerate(doc_ids):
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc or not doc.content:
            results.append({"id": doc_id, "error": "文档不存在或未解析"})
            continue

        def cb(msg, pct, _i=i, _total=total):
            if progress_callback:
                progress_callback(f"[{_i+1}/{_total}] {msg}", (_i + pct) / _total)

        result = await analyze_document(
            db, doc, ai_service,
            extract_kp=extract_kp,
            extract_questions=extract_questions,
            progress_callback=cb,
        )
        result["id"] = doc_id
        result["file_name"] = doc.file_name
        results.append(result)

    return results
