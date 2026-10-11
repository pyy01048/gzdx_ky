# -*- coding: utf-8 -*-
"""轻量 Agent 路由编排器（V12 · P1 · 对标 kaoyan-copilot 的 Supervisor 模式）。

当前先落「规则意图分类 + 能力路由表」，后续接入 LLM 意图识别与多 Agent 协作：
- Tutor（答疑）      → /api/ai/chat（RAG + 科目路由已有）
- Planner（规划）    → /api/plan/*（里程碑/周计划已有）
- Consultant（择校） → /api/kaoyan/analysis/auto-adjust + recommend（已有）
- Radar（情报）      → /api/kaoyan/notices/feed + reforms（V10 已有）
- Reviewer（复盘）   → /api/insight/weekly-report（V11 已有）

设计约定：本编排器**不做**业务，只做意图识别与路由决策；所有模型调用
继续走 model_gateway（不在编排器内直连 Ollama/API）。
"""
from __future__ import annotations

import re
from typing import Dict, Optional

# 意图关键词 → Agent（按命中优先级排序，扫分模式：命中数最多者胜）
INTENT_RULES = [
    ("tutor", r"(答疑|讲解|为什么|怎么理解|帮我讲|解析|原理|这道题)"),
    ("planner", r"(计划|安排|规划|进度|今天学什么|每天|周计划|时间表)"),
    ("consultant", r"(择校|院校|报考|推荐学校|专业目录|\d{3}分.{0,8}(能上|够|冲)|(能上|考得上).{0,8}(学校|院校))"),
    ("radar", r"(改考|停招|通知|公告|简章|招生动态|院校变动)"),
    ("reviewer", r"(周报|复盘|总结|正确率|薄弱|错误率|学习情况)"),
]

# Agent → 能力端点映射（前端/CLI 按此直连，编排器只负责"该找谁"）
AGENT_CAPABILITIES = {
    "tutor": {"endpoint": "/api/ai/chat", "note": "RAG 答疑（科目路由 + 流式）"},
    "planner": {"endpoint": "/api/plan/roadmap", "note": "18 节点里程碑 + 三层计划"},
    "consultant": {"endpoint": "/api/kaoyan/analysis/auto-adjust", "note": "冲稳保自动调整"},
    "radar": {"endpoint": "/api/kaoyan/notices/feed", "note": "通知流 + 改考雷达"},
    "reviewer": {"endpoint": "/api/insight/weekly-report", "note": "学习周报"},
}


def classify_intent(question: str) -> Dict:
    """规则意图分类：返回 {agent, confidence, matched, candidates}。

    confidence 为规则命中强度的归一值（无 LLM，快且可解释）；
    多意图并存时返回 candidates 供上层追问澄清。
    """
    text = (question or "").strip()
    scores: Dict[str, int] = {}
    for agent, pattern in INTENT_RULES:
        hits = re.findall(pattern, text)
        if hits:
            scores[agent] = len(hits)
    if not scores:
        return {"agent": "tutor", "confidence": 0.3, "matched": [],
                "candidates": ["tutor"], "fallback": True}
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    total = sum(scores.values())
    return {
        "agent": ranked[0][0],
        "confidence": round(ranked[0][1] / total, 2),
        "matched": [a for a, _ in ranked],
        "candidates": [a for a, _ in ranked],
        "fallback": False,
    }


def route(question: str) -> Dict:
    """意图 → 路由决策（含能力端点与备用候选）。"""
    intent = classify_intent(question)
    agent = intent["agent"]
    cap = AGENT_CAPABILITIES.get(agent)
    return {
        **intent,
        "route": cap,
        "alternatives": [AGENT_CAPABILITIES[a] for a in intent["candidates"][1:2]],
    }
