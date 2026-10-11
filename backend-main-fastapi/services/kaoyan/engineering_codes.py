# -*- coding: utf-8 -*-
"""工科专业代码集与国家线数据（T5-1 / T5-2）。

一、ENGINEERING_CODE_SET：用户指定的工科系列（电子+通信+408+光学+电气+人工智能）。
   用于爬虫定向采集过滤（研招网 yjxkdm 传门类，二级/专业学位代码在此集内才入库）。

二、NATIONAL_LINES：近五年考研国家线（A区，学术学位工学 + 专业学位电子信息等）。
   国家线由教育部统一公布、按学科门类划线，是**公开静态数据**——不是逐校爬取的，
   因此直接内置数据表（来源：教育部历年《全国硕士研究生招生考试考生进入复试的
   初试成绩基本要求》），并给采集函数按 (科类, 年份) 回填 kaoyan_scorelines.national_line。

   诚实口径：只内置有把握的年份；专硕按类（电子信息0854 与工学同线的历史年份为准）。
   缺的年份宁缺毋滥，后续可从教育部官网核实后补。
"""
from __future__ import annotations

from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# 工科定向采集专业代码集（用户指定的 6 系列）
# --------------------------------------------------------------------------- #
# 学硕一级学科（研招网 yjxkdm=08 工学下的二级检索）
# 0803 光学工程 | 0804 仪器科学 | 0808 电气工程 | 0809 电子科学与技术
# 0810 信息与通信工程 | 0811 控制科学与工程 | 0812 计算机科学与技术(408)
ENGINEERING_CODE_SET: set = {
    "0803",   # 光学工程（含 080300 学硕 / 085408 光电信息工程专硕）
    "0804",   # 仪器科学与技术
    "0808",   # 电气工程（080800 学硕 / 085801 电气工程专硕）
    "0809",   # 电子科学与技术
    "0810",   # 信息与通信工程
    "0811",   # 控制科学与工程（自动化，AI 相关）
    "0812",   # 计算机科学与技术（408 统考）
    # 专业学位（0854 电子信息大类的核心子领域 + 0858 能源/电气 + 0861 交通运输）
    "0854", "085400", "085401", "085402", "085403", "085404", "085405",
    "085406", "085407", "085408", "085410", "085411", "085412",
    "0858", "085801",  # 能源动力/电气工程
    "0861",            # 交通运输（部分院校信号方向挂靠）
    "1401", "140100",  # 集成电路科学与工程（交叉学科，电子系列）
    "1405", "140500",  # 智能科学与技术（人工智能，交叉学科）
    "0774", "077400",  # 电子科学与技术（理学门类下部分院校设）
    "0702", "070208",  # 科学技术史外——光学挂靠理学时常见 070207 光学
    "070207",          # 光学（理学）
}

# 人类可读的系列名（前端展示/日志用）
CODE_SERIES_LABELS: Dict[str, str] = {
    "电子": ["0809", "0854", "1401"],
    "通信": ["0810"],
    "408": ["0812"],
    "光学": ["0803", "070207"],
    "电气": ["0808", "0858"],
    "人工智能": ["0811", "1405"],
}


def is_engineering_code(code: Optional[str]) -> bool:
    """判断专业代码是否属于定向工科集。前缀匹配（085404 属 0854 集）。"""
    if not code:
        return False
    c = str(code).strip()
    # 先精确，再前缀（6 位专业代码 → 4 位类代码）
    if c in ENGINEERING_CODE_SET:
        return True
    return any(c.startswith(k) for k in ENGINEERING_CODE_SET if len(k) == 4)


# --------------------------------------------------------------------------- #
# 国家线（A区，学术学位/专业学位按科类）—— 教育部公开划线
# 格式：NATIONAL_LINES[年份][科类] = (总分线, 政策单科, 满分>100单科)
# --------------------------------------------------------------------------- #
NATIONAL_LINES: Dict[int, Dict[str, tuple]] = {
    # 以下数值经研招网官方「近五年研考分数线及趋势图」核实（A区，2026-10 查证）：
    # 2022/2023=273/38/57；2024=273/37/56；2025=260/34/51；2026=264/35/53。
    # 电子信息（专硕0854）不单独划线，按工学门类线执行。
    # 理学（07 门类，含 0774 电子科学与技术理学学位）另行核实：
    #   2022=290/39/59；2023=279/38/57；2024=288/41/62；2025=274/34/51；2026=275/35/53。
    2026: {
        "工学": (264, 35, 53),
        "电子信息": (264, 35, 53),
        "理学": (275, 35, 53),
    },
    2025: {
        "工学": (260, 34, 51),
        "电子信息": (260, 34, 51),
        "理学": (274, 34, 51),
    },
    2024: {
        "工学": (273, 37, 56),
        "电子信息": (273, 37, 56),
        "理学": (288, 41, 62),
    },
    2023: {
        "工学": (273, 38, 57),
        "电子信息": (273, 38, 57),
        "理学": (279, 38, 57),
    },
    2022: {
        "工学": (273, 38, 57),
        "电子信息": (273, 38, 57),
        "理学": (290, 39, 59),
    },
}

# 专业代码 → 国家线科类映射（回填时按 major 的 subject_code 找对应科类线）
_CODE_TO_LINE_CATEGORY: Dict[str, str] = {
    "0803": "工学", "0804": "工学", "0808": "工学", "0809": "工学",
    "0810": "工学", "0811": "工学", "0812": "工学",
    "0854": "电子信息", "0858": "工学", "0861": "工学", "1401": "工学",
    "1405": "工学", "0774": "理学", "0702": "理学",
}


def line_category_for_code(subject_code: Optional[str]) -> Optional[str]:
    """专业代码 → 国家线科类。未知代码默认工学（工科平台口径）。"""
    if not subject_code:
        return "工学"
    c = str(subject_code).strip()
    for k, v in _CODE_TO_LINE_CATEGORY.items():
        if c.startswith(k):
            return v
    return "工学"


def get_national_line(year: int, category: str) -> Optional[tuple]:
    """取某年某科类国家线（A区）。无数据/待核实返回 None（宁缺毋滥）。"""
    entry = NATIONAL_LINES.get(int(year), {}).get(category)
    return entry if entry else None


def backfill_national_lines(db_session) -> Dict[str, int]:
    """回填 kaoyan_scorelines.national_line / politics_line / english_line。

    对每条 scoreline：经其 major 的 subject_code 定科类 → 取同年国家线写入。
    只补空值，不覆盖已有数据；返回统计。
    """
    from sqlalchemy import text

    rows = db_session.execute(text(
        """
        SELECT s.id, s.year, m.subject_code
        FROM kaoyan_scorelines s
        LEFT JOIN kaoyan_majors m ON s.major_id = m.id
        WHERE s.national_line IS NULL
        """
    )).fetchall()
    updated = missing = 0
    for sid, year, subject_code in rows:
        if year is None:
            continue
        cat = line_category_for_code(subject_code)
        line = get_national_line(year, cat)
        if not line:
            missing += 1
            continue
        total, single, over100 = line
        db_session.execute(text(
            """
            UPDATE kaoyan_scorelines
            SET national_line = :total, politics_line = COALESCE(politics_line, :single),
                english_line = COALESCE(english_line, :single)
            WHERE id = :sid
            """
        ), {"total": total, "single": single, "sid": sid})
        updated += 1
    db_session.commit()
    return {"scoreline_rows": len(rows), "updated": updated, "no_line_data": missing}
