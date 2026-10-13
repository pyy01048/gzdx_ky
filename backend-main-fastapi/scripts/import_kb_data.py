# -*- coding: utf-8 -*-
"""训练数据分类入库脚本（dry-run / 正式导入两用）。

数据源：
  kb_chunks/   : 5164 个 RAG 分块 JSON + index.json
  processed/   : 442 个清洗后 txt 全文
  sft/         : train.jsonl + val.jsonl

目标：
  kaoyan.db 新增 knowledge_chunks / sft_examples 表，
  documents 表重建为 processed 清洗全文并按学科分类。
"""
import os
import sys
import json
import re
import sqlite3
import shutil
import datetime
import collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.delete_guard import require_physical_delete_enabled  # noqa: E402

DATA = r"D:\MarvisData\User\oAN1i2T40ogJFVM4CCm9d72iRr_I\workspace\conv_8902ff7614d342c7962b8e3a65ae2d45\output\kaoyan_ai_project_20260830\data"
DB = r"D:\MarvisData\User\oAN1i2T40ogJFVM4CCm9d72iRr_I\workspace\conv_6307dce6ea3e494fa029dd89f1bf322a\output\kaoyan-study-platform\backend-main-fastapi\data\kaoyan.db"
BACKUP = r"D:\MarvisData\User\oAN1i2T40ogJFVM4CCm9d72iRr_I\workspace\conv_6307dce6ea3e494fa029dd89f1bf322a\temp"

DRY_RUN = "--commit" not in sys.argv

# ---------------- 学科分类 ---------------- #
DIGITAL = ['数电', '数字电路', '数字电子', '数字部分', '逻辑代数', '逻辑函数', '门电路', '触发器',
           '组合逻辑', '时序逻辑', '锁存器', '寄存器', '存储器', '可编程逻辑', 'vhdl', 'verilog', '硬件描述',
           '数制', '编码器', '译码器', '脉冲', '计数器', '卡诺图', '二进制', '数模', '模数', '数-模', '模-数',
           '555', '数据选择器', '比较器', '加法器', '全加器', '半加器', '同步时序', '异步时序', '移位寄存器',
           '数字-模拟', '模拟-数字', '几种常用的脉冲']
ANALOG = ['模电', '模拟电子', '模拟部分', '放大电路', '半导体器件', '多级放大', '集成运算', '运算放大',
          '功率放大', '直流电源', '反馈', '电子线路', '二极管', '三极管', '场效应', '差分', '共射', '共集',
          '共基', '静态工作点', '波形', '基本放大']
ENGLISH = ['英语', '精讲册', '逐词逐句', '真题逐题细解', '长难句', '核心词', '背单词', '单词', '词汇', '阅读',
           '作文', '完形', '翻译', '刘晓艳', '真题速查', '真题及答案']
MATH = ['数学', '高数', '线代', '线性代数', '概率', '统计', '张宇', '660', '1000', '基础30讲', '数一', '数二', '数三']
EXAM = ['真题', '月考', '模拟考试', '试卷', '答案', '测试', '考纲']
NETWORK = ['网络补充', '通信原理', '信号与系统', '计算机网络', '电磁场', '电路分析',
           '高频电子', '数据结构', 'c语言', '操作系统', '微机原理']

# 内容反查关键词（对文件名无法确定学科时使用）
CONTENT_KW = {
    '数字电子技术': ['逻辑门', '触发器', '计数器', '译码器', '时序电路', '组合逻辑', '布尔', '卡诺图',
                  '二进制', '与非', '或非', '寄存器', '锁存器', '数据选择器', '全加器', '真值表', '编码',
                  'vhdl', '555', '施密特', '状态方程', '驱动方程', '激励表', '波形图'],
    '模拟电子技术': ['二极管', '三极管', '运放', '运算放大', '反馈', '差分', '共射', '共集', '场效应',
                  '整流', '稳压', '偏置', '静态工作点', '放大倍数', '波特图', '功放', 'pn结', '基极', '集电极'],
    '英语': ['passage', 'sentence', 'vocabulary', 'reading', '单词', '词汇', '长难句', '完形填空',
           '阅读理解', 'the ', ' and ', ' that ', ' which '],
    '数学': ['函数', '导数', '极限', '矩阵', '概率', '积分', '向量', '行列式', '微分', '连续', '收敛',
           '概率统计', '大数定律', '分布函数', '抽样'],
}

