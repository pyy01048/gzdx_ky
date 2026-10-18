#!/usr/bin/env bash
# =============================================================================
# DSW 一条龙：体检 → OCR → 题目抽取(含配图) → 合成数据 → 合并 → 训练 → 回传 OSS
#
# 设计原则：**每阶段可单独跳过、可断点续跑**。
#   OCR 跳过已产出 json 的文件；题目抽取只读已有 json；合成跳过已完成种子；
#   训练支持 checkpoint 续跑。实例被回收后重跑本脚本只补没做完的部分。
#
# 用法：
#   bash run_everything.sh                    # 全流程（含 OCR，默认 240 分钟预算）
#   SKIP_OCR=1 bash run_everything.sh         # 跳过 OCR，只用已入库的 v3 数据（快档）
#   OCR_BUDGET_MIN=600 bash run_everything.sh # 给 OCR 更多时间
#   SKIP_SYNTH=1 bash run_everything.sh       # 跳过合成
#   ONLY_TRAIN=1 bash run_everything.sh       # 只重训（数据已备好）
#   RESUME_MERGE=1 bash run_everything.sh     # 从 checkpoint 续训
#
# 可调参数：
#   OCR_WORKERS=12 OCR_MAX_PAGES=300 OCR_BUDGET_MIN=240
#   Q_MAX_DOCS=0 Q_MAX_IMAGES=40
#   SYNTH_PER_KIND=1500 SYNTH_BATCH=8
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")"

WS="${WS:-/mnt/workspace}"
SRC_DIR="${SRC_DIR:-/mnt/data/考研资料数据集}"
OCR_DIR="${OCR_DIR:-$WS/ocr_out}"
QUIZ_DIR="${QUIZ_DIR:-$WS/quiz_out}"
IMG_DIR="${IMG_DIR:-$WS/question_images}"
SYNTH_DIR="${SYNTH_DIR:-$WS/synth}"
MERGED_DIR="${MERGED_DIR:-$WS/train_data_v4}"
OUT_DIR="${OUT_DIR:-$WS/lora_out}"

OCR_WORKERS="${OCR_WORKERS:-12}"
OCR_MAX_PAGES="${OCR_MAX_PAGES:-300}"
OCR_BUDGET_MIN="${OCR_BUDGET_MIN:-240}"
Q_MAX_DOCS="${Q_MAX_DOCS:-0}"
Q_MAX_IMAGES="${Q_MAX_IMAGES:-40}"
SYNTH_PER_KIND="${SYNTH_PER_KIND:-1500}"
SYNTH_BATCH="${SYNTH_BATCH:-8}"

STEP=0
TOTAL=7
say() { STEP=$((STEP+1)); echo; echo "════════ [$STEP/$TOTAL] $1 ════════"; }
skip() { STEP=$((STEP+1)); echo; echo "════════ [$STEP/$TOTAL] $1（已跳过） ════════"; }
die() { echo; echo "✗ 失败：$1"; echo "  修完后重跑本脚本即可，前面阶段的产物不会丢。"; exit 1; }

echo "════════════════════════════════════════════════════════"
echo " PAI-DSW 一条龙训练管线（OCR → 题库 → 训练）"
echo " 开始: $(date '+%Y-%m-%d %H:%M:%S')"
echo " 工作空间: $WS   资料源: $SRC_DIR"
echo "════════════════════════════════════════════════════════"

if [ "${ONLY_TRAIN:-0}" = "1" ]; then
  skip "环境体检"; skip "OCR 抽取"; skip "题目抽取"; skip "合成数据"
