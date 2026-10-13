# -*- coding: utf-8 -*-
"""LLM 结构化抽取层（精准读取各校公告正文，替代脆弱正则启发式）。

设计目标
--------
把「从一段公告标题+正文里精准抽取结构化字段」这件事，从每站一套正则启发式
升级为「LLM 精准抽取 + 正则兜底」双层：

1. 首选 LLM：复用 ``services.ai_service.AIService``（本地 LoRA + 在线 API 双引擎），
   用带 JSON schema 约束的 prompt 让模型输出结构化 JSON。
2. 兜底正则：LLM 不可用 / 解析失败时，回退到现有启发式（``spider_notices`` 的
   ``infer_notice_type`` / 日期正则），保证「宁慢不错、宁缺毋滥」。
3. 诚实口径：抽取结果带 ``method`` 字段（llm / regex），前端可据以标注置信度。

合规与隐私
----------
- 只抽取**公开的院校公告信息**（招生简章/复试线/录取名单等），不含个人隐私。
- 抽取任务**强制走在线 API**（本地 1.5B 模型做结构化抽取能力不足），
  但所有抽取输入均为公开数据，不涉及用户个人数据，符合「数据不出网」红线
  （该红线针对用户隐私类内容，公开院校数据不在此列）。

用法
----
    from services.kaoyan.llm_extractor import LLMNoticeExtractor
    ex = LLMNoticeExtractor(db_session)
    # 同步封装（内部 asyncio.run）
    fields = ex.extract_notice("清华大学2027年硕士研究生招生考试报名公告", "正文……")
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from services.kaoyan.spider_notices import infer_notice_type

# --------------------------------------------------------------------------- #
# 抽取字段 schema（单一事实来源，LLM prompt 与兜底都据此对齐）
# --------------------------------------------------------------------------- #
# notice_type  公告 | 简章 | 复试 | 调剂 | 录取 | 目录 | 大纲
# publish_date YYYY-MM-DD 或 None
# deadline     YYYY-MM-DD 或 None（报名/确认/缴费等硬截止日）
# event_kind   报名 | 复试 | 录取 | 调剂 | 分数线 | 大纲 | 目录 | 其他
# numbers      关键数字（如招生人数/分数线），[{label, value}] 列表
# is_noise     是否噪声（纯党务/活动/博士等与硕士考研无关）

# 在线强模型用的完整抽取 prompt（可吐完整 JSON）
_EXTRACT_PROMPT = """你是考研招生信息结构化抽取助手。请从给定的院校招生公告【标题】与【正文】中，精准抽取以下字段，严格按 JSON 输出（不要输出任何 JSON 以外的文字、不要用 markdown 代码块包裹）：

{
  "notice_type": "公告|简章|复试|调剂|录取|目录|大纲 之一",
  "publish_date": "YYYY-MM-DD 或 null",
  "deadline": "YYYY-MM-DD 或 null（报名/确认/缴费/调剂等硬截止日；仅当正文明确给出具体日期才填，否则 null）",
  "event_kind": "报名|复试|录取|调剂|分数线|大纲|目录|其他 之一",
  "numbers": [{"label": "招生人数/总分线/单科线等名称", "value": "数值或文本"}],
  "is_noise": true或false（纯党务/党建/活动/博士招生等与【硕士考研】无关的内容为 true）
}

抽取规则：
1. 只抽取正文中明确出现的信息，禁止臆造或推断。
2. deadline 仅在正文出现明确日期时填写，否则一律 null。
3. is_noise 判定：若该通知是纯博士招生、党务党建、文体活动、招标采购等与硕士考研无关内容，则为 true；凡含「硕士/研究生招生/复试/调剂/录取/报名/初试」任一信号即为 false。
4. numbers 抽取「招生人数」「复试分数线」「总分线」「单科线」等关键数字，label 用中文简述，value 保留原文（含单位/分数）。

【标题】：{title}

【正文】：
{content}

请输出 JSON："""

# 本地小模型用的「极简判断题」prompt（本地模型 500 token 上限，只做类型+噪声判断，
# 不吐完整 JSON，避免被截断；日期/数字仍由确定性正则抽取，保证可靠）。
_LOCAL_CLASSIFY_PROMPT = """只判断这条考研通知的类型和是否噪声，直接回复两个词（中间用 | 分隔，不要解释）：
类型（公告|简章|复试|调剂|录取|目录|大纲）+ | + 噪声（是|否）

