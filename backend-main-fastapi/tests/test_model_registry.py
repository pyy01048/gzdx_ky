"""模型注册表回归测试。

验证的是选型的**硬逻辑**，不是模型效果（效果得实测，测不了）：
- 显存估算是否单调、是否保守
- 适配判定档位是否正确
- 分科路由是否把"对的模型给对的科目"
- 硬件未知时是否优雅降级

运行：pytest tests/test_model_registry.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services import model_registry as mr


# --------------------------------------------------------------------------- #
# 显存估算
# --------------------------------------------------------------------------- #

class TestMemoryEstimate:

    def test_weights_scale_with_params(self):
        """参数量越大，权重显存越大。"""
        small = mr.ModelProfile(key="a", name="A", family="x", params_b=3)
        big = mr.ModelProfile(key="b", name="B", family="x", params_b=14)
        assert big.weights_gb() > small.weights_gb()

    def test_quantization_reduces_memory(self):
        """量化档越低，占用越小，且顺序正确。"""
        m = mr.ModelProfile(key="a", name="A", family="x", params_b=8)
        sizes = [m.weights_gb(q) for q in ("Q4_K_M", "Q5_K_M", "Q8_0", "FP16")]
        assert sizes == sorted(sizes), "量化档位与占用应单调递增"

    def test_required_exceeds_weights(self):
        """总需求必须大于权重（要算上 KV cache 与运行时开销）。"""
        for m in mr.MODEL_CATALOG:
            if m.local:
                assert m.required_gb() > m.weights_gb(), f"{m.key} 需求估算异常"

    def test_7b_at_q4_fits_in_8gb(self):
        """7B@Q4 应能装进 8GB —— 这是选型结论的基础。"""
        m = mr.get_profile("deepseek-r1:7b")
        assert m is not None
        assert m.required_gb() < 8.0

    def test_14b_does_not_fit_in_8gb(self):
        """14B 不该被判为能装进 8GB（否则是估算过于乐观）。"""
        m = mr.get_profile("qwen3:14b")
        assert m.required_gb() > 7.5


# --------------------------------------------------------------------------- #
# 适配判定
# --------------------------------------------------------------------------- #

class TestFitVerdict:

    def _hw(self, vram):
        return mr.HardwareProfile(gpu_name="test", vram_gb=vram, ram_gb=16, cuda_available=True)

    def test_small_model_on_big_gpu_is_perfect(self):
        m = mr.get_profile("deepseek-r1:1.5b")
        assert mr.fit_verdict(m, self._hw(24))["level"] == "perfect"

    def test_big_model_on_small_gpu_is_too_big(self):
        m = mr.get_profile("qwen3:14b")
        assert mr.fit_verdict(m, self._hw(8))["level"] == "too_big"

    def test_cloud_model_is_cloud_only(self):
        m = mr.get_profile("deepseek-chat")
        assert mr.fit_verdict(m, self._hw(8))["level"] == "cloud_only"

    def test_no_gpu_is_unknown(self):
        m = mr.get_profile("deepseek-r1:7b")
        hw = mr.HardwareProfile(vram_gb=0, cuda_available=False)
        v = mr.fit_verdict(m, hw)
        assert v["level"] == "unknown"
        assert "云端" in v["detail"] or "CPU" in v["detail"]

    def test_reserve_reduces_usable(self):
        """8GB 卡必须留出系统占用，可用显存应小于标称。"""
        m = mr.get_profile("qwen3:8b")
        v = mr.fit_verdict(m, self._hw(8))
        assert v["usable_gb"] < 8.0

    def test_every_local_model_has_verdict(self):
        hw = self._hw(8)
        for m in mr.local_models():
            v = mr.fit_verdict(m, hw)
            assert v["level"] in mr.FIT_LEVELS
            assert v["label"]


# --------------------------------------------------------------------------- #
# 分科路由 —— 这是"更智能更自主"的核心
# --------------------------------------------------------------------------- #

class TestSubjectRouting:

    def test_subject_to_task_mapping(self):
        assert mr.route_for_subject("数学") == "reasoning"
        assert mr.route_for_subject("数字电子技术") == "reasoning"
        assert mr.route_for_subject("政治") == "chinese_qa"
        assert mr.route_for_subject("英语") == "chinese_qa"

    def test_unknown_subject_falls_back_to_general(self):
        assert mr.route_for_subject("不存在的科目") == "general"
        assert mr.route_for_subject(None) == "general"

    def test_math_routes_to_reasoning_model(self):
        """数学应优先推理型模型（DeepSeek-R1 蒸馏系列）。"""
        recs = mr.recommend_for_task("reasoning", subject="数学")
        assert recs, "数学应有推荐"
        assert recs[0]["reasoning"] >= 4, "数学首选应是推理强的模型"

    def test_politics_routes_to_chinese_model(self):
        """政治应优先中文强的模型（Qwen 系列）。"""
        recs = mr.recommend_for_task("chinese_qa", subject="政治")
        assert recs
        assert recs[0]["chinese"] >= 4

    def test_no_mismatched_recommendation(self):
        """不能把未声明该科目的模型排在首位 —— 例如用数电微调模型答政治。"""
        for subj in ("数学", "政治", "英语", "数字电子技术"):
            task = mr.route_for_subject(subj)
            recs = mr.recommend_for_task(task, subject=subj)
            if recs:
                assert recs[0]["subject_score"] > 0, \
                    f"{subj} 首位推荐「{recs[0]['name']}」未声明该科强项"

    def test_unfit_model_not_recommended_first(self):
        """跑不动的模型不能排在能跑的模型前面。"""
        recs = mr.recommend_for_task("reasoning", subject="数学")
        order = {"perfect": 0, "ok": 1, "cloud_only": 2, "tight": 3, "too_big": 4, "unknown": 2}
        levels = [order[r["fit"]["level"]] for r in recs]
        assert levels == sorted(levels), "推荐顺序未按适配度排序"

    def test_all_core_subjects_have_recommendation(self):
        """每个主线科目都要有推荐，不能有空档。"""
        from services import taxonomy
        for subj in taxonomy.CORE_SUBJECTS:
            task = mr.route_for_subject(subj)
            recs = mr.recommend_for_task(task, subject=subj)
            assert recs, f"{subj} 没有任何推荐"


# --------------------------------------------------------------------------- #
# 档案完整性
# --------------------------------------------------------------------------- #

class TestCatalogIntegrity:

    def test_keys_unique(self):
        keys = [m.key for m in mr.MODEL_CATALOG]
        assert len(keys) == len(set(keys)), "模型 key 有重复"

    def test_local_models_have_ollama_name(self):
        for m in mr.local_models():
            assert m.ollama_name, f"{m.key} 是本地模型但没有 ollama_name"

    def test_cloud_models_have_no_ollama_name(self):
        for m in mr.cloud_models():
            assert not m.ollama_name, f"{m.key} 是云端模型但带 ollama_name"

    def test_best_for_keys_are_valid(self):
        for m in mr.MODEL_CATALOG:
            for t in m.best_for:
                assert t in mr.TASK_KINDS, f"{m.key} 的 best_for 含未知任务 {t}"

    def test_strength_keys_are_real_subjects(self):
        """strengths 的键必须是真实科目名，否则路由永远匹配不上。"""
        from services import taxonomy
        valid = set(taxonomy.ALL_SUBJECTS)
        for m in mr.MODEL_CATALOG:
            for subj in m.strengths:
                assert subj in valid, f"{m.key} 的 strengths 含未知科目 {subj}"

    def test_strength_scores_in_range(self):
        for m in mr.MODEL_CATALOG:
            for subj, score in m.strengths.items():
                assert 1 <= score <= 5, f"{m.key}.{subj} 评分 {score} 越界"

    def test_get_profile_by_key_and_ollama_name(self):
        assert mr.get_profile("qwen3:8b") is not None
        assert mr.get_profile("qwen3:8b").params_b > 0
        assert mr.get_profile("不存在的模型") is None

    def test_full_report_shape(self):
        rep = mr.full_report(installed={"qwen3:4b"})
        assert "hardware" in rep and "models" in rep
        assert "subject_plan" in rep and "batch_plan" in rep
        assert isinstance(rep["installed_models"], list)
        # 已安装标记要能透传
        installed = [m for m in rep["models"] if m.get("installed")]
        assert installed, "installed 标记未生效"


# --------------------------------------------------------------------------- #
# 硬件探测（真实环境，容错）
# --------------------------------------------------------------------------- #

class TestHardwareDetect:

    def test_detect_returns_profile(self):
        hw = mr.detect_hardware()
        assert isinstance(hw, mr.HardwareProfile)
        assert hw.vram_gb >= 0
        assert hw.tier in ("cpu", "entry", "mainstream", "advanced", "high")

    def test_tier_boundaries(self):
        assert mr.HardwareProfile(vram_gb=0).tier == "cpu"
        assert mr.HardwareProfile(vram_gb=5).tier == "entry"
        assert mr.HardwareProfile(vram_gb=8).tier == "mainstream"
        assert mr.HardwareProfile(vram_gb=12).tier == "advanced"
        assert mr.HardwareProfile(vram_gb=24).tier == "high"


# --------------------------------------------------------------------------- #
# 已安装模型优先（"现在能用哪个" vs "理想该用哪个"）
# --------------------------------------------------------------------------- #

class TestPickBestAvailable:
    """用户可能只装了一个模型。这时**不该因为理想模型没装就退回云端** ——
    本地能跑就先本地跑（省钱、数据不出网）。
    """

    def test_returns_none_when_nothing_installed(self):
        assert mr.pick_best_available("reasoning", subject="数学", installed=set()) is None

    def test_uses_only_installed_model(self):
        """只装了 qwen3:4b 时，各科都应挑它（而不是返回未安装的理想模型）。"""
        inst = {"qwen3:4b", "qwen3"}
        for subj in ("数学", "数字电子技术", "政治", "英语", "电路"):
            task = mr.route_for_subject(subj)
            best = mr.pick_best_available(task, subject=subj, installed=inst)
            assert best is not None, f"{subj} 应能挑到已装的模型"
            assert best["ollama_name"] == "qwen3:4b", f"{subj} 挑到了 {best['ollama_name']}"

    def test_prefers_ideal_when_installed(self):
        """理想模型也装了时，应优先理想模型。"""
        inst = {"deepseek-r1:7b", "qwen3:4b"}
        best = mr.pick_best_available("reasoning", subject="数学", installed=inst)
        assert best["ollama_name"] == "deepseek-r1:7b"

    def test_result_has_uniform_shape(self):
        """两条返回路径都要有 relevance 字段（调用方无需分辨来源）。"""
        inst = {"qwen3:4b"}
        best = mr.pick_best_available("reasoning", subject="数学", installed=inst)
        assert "relevance" in best and best["relevance"]

    def test_ignores_unfit_model(self):
        """装了跑不动的模型时不能推荐它。"""
        hw = mr.HardwareProfile(gpu_name="t", vram_gb=4, ram_gb=16, cuda_available=True)
        best = mr.pick_best_available("reasoning", subject="数学",
                                      installed={"qwen3:14b"}, hw=hw)
        assert best is None or best["fit"]["level"] in ("perfect", "ok")
