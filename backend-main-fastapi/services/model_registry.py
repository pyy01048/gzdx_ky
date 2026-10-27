# -*- coding: utf-8 -*-
"""模型注册表：把"哪个模型适合干什么、我的机器跑不跑得动"变成可查询的事实。

### 为什么需要

应用的 AI 层此前是"能用就行"：模型名散落在十几个文件里硬编码
（`qwen3.5:4b`、`kaoyan-assistant`、`deepseek-chat`…），
既不知道某个模型适不适合考研某一科，也不知道本机显存够不够。
用户面对"该装哪个模型"只能靠猜。

### 这个模块提供什么

1. **模型档案（MODEL_CATALOG）**：参数量、量化后显存、上下文、中文能力、
   学科强项、适用场景 —— 全部是选型的硬依据
2. **硬件画像（HardwareProfile）**：本机 GPU 显存 / 内存 → 能跑什么档位
3. **适配判定（fit_verdict）**：显存 vs 需求 → 完美 / 勉强 / 跑不动
4. **分科路由（route_for_subject）**：数学走推理型、政治走中文型、
   文档处理走轻量型 —— 这是"更智能更自主"的核心

### 显存估算口径（保守，留出 KV cache 余量）

    权重显存 ≈ 参数量(B) × 量化字节数
      Q4_K_M ≈ 0.58 GB/B    Q5 ≈ 0.70    Q8 ≈ 1.07    FP16 ≈ 2.0
    总需求   ≈ 权重 + KV cache + 运行时开销
    KV cache 取 2K 上下文约 0.5-1.5GB（按模型层数/头数粗估）

估算是**保守**的：宁可提示"勉强"，也不要用户装完发现爆显存。
"""

from __future__ import annotations
import logging

import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# 量化档位 → 每十亿参数的显存占用（GB）
# --------------------------------------------------------------------------- #
QUANT_GB_PER_B = {
    "Q4_K_M": 0.58,
    "Q5_K_M": 0.70,
    "Q8_0": 1.07,
    "FP16": 2.00,
    "FP32": 4.00,
}

# --------------------------------------------------------------------------- #
# 模型档案
# --------------------------------------------------------------------------- #
@dataclass
class ModelProfile:
    """一个模型的选型档案。"""

    key: str                        # 唯一键（也是 Ollama 拉取名，若适用）
    name: str                       # 展示名
    family: str                     # 阵营：deepseek / qwen / gemma / llama / glm / mistral / minimax / kimi
    params_b: float                 # 参数量（十亿）
    ollama_name: Optional[str] = None      # Ollama 拉取名
    context_k: int = 32                    # 上下文窗口（K）
    chinese: int = 3                       # 中文能力 1-5
    reasoning: int = 3                     # 推理/数学能力 1-5
    speed: int = 3                         # 相对速度 1-5（越大越快）
    license: str = ""
    local: bool = True                     # 是否可本地运行
    #: 学科强项评分 {科目: 1-5}。**这是分科路由的依据** ——
    #: 用布尔"是否覆盖"太粗，会把"通才"和"这一科专门调过的"排成一样。
    #: 未列出的科目视为 0（不推荐）。
    strengths: dict[str, int] = field(default_factory=dict)
    #: 最适合的任务键（见 TASK_KINDS）
    best_for: list[str] = field(default_factory=list)
    #: 每条备注都要有依据，不要写营销词
    note: str = ""
    #: 8GB 显存下的推荐量化档
    quant: str = "Q4_K_M"

    def weights_gb(self, quant: Optional[str] = None) -> float:
        q = quant or self.quant
        return round(self.params_b * QUANT_GB_PER_B.get(q, 0.58), 2)

    def required_gb(self, quant: Optional[str] = None, context_k: int = 4) -> float:
        """总显存需求 = 权重 + KV cache + 运行时开销。"""
        w = self.weights_gb(quant)
        # KV cache 粗估：与上下文长度近似线性；2K 约 0.6GB 起步
        kv = round(0.3 + context_k * 0.15, 2)
        return round(w + kv + 0.6, 2)


