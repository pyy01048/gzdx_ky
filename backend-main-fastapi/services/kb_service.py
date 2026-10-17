# -*- coding: utf-8 -*-
"""知识库入库服务（P0-1 闭环核心）。

把"任意文本"切分为知识分块并写入 knowledge_chunks，
同步到 FTS5 全文检索表，使其可被 RAG 检索到。

这是实现"本地 + 网盘知识库精准回答"的前提：
此前 knowledge_chunks 只有一次性种子脚本（scripts/import_kb_data.py）
写入，用户上传的文档 / 网盘资料完全进不了知识库。
本服务让任何文本来源都能进入知识库并被 AI 检索。
"""
from __future__ import annotations

import os
import re
import collections

from sqlalchemy.orm import Session

from services.dbapi_compat import wrap_conn
from models import Document, KnowledgeChunk
from services import search_service
from services.delete_guard import require_physical_delete_enabled


# --------------------------------------------------------------------------- #
# 学科分类
#
# ⚠️ 设计教训（2026-10 修）：原先的列表把**科目词**和**文档类型词**混在一起，
# 且用"首个匹配即返回"。结果 `_ENGLISH` 里的 '精讲册'、'逐词逐句'、'真题逐题细解'
# 命中了《【电子技术基础-数字部分】康华光 考研真题解析 讲义》，
# 把 187 篇电子技术资料误标成「英语」。
#
# 现在的规则：
#  1. **强信号**（科目专有名词）加权 3 分
#  2. **弱信号**（题型名，如"阅读""翻译"，各科都有）加权 1 分
#  3. **文档类型词**（精讲册/真题/月考/试卷…）**完全不参与科目判定** ——
#     它们只说明"这是什么资料"，不说明"这是哪一科"
#  4. 文件名分数不足时，用正文关键词反查补足
# --------------------------------------------------------------------------- #

#: 各科强信号词（文件名命中直接 +3）
#:
#: ⚠️ 匹配陷阱（2026-10 修）：像 `电路` 这种词是**其他词的子串** ——
#: `时序电路`、`组合电路`、`放大电路` 都是**数电/模电**的章节名，
#: 用朴素子串匹配会把它们全判成"电路理论"。
#: 所以引入 `(关键词, 排除前缀)` 二元组：紧邻排除前缀出现时不算命中。
_SUBJECT_STRONG: dict[str, list] = {
    "数字电子技术": [
        "数电", "数字电路", "数字电子", "逻辑代数", "逻辑函数", "门电路", "触发器",
        "组合逻辑", "时序逻辑", "锁存器", "寄存器", "可编程逻辑", "vhdl", "verilog",
        "数制", "编码器", "译码器", "计数器", "卡诺图", "二进制", "数据选择器",
        "全加器", "半加器", "移位寄存器", "施密特", "555", "阎石",
        # 数电特有的"XX电路"表述（要抢在"电路"的排除判定之前命中）
        "时序电路", "组合电路", "脉冲电路", "整形电路", "存储电路", "逻辑电路",
        "时序逻辑电路", "组合逻辑电路", "触发电路", "计数电路", "中规模", "小规模",
        "存储器", "随机存储器", "只读存储器", "ram", "rom", "sram", "dram",
    ],
    "模拟电子技术": [
        "模电", "模拟电子", "模拟电路", "模拟部分", "放大电路", "半导体器件", "多级放大",
        "集成运算", "运算放大", "功率放大", "直流电源", "电子线路", "二极管", "三极管",
        "场效应", "差分放大", "共射", "共集", "共基", "静态工作点", "基本放大",
        "童诗白", "康华光", "pn结",
        # 裸"电子技术(基础)"专名：无"数字/模拟"限定时按模电归类
        #（该教材主体是模电半导体内容；若出现"数字部分"由 _MUTEX_HINTS 纠正为数电）
        "电子技术基础", "电子技术",
    ],
    "英语": [
        "英语", "英一", "英二", "长难句", "背单词", "单词", "词汇", "作文",
        "完形", "刘晓艳", "阅读理解", "考研英语", "英语真题",
    ],
    "数学": [
        "数学", "高数", "高等数学", "线代", "线性代数", "概率论", "数理统计",
        "张宇", "660", "基础30讲", "数一", "数二", "数三",
        "概统", "概率统计", "微积分", "同济", "复习全书",
        # ⚠️ 裸「1000题」是**跨科歧义词**：肖秀荣1000题是政治、张宇1000题是数学，
        # 写法完全一样。2026-10 实测它把
        # `专业课-其他/政治/1000题：学习打卡表（新思想）.pdf` 直接判成数学，
        # 同期一批肖1000 / 政治课堂笔记被误归到数学。裸词一律**不记分**，
        # 只认带科目限定的写法，其余交给路径目录与正文特征。
        "张宇1000题", "数学1000题",
    ],
    "政治": [
        "政治", "马原", "毛中特", "史纲", "思修", "肖秀荣", "徐涛", "腿姐",
        "辩证法", "唯物史观", "近代史纲要",
        # 补（2026-10）：政治五大板块里的「新思想」（习思想）此前完全不在词表，
        # 配合上面被数学抢走的「1000题」，政治资料一旦文件名不含「政治/马原/史纲」
        # 就没有任何强信号可命中，只能掉进正文兜底被判成别的科。
        "新思想", "毛概", "马哲", "时政", "考研政治", "政治理论", "思修法基",
        "肖1000", "帽子题", "优题库",
    ],
    # ---- 专业课支撑科目 ----
    "电路": [
        # "电路" 需排除数电/模电的章节词
        ("电路", ["时序", "组合", "放大", "逻辑", "脉冲", "整形", "存储", "门",
                 "序", "合", "大", "辑", "冲", "形", "储"]),
        # "电路分析" 同理：数电里有"时序电路分析专题"这种表述
        ("电路分析", ["时序", "组合", "放大", "逻辑", "脉冲", "整形", "存储", "门",
                   "序", "合", "大", "辑", "冲", "形", "储"]),
        "电路原理", "邱关源", "基尔霍夫", "戴维南", "诺顿",
        "节点电压", "网孔电流", "三相电路", "二端口", "耦合电感", "相量法",
    ],
    "信号与系统": [
        "信号与系统", "信号系统", "郑君里", "奥本海姆", "卷积", "傅里叶变换",
        "拉普拉斯变换", "z变换", "抽样定理", "采样定理", "冲激响应", "系统函数",
    ],
    "通信原理": [
        "通信原理", "通信系统", "樊昌信", "调制解调", "误码率", "信噪比",
        "香农", "基带传输", "带通传输", "差错控制", "汉明码", "循环码", "眼图",
    ],
    "光学与工程光学": [
        "光学", "工程光学", "物理光学", "应用光学", "郁道银", "干涉", "衍射",
        "偏振", "光栅", "双缝", "牛顿环", "迈克尔逊", "透镜", "像差",
    ],
    "普通物理": [
        "普通物理", "大学物理", "程守洙", "马文蔚", "刚体", "转动惯量",
        "热力学", "静电场", "稳恒磁场", "电磁感应", "麦克斯韦", "简谐振动",
        "电磁场", "电磁波", "波动光学", "狭义相对论",
    ],
    "计算机学科专业基础408": [
        "408", "数据结构", "计算机组成", "操作系统", "计算机网络", "计算机统考",
        "线性表", "二叉树", "图论", "排序算法", "进程管理", "内存管理",
    ],
}


