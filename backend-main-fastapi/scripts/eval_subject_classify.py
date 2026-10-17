# -*- coding: utf-8 -*-
"""抽样评测 `smart_ingest.extract_metadata` 的学科 / 书名判定准确率。

用途：修复「政治教材被判成数学」这类元数据偏差时，用它量化**修复前 / 修复后**
的准确率对比。样本清单固化为 `scripts/_subject_samples.json`，可反复运行。

只读取知识库文件，**不做任何写库 / 改文件操作**。

用法：
    python scripts/eval_subject_classify.py                # 全量样本（修复后逻辑）
    python scripts/eval_subject_classify.py --legacy       # 复现修复前逻辑，做基线对比
    python scripts/eval_subject_classify.py --limit 5      # 只跑前 5 个（调试）
    python scripts/eval_subject_classify.py --verbose      # 打印正文前 200 字

`--legacy` 通过**打补丁**还原修复前的三处行为（不碰磁盘上的代码）：
  1. `_subject_from_path` 恒返回 None —— 等价于旧调用只传 basename、丢掉目录；
  2. 数学强信号词表含裸「1000题」，政治词表不含「新思想/肖1000/帽子题…」；
  3. `book_name` 回退到「正文首个《》」的老规则。
这样同一份样本清单能跑出修复前 / 修复后的两组可比数字。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

SAMPLES_PATH = os.path.join(BASE_DIR, "scripts", "_subject_samples.json")

_LEGACY = False

from services import smart_ingest as si                     # noqa: E402
from services.kb_service import _SUBJECT_STRONG              # noqa: E402
from services import kb_service as kb                       # noqa: E402
from services.document_parser import DocumentParser          # noqa: E402

CACHE_DIR = os.path.join(BASE_DIR, "data", "_eval_text_cache")

#: 修复前的数学/政治强信号词表（取自 git HEAD，用于 --legacy 复现旧行为）
_LEGACY_STRONG = {
    "数学": ["数学", "高数", "高等数学", "线代", "线性代数", "概率论", "数理统计",
             "张宇", "660", "1000题", "基础30讲", "数一", "数二", "数三",
             "概统", "概率统计", "微积分", "同济", "复习全书"],
    "政治": ["政治", "马原", "毛中特", "史纲", "思修", "肖秀荣", "徐涛", "腿姐",
             "辩证法", "唯物史观", "近代史纲要"],
}


def apply_legacy_patch() -> None:
    """把服务端的判定逻辑**在内存里**还原成修复前的样子。"""
    _SUBJECT_STRONG.update(_LEGACY_STRONG)
    kb._subject_from_path = lambda path: None
    si._BOOK_NAME_NOISE = re.compile(r"(?!x)x")      # 永不命中 = 关掉噪声过滤
    si._pick_book_name_from_text = lambda head: (
        (si._BOOK_RE.search(head).group(1).strip()
         if si._BOOK_RE.search(head) else "")
    )


def parse_text(path: str) -> str:
    """提取正文（只读）。解析失败返回空串。结果落磁盘缓存，二次跑秒出。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = hashlib.md5(path.encode("utf-8")).hexdigest() + ".txt"
    cache = os.path.join(CACHE_DIR, key)
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return f.read()
    try:
        text = DocumentParser().parse(path) or ""
    except Exception as e:                                  # noqa: BLE001
        print(f"    [解析失败] {type(e).__name__}: {e}")
        text = ""
    # errors="replace"：PDF 文本层里偶有孤立代理字符（'\ud835'），直接写会崩
    with open(cache, "w", encoding="utf-8", errors="replace") as f:
        f.write(text)
    return text


def call_extract(name: str, text: str, path: str) -> dict:
    """调用 extract_metadata。legacy 模式下只传 basename，等价于修复前的调用。"""
    if _LEGACY:
        return si.extract_metadata(name, text)
    return si.extract_metadata(name, text, path=path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个样本")
    ap.add_argument("--verbose", action="store_true", help="打印正文前 200 字")
    ap.add_argument("--samples", default=SAMPLES_PATH, help="样本清单 json 路径")
    ap.add_argument("--legacy", action="store_true",
                    help="打补丁复现修复前的判定逻辑，产出基线数据")
    args = ap.parse_args()

    global _LEGACY
    _LEGACY = args.legacy
    if args.legacy:
        apply_legacy_patch()
        print("[legacy] 已还原修复前逻辑：无路径信号 / 数学含裸「1000题」/ "
              "book_name 取正文首个《》\n")

    with open(args.samples, encoding="utf-8") as f:
        samples = json.load(f)
    if args.limit:
        samples = samples[: args.limit]

    total = ok = bad = no_text = 0
    wrong: list[dict] = []

    print(f"{'#':>2} {'期望':<22} {'实际':<22} {'':<3} 文件名")
    print("-" * 110)
    for i, s in enumerate(samples, 1):
        path = s["path"]
        name = os.path.basename(path)
        expected = s["expected_subject"]

        t0 = time.time()
        text = parse_text(path)
        chars = len(text.strip())
        meta = call_extract(name, text, path)
        actual = meta.get("subject", "")
        book = meta.get("book_name", "")

        if chars == 0:
            no_text += 1
            flag = "?"
        else:
            total += 1
            if actual == expected:
                ok += 1
                flag = "OK"
            else:
                bad += 1
                flag = "XX"
                wrong.append({"path": path, "expected": expected,
                              "actual": actual, "book": book})

        print(f"{i:>2} {expected:<22} {actual:<22} {flag:<3} {name[:52]}")
        print(f"       chars={chars} ({time.time() - t0:.1f}s) "
              f"book={book!r} chapter={meta.get('chapter', '')!r} "
              f"ctype={meta.get('content_type', '')!r}")
        if args.verbose and text:
            print("       head:", repr(text.strip()[:200]))

    print("-" * 110)
    print(f"样本 {len(samples)} 个，可判定 {total} 个，无文本层 {no_text} 个")
    if total:
        print(f"学科判定准确率：{ok}/{total} = {ok / total * 100:.1f}%  "
              f"（错 {bad}）")
    if wrong:
        print("\n判错明细：")
        for w in wrong:
            print(f"  期望={w['expected']}  实际={w['actual']}  "
                  f"book={w['book']!r}\n    {w['path']}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
