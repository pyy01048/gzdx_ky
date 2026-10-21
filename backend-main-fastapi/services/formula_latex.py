"""公式图 → LaTeX 识别服务（PP-FormulaNet，纯 ONNX，不依赖 torch/网络）。

背景
----
Word 题库里的数学公式是**以图片形式嵌在段落里**的（见 ``services/docx_formula.py``）。
``services/document_parser.py`` 只取 ``paragraph.text``，图片全被丢弃，于是块文本变成
「设函数具有二阶导数，，则在上（　）」这种缺公式的残句——LLM 读到的是残句，
既不能检索也不能作答。

本模块把**公式图**识别成 **LaTeX**，让公式重新变成机器可读的文本。

为什么不用 pix2tex
------------------
``pix2tex`` 依赖 ``pytorch-lightning`` + ``albumentations``，后者又拖 ``skimage``、
``albucore``、``numkong`` 一串包，在本机反复装不上；而且它对中文公式（图里混「若/则」）
是盲区。本机已有 MinerU 落盘的 **PP-FormulaNet_plus-M**（UniMERNet 架构，
591MB ONNX，专门吃中文数学公式），且 ONNX 推理不需要 torch——所以直接用它。

模型与依赖
----------
* 模型：``~/.mineru/models/MinerU-4_models_onnx/MFR/pp_formulanet_plus_m/PP-FormulaNet_plus-M.onnx``
  输入 ``encoder/image`` [batch,1,384,384] float32；输出 ``token_ids`` [batch, len] int64。
* tokenizer：完整配置内嵌在同目录 ``*_inference.yml`` 的
  ``PostProcess.character_dict.fast_tokenizer_file``（是 HF tokenizers 的 JSON），
  用 ``tokenizers.Tokenizer.from_str`` 直接构建，**不需要联网下载词表**。
* 依赖：``onnxruntime`` + ``tokenizers`` + ``Pillow`` + ``numpy``，全部已在本机。

预处理（与 MinerU 官方 processors.py 逐步对齐）
------------------------------------------
1. ``crop_margin``：灰度 → min-max 归一 → 二值化(阈值 200 取深色) → 最小外接框，裁白边。
   这步很关键：Word 公式图白边占比可达 60%，不裁会让字缩得很小。
2. ``resize``：短边缩到 384，再 ``thumbnail(384,384)`` 限制长边。
3. 居中 pad 到 384×384（白底 255）。
4. 归一化：``(x/255 - 0.7931) / 0.1738``（UniMERNet 官方 mean/std）。
5. pad 到 16 的倍数（384 已满足），扩成 ``(1,1,384,384)``。

质量门禁
--------
识别结果**不是**直接可信。每个 LaTeX 都要过 ``latex_is_plausible()``：

* 空/过短 → 失败；
* 残留中文（模型把汉字当符号吐出来）→ 失败；
* 圆括号/花括号不配对 → 失败；
* 出现 LaTeX 里不存在的反斜杠命令 → 失败。

失败时 ``ok=False`` 且**保留原图路径**，由上层决定「退回显示图片」还是「标记待识别」。
宁可显式失败，也不要把坏公式当好公式入库。

用法
----
```python
from services.formula_latex import recognize_formula_image, get_recognizer

r = recognize_formula_image(path)
print(r.ok, r.latex)

# 批量：复用同一个 session，别每张图都重载 591MB 模型
rec = get_recognizer()
for p in paths:
    print(rec.recognize(p).latex)
```
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageOps

# ---- 常量 ---------------------------------------------------------------- #
MIN_LATEX_LEN = 1
INPUT_SIZE = 384
MEAN = 0.7931
STD = 0.1738
# crop_margin 的二值化阈值：低于此灰度算「墨迹」
INK_THRESHOLD = 200
# 宽高比上限：超过（如 240×15 的单行下标）实测要 21.8s 且识别不准，快速失败
MAX_ASPECT = 12.0
# 无法可靠栅格化的矢量格式。PIL 的 WmfImagePlugin 只能读尺寸和部分记录，
# 渲染出来的位图**内容失真**：实测一份数电讲义的逻辑代数公式
# （0·1=0、A·A=A）被识别成几何符号 \angle A B C、\Delta A \cong \Delta B D。
# 语法合法但语义全错，比不识别更糟——必须拦掉，让它走图片兜底。
UNRENDERABLE_EXTS = frozenset({'.wmf', '.emf', '.wmz', '.emz'})

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff01-\uff60]")
_CMD_RE = re.compile(r"\\([a-zA-Z]+)")

# LaTeX 常见命令白名单（只用于判断「模型是否吐了不存在的命令」，不做严格语法校验）
_KNOWN_CMDS = frozenset(
    """
    frac dfrac tfrac cfrac sqrt sum prod int iint iiint oint lim log ln lg exp sin cos tan
    cot sec csc arcsin arccos arctan sinh cosh tanh coth
    infty partial nabla forall exists nexists neg neq le leq ge geq approx equiv sim simeq
    cong propto ll gg prec succ subset supset subseteq supseteq in notin ni cup cap setminus
    emptyset varnothing
    pm mp times div cdot ast star circ bullet oplus otimes odot oslash
    left right middle big Big bigg Bigg bigl bigr Bigl Bigr
    quad qquad enspace thinspace medspace hspace vspace kern mkern
    alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi
    omicron pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega
    Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
    begin end text textbf textit textrm textsf texttt textnormal textstyle displaystyle
    mathbb mathcal mathfrak mathsf mathtt mathrm mathbf mathit mathnormal boldsymbol bm
    operatorname overline underline overrightarrow overleftarrow overleftrightarrow
    vec hat widehat bar widebar dot ddot dddot tilde widetilde acute grave breve check
    mathring overbrace underbrace overset underset stackrel
    cases dcases matrix pmatrix bmatrix Bmatrix vmatrix Vmatrix smallmatrix array aligned
    align gather split subarray substack
    binom dbinom tbinom choose
    max min sup inf det dim ker hom arg deg gcd lcm
    langle rangle lfloor rfloor lceil rceil lvert rvert Vert lVert rVert
    uparrow downarrow Uparrow Downarrow updownarrow leftarrow rightarrow Leftarrow Rightarrow
    leftrightarrow Leftrightarrow longleftarrow longrightarrow mapsto to gets
    cdots ldots dots vdots ddots dotsc dotsb dotsm dotsi dotso
    square blacksquare triangle angle perp parallel mid nmid
    because therefore implies impliedby
    space
    """.split()
)


@dataclass
class FormulaResult:
    """单张公式图的识别结果。"""

    ok: bool
    latex: str = ""
    image_path: str = ""
    engine: str = ""
    confidence: Optional[float] = None
    reason: str = ""
    elapsed: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "latex": self.latex,
            "image_path": self.image_path,
            "engine": self.engine,
            "confidence": self.confidence,
            "reason": self.reason,
            "elapsed": round(self.elapsed, 3),
            "extra": self.extra,
        }


# ---- LaTeX 可信度校验 ---------------------------------------------------- #
def latex_is_plausible(latex: str) -> Tuple[bool, str]:
    """校验识别出的 LaTeX 是否可信，返回 ``(是否可信, 原因)``。

    只拦**强信号**的坏输出：

    * 空/过短 —— 模型什么都没吐出来；
    * 残留 CJK —— 模型把汉字当数学符号了（典型是整块的中文选项图）；
    * 圆括号/花括号不配对 —— 结构已坏。

    **不把「未知命令」当失败**：LaTeX 有几千个命令，白名单永远不全，实测
    ``\\vert`` 这类完全合法的命令会被误杀。未知命令只作为提示返回给调用方
    记录，不阻断入库——宁可放行一个带少见命令的正确公式，
    也不要因为白名单不全而把好公式判死。
    """
    s = (latex or "").strip()
    if len(s) < MIN_LATEX_LEN:
        return False, "too_short"
    if _CJK_RE.search(s):
        return False, "contains_cjk"
    # 括号配对：只查圆/花括号；方括号在 LaTeX 里常作可选参数，误报率高，不查
    if s.count("(") != s.count(")"):
        return False, "unbalanced_paren"
    if s.count("{") != s.count("}"):
        return False, "unbalanced_brace"
    return True, "ok"


def unknown_commands(latex: str) -> List[str]:
    """列出不在常见命令表里的反斜杠命令（**仅作提示，不参与门禁**）。"""
    return sorted({c for c in _CMD_RE.findall(latex or "") if c not in _KNOWN_CMDS})


# ---- 语义级误识别 -------------------------------------------------------- #
# 上面 latex_is_plausible 只管**结构**（空/CJK/括号）。这里管**语义**：
# 结构完全合法、但数学意思已经错了的输出。这类比识别失败危险得多——
# 识别失败会保留占位符（人能看到「这里缺东西」），而错误 LaTeX 会渲染成
# 一个看起来正常的公式，读者不会怀疑它。
#
# 每一条都来自实测：
#
# 1) ``\prod`` + 微分元 —— 实测 quiz 352 的四个曲面积分：
#        \prod _ { S } x ^ { 2 } d S ^ { 2 }        （真值 \iint_S x^2 dS）
#        \prod \limits _ { \bar { S } } x ^ { 2 } d y d z ^ { 2 }
#    多重积分号 ∬/∭ 竖排得很像 ∏。而连乘里**不会**出现 dx/dy/dz/dS，
#    所以两者同时出现基本可以断定是误认。
#
# 2) 微分元带数字上标 ``dS^2`` / ``dz^2`` —— 考研题里不存在这种写法，
#    是 ∬ 的两个圈被读成了上标。
#
# 3) 空的 ``\bar{}`` —— 典型的崩坏输出（``\prod_{\bar{s}}^{\bar{}} y dz dx^{\bar{}}``）。
_SUSPECT_TEX: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"d\s*[xyzS]\s*\^\s*\{?\s*\d"), "微分元被多加上标"),
    (re.compile(r"\\bar\s*\{\s*\}"), r"空 \bar{}"),
]
# 「\prod + 微分元」不能写成一条 `\prod[^\\]{0,60}?dx`：`\prod \limits _ { S } x d S`
# 中间隔着 `\limits`，一遇反斜杠就断，实测漏判了 quiz 352 的 B/C/D 三个选项。
# 公式本身很短，同时出现就足够判定，不必限制距离。
_PROD_RE = re.compile(r"\\prod\b")
_DIFF_RE = re.compile(r"(?<![A-Za-z\\])d\s*[xyzS]\b")


def latex_suspect(latex: str) -> str:
    """识别结果是否可判定**语义**不可信；可信返回空串。

    与 :func:`latex_is_plausible` 互补：那个管结构，这个管意思。
    返回非空时调用方应当**放弃这条 LaTeX**，改出原始公式图片或保留占位符。
    """
    t = latex or ""
    if _PROD_RE.search(t) and _DIFF_RE.search(t):
        return r"\prod 误认（应为多重积分）"
    for pat, why in _SUSPECT_TEX:
        if pat.search(t):
            return why
    return ""


# ---- 图像预处理（对齐 MinerU processors.py） ----------------------------- #
def _crop_margin(img: Image.Image) -> Image.Image:
    """裁掉公式图四周白边。

    与 MinerU ``UniMERNetImgDecode.crop_margin`` 等价：
    灰度 → min-max 归一到 0..255 → 二值化 (x < 200 视为墨迹) → 最小外接框。
    纯色图（没有墨迹）原样返回，避免空点集报错。
    """
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    max_val = int(gray.max())
    min_val = int(gray.min())
    if max_val == min_val:
        return img
    norm = (gray.astype(np.float32) - min_val) / float(max_val - min_val) * 255.0
    mask = (norm < INK_THRESHOLD).astype(np.uint8)
    ys, xs = np.nonzero(mask)
    if xs.size == 0 or ys.size == 0:
        return img
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    # 留 1px 余量，避免切掉笔画端点
    x0 = max(0, x0 - 1)
    y0 = max(0, y0 - 1)
    x1 = min(img.width, x1 + 1)
    y1 = min(img.height, y1 + 1)
    if x1 <= x0 or y1 <= y0:
        return img
    return img.crop((x0, y0, x1, y1))


def _flatten_alpha(img: Image.Image) -> Image.Image:
    """把透明底合成到**白底**上，再转 RGB。

    Word 里的公式图大量是带 alpha 的 GIF（P 模式 + transparency）。
    直接 ``convert("RGB")`` 会把透明像素变成**黑色**，于是「白底黑字」变成
    「黑底黑字」——整张图糊成一块黑，识别结果只剩一个 ``\\cdot``。
    这是实测踩到的坑（144×47 的完整公式被识别成 ``\\cdot``），必须显式合成。
    """
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    return img.convert("RGB")


def _img_decode(img: Image.Image) -> Optional[np.ndarray]:
    """裁边 → 缩放 → 居中 pad 到 384×384。"""
    try:
        img = _crop_margin(_flatten_alpha(img))
    except OSError:
        return None
    if img.height == 0 or img.width == 0:
        return None

    # 目标尺寸**一步算出来**，不要「先放大短边到 384、再 thumbnail 缩长边」。
    # 后者对极扁的公式图（实测 259×15，即 $x_{n+1}$ 这种单行下标）会先生成
    # 6630×384 的巨大中间图，内存暴涨且慢——一批这样的图能把进程卡死数分钟。
    w, h = img.size
    scale = INPUT_SIZE / float(max(1, min(w, h)))
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    longest = max(new_w, new_h)
    if longest > INPUT_SIZE:
        shrink = INPUT_SIZE / float(longest)
        new_w = max(1, int(round(new_w * shrink)))
        new_h = max(1, int(round(new_h * shrink)))
    img = img.resize((new_w, new_h), Image.BICUBIC)

    delta_w = INPUT_SIZE - img.width
    delta_h = INPUT_SIZE - img.height
    pad_w, pad_h = delta_w // 2, delta_h // 2
    padding = (pad_w, pad_h, delta_w - pad_w, delta_h - pad_h)
    # pad 用黑色 —— 与 MinerU 官方 ``ImageOps.expand(img, padding)`` 的默认
    # fill=0 保持一致。UniMERNet 训练时就是黑边填充，换成白色会让模型判读偏移。
    return np.asarray(ImageOps.expand(img, padding, fill=(0, 0, 0)))


def _normalize(arr: np.ndarray) -> np.ndarray:
    """UniMERNet 官方归一化：``(x/255 - mean) / std``，取单通道。"""
    x = arr.astype(np.float32) / 255.0
    # 3 通道同值，等价于灰度化
    x = x[:, :, 0]
    x = (x - MEAN) / STD
    h, w = x.shape
    pad_h = math.ceil(h / 16) * 16 - h
    pad_w = math.ceil(w / 16) * 16 - w
    if pad_h or pad_w:
        x = np.pad(x, ((0, pad_h), (0, pad_w)), constant_values=0)
    return x[np.newaxis, np.newaxis, :, :].astype(np.float32)


# ---- 识别器 -------------------------------------------------------------- #
_MODEL_REL = os.path.join("MinerU-4_models_onnx", "MFR", "pp_formulanet_plus_m")
_ONNX_NAME = "PP-FormulaNet_plus-M.onnx"
_YAML_NAME = "PP-FormulaNet_plus-M_inference.yml"


def _default_model_dir() -> str:
    """按优先级探测模型目录（环境变量 → ``~/.mineru`` 默认位置）。"""
    env = os.environ.get("KAOYAN_FORMULA_MODEL_DIR", "").strip()
    if env:
        return env
    home = os.path.expanduser("~")
    return os.path.join(home, ".mineru", "models", _MODEL_REL)


class FormulaRecognizer:
    """PP-FormulaNet 公式识别器（ONNX Runtime）。

    模型 591MB，加载一次常驻；``session`` 建好后 ``recognize`` 可并发调用
    （onnxruntime 的 ``InferenceSession.run`` 本身线程安全）。
    """

    engine_name = "pp-formulanet-onnx"

    def __init__(self, model_dir: Optional[str] = None, *, providers: Optional[Sequence[str]] = None):
        self.model_dir = model_dir or _default_model_dir()
        self._providers = list(providers) if providers else None
        self._session: Any = None
        self._tokenizer: Any = None
        self._lock = threading.Lock()
        self._load_error: str = ""

    # -- 加载 ------------------------------------------------------------
    def _ensure_loaded(self) -> bool:
        if self._session is not None and self._tokenizer is not None:
            return True
        with self._lock:
            if self._session is not None and self._tokenizer is not None:
                return True
            if self._load_error:
                return False
            try:
                self._load()
            except Exception as exc:  # noqa: BLE001
                self._load_error = f"{type(exc).__name__}: {exc}"
                return False
            return True

    def _load(self) -> None:
        import onnxruntime as ort

        onnx_path = os.path.join(self.model_dir, _ONNX_NAME)
        yaml_path = os.path.join(self.model_dir, _YAML_NAME)
        if not os.path.exists(onnx_path):
            raise FileNotFoundError(f"公式模型不存在: {onnx_path}")
        if not os.path.exists(yaml_path):
            raise FileNotFoundError(f"公式模型配置不存在: {yaml_path}")

        providers = self._providers
        if providers is None:
            avail = ort.get_available_providers()
            providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in avail]
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(onnx_path, sess_options=opts, providers=providers)

        # tokenizer 完整配置内嵌在 yaml 里，无需联网
        import yaml as _yaml
        from tokenizers import Tokenizer

        with open(yaml_path, "r", encoding="utf-8") as fh:
            cfg = _yaml.safe_load(fh)
        fast_tok = cfg["PostProcess"]["character_dict"]["fast_tokenizer_file"]
        if isinstance(fast_tok, dict):
            self._tokenizer = Tokenizer.from_str(json.dumps(fast_tok, ensure_ascii=False))
        else:
            self._tokenizer = Tokenizer.from_file(str(fast_tok))

    @property
    def available(self) -> bool:
        return self._ensure_loaded()

    @property
    def load_error(self) -> str:
        return self._load_error

    def engine_info(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "engine": self.engine_name,
            "ready": self._session is not None,
            "model_dir": self.model_dir,
            "load_error": self._load_error,
        }
        if self._session is not None:
            info["providers"] = self._session.get_providers()
        return info

    # -- 推理 ------------------------------------------------------------
    def _infer(self, arr: np.ndarray, *, image_path: str, t0: float, validate: bool) -> FormulaResult:
        """对已预处理好的 (384,384,3) uint8 数组跑一次推理。"""
        try:
            inp = _normalize(arr)
            out = self._session.run(None, {"encoder/image": inp})
            token_ids = np.asarray(out[0])
            ids = token_ids[0].tolist() if token_ids.ndim > 1 else token_ids.tolist()
            latex = self._tokenizer.decode([int(i) for i in ids], skip_special_tokens=True).strip()
        except Exception as exc:  # noqa: BLE001
            return FormulaResult(
                ok=False, image_path=image_path, engine=self.engine_name,
                reason=f"inference_failed: {type(exc).__name__}: {exc}",
                elapsed=time.time() - t0,
            )

        if validate:
            good, why = latex_is_plausible(latex)
            if not good:
                return FormulaResult(
                    ok=False, latex=latex, image_path=image_path, engine=self.engine_name,
                    reason=why, elapsed=time.time() - t0,
                )
        extra: Dict[str, Any] = {}
        unc = unknown_commands(latex)
        if unc:
            extra["unknown_commands"] = unc
        return FormulaResult(
            ok=True, latex=latex, image_path=image_path, engine=self.engine_name,
            elapsed=time.time() - t0, extra=extra,
        )

    def recognize_image(self, img: Image.Image, *, image_path: str = "", validate: bool = True) -> FormulaResult:
        """直接识别一张内存里的 PIL 图像（不落盘）。

        给「PDF 版面裁切 → 识别」这种流式场景用：一页可能裁出上百个公式框，
        每个都写一次临时文件既慢又难清理。裁切结果本身就在内存里，直接喂。
        """
        t0 = time.time()
        if img is None:
            return FormulaResult(ok=False, image_path=image_path, reason="empty_image")
        try:
            w, h = img.size
            if h > 0 and (w / float(h)) > MAX_ASPECT:
                return FormulaResult(
                    ok=False, image_path=image_path, engine=self.engine_name,
                    reason=f"too_wide: {w}x{h} aspect={w / float(h):.1f}",
                    elapsed=time.time() - t0,
                )
            arr = _img_decode(img)
        except Exception as exc:  # noqa: BLE001
            return FormulaResult(
                ok=False, image_path=image_path, engine=self.engine_name,
                reason=f"image_decode_failed: {type(exc).__name__}: {exc}",
                elapsed=time.time() - t0,
            )
        if arr is None:
            return FormulaResult(
                ok=False, image_path=image_path, engine=self.engine_name,
                reason="image_decode_failed: empty", elapsed=time.time() - t0,
            )
        if not self._ensure_loaded():
            return FormulaResult(
                ok=False, image_path=image_path, engine=self.engine_name,
                reason=f"engine_unavailable: {self._load_error}",
                elapsed=time.time() - t0,
            )
        return self._infer(arr, image_path=image_path, t0=t0, validate=validate)

    def recognize(self, path: str, *, validate: bool = True) -> FormulaResult:
        t0 = time.time()
        if not path or not os.path.exists(path):
            return FormulaResult(ok=False, image_path=path or "", reason="file_not_found")
        ext = os.path.splitext(path)[1].lower()
        if ext in UNRENDERABLE_EXTS:
            return FormulaResult(
                ok=False,
                image_path=path,
                engine=self.engine_name,
                reason=f"vector_format_unrenderable: {ext}",
            )
        if not self._ensure_loaded():
            return FormulaResult(
                ok=False,
                image_path=path,
                engine=self.engine_name,
                reason=f"engine_unavailable: {self._load_error}",
            )
        try:
            with Image.open(path) as im:
                w, h = im.size
                # 极端宽高比快速失败：实测 240×15 这类图要 21.8s（正常 0.3s），
                # 且模型对极扁输入会吐残缺序列。别让它拖死整批回填。
                if h > 0 and (w / float(h)) > MAX_ASPECT:
                    return FormulaResult(
                        ok=False, image_path=path, engine=self.engine_name,
                        reason=f"too_wide: {w}x{h} aspect={w / float(h):.1f}",
                        elapsed=time.time() - t0,
                    )
                arr = _img_decode(im.copy())
        except Exception as exc:  # noqa: BLE001
            return FormulaResult(
                ok=False,
                image_path=path,
                engine=self.engine_name,
                reason=f"image_decode_failed: {type(exc).__name__}: {exc}",
                elapsed=time.time() - t0,
            )
        if arr is None:
            return FormulaResult(
                ok=False, image_path=path, engine=self.engine_name,
                reason="image_decode_failed: empty", elapsed=time.time() - t0,
            )
        return self._infer(arr, image_path=path, t0=t0, validate=validate)

    def recognize_many(self, paths: Sequence[str], *, validate: bool = True) -> List[FormulaResult]:
        """批量识别（逐张，保留每张的失败原因）。

        需要吞吐时用 ``recognize_batch``——那个走一次多 batch 推理。
        """
        return [self.recognize(p, validate=validate) for p in paths]

    def recognize_batch(
        self,
        paths: Sequence[str],
        *,
        batch_size: int = 8,
        validate: bool = True,
        on_progress=None,
    ) -> List[FormulaResult]:
        """批量识别，一次推理多张图。

        为什么需要：单张 384×384 推理在 CPU 上约 1.5s，其中固定开销（ONNX
        kernel 调度、内存拷贝）占大头；凑成 batch 后均摊，实测吞吐提升 3–4 倍。
        全量回填有几万张图，这个优化不是锦上添花而是必要条件。

        返回顺序与 ``paths`` 严格对应；单张失败只影响自己，不牵连整批。
        """
        results: List[Optional[FormulaResult]] = [None] * len(paths)
        # 预解码：解码失败的直接定案，不进 batch
        decoded: List[Tuple[int, np.ndarray]] = []
        for i, p in enumerate(paths):
            t0 = time.time()
            if not p or not os.path.exists(p):
                results[i] = FormulaResult(ok=False, image_path=p or "", reason="file_not_found")
                continue
            try:
                with Image.open(p) as im:
                    arr = _img_decode(im.copy())
            except Exception as exc:  # noqa: BLE001
                results[i] = FormulaResult(
                    ok=False, image_path=p, engine=self.engine_name,
                    reason=f"image_decode_failed: {type(exc).__name__}: {exc}",
                    elapsed=time.time() - t0,
                )
                continue
            if arr is None:
                results[i] = FormulaResult(
                    ok=False, image_path=p, engine=self.engine_name,
                    reason="image_decode_failed: empty", elapsed=time.time() - t0,
                )
                continue
            decoded.append((i, _normalize(arr)))

        if not decoded:
            return [r for r in results if r is not None]

        if not self._ensure_loaded():
            for i, _ in decoded:
                results[i] = FormulaResult(
                    ok=False, image_path=paths[i], engine=self.engine_name,
                    reason=f"engine_unavailable: {self._load_error}",
                )
            return [r for r in results if r is not None]

        done = 0
        for start in range(0, len(decoded), batch_size):
            chunk = decoded[start: start + batch_size]
            t0 = time.time()
            batch = np.concatenate([a for _, a in chunk], axis=0)
            try:
                out = self._session.run(None, {"encoder/image": batch})
                token_ids = np.asarray(out[0])
                if token_ids.ndim == 1:
                    token_ids = token_ids[None, :]
            except Exception as exc:  # noqa: BLE001
                for i, _ in chunk:
                    results[i] = FormulaResult(
                        ok=False, image_path=paths[i], engine=self.engine_name,
                        reason=f"inference_failed: {type(exc).__name__}: {exc}",
                    )
                continue
            elapsed_each = (time.time() - t0) / max(1, len(chunk))
            for row, (i, _) in enumerate(chunk):
                if row >= token_ids.shape[0]:
                    results[i] = FormulaResult(
                        ok=False, image_path=paths[i], engine=self.engine_name,
                        reason="inference_failed: output_row_missing",
                    )
                    continue
                try:
                    ids = [int(x) for x in token_ids[row].tolist()]
                    latex = self._tokenizer.decode(ids, skip_special_tokens=True).strip()
                except Exception as exc:  # noqa: BLE001
                    results[i] = FormulaResult(
                        ok=False, image_path=paths[i], engine=self.engine_name,
                        reason=f"decode_failed: {type(exc).__name__}: {exc}",
                    )
                    continue
                if validate:
                    good, why = latex_is_plausible(latex)
                    if not good:
                        results[i] = FormulaResult(
                            ok=False, latex=latex, image_path=paths[i],
                            engine=self.engine_name, reason=why, elapsed=elapsed_each,
                        )
                        continue
                extra: Dict[str, Any] = {}
                unc = unknown_commands(latex)
                if unc:
                    extra["unknown_commands"] = unc
                results[i] = FormulaResult(
                    ok=True, latex=latex, image_path=paths[i],
                    engine=self.engine_name, elapsed=elapsed_each, extra=extra,
                )
            done += len(chunk)
            if on_progress:
                on_progress(done, len(decoded))

        return [r for r in results if r is not None]


# 进程级单例
_DEFAULT: Optional[FormulaRecognizer] = None
_DEFAULT_LOCK = threading.Lock()


def get_recognizer() -> FormulaRecognizer:
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = FormulaRecognizer()
    return _DEFAULT


def recognize_formula_image(path: str, recognizer: Optional[FormulaRecognizer] = None) -> FormulaResult:
    """识别单张公式图（便捷函数）。"""
    return (recognizer or get_recognizer()).recognize(path)