# 各校考研真题（高校名+数字代码）
EXAM_SCHOOL = re.compile(r'(东南大学|华北电力大学|厦门大学|安徽大学|江南大学|湖南大学|西北大学|'
                         r'西南科技大学|中国航天|贵州大学|复旦大学|浙江大学|西安电子|北京邮电|电子科技大学)\d*')

# 章节型教材文档（无学科词但章节标题可反查）
CHAPTER_DIGITAL = re.compile(r'^(第?[1-9一二三四五六七八九十]+[章节]|[1-9]+[章节]|概述|第一节|第二节|第三节|第四节|第五节)')


def classify_by_name(name):
    n = name.lower()
    if any(k.lower() in n for k in NETWORK): return '网络补充'
    if any(k.lower() in n for k in DIGITAL): return '数字电子技术'
    if any(k.lower() in n for k in ANALOG): return '模拟电子技术'
    if any(k in n for k in ENGLISH): return '英语'
    if any(k in n for k in MATH): return '数学'
    if any(k in n for k in EXAM): return '真题综合'
    if EXAM_SCHOOL.search(name): return '真题综合'
    if '概统' in name or '概率统计' in name: return '数学'
    if '电子技术基础' in name: return '电子技术基础'
    return None  # 需内容反查


def classify_by_content(text):
    if not text:
        return '其他'
    t = text[:3000].lower()
    scores = collections.Counter()
    for subj, kws in CONTENT_KW.items():
        for kw in kws:
            if kw in t:
                scores[subj] += 1
    if scores:
        subj, cnt = scores.most_common(1)[0]
        if cnt >= 2:
            return subj
    return '其他'


def classify_doc(name, content_text=''):
    s = classify_by_name(name)
    if s:
        return s
    return classify_by_content(content_text)


# ---------------- 读取数据 ---------------- #
def load_index():
    with open(os.path.join(DATA, 'kb_chunks', 'index.json'), 'r', encoding='utf-8') as f:
        return json.load(f)


def load_chunk_text(doc, chunk_id):
    p = os.path.join(DATA, 'kb_chunks', f'{doc}__{chunk_id}.json')
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f).get('text', '')
    except Exception:
        return ''


