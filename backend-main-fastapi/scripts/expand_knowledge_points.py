# -*- coding: utf-8 -*-
"""知识点扩充脚本（M1-2，2026-10）：让知识点覆盖所有「有题目」的科目。

背景（真库实测，D:\\平台\\database\\kaoyan.db）：
    `knowledge_points` 共 651 条，分布严重不均：
        模拟电子技术 209 | 数字电子技术 192 | 数学 105 | 英语 38
        计算机学科专业基础408 20 | 电路 15 | 普通物理 14 | 通信原理 13
        光学与工程光学 11 | 信号与系统 9 | 政治 9 | 真题综合 6 | ...
    而 `quiz_questions`（9171 题）科目分布为：
        模拟电子技术 4227 | 数字电子技术 3608 | 政治 814
        计算机学科专业基础408 292 | 英语 93 | 真题综合 66 | 数学 54 | ...
    **关键缺口**：政治有 814 题却只有 9 个知识点；408 有 292 题却只有 20 个
    知识点。题目 `chapter` 字段已有 5006 题带值，可直接确定性派生知识点。

本脚本**只新增、不删不改**任何已有知识点，三层策略（全部确定性、无 LLM）：

    第 1 层（主路径·题目章节）：对每个科目，取 `quiz_questions` 中该科目
        **非空且去重**的 `chapter` 值；用现有
        `services/structure_parser._normalize_chapter()` 对齐/去除「第X章」编号
        前缀，得到语义名；若同科目下不存在同名知识点，则新增：
            name=语义名, subject=该科目, chapter=原始 chapter, document_id=NULL。

    第 2 层（大纲补全·解决零覆盖）：对「有题目但知识点极少/为 0」的科目
        （政治、408 等），取 `services.taxonomy.chapters_of(subject)` 的
        权威大纲章节名，按同规则补成章节级知识点。这是**确定性**来源，可覆盖
        814 题政治 / 292 题 408 的章节维度。

    第 3 层（题目知识点字段）：`quiz_questions.knowledge_point` 中出现、但
        同科目下不存在同名的名字，也补成知识点（name=该字段值）。

设计要点：
    * 幂等：以「同科同名（去空白归一）」为唯一查重口径，重跑只补增量；
    * 默认 dry-run（预览），`--apply` 才写库，且**先备份真库**（sqlite backup API）；
    * 不写 NULL / 空名 / 纯空白名；章节语义名为空则跳过（不落库脏数据）;
    * 新增行 difficulty=3、exam_frequency=0，description 标注来源便于追溯；
    * `--backfill-count` 可选回填 `knowledge_points.question_count`
      = 该科同章题数（同名精确匹配口径，简单可靠）。

用法：
    python scripts/expand_knowledge_points.py                 # 预览（默认 dry-run）
    python scripts/expand_knowledge_points.py --layers 1      # 只预览第 1 层
    python scripts/expand_knowledge_points.py --apply         # 写库（先自动备份）
    python scripts/expand_knowledge_points.py --apply --backfill-count  # 写库并回填题数
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime

# --------------------------------------------------------------------------- #
# 路径与常量
# --------------------------------------------------------------------------- #
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 以脚本方式运行时（python scripts/xxx.py），sys.path[0] 是 scripts/，
# 导致 `import services.*` 失败——把项目根加入 sys.path。
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
# 独立运行时 .env 不会被自动加载：显式载入，保证 DATABASE_PATH 指向真库。
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, ".env"))
except Exception:
    pass

#: 真库路径：优先 .env 的 DATABASE_PATH；否则回退到 <项目父目录>/database/kaoyan.db。
DB_PATH = os.environ.get("DATABASE_PATH", "").strip() or os.path.join(
    os.path.dirname(BASE_DIR), "database", "kaoyan.db"
)

#: 重点科目（用户点名，最终报告单独展示）
FOCUS_SUBJECTS = ["政治", "计算机学科专业基础408", "信号与系统", "通信原理", "光学与工程光学", "光学"]

#: 第 4 层：考点级细分（curated syllabus sub-points）。
#: 背景：408 有 292 题却只有 20 个**章节级**知识点，缺少「考点级」粒度；
#: 政治 814 题只有 5 个章节级知识点。taxonomy 只到大纲章级，不足以细分。
#: 本层给出标准的考研大纲**考点级**知识点（公开考纲，确定性常量，非 LLM 生成），
#: 格式 {科目: {章节名: [考点名, ...]}}，章节名须与 taxonomy.chapters_of() 一致。
#: 幂等：同名同科跳过；父级 parent_id 指向该章节知识点（若存在）。
SUBTOPIC_MAP: dict[str, dict[str, list[str]]] = {
    "计算机学科专业基础408": {
        "数据结构·线性表": ["顺序表", "单链表", "双链表", "循环链表", "静态链表"],
        "数据结构·栈队列与数组": ["栈", "队列", "循环队列", "双端队列", "特殊矩阵的压缩存储"],
        "数据结构·树与二叉树": ["二叉树遍历", "线索二叉树", "树与森林的转换", "哈夫曼树与哈夫曼编码", "二叉排序树", "平衡二叉树", "并查集"],
        "数据结构·图": ["图的存储结构", "图的遍历", "最小生成树", "最短路径", "拓扑排序", "关键路径"],
        "数据结构·查找": ["顺序查找", "折半查找", "分块查找", "B树与B+树", "散列表", "KMP算法"],
        "数据结构·排序": ["插入排序", "希尔排序", "冒泡排序", "快速排序", "选择排序", "堆排序", "归并排序", "基数排序", "外部排序"],
        "计算机组成原理·数据的表示和运算": ["定点数的表示与运算", "浮点数的表示与运算", "溢出判断", "ALU与加法器", "校验码"],
        "计算机组成原理·存储系统": ["Cache", "主存与存储芯片", "虚拟存储器", "磁盘与存储器层次结构"],
        "计算机组成原理·指令系统": ["指令格式", "寻址方式", "CISC与RISC", "指令流水线"],
        "计算机组成原理·中央处理器": ["CPU的功能与结构", "数据通路", "控制器", "异常与中断", "多处理器基础"],
        "计算机组成原理·总线与IO": ["总线", "IO接口", "程序查询方式", "中断方式", "DMA方式"],
        "操作系统·进程与线程": ["进程", "线程", "调度算法", "同步与互斥", "死锁", "信号量机制", "管程"],
        "操作系统·内存管理": ["连续分配管理方式", "分页管理", "分段管理", "段页式管理", "页面置换算法", "抖动与工作集"],
        "操作系统·文件管理": ["文件逻辑结构", "文件物理结构", "目录结构", "文件共享与保护", "磁盘空间管理"],
        "操作系统·IO管理": ["IO软件层次结构", "缓冲区管理", "设备分配", "磁盘调度算法"],
        "计算机网络·体系结构": ["OSI参考模型", "TCP/IP模型", "性能指标"],
        "计算机网络·物理层与数据链路层": ["编码与调制", "传输介质", "差错控制", "流量控制与可靠传输", "介质访问控制", "以太网与交换机", "组帧"],
        "计算机网络·网络层": ["IPv4", "子网划分与CIDR", "ARP", "ICMP", "路由算法", "RIP与OSPF", "IPv6", "NAT"],
        "计算机网络·传输层": ["UDP", "TCP连接管理", "TCP可靠传输", "TCP流量控制", "TCP拥塞控制"],
        "计算机网络·应用层": ["DNS", "HTTP", "FTP", "电子邮件", "DHCP"],
    },
    "政治": {
        "马克思主义基本原理": ["唯物论", "辩证法", "认识论", "唯物史观", "资本主义本质", "垄断资本主义", "社会主义发展"],
        "毛泽东思想和中国特色社会主义理论体系": ["毛泽东思想", "新民主主义革命理论", "社会主义改造理论", "邓小平理论", "三个代表重要思想", "科学发展观", "习近平新时代中国特色社会主义思想"],
        "中国近现代史纲要": ["近代中国屈辱史", "旧民主主义革命", "新民主主义革命", "社会主义革命与建设", "改革开放与现代化建设"],
        "思想道德与法治": ["人生观与价值观", "理想信念", "中国精神", "社会主义核心价值观", "道德修养", "法治素养", "宪法与法律体系"],
        "形势与政策": ["年度时事政治", "党和国家重大方针政策", "国际形势与外交"],
    },
    "信号与系统": {
        "第1章 信号与系统概述": ["信号的分类", "基本信号", "信号的时域变换", "系统的性质与分类"],
        "第2章 连续时间系统的时域分析": ["卷积积分", "冲激响应与阶跃响应", "系统微分方程求解"],
        "第3章 傅里叶变换": ["傅里叶变换性质", "傅里叶反变换", "频域分析"],
        "第4章 拉普拉斯变换与s域分析": ["拉普拉斯变换与性质", "系统函数", "零极点分析", "稳定性判断"],
        "第6章 离散时间系统的时域分析": ["卷积和", "单位序列响应", "差分方程求解"],
        "第7章 z变换与z域分析": ["z变换与性质", "系统函数与零极点", "离散系统稳定性"],
        "第9章 采样定理与信号重建": ["采样定理", "频谱混叠", "信号重建", "零阶保持"],
    },
    "通信原理": {
        "第3章 随机过程": ["随机过程基本概念", "平稳随机过程", "高斯过程与窄带过程"],
        "第4章 信道": ["信道的数学模型", "恒参信道与随参信道", "信道容量"],
        "第5章 模拟调制系统": ["幅度调制AM/DSB/SSB", "角度调制FM/PM", "抗噪声性能"],
        "第6章 数字基带传输系统": ["数字基带信号", "基带传输与码间串扰", "眼图", "时域均衡"],
        "第7章 数字带通传输系统": ["2ASK", "2FSK", "2PSK与2DPSK", "误码率分析"],
        "第9章 模拟信号的数字传输": ["抽样定理", "量化与编码", "PCM", "ΔM与DPCM"],
        "第11章 差错控制编码": ["纠错编码原理", "线性分组码", "循环码", "卷积码"],
        "第13章 同步原理": ["载波同步", "位同步", "群同步"],
    },
    "光学与工程光学": {
        "几何光学·理想光学系统": ["理想光学系统成像", "基点与基面", "物像关系公式"],
        "几何光学·光线的光路计算及像差理论": ["球差", "彗差与像散", "场曲与畸变", "色差"],
        "物理光学·光的干涉": ["杨氏双缝干涉", "薄膜干涉", "迈克尔逊干涉仪", "牛顿环"],
        "物理光学·光的衍射": ["单缝衍射", "圆孔衍射", "光栅衍射", "菲涅耳衍射"],
        "物理光学·光的偏振": ["偏振光", "马吕斯定律", "布儒斯特角", "双折射", "波片"],
    },
}

#: 章名前缀正则：用于剥离「第X章」「第X节」「X.」「（一）」等编号，保留语义。
#: 例："第3章 门电路" → "门电路"；"一、绪论" → "绪论"；"1.2 电阻电路" → "电阻电路"。
_CHAPTER_PREFIX_PATTERNS = [
    re.compile(r"^第\s*[0-9一二三四五六七八九十百]+\s*[章节讲部分]\s*[.、:：\-\s]*"),
    re.compile(r"^[（(]\s*[0-9一二三四五六七八九十]+\s*[)）]\s*"),
    re.compile(r"^[0-9]+\s*[.、:：]\s*[0-9]*\s*[.、:：]?\s*"),
    re.compile(r"^[一二三四五六七八九十]+\s*[、.：:]\s*"),
]


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _norm_key(text: str) -> str:
    """归一化名称用于「同科同名」查重：去除所有空白（含全角空格）。"""
    if not text:
        return ""
    return re.sub(r"[\s\u3000]+", "", str(text)).strip().lower()


def _strip_chapter_prefix(chapter: str) -> str:
    """剥离章名编号前缀，保留语义片段。

    先复用项目现有 `structure_parser._normalize_chapter()`（会尝试对齐到大纲），
    再兜底剥掉「第X章」「一、」「1.2」等编号前缀。

    Args:
        chapter: 原始章名字符串，如 "第3章 门电路"。

    Returns:
        语义名，如 "门电路"；若剥离后为空，则回退返回原文去空白后的结果。
    """
    raw = (chapter or "").strip()
    if not raw:
        return ""

    # 1) 复用项目现有归一（对齐大纲标准章名；无大纲时原样返回）
    try:
        from services.structure_parser import _normalize_chapter  # 延迟导入，避免启动期依赖
        normalized = _normalize_chapter(raw, "") or raw
    except Exception:
        normalized = raw

    # 2) 兜底剥离编号前缀（循环剥离，处理 "第1章 1.1 xxx" 这类叠加前缀）
    name = normalized.strip()
    changed = True
    while changed and name:
        changed = False
        for pat in _CHAPTER_PREFIX_PATTERNS:
            new_name = pat.sub("", name, count=1).strip()
            if new_name and new_name != name:
                name = new_name
                changed = True
                break

    # 3) 去掉两侧残留的分隔符（·、/、- 等）
    name = name.strip("·•.、,;；:：/-—_()（） \t\u3000")
    return name or normalized.strip()


def _is_valid_name(name: str) -> bool:
    """名称有效性闸门：非 NULL、非空白、非纯标点。"""
    if not name:
        return False
    stripped = str(name).strip()
    if not stripped:
        return False
    # 纯标点/纯空白视为无效
    if re.fullmatch(r"[\W_]+", stripped):
        return False
    return True


def _backup_db(con: sqlite3.Connection) -> str:
    """备份真库到 data/backups/，返回备份文件路径。"""
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_expand_kp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )
    with sqlite3.connect(bak) as dest:
        con.backup(dest)
    return bak


# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #
def _load_kp_keys(cur: sqlite3.Cursor) -> dict[str, set[str]]:
    """加载现有知识点「科目 → {归一化名称集合}」，用于幂等查重。"""
    keys: dict[str, set[str]] = {}
    for subject, name in cur.execute("SELECT subject, name FROM knowledge_points"):
        subj = (subject or "").strip()
        key = _norm_key(name)
        if not key:
            continue
        keys.setdefault(subj, set()).add(key)
    return keys


def _load_kp_counts(cur: sqlite3.Cursor) -> dict[str, int]:
    """加载现有知识点「科目 → 数量」，用于扩充前后对比。"""
    out: dict[str, int] = {}
    for subject, cnt in cur.execute(
        "SELECT subject, COUNT(*) FROM knowledge_points GROUP BY subject"
    ):
        out[(subject or "").strip()] = cnt
    return out


def _load_question_chapters(cur: sqlite3.Cursor) -> dict[str, dict[str, int]]:
    """加载题目「科目 → {原始 chapter: 题数}」（去重、非空）。"""
    out: dict[str, dict[str, int]] = {}
    for subject, chapter, cnt in cur.execute(
        "SELECT subject, chapter, COUNT(*) FROM quiz_questions "
        "WHERE chapter IS NOT NULL AND TRIM(chapter) != '' "
        "GROUP BY subject, chapter"
    ):
        out.setdefault((subject or "").strip(), {})[(chapter or "").strip()] = cnt
    return out


def _load_question_kps(cur: sqlite3.Cursor) -> dict[str, dict[str, int]]:
    """加载题目「科目 → {knowledge_point 字段值: 题数}」（去重、非空）。"""
    out: dict[str, dict[str, int]] = {}
    for subject, kp, cnt in cur.execute(
        "SELECT subject, knowledge_point, COUNT(*) FROM quiz_questions "
        "WHERE knowledge_point IS NOT NULL AND TRIM(knowledge_point) != '' "
        "GROUP BY subject, knowledge_point"
    ):
        out.setdefault((subject or "").strip(), {})[(kp or "").strip()] = cnt
    return out


def _load_subjects_with_questions(cur: sqlite3.Cursor) -> dict[str, int]:
    """加载「有题目的科目 → 题数」。"""
    return {
        (s or "").strip(): c
        for s, c in cur.execute(
            "SELECT subject, COUNT(*) FROM quiz_questions "
            "WHERE subject IS NOT NULL AND TRIM(subject) != '' GROUP BY subject"
        )
    }


# --------------------------------------------------------------------------- #
# 候选生成（三层）
# --------------------------------------------------------------------------- #
def _build_candidates(
    subjects: dict[str, int],
    chapters: dict[str, dict[str, int]],
    q_kps: dict[str, dict[str, int]],
    kp_counts: dict[str, int],
    layers: set[int],
) -> list[dict]:
    """汇总各层候选（去重、过滤已存在、过滤非法名）。

    Returns:
        候选列表，每项：
            {subject, name, chapter, source, source_detail, parent_name}
        source ∈ {"q_chapter", "syllabus", "q_kp", "subtopic"}
    """
    cands: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (subject, norm_name) 本批次内去重

    def _add(
        subject: str,
        name: str,
        chapter: str | None,
        source: str,
        detail: str,
        parent_name: str | None = None,
    ) -> None:
        if not _is_valid_name(name):
            return
        key = (subject, _norm_key(name))
        if key in seen:
            return
        seen.add(key)
        cands.append(
            {
                "subject": subject,
                "name": name.strip(),
                "chapter": (chapter or "").strip() or None,
                "source": source,
                "source_detail": detail,
                "parent_name": parent_name,
            }
        )

    # ---- 第 1 层：题目章节派生（主路径）----
    if 1 in layers:
        for subject in subjects:
            for raw_chapter, cnt in sorted(
                chapters.get(subject, {}).items(), key=lambda kv: -kv[1]
            ):
                semantic = _strip_chapter_prefix(raw_chapter)
                _add(
                    subject, semantic, raw_chapter, "q_chapter",
                    f"题目章节派生（{cnt} 题同章）",
                )

    # ---- 第 2 层：大纲补全（解决零覆盖科目）----
    if 2 in layers:
        try:
            from services import taxonomy  # 延迟导入
            for subject in subjects:
                for std_chapter in taxonomy.chapters_of(subject):
                    semantic = _strip_chapter_prefix(std_chapter)
                    _add(
                        subject, semantic, std_chapter, "syllabus",
                        "大纲章节补全（syllabus）",
                    )
        except Exception as exc:  # 大纲不可用时优雅降级，不阻断第 1/3/4 层
            print(f"[warn] 大纲补全跳过（taxonomy 不可用）: {exc}")

    # ---- 第 3 层：题目 knowledge_point 字段 ----
    if 3 in layers:
        for subject in subjects:
            for kp_name, cnt in sorted(
                q_kps.get(subject, {}).items(), key=lambda kv: -kv[1]
            ):
                _add(subject, kp_name, None, "q_kp", f"题目知识点字段（{cnt} 题）")

    # ---- 第 4 层：考点级细分（curated syllabus sub-points）----
    # 仅对「有题目」的科目补细分考点，避免给无题科目造冗余知识。
    if 4 in layers:
        for subject, ch_map in SUBTOPIC_MAP.items():
            if subject not in subjects:
                continue  # 只处理有题目的科目
            for std_chapter, subtopics in ch_map.items():
                parent_name = _strip_chapter_prefix(std_chapter)
                for st in subtopics:
                    _add(
                        subject, st, std_chapter, "subtopic",
                        f"考点级细分（{std_chapter}，标准考研大纲）",
                        parent_name=parent_name,
                    )

    return cands


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def _plan_by_subject(cands: list[dict], kp_keys: dict[str, set[str]]) -> dict[str, list[dict]]:
    """按科目归并「确认可新增」的候选（过滤掉同科同名已存在项）。"""
    plan: dict[str, list[dict]] = {}
    for c in cands:
        existing = kp_keys.get(c["subject"], set())
        if _norm_key(c["name"]) in existing:
            continue  # 同科同名已存在 → 幂等跳过
        plan.setdefault(c["subject"], []).append(c)
    return plan


def _print_report(
    subjects: dict[str, int],
    kp_counts: dict[str, int],
    plan: dict[str, list[dict]],
    total_new: int,
) -> None:
    """打印扩充前后对比 + 重点科目 + 抽查。"""
    print("\n" + "=" * 78)
    print("【扩充前后各科知识点数对比】（仅列有题目的科目）")
    print("=" * 78)
    header = f"{'科目':<26}{'题数':>7}{'扩充前':>9}{'新增':>7}{'扩充后':>9}"
    print(header)
    print("-" * 78)
    ordered = sorted(subjects.keys(), key=lambda s: -subjects.get(s, 0))
    for subj in ordered:
        before = kp_counts.get(subj, 0)
        add = len(plan.get(subj, []))
        print(f"{subj:<26}{subjects.get(subj, 0):>7}{before:>9}{add:>7}{before + add:>9}")
    print("-" * 78)
    print(f"{'合计新增':<26}{'':>7}{'':>9}{total_new:>7}")

    print("\n" + "=" * 78)
    print("【重点科目覆盖变化】（用户点名）")
    print("=" * 78)
    for subj in FOCUS_SUBJECTS:
        if subj not in subjects and subj not in plan:
            continue
        before = kp_counts.get(subj, 0)
        add = len(plan.get(subj, []))
        qn = subjects.get(subj, 0)
        tag = "✔ 从 0/极少 → 有覆盖" if before <= 20 else ""
        print(f"{subj:<26} 题 {qn:>5} | 知识点 {before:>3} → {before + add:>3} (+{add}) {tag}")

    print("\n" + "=" * 78)
    print("【各层新增明细】")
    print("=" * 78)
    stat: dict[str, int] = {}
    for items in plan.values():
        for it in items:
            stat[it["source"]] = stat.get(it["source"], 0) + 1
    name_map = {
        "q_chapter": "第1层·题目章节派生",
        "syllabus": "第2层·大纲补全",
        "q_kp": "第3层·题目知识点字段",
        "subtopic": "第4层·考点级细分",
    }
    for k, v in sorted(stat.items(), key=lambda kv: -kv[1]):
        print(f"  {name_map.get(k, k):<24} {v:>6} 条")


def _print_samples(plan: dict[str, list[dict]], sample: int) -> None:
    """打印抽查样本（跨科目轮询，保证重点科目有代表）。"""
    print("\n" + "=" * 78)
    print(f"【抽查 {sample} 个新增知识点（供人工核验命名质量）】")
    print("=" * 78)
    # 优先展示重点科目
    ordered = [s for s in FOCUS_SUBJECTS if s in plan] + [
        s for s in plan if s not in FOCUS_SUBJECTS
    ]
    picked: list[dict] = []
    idx = 0
    while len(picked) < sample:
        progressed = False
        for subj in ordered:
            items = plan.get(subj, [])
            if idx < len(items):
                picked.append(items[idx])
                progressed = True
                if len(picked) >= sample:
                    break
        if not progressed:
            break
        idx += 1
    for i, it in enumerate(picked, 1):
        print(
            f"  {i:>2}. [{it['subject']}] name='{it['name']}'  "
            f"chapter='{it['chapter']}'  来源={it['source']}"
        )
    if not picked:
        print("  （无新增）")


# --------------------------------------------------------------------------- #
# 写库
# --------------------------------------------------------------------------- #
def _apply_inserts(cur: sqlite3.Cursor, plan: dict[str, list[dict]]) -> int:
    """执行插入，返回实际插入条数（同科同名二次校验，避免并发/重复）。

    支持 parent_name：若该父知识点（同科同名）已存在，则回填 parent_id 建立
    「章节 → 考点」层级；否则 parent_id 置 NULL（不阻断插入）。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    for subject, items in plan.items():
        # 当前科目「归一化名 → id」映射（含已有 + 本批已插入）
        name_to_id: dict[str, int] = {
            _norm_key(n): i
            for (n, i) in cur.execute(
                "SELECT name, id FROM knowledge_points WHERE subject = ?", (subject,)
            )
        }
        for it in items:
            key = _norm_key(it["name"])
            if key in name_to_id:
                continue  # 幂等二次闸门
            parent_id = None
            pname = it.get("parent_name")
            if pname:
                parent_id = name_to_id.get(_norm_key(pname))
            cur.execute(
                "INSERT INTO knowledge_points "
                "(name, subject, chapter, parent_id, mastery, exam_frequency, "
                " description, created_at, document_id, question_types, difficulty, "
                " review_count, ease_factor, interval, lapses, question_count) "
                "VALUES (?, ?, ?, ?, 0, 0, ?, ?, NULL, NULL, 3, 0, 2.5, 0, 0, 0)",
                (
                    it["name"],
                    subject,
                    it["chapter"],
                    parent_id,
                    f"知识点扩充（M1-2，{it['source_detail']}）",
                    now,
                ),
            )
            name_to_id[key] = cur.lastrowid
            inserted += 1
    return inserted