#: 任务类型（路由按这个维度选模型）
TASK_KINDS = {
    "reasoning": "数学推导 / 专业课计算题 / 逻辑推理",
    "chinese_qa": "中文概念问答 / 政治背诵 / 英语翻译",
    "doc_process": "文档要点提炼 / 分块摘要（批量、要快）",
    "ocr_cleanup": "OCR 结果纠错与整理",
    "long_context": "整章 / 整本书分析",
    "code": "代码与脚本（平台二次开发）",
    "plan": "学习计划生成",
    "general": "通用问答",
}


MODEL_CATALOG: list[ModelProfile] = [
    # ---------------- DeepSeek 蒸馏系列：小参数强推理 ----------------
    ModelProfile(
        key="deepseek-r1:7b",
        name="DeepSeek-R1 蒸馏 Qwen 7B",
        family="deepseek",
        params_b=7.6,
        ollama_name="deepseek-r1:7b",
        context_k=128,
        chinese=4,
        reasoning=5,
        speed=3,
        license="MIT",
        strengths={"数学": 5, "数字电子技术": 5, "模拟电子技术": 5,
                   "真题综合": 5, "电路": 5, "信号与系统": 5, "通信原理": 4,
                   "光学与工程光学": 4, "普通物理": 4,
                   "计算机学科专业基础408": 4,
                   "电路分析": 4, "光学": 3,
                   "英语": 2, "政治": 2},
        best_for=["reasoning"],
        note="把 R1(671B) 的推理链蒸馏进 7B，数学推导与计算题是它的主场；"
             "输出带思考过程，适合看「怎么想到的」。上下文长，但长上下文吃显存。",
    ),
    ModelProfile(
        key="deepseek-r1:1.5b",
        name="DeepSeek-R1 蒸馏 1.5B",
        family="deepseek",
        params_b=1.8,
        ollama_name="deepseek-r1:1.5b",
        context_k=32,
        chinese=3,
        reasoning=3,
        speed=5,
        license="MIT",
        strengths={"数字电子技术": 2, "模拟电子技术": 2,
                   "电路": 2, "信号与系统": 1, "普通物理": 1},
        best_for=["doc_process", "ocr_cleanup"],
        note="极小极快，适合批量处理文档与 OCR 纠错；推理深度有限，"
             "别指望它做复杂推导。",
    ),
    # ---------------- Qwen Coder：结构化 JSON 生成 ---------------- #
    ModelProfile(
        key="qwen2.5-coder:1.5b",
        name="Qwen2.5 Coder 1.5B",
        family="qwen",
        params_b=1.8,
        ollama_name="qwen2.5-coder:1.5b",
        context_k=32,
        chinese=3,
        reasoning=3,
        speed=5,
        license="Apache-2.0",
        strengths={},
        best_for=["doc_process", "code"],
        note="代码/结构化输出专用：输出稳定、无 think 干扰，"
             "适合答案解析/变式题的 JSON 生成（qwen3 系会带 think 破坏 JSON）。",
    ),
    # ---------------- Qwen 系列：中文最强 ----------------
    ModelProfile(
        key="qwen3:8b",
        name="Qwen3 8B",
        family="qwen",
        params_b=8.2,
        ollama_name="qwen3:8b",
        context_k=32,
        chinese=5,
        reasoning=4,
        speed=3,
        license="Apache-2.0",
        strengths={"政治": 5, "英语": 5, "数学": 4, "真题综合": 4,
                   "数字电子技术": 4, "模拟电子技术": 4,
                   "电路": 4, "信号与系统": 4, "通信原理": 4,
                   "光学与工程光学": 3, "普通物理": 4,
                   "计算机学科专业基础408": 4,
                   "电路分析": 3, "光学": 3},
        best_for=["chinese_qa", "general", "reasoning"],
        note="中文理解与长文本处理开箱即用，政治背诵、英语翻译更准；"
             "8B 在 8GB 显存上需 Q4 量化，属于「能用但别开大上下文」。",
    ),
    ModelProfile(
        key="qwen3:4b",
        name="Qwen3 4B",
        family="qwen",
        params_b=4.0,
        ollama_name="qwen3:4b",
        context_k=32,
        chinese=5,
        reasoning=3,
        speed=5,
        license="Apache-2.0",
        strengths={"政治": 3, "英语": 3, "真题综合": 2, "电路": 2,
                   "信号与系统": 2, "普通物理": 2},
        # 也纳入 chinese_qa / reasoning：它是 8GB 卡的"舒适区"模型，
        # 当机器上**只有它**时，应该本地作答而不是退回云端。
        best_for=["doc_process", "ocr_cleanup", "general", "chinese_qa", "reasoning"],
        note="4B 是 8GB 显存的「舒适区」：又快又稳，适合当默认的日常问答与文档处理。",
    ),
    ModelProfile(
        key="qwen3:14b",
        name="Qwen3 14B",
        family="qwen",
        params_b=14.8,
        ollama_name="qwen3:14b",
        context_k=32,
        chinese=5,
        reasoning=4,
        speed=2,
        license="Apache-2.0",
        strengths={"政治": 5, "英语": 5, "数学": 4, "真题综合": 4,
                   "电路": 4, "信号与系统": 4, "通信原理": 4},
        best_for=["chinese_qa"],
        note="中文能力更上一层，但 8GB 显存需激进量化(Q3)且速度明显下降，"
             "更适合 12GB+ 显卡。",
    ),
    # ---------------- Gemma：知识密度高 ----------------
    ModelProfile(
        key="gemma3:4b",
        name="Gemma 3 4B",
        family="gemma",
        params_b=4.3,
        ollama_name="gemma3:4b",
        context_k=128,
        chinese=2,
        reasoning=4,
        speed=5,
        license="Gemma Terms",
        strengths={},
        best_for=["doc_process"],
        note="知识密度高、4B 能有越级表现，但**中文支持弱** —— "
             "中文考研资料不建议做主力，可当英文文献阅读或文档摘要的补充。",
    ),
    ModelProfile(
        key="gemma3:12b",
        name="Gemma 3 12B",
        family="gemma",
        params_b=12.2,
        ollama_name="gemma3:12b",
        context_k=128,
        chinese=2,
        reasoning=4,
        speed=2,
        license="Gemma Terms",
        strengths={},
        best_for=[],
        note="同样受限于中文能力与显存，8GB 上需 Q4 且偏慢，不推荐做主力。",
    ),
    # ---------------- 其他阵营（了解即可，多数不适合本地） ----------------
    ModelProfile(
        key="llama3.1:8b",
        name="Llama 3.1 8B",
        family="llama",
        params_b=8.0,
        ollama_name="llama3.1:8b",
        context_k=128,
        chinese=2,
        reasoning=3,
        speed=3,
        license="Llama 3.1 Community",
        strengths={},
        best_for=[],
        note="生态最强，但**中文能力一般**，考研中文场景不推荐；需微调才可用。",
    ),
    ModelProfile(
        key="mistral-nemo:12b",
        name="Mistral Nemo 12B",
        family="mistral",
        params_b=12.2,
        ollama_name="mistral-nemo:12b",
        context_k=128,
        chinese=2,
        reasoning=3,
        speed=2,
        license="Apache-2.0",
        strengths={},
        best_for=[],
        note="欧洲合规场景见长，中文非强项，且 8GB 显存需量化。",
    ),
    # ---------------- 本地微调模型 ----------------
    ModelProfile(
        key="kaoyan-assistant",
        name="考研微调模型（自训 LoRA）",
        family="local-tuned",
        params_b=3.1,
        ollama_name="kaoyan-assistant",
        context_k=32,
        chinese=4,
        reasoning=3,
        speed=4,
        license="自训",
        strengths={"数字电子技术": 4, "模拟电子技术": 4,
                   "电路": 2, "信号与系统": 2},
        best_for=["chinese_qa", "reasoning"],
        note="用本题库 570 条真题问答 LoRA 微调而成，answer 风格贴合 834；"
             "但训练集偏小且以数电模电为主，别当全能模型用。",
    ),
    # ---------------- 仅云端（列出来是为了让选型有对照） ----------------
    ModelProfile(
        key="deepseek-chat",
        name="DeepSeek Chat（云端 API）",
        family="deepseek",
        params_b=0,
        ollama_name=None,
        context_k=64,
        chinese=5,
        reasoning=5,
        speed=5,
        license="商业 API",
        local=False,
        strengths={"数学": 5, "数字电子技术": 5, "模拟电子技术": 5, "政治": 4,
                   "英语": 4, "真题综合": 5, "电路": 5, "信号与系统": 5,
                   "通信原理": 5, "光学与工程光学": 4, "普通物理": 5,
                   "计算机学科专业基础408": 5,
                   "电路分析": 4, "光学": 3},
        best_for=["reasoning", "chinese_qa", "long_context", "plan", "general"],
        note="本地跑不动时的兜底；推理与中文都强，代价是数据出网、按量计费。",
    ),
    ModelProfile(
        key="qwen-plus",
        name="通义千问 Plus（云端 API）",
        family="qwen",
        params_b=0,
        ollama_name=None,
        context_k=128,
        chinese=5,
        reasoning=4,
        speed=5,
        license="商业 API",
        local=False,
        strengths={"政治": 4, "英语": 4, "数学": 4, "真题综合": 4,
                   "电路": 4, "信号与系统": 4, "通信原理": 4,
                   "普通物理": 4, "计算机学科专业基础408": 4},
        best_for=["chinese_qa", "long_context", "general"],
        note="中文场景的云端备选，长文本处理稳定。",
    ),
    ModelProfile(
        key="glm-4-plus",
        name="GLM 系列（云端 API）",
        family="glm",
        params_b=0,
        ollama_name=None,
        context_k=128,
        chinese=5,
        reasoning=4,
        speed=5,
        license="商业 API",
        local=False,
        strengths={"政治": 3},
        best_for=["code", "chinese_qa"],
        note="编程与智能体能力突出的开源阵营，但旗舰规模**无法本地运行**，"
             "只能走云端 API。",
    ),
    ModelProfile(
        key="kimi-k2",
        name="Kimi（云端 API）",
        family="kimi",
        params_b=0,
        ollama_name=None,
        context_k=256,
        chinese=4,
        reasoning=4,
        speed=4,
        license="商业 API",
        local=False,
        strengths={"英语": 3, "政治": 3},
        best_for=["long_context"],
        note="超长上下文是它的特点，适合整本书/整章分析；本地无法运行。",
    ),
]


