"""修复题库**选项**里被丢弃的公式（从源 docx 精准重取）。

背景
----
题干和解析已经修过两轮（见 ``scripts/repair_quiz_stems.py``），但**选项从来没人修**。
数据探查的证据很直接：

    select count(*) from quiz_questions where options::text like '%$%';
    --> 0

386 道题、1509 个选项里，**一个 LaTeX 都没有**。旧入库管线把选项段落里的公式图片
整段丢掉，只剩标点：

    A．，，    B．，，    C．，，    D．，，

这些题等于没有选项，用户只能靠猜。纯标点的选项实测 17 个、涉及 5 道题；
但损害远不止这 17 个——像「$R_1$和$R_2$串联」，丢掉公式后剩下「和串联」，
看着像字，其实是残句，任何**基于库内文本**的判据都抓不到。

## 为什么判据必须回源 docx

因为「残缺」在选项上没有可靠文本特征：

    残缺 ：「，」「，，」「和串联」
    正常 ：「0」「1」「发散」「电压」「①②」

「，」和「和串联」都是残缺，但「0」「发散」是正常选项。所以本脚本不猜，
而是**全量扫所有有 source_label 的题**，逐题回源看 docx 里那一段本来有没有
``[[F:n]]`` 占位符——有、而库里没有，就是被丢了。

## 方法

1. 用题干（已修复的 ``content``，剥掉 ``$...$`` 还原成 plain）在 ``aligned.plain``
   里定位，拿到题干在 docx 里的位置；
2. 从题干行往后扫若干行，找连续的 ``A．/B．/C．/D．`` 选项段（支持四个选项各占
   一行，也支持一行里并排写 ``A．… B．…``）；
3. 每段的 plain 区间用 ``AlignedText.plain_to_marked`` 换到 marked 区间，
   取出这段里的 ``[[F:n]]`` 占位符；
4. 占位符 → 公式图 → ``formula_latex`` 识别成 LaTeX；识别失败退**图片**，
   再失败保留占位符（前端会渲染成醒目小标记，不静默丢）；
5. **对照校验**：docx 这段去掉占位符后的纯文本，必须与库里该选项的文本一致
   （或互相包含）。不一致就跳过——题干定位错位时宁可不动，绝不写坏别的选项；
6. 默认干跑打印 before/after，``--apply`` 才写库。

用法
----
```
python scripts/repair_quiz_options.py                  # 干跑，看能修多少
python scripts/repair_quiz_options.py --quiz-id 293    # 只看指定题
python scripts/repair_quiz_options.py --apply          # 真写库
python scripts/repair_quiz_options.py --report /tmp/o.json
```
"""
from __future__ import annotations

import argparse
import bisect
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
# 语义级误识别门（\prod 误认多重积分、微分元被多加上标、空 \bar{}）
# 放在 services 层是因为题干/解析那条链路也要用同一套判据——
# 之前只有本脚本做这道检查，等于一半的公式没有语义校验。
from services.formula_latex import latex_suspect  # noqa: E402
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

# 选项起始标记：A． / B. / C、 / D）
# 只在行首、或前面隔了 2 个以上空格时才认（防止题干里的 "A．" 字样被误当选项）
OPTION_MARK_RE = re.compile(r"([A-D])\s*[．.、\)）]")
_LINE_END = "\n"

# 题干之后往下看多少行找选项段（多选题四个选项各一行，只需 4 行；
# 留 18 行是因为中间常夹着「图8-1」这类图注行）
SCAN_WINDOW = 18
# 选项片段长度上限，超了说明片段跨到了别的内容
MAX_OPTION_PLAIN = 200



def _line_starts(text: str) -> List[int]:
    """每行起始偏移。"""
    starts = [0]
    for i, ch in enumerate(text):
        if ch == _LINE_END:
            starts.append(i + 1)
    return starts


def _line_of(starts: List[int], pos: int) -> int:
    return max(0, bisect.bisect_right(starts, pos) - 1)


def _line_span(starts: List[int], text: str, i: int) -> Tuple[int, int]:
    s = starts[i]
    e = starts[i + 1] - 1 if i + 1 < len(starts) else len(text)
    return s, e