def _backfill_question_count(cur: sqlite3.Cursor) -> int:
    """回填 question_count = 同科、同章名精确匹配的题数（简单可靠口径）。

    口径说明：用 `quiz_questions.chapter` 与知识点 `chapter`（原始章名）做
    **同科精确匹配**计数；对无 chapter 的知识点（如第 3 层派生）保持原值不动。
    这是保守口径，避免与 M1-1 的关联回填口径冲突。
    """
    rows = cur.execute(
        "SELECT id, subject, chapter FROM knowledge_points "
        "WHERE chapter IS NOT NULL AND TRIM(chapter) != ''"
    ).fetchall()
    updated = 0
    for kp_id, subject, chapter in rows:
        cnt = cur.execute(
            "SELECT COUNT(*) FROM quiz_questions "
            "WHERE subject = ? AND chapter = ? "
            "AND chapter IS NOT NULL AND TRIM(chapter) != ''",
            (subject, chapter),
        ).fetchone()[0]
        if cnt > 0:
            cur.execute(
                "UPDATE knowledge_points SET question_count = ? WHERE id = ?",
                (cnt, kp_id),
            )
            updated += 1
    return updated


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="知识点扩充（M1-2）：覆盖所有有题目的科目")
    ap.add_argument("--apply", action="store_true", help="实际写库（默认仅预览）")
    ap.add_argument(
        "--layers",
        default="1,2,3,4",
        help="启用层，逗号分隔：1=题目章节 2=大纲补全 3=题目知识点字段 4=考点级细分（默认全部）",
    )
    ap.add_argument("--sample", type=int, default=10, help="抽查样例条数（默认 10）")
    ap.add_argument(
        "--backfill-count",
        action="store_true",
        help="写库后回填 knowledge_points.question_count（同科同章精确口径）",
    )
    return ap.parse_args()