def get_profile(key: str) -> Optional[ModelProfile]:
    """按 key 或 ollama_name 查档案。"""
    for m in MODEL_CATALOG:
        if m.key == key or (m.ollama_name and m.ollama_name == key):
            return m
    return None


def local_models() -> list[ModelProfile]:
    return [m for m in MODEL_CATALOG if m.local]


def cloud_models() -> list[ModelProfile]:
    return [m for m in MODEL_CATALOG if not m.local]


# --------------------------------------------------------------------------- #
# 硬件画像
# --------------------------------------------------------------------------- #
@dataclass
class HardwareProfile:
    gpu_name: str = ""
    vram_gb: float = 0.0
    ram_gb: float = 0.0
    cuda_available: bool = False
    source: str = "unknown"

    @property
    def tier(self) -> str:
        """显存档位。"""
        v = self.vram_gb
        if v <= 0:
            return "cpu"
        if v < 6:
            return "entry"      # 4-6GB
        if v < 9:
            return "mainstream"  # 6-9GB（RTX 4060 8GB 属此档）
        if v < 16:
            return "advanced"    # 9-16GB
        return "high"            # 16GB+


def detect_hardware() -> HardwareProfile:
    """探测本机 GPU / 内存。

    优先 nvidia-smi（不依赖 torch），torch 作补充。
    """
    hw = HardwareProfile()

    # 内存
    try:
        import psutil  # type: ignore
        hw.ram_gb = round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except Exception:
        try:
            if sys.platform == "win32":
                out = subprocess.run(
                    ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"],
                    capture_output=True, text=True, timeout=8, errors="ignore",
                ).stdout
                nums = [int(s) for s in out.split() if s.isdigit()]
                if nums:
                    hw.ram_gb = round(nums[0] / 1024 ** 3, 1)
        except Exception as _exc:  # noqa: BLE001
            # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
            # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
            logging.getLogger(__name__).warning(
                '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
            )

    # GPU（nvidia-smi 优先）
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, errors="ignore",
        )
        if out.returncode == 0 and out.stdout.strip():
            line = out.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2 and parts[1].isdigit():
                hw.gpu_name = parts[0]
                hw.vram_gb = round(int(parts[1]) / 1024, 1)   # MiB → GB
                hw.cuda_available = True
                hw.source = "nvidia-smi"
                return hw
    except Exception as _exc:  # noqa: BLE001
        # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
        # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
        logging.getLogger(__name__).warning(
            '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
        )

    # 退回 torch
    try:
        os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
        import torch  # type: ignore
        if torch.cuda.is_available():
            hw.cuda_available = True
            hw.gpu_name = torch.cuda.get_device_name(0)
            hw.vram_gb = round(torch.cuda.get_device_properties(0).total_memory / 1024 ** 3, 1)
            hw.source = "torch"
    except Exception as _exc:  # noqa: BLE001
        # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
        # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
        logging.getLogger(__name__).warning(
            '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
        )

    return hw


