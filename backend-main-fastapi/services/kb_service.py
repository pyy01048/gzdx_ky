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

import re
import collections

from sqlalchemy.orm import Session

from models import KnowledgeChunk
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
        "张宇", "660", "1000题", "基础30讲", "数一", "数二", "数三",
        "概统", "概率统计", "微积分", "同济", "复习全书",
    ],
    "政治": [
        "政治", "马原", "毛中特", "史纲", "思修", "肖秀荣", "徐涛", "腿姐",
        "辩证法", "唯物史观", "近代史纲要",
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
    name: str, content_text: str = '', *, allow_weak: bool = False
) -> tuple[str, bool]:
    """返回 `(科目, 是否高置信)`。

    高置信 = 有明确的科目强信号，或正文关键词足够集中。
    低置信 = 仅靠"真题/试卷"这类形态词兜底，或压根没法判。

    批量重标存量数据时应该**只用高置信结果** ——
    否则会把原本合理的标注改成臆测值，越改越乱。
    """
    from services import taxonomy

    n = (name or "").lower()
    content = content_text or ""
    if is_parse_failure(content):
        content = ""      # 报错信息不参与判定

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


def classify_subject(name: str, content_text: str = '') -> str:
    """根据文件名 + 正文推断学科分类（对外主入口）。

    先按文件名打分（强信号优先），分数不足时用正文关键词补足。
    文档类型词（真题/讲义/答案…）不参与科目判定。
    """
    return classify_subject_confidence(name, content_text)[0]


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
            conn0 = db.connection().connection
            placeholders = ','.join('?' * len(old_ids))
            # 先清依赖表引用（向量表 / 错题-知识点关联），避免外键约束失败。
            # 依赖表按 sqlite_master 判定存在才删：knowledge_chunks_vec / _fts 不在 ORM
            # metadata 里，是检索侧 ensure_* 惰性建的；库还没建过它们时本就 0 行可清，
            # 若硬删会抛 "no such table" 把整个重新解析打断。
            _have = {r[0] for r in conn0.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
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

    conn = db.connection().connection
    # 若 FTS 尚未初始化则先全量同步一次（仅首次，避免重复）
    search_service.ensure_fts_table(conn)

    count = 0
    for idx, ch in enumerate(chunks):
        kc = KnowledgeChunk(
            document_id=doc_id,
            doc_name=doc_name,
            chunk_id=idx,
            subject=subject,
            text=ch,
        )
        db.add(kc)
        db.flush()  # 取得自增 id
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
    subject = doc.subject or classify_subject(doc.file_name, doc.content)
    if not doc.subject:
        doc.subject = subject
    category = getattr(doc, "content_category", None) or classify_content_category(
        doc.file_name, doc.content
    )
    return ingest_text(
        db, doc.id, doc.file_name, doc.content, subject=subject,
        replace=replace, content_category=category,
    )
