# -*- coding: utf-8 -*-
"""模型训练与文档识别管理接口。

提供：
1. LoRA 微调任务管理（启动、停止、状态查询）—— 真实子进程 + 状态文件
2. 批量文档 OCR 识别与去手写处理（当前未接入，明确返回 501，不报假成功）
3. 知识库题目导入进度追踪

训练进程由 ``training/lora_finetune.py`` 启动；该脚本与 API 共用
``data/lora_finetune/training_state.json``，所以命令行训练也能被页面看到。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Document, QuizQuestion
from utils.security import require_admin

router = APIRouter(prefix="/api/model-training", tags=["model-training"], dependencies=[Depends(require_admin)])

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_ROOT = (BASE_DIR / "data").resolve()
STATE_FILE = DATA_ROOT / "lora_finetune" / "training_state.json"
TRAIN_SCRIPT = BASE_DIR / "training" / "lora_finetune.py"


# --------------------------------------------------------------------------- #
# Pydantic Schemas
# --------------------------------------------------------------------------- #
class TrainingStartRequest(BaseModel):
    """启动训练请求。"""
    base_model: str = ""  # 留空则用后端 LORA_MODEL_NAME 环境变量
    data_dir: str = ""    # 留空则用后端 LORA_DATA_DIR 环境变量
    num_epochs: int = Field(3, ge=1, le=20)
    batch_size: int = Field(1, ge=1, le=16)  # QLoRA 在 8GB 卡上默认 1
    learning_rate: float = Field(2e-4, gt=0, le=1e-2)
    lora_r: int = Field(16, ge=4, le=128)
    lora_alpha: int = Field(32, ge=8, le=256)
    use_gpu: bool = True


class OcrBatchRequest(BaseModel):
    """批量 OCR 识别请求。"""
    doc_ids: Optional[list[int]] = None
    enable_denoise: bool = False
    file_types: Optional[list[str]] = None


class ImportProgress(BaseModel):
    """导入进度响应。"""
    total_docs: int = 0
    processed_docs: int = 0
    extracted_questions: int = 0
    imported_questions: int = 0
    status: str = "idle"
    error_message: Optional[str] = None


# --------------------------------------------------------------------------- #
# 训练状态文件
# --------------------------------------------------------------------------- #
def _read_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_state(**updates) -> dict:
    state = _read_state()
    state.update(updates)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)
    return state


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _tail_log(path: str, limit: int = 20) -> list[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 64 * 1024))
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = []
    for line in raw.replace("\r", "\n").splitlines():
        line = line.strip()
        if not line or "%|" in line or line.startswith("Map:") or line.startswith("Filter:"):
            continue
        lines.append(line[:300])
    return lines[-limit:]


def _trainer_progress(output_dir: str) -> dict:
    root = Path(output_dir)
    path = root / "trainer_state.json"
    if not path.is_file():
        # Trainer 只在 checkpoint-N/ 下写 trainer_state.json，输出根目录通常没有；
        # 不回退就会让真实训练一直显示 0/0。
        candidates = []
        for d in root.glob("checkpoint-*"):
            try:
                step = int(d.name.split("-")[-1])
            except ValueError:
                continue
            p = d / "trainer_state.json"
            if p.is_file():
                candidates.append((step, p))
        if candidates:
            path = max(candidates)[1]
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return {}
    step = int(state.get("global_step") or 0)
    max_steps = int(state.get("max_steps") or 0)
    epoch = state.get("epoch")
    last_loss = None
    for entry in reversed(state.get("log_history") or []):
        if "loss" in entry:
            last_loss = round(float(entry["loss"]), 4)
            break
    return {
        "global_step": step,
        "max_steps": max_steps,
        "epoch": epoch,
        "last_loss": last_loss,
        "progress": min(100, int(step * 100 / max_steps)) if max_steps > 0 else 0,
    }


def _estimate_remaining(started_at: str, progress: int) -> str:
    if not started_at or progress <= 5:
        return "-"
    try:
        start = datetime.fromisoformat(started_at)
    except ValueError:
        return "-"
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    if elapsed <= 0:
        return "-"
    remain = elapsed / progress * (100 - progress)
    if remain < 60:
        return "不到 1 分钟"
    return f"约 {int(remain // 60)} 分钟"


def _resolve_data_dir(raw: str) -> Path:
    raw = (raw or os.environ.get("LORA_DATA_DIR", "")).strip() or "data/lora_finetune"
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    path = path.resolve()
    try:
        path.relative_to(DATA_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="训练数据目录必须位于后端 data/ 下")
    for name in ("train.jsonl", "val.jsonl"):
        if not (path / name).is_file():
            raise HTTPException(status_code=400, detail=f"数据目录缺少 {name}：{path}")
    return path


def _resolve_python() -> str:
    python = os.environ.get("LORA_TRAIN_PYTHON", "").strip() or sys.executable
    if not Path(python).is_file():
        raise HTTPException(status_code=400, detail=f"训练 Python 不存在：{python}")
    return python


# --------------------------------------------------------------------------- #
# 训练任务管理
# --------------------------------------------------------------------------- #
@router.get("/training/status")
async def get_training_status():
    """获取当前训练任务状态。"""
    state = _read_state()
    if not state:
        return {
            "status": "idle", "progress": 0, "current_epoch": 0, "total_epochs": 0,
            "message": "暂无训练任务", "logs": [], "estimated_time": "-",
        }

    pid = int(state.get("pid") or 0)
    status = state.get("status") or "idle"
    if status in {"preparing", "training", "merging"} and not _pid_alive(pid):
        # 进程已退出但没来得及写终态：按 final/ 是否存在判定，避免永远显示训练中
        final_dir = Path(state.get("output_dir") or "") / "final"
        status = "completed" if final_dir.is_dir() else "error"
        state = _write_state(
            status=status,
            finished_at=datetime.now(timezone.utc).isoformat(),
            message="训练进程已退出" if status == "error" else "训练完成",
        )

    progress = _trainer_progress(state.get("output_dir") or "")
    total_epochs = int((state.get("config") or {}).get("num_epochs") or 0)
    epoch = progress.get("epoch") or 0
    status_text = {
        "idle": "暂无训练任务",
        "preparing": "准备中",
        "training": "训练中",
        "merging": "合并中",
        "completed": "训练完成",
        "error": "训练失败",
        "cancelled": "已取消",
    }.get(status, status)

    return {
        "status": status,
        "progress": 100 if status == "completed" else progress.get("progress", 0),
        "current_epoch": round(float(epoch), 2) if epoch else 0,
        "total_epochs": total_epochs,
        "global_step": progress.get("global_step", 0),
        "max_steps": progress.get("max_steps", 0),
        "last_loss": progress.get("last_loss"),
        "estimated_time": _estimate_remaining(state.get("started_at", ""), progress.get("progress", 0)),
        "message": state.get("message") or status_text,
        "logs": _tail_log(state.get("log_path") or ""),
        "data_dir": state.get("data_dir"),
        "output_dir": state.get("output_dir"),
        "pid": pid or None,
    }


@router.post("/training/start")
async def start_training(req: TrainingStartRequest):
    """启动 LoRA 微调任务（真实子进程）。"""
    current = _read_state()
    if current.get("status") in {"preparing", "training", "merging"} and _pid_alive(int(current.get("pid") or 0)):
        raise HTTPException(status_code=409, detail=f"已有训练任务在运行（PID {current.get('pid')}）")

    data_dir = _resolve_data_dir(req.data_dir)
    python = _resolve_python()
    output_dir = data_dir / "checkpoints"
    log_path = data_dir / "train.log"

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TRAIN_EPOCHS"] = str(req.num_epochs)
    env["TRAIN_BATCH_SIZE"] = str(req.batch_size)
    env["LORA_LR"] = str(req.learning_rate)
    env["LORA_R"] = str(req.lora_r)
    env["LORA_ALPHA"] = str(req.lora_alpha)
    if req.base_model.strip():
        env["LORA_MODEL_NAME"] = req.base_model.strip()
    if not req.use_gpu:
        env["CUDA_VISIBLE_DEVICES"] = ""

    # 先验证训练环境，避免页面显示「已启动」但进程 1 秒后因缺 torch 退出
    # P0-2：环境探测是同步子进程、timeout 高达 120s，在 async 端点里直调
    # 会把事件循环按死整整两分钟 → 挪线程池。
    from starlette.concurrency import run_in_threadpool

    def _probe_env():
        try:
            return subprocess.run(
                [python, "-c", "import torch, transformers, peft, bitsandbytes"],
                capture_output=True, text=True, timeout=120, env=env,
            )
        except subprocess.TimeoutExpired:
            return None

    probe = await run_in_threadpool(_probe_env)
    if probe is None:
        raise HTTPException(status_code=400, detail=f"训练环境探测超时：{python}")
    if probe.returncode != 0:
        tail = (probe.stderr or probe.stdout or "").strip().splitlines()[-3:]
        raise HTTPException(
            status_code=400,
            detail=f"训练环境不可用（{python}）：{' / '.join(tail) or '依赖缺失'}",
        )

    cmd = [
        python, "-u", str(TRAIN_SCRIPT), "--stage", "train",
        "--data-dir", str(data_dir), "--output-dir", str(output_dir),
    ]
    if req.base_model.strip():
        cmd += ["--base-model", req.base_model.strip()]

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "ab")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(BASE_DIR), env=env, stdout=log_file, stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    finally:
        log_file.close()

    started_at = datetime.now(timezone.utc).isoformat()
    _write_state(
        task_id=f"train-{int(time.time())}",
        pid=proc.pid,
        status="training",
        started_at=started_at,
        finished_at=None,
        data_dir=str(data_dir),
        output_dir=str(output_dir),
        log_path=str(log_path),
        base_model=env.get("LORA_MODEL_NAME", ""),
        message="训练进程已启动",
        config={
            "num_epochs": req.num_epochs,
            "batch_size": req.batch_size,
            "learning_rate": req.learning_rate,
            "lora_r": req.lora_r,
            "lora_alpha": req.lora_alpha,
            "use_gpu": req.use_gpu,
        },
    )

    # 1.5 秒内退出通常意味着基座路径错/显存不足，直接把日志尾部还给前端
    time.sleep(1.5)
    if proc.poll() is not None:
        tail = " / ".join(_tail_log(str(log_path), 5))
        _write_state(status="error", message="训练进程启动失败", finished_at=started_at)
        raise HTTPException(status_code=500, detail=f"训练进程启动失败：{tail or proc.returncode}")

    return {
        "task_id": f"train-{int(time.time())}",
        "pid": proc.pid,
        "message": "训练任务已启动，页面会自动刷新状态",
    }


@router.post("/training/cancel")
async def cancel_training():
    """取消当前训练任务（只杀本任务 PID，不用 taskkill /IM）。"""
    state = _read_state()
    pid = int(state.get("pid") or 0)
    if state.get("status") not in {"preparing", "training", "merging"} or not _pid_alive(pid):
        return {"message": "当前没有正在运行的任务"}

    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            pass

    for _ in range(20):
        if not _pid_alive(pid):
            break
        time.sleep(0.5)

    _write_state(
        status="cancelled",
        finished_at=datetime.now(timezone.utc).isoformat(),
        message="训练任务已取消",
    )
    return {"message": "训练任务已取消", "pid": pid}


# --------------------------------------------------------------------------- #
# OCR 识别与去手写（未接入，明确拒绝）
# --------------------------------------------------------------------------- #
@router.post("/ocr/batch-scan")
async def batch_ocr_scan(req: OcrBatchRequest, db: Session = Depends(get_db)):
    """批量 OCR 尚未接入后台队列，返回 501，避免前端误以为已提交。"""
    count = db.query(Document).count()
    raise HTTPException(
        status_code=501,
        detail=f"批量 OCR 尚未接入后台任务队列（当前库内 {count} 篇）；请走「知识库导入」逐篇扫描。",
    )


@router.post("/ocr/denoise")
async def denoise_document(doc_id: int, db: Session = Depends(get_db)):
    """去手写算法未实现，返回 501，不返回假长度。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    raise HTTPException(status_code=501, detail="去手写处理尚未实现，未对文档做任何修改。")