def _kw_hit(keyword, name: str) -> bool:
    """关键词命中判定，支持 `(词, 排除前缀)` 二元组。"""
    if isinstance(keyword, tuple):
        word, excludes = keyword
        w = word.lower()
        start = 0
        while True:
            i = name.find(w, start)
            if i == -1:
                return False
            # 取该词前面 2 个字判断是否踩到排除前缀
            prefix = name[max(0, i - 2):i]
            if not any(prefix.endswith(x) for x in excludes):
                return True
            start = i + 1
    return keyword.lower() in name

#: 弱信号（题型名，多科通用 —— 只给 1 分，不能定科）
_SUBJECT_WEAK: dict[str, list[str]] = {
    "英语": ["翻译", "写作", "阅读"],
    "政治": ["分析题", "多选题"],
}

#: 文档类型词：**只描述资料形态，不参与科目判定**
_DOC_TYPE_WORDS = [
    "精讲册", "逐词逐句", "真题逐题细解", "真题", "月考", "模拟考试", "试卷",
    "答案", "测试", "考纲", "讲义", "笔记", "习题", "解析", "速查", "大纲",
    "课件", "辅导", "必练", "真题及答案",
]

_CONTENT_KW = {
    '数字电子技术': ['逻辑门', '触发器', '计数器', '译码器', '时序电路', '组合逻辑', '布尔', '卡诺图',
                  '二进制', '与非', '或非', '寄存器', '锁存器', '数据选择器', '全加器', '真值表', '编码',
                  'vhdl', '555', '施密特', '状态方程', '驱动方程', '激励表', '波形图'],
    '模拟电子技术': ['二极管', '三极管', '运放', '运算放大', '反馈', '差分', '共射', '共集', '场效应',
                  '整流', '稳压', '偏置', '静态工作点', '放大倍数', '波特图', '功放', 'pn结', '基极', '集电极'],
    '英语': ['passage', 'sentence', 'vocabulary', 'reading', '单词', '词汇', '长难句', '完形填空',
             '阅读理解', 'the ', ' and ', ' that ', ' which '],
    '数学': ['函数', '导数', '极限', '矩阵', '概率', '积分', '向量', '行列式', '微分', '连续', '收敛',
             '概率统计', '大数定律', '分布函数', '抽样'],
    '政治': ['马克思主义', '唯物', '辩证法', '生产力', '生产关系', '社会主义', '矛盾', '实践'],
    '电路': ['基尔霍夫', '节点电压', '网孔', '戴维南', '诺顿', '叠加定理', '相量', '谐振', '三相'],
    '信号与系统': ['卷积', '傅里叶', '拉普拉斯', 'z变换', '冲激响应', '系统函数', '零极点', '频谱'],
    '通信原理': ['调制', '解调', '误码率', '信噪比', '香农', '基带', '带通', '汉明码', '眼图'],
    '光学与工程光学': ['干涉', '衍射', '偏振', '光栅', '双缝', '透镜', '折射', '全反射'],
    '普通物理': ['刚体', '转动惯量', '动量守恒', '热力学', '熵', '高斯定理', '电磁感应', '麦克斯韦',
             '电磁场', '电磁波', '静电场', '稳恒磁场', '简谐振动', '波动方程', '狭义相对论'],
    '计算机学科专业基础408': ['数据结构', '二叉树', '链表', '进程', '死锁', '页面置换', 'tcp',
                       '指令系统', '流水线', 'cache', '路由'],
}


#: 互斥词对：文件名同时出现两者时，按"更具体"的一方定科。
#  例：《【电子技术基础-数字部分】康华光…》里 "模拟部分" 不出现，
#  但 "数字部分" 明确指向数电 —— 不能因为"康华光"两边都沾就判错。
_MUTEX_HINTS = [
    ("数字电子技术", "模拟电子技术",
     ["数字部分", "数字电路", "数电", "逻辑", "数字电子"],
     ["模拟部分", "模拟电路", "模电", "放大"]),
]


def _apply_mutex(name: str, scores: collections.Counter) -> collections.Counter:
    """用互斥线索纠正数电/模电这类易混判定。

    权重要**足够大以压过基础分**：像《【电子技术基础-数字部分】康华光…》里
    "电子技术基础"(模电+3) 与 "康华光"(模电+3) 合计 6 分，若互斥权重太小
    （如 ×4）会被模电基础分反超。这里给 ×10，确保"数字部分/模拟部分"这类
    **明确指向**能决定性生效。
    """
    n = (name or "").lower()
    for subj_a, subj_b, hints_a, hints_b in _MUTEX_HINTS:
        a = sum(1 for h in hints_a if h.lower() in n)
        b = sum(1 for h in hints_b if h.lower() in n)
        if a and not b:
            scores[subj_a] += a * 10      # 明确指向 A，压倒性加权
        elif b and not a:
            scores[subj_b] += b * 10
    return scores