else
  # ---- 1. 环境体检：缺什么补什么，绝不盲目升级核心包 --------------------- #
  say "环境体检与依赖"
  bash env_setup.sh || die "环境体检未通过"

  # ---- 2. OCR 批量抽取（PDF 为主：文字层优先，扫描页才 OCR）------------- #
  if [ "${SKIP_OCR:-0}" = "1" ]; then
    skip "OCR 抽取（SKIP_OCR=1）"
  else
    say "OCR 抽取（断点续跑 · 页数封顶 ${OCR_MAX_PAGES} · 预算 ${OCR_BUDGET_MIN} 分钟 · ${OCR_WORKERS} 进程）"
    if [ ! -d "$SRC_DIR" ]; then
      echo "  [!] 资料源不存在，跳过 OCR：$SRC_DIR"
    else
      python3 ocr_extract.py --src-dir "$SRC_DIR" --out-dir "$OCR_DIR" \
        --workers "$OCR_WORKERS" --max-pages "$OCR_MAX_PAGES" \
        --time-budget-min "$OCR_BUDGET_MIN" --mode auto \
        || echo "  [!] OCR 阶段异常退出（已完成的 json 保留），继续后续步骤"
      echo "  OCR 产物: $(ls "$OCR_DIR" 2>/dev/null | wc -l) 个 json"
      echo "  [i] OCR 没跑完不要紧：已产出的 json 已足够合成数据用；"
      echo "      明天再跑一次本脚本会自动接着抽剩下的。"
    fi
  fi

  # ---- 3. 题目抽取（题目 + 原页配图 + 视觉训练集）---------------------- #
  if [ "${SKIP_QUIZ:-0}" = "1" ]; then
    skip "题目抽取（SKIP_QUIZ=1）"
  else
    say "题目抽取（题干/选项/答案 + 原页配图）"
    python3 extract_questions.py --ocr-dir "$OCR_DIR" --out-dir "$QUIZ_DIR" \
      --img-dir "$IMG_DIR" --max-docs "$Q_MAX_DOCS" \
      --max-images-per-doc "$Q_MAX_IMAGES" \
      || echo "  [!] 题目抽取异常退出，继续后续步骤"
  fi

  # ---- 4. 合成数据生产（7B 当工人）-------------------------------------- #
  if [ "${SKIP_SYNTH:-0}" = "1" ]; then
    skip "合成数据生产（SKIP_SYNTH=1）"
  else
    say "合成数据生产（7B 当工人 · 每类上限 ${SYNTH_PER_KIND} 条）"
    python3 gen_synthetic.py --ocr-dir "$OCR_DIR" --out-dir "$SYNTH_DIR" \
      --max-per-kind "$SYNTH_PER_KIND" --batch-size "$SYNTH_BATCH" \
      || echo "  [!] 合成阶段异常退出（已生成的 jsonl 保留），继续后续步骤"
  fi
fi