# --------------------------------------------------------------------------- #
# 知识库导入进度
# --------------------------------------------------------------------------- #
@router.get("/import/progress")
async def get_import_progress(db: Session = Depends(get_db)):
    """获取知识库导入进度。"""
    total_docs = db.query(Document).count()
    total_questions = db.query(QuizQuestion).count()
    docs_with_content = (
        db.query(Document)
        .filter(Document.content.isnot(None))
        .filter(Document.content != "")
        .count()
    )
    return {
        "total_docs": total_docs,
        "docs_with_content": docs_with_content,
        "total_questions": total_questions,
        "status": "completed" if docs_with_content > 0 else "pending",
    }


@router.post("/import/start")
async def start_kb_import(req: OcrBatchRequest, db: Session = Depends(get_db)):
    """启动知识库导入流程（复用 kb_import 扫描）。

    流程：批量 OCR → 提取候选题目 → 去重检测 → 用户预览勾选 → 确认入库
    """
    from routers.kb_import import scan as kb_scan

    class FakePayload:
        def __init__(self, doc_ids):
            self.doc_ids = doc_ids

    try:
        result = await kb_scan(FakePayload(req.doc_ids), db)
        return {
            "scan_result": result,
            "message": "扫描完成，请在文档页面预览并确认入库",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"扫描失败：{str(e)}")