# --------------------------------------------------------------------------- #
# 适配判定
# --------------------------------------------------------------------------- #
FIT_LEVELS = {
    "perfect": "完美适配",
    "ok": "可以运行",
    "tight": "勉强运行（需量化/小上下文）",
    "too_big": "显存不足",
    "cloud_only": "仅云端",
    "unknown": "硬件未知",
}


def fit_verdict(profile: ModelProfile, hw: HardwareProfile,
                *, reserve_gb: float = 0.0) -> dict[str, Any]:
    """判定某模型在本机能否跑、跑得怎么样。

    :param reserve_gb: 显存预留（浏览器/其他程序占用），默认按档位自动留。
    """
    if not profile.local:
        return {
            "level": "cloud_only", "label": FIT_LEVELS["cloud_only"],
            "required_gb": None, "vram_gb": hw.vram_gb,
            "detail": "该模型规模无法本地运行，需通过云端 API 使用",
        }
    if hw.vram_gb <= 0:
        return {
            "level": "unknown", "label": FIT_LEVELS["unknown"],
            "required_gb": profile.required_gb(),
            "vram_gb": 0,
            "detail": "未检测到可用 GPU。只能走云端 API，或用 CPU 推理（很慢）",
        }

    # 预留：8GB 卡实际可用约 7GB（系统/浏览器占用）
    if reserve_gb <= 0:
        reserve_gb = 0.8 if hw.vram_gb <= 9 else 1.5
    usable = round(hw.vram_gb - reserve_gb, 2)

    req = profile.required_gb()
    detail_parts = [f"{profile.params_b}B @ {profile.quant} ≈ {profile.weights_gb()}GB 权重",
                    f"总需求 ≈ {req}GB（含 KV cache）",
                    f"可用 ≈ {usable}GB"]

    if req <= usable * 0.85:
        level, extra = "perfect", "余量充足，可以开更大上下文"
    elif req <= usable:
        level, extra = "ok", "刚好放下，建议上下文控制在 4K 以内"
    elif req <= usable * 1.35:
        level, extra = "tight", "需更激进的量化（如 Q3）或缩小上下文，速度会明显下降"
    else:
        level, extra = "too_big", "即便量化也放不下，请改用云端 API 或更小模型"

    return {
        "level": level,
        "label": FIT_LEVELS[level],
        "required_gb": req,
        "usable_gb": usable,
        "weights_gb": profile.weights_gb(),
        "vram_gb": hw.vram_gb,
        "detail": "；".join(detail_parts) + "。 " + extra,
    }


