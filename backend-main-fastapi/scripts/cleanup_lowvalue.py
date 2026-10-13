# -*- coding: utf-8 -*-
"""
清理低价值资料：答题卡/答题纸/打卡表/课程表/封面目录/打印店广告。

设计要点（重要）：
1. **排除关键词刻意不含"打印"**。因为《2010-2024英语一真题一键打印版》
   《高数刷题本（打印版）》这类是宝贵真题/题本，只是文件名带"打印"二字。
   只用精确的垃圾词：答题卡 / 答题纸 / 打卡 / 课程表 / 打印店广告 等。
2. 磁盘文件**移动到 _trash/<日期>/**，不 rm，可回溯。
3. 数据库先 backup() API 备份（SQLite WAL 模式下 cp 会丢未合并数据）。
4. 默认 dry-run，加 --apply 才真正执行。

用法：
  python scripts/cleanup_lowvalue.py                # 预览
  python scripts/cleanup_lowvalue.py --apply        # 执行
  python scripts/cleanup_lowvalue.py --apply --only-db
  python scripts/cleanup_lowvalue.py --apply --only-fs
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.delete_guard import require_physical_delete_enabled  # noqa: E402

DB = r"D:\平台\database\kaoyan.db"
KB = r"D:\平台\knowledge_base"
BACKUP_DIR = r"D:\平台\data\backups"
TRASH_ROOT = os.path.join(KB, "_trash")

# ---------------------------------------------------------------- 排除规则
# 精确垃圾词。**不要加"打印"/"打印版"** —— 会误杀真题。
EXCLUDE_WORDS = [
    "答题卡", "答题纸", "答题版", "机读卡", "填涂卡",
    "打卡", "签到表", "进度表", "计划表", "倒计时",
    "课程表", "课表",
    "打印店", "彩印", "打印店太香", "在线打印",
    "封面及目录", "封面.ppt", "封面.pptx",
]
# 明确的"目录/封面"文件名（无实质内容）
EXCLUDE_EXACT = {"封面及目录.txt", "封面及目录.pptx", "目录.TXT", "目录.txt",
                 "华成英主讲目录.txt"}

# 白名单：即使命中关键词也**必须保留**（真题/题本/教材）
WHITELIST_HINT = [
    "真题", "试题", "题库", "习题", "答案", "解析", "刷题", "教材",
    "全书", "指南", "大纲", "讲义", "笔记", "考点", "复习",
]

# 高价值硬保护：这些文件名里带"打卡"但本体是核心单词书，**绝不能删**。
# 依据 check_keep_guard.py 实测：
#   红宝书 118.9MB —— 尚未入库（chunk=0），是考研英语核心词汇书，删了不可恢复
#   艾宾浩斯抗遗忘打卡 —— 已产出 48 个 chunk，是单词数据源
PROTECTED_FILES = [
    "红宝书",
    "艾宾浩斯抗遗忘打卡",
    "抗遗忘",
]

EXCLUDE_EXTS = {".md", ".json", ".txt"}  # 这些在 documents/ima 下是缓存产物


def classify(name: str):
    """返回 (should_delete, reason)"""
    base = os.path.basename(name)
    if base in EXCLUDE_EXACT:
        return True, "文件名精确命中(封面/目录)"
    hits = [w for w in EXCLUDE_WORDS if w in base]
    if not hits:
        return False, ""
    # 硬保护：高价值单词书等
    prot = [p for p in PROTECTED_FILES if p in base]
    if prot:
        return False, f"命中垃圾词{hits}但属硬保护词汇书{prot}，保留"
    # 白名单保护：命中关键词但同时具备高价值特征 → 保留
    keeps = [k for k in WHITELIST_HINT if k in base]
    if keeps:
        return False, f"命中垃圾词{hits}但具备高价值特征{keeps}，保留"
    return True, f"命中垃圾词{hits}"


def backup_db(tag: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"kaoyan_pre_lowvalue_{stamp}_{tag}.db")
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)          # 必须用 backup API，cp 在 WAL 模式下会丢数据
    finally:
        out.close()
        src.close()
    return dst


def scan_fs():
    """扫描磁盘上应删除/隔离的文件"""
    hit, keep = [], []
    for root, dirs, files in os.walk(KB):
        # 不进入已隔离区
        if "_trash" in root:
            continue
        for fn in files:
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, KB)
            dele, reason = classify(fn)
            try:
                sz = os.path.getsize(p)
            except OSError:
                sz = 0
            (hit if dele else keep).append(
                {"path": rel, "abs": p, "size": sz, "reason": reason})
    return hit, keep


def scan_db(conn):
    """扫描 documents 表中应删除的行"""
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(documents)")]
    rows = cur.execute("SELECT id, file_name, file_path FROM documents").fetchall()
    hit, keep = [], []
    for did, fname, fpath in rows:
        target = fname or ""
        dele, reason = classify(target)
        if not dele and fpath:
            # 仅当文件名侧不是"保护/白名单"结论时，才允许路径侧否决
            protected = reason.startswith("命中垃圾词") and "保留" in reason
            if not protected:
                dele2, reason2 = classify(fpath)
                # 路径命中但文件名不像（如 "00.26考研各科答题卡/政治.pdf"）→ 也删
                if dele2:
                    dele, reason = True, f"路径命中: {reason2}"
        rec = {"id": did, "file_name": fname, "file_path": fpath, "reason": reason}
        (hit if dele else keep).append(rec)
    return hit, keep, cols


def delete_db(conn, ids):
    """级联删除 documents 行及其知识块"""
    cur = conn.cursor()
    if not ids:
        return {"documents": 0, "chunks": 0}
    ph = ",".join("?" * len(ids))
    # 先统计关联块
    n_chunk = 0
    try:
        n_chunk = cur.execute(
            f"SELECT COUNT(*) FROM knowledge_chunks WHERE document_id IN ({ph})",
            ids).fetchone()[0]
    except sqlite3.OperationalError:
        n_chunk = 0
    try:
        # 物理删除闸门：knowledge_chunks 物理删除不可逆，批量删分块
        # 一旦判重逻辑出错就会造成大面积数据损失（本周曾误删 158 条真题）。
        require_physical_delete_enabled("knowledge_chunks")
        cur.execute(f"DELETE FROM knowledge_chunks WHERE document_id IN ({ph})", ids)
    except sqlite3.OperationalError:
        pass
    cur.execute(f"DELETE FROM documents WHERE id IN ({ph})", ids)
    conn.commit()
    return {"documents": len(ids), "chunks": n_chunk}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正执行（默认 dry-run）")
    ap.add_argument("--only-db", action="store_true")
    ap.add_argument("--only-fs", action="store_true")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认")
    args = ap.parse_args()

    run_db = not args.only_fs
    run_fs = not args.only_db

    report = {"mode": "apply" if args.apply else "dry-run"}

    conn = sqlite3.connect(DB)
    db_hit, db_keep, _ = scan_db(conn)
    report["db_delete"] = db_hit
    report["db_delete_count"] = len(db_hit)
    # 白名单保护样本（让人能看到我们没误杀什么）
    report["db_protected_samples"] = [
        k for k in db_keep if classify(k["file_name"] or "")[1]
    ][:15]

    if run_fs:
        fs_hit, _ = scan_fs()
        report["fs_delete"] = fs_hit
        report["fs_delete_count"] = len(fs_hit)
        report["fs_total_mb"] = round(
            sum(f["size"] for f in fs_hit) / 1048576, 1)

    print("=" * 68)
    print(f"模式: {report['mode']}")
    if run_db:
        print(f"数据库待删 documents: {len(db_hit)} 条")
        for r in db_hit:
            print(f"   #{r['id']:<6} {r['file_name']}  <- {r['reason']}")
    if run_fs:
        print(f"磁盘待隔离文件: {len(fs_hit)} 个, 共 {report['fs_total_mb']} MB")
        for f in fs_hit[:40]:
            print(f"   {f['path']}  ({f['size']//1024} KB) <- {f['reason']}")
        if len(fs_hit) > 40:
            print(f"   ... 另有 {len(fs_hit)-40} 个")
    print("=" * 68)

    if not args.apply:
        print("这是 dry-run。加 --apply 执行。")
        conn.close()
        return

    if not args.yes:
        ans = input(f"确认删除? 数据库 {len(db_hit)} 条 / 磁盘 {len(fs_hit)} 个文件 [y/N] ")
        if ans.strip().lower() != "y":
            print("已取消。")
            conn.close()
            return

    # 1) 备份
    bpath = backup_db("lowvalue")
    print(f"已备份数据库 -> {bpath}")

    # 2) 数据库清理
    if run_db and db_hit:
        res = delete_db(conn, [r["id"] for r in db_hit])
        report["db_result"] = res
        print(f"数据库已删除: documents {res['documents']} 条, "
              f"knowledge_chunks {res['chunks']} 条")

    conn.close()

    # 3) 磁盘隔离（移动而非删除，可回溯）
    if run_fs and fs_hit:
        stamp = datetime.now().strftime("%Y%m%d")
        moved, failed = 0, []
        for f in fs_hit:
            src = f["abs"]
            dst = os.path.join(TRASH_ROOT, stamp, f["path"])
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                moved += 1
            except Exception as e:
                failed.append({"path": f["path"], "err": str(e)})
        report["fs_result"] = {"moved": moved, "failed": failed,
                               "trash": os.path.join(TRASH_ROOT, stamp)}
        print(f"磁盘已隔离: {moved} 个 -> {os.path.join(TRASH_ROOT, stamp)}")
        if failed:
            print(f"  失败 {len(failed)} 个: {failed[:5]}")

    outp = os.path.join(BACKUP_DIR, "lowvalue_cleanup_report.json")
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"报告 -> {outp}")


if __name__ == "__main__":
    main()
