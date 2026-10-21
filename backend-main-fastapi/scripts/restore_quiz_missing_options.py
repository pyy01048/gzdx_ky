"""从源 docx 补全题库**整项丢失 / 被合并**的选项。

背景
----
``quiz_questions.options`` 是 ``[{"key": "A", "text": "..."}, ...]`` 形式的 JSONB 数组。
库里 386 道题全部是 ``question_type='single'``（单选），按命题规范本该有 A/B/C/D 四项，
但实测有 21 道只剩 3 项、7 道只剩 2 项。它们不是「本来就这么少」，而是旧入库管线
在切选项段落时整项漏掉，或者把后一项的标记挤进了前一项的文本里：

    id=78   2 项  A=增大  B=减小                ← 源题本来就只有 A、B（不可补）
    id=118  2 项  A=ＡＢＣ  B=Ａ C． D．        ← C、D 的标记被挤进 B，内容（公式图）全丢
    id=157  2 项  A=1       B=2 C．             ← C、D 整项丢失
    id=192  2 项  C=惟一    D=至少一点          ← A、B 整项丢失
    id=215  3 项  B=存在  C=存在且  D=…         ← A 整项丢失（A 本身是一张公式图）

源 docx 里这些题的选项段是完整的 A．/B．/C．/D．（个别题在 docx 里本身就只有 2~3 项），
所以正确的做法**不是猜**，而是回源精确取回——取不到（docx 也只有 2~3 项）就不动。

## 为什么 ``find_option_block`` 必须传 ``max_run_index=1``

``find_option_block`` 的做法是在题干行之后扫一段行，收集所有形如 ``A．`` 的命中，
再找第一串连续的 ``[A, B, C, D]``。这对「库里已经有 A~D 四项、只是内容坏了」的题没问题
（见 ``repair_quiz_options.py``），但对「库里只有 2 项」的题是**灾难**：

    id=78 题干在第 147 行，选项只有 A、B（148、149 行），第 150 行是【答案】，
           下一题从 152 行开始，它的 A/B/C/D 在 153 行往后。
           不限制时命中序列是 [A,B, A,B,C,D]，第一串 A~D 落在下标 2——
           切出来的是**下一题**的四个选项，一写库就把 id=78 的选项换成了别人的。

所以这里只接受「A~D 这一串的起始下标 ≤ 1」的段：容忍题干行里偶发的一个假命中
（比如题干本身提到 "A．"），但绝不允许跨到下一题。命中不到就判 ``option_block_not_found``，
宁可不补，也不补错。

## 为什么需要 G1 / G2 两道守卫

``max_run_index`` 只解决「跳到下一题」，不解决「切偏了一行」。
选项文本短（「1」「2」「增大」），任何一行的错位都可能让切片看起来还挺像。
所以写库前必须证明「切出来的这四段，就是库里这道题原本的那四项」。

- **G1 逐项精确**：库里已有的每个 key，其文本 ``norm`` 后必须**精确等于** docx 对应段的纯文本。
  适用「缺的是开头几项」的题（id=192 缺 A/B、id=215 缺 A）——B/C/D 三项同时精确命中，
  基本不可能是巧合，A 就可以安全补上。
- **G2 前缀拼接相等**：把库里已有选项按 key 顺序拼起来，和 docx 前 N 段（N=库里项数）
  拼起来必须**精确相等**。专门处理「C、D 被挤进 B」这一类：库里 B 的文本里还留着
  ``C． D．`` 这种**只剩标记、没有内容**的残渣（内容是公式图，被旧管线丢了），
  直接比会永远不等，所以比对前先把这些残余标记剥掉（``_strip_merged_marks``），
  剥完必须是 docx 选项序列的**前缀**。

两道守卫都过不了就标 ``guard_failed`` 并跳过——这是本脚本最重要的性质：
**绝不写一版自己没法证明是对的选项。**

算法
----
1. ``resolve_doc`` 找到 docx → ``build_aligned(parse_docx_with_images(path))`` 拿到
   ``al.plain``（去公式）与 ``al.marked``（带 ``[[F:n]]``）两个对齐视图；
2. 用 ``strip_rendered(content)`` 在 ``al.plain`` 里 ``locate``（失败再 ``locate_by_prefix``）；
3. 用**题干末位置的行号**去索引 ``al.marked`` 的行首，从那里切选项段
   （行号在 plain/marked 两边严格对齐；不能用 ``plain_to_marked``，见 repair_quiz_options 的注释）；
4. 段里的 ``[[F:n]]`` → 导出图片 → ``formula_latex`` 识别 → ``sanitize_latex``
   → ``_suspect``（``latex_suspect`` + 本地补的「重复上划线」判据）拦截误识别；
   识别失败的出 ``![公式](url)``，错的 LaTeX 比图片有害；
5. 过 G1 或 G2 后写 4 项：缺的补上，原有的重新渲染公式；
6. 默认干跑；``--apply`` 前自动备份，逐条 commit。

用法
----
```
python scripts/restore_quiz_missing_options.py                    # 干跑，逐题打印 before/after
python scripts/restore_quiz_missing_options.py --quiz-id 118      # 只看指定题
python scripts/restore_quiz_missing_options.py --report out.json  # 导 JSON 报告
python scripts/restore_quiz_missing_options.py --apply            # 真写库
```
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.docx_formula import (  # noqa: E402
    MARKER_RE,
    build_aligned,
    parse_docx_with_images,
    strip_markers,
)
from repair_quiz_options import (  # noqa: E402
    OPTION_MARK_RE,
    _line_of,
    _line_span,
    _line_starts,
    _render_markers,
    _rewrite_option_text,
    find_option_block,
    latex_suspect,
)
from repair_quiz_stems import (  # noqa: E402
    _ensure_web_png,
    _media_root,
    build_norm_index,
    locate,
    locate_by_prefix,
    norm,
    resolve_doc,
    sanitize_latex,
    strip_rendered,
)

# 单选四个选项的标准 key 顺序
KEYS = ["A", "B", "C", "D"]

# 被挤进相邻选项里的「残余选项标记」：只有标记、没有内容。
# 旧管线遇到公式图就整段丢掉，但标记符（是普通文字）留了下来，
# 于是 id=118 的 B 变成了 "Ａ C． D．"、id=157 的 B 变成了 "2 C．"。
_TRAILING_MARK_RE = re.compile(r"\s*[A-D]\s*[．.、\)）]\s*$")

# 打印 before/after 时的截断长度
_SHOW = 100

# 在 ``latex_suspect`` 之外补两条判据（都来自本批实测，且**误判代价很低**——
# 误判只是把这一项退回图片，图片本身就是正确的显示形态）：

# 1) 重复上划线。id=118 的 C 项源图是 ABC 上一道横线（= \overline{ABC}），
#    却识别成 ``\overline{{A\overline{{BC}}}}``，多套了一层。
#    数学上 \overline{\overline{x}} = x，公式里不会真写两个上划线，命中即误识别。
_MULTI_OVERLINE_RE = re.compile(r"\\overline")

# 2) 单独的上标 t。撇号（′/″）在这批小图上几乎总被读成 t：
#    id=192 的 A 项源图是 f''(x)，识别成 ``f ^ { t } ( x )``；
#    库里 id=191 的解析也是同一个毛病（``(e^x f(x))^{t}`` 应为 (e^x f(x))'）。
#    全库 ``^{t}`` 只出现过 1 次，且就是误识别，所以这条判据的误伤面很小。
_PRIME_AS_T_RE = re.compile(r"\^\s*\{\s*t\s*\}|\^t\b")


def _suspect(tex: str) -> str:
    """识别结果是否可判定不可信；可信返回空串。"""
    why = latex_suspect(tex)
    if why:
        return why
    if len(_MULTI_OVERLINE_RE.findall(tex or "")) >= 2:
        return "重复上划线（上划线被拆错层）"
    if _PRIME_AS_T_RE.search(tex or ""):
        return "上标 t（多为撇号误识别）"
    return ""


def _strip_merged_marks(text: str) -> str:
    """剥掉选项文本**行尾连续的**残余选项标记（``C．`` / ``D．``），只用于 G2 比对。

    这些标记是旧管线丢公式图时留下的空壳，本身不属于任何选项的内容：
    id=118 的 B 是 ``Ａ C． D．``（C、D 的内容都是公式图，被整条丢了），
    id=157 的 B 是 ``2 C．``。不剥掉的话「库里 B vs 源 A+B+C+D」永远拼不相等。

    **只剥行尾**：正文里的 ``A``~``D`` 字母（比如选项 ``ＡＢＣ``、``ABC +
    \\overline{BC}``）必须原样保留，否则 G2 会把「字母相同」误判成「文本相同」。
    """
    t = text or ""
    while True:
        new = _TRAILING_MARK_RE.sub("", t)
        if new == t:
            return t
        t = new


def _seg_plain(seg: dict) -> str:
    """docx 选项段的纯文本：去 ``A．`` 前缀 → 去 ``[[F:n]]`` → 归一化空白。"""
    return norm(strip_markers(_rewrite_option_text(seg["text"])))


def _peek_option_keys(marked: str, starts: List[int], from_pos: int, window: int = 8) -> List[str]:
    """诊断用：把题干后若干行里的选项标记按出现顺序读出来（不做任何切分）。

    只为在「找不到连续 A~D」时告诉人工到底是「源题本来就只有 3 项」
    还是「格式变了」。绝不参与写库判断。
    """
    i0 = _line_of(starts, from_pos)
    order = "ABCD"
    keys: List[str] = []
    for j in range(i0, min(len(starts), i0 + window)):
        s, e = _line_span(starts, marked, j)
        for m in OPTION_MARK_RE.finditer(marked[s:e]):
            before = marked[s:e][: m.start()]
            if before.strip() and not before.endswith("  "):
                continue
            key = m.group(1)
            # 只收「从第一个标记开始逐字母递进」的那一串：中间断掉就说明
            # 已经离开本题的选项段（多半是走到下一题的 A 了），到此为止。
            if keys and order.index(key) != order.index(keys[-1]) + 1:
                return keys
            keys.append(key)
    return keys


def _db_plain(text: str) -> str:
    """库里选项的纯文本：剥掉已渲染的 ``$...$`` / ``![...](...)`` / 旧占位符再归一化。

    必须用 ``strip_rendered`` 而不是直接 ``norm``——选项如果已经被
    ``repair_quiz_options.py`` 修过，文本里是 ``$...$``，而 docx 段的纯文本
    里公式本来就已被 ``strip_markers`` 抹掉，两边只有都去掉公式才可比。
    """
    return norm(strip_rendered(text or ""))


def _web_png(path: str) -> str:
    """转成**不透明白底 PNG**，返回可直接给 ``<img>`` 的路径。

    两层处理：

    1. ``_ensure_web_png`` 负责 ``.gif``/``.bmp`` → ``.png``。docx 里的公式图
       大量是**透明底 GIF**，深色主题下会变成「黑底黑字」看不见；而且 ``.gif``
       的 MIME 映射依赖 Windows 注册表，不可靠。
    2. 但它的 ``_WEB_SAFE_EXTS`` 对 ``.png`` 直接放行，而源 docx 里也有**带 alpha
       的 PNG**（实测 ``61/formula_00032.png`` 背景 alpha=0、字是纯黑），直接用
       一样是黑底黑字。所以这里再压平一次，输出 ``<stem>_w.png``。

    转换失败就退回原图——宁可样式难看，也不能把公式弄丢。
    """
    usable = _ensure_web_png(path)
    try:
        from PIL import Image

        with Image.open(usable) as im:
            if im.mode not in ("RGBA", "LA", "P"):
                return usable
            rgba = im.convert("RGBA")
            if rgba.getextrema()[3][0] == 255:  # 没有透明像素，不用动
                return usable
            out = os.path.splitext(usable)[0] + "_w.png"
            if not os.path.exists(out):
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                bg.save(out, "PNG")
            return out
    except Exception:  # noqa: BLE001 - 转不了就退回原图，不能因此丢公式
        return usable


def collect_targets(db, *, quiz_ids: Optional[List[int]] = None, limit: int = 0) -> List[dict]:
    """筛出「单选 + 选项不足 4 项 + 有来源标签」的题。"""
    from sqlalchemy import text as sqltext

    rows = db.execute(sqltext("""
        select id, coalesce(subject,''), coalesce(content,''),
               coalesce(options::text,'[]'), coalesce(source_label,'')
        from quiz_questions
        where question_type = 'single'
          and options is not null
          and jsonb_array_length(options) < 4
          and coalesce(source_label,'') <> ''
        order by source_label, id
    """)).fetchall()
    out: List[dict] = []
    for qid, subj, content, options_json, label in rows:
        if quiz_ids and qid not in quiz_ids:
            continue
        try:
            opts = json.loads(options_json)
        except (ValueError, TypeError):
            continue
        if not isinstance(opts, list):
            continue
        out.append({
            "id": qid, "subject": subj, "content": content,
            "options": opts, "label": label,
        })
    if limit:
        out = out[:limit]
    return out


def _guard(
    db_opts: Dict[str, str], doc_plain: Dict[str, str],
) -> Tuple[str, str]:
    """判定能否安全写库。返回 ``(守卫名, 说明)``，守卫名为空表示没过。

    ``db_opts`` 是库里已有的 key→文本；``doc_plain`` 是 docx 四段 key→纯文本。
    """
    missing = [k for k in KEYS if k not in db_opts]
    if not missing:
        return "", "库里已是 4 项"
    if any(k not in doc_plain for k in db_opts):
        return "", "库里有 docx 不存在的 key"

    # ---- G1 逐项精确 ----
    # 库里每一项都必须与 docx 对应段逐字相同（空白除外）。
    if all(_db_plain(db_opts[k]) == doc_plain[k] for k in db_opts):
        return "G1", f"已有 {len(db_opts)} 项逐项精确命中"

    # ---- G2 前缀拼接相等 ----
    # 库里已有选项（剥掉残余标记后）拼起来，必须等于 docx 前 N 段拼起来。
    # N 取库里项数，因为「整项丢失」既可能丢在尾部（157），也可能丢掉开头（不存在，
    # 开头丢失由 G1 负责）；用前缀比较同时覆盖「尾部丢失」与「尾部被合并」两种形态。
    n = len(db_opts)
    db_seq = "".join(_db_plain(_strip_merged_marks(db_opts[k])) for k in KEYS if k in db_opts)
    doc_seq = "".join(doc_plain[k] for k in KEYS[:n])
    if db_seq and db_seq == doc_seq:
        return "G2", f"已有 {n} 项拼接等于 docx 前 {n} 段"
    return "", f"逐项不等且拼接不等（库={db_seq[:40]!r} 源={doc_seq[:40]!r}）"


def _build_options(
    block: List[dict], db_opts: Dict[str, str], guard: str,
    latex_map: Dict[int, str], img_url: Dict[int, str], *,
    prefer: str = "tex", force_keys: frozenset = frozenset(),
) -> List[dict]:
    """渲染出 4 项候选选项。

    已有且无需改动的选项保留库里原文：守卫只证明「纯文本一致」，标点/空白可能有细微差异，
    没有理由去动没坏的项。需要改的只有两种——缺的项，以及带公式的项。

    G2 例外：G2 的成因就是「库里这项文本里塞了别人的标记」，必须按 docx 重写，
    否则残渣（``C．``）会留在库里。

    ``force_keys`` 里的 key 强制出图片：有些公式识别结果肉眼可辨是错的（单字符误读），
    任何字符串判据都抓不到，只能人工点名退回图片——见 ``--force-image``。
    """
    out: List[dict] = []
    for seg in block:
        key = seg["key"]
        if key in db_opts and not seg.get("markers") and guard == "G1" and key not in force_keys:
            out.append({"key": key, "text": db_opts[key]})
            continue
        seg_prefer = "image" if key in force_keys else prefer
        text, _n_mark, _n_tex = _render_markers(
            _rewrite_option_text(seg["text"]), latex_map, img_url, prefer=seg_prefer
        )
        out.append({"key": key, "text": text})
    return out


def _has_duplicate(cand: List[dict]) -> bool:
    """含公式的项里是否出现两项完全相同（公式识别塌陷的典型症状）。

    只比含公式的项：源题本身就可能有两项文字一样（比如都写「以上皆不是」），
    那是题目的问题，不该让本脚本判失败。
    """
    texts = [o["text"] for o in cand if o["text"] and ("$" in o["text"] or "![" in o["text"])]
    return len(texts) != len(set(texts))


def _short(text: str, n: int = _SHOW) -> str:
    t = (text or "").replace("\n", "\\n")
    return t if len(t) <= n else t[: n - 1] + "…"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="从源 docx 补全题库整项丢失/被合并的选项（默认干跑）"
    )
    ap.add_argument("--quiz-id", type=int, action="append", default=[],
                    help="只处理指定题目 id，可多次指定")
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少道")
    ap.add_argument("--apply", action="store_true", help="真写库（默认干跑）")
    ap.add_argument("--report", help="把逐题结果写成 JSON")
    ap.add_argument("--no-image-fallback", action="store_true",
                    help="公式识别失败时不留图片（默认留图）")
    ap.add_argument("--force-image", action="append", default=[], metavar="ID:KEY",
                    help="强制某个选项出图片而不出 LaTeX，形如 192:C，可多次指定。"
                         "用于识别结果肉眼可辨是错的、但任何字符串判据都抓不到的单字符误读")
    args = ap.parse_args()

    # ID:KEY → 该题需要强制走图片的选项字母
    force_image: Dict[int, set] = {}
    for spec in args.force_image:
        qid_s, _, key = spec.partition(":")
        key = key.strip().upper()
        try:
            qid = int(qid_s)
        except ValueError:
            ap.error(f"--force-image 格式应为 题号:选项字母，收到 {spec!r}")
        if key not in KEYS:
            ap.error(f"--force-image 的选项字母必须属于 A~D，收到 {spec!r}")
        force_image.setdefault(qid, set()).add(key)

    from database import SessionLocal
    from models import QuizQuestion

    db = SessionLocal()
    results: List[dict] = []
    try:
        targets = collect_targets(db, quiz_ids=args.quiz_id or None, limit=args.limit)
        print(f"[选项补全] 候选 {len(targets)} 道（single 且选项 < 4 且 source_label 非空）")
        if not targets:
            return 0

        from services.formula_latex import get_recognizer

        rec = get_recognizer()
        if not rec.available:
            print(f"[选项补全] 公式引擎不可用：{rec.load_error}")
            return 1

        groups: Dict[str, List[dict]] = {}
        for t in targets:
            groups.setdefault(t["label"], []).append(t)
        print(f"[选项补全] 涉及源文档 {len(groups)} 篇")

        img_root = os.path.join(_media_root(), "quiz_option")
        gi = 0
        for label, items in groups.items():
            gi += 1
            d = resolve_doc(db, label)
            if not d:
                for it in items:
                    it["status"] = "doc_not_found"
                    it["reason"] = "docx 未找到"
                    results.append(it)
                print(f"\n[{gi}/{len(groups)}] 未找到文档：{label[:60]}")
                continue

            t0 = time.time()
            try:
                res = parse_docx_with_images(d.file_path)
            except Exception as exc:  # noqa: BLE001 - 单篇失败不影响其它篇
                for it in items:
                    it["status"] = f"parse_failed: {exc}"
                    results.append(it)
                print(f"\n[{gi}/{len(groups)}] 解析失败：{label[:40]} {exc}")
                continue

            al = build_aligned(res)
            starts_p = _line_starts(al.plain)
            starts_m = _line_starts(al.marked)
            norm_plain, norm_idx = build_norm_index(al.plain)
            print(
                f"\n[{gi}/{len(groups)}] doc={d.id} 「{d.file_name[:36]}」 "
                f"plain={len(al.plain)} 公式={al.marked.count('[[F:')} "
                f"题={len(items)} 解析 {time.time() - t0:.1f}s"
            )

            # ---- 第一步：定位题干 + 切选项段（纯文本，不碰图） ----
            plans: List[Tuple[dict, List[dict], List[int]]] = []
            wanted: set = set()
            for it in sorted(items, key=lambda x: x["id"]):
                raw = it["content"]
                plain_needle = strip_rendered(raw)
                span = locate(al.plain, plain_needle, norm_plain, norm_idx)
                if not span and plain_needle:
                    span = locate_by_prefix(al.plain, plain_needle, norm_plain, norm_idx)
                if not span:
                    it["status"] = "stem_locate_failed"
                    it["reason"] = "题干在 docx 里定位失败"
                    results.append(it)
                    print(f"  quiz {it['id']}: stem_locate_failed")
                    continue

                # 行号在 plain / marked 两边严格对齐，用 plain 的行号索引 marked 的行首。
                # 不能用 plain_to_marked(span[1])：选项首字符正好压在占位符上时，
                # 会把该占位符算到片段之前，选项的第一个公式就丢了。
                line_i = _line_of(starts_p, span[1])
                block = find_option_block(
                    al.marked, starts_m, starts_m[line_i], max_run_index=1
                )
                if not block:
                    # 源 docx 里这一段只有 2~3 项（题目本身就是少项），或题干后紧跟
                    # 的不是 A~D 连续段。两种情况都不能补——补一版自己证明不了的选项
                    # 比留空更糟。
                    peek = _peek_option_keys(al.marked, starts_m, starts_m[line_i])
                    it["status"] = "option_block_not_found"
                    it["docx_keys"] = "".join(peek)
                    it["reason"] = (
                        f"docx 该题后选项依次为 {''.join(peek) or '（无标记）'}"
                        f"，凑不成连续 A~D"
                    )
                    results.append(it)
                    print(f"  quiz {it['id']}: option_block_not_found "
                          f"（源 docx 选项={''.join(peek) or '无'}）")
                    continue

                mids: List[int] = []
                for seg in block:
                    seg["markers"] = [int(m.group(1)) for m in MARKER_RE.finditer(seg["text"])]
                    mids.extend(seg["markers"])
                plans.append((it, block, mids))
                wanted.update(mids)

            if not plans:
                continue

            # ---- 第二步：只为真正被引用的公式图导出 + 识别 ----
            latex_map: Dict[int, str] = {}
            img_url: Dict[int, str] = {}
            rejected: List[Tuple[int, str, str]] = []
            if wanted:
                out_dir = os.path.join(img_root, str(d.id))
                res2 = parse_docx_with_images(
                    d.file_path, out_dir=out_dir, only_indices=wanted
                )
                images = {i.index: i for i in res2.images}
                for idx in sorted(wanted):
                    img = images.get(idx)
                    if not img or not img.out_path or not os.path.exists(img.out_path):
                        continue
                    # docx 里的公式图大量是透明底 GIF / 带 alpha 的 PNG：直接当 <img>
                    # 用在深色背景上会「黑底黑字」看不见，且 .gif 的 MIME 映射
                    # 依赖 Windows 注册表。统一转白底 PNG（识别仍用原图，
                    # 避免二次压缩影响精度）。
                    usable = _web_png(img.out_path)
                    url = (
                        f"/media/images/quiz_option/{d.id}/"
                        f"{os.path.basename(usable)}"
                    )
                    if args.no_image_fallback:
                        url = ""
                    if url:
                        img_url[idx] = url
                    r = rec.recognize(img.out_path)
                    if r.ok and r.latex:
                        tex = sanitize_latex(r.latex)
                        why = _suspect(tex)
                        if why:
                            rejected.append((idx, why, tex))
                            continue
                        latex_map[idx] = tex
                print(
                    f"        公式图导出 {sum(1 for i in res2.images if i.out_path)} 张 → "
                    f"LaTeX {len(latex_map)} / 可用图片 {len(img_url)} / "
                    f"判定不可信 {len(rejected)}"
                )
                for idx, why, tex in rejected[:3]:
                    print(f"        退图片 #{idx}: {why}  {tex[:60]!r}")

            # ---- 第三步：守卫判定 + 渲染 ----
            for it, block, _mids in plans:
                db_opts = {
                    str(o.get("key", "")).upper(): str(o.get("text", ""))
                    for o in it["options"]
                }
                doc_plain = {seg["key"]: _seg_plain(seg) for seg in block}
                guard, why = _guard(db_opts, doc_plain)
                it["run_index"] = block[0].get("run_index")
                it["doc_plain"] = doc_plain
                it["db_opts"] = db_opts
                if not guard:
                    it["status"] = "guard_failed"
                    it["reason"] = why
                    results.append(it)
                    continue

                forced = frozenset(force_image.get(it["id"], ()))
                cand = _build_options(
                    block, db_opts, guard, latex_map, img_url, force_keys=forced
                )
                # 四项里有重复文本 → 多半是公式识别塌陷（两个公式认成同一串），
                # 整题退图片。错的 LaTeX 比图片有害。
                if _has_duplicate(cand) and img_url:
                    cand = _build_options(
                        block, db_opts, guard, latex_map, img_url,
                        prefer="image", force_keys=forced,
                    )
                    it["fallback"] = "duplicate"
                if _has_duplicate(cand):
                    it["status"] = "guard_failed"
                    it["reason"] = "四项出现重复文本"
                    results.append(it)
                    continue
                if forced:
                    it["force_image"] = sorted(forced)

                it["candidate"] = cand
                it["guard"] = guard
                it["status"] = "ok"
                it["reason"] = why
                results.append(it)

        # ---- 汇总 ----
        ok_items = [r for r in results if r.get("status") == "ok"]
        from collections import Counter

        cnt = Counter(r.get("status", "?") for r in results)
        print(f"\n[选项补全] 可补 {len(ok_items)} / 候选 {len(results)} 道")
        for k, v in cnt.most_common():
            print(f"        {k}: {v}")
        gcnt = Counter(r.get("guard") for r in ok_items)
        for k in ("G1", "G2"):
            print(f"        守卫 {k}: {gcnt.get(k, 0)} 道")
        # 「找不到连续 A~D」的题单独按 docx 里实际有的选项分布列一下：
        # 这一批不是脚本没能力补，而是**源 docx 本身就只有 2~3 项**，补不了也不该补。
        kcnt = Counter(r.get("docx_keys", "") for r in results
                       if r.get("status") == "option_block_not_found")
        if kcnt:
            print("        其中源 docx 选项不足 4 项：" +
                  "，".join(f"{k or '无标记'}={v} 道" for k, v in kcnt.most_common()))

        # 逐题打印全部候选（team-lead 要核对每一条，不做 show 限制）
        for r in results:
            if r.get("status") != "ok":
                print(f"\n跳过 quiz {r['id']} [{r.get('subject','')}] "
                      f"{r['status']}：{r.get('reason','')}")
                continue
            before = r["db_opts"]
            print(
                f"\nquiz {r['id']} [{r.get('subject','')}] "
                f"{len(before)} 项 → 4 项 | 守卫 {r['guard']} | "
                f"run_index={r['run_index']} | {r.get('fallback','')}"
            )
            for o in r["candidate"]:
                old = before.get(o["key"])
                old_s = "（缺失）" if old is None else repr(_short(old))
                print(f"  {o['key']} BEFORE {old_s}")
                print(f"  {o['key']} AFTER  {_short(o['text'])!r}")

        if args.report:
            with open(args.report, "w", encoding="utf-8") as fh:
                json.dump(results, fh, ensure_ascii=False, indent=1)
            print(f"\n[选项补全] 报告已写入 {args.report}")

        if args.apply:
            if not ok_items:
                print("[选项补全] 没有可写库的题")
                return 0
            from services.backup_service import create_backup

            backup = create_backup()
            print(f"[选项补全] 已备份：{backup}")
            n = 0
            for r in ok_items:
                q = db.get(QuizQuestion, r["id"])
                if not q:
                    continue
                q.options = r["candidate"]
                db.commit()  # 逐条提交：中途失败不会把已确认的题一起回滚
                n += 1
                print(f"[选项补全] 已写 quiz {r['id']}（守卫 {r['guard']}）")
            print(f"[选项补全] 已写库 {n} 道")
        elif ok_items:
            print("\n[选项补全] 干跑结束，加 --apply 才会写库")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