def main():
    print(f"[{'DRY-RUN 只读预览' if DRY_RUN else '正式导入'}]")
    index = load_index()
    proc_dir = os.path.join(DATA, 'processed')

    # 1) processed 文档分类
    proc_docs = []
    for fn in sorted(os.listdir(proc_dir)):
        stem = os.path.splitext(fn)[0]
        with open(os.path.join(proc_dir, fn), 'r', encoding='utf-8') as f:
            content = f.read()
        subject = classify_doc(stem, content)
        proc_docs.append({
            'file_name': fn, 'stem': stem, 'content': content,
            'subject': subject, 'size': len(content.encode('utf-8')),
        })

    doc_cnt = collections.Counter(d['subject'] for d in proc_docs)
    print("\n== processed 学科分布（documents 表将重建）:")
    for k, v in doc_cnt.most_common():
        print(f"   {k}: {v}")
    print(f"   total: {len(proc_docs)}")

    # 2) chunk 分类（doc -> subject 映射复用 processed）
    stem2subj = {d['stem']: d['subject'] for d in proc_docs}
    chunk_subj = collections.Counter()
    doc_set = set()
    unknown_docs = set()
    for e in index:
        doc = e['doc']
        doc_set.add(doc)
        subj = stem2subj.get(doc)
        if not subj:
            # 反查第一个 chunk 文本
            txt = load_chunk_text(doc, e['chunk_id'])
            subj = classify_doc(doc, txt)
            stem2subj[doc] = subj
            if subj == '其他':
                unknown_docs.add(doc)
        chunk_subj[subj] += 1

    print("\n== kb_chunks 学科分布（knowledge_chunks 表）:")
    for k, v in chunk_subj.most_common():
        print(f"   {k}: {v}")
    print(f"   total chunks: {sum(chunk_subj.values())}, 去重 doc: {len(doc_set)}")
    if unknown_docs:
        print(f"   !! 无法判定学科的 doc({len(unknown_docs)}): {sorted(unknown_docs)[:10]}")

    # 3) SFT 统计
    sft_cnt = {}
    for split in ['train', 'val']:
        p = os.path.join(DATA, 'datasets', 'sft', f'{split}.jsonl')
        n = sum(1 for _ in open(p, 'r', encoding='utf-8'))
        sft_cnt[split] = n
    print(f"\n== SFT 数据（sft_examples 表）: train={sft_cnt['train']}, val={sft_cnt['val']}")

    if DRY_RUN:
        print("\n[dry-run 结束，未写入任何数据。确认无误后加 --commit 正式导入]")
        return

    # ---------------- 正式导入 ---------------- #
    # 备份数据库
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = os.path.join(BACKUP, f'kaoyan_backup_{ts}.db')
    shutil.copy2(DB, bak)
    print(f"\n[备份] 原数据库 -> {bak}")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # 重建 documents 表（含 subject 列）
    # 物理删除闸门：DROP TABLE knowledge_chunks 是整表级不可逆操作，
    # 比行级DELETE 危险得多，必须显式放行。
    require_physical_delete_enabled("knowledge_chunks")
    cur.execute("DROP TABLE IF EXISTS knowledge_chunks")
    cur.execute("DROP TABLE IF EXISTS sft_examples")
    cur.execute("""CREATE TABLE IF NOT EXISTS knowledge_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER,
        doc_name TEXT,
        chunk_id INTEGER,
        subject TEXT,
        text TEXT,
        created_at TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS sft_examples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        split TEXT,
        system TEXT,
        user TEXT,
        assistant TEXT,
        subject TEXT,
        created_at TEXT
    )""")

    # documents 表加 subject 列（若不存在）
    cols = [r[1] for r in cur.execute("PRAGMA table_info(documents)").fetchall()]
    if 'subject' not in cols:
        cur.execute("ALTER TABLE documents ADD COLUMN subject TEXT")
    # 清空旧 documents / knowledge_points（避免与清洗全文重复）
    cur.execute("DELETE FROM documents")
    cur.execute("DELETE FROM knowledge_points")

    now = datetime.datetime.now(datetime.UTC).isoformat()

    # 写 documents
    doc_id_map = {}
    for d in proc_docs:
        cur.execute(
            """INSERT INTO documents (file_name, file_type, size, index_status,
               knowledge_point_count, parse_progress, content, subject, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (d['file_name'], 'txt', d['size'], 'indexed', 0, 1.0, d['content'], d['subject'], now),
        )
        doc_id_map[d['stem']] = cur.lastrowid
    print(f"[导入] documents: {len(proc_docs)} 条")

    # 写 knowledge_chunks
    chunk_doc_map = {}
    for e in index:
        doc = e['doc']
        did = doc_id_map.get(doc)
        if did is None:
            did = None
        subj = stem2subj.get(doc, '其他')
        txt = load_chunk_text(doc, e['chunk_id'])
        cur.execute(
            """INSERT INTO knowledge_chunks (document_id, doc_name, chunk_id, subject, text, created_at)
               VALUES (?,?,?,?,?,?)""",
            (did, doc, e['chunk_id'], subj, txt, now),
        )
    print(f"[导入] knowledge_chunks: {len(index)} 条")

    # 写 sft_examples
    for split in ['train', 'val']:
        p = os.path.join(DATA, 'datasets', 'sft', f'{split}.jsonl')
        n = 0
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                msgs = obj.get('messages', [])
                sys_msg = ''
                user_msg = ''
                asst_msg = ''
                for m in msgs:
                    if m.get('role') == 'system':
                        sys_msg = m.get('content', '')
                    elif m.get('role') == 'user':
                        user_msg = m.get('content', '')
                    elif m.get('role') == 'assistant':
                        asst_msg = m.get('content', '')
                subj = classify_by_content(user_msg or sys_msg)
                cur.execute(
                    """INSERT INTO sft_examples (split, system, user, assistant, subject, created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (split, sys_msg, user_msg, asst_msg, subj, now),
                )
                n += 1
        print(f"[导入] sft_examples[{split}]: {n} 条")

    conn.commit()

    # 验证统计
    print("\n== 入库验证 ==")
    for t in ['documents', 'knowledge_chunks', 'sft_examples']:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"   {t}: {cur.fetchone()[0]}")
    cur.execute("SELECT subject, COUNT(*) FROM documents GROUP BY subject ORDER BY COUNT(*) DESC")
    print("   documents 学科分布:", dict(cur.fetchall()))
    cur.execute("SELECT subject, COUNT(*) FROM knowledge_chunks GROUP BY subject ORDER BY COUNT(*) DESC")
    print("   knowledge_chunks 学科分布:", dict(cur.fetchall()))
    cur.execute("SELECT split, COUNT(*) FROM sft_examples GROUP BY split")
    print("   sft_examples 分布:", dict(cur.fetchall()))
    conn.close()


if __name__ == '__main__':
    main()