def find_option_block(
    text: str, starts: List[int], from_pos: int, *, window: int = SCAN_WINDOW,
    max_run_index: Optional[int] = None,
) -> Optional[List[Dict]]:
    """在 ``from_pos`` 之后找连续的 A/B/C/D 选项段。

    传进来的 ``text`` 必须是 **marked 文本**（带 ``[[F:n]]`` 占位符）：选项的
    公式是图片，去掉占位符之后选项只剩标点，**没有**任何东西可以用来判断
    「这一段到哪儿为止」，只有在带占位符的文本上切才能拿到完整的公式序列。

    ``max_run_index``：只接受「A~D 这一串在命中序列里的起始下标不超过此值」的段。
    默认 ``None``（不限制）。补全缺失选项时必须传 ``1`` 这类收紧值——
    一道库里只有 A、B 两项的题，紧跟其后的**下一题**选项会产生
    ``[A,B, A,B,C,D]`` 的命中序列，不收紧就会把下一题的选项当成自己的。

    返回 ``[{"key","start","end","text"}, ...]``，找不到返回 ``None``。
    """
    i0 = _line_of(starts, from_pos)
    hits: List[Tuple[str, int, int, int]] = []  # (key, 字母位置, 片段起点, 行号)
    for j in range(i0, min(len(starts), i0 + window)):
        s, e = _line_span(starts, text, j)
        line = text[s:e]
        for m in OPTION_MARK_RE.finditer(line):
            before = line[: m.start()]
            # 行首，或前面有 2 个以上空白（并排写法）
            if before.strip() and not before.endswith("  "):
                continue
            hits.append((m.group(1), s + m.start(), s + m.end(), j))
        # 已经凑够 A~D 就不用再往下扫了
        if len(hits) >= 4:
            keys = [h[0] for h in hits]
            if any(keys[k : k + 4] == ["A", "B", "C", "D"] for k in range(len(keys) - 3)):
                break

    for k in range(len(hits) - 3):
        if max_run_index is not None and k > max_run_index:
            continue
        if [hits[k + t][0] for t in range(4)] != ["A", "B", "C", "D"]:
            continue
        block: List[Dict] = []
        for t in range(4):
            key, _lpos, seg_start, line_idx = hits[k + t]
            nxt = hits[k + t + 1] if k + t + 1 < len(hits) else None
            if nxt and nxt[3] == line_idx:
                seg_end = nxt[1]  # 同一行：切到下一个字母
            else:
                _, line_end = _line_span(starts, text, line_idx)
                seg_end = line_end
            if seg_end - seg_start > MAX_OPTION_PLAIN:
                break
            block.append({
                "key": key, "start": seg_start, "end": seg_end,
                "text": text[seg_start:seg_end],
            })
        if len(block) == 4:
            block[0]["run_index"] = k
            return block
    return None


def _render_markers(
    slice_marked: str, latex_map: Dict[int, str], img_url: Dict[int, str], *, prefer: str = "tex"
) -> Tuple[str, int, int]:
    """把片段里的 ``[[F:n]]`` 换成 ``$tex$`` / ``![公式](url)`` / 原样保留。

    ``prefer="image"`` 时只要有图就用图（识别结果被判定不可信时走这条）。
    返回 ``(新文本, 占位符数, 出 LaTeX 数)``。
    """
    stats = {"n": 0, "tex": 0}

    def _repl(m: "re.Match[str]") -> str:
        idx = int(m.group(1))
        stats["n"] += 1
        tex = (latex_map.get(idx) or "").strip()
        url = img_url.get(idx)
        if prefer == "image" and url:
            return f"![公式]({url})"
        if tex:
            stats["tex"] += 1
            return f"${tex}$"
        if url:
            return f"![公式]({url})"
        return m.group(0)

    return MARKER_RE.sub(_repl, slice_marked), stats["n"], stats["tex"]


def _rewrite_option_text(marked_slice: str) -> str:
    """去掉片段的 ``A．`` 前缀与首尾空白。"""
    return re.sub(r"^\s*[A-D]\s*[．.、\)）]\s*", "", marked_slice).strip()


