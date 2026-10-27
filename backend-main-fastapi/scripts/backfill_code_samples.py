# -*- coding: utf-8 -*-
"""从 description 全文回填缺失的 sample_input / sample_output。

既匹配 ```text 代码块，也匹配描述中直接以「输入：」「输出：」开头的普通段落。
"""
import re
import psycopg

conn = psycopg.connect(host="127.0.0.1", port=5432, user="kaoyan",
                      password="kaoyan_dev_2026", dbname="kaoyan")
cur = conn.cursor()
cur.execute("""SELECT id, title, description FROM code_problems
               WHERE sample_input IS NULL OR sample_input=''
                  OR sample_output IS NULL OR sample_output=''
               ORDER BY id""")
rows = cur.fetchall()
print("待回填:", len(rows))

updated = 0
for pid, title, desc in rows:
    si = so = None
    # 1) 先匹配 ```text 块
    blocks = re.findall(r"```text\s*(.*?)```", desc, re.DOTALL)
    for b in blocks:
        im = re.search(r"输入[:：]\s*(.*?)(?:\n\s*输出[:：]|输出[:：])", b, re.DOTALL)
        om = re.search(r"输出[:：]\s*(.*?)(?:\n\s*解释[:：]|解释[:：]|$)", b, re.DOTALL)
        if im and om:
            si, so = im.group(1).strip(), om.group(1).strip()
            break
    # 2) 若无 ```text 块，在全文找 输入: ... 输出: ...
    if not (si and so):
        im = re.search(r"输入[:：]\s*(.*?)(?:\n\s*输出[:：]|输出[:：])", desc, re.DOTALL)
        om = re.search(r"输出[:：]\s*(.*?)(?:\n\s*解释[:：]|解释[:：]|$)", desc, re.DOTALL)
        if im and om:
            si, so = im.group(1).strip(), om.group(1).strip()
    if si and so:
        cur.execute("UPDATE code_problems SET sample_input=%s, sample_output=%s, updated_at=now() WHERE id=%s",
                    (si, so, pid))
        updated += 1
    else:
        print("仍无法提取:", pid, title)

conn.commit()
print("回填成功:", updated)
conn.close()