#: 路径目录名 → 学科。**目录名是人工整理时已经给出的学科归属**，是可信度最高的
#: 一路信号（比文件名关键词和正文关键词都强）。
#:
#: 为什么必须有它（2026-10）：`smart_ingest.process_file` 调用
#: `extract_metadata(os.path.basename(path), text)` —— 只传文件名，把
#: `.../政治/xxx.pdf` 里的「政治」整段丢掉了。于是像
#: `1000题：学习打卡表（新思想）.pdf` 这种文件名里没有「政治」二字的资料，
#: 只能靠正文兜底，被判成数学。目录名是白送的强信号，不该丢。
_PATH_DIR_SUBJECTS: dict[str, str] = {
    # ---- 公共课 ----
    "政治": "政治", "考研政治": "政治", "政治理论": "政治",
    "马原": "政治", "马克思主义基本原理": "政治", "马哲": "政治",
    "毛概": "政治", "毛中特": "政治", "毛泽东思想": "政治",
    "史纲": "政治", "近代史纲要": "政治", "中国近现代史纲要": "政治",
    "思修": "政治", "思修法基": "政治", "思想道德与法治": "政治",
    "新思想": "政治", "新思想概论": "政治", "习思想": "政治", "时政": "政治",
    "数学": "数学", "考研数学": "数学", "数学辅导": "数学",
    "高数": "数学", "高等数学": "数学",
    "线代": "数学", "线性代数": "数学", "概率": "数学", "概率论": "数学",
    "英语": "英语", "考研英语": "英语", "英语一": "英语", "英语二": "英语",
    # ---- 专业课 ----
    "数字电子技术": "数字电子技术", "数电": "数字电子技术", "数字电路": "数字电子技术",
    "模拟电子技术": "模拟电子技术", "模电": "模拟电子技术", "模拟电路": "模拟电子技术",
    "模电试题": "模拟电子技术",
    # 「电子技术基础」是模电+数电的合并课，按 taxonomy.SUBJECT_ALIASES 的既有口径
    # 归一到数字电子技术（834 同理，见下）。
    "电子技术基础": "数字电子技术", "电子技术": "数字电子技术",
    "电路": "电路", "电路分析": "电路", "电路原理": "电路", "电路理论": "电路",
    "信号与系统": "信号与系统", "信号系统": "信号与系统", "信号": "信号与系统",
    "通信原理": "通信原理", "通信": "通信原理", "通信系统": "通信原理",
    "光学": "光学与工程光学", "工程光学": "光学与工程光学", "物理光学": "光学与工程光学",
    "普通物理": "普通物理", "大学物理": "普通物理", "物理": "普通物理",
    "408": "计算机学科专业基础408", "计算机408": "计算机学科专业基础408",
    "计算机专业课": "计算机学科专业基础408", "计算机": "计算机学科专业基础408",
    "数据结构": "计算机学科专业基础408", "操作系统": "计算机学科专业基础408",
    "计算机网络": "计算机学科专业基础408", "软件工程": "计算机学科专业基础408",
    # 院校自命题科目代码：贵州大学 834 = 电子技术基础
    "834": "数字电子技术", "贵大834": "数字电子技术",
    # 真题集合：不指科目，但显式目录名也算一种归属
    "真题综合": "真题综合",
}

#: 目录名里混着的序号前缀（「01.马原」「16.电路」「27计算机408」「(2.1)—」…）
_PATH_DIR_NOISE_PREFIX = re.compile(r"^\s*[\(（]?\d+(?:[.\-_]\d+)*[)）]?\s*[.、_\-\s]*")


def _subject_from_path(path: str):
    """从**文件路径的目录段**推断学科，命中返回标准科目名，否则 None。

    从最深层目录往浅层找，第一个命中即返回 —— 深层目录更具体
    （`专业课-其他/通信/信号/xxx.pdf` 里「信号」比「通信」准）。
    """
    if not path:
        return None
    segs = [s for s in str(path).replace("\\", "/").split("/") if s]
    if len(segs) < 2:          # 只有文件名，没有目录信息
        return None
    for seg in reversed(segs[:-1]):
        s = _PATH_DIR_NOISE_PREFIX.sub("", seg).strip()
        if not s:
            continue
        hit = _PATH_DIR_SUBJECTS.get(s)
        if hit:
            return hit
        # 「27计算机408」「考研政治历年真题」这类带修饰词的目录名再做一次包含匹配
        for key, subj in _PATH_DIR_SUBJECTS.items():
            if len(key) >= 2 and key in s:
                return subj
    return None


def _subject_scores(name: str) -> collections.Counter:
    """按文件名给各科打分（强信号 3 分，弱信号 1 分）。"""
    n = (name or "").lower()
    scores: collections.Counter = collections.Counter()
    for subj, kws in _SUBJECT_STRONG.items():
        hits = sum(1 for k in kws if _kw_hit(k, n))
        if hits:
            scores[subj] += hits * 3
    for subj, kws in _SUBJECT_WEAK.items():
        hits = sum(1 for k in kws if _kw_hit(k, n))
        if hits:
            scores[subj] += hits
    return _apply_mutex(name, scores)


#: 解析失败时写进 content 的标记前缀（见 document_parser）。
#: ⚠️ 这类文本是**英文报错信息**，绝不能被当成"英语资料"或被用来判科目。
_PARSE_FAIL_MARK = "[解析失败"


def is_parse_failure(content: str | None) -> bool:
    """正文是否是解析失败留下的报错信息（而非真实内容）。"""
    return bool(content) and content.lstrip().startswith(_PARSE_FAIL_MARK)


def _latin_ratio(text: str) -> float:
    """拉丁字母占非空白字符的比例。用于判定"这是不是英语资料"。"""
    if not text:
        return 0.0
    letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    nonspace = sum(1 for ch in text if not ch.isspace())
    return letters / max(nonspace, 1)


def classify_subject_confidence(
    name: str, content_text: str = '', *, allow_weak: bool = False,
    path: str = '',
) -> tuple[str, bool]:
    """返回 `(科目, 是否高置信)`。

    高置信 = 有明确的科目强信号，或正文关键词足够集中。
    低置信 = 仅靠"真题/试卷"这类形态词兜底，或压根没法判。

    批量重标存量数据时应该**只用高置信结果** ——
    否则会把原本合理的标注改成臆测值，越改越乱。

    判定优先级（2026-10 修）：**路径目录名 > 文件名强信号 > 正文补分 > 兜底**。
    `path` 是可选的第 0 路信号：目录名是人工整理时给出的学科归属，比从文件名
    猜准得多；传了就优先采信。
    """
    from services import taxonomy

    n = (name or "").lower()
    content = content_text or ""
    if is_parse_failure(content):
        content = ""      # 报错信息不参与判定

    # -1. 路径目录名（最强信号）：`.../政治/xxx.pdf` → 政治。
    #     实测没它的时候，`1000题：学习打卡表（新思想）.pdf` 会被判成数学。
    if path:
        dir_subj = _subject_from_path(path)
        if dir_subj:
            return taxonomy.normalize_subject(dir_subj), True

    # 0. 英语的决定性信号（文件名无科目信息时，靠正文拉丁字母密度）。
    #    加最小长度门槛：几十个字符的 OCR 碎片或报错片段不足以定科，
    #    否则会把"微信图片_xxx.jpg"这类碎片判成英语。
    #    80 字是实测的平衡点：真实英语段落（百字以上）能过，
    #    微信图片那种 56 字碎片被挡住。
    if len(content) >= 80 and not _subject_scores(name):
        if _latin_ratio(content[:4000]) > 0.35:
            return "英语", True

    # 1. 文件名强信号
    scores = _subject_scores(name)
    if scores:
        top, cnt = scores.most_common(1)[0]
        second = scores.most_common(2)[1][1] if len(scores) > 1 else 0
        if cnt >= 3 and cnt > second:
            return taxonomy.normalize_subject(top), True

    # 2. 正文补分（累加到文件名分数上）
    if content:
        t = content[:5000].lower()
        for subj, kws in _CONTENT_KW.items():
            hits = sum(1 for kw in kws if _kw_hit(kw, t))
            if hits:
                scores[subj] += hits
        if scores:
            top, cnt = scores.most_common(1)[0]
            second = scores.most_common(2)[1][1] if len(scores) > 1 else 0
            if cnt >= 2 and cnt > second:
                return taxonomy.normalize_subject(top), True

    # 3. 兜底：低置信
    if any(_kw_hit(k, n) for k in _DOC_TYPE_WORDS):
        return "真题综合", False
    return "其他", False


