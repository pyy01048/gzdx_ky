"""POST /api/tasks/ai-generate：前端「主题」必须真的进提示词。

历史缺陷：这个端点不收 body，前端传来的 {topic} 被整个丢掉，用户填了主题
照样拿到一份全科计划；同时前端在后端不可用时会本地"生成"一套
数学/英语/政治/834专业课 的假任务并当成 AI 结果（已在 Tasks.jsx 移除）。
"""
from services.ai_service import AIService


class _Capture:
    def __init__(self):
        self.kwargs = {}

    async def generate_plan(self, goal=None, available_time=None):
        self.kwargs = {"goal": goal, "available_time": available_time}
        return "1. 强化特征值与相似矩阵"


class TestAiPlanTopic:
    def test_topic_is_passed_into_prompt(self, client, monkeypatch):
        cap = _Capture()
        monkeypatch.setattr(AIService, "generate_plan", cap.generate_plan)

        r = client.post("/api/tasks/ai-generate", json={"topic": "线性代数特征值强化"})

        assert r.status_code == 200
        body = r.json()
        assert body["plan"] == "1. 强化特征值与相似矩阵"
        assert "线性代数特征值强化" in (cap.kwargs["goal"] or "")

    def test_empty_topic_is_not_fabricated_into_prompt(self, client, monkeypatch):
        cap = _Capture()
        monkeypatch.setattr(AIService, "generate_plan", cap.generate_plan)

        r = client.post("/api/tasks/ai-generate", json={"topic": "   "})

        assert r.status_code == 200
        assert "本次主题" not in (cap.kwargs["goal"] or "")

    def test_no_body_keeps_legacy_behaviour(self, client, monkeypatch):
        """老调用方（不带 body）不能被这次的入参改动打断。"""
        cap = _Capture()
        monkeypatch.setattr(AIService, "generate_plan", cap.generate_plan)

        r = client.post("/api/tasks/ai-generate")

        assert r.status_code == 200
        assert r.json()["plan"]