def collect_targets(db, *, quiz_ids: Optional[List[int]] = None, limit: int = 0) -> List[dict]:
    from sqlalchemy import text as sqltext

    rows = db.execute(sqltext("""
        select id, coalesce(subject,''), coalesce(content,''),
               coalesce(options::text,''), coalesce(source_label,'')
        from quiz_questions
        where coalesce(source_label,'') <> ''
          and options is not null
        order by id
    """)).fetchall()
    out: List[dict] = []
    for qid, subj, content, options_json, label in rows:
        if quiz_ids and qid not in quiz_ids:
            continue
        try:
            opts = json.loads(options_json)
        except (ValueError, TypeError):
            continue
        if not isinstance(opts, list) or not opts:
            continue
        out.append({
            "id": qid, "subject": subj, "content": content,
            "options": opts, "label": label,
        })
    if limit:
        out = out[:limit]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="从源 docx 精准重取题库**选项**里丢失的公式")
    ap.add_argument("--quiz-id", type=int, action="append", default=[])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true", help="真写库（默认干跑）")
    ap.add_argument("--report", help="导出 JSON 报告")
    ap.add_argument("--show", type=int, default=12, help="最多打印多少条对比")
    ap.add_argument("--no-image-fallback", action="store_true", help="识别失败不留图片")
    args = ap.parse_args()

    from database import SessionLocal
    from models import QuizQuestion

    db = SessionLocal()
    try:
        targets = collect_targets(db, quiz_ids=args.quiz_id or None, limit=args.limit)
        print(f"[选项] 待扫描题 {len(targets)} 道")
        if not targets:
            return 0

        from services.formula_latex import get_recognizer

        rec = get_recognizer()
        if not rec.available:
            print(f"[选项] 公式引擎不可用：{rec.load_error}")
            return 1

        groups: Dict[str, List[dict]] = {}
        for t in targets:
            groups.setdefault(t["label"], []).append(t)
        print(f"[选项] 涉及源文档 {len(groups)} 篇")

        media = _media_root()
        img_root = os.path.join(media, "quiz_option")
        results: List[dict] = []
        gi = 0
        for label, items in groups.items():
            gi += 1
            d = resolve_doc(db, label)
            if not d:
                for it in items:
                    it["status"] = "doc_not_found"
                    results.append(it)
                print(f"\n[{gi}/{len(groups)}] 未找到文档: {label[:50]}")
                continue

            t0 = time.time()
            try:
                res = parse_docx_with_images(d.file_path)
            except Exception as exc:  # noqa: BLE001 - 单篇失败不影响其它
                for it in items:
                    it["status"] = f"parse_failed: {exc}"
                    results.append(it)
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

            # ---- 第一步：定位题干 + 圈出选项段（纯文本计算，不碰图） ----
            plans: List[Tuple[dict, List[Dict], List[int]]] = []
            wanted: set = set()
            for it in sorted(items, key=lambda x: x["id"]):
                raw = it["content"]
                span = locate(al.plain, raw, norm_plain, norm_idx)
                if not span:
                    sp = strip_rendered(raw)
                    if sp and sp != raw:
                        span = locate(al.plain, sp, norm_plain, norm_idx)
                if not span:
                    sp = strip_rendered(raw)
                    span = locate_by_prefix(al.plain, sp or raw, norm_plain, norm_idx)
                if not span:
                    it["status"] = "stem_locate_failed"
                    results.append(it)
                    continue
                # 从题干**所在行**的行首开始找选项。
                # 注意：不能拿 plain_to_marked(span[1]) 当起点去切 marked——
                # 选项首字符正好压在占位符上时，plain_to_marked 会把该占位符算到
                # 片段之前（`core_start <= core_pos` 是闭区间），选项的第一个公式就丢了。
                # 实测 quiz 352 四个选项各丢一个 ∬，A/C 因此塌成同一串。
                # 行号是两边严格对齐的，所以用 plain 的行号去索引 marked 的行首是安全的。
                line_i = _line_of(starts_p, span[1])
                block = find_option_block(al.marked, starts_m, starts_m[line_i])
                if not block:
                    it["status"] = "option_block_not_found"
                    results.append(it)
                    continue
                mids: List[int] = []
                for seg in block:
                    seg["markers"] = [int(m.group(1)) for m in MARKER_RE.finditer(seg["text"])]
                    mids.extend(seg["markers"])
                plans.append((it, block, mids))
                wanted.update(mids)

            if not plans:
                continue

            # ---- 第二步：只为「确实有占位符」的图导出 + 识别 ----
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
                    if not img or not img.out_path:
                        continue
                    if not os.path.exists(img.out_path):
                        continue
                    # 图片 URL 对**每个**导出成功的公式都建：质量门判定识别不可信时
                    # 要能整题退图片，不能等到那时才发现没 URL
                    # 白底 PNG：docx 里的公式图大量是透明底 .gif，直接当 <img>
                    # 用在深色背景上会变成「黑底黑字」，而且 Windows 下 .gif 的
                    # MIME 映射来自注册表，不一定可靠。统一转格式后再写 URL。
                    usable = _ensure_web_png(img.out_path)
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
                        why = latex_suspect(tex)
                        if why:
                            rejected.append((idx, why, tex))
                            continue
                        latex_map[idx] = tex
                print(
                    f"        公式图 {len(images)} 张 → LaTeX {len(latex_map)} / "
                    f"可用图片 {len(img_url)} / 判定不可信 {len(rejected)}"
                )
                for idx, why, tex in rejected[:3]:
                    print(f"        退图片 #{idx}: {why}  {tex[:60]!r}")

            # ---- 第三步：逐题逐选项渲染 + 对照校验 ----
            for it, block, mids in plans:
                db_opts = {str(o.get("key", "")).upper(): str(o.get("text", "")) for o in it["options"]}
                bad_key = next((s["key"] for s in block if s["key"] not in db_opts), "")
                if bad_key:
                    it["status"] = f"key_mismatch:{bad_key}"
                    results.append(it)
                    continue

                def _build(prefer: str) -> Tuple[List[dict], int, int, int, List[str]]:
                    outs: List[dict] = []
                    n_changed = n_guard = n_tex = n_mark = 0
                    with_marker: List[str] = []
                    for seg in block:
                        key = seg["key"]
                        old_text = db_opts[key]
                        new_text, k_mark, k_tex = _render_markers(
                            _rewrite_option_text(seg["text"]), latex_map, img_url, prefer=prefer
                        )
                        n_mark += k_mark
                        n_tex += k_tex
                        if k_mark:
                            with_marker.append(key)
                        # 没有公式的选项一律保持库里的原样。
                        # 顺手把 4 个选项都按 docx 重写是危险的：docx 段落和库里的
                        # 选项在标点/空白上可能有细微差异，我们没理由去改本来没坏的选项。
                        if not k_mark:
                            outs.append({"key": key, "text": old_text})
                            continue
                        # 对照校验：docx 这段去掉占位符后的纯文本必须**精确等于**库里
                        # 该选项的文本。这里不能放宽成「包含」——选项跨行折行时
                        # 片段会被截断，而截断的前缀恰好是库内文本的前缀，
                        # 用包含判据会放行，最后写进去的是半截选项。
                        doc_plain = norm(strip_markers(seg["text"]))
                        doc_plain = norm(re.sub(r"^[A-D]\s*[．.、\)）]", "", doc_plain))
                        if not old_text or doc_plain != norm(old_text):
                            n_guard += 1
                            outs.append({"key": key, "text": old_text})
                            continue
                        if "$" not in old_text and "![" not in old_text:
                            n_changed += 1
                        outs.append({"key": key, "text": new_text})
                    return outs, n_changed, n_guard, n_tex, with_marker

                cand, changed, guarded, tex_n, with_marker = _build("tex")
                # ---- 质量门：同一题里不该有两项被识别成同一串 ----
                # quiz 352 的 A/C 曾被识别成同一串 \prod...x^2dydz^2（∬ 塌成 \prod），
                # 说明这题的识别不可信。整题退图片——错的 LaTeX 比图片有害得多。
                # 只比较**含公式**的选项：不含公式的那几项是原样保留的，
                # 源题本身就可能有两项文字相同，不该因此连坐。
                texts = [o["text"] for o in cand if o["key"] in with_marker and o["text"]]
                if len(texts) != len(set(texts)) and img_url:
                    cand, changed, guarded, tex_n, with_marker = _build("image")
                    it["fallback"] = "duplicate"
                it["markers"] = sum(len(s["markers"]) for s in block)
                it["latex_ok"] = tex_n
                it["changed"] = changed
                it["guarded"] = guarded
                it["candidate"] = cand
                it["status"] = "ok" if changed else "no_change"
                results.append(it)

        # ---- 汇总 ----
        ok_items = [r for r in results if r.get("status") == "ok"]
        print(
            f"\n[选项] 扫描 {len(results)} 道，需要修复 {len(ok_items)} 道，"
            f"改动选项 {sum(r.get('changed', 0) for r in ok_items)} 个"
        )
        from collections import Counter

        cnt = Counter(r.get("status", "?") for r in results)
        for k, v in cnt.most_common():
            print(f"        {k}: {v}")

        for r in ok_items[: args.show]:
            print(f"\n--- quiz {r['id']} [{r['subject']}] 选项改 {r['changed']} 个 "
                  f"公式 {r['latex_ok']}/{r['markers']} 守卫拦截 {r['guarded']} ---")
            old_map = {str(o.get("key", "")).upper(): str(o.get("text", "")) for o in r["options"]}
            for o in r["candidate"]:
                if old_map.get(o["key"]) != o["text"]:
                    print(f"  {o['key']} BEFORE: {old_map.get(o['key'], '')[:80]!r}")
                    print(f"  {o['key']} AFTER : {o['text'][:140]!r}")

        if args.report:
            with open(args.report, "w", encoding="utf-8") as fh:
                json.dump(results, fh, ensure_ascii=False, indent=1)
            print(f"\n[选项] 报告已写入 {args.report}")

        if args.apply:
            if not ok_items:
                print("[选项] 没有需要写库的题")
                return 0
            from services.backup_service import create_backup

            backup = create_backup()
            print(f"[选项] 已备份: {backup}")
            n = 0
            for r in ok_items:
                q = db.get(QuizQuestion, r["id"])
                if not q:
                    continue
                q.options = r["candidate"]
                n += 1
            db.commit()
            print(f"[选项] 已写库 {n} 道")
        elif ok_items:
            print("[选项] 干跑结束，加 --apply 才会写库")
        return 0

    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
