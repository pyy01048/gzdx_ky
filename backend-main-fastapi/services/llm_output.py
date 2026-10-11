# -*- coding: utf-8 -*-
"""本地 thinking 模型（Qwen3 系列）的输出清洗。

### 踩过的坑（实测，2026-10）

Qwen3 系列是**思考模型**，Ollama 会把推理过程放在 `message.thinking`，
把最终答案放在 `message.content`。听起来很清晰，但 `think` 参数的行为
**跟直觉相反**：

| 设置 | `content` | `thinking` | 能直接用吗 |
| :--- | :--- | :--- | :--- |
| 默认（不传 `think`） | ✅ 干净答案（70 字） | 推理过程（4443 字） | ✅ 可以 |
| `"think": false` | ❌ **推理过程泄漏**（3529 字） | 空 | ❌ **不行** |

也就是说：**显式关闭思考，反而把思考内容倒进了正文**。
代码里原先那句"必须显式 think:false 才能拿到正文"是错的 ——
它描述的是另一个模型（`qwen3.5:4b`）的行为，套到 `qwen3:4b` 上正好相反。

后果很严重：文档提炼会把「首先，用户要求我提炼以下资料…」这种
**思维链当成知识要点写进知识库**，污染检索结果。

### 所以这里不猜模型脾气，只做两件事

1. **优先读 `content`，它为空/异常时才回退到 `thinking`**
2. **无论如何都做一次「推理过程检测」**，疑似思维链就丢弃

这样不管模型怎么变、`think` 参数怎么改，都不会把思维链当答案。
"""

from __future__ import annotations

import re
from typing import Optional

#: 思维链开头的典型话术（第一人称自述、复述任务）
_COT_OPENERS = [
    "首先，", "首先用户", "用户要求", "用户问", "用户想要", "用户需要",
    "我需要", "我得", "我要", "让我", "我来", "我们来", "让我想想",
    "好的，我", "嗯，", "这个问题的", "分析一下", "让我分析",
    "the user", "i need to", "i should", "let me", "first,", "okay,",
    "we need to", "the question",
]

#: 思维链高频标记词（出现多次基本可判定为推理过程）
_COT_MARKERS = [
    "用户", "要求", "我需要", "需要输出", "可能的", "要点：", "关键点",
    "让我", "应该", "可以考虑", "首先", "其次", "然后", "最后",
    "user", "request", "i need", "i should", "we need", "let me",
]


def looks_like_chain_of_thought(text: str) -> bool:
    """判断文本是否像"模型的思考过程"而非"最终答案"。

    判据（任一成立即判定）：
      · 以第一人称自述开头（"首先，用户要求我…"）
      · 篇幅过长（正常要点提炼不该超过 ~600 字）
      · 思维链标记词出现 ≥ 3 次
    """
    if not text:
        return False
    t = text.strip()
    head = t[:40]
    head_low = head.lower()

    # 开头话术比对统一用小写（中英文都要能匹配）
    for opener in _COT_OPENERS:
        if head_low.startswith(opener.lower()):
            return True

    # 太长的"要点"基本是推理过程，不是要点
    if len(t) > 800:
        return True

    low = t.lower()
    hits = sum(1 for m in _COT_MARKERS if m in low)
    if hits >= 3:
        return True
    return False


def extract_answer(message: dict, *, allow_thinking_fallback: bool = True) -> str:
    """从 Ollama 的 `message` 里取出**真正的答案**。

    :param allow_thinking_fallback: content 为空时，是否允许回退到 thinking。
        thinking 里往往是"推理 + 结论"混在一起，只能作为最后手段，
        且仍要过一遍思维链检测。
    """
    if not isinstance(message, dict):
        return ""

    content = (message.get("content") or "").strip()
    thinking = (message.get("thinking") or message.get("reasoning") or "").strip()

    # 1. content 正常就直接用
    if content and not looks_like_chain_of_thought(content):
        return content

    # 2. content 像思维链 —— 说明 think 参数被错误设置（见模块说明）
    if content and looks_like_chain_of_thought(content):
        # 尝试从 thinking 里找干净结论（一般 thinking 为空，但以防万一）
        if thinking and not looks_like_chain_of_thought(thinking):
            return thinking
        return ""      # 宁可返回空，也不把思维链当答案

    # 3. content 为空，回退 thinking
    if allow_thinking_fallback and thinking:
        if not looks_like_chain_of_thought(thinking):
            return thinking
        # thinking 里通常末尾才是结论，取最后一段试试
        tail = _last_conclusive_paragraph(thinking)
        return tail
    return ""


def _last_conclusive_paragraph(thinking: str) -> str:
    """从思维链里抽出最后一个像"结论"的段落。

    思维链末尾往往就是答案（"所以答案是…"）。抽不到就返回空 ——
    不要让脏数据进知识库。
    """
    parts = [p.strip() for p in re.split(r"\n{2,}", thinking) if p.strip()]
    for para in reversed(parts[-4:]):
        if len(para) > 600:
            continue
        if looks_like_chain_of_thought(para):
            continue
        return para
    return ""


def build_payload(
    model: str,
    prompt: str,
    *,
    temperature: float = 0.3,
    num_predict: int = 1024,
    keep_alive: str = "10m",
    think: Optional[bool] = None,
) -> dict:
    """构造 Ollama /api/chat 请求体。

    **默认不传 `think`** —— 实测默认行为才会把答案放进 `content`。
    某些模型（如 qwen3.5 系列）需要显式 `think:false`，那由调用方传入。
    """
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": keep_alive,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    if think is not None:
        payload["think"] = think
    return payload
