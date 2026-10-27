# -*- coding: utf-8 -*-
"""
第二轮精确清理：仅删「确认无实质内容」的残留文档。

背景：cleanup_lowvalue.py 的文件名规则把「艾宾浩斯抗遗忘打卡」整类硬保护了，
但实测其内容差异极大：
  - #842 / #1249 / #1931 艾宾浩斯核心词：分别含 862 / 141 / 475 个真实英文单词 → **保留**
  - #889 / #1295 / #1897 词汇闪过打卡表：仅含 8 次 "OCR" 字样，0 个词汇 → 纯广告页 → **删**
另有：
  - #1626 数学答题卡：856 字条形码/注意事项 → 无试题内容 → **删**
  - #2330 康华光课程表1.jpg：42 字乱码 → **删**
  - #2397 / #2398 日/月计划表空白版：正文为二进制乱码（.doc 未解析）→ **删**
  - #397 空文档（正文 0 字）→ **删**

判据以**实际内容**为准，不看文件名。
"""
from pathlib import Path
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.delete_guard import require_physical_delete_enabled  # noqa: E402

# 路径按本文件位置推导（P0-B2：拆除机器专属绝对路径绑定）
_REPO = Path(__file__).resolve().parents[2]
DB = str(_REPO / "database" / "kaoyan.db")
BACKUP_DIR = str(_REPO / "data" / "backups")
KB = str(_REPO / "knowledge_base")
TRASH_ROOT = os.path.join(KB, "_trash")

# 已逐条人工核验的残留文档 id
DELETE_IDS = [1626, 397, 889, 1295, 1897, 2330, 2397, 2398]
KEEP_IDS_NOTE = {842: "862个真实英文词", 1249: "141个真实英文词",
                 1931: "475个真实英文词"}

APPLY = "--apply" in sys.argv


def assess(doc_id, name, content):
    """基于内容判定，输出 (delete?, reason)"""
    text = content or ""
    n_words = len(set(w.lower() for w in re.findall(r"[a-zA-Z]{3,}", text)))
    if len(text.strip()) == 0:
        return True, "正文为空"
    if "答题卡" in name or "答题纸" in name:
        return True, f"答题卡，无试题内容（{len(text)}字）"
    if "计划表" in name:
        return True, f"空白计划表，正文为乱码/二进制（{len(text)}字）"
    if "课程表" in name:
        return True, f"课程表图片，OCR 仅 {len(text)} 字且为乱码"
    if n_words <= 5:
        return True, f"无实质词汇内容（仅 {n_words} 个英文词），属广告/说明页"
    return False, f"含 {n_words} 个真实英文词，保留"


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # 先取 file_path（删行后就拿不到了）
    path_map = {}
    for did in DELETE_IDS:
        row = cur.execute(
            "SELECT file_name, content, file_path FROM documents WHERE id = ?",
            (did,)).fetchone()
        if row:
            path_map[did] = row[2]

    print("=" * 70)
    print("第二轮清理（按内容判定，不按文件名）")
    print("=" * 70)

    todo = []
    for did in DELETE_IDS:
        row = cur.execute(
            "SELECT file_name, content FROM documents WHERE id = ?",
            (did,)).fetchone()
        if not row:
            print(f"#{did} 已不存在，跳过")
            continue
        name, content = row
        dele, reason = assess(did, name, content)
        flag = "删除" if dele else "保留"
        print(f"  #{did:<6} {name[:52]:<54} [{flag}] {reason}")
        if dele:
            todo.append((did, name, reason))

    # 保留确认
    print("\n保留确认（有价值词汇书）：")
    for did, note in KEEP_IDS_NOTE.items():
        row = cur.execute(
            "SELECT file_name FROM documents WHERE id=?", (did,)).fetchone()
        if row:
            print(f"  #{did:<6} {row[0][:52]:<54} [保留] {note}")

    print(f"\n本轮将删除 {len(todo)} 条")
    if not APPLY:
        print("dry-run。加 --apply 执行。")
        conn.close()
        return

    # 备份
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bpath = os.path.join(BACKUP_DIR, f"kaoyan_pre_lowvalue2_{stamp}.db")
    out = sqlite3.connect(bpath)
    try:
        conn.backup(out)
    finally:
        out.close()
    print(f"已备份 -> {bpath}")

    # 数据库删除
    ids = [t[0] for t in todo]
    ph = ",".join("?" * len(ids))
    n_chunk = 0
    try:
        n_chunk = cur.execute(
            f"SELECT COUNT(*) FROM knowledge_chunks WHERE document_id IN ({ph})",
            ids).fetchone()[0]
        # 物理删除闸门：knowledge_chunks 物理删除不可逆，批量删分块
        # 属高危操作，必须显式设置 KAOYAN_ALLOW_PHYSICAL_DELETE=1 才放行。
        require_physical_delete_enabled("knowledge_chunks")
        cur.execute(f"DELETE FROM knowledge_chunks WHERE document_id IN ({ph})", ids)
    except sqlite3.OperationalError as e:
        print("chunk 清理跳过:", e)
    cur.execute(f"DELETE FROM documents WHERE id IN ({ph})", ids)
    conn.commit()
    print(f"数据库已删: documents {len(ids)} 条, knowledge_chunks {n_chunk} 条")

    # 磁盘隔离
    moved, failed = 0, []
    day = datetime.now().strftime("%Y%m%d")
    for did, name, _ in todo:
        fp = path_map.get(did)
        if not fp:
            continue
        src = fp if os.path.isabs(fp) else os.path.join(KB, fp)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(TRASH_ROOT, day, os.path.basename(name))
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            moved += 1
        except Exception as e:
            failed.append({"name": name, "err": str(e)})
    print(f"磁盘已隔离 {moved} 个 -> {os.path.join(TRASH_ROOT, day)}")
    if failed:
        print(f"  失败: {failed}")

    conn.close()
    print("=" * 70)


if __name__ == "__main__":
    main()