# ---- 5. 合并数据集 -------------------------------------------------------- #
say "合并数据集（v3 + 合成 → v4）"
INPUTS=()
[ -f data/lora_finetune_v3/train.jsonl ] && INPUTS+=("data/lora_finetune_v3/train.jsonl")
[ -f data/lora_finetune_v3/val.jsonl ]   && INPUTS+=("data/lora_finetune_v3/val.jsonl")
for f in "$SYNTH_DIR"/*.jsonl; do
  [ -f "$f" ] && INPUTS+=("$f")
done
# 抽到的真题（有答案的 A/B 级）本身就是最好的答疑语料，一并进训练集
if [ -f "$QUIZ_DIR/quiz_questions.jsonl" ] && [ "${INCLUDE_QUIZ_IN_TRAIN:-1}" = "1" ]; then
  python3 - "$QUIZ_DIR/quiz_questions.jsonl" "$QUIZ_DIR/quiz_train.jsonl" <<'PY' 2>/dev/null || true
import json, sys
src, dst = sys.argv[1], sys.argv[2]
n = 0
with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8") as o:
    for line in f:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("grade") not in ("A", "B") or not r.get("answer"):
            continue
        stem = r["content"] + ("\n" + "\n".join(r["options"]) if r["options"] else "")
        head = f"答案是：{r['answer']}"
        o.write(json.dumps({
            "messages": [
                {"role": "system", "content": "你是一位考研辅导老师，负责计算机与电子信息类"
                 "（834 电子技术基础）以及数学二、英语二、政治的答疑。答疑风格：① 先判断学生"
                 "卡在概念还是计算——概念不清时先抛一个引导性问题帮他定位盲点（苏格拉底式引导）"
                 "再讲解，计算类直接给结论与步骤；② 结构：先给结论，再讲原理，必要时给出解题步骤，"
                 "只讲与问题相关的内容，不复述题目原文；③ 对定义、公式、考点等记忆型内容，提示用"
                 "间隔重复（当天、1天、3天、7天后回顾，对应 SM-2 记忆曲线）巩固；"
                 "④ 不确定时明确说明并给出最稳妥的复习建议，不编造。"},
                {"role": "user", "content": stem},
                {"role": "assistant", "content": head},
            ],
            "subject": r.get("subject", "其他"),
            "source": "quiz_extract",
        }, ensure_ascii=False) + "\n")
        n += 1
print(f"  真题转训练样本 {n} 条 -> {dst}")
PY
  [ -f "$QUIZ_DIR/quiz_train.jsonl" ] && INPUTS+=("$QUIZ_DIR/quiz_train.jsonl")
fi

if [ ${#INPUTS[@]} -eq 0 ]; then
  echo "  [!] 无输入数据集，改用 prepare_data.sh 的兜底"
  bash prepare_data.sh || die "准备基础数据集失败"
  DATA_DIR="${DEST:-$WS/train_data}"
else
  echo "  合并 ${#INPUTS[@]} 个来源"
  python3 merge_dataset.py "${INPUTS[@]}" --out-dir "$MERGED_DIR" \
    --max-source-share 0.45 || die "合并失败"
  DATA_DIR="$MERGED_DIR"
fi
echo "  最终训练数据: $DATA_DIR"

# ---- 6. 训练前体检 + LoRA 训练 ------------------------------------------- #
say "训练前体检"
python3 preflight.py --data-dir "$DATA_DIR" || die "体检未通过，先修上面报的问题"

say "LoRA 训练（Qwen2.5-7B + QLoRA 4bit）"
RESUME_ARG=""
if [ "${RESUME_MERGE:-0}" = "1" ]; then
  LAST_CKPT=$(ls -d "$OUT_DIR"/checkpoints/checkpoint-* 2>/dev/null | sort -V | tail -1)
  [ -n "$LAST_CKPT" ] && RESUME_ARG="--resume $LAST_CKPT" && echo "  续跑: $LAST_CKPT"
fi
python3 train_dsw.py --data-dir "$DATA_DIR" --output-dir "$OUT_DIR" $RESUME_ARG \
  || die "训练失败（可用 RESUME_MERGE=1 续跑）"

# ---- 7. 回传 OSS ---------------------------------------------------------- #
say "回传 adapter 到 OSS"
bash push_checkpoint.sh "$OUT_DIR/checkpoints/final"

echo
echo "════════════════════════════════════════════════════════"
echo " ✓ 全流程完成  $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════════════"
echo "产物清单（回本地要用的）："
echo "  ① 知识库文本  $OCR_DIR          ($(ls "$OCR_DIR" 2>/dev/null | wc -l) 个 json)"
echo "  ② 题库记录    $QUIZ_DIR/quiz_questions.jsonl + .csv"
echo "  ③ 题目配图    $IMG_DIR          ($(ls "$IMG_DIR" 2>/dev/null | wc -l) 张 png)"
echo "  ④ 视觉训练集  $QUIZ_DIR/vl_dataset.jsonl"
echo "  ⑤ 最终数据集  $DATA_DIR"
echo "  ⑥ adapter     $OUT_DIR/checkpoints/final → 已传 OSS"
echo
echo "本地接下来做："
echo "  1. 把 ①②③④ 从 OSS 下载回本地 → 走 smart_ingest 入库（题库+知识库）"
echo "  2. adapter 下载 → merge → ollama create kaoyan-assistant-v5"
echo "  3. 评测：python scripts/eval_qa_model.py --models kaoyan-assistant,kaoyan-assistant-v5 --n 150"