"""为 kaoyan_schools 补全研招网 schId（按校名查研招网院校库搜索页）。

用途：backfill_school_intro.py 的第 2 层（研招网简介）依赖 schId，
但库内 official_url/tags 多数不含 schId，导致大量院校「无可用映射」。
本脚本按校名调用研招网公开搜索接口，解析出 schId 并写回 tags.yz_schid，
不写任何编造内容。

用法：
    python scripts/fill_chsi_schid.py            # dry-run，只统计
    python scripts/fill_chsi_schid.py --apply    # 写库
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "..", "database", "kaoyan.db")
DB_PATH = os.path.abspath(DB_PATH)

SEARCH_URL = "https://yz.chsi.com.cn/sch/search.do"
TIMEOUT = int(os.environ.get("SCHID_TIMEOUT", "15"))
WORKERS = int(os.environ.get("SCHID_WORKERS", "6"))

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_ITEM_RE = re.compile(
    r'<a class="name[^"]*" href="/sch/schoolInfo--schId-(\d+)\.dhtml"[^>]*>\s*'
    r'([^<]+?)\s*</a>',
    re.S,
)


def _fetch(url: str, timeout: int = TIMEOUT) -> str:
    import urllib.request

    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        for enc in ("utf-8", "gb18030"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _norm(s: str) -> str:
    return re.sub(r"[\s\(\)（）·、,，.。\-—_/]", "", s or "")


def search_schid(name: str) -> Tuple[str, str]:
    """按校名搜索研招网院校库，返回 (schId, 命中的研招网校名)。"""
    qs = urllib.parse.urlencode({"searchType": "1", "yxmc": name})
    html = _fetch(f"{SEARCH_URL}?{qs}")
    if not html:
        return "", ""
    target = _norm(name)
    cands: List[Tuple[str, str]] = []
    for sid, nm in _ITEM_RE.findall(html):
        cands.append((sid, _norm(nm)))
    if not cands:
        return "", ""
    # 1) 精确命中
    for sid, nm in cands:
        if nm == target:
            return sid, nm
    # 2) 去掉「（中外合作办学）」等后缀再比
    short = _norm(re.sub(r"[（(].*?[)）]", "", name))
    for sid, nm in cands:
        if nm == short:
            return sid, nm
    # 3) 包含关系（取最长匹配，避免「北京大学」命中「北京大学医学部」错配）
    hits = [(sid, nm) for sid, nm in cands if short and (short in nm or nm in short)]
    if hits:
        hits.sort(key=lambda x: -len(x[1]))
        return hits[0][0], hits[0][1]
    return "", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    rows = cur.execute(
        "SELECT id, name, official_url, tags FROM kaoyan_schools ORDER BY id"
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    targets: List[tuple] = []
    for sid, name, ourl, tags in rows:
        if str(ourl or "").strip().isdigit():
            continue
        if tags:
            try:
                d = json.loads(tags)
                if isinstance(d, dict) and d.get("yz_schid"):
                    continue
            except (json.JSONDecodeError, TypeError):
                pass
        targets.append((sid, name, ourl, tags))

    print(f"待解析 schId: {len(targets)} 所（apply={args.apply}）\n")

    done = [0]
    ok: List[Dict] = []
    fail: List[Dict] = []

    def one(row):
        sid, name, ourl, tags = row
        chsi_id, hit = search_schid(name)
        done[0] += 1
        return sid, name, ourl, tags, chsi_id, hit

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for sid, name, ourl, tags, chsi_id, hit in pool.map(one, targets):
            if chsi_id:
                print(f"[{done[0]}/{len(targets)}] ✓ {name} → {chsi_id} ({hit})")
                ok.append({"id": sid, "name": name, "schId": chsi_id, "hit": hit})
            else:
                print(f"[{done[0]}/{len(targets)}] ✗ {name}")
                fail.append({"name": name})
            time.sleep(0)

    print(f"\n解析成功 {len(ok)}，失败 {len(fail)}")

    if args.apply and ok:
        upd = 0
        for item in ok:
            sid = item["id"]
            row = cur.execute("SELECT tags FROM kaoyan_schools WHERE id=?",
                              (sid,)).fetchone()
            data = {}
            if row and row[0]:
                try:
                    d = json.loads(row[0])
                    if isinstance(d, dict):
                        data = d
                except (json.JSONDecodeError, TypeError):
                    data = {}
            data["yz_schid"] = item["schId"]
            cur.execute("UPDATE kaoyan_schools SET tags=? WHERE id=?",
                        (json.dumps(data, ensure_ascii=False), sid))
            upd += 1
        con.commit()
        print(f"已写库 {upd} 所")

    # 落盘映射供后续复用
    out = os.path.join(BASE_DIR, "data", "chsi_schid_map.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    prev: Dict[str, str] = {}
    if os.path.exists(out):
        try:
            prev = json.load(open(out, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = {}
    for item in ok:
        prev[item["name"]] = item["schId"]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(prev, f, ensure_ascii=False, indent=2)
    print(f"映射已存: {out}（共 {len(prev)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
