# -*- coding: utf-8 -*-
"""填充 code_problems 表：解析 doocs/leetcode 开源题解数据并写入 PostgreSQL。

用法:
    python fill_code_problems_pg.py

依赖:
    pip install psycopg[binary]  (已安装 psycopg 3.2.10)
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import sys
from pathlib import Path

import psycopg

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
PG_CONFIG = dict(host="127.0.0.1", port=5432, user="kaoyan",
                   password="kaoyan_dev_2026", dbname="kaoyan")

# doocs/leetcode 提取出的 README 根目录
README_ROOT = Path(r"D:/平台/backend-main-fastapi/temp/readmes")

# 最终脚本保存路径（本文件自身）
SCRIPT_PATH = Path(r"D:/平台/backend-main-fastapi/scripts/fill_code_problems_pg.py")

# 写入数量上限（目标 500+，留余量防止重复）
LIMIT = 600

# 难度映射：简单->1 中等->3 困难->5（LeetCode 三档映射到 1-5 的 1/3/5）
DIFF_MAP = {"简单": 1, "中等": 3, "困难": 5}

# 数据结构类标签
DS_TAGS = {"数组", "链表", "树", "二叉树", "图", "哈希表", "哈希", "堆（优先队列）", "堆",
           "栈", "队列", "字符串", "字符串匹配", "前缀和", "并查集", "字典树", "线段树",
           "树状数组", "单调栈", "单调队列", "双向链表", "红黑树", "设计", "数据流",
           "矩阵", "几何", "随机化", "蓄水池抽样", "基数排序", "计数排序"}

# 算法类标签
ALGO_TAGS = {"排序", "查找", "搜索", "深度优先搜索", "广度优先搜索", "回溯", "动态规划",
             "贪心", "递归", "二分查找", "数学", "位运算", "滑动窗口", "双指针", "分治",
             "快速选择", "拓扑排序", "最短路", "最小生成树", "博弈", "状态压缩", "记忆化搜索",
             "扫描线", "差分", "模拟", "枚举", "数论", "组合数学", "概率统计", "脑筋急转弯"}


# ---------------------------------------------------------------------------
# Markdown / HTML 解析工具
# ---------------------------------------------------------------------------
def extract_frontmatter(text: str) -> tuple[str, list[str]]:
    """提取 frontmatter 中的 difficulty 和 tags。返回 (difficulty, tags)。"""
    m = re.search(r"^---\s*\n(.*?)\n---\s*\n", text, re.MULTILINE | re.DOTALL)
    difficulty = ""
    tags: list[str] = []
    if m:
        fm = m.group(1)
        dm = re.search(r"difficulty:\s*(.+)", fm)
        if dm:
            difficulty = dm.group(1).strip()
        tm = re.search(r"tags:\s*\n((?:\s*-\s*.+\n?)+)", fm)
        if tm:
            tags = re.findall(r"-\s*(.+)", tm.group(1))
            tags = [t.strip() for t in tags]
        else:
            tm2 = re.search(r"tags:\s*\[([^\]]+)\]", fm)
            if tm2:
                tags = [t.strip().strip("\"'") for t in tm2.group(1).split(",")]
    return difficulty, tags


def extract_description(text: str) -> str:
    """提取 <!-- description:start --> 与 <!-- description:end --> 之间的题目描述并转纯文本。

    样例块（<pre>）会以文本形式保留在描述末尾，同时由 extract_samples 单独提取。
    """
    m = re.search(r"<!-- description:start -->(.*?)<!-- description:end -->",
                  text, re.DOTALL)
    if not m:
        return ""
    block = m.group(1)
    # 移除示例标题（"示例 1：" 等，因为 <pre> 内容会以文本形式还原）
    block = re.sub(r"<strong class=\"example\">[^<]*</strong>", "", block)
    # 先将 <pre> 块整体保存
    pres: list[str] = []
    def _hold_pre(mo):
        pres.append(mo.group(1))
        return f"\n[PRE{len(pres)-1}]\n"
    block = re.sub(r"<pre>(.*?)</pre>", _hold_pre, block, flags=re.DOTALL)

    # 提取提示列表 <ul><li> 转为文本
    block = re.sub(r"<li>(.*?)</li>", lambda mo: "- " + _clean_html(mo.group(1)) + "\n", block, flags=re.DOTALL)
    # 去掉其余 HTML 标签
    txt = _clean_html(block)
    txt = re.sub(r"&nbsp;", " ", txt)
    # 还原样例占位为可读文本
    def _restore_pre(mo):
        idx = int(mo.group(1))
        p_raw = pres[idx]
        p_clean = _clean_html(p_raw)
        # 把 "输入：xxx 输出：xxx 解释：xxx" 转成多行
        p_clean = re.sub(r"输入[:：]", "\n输入: ", p_clean)
        p_clean = re.sub(r"输出[:：]", "\n输出: ", p_clean)
        p_clean = re.sub(r"解释[:：]", "\n解释: ", p_clean)
        return f"\n```text\n{p_clean.strip()}\n```\n"
    txt = re.sub(r"\[PRE(\d+)\]", _restore_pre, txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    return txt


def _clean_html(block: str) -> str:
    """移除 HTML 标签并反转义实体。"""
    block = re.sub(r"<br\s*/?>", "\n", block, flags=re.IGNORECASE)
    block = re.sub(r"</p>", "\n\n", block, flags=re.IGNORECASE)
    block = re.sub(r"</(?:div|pre|ul|ol|li|h1|h2|h3|h4)>", "\n", block, flags=re.IGNORECASE)
    block = re.sub(r"<[^>]+>", "", block)
    return html_lib.unescape(block).strip()


def extract_samples(text: str) -> tuple[str, str]:
    """从描述块中的 <pre> 提取第一组 输入/输出 样例。

    返回 (sample_input, sample_output)。
    """
    m = re.search(r"<!-- description:start -->(.*?)<!-- description:end -->",
                  text, re.DOTALL)
    block = m.group(1) if m else text
    pres = re.findall(r"<pre>(.*?)</pre>", block, flags=re.DOTALL)
    sample_input, sample_output = "", ""
    for p in pres:
        p_clean = _clean_html(p)
        # 中文版：输入：xxx 输出：xxx 解释：xxx
        # 输入值 = 输入: 到 输出: 之间的内容；输出值 = 输出: 到 解释:(可选) 或行尾
        im = re.search(r"输入[:：]\s*(.*?)(?:\n\s*输出[:：]|输出[:：])", p_clean, re.DOTALL)
        if im:
            sample_input = im.group(1).strip()
        om = re.search(r"输出[:：]\s*(.*?)(?:\n\s*解释[:：]|解释[:：]|$)", p_clean, re.DOTALL)
        if om:
            sample_output = om.group(1).strip()
        if sample_input and sample_output:
            break
    return sample_input, sample_output


def extract_hints(text: str) -> str:
    """从 solution 区域截取「方法一」的解法说明作为 hints。"""
    m = re.search(r"<!-- solution:start -->(.*?)<!-- solution:end -->",
                  text, re.DOTALL)
    if not m:
        return ""
    sol = m.group(1)
    # 从「方法一」标题之后，截取到代码 tabs 之前的所有内容（含 thinking 块和正文）
    method = re.search(r"###\s*方法一[^\n]*\n(.*?)(?=<!-- tabs:start -->|<!-- solution:end -->|###\s)",
                       sol, re.DOTALL)
    if method:
        body = method.group(1)
        # 去掉 thinking 注释标记
        body = re.sub(r"<!--\s*thinking:(?:start|end)\s*-->", "", body)
        # 去掉 blockquote 符号和 Markdown 标题残留
        body = re.sub(r"^>\s*", "", body, flags=re.MULTILINE)
        body = re.sub(r"^\s*###\s*", "", body, flags=re.MULTILINE)
        body = re.sub(r"\*\*思考\*\*\s*", "", body)
        body = _clean_html(body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        body = re.sub(r"^方法一[：:]\s*", "", body)
        if body:
            return body[:2000]
    # 回退：取 solution 里第一段文字
    txt = _clean_html(sol)
    lines = [l for l in txt.splitlines() if l.strip()]
    if lines:
        return " ".join(lines[0:5])[:2000]
    return ""


def extract_title(text: str) -> str:
    """提取 # [1. 两数之和](...) 中的标题。"""
    m = re.search(r"^#\s*\[([^\]]+)\]", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return ""


def choose_subject(tags: list[str]) -> str:
    """根据 tags 判断 subject：优先数据结构，否则算法，否则 '算法'。"""
    ds_hit = next((t for t in tags if t in DS_TAGS), None)
    if ds_hit:
        return "数据结构"
    algo_hit = next((t for t in tags if t in ALGO_TAGS), None)
    if algo_hit:
        return "算法"
    return "算法"


def build_io_formats(title: str, sample_input: str | None, sample_output: str | None) -> tuple[str, str]:
    """根据样例生成输入/输出格式说明（LeetCode 函数式题目没有 stdin 格式，生成通用说明）。"""
    if sample_input:
        input_format = ("输入为题目描述中给定的参数（LeetCode 风格，函数入参）。\n"
                        f"示例输入：{sample_input}")
    else:
        input_format = "输入为题目描述中给定的参数（LeetCode 风格，函数入参）。"
    if sample_output:
        output_format = ("输出为符合题目要求的结果。\n"
                         f"示例输出：{sample_output}")
    else:
        output_format = "输出为符合题目要求的结果。"
    return input_format, output_format


def load_readmes(root: Path) -> list[dict]:
    """遍历 root 下所有 README.md，解析为记录字典。"""
    records = []
    for p in sorted(root.rglob("README.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if not text.strip():
            continue
        title = extract_title(text)
        if not title:
            continue
        difficulty_cn, tags = extract_frontmatter(text)
        difficulty = DIFF_MAP.get(difficulty_cn, 2)
        description = extract_description(text)
        if len(description) < 30:  # 描述过短视为解析失败
            continue
        sample_input, sample_output = extract_samples(text)
        hints = extract_hints(text)
        subject = choose_subject(tags)
        input_format, output_format = build_io_formats(title, sample_input, sample_output)
        records.append({
            "title": title,
            "subject": subject,
            "difficulty": difficulty,
            "description": description,
            "input_format": input_format,
            "output_format": output_format,
            "sample_input": sample_input or None,
            "sample_output": sample_output or None,
            "hints": hints or None,
            "tags": tags,
            "source": "doocs/leetcode",
        })
    return records


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    records = load_readmes(README_ROOT)
    print(f"解析得到有效记录: {len(records)} 条")

    # 去重（同一 title 只保留一次）
    seen: set[str] = set()
    uniq = []
    for r in records:
        key = r["title"].lower().strip()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    records = uniq
    print(f"去重后: {len(records)} 条")

    if LIMIT:
        records = records[:LIMIT]

    conn = psycopg.connect(**PG_CONFIG)
    conn.autocommit = False
    cur = conn.cursor()

    # 幂等：清空已有数据（本次任务要求从 0 开始）
    cur.execute("TRUNCATE code_problems RESTART IDENTITY CASCADE")

    insert_sql = """
        INSERT INTO code_problems
            (title, subject, difficulty, description, input_format, output_format,
             sample_input, sample_output, hints, time_limit_ms, memory_limit_kb,
             tags, is_public, created_at, updated_at)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
    """
    inserted = 0
    for r in records:
        cur.execute(insert_sql, (
            r["title"],
            r["subject"],
            r["difficulty"],
            r["description"],
            r["input_format"],
            r["output_format"],
            r["sample_input"],
            r["sample_output"],
            r["hints"],
            1000,
            256000,
            json.dumps(r["tags"], ensure_ascii=False),
            True,
        ))
        inserted += 1

    conn.commit()
    cur.execute("SELECT count(*) FROM code_problems")
    total = cur.fetchone()[0]
    conn.close()
    print(f"写入完成: {inserted} 条, 表中总数: {total}")

    # 保存统计数据供报告使用
    stats_path = Path(r"D:/平台/backend-main-fastapi/temp/fill_stats.json")
    stats_path.write_text(json.dumps({
        "inserted": inserted,
        "total": total,
        "source": "doocs/leetcode",
        "ai_generated": 0,
        "records_parsed": len(records),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"统计保存至 {stats_path}")


if __name__ == "__main__":
    main()