def classify_subject(name: str, content_text: str = '', path: str = '') -> str:
    """根据文件名 + 正文推断学科分类（对外主入口）。

    先按文件名打分（强信号优先），分数不足时用正文关键词补足。
    文档类型词（真题/讲义/答案…）不参与科目判定。

    `path` 可选：给完整文件路径时会**优先采信路径里的学科目录名**
    （`.../政治/xxx.pdf` → 政治），这是实测下来最准的一路信号。
    """
    return classify_subject_confidence(name, content_text, path=path)[0]


# --------------------------------------------------------------------------- #
# 文本切分
# --------------------------------------------------------------------------- #
def chunk_text(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    """把长文本按段落 / 句子切分为带重叠的知识分块。

    - 优先按空行分段，段落内不足 chunk_size 则合并；
    - 超长段落按中英文句末标点切分；
    - 除首块外，每块前缀上一块的尾部 overlap 字符，保留上下文连贯。
    """
    text = (text or '').strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r'\n+', text) if p.strip()]
    chunks: list[str] = []
    cur = ''

    for para in paragraphs:
        if len(cur) + len(para) <= chunk_size:
            cur = (cur + '\n' + para).strip()
            continue
        # 当前累积已满，先落盘
        if cur:
            chunks.append(cur)
        if len(para) > chunk_size:
            # 超长段落按句切分
            for sent in re.split(r'(?<=[。！？；.!?;])', para):
                sent = sent.strip()
                if not sent:
                    continue
                if len(cur) + len(sent) <= chunk_size:
                    cur = (cur + sent).strip()
                else:
                    if cur:
                        chunks.append(cur)
                    cur = sent
            if cur.strip():
                chunks.append(cur.strip())
                cur = ''
        else:
            cur = para

    if cur.strip():
        chunks.append(cur.strip())

    # 重叠拼接
    if overlap > 0 and len(chunks) > 1:
        merged = [chunks[0]]
        for c in chunks[1:]:
            prev = merged[-1]
            piece = (prev[-overlap:] + '\n' + c) if len(prev) >= overlap else c
            merged.append(piece)
        chunks = merged

    return [c for c in chunks if c]


def has_searchable_chunks(db: Session, doc_id) -> bool:
    """这篇文档此刻在知识库里**真的有可检索的分块**吗。

    入库路径用它决定 `index_status`，而不是用本轮 `ingest_text` 的返回值：
    重新解析被物理删除闸门拦住时，旧分块和检索镜像其实都还在、RAG 照样能搜到，
    那种情况标 failed 是另一句谎话。口径只有一个 —— 库里有块就是 indexed。
    """
    if doc_id is None:
        return False
    return db.query(KnowledgeChunk.id).filter(
        KnowledgeChunk.document_id == doc_id).first() is not None


# --------------------------------------------------------------------------- #
# 入库：文本 -> 分块 -> knowledge_chunks + FTS
# --------------------------------------------------------------------------- #
#: 块级质量下限。现库 61091 块实测：短于 80 字的 92 块基本是一行残句或目录点线，
#: 进 FTS 只会把检索命中让给噪声。
MIN_CHUNK_CHARS = 80
#: 替换符占比上限。实测替换符占比>1% 的 131 块全是乱码块，而"500 字里混进
#: 1 个 U+FFFD"的正常真题块必须放过 —— 不能为了干净删真正文。
MAX_CHUNK_MOJIBAKE_RATIO = 0.01


def chunk_is_retrievable(chunk: str) -> bool:
    """这一块值不值得进知识库？（写侧块级闸门）

    文档级闸门看整篇正文，切块之后仍会漏进"一整块都是乱码""只剩半行"这类；
    这里拦下的块**不写 knowledge_chunks**，而 FTS/向量镜像只在同一事务里跟着
    knowledge_chunks 写，所以块不存在 = 镜像里也不可能被搜到。
    """
    t = (chunk or "").strip()
    if len(t) < MIN_CHUNK_CHARS:
        return False
    if t.count(chr(0xFFFD)) > len(t) * MAX_CHUNK_MOJIBAKE_RATIO:
        return False
    return True