def main() -> int:
    args = _parse_args()
    layers = {int(x) for x in args.layers.split(",") if x.strip().isdigit()}

    if not os.path.exists(DB_PATH):
        print(f"[error] 真库不存在: {DB_PATH}")
        return 2

    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    print(f"数据库: {DB_PATH}")
    subjects = _load_subjects_with_questions(cur)
    kp_counts = _load_kp_counts(cur)
    kp_keys = _load_kp_keys(cur)
    chapters = _load_question_chapters(cur)
    q_kps = _load_question_kps(cur)

    total_kp = cur.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]
    total_q = cur.execute("SELECT COUNT(*) FROM quiz_questions").fetchone()[0]
    print(f"现状：知识点 {total_kp} 个 / 题目 {total_q} 题 / 有题目科目 {len(subjects)} 个")
    print(f"启用层：{sorted(layers)}")

    cands = _build_candidates(subjects, chapters, q_kps, kp_counts, layers)
    plan = _plan_by_subject(cands, kp_keys)
    total_new = sum(len(v) for v in plan.values())

    _print_report(subjects, kp_counts, plan, total_new)
    _print_samples(plan, args.sample)

    if not args.apply:
        print("\n[DRY-RUN] 未写库。确认无误后加 --apply 执行。")
        con.close()
        return 0

    # ---- 备份 ----
    bak = _backup_db(con)
    print(f"\n已备份 → {bak}")

    # ---- 写库 ----
    inserted = _apply_inserts(cur, plan)
    con.commit()
    after_kp = cur.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]
    print(f"已插入 {inserted} 条知识点（{total_kp} → {after_kp}）")

    # ---- 可选回填 question_count ----
    if args.backfill_count:
        updated = _backfill_question_count(cur)
        con.commit()
        print(f"已回填 question_count：{updated} 个知识点")

    # ---- 扩充后各科分布（落库后复核）----
    print("\n【落库后各科知识点数】")
    for subj, cnt in cur.execute(
        "SELECT subject, COUNT(*) FROM knowledge_points GROUP BY subject ORDER BY 2 DESC"
    ):
        print(f"  {(subj or ''):<26}{cnt:>6}")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