标题：{title}
正文：{content}

回复："""


def _parse_json_loose(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出里宽松解析 JSON（容忍前后夹带文字/代码块围栏）。"""
    if not text:
        return None
    # 优先取 ```json ... ``` 围栏
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        # 否则取第一个 { 到最后一个 }
        s = text.find("{")
        e = text.rfind("}")
        if s == -1 or e == -1 or e <= s:
            return None
        text = text[s:e + 1]
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _regex_fallback(title: str, content: str) -> Dict[str, Any]:
    """LLM 不可用时的正则兜底（复用现有启发式，诚实标注 method=regex）。"""
    nt = infer_notice_type(title or "")
    # 日期：标题/正文里首个 YYYY-MM-DD 或 YYYY.MM.DD
    dm = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", (title or "") + "\n" + (content or ""))
    pub = None
    if dm:
        y, mo, d = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            pub = f"{y:04d}-{mo:02d}-{d:02d}"
    # 截止日：后缀型截止词
    deadline = None
    dm2 = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})\s*日?\s*(?:前|截止|之前|以内)", (title or "") + (content or ""))
    if dm2:
        y, mo, d = int(dm2.group(1)), int(dm2.group(2)), int(dm2.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            deadline = f"{y:04d}-{mo:02d}-{d:02d}"
    return {
        "notice_type": nt,
        "publish_date": pub,
        "deadline": deadline,
        "event_kind": _kind_from_type(nt),
        "numbers": [],
        "is_noise": False,
        "method": "regex",
    }


def _kind_from_type(nt: str) -> str:
    m = {
        "简章": "目录", "复试": "复试", "调剂": "调剂", "录取": "录取",
        "目录": "目录", "大纲": "大纲", "分数线": "分数线",
    }
    return m.get(nt, "其他")


class LLMNoticeExtractor:
    """用 LLM 精准抽取公告结构化字段，失败回退正则。

    复用 AIService.chat() 的智能路由，但通过 provider_id=None + 强制在线
    （本地 1.5B 模型对结构化 JSON 抽取不可靠）。抽取输入均为公开院校数据。
    """

    # 允许的 notice_type 枚举（校验 LLM 输出合法性）
    VALID_TYPES = {"公告", "简章", "复试", "调剂", "录取", "目录", "大纲", "分数线"}

    def __init__(self, db_session, max_content_chars: int = 3000):
        self.db = db_session
        self.max_content_chars = max_content_chars

    def _truncate(self, text: str) -> str:
        if not text:
            return ""
        t = re.sub(r"\s+", " ", text).strip()
        return t[: self.max_content_chars]

    async def _extract_async(self, title: str, content: str) -> Dict[str, Any]:
        from models import AIProvider
        from services.ai_service import AIService

        # 1. 优先在线强模型（doubao/deepseek），仅当配置了真实密钥才走 LLM 完整抽取。
        online = (
            self.db.query(AIProvider)
            .filter(
                AIProvider.provider_type.in_(["doubao", "deepseek"]),
                AIProvider.is_enabled == True,
                AIProvider.api_key.isnot(None),
                AIProvider.api_key != "",
            )
            .order_by(AIProvider.fallback_priority.asc())
            .first()
        )

        svc = AIService(self.db)

        # 1) 在线强模型：完整 JSON 抽取
        if online is not None:
            try:
                result = await svc.chat(
                    [{"role": "user", "content": _EXTRACT_PROMPT.format(
                        title=self._truncate(title), content=self._truncate(content)
                    )}],
                    provider_id=online.id,
                    use_routing=False,
                )
                obj = _parse_json_loose(result.get("content", ""))
                if obj:
                    return self._normalize(obj, title, method="llm", model=result.get("model"))
            except Exception:
                pass  # 在线失败 → 继续降级本地

        # 2) 本地模型：只做「类型 + 噪声」判断题，日期/数字用确定性正则兜底
        #    优先用通用模型（qwen3:8b 等），微调模型 kaoyan-assistant 对结构化判断题不擅长。
        try:
            local = self._pick_local_provider(svc)
            if local is not None:
                result = await svc.chat(
                    [{"role": "user", "content": _LOCAL_CLASSIFY_PROMPT.format(
                        title=self._truncate(title), content=self._truncate(content)
                    )}],
                    provider_id=local.id if getattr(local, "id", None) else None,
                    use_routing=False,
                )
                raw = (result.get("content") or "").strip()
                nt, is_noise = self._parse_classify(raw)
                if nt:
                    fb = _regex_fallback(title, content)
                    fb["notice_type"] = nt
                    fb["event_kind"] = _kind_from_type(nt)
                    fb["is_noise"] = is_noise
                    fb["method"] = "llm-local"
                    fb["model"] = result.get("model")
                    return fb
        except Exception:
            pass

        # 3) 最终兜底：纯正则
        return _regex_fallback(title, content)

    @staticmethod
    def _pick_local_provider(svc) -> Any:
        """选本地模型做判断题：优先通用大模型（8b/7b），其次 4b，最后微调模型。

        微调模型 kaoyan-assistant 面向「考研答疑」而非「结构化分类」，做判断题
        会把类型词误判为噪声，故排在最后。
        """
        from models import AIProvider

        providers = (
            svc.db.query(AIProvider)
            .filter(AIProvider.provider_type.in_(["ollama", "local"]), AIProvider.is_enabled == True)
            .all()
        )
        # 优先级：名字含 8b > 7b > 4b > 其他 > kaoyan
        def rank(p):
            m = (p.model_name or "").lower()
            if "8b" in m:
                return 0
            if "7b" in m:
                return 1
            if "4b" in m:
                return 2
            if "kaoyan" in m or "1.5b" in m:
                return 4
            return 3
        if not providers:
            return svc._get_local_provider()
        return sorted(providers, key=rank)[0]

    @staticmethod
    def _parse_classify(raw: str):
        """解析判断题回复，返回 (notice_type|None, is_noise: bool)。

        兼容多种输出形态：
        - 「类型（公告）| 是」
        - 「公告 | 否」
        - 「公告 否」
        - 只回了类型词
        """
        if not raw:
            return None, False
        # 提取「类型（X）」里的 X
        m = re.search(r"类型[（(]\s*([^）)]+)\s*[）)]", raw)
        parts = re.split(r"[|｜\n]", raw)
        nt = None
        if m:
            nt = m.group(1).strip()
        else:
            # 直接取第一个非空片段，看是否命中枚举
            for p in parts:
                p = p.strip().strip("（()） ").strip()
                if p in ("公告", "简章", "复试", "调剂", "录取", "目录", "大纲"):
                    nt = p
                    break
        is_noise = False
        # 噪声：剩余部分含「是」且不含「否」
        tail = raw
        if m:
            tail = raw[m.end():]
        if ("是" in tail or "是" in " ".join(parts[1:])) and "否" not in tail and "否" not in raw:
            is_noise = True
        return nt, is_noise

    def _normalize(self, obj: Dict[str, Any], title: str, method: str, model: Any = None) -> Dict[str, Any]:
        nt = obj.get("notice_type")
        if nt not in self.VALID_TYPES:
            nt = infer_notice_type(title or "")
        return {
            "notice_type": nt,
            "publish_date": obj.get("publish_date") or None,
            "deadline": obj.get("deadline") or None,
            "event_kind": obj.get("event_kind") or _kind_from_type(nt),
            "numbers": obj.get("numbers") if isinstance(obj.get("numbers"), list) else [],
            "is_noise": bool(obj.get("is_noise", False)),
            "method": method,
            "model": model,
        }

    def extract_notice(self, title: str, content: str = "") -> Dict[str, Any]:
        """同步封装：抽取一条公告。"""
        try:
            return asyncio.run(self._extract_async(title, content))
        except Exception:
            # 任何异常（无 AI 服务商/网络/解析）都回退正则，保证可用
            return _regex_fallback(title, content)

    def extract_batch(self, notices: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """批量抽取（顺序执行，逐条失败独立兜底）。"""
        out: List[Dict[str, Any]] = []
        for n in notices:
            out.append(self.extract_notice(n.get("title", ""), n.get("content", "")))
        return out