def ingest_text(
    db: Session,
    doc_id,
    doc_name: str,
    text: str,
    subject: str = None,
    *,
    replace: bool = False,
    content_category: str | None = None,
) -> int:
    """把一段文本切分并写入知识库。返回新建分块数。

    - 写入 knowledge_chunks（ORM）
    - 同步 knowledge_chunks_fts（FTS5 全文检索），使 RAG 可检索
    - replace=True 时先删除该文档已有的分块与 FTS 记录（用于重新解析）
    """
    text = (text or '').strip()
    if not text:
        return 0
    # 清理无效Unicode字符（代理对、控制字符等），确保能存入UTF-8数据库
    import re
    cleaned = []
    for ch in text:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            continue
        if code < 32 and ch not in ('\n', '\t', '\r'):
            continue
        if code == 0x7F:
            continue
        cleaned.append(ch)
    text = ''.join(cleaned)
    text = re.sub(r'\n{3,}', '\n\n', text)
    if not text:
        return 0
    if not subject:
        subject = classify_subject(doc_name, text)

    # 可选：清除旧分块（重新解析场景）
    if replace and doc_id is not None:
        old = db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc_id).all()
        old_ids = [c.id for c in old]
        # 物理删除闸门只在**真要删已有分块**时才要放行：
        # 本周曾因判重缺陷误删大量真题，所以清空旧块必须显式开 KAOYAN_ALLOW_PHYSICAL_DELETE。
        # 但闸门原先放在查询之前，首次入库（本来一块都没有）也被它挡死 ——
        # 而所有入库路径都传 replace=True，于是正文落库成功、分块 0 条，
        # 文档静静进不了 RAG。删 0 行不可能是数据损失，这里按 old_ids 判定。
        if old_ids:
            require_physical_delete_enabled("knowledge_chunks")
            conn0 = wrap_conn(db.connection().connection)
            placeholders = ','.join('?' * len(old_ids))
            # 先清依赖表引用（向量表 / 错题-知识点关联），避免外键约束失败。
            # 依赖表按 sqlite_master 判定存在才删：knowledge_chunks_vec / _fts 不在 ORM
            # metadata 里，是检索侧 ensure_* 惰性建的；库还没建过它们时本就 0 行可清，
            # 若硬删会抛 "no such table" 把整个重新解析打断。
            from services.dbapi_compat import list_tables as _list_tables
            _have = {r[0] for r in _list_tables(conn0)}
            for _dep in ("knowledge_chunks_vec", "error_knowledge_links",
                         "knowledge_chunks_fts"):
                if _dep in _have:
                    conn0.execute(
                        f"DELETE FROM {_dep} WHERE chunk_id IN ({placeholders})",
                        old_ids,
                    )
            # 这里**不 commit**：raw cursor 与 ORM 同一条连接，删镜像行必须和
            # 下面的 knowledge_chunks 删除、以及新块插入进同一个事务。
            # 原先在此 commit 会把「FTS/向量已删、分块还在」的中间态钉死：
            # 一旦后续 flush/插入异常，调用方 rollback 也救不回镜像，
            # 文档就会变成「块在、检索不到」的静默损坏。
        for c in old:
            db.delete(c)
        db.flush()

    _size, _overlap = chunk_size_for_category(content_category)
    chunks = chunk_text(text, chunk_size=_size, overlap=_overlap)
    if not chunks:
        return 0

    # —— 块级质量谓词（写侧闸门）——
    # 文档级闸门看的是整篇，切块之后仍可能漏进"一整块都是乱码/一行残句"这种。
    # 阈值按现库 61091 块实测：短于 80 字的 92 块、替换符占比>1% 的 131 块，
    # 合计 223 块（0.37%）会被拦；而"500 字里 1 个 U+FFFD"这种只掉一个字符的
    # 正常块**不能**拦，否则等于为了干净把真题正文删掉。
    # 拦下的块**不写 knowledge_chunks，也就不可能进 FTS/向量镜像**
    # （镜像只在同一个事务里跟着 knowledge_chunks 写）。
    kept = [c for c in chunks if chunk_is_retrievable(c)]
    if len(kept) != len(chunks):
        print(f"[kb] 块级闸门丢弃 {len(chunks) - len(kept)}/{len(chunks)} 块: {doc_name}")
    chunks = kept
    if not chunks:
        return 0

    conn = wrap_conn(db.connection().connection)
    # 若 FTS 尚未初始化则先全量同步一次（仅首次，避免重复）
    search_service.ensure_fts_table(conn)
    # PG 侧 FTS 走 knowledge_chunks.search_vector 生成列（插入时自动填充），
    # 生产库默认**没有** knowledge_chunks_fts 镜像表；SQLite 侧才维护 FTS5 镜像虚表。
    # 但镜像表一旦存在（兼容层 / 旧数据导入），就必须跟着块一起写：
    # 上面 replace 分支在 PG 下同样会按「表存在」去删镜像行，若这里只删不写，
    # 重新解析后镜像会整篇丢失 —— 与 sync_mirror_subjects 同一口径，按表存在判定。
    from services.dbapi_compat import table_exists as _table_exists
    write_fts_mirror = (not search_service._is_pg(conn)) or _table_exists(
        conn, "knowledge_chunks_fts")

    count = 0
    for idx, ch in enumerate(chunks):
        kc = KnowledgeChunk(
            document_id=doc_id,
            doc_name=doc_name,
            chunk_index=idx,
            subject=subject,
            text=ch,
        )
        db.add(kc)
        db.flush()  # 取得自增 id
        if write_fts_mirror:
            conn.execute(
                "INSERT INTO knowledge_chunks_fts (chunk_id, document_id, subject, content) VALUES (?,?,?,?)",
                (kc.id, doc_id, subject, ch),
            )
        count += 1

    db.commit()
    return count


# --------------------------------------------------------------------------- #
# 资料层级分类（# 原始层 / 加工层 / 索引层）
# --------------------------------------------------------------------------- #
_NOTE_KW = ["笔记", "总结", "整理", "错题", "手写", "摘要", "划重点"]
_INDEX_KW = ["思维导图", "考点清单", "大纲", "目录", "速查", "索引"]
_RAW_KW = ["教材", "课本", "真题", "试卷", "试题", "题库", "习题", "讲义", "课件", "模拟"]
_IMAGE_TYPES = ("jpg", "jpeg", "png", "bmp", "tiff", "webp")


# --------------------------------------------------------------------------- #
# V11 模块5：内容语义分层（textbook / example / exam / method）
# --------------------------------------------------------------------------- #
# 与 doc_type（raw/note/index 加工层级）正交：这是"这份资料讲什么"的语义分类。
# 判定优先级：exam > example > method > textbook（兜底）。
_EXAM_KW = ["真题", "试题", "试卷", "考卷", "月考", "模拟考试", "模拟试题", "模拟题", "模拟卷", "回忆版", "年卷", "冲刺卷"]
_EXAMPLE_KW = ["题解", "例题", "典型题", "习题", "题库", "题全解", "答案部分",
                "小题专项", "解答", "课后答案", "同步辅导", "答案"]
_METHOD_KW = ["方法", "技巧", "总结", "攻略", "精讲", "思维导图", "笔记"]
_TEXTBOOK_KW = ["教材", "讲义", "课件", "课本", "基础课", "冲刺课"]
_YEAR_PAPER_RE = re.compile(r"\d{4}\s*年.*?卷")

# 差异化切分：按语义类别给不同 chunk_size（overlap ≈ chunk_size 的 1/8）
CONTENT_CATEGORY_CHUNK = {
    "textbook": (512, 64),
    "example": (1024, 128),
    "exam": (2048, 256),
    "method": (768, 96),
}
_DEFAULT_CHUNK = (600, 80)


def classify_content_category(file_name: str, content: str = "") -> str:
    """按文件名（辅以正文特征）判定内容语义分类。

    - exam    历年真题/试题/试卷/月考/模拟/回忆版卷
    - example 典型例题/题解/习题解答/题库/课后答案
    - method  解题方法/技巧/总结/攻略/精讲
    - textbook 教材/讲义/课件/课本/基础课（拿不准兜底）
    """
    n = file_name or ""
    if any(k in n for k in _EXAM_KW) or _YEAR_PAPER_RE.search(n):
        return "exam"
    if any(k in n for k in _EXAMPLE_KW):
        return "example"
    if any(k in n for k in _METHOD_KW):
        return "method"
    if any(k in n for k in _TEXTBOOK_KW):
        return "textbook"
    return "textbook"


def chunk_size_for_category(category):
    """返回 (chunk_size, overlap)。未知/None → 旧默认 (600, 80)，保持存量兼容。"""
    return CONTENT_CATEGORY_CHUNK.get(category, _DEFAULT_CHUNK)


def classify_doc_type(file_name: str, file_type: str = "") -> str:
    """把资料归入三层结构。

    - raw   原始层：教材 / 讲义 / 真题原卷（保持原貌，不加工）
    - note  加工层：自己的笔记 / 摘要 / 错题整理（按章节挂接）
    - index 索引层：思维导图 / 考点清单（便于快速检索复盘）
    """
    n = file_name or ""
    if any(k in n for k in _INDEX_KW):
        return "index"
    if any(k in n for k in _NOTE_KW):
        return "note"
    if any(k in n for k in _RAW_KW):
        return "raw"
    if (file_type or "").lower() in _IMAGE_TYPES:
        return "raw"
    return "raw"


