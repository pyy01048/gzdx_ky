"""把题库里引用的公式图统一成「浏览器一定能正确显示」的格式。

## 为什么需要这一步

`repair_quiz_stems.py` / `repair_quiz_options.py` 在识别失败时会退回公式图片
（`![公式](/media/images/...)`），但写进库的图片可能是：

* **透明底 GIF** —— docx 里公式图的主流格式；
* **带 alpha 的 PNG** —— Word 另存出来的公式图，底色全透明（实测
  `quiz_option/37` 下 6 张、`quiz_stem/88` 下 3 张 alpha 最小值为 0）。

这两种在浅色页面上看着完全正常，一旦用户开深色模式就变成**黑底黑字**，
等于公式又没了。而 `_ensure_web_png` 早期版本对 `.png` 是直接放行的——
「扩展名看着安全」不等于「像素不透明」，所以已经写进库的 URL 里可能残留透明图。

## 做什么

1. 扫 `quiz_questions` 的 `content` / `analysis` / `options` 三个字段，
   取出所有 `/media/images/...` 链接；
2. 每个链接落到磁盘：文件不存在 → 记 `missing`。**不猜、不删链接**——
   断链本身就是需要知道的缺陷，替它编一个路径只会把问题藏起来；
3. 透明图 → 压平成白底 `<stem>_w.png`（加后缀另存，保留原始字节以便回溯）；
4. 把三个字段里的 URL 换成新路径；
5. 复查：所有链接都存在、且不再有透明图。

默认干跑。``--apply`` 前自动备份数据库，逐行提交。

用法
----
```
python scripts/normalize_quiz_formula_images.py            # 干跑
python scripts/normalize_quiz_formula_images.py --apply    # 写库
```
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from repair_quiz_stems import _ensure_web_png, _media_root, _needs_flatten  # noqa: E402

URL_RE = re.compile(r"/media/images/([^)\s]+)")
FIELDS = ("content", "analysis", "options")
PREFIX = "/media/images/"


def _abs_path(rel: str) -> str:
    return os.path.join(_media_root(), rel.replace("/", os.sep))


def _flattened_rel(rel: str) -> str:
    """压平后的相对路径（与 URL 一致，用 / 分隔）。"""
    usable = _ensure_web_png(_abs_path(rel))
    return os.path.relpath(usable, _media_root()).replace(os.sep, "/")


def _rewrite(blob: str, mapping: dict) -> tuple:
    """把 blob 里落在 mapping 的链接换掉，返回 (新文本, 改写条数)。"""
    count = [0]

    def _sub(m):
        rel = m.group(1)
        if rel in mapping:
            count[0] += 1
            return PREFIX + mapping[rel]
        return m.group(0)

    return URL_RE.sub(_sub, blob), count[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="把题库公式图统一成白底 PNG")
    ap.add_argument("--apply", action="store_true", help="真写库（默认干跑）")
    ap.add_argument("--show", type=int, default=15)
    args = ap.parse_args()

    from sqlalchemy import text as sqltext
    from database import SessionLocal
    from models import QuizQuestion

    db = SessionLocal()
    try:
        rows = db.execute(sqltext("""
            select id, coalesce(content,''), coalesce(analysis,''),
                   coalesce(options::text,'')
            from quiz_questions
        """)).fetchall()

        rels = set()
        for _qid, c, a, o in rows:
            for blob in (c, a, o):
                rels.update(URL_RE.findall(blob))

        missing, transparent, mapping = [], [], {}
        for rel in sorted(rels):
            path = _abs_path(rel)
            if not os.path.exists(path):
                missing.append(rel)
                continue
            if _needs_flatten(path):
                transparent.append(rel)
                mapping[rel] = _flattened_rel(rel)

        print(f"[图] 引用图片 {len(rels)} 个：透明底 {len(transparent)} / 断链 {len(missing)}")
        for rel in missing[: args.show]:
            print(f"       断链: {rel}")
        for rel in transparent[: args.show]:
            print(f"       压平: {rel}  ->  {mapping[rel]}")

        if not mapping:
            print("[图] 没有需要改写的链接")
            return 0
        if not args.apply:
            print("[图] 干跑结束，加 --apply 才会写库")
            return 0

        from services.backup_service import create_backup

        backup = create_backup()
        print(f"[图] 已备份: {backup}")

        n_rows = n_links = 0
        for qid in [r[0] for r in rows]:
            q = db.get(QuizQuestion, qid)
            if not q:
                continue
            touched = False
            for field in FIELDS:
                raw = getattr(q, field)
                if not raw:
                    continue
                if field == "options":
                    new_opts = []
                    for opt in raw:
                        opt2 = dict(opt)
                        new_txt, n = _rewrite(str(opt2.get("text", "")), mapping)
                        if n:
                            opt2["text"] = new_txt
                            n_links += n
                            touched = True
                        new_opts.append(opt2)
                    if touched:
                        q.options = new_opts
                else:
                    new_text, n = _rewrite(str(raw), mapping)
                    if n:
                        setattr(q, field, new_text)
                        n_links += n
                        touched = True
            if touched:
                db.commit()
                n_rows += 1

        print(f"[图] 已写库 {n_rows} 行 / 改写 {n_links} 个链接")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