# --------------------------------------------------------------------------- #
# 分科路由
# --------------------------------------------------------------------------- #
#: 科目 → 优先任务类型（决定选哪类模型）
SUBJECT_TASK: dict[str, str] = {
    # 主线（考试口径）
    "数学": "reasoning",
    "数字电子技术": "reasoning",
    "模拟电子技术": "reasoning",
    "真题综合": "reasoning",
    "政治": "chinese_qa",
    "英语": "chinese_qa",
    # 专业课支撑科目（电子信息 / 电气大类）
    "电路": "reasoning",
    "信号与系统": "reasoning",
    "通信原理": "reasoning",
    "光学与工程光学": "reasoning",
    "普通物理": "reasoning",
    "计算机学科专业基础408": "reasoning",
    # 拓展
    "电路分析": "reasoning",
    "光学": "reasoning",
}


def route_for_subject(subject: str | None) -> str:
    """科目 → 任务类型。未识别则给 general。"""
    from services import taxonomy

    std = taxonomy.normalize_subject(subject)
    return SUBJECT_TASK.get(std, "general")


def recommend_for_task(
    task: str,
    *,
    subject: str | None = None,
    hw: Optional[HardwareProfile] = None,
    installed: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """按任务类型推荐模型，带本机适配判定与是否已安装。

    :param subject: 具体科目。传了就**优先选把该科列为强项的模型** ——
        否则会出现"用数电微调模型答政治"这种明显错配。

    排序依据：适配度 → 是否覆盖该科目 → 是否已安装 → 任务能力 → 速度。
    """
    hw = hw or detect_hardware()
    installed = installed or set()

    std = None
    if subject:
        from services import taxonomy
        std = taxonomy.normalize_subject(subject)

    order = {"perfect": 0, "ok": 1, "cloud_only": 2, "tight": 3, "too_big": 4, "unknown": 2}

    out = []
    for m in MODEL_CATALOG:
        if task not in m.best_for:
            continue
        fit = fit_verdict(m, hw)
        # 科目强项评分：0 表示该模型未声明这一科
        subj_score = m.strengths.get(std, 0) if std else 0
        out.append({
            "key": m.key,
            "name": m.name,
            "family": m.family,
            "params_b": m.params_b,
            "ollama_name": m.ollama_name,
            "local": m.local,
            "installed": bool(m.ollama_name and m.ollama_name in installed),
            "subject_score": subj_score,
            "covers_subject": subj_score > 0,
            "fit": fit,
            "chinese": m.chinese,
            "reasoning": m.reasoning,
            "speed": m.speed,
            "note": m.note,
        })

    def sort_key(x):
        ability = x["reasoning"] if task == "reasoning" else x["chinese"]
        return (
            # 1. 本机跑不跑得动是硬约束
            order.get(x["fit"]["level"], 9),
            # 2. 科目强项评分 —— 路由的核心依据
            #    （用布尔"是否覆盖"会把通才和专门微调过的排成一样）
            -x["subject_score"],
            # 3. 任务通用能力（推理题看 reasoning，中文题看 chinese）
            -ability,
            # 4. 同等条件下优先已安装的（省得再拉模型）
            0 if x["installed"] else 1,
            -x["speed"],
        )

    out.sort(key=sort_key)

    # 科目未声明（score=0）的模型兜底降级：
    # 只要还有"声明了这一科"的候选，就不该把没声明的排进推荐位 ——
    # 否则会出现"用数电微调模型答政治"这种明显错配。
    if std:
        declared = [x for x in out if x["subject_score"] > 0]
        if declared:
            # 保留已安装但未声明该科的模型（用户可能就想用它），排到最后
            rest = [x for x in out if x["subject_score"] == 0 and x["installed"]]
            out = declared + rest
    return out


def pick_best_available(
    task: str,
    *,
    subject: str | None = None,
    installed: set[str] | None = None,
    hw: Optional[HardwareProfile] = None,
) -> Optional[dict[str, Any]]:
    """挑一个**本机已安装且跑得动**的模型；没有则返回 None。

    与 `recommend_for_task` 的区别：
    - 后者回答"**理想情况下**该用哪个模型"（可能尚未安装）
    - 本函数回答"**现在**能用哪个模型"

    为什么要分开：用户可能只装了 `qwen3:4b`，而某科的理想模型是
    `deepseek-r1:7b`。这时**不该因为理想模型没装就退回云端** ——
    本地能跑就先本地跑（省钱、数据不出网），理想模型装上了再自动切过去。
    """
    installed = installed or set()
    if not installed:
        return None
    hw = hw or detect_hardware()

    # 先看按科目排出来的顺序里有没有"已安装且适配"的
    recs = recommend_for_task(task, subject=subject, hw=hw, installed=installed)
    for r in recs:
        if r["installed"] and r["fit"]["level"] in ("perfect", "ok"):
            # 统一返回结构：两条路径都要有 relevance，调用方无需分辨
            return {**r, "relevance": "科目推荐"}

    # 科目推荐里没有已安装的，就从**全部已安装模型**里挑一个能跑的
    fallback: list[tuple[int, dict]] = []
    for m in MODEL_CATALOG:
        if not m.local or not m.ollama_name:
            continue
        if m.ollama_name not in installed and m.key not in installed:
            continue
        fit = fit_verdict(m, hw)
        if fit["level"] not in ("perfect", "ok"):
            continue
        # 任务相关性优先，其次推理/中文能力
        relevant = 0 if task in m.best_for else 1
        ability = m.reasoning if task == "reasoning" else m.chinese
        fallback.append((relevant * 100 - ability, {
            "key": m.key,
            "name": m.name,
            "ollama_name": m.ollama_name,
            "installed": True,
            "relevance": "科目推荐" if relevant == 0 else "已装可用（科目不完全对口）",
            "fit": fit,
        }))
    if fallback:
        fallback.sort(key=lambda kv: kv[0])
        return fallback[0][1]
    return None


def full_report(installed: Optional[set[str]] = None) -> dict[str, Any]:
    """完整选型报告：硬件 + 全部模型 + 分科建议。"""
    hw = detect_hardware()
    installed = installed or set()

    models = []
    for m in MODEL_CATALOG:
        d = asdict(m)
        d["weights_gb"] = m.weights_gb()
        d["required_gb"] = m.required_gb()
        d["fit"] = fit_verdict(m, hw)
        d["installed"] = bool(m.ollama_name and m.ollama_name in installed)
        d["strengths_cn"] = m.strengths
        models.append(d)

    # 分科建议：主线 + 专业课支撑科目都要给建议
    from services import taxonomy

    subject_plan = []
    for subj in list(taxonomy.CORE_SUBJECTS) + list(taxonomy.MAJOR_SUBJECTS):
        task = route_for_subject(subj)
        recs = recommend_for_task(task, subject=subj, hw=hw, installed=installed)
        subject_plan.append({
            "subject": subj,
            "task": task,
            "task_desc": TASK_KINDS.get(task, ""),
            "scope": "core" if taxonomy.is_core(subj) else "major",
            "recommendations": recs[:3],
        })

    # 批量任务（文档处理 / OCR 纠错）单独给建议
    batch_plan = []
    for task in ("doc_process", "ocr_cleanup"):
        recs = recommend_for_task(task, hw=hw, installed=installed)
        batch_plan.append({
            "task": task,
            "task_desc": TASK_KINDS[task],
            "recommendations": recs[:3],
        })

    return {
        "hardware": asdict(hw),
        "hardware_tier": hw.tier,
        "installed_models": sorted(installed),
        "task_kinds": TASK_KINDS,
        "quant_table": QUANT_GB_PER_B,
        "models": models,
        "subject_plan": subject_plan,
        "batch_plan": batch_plan,
    }