def detect_doc_meta(db: Session, doc) -> dict:
    """为文档补齐 doc_type / structure_level / ocr_used，返回判定结果。

    在文档解析完成后调用，让"这份资料属于哪一层、是否扫描件"可被前端筛选。
    """
    from services import structure_parser

    changed = False

    if not doc.doc_type:
        doc.doc_type = classify_doc_type(doc.file_name, doc.file_type)
        changed = True

    content = doc.content or ""
    ocr_like = (doc.file_type or "").lower() in _IMAGE_TYPES or "页(OCR)" in content

    if not doc.structure_level and content:
        parsed = structure_parser.parse_structure(content, doc.subject)
        doc.structure_level = "ocr" if ocr_like else parsed["level"]
        changed = True

    if ocr_like and not doc.ocr_used:
        doc.ocr_used = True
        changed = True

    if not getattr(doc, "content_category", None):
        doc.content_category = classify_content_category(doc.file_name, content)
        changed = True

    if changed:
        db.add(doc)
    return {
        "doc_type": doc.doc_type,
        "structure_level": doc.structure_level,
        "ocr_used": bool(doc.ocr_used),
    }


def ingest_document(db: Session, doc, *, replace: bool = True) -> int:
    """对已有 Document 记录重新分块入库。"""
    if not doc or not doc.content:
        return 0
    subject = doc.subject or classify_subject(
        doc.file_name, doc.content, path=getattr(doc, "file_path", "") or "")
    if not doc.subject:
        doc.subject = subject
    category = getattr(doc, "content_category", None) or classify_content_category(
        doc.file_name, doc.content
    )
    return ingest_text(
        db, doc.id, doc.file_name, doc.content, subject=subject,
        replace=replace, content_category=category,
    )


# --------------------------------------------------------------------------- #
# 文档治理（学习文库 / 文档知识库）：预清洗 · Markdown 快照 · 导出 · 归档 · 按科目归档
#
# 用户诉求（逐条落地）：
#   1. 水印：识别结果里混入「东坡哥微信/haodongpo」「第N页(OCR)」「QQ群/淘宝店」等。
#      → 复用 services/extraction_noise 的规则做**导入时预清洗**（与存量清洗脚本同源）。
#   2. 格式统一：pdf/doc/docx/txt 落库时统一生成 Markdown 快照
#      （knowledge_base/_md/{doc_id}.md），源文件归入 knowledge_base/_archive/（默认归档而非删除）。
#   3. 可转格式：详情里能导出 md / txt；pdf 依赖缺失则降级并**明确提示**，不静默失败。
#   5. 按科目归档：根目录文件按「文件名关键词 + 文档已有 subject」推断科目，
#      移动到 knowledge_base/{科目}/{文件名}；未匹配进 待分类/。
#
# 硬约束（这是本模块存在的原因）：
#   · 真库约 1561 篇 file_path 指向 knowledge_base，实测 315 篇文件已不在盘上（断链）。
#     所以「按科目归档」必须是「**先移动成功 → 再写回 DB file_path**」的原子流程，
#     失败要回滚文件移动；对断链记录**跳过并计入报告**，绝不因找不到文件整体抛异常。
#   · 任何真库写入前先 :func:`ensure_write_backup`（PG 走 pg_dump 自定义格式，
#     SQLite 走 backup API，禁 cp/copy2）。备份失败即抛 ``WriteBackupBlocked``，
#     **不允许"警告后继续写"**。
# --------------------------------------------------------------------------- #

#: 知识库根目录（仓库根/knowledge_base）。可用环境变量覆盖，便于测试注入临时目录。
_KB_ROOT_ENV = "KAOYAN_KB_ROOT"
#: Markdown 快照目录名（相对 knowledge_base 根）。
MD_SNAPSHOT_DIRNAME = "_md"
#: 源文件归档目录名（相对 knowledge_base 根）。
ARCHIVE_DIRNAME = "_archive"
#: 软删（标记删除）源文件落到这里，保留可恢复性。
TRASH_DIRNAME = "_trash"
#: 未匹配任何科目的文件落的目录。
PENDING_SUBJECT = "待分类"
#: 根目录下不参与归档的保留文件名（仓库自带的说明/状态文件）。
RESERVED_ROOT_FILES = {"readme.md", "readme.txt", "readme", ".processed_files.json"}


class WriteBackupBlocked(RuntimeError):
    """写前备份不可用 → 真库写入必须中止。

    继承 ``RuntimeError``，与 :class:`services.delete_guard.PhysicalDeleteBlocked`
    同一约定：调用方即使只按 ``RuntimeError`` 兜底也不会漏接。
    """


def _backend_dir() -> str:
    """后端根目录（本文件位于 <backend>/services/）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_kb_root(kb_root: str | None = None) -> str:
    """解析知识库根目录：显式入参 > 环境变量 KAOYAN_KB_ROOT > 仓库同级 knowledge_base。"""
    if kb_root:
        return os.path.abspath(kb_root)
    env = (os.environ.get(_KB_ROOT_ENV) or "").strip()
    if env:
        return os.path.abspath(env)
    return os.path.abspath(os.path.join(_backend_dir(), os.pardir, "knowledge_base"))


def _safe_dirname(name: str) -> str:
    """把科目名清洗成可安全用作目录名的片段（挡掉路径分隔符等危险字符）。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", (name or "").strip())
    return cleaned.strip(" .") or PENDING_SUBJECT


def _normcase_abspath(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _is_under(path: str, root: str) -> bool:
    ap, rp = _normcase_abspath(path), _normcase_abspath(root)
    return ap == rp or ap.startswith(rp + os.sep)


def preclean_watermarks(text: str | None) -> tuple[str, int, int]:
    """导入/入库时预清洗行内水印。返回 (清洗后文本, 丢行数, 删片段行数)。

    规则与 :mod:`scripts.clean_document_watermarks` 完全同源（都在
    :mod:`services.extraction_noise`），避免"清过的又被重新导入弄脏"。
    """
    from services.extraction_noise import clean_document_text

    return clean_document_text(text)


def configured_subject_set(db: Session) -> set[str]:
    """当前 subject_config 字典里的科目名集合（科目唯一权威）。"""
    try:
        from models import SubjectConfig

        return {r[0] for r in db.query(SubjectConfig.subject).all() if r[0]}
    except Exception:  # noqa: BLE001 —— 字典表缺失不应让归档整体失败
        return set()


def infer_subject_for_doc(db: Session, file_name: str, doc=None) -> tuple[str, bool]:
    """推断文件应归入的科目。返回 ``(科目名, 是否为待分类)``。

    依据（按优先级）：
      1. 文件名关键词表（复用 kb_service.classify_subject_confidence，高置信才采信）；
      2. 文档已有 subject（DB 里已有的标注）；
      3. 都判不出 → ``待分类``。
    """
    subj, high = classify_subject_confidence(file_name or "", (doc.content if doc else "") or "")
    if high and subj:
        return subj, False
    if doc is not None and (getattr(doc, "subject", None) or "").strip():
        return str(doc.subject).strip(), False
    return PENDING_SUBJECT, True


def build_markdown_snapshot(doc, *, cleaned_content: str | None = None) -> str:
    """把一篇文档渲染成统一的 Markdown 快照文本（带 YAML front-matter 元信息）。"""
    body = cleaned_content
    if body is None:
        body, _d, _m = preclean_watermarks(doc.content or "")
    name = doc.file_name or f"document_{getattr(doc, 'id', '')}"
    stem = os.path.splitext(name)[0]
    lines = [
        "---",
        f"doc_id: {getattr(doc, 'id', '')}",
        f"file_name: {name}",
        f"file_type: {doc.file_type or ''}",
        f"subject: {doc.subject or ''}",
        f"file_path: {(doc.file_path or '').replace(chr(92), '/')}",
        "---",
        "",
        f"# {stem}",
        "",
        body,
        "",
    ]
    return "\n".join(lines)


def snapshot_path(doc_id, *, kb_root: str | None = None) -> str:
    """返回某文档 Markdown 快照的绝对路径。"""
    return os.path.join(resolve_kb_root(kb_root), MD_SNAPSHOT_DIRNAME, f"{doc_id}.md")


def write_markdown_snapshot(doc, *, kb_root: str | None = None) -> str:
    """生成/覆盖文档的 Markdown 快照到 ``knowledge_base/_md/{doc_id}.md``，返回路径。"""
    path = snapshot_path(doc.id, kb_root=kb_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    md = build_markdown_snapshot(doc)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    return path


def export_document(doc, fmt: str, *, kb_root: str | None = None) -> dict:
    """导出文档统一快照。

    Returns:
        ``{"data": bytes, "filename": str, "media_type": str, "degraded": bool,
        "note": str}``。``fmt=pdf`` 依赖缺失时返回 ``degraded=True`` 并把
        ``data`` 降级为 Markdown 快照，调用方据此在 UI 明确提示（不静默失败）。
    """
    fmt = (fmt or "md").lower().strip()
    stem = os.path.splitext(doc.file_name or f"document_{doc.id}")[0] or f"document_{doc.id}"
    cleaned, _d, _m = preclean_watermarks(doc.content or "")
    md_text = build_markdown_snapshot(doc, cleaned_content=cleaned)

    if fmt == "txt":
        return {
            "data": cleaned.encode("utf-8-sig"),
            "filename": f"{stem}.txt",
            "media_type": "text/plain",
            "degraded": False,
            "note": "",
        }

    if fmt == "pdf":
        pdf_bytes = _render_pdf(cleaned, stem)
        if pdf_bytes is not None:
            return {
                "data": pdf_bytes,
                "filename": f"{stem}.pdf",
                "media_type": "application/pdf",
                "degraded": False,
                "note": "",
            }
        # 降级：明确告知，不静默失败
        return {
            "data": md_text.encode("utf-8-sig"),
            "filename": f"{stem}.md",
            "media_type": "text/markdown",
            "degraded": True,
            "note": "PDF 渲染依赖不可用，已降级为 Markdown 快照（内容一致）",
        }

    # 默认 md
    return {
        "data": md_text.encode("utf-8-sig"),
        "filename": f"{stem}.md",
        "media_type": "text/markdown",
        "degraded": False,
        "note": "",
    }


def _render_pdf(text: str, title: str) -> bytes | None:
    """用 reportlab 生成中文 PDF；依赖/字体不可用时返回 None（交由调用方降级）。"""
    try:
        from io import BytesIO

        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except Exception:  # noqa: BLE001
        return None

    try:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            font_name = "STSong-Light"
        except Exception:  # noqa: BLE001
            font_name = "Helvetica"

        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        width, height = A4
        x, top = 18 * mm, height - 20 * mm
        bottom = 18 * mm
        line_h = 6.5 * mm
        chars_per_line = max(20, int((width - 36 * mm) / 5.2))

        ctx = c.beginText(x, top)
        ctx.setFont(font_name, 10.5)
        y = top

        def _new_page():
            nonlocal ctx, y
            c.drawText(ctx)
            c.showPage()
            ctx = c.beginText(x, top)
            ctx.setFont(font_name, 10.5)
            y = top

        for raw_line in (text or "").split("\n"):
            line = raw_line.rstrip()
            # 依字符宽度硬折行（中文字符等宽近似），保证不溢出页宽
            pieces = [line[i:i + chars_per_line] for i in range(0, len(line), chars_per_line)] or [""]
            for piece in pieces:
                ctx.textLine(piece)
                y -= line_h
                if y < bottom:
                    _new_page()
        c.drawText(ctx)
        c.save()
        return buf.getvalue()
    except Exception:  # noqa: BLE001 —— 任何渲染异常都降级，不冒泡打断导出
        return None


def archive_source_file(doc, *, kb_root: str | None = None) -> dict:
    """把文档源文件移动到 ``knowledge_base/_archive/``（默认归档而非删除）。

    返回 ``{"archived": bool, "new_path": str|None, "reason": str}``。
    文件不存在/未登记路径 → ``archived=False`` 且给出原因（调用方据此计数，
    **绝不抛异常**，否则存量 315 篇断链记录会把整批归档一起带崩）。
    """
    raw = (getattr(doc, "file_path", None) or "").strip()
    if not raw:
        return {"archived": False, "new_path": None, "reason": "未登记原文路径"}
    if not os.path.isabs(raw):
        return {"archived": False, "new_path": None, "reason": "原文在外部知识库，本地无文件"}
    src = os.path.abspath(raw)
    if not os.path.isfile(src):
        return {"archived": False, "new_path": None, "reason": "原文文件已不在磁盘（断链）"}
    root = resolve_kb_root(kb_root)
    archive_dir = os.path.join(root, ARCHIVE_DIRNAME)
    if _is_under(src, archive_dir):
        return {"archived": False, "new_path": src, "reason": "已在归档目录"}
    stem, ext = os.path.splitext(os.path.basename(src))
    dest = os.path.join(archive_dir, f"{stem}_{doc.id}{ext}")
    try:
        os.makedirs(archive_dir, exist_ok=True)
        if os.path.exists(dest):
            dest = os.path.join(archive_dir, f"{stem}_{doc.id}_{int(os.path.getmtime(src))}{ext}")
        os.replace(src, dest)
    except OSError as e:
        return {"archived": False, "new_path": None, "reason": f"移动失败：{e}"}
    return {"archived": True, "new_path": dest, "reason": ""}


def soft_delete_source_file(doc, *, kb_root: str | None = None) -> dict:
    """软删（标记删除）源文件：移动到 ``knowledge_base/_trash/``，DB 记录保留。

    与归档同一口径：文件不存在/断链 → 返回原因而不抛异常。
    """
    raw = (getattr(doc, "file_path", None) or "").strip()
    if not raw or not os.path.isabs(raw):
        return {"archived": False, "new_path": None, "reason": "无可移动的本地原文"}
    src = os.path.abspath(raw)
    if not os.path.isfile(src):
        return {"archived": False, "new_path": None, "reason": "原文文件已不在磁盘（断链）"}
    root = resolve_kb_root(kb_root)
    trash_dir = os.path.join(root, TRASH_DIRNAME)
    if _is_under(src, trash_dir):
        return {"archived": False, "new_path": src, "reason": "已在回收目录"}
    stem, ext = os.path.splitext(os.path.basename(src))
    dest = os.path.join(trash_dir, f"{stem}_{doc.id}{ext}")
    try:
        os.makedirs(trash_dir, exist_ok=True)
        if os.path.exists(dest):
            dest = os.path.join(trash_dir, f"{stem}_{doc.id}_{int(os.path.getmtime(src))}{ext}")
        os.replace(src, dest)
    except OSError as e:
        return {"archived": False, "new_path": None, "reason": f"移动失败：{e}"}
    return {"archived": True, "new_path": dest, "reason": ""}


def ensure_write_backup() -> str | None:
    """真库写入**之前**必须有一次可回滚备份；备份做不成就别让写。

    V3.1 起改为「失败即抛」。旧实现 ``print(...) + return None`` 静默放行，
    于是 PostgreSQL 后端下（备份层只会 SQLite、必然抛 FileNotFoundError）批量导入
    **全程无备份裸写**——误删/误覆盖后再无退路，等于没有防护。

    Returns:
        备份文件路径；测试沙箱库返回 ``None``（刻意跳过：不在 ``data/backups``
        堆 dump，也不触发生产备份清理）。

    Raises:
        WriteBackupBlocked: 备份失败或被环境阻断（缺 ``pg_dump`` / PG 未启动 /
            源库缺失或为空 / 产物未通过完整性校验）。消息含原因与下一步动作。
    """
    from services.backup_service import create_backup, is_test_database

    if is_test_database():
        return None
    try:
        return create_backup()
    except Exception as e:  # noqa: BLE001 —— 统一成调用方必须接住的闸门异常
        raise WriteBackupBlocked(
            f"写前备份失败，写入已中止（不可回滚的写一律挡在门外）：{e}"
        ) from e


def scan_root_and_archive(
    db: Session,
    *,
    kb_root: str | None = None,
    dry_run: bool = False,
) -> dict:
    """扫描 knowledge_base **根目录**文件 → 按科目归档 → 同步 DB file_path。

    原子性（本任务硬骨头）：
      · 先 ``os.replace`` 移动文件成功，**再**写回 ``doc.file_path`` 并 commit；
      · DB 写失败则把文件移动回原位（best-effort）并计入 ``errors``；
      · 对断链文档（file_path 指向已不存在的文件）**只统计不处理**，绝不抛异常。

    Returns:
        ``{moved, skipped, broken, unclassified, errors, moved_items,
        skipped_items, broken_items, kb_root, dry_run}``。
    """
    root = resolve_kb_root(kb_root)
    report: dict = {
        "moved": 0,
        "skipped": 0,
        "broken": 0,
        "unclassified": 0,
        "errors": 0,
        "moved_items": [],
        "skipped_items": [],
        "broken_items": [],
        "kb_root": root,
        "dry_run": bool(dry_run),
    }
    if not os.path.isdir(root):
        report["error"] = f"知识库根目录不存在：{root}"
        return report

    # 文档索引：绝对路径 → Document（用于移动后写回 file_path）
    docs = db.query(Document).filter(Document.file_path.isnot(None)).all()
    by_abspath: dict[str, object] = {}
    for d in docs:
        fp = (d.file_path or "").strip()
        if fp and os.path.isabs(fp):
            by_abspath[_normcase_abspath(fp)] = d

    # ---- 1) 根目录文件 → 科目目录 ----
    try:
        entries = sorted(os.listdir(root))
    except OSError as e:
        report["error"] = f"无法读取知识库根目录：{e}"
        return report

    for name in entries:
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        if name.startswith(".") or name.lower() in RESERVED_ROOT_FILES:
            continue

        doc = by_abspath.get(_normcase_abspath(full))
        subject, unclassified = infer_subject_for_doc(db, name, doc)
        subject_dir = _safe_dirname(subject)
        dest_dir = os.path.join(root, subject_dir)
        dest = os.path.join(dest_dir, name)

        if _normcase_abspath(dest) == _normcase_abspath(full):
            report["skipped"] += 1
            report["skipped_items"].append({"file": name, "reason": "已在目标科目目录"})
            continue
        if os.path.exists(dest):
            report["skipped"] += 1
            report["skipped_items"].append({"file": name, "reason": "目标已存在，跳过避免覆盖"})
            continue

        entry = {"file": name, "subject": subject, "doc_id": getattr(doc, "id", None), "dest": dest}

        if dry_run:
            report["moved"] += 1
            if unclassified:
                report["unclassified"] += 1
            report["moved_items"].append({**entry, "dry_run": True})
            continue

        # 先移动文件
        try:
            os.makedirs(dest_dir, exist_ok=True)
            os.replace(full, dest)
        except OSError as e:
            report["errors"] += 1
            report["skipped_items"].append({"file": name, "reason": f"移动失败：{e}"})
            continue

        # 移动成功 → 再写回 DB（失败则回滚文件位置）
        if doc is not None:
            try:
                doc.file_path = dest
                db.commit()
            except Exception as e:  # noqa: BLE001
                db.rollback()
                try:
                    os.replace(dest, full)
                except OSError:
                    pass
                report["errors"] += 1
                report["skipped_items"].append(
                    {"file": name, "reason": f"DB 写回失败已回滚文件：{e}"}
                )
                continue

        report["moved"] += 1
        if unclassified:
            report["unclassified"] += 1
        report["moved_items"].append(entry)

    # ---- 2) 断链统计：file_path 落在知识库内但文件已不存在 ----
    for d in docs:
        fp = (d.file_path or "").strip()
        if not fp or not os.path.isabs(fp):
            continue
        ap = os.path.abspath(fp)
        if not _is_under(ap, root):
            continue
        if not os.path.isfile(ap):
            report["broken"] += 1
            if len(report["broken_items"]) < 50:
                report["broken_items"].append({"doc_id": d.id, "file_path": ap})
    return report


def scan_root_preview(db: Session, *, kb_root: str | None = None) -> dict:
    """只读预览：不落盘、不写库，返回与 :func:`scan_root_and_archive` 同结构的统计。"""
    return scan_root_and_archive(db, kb_root=kb_root, dry_run=True)

