"""
V3.0 AI 智能路由网关
自动判断问题类型，选择最优AI引擎：
- 简单题 → 本地模型（Ollama/LoRA），快速响应，不花钱
- 复杂题 → 在线大模型API（豆包/DeepSeek/通义），高质量回答
- 资料题 → RAG检索 + 在线API，基于本地知识库精准回答
- 敏感内容 → 拦截或转人工
"""
import re
import logging
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.orm import Session
from utils.http_client import get_async_client

logger = logging.getLogger(__name__)

#: 科目识别特征词（用于分科选模型）。
#  只放**高区分度**的词：像"电路"这种在数电模电里都出现的词不放进单一科目，
#  否则会把模电题误判成数电。
_SUBJECT_HINTS: Dict[str, List[str]] = {
    "数字电子技术": [
        "逻辑", "卡诺图", "真值表", "触发器", "计数器", "寄存器", "编码器", "译码器",
        "时序", "组合逻辑", "与非门", "或非门", "异或", "ttl", "cmos", "三态门",
        "最小项", "数制", "二进制", "d/a", "a/d", "555", "施密特", "存储器",
        "可编程", "竞争冒险", "移位寄存器", "全加器", "数据选择器", "数电",
    ],
    "模拟电子技术": [
        "放大电路", "共射", "共集", "共基", "运放", "运算放大", "反馈", "差分放大",
        "静态工作点", "偏置", "整流", "滤波", "稳压", "功率放大", "功放", "振荡",
        "pn结", "二极管", "三极管", "场效应", "失真", "射极跟随", "模电",
        "有源滤波", "直流电源", "跨导", "波特图",
    ],
    "数学": [
        "极限", "导数", "微分", "积分", "矩阵", "行列式", "特征值", "概率",
        "级数", "洛必达", "中值定理", "偏导", "二重积分", "微分方程", "线性代数",
        "高数", "数二", "泰勒", "拐点", "渐近线",
    ],
    "英语": [
        "单词", "词汇", "长难句", "完形", "阅读", "翻译", "作文", "语法",
        "短语", "句式", "英译汉", "作文模板", "背单词", "从句",
    ],
    "政治": [
        "马原", "毛中特", "史纲", "思修", "辩证法", "唯物", "剩余价值", "生产力",
        "生产关系", "社会主义", "近代史", "时政", "肖秀荣", "政治", "矛盾论",
    ],
    "电路": [
        "基尔霍夫", "节点电压", "网孔电流", "戴维南", "诺顿", "叠加定理", "一阶电路",
        "二阶电路", "正弦稳态", "相量", "三相电路", "二端口", "耦合电感", "复频域",
        "谐振", "功率因数", "动态电路", "换路定则", "时间常数",
    ],
    "信号与系统": [
        "信号与系统", "卷积", "傅里叶", "拉氏变换", "z变换", "抽样定理", "采样定理",
        "冲激响应", "阶跃响应", "系统函数", "零极点", "频谱", "因果", "稳定判据",
        "离散时间", "连续时间", "状态方程", "帕塞瓦尔",
    ],
    "通信原理": [
        "通信原理", "调制", "解调", "误码率", "信噪比", "香农", "信道容量",
        "基带传输", "带通传输", "ask", "fsk", "psk", "qam", "曼彻斯特",
        "差错控制", "汉明码", "循环码", "卷积码", "白噪声", "匹配滤波",
        "同步", "眼图", "码间串扰", "pcm", "增量调制",
    ],
    "光学与工程光学": [
        "工程光学", "几何光学", "成像", "光焦度", "近轴", "光阑", "像差", "色差",
        "干涉", "衍射", "偏振", "光栅", "双缝", "牛顿环", "迈克尔逊", "马吕斯",
        "布儒斯特", "菲涅耳", "波片", "全反射",
    ],
    "普通物理": [
        "普通物理", "大学物理", "质点", "刚体", "转动惯量", "动量守恒", "机械能",
        "简谐振动", "波动方程", "热力学", "熵", "理想气体", "静电场", "高斯定理",
        "稳恒磁场", "安培环路", "电磁感应", "麦克斯韦", "狭义相对论", "光电效应",
    ],
    "计算机学科专业基础408": [
        "408", "数据结构", "线性表", "链表", "二叉树", "哈夫曼", "图的遍历",
        "最短路径", "拓扑排序", "快速排序", "堆排序", "哈希", "b树", "红黑树",
        "计算机组成", "指令系统", "流水线", "cache", "虚拟内存", "操作系统",
        "进程", "死锁", "页面置换", "文件系统", "计算机网络", "tcp", "ip协议",
        "路由算法", "滑动窗口", "osi",
    ],
    "电路分析": ["电路分析", "网孔分析", "节点分析"],
    "光学": ["杨氏双缝", "薄膜干涉"],
}


class AIRouter:
    """AI智能路由网关。"""

    def __init__(self, db: Session):
        self.db = db
        self.local_available = False
        self.local_check_time = None
        self.local_check_cache = 300  # 5分钟缓存

    @staticmethod
    def detect_subject(question: str) -> Optional[str]:
        """从问题文本猜测科目，用于分科选模型。

        只认**明确的关键词**，猜不准就返回 None（不硬猜）——
        猜错科目会导致选错模型，比不选更糟。
        """
        try:
            from services import taxonomy

            q = (question or "").lower()
            # 按"关键词 → 科目"打分，取最高
            hits: Dict[str, int] = {}
            for subj, kws in _SUBJECT_HINTS.items():
                score = sum(1 for kw in kws if kw in q)
                if score:
                    hits[subj] = score
            if not hits:
                return None
            subj, score = max(hits.items(), key=lambda kv: kv[1])
            # 至少命中 1 个特征词才采纳；多科同分则不猜
            if score < 1:
                return None
            if list(hits.values()).count(score) > 1:
                return None
            return taxonomy.normalize_subject(subj)
        except Exception:
            return None

    def classify_question(self, question: str) -> Dict[str, Any]:
        """
        分类问题类型，决定路由策略。

        返回：
        {
            "type": "simple" | "complex" | "knowledge" | "sensitive",
            "confidence": float,
            "reason": str,
            "need_rag": bool,
            "preferred_engine": "local" | "api" | "rag",
            "subject": str | None,        # 识别出的科目，用于分科选模型
        }
        """
        q = question.strip().lower()

        # 1. 敏感内容检测
        sensitive_patterns = [
            r'政治', r'领导人', r'敏感', r'违法', r'犯罪',
            r'色情', r'暴力', r'恐怖', r'毒品', r'武器',
        ]
        for pattern in sensitive_patterns:
            if re.search(pattern, q):
                return {
                    "type": "sensitive",
                    "confidence": 0.9,
                    "reason": "检测到敏感内容",
                    "need_rag": False,
                    "preferred_engine": "api",  # 敏感内容走API，由API安全策略处理
                }

        # 2. 资料/知识库相关问题检测
        knowledge_keywords = [
            '文档', '资料', '课件', '讲义', '真题', '题目', '知识点',
            '这本书', '这篇', '这个文档', '根据资料', '参考文档',
            '数电', '模电', '高数', '英语', '政治', '专业课',
            '第一章', '第二章', '第.*章', 'section', 'chapter',
        ]
        knowledge_score = 0
        for kw in knowledge_keywords:
            if re.search(kw, q):
                knowledge_score += 1

        # 问题中包含具体知识点或科目
        subject_keywords = ['数字电子', '模拟电子', '高等数学', '线性代数', '概率论', '英语', '政治', '专业课']
        for kw in subject_keywords:
            if kw in question:
                knowledge_score += 2

        if knowledge_score >= 2:
            return {
                "type": "knowledge",
                "confidence": min(0.95, 0.5 + knowledge_score * 0.1),
                "reason": f"检测到知识库相关问题（得分{knowledge_score}）",
                "need_rag": True,
                "preferred_engine": "rag",
            }

        # 3. 复杂问题检测（需要推理、计算、多步分析）
        complex_patterns = [
            r'为什么', r'如何证明', r'推导', r'证明', r'分析',
            r'比较', r'区别', r'优缺点', r'原理', r'机制',
            r'计算', r'求解', r'解方程', r'积分', r'微分',
            r'设计', r'实现', r'方案', r'架构',
            r'请详细', r'请解释', r'深入', r'全面',
        ]
        complex_score = 0
        for pattern in complex_patterns:
            if re.search(pattern, q):
                complex_score += 1

        # 问题长度也是一个指标
        if len(question) > 50:
            complex_score += 1
        if len(question) > 100:
            complex_score += 1

        if complex_score >= 2:
            return {
                "type": "complex",
                "confidence": min(0.9, 0.4 + complex_score * 0.1),
                "reason": f"检测到复杂问题（得分{complex_score}）",
                "need_rag": False,
                "preferred_engine": "api",
            }

        # 4. 简单问题（定义、概念、简单问答）
        return {
            "type": "simple",
            "confidence": 0.7,
            "reason": "简单问题，可由本地模型快速回答",
            "need_rag": False,
            "preferred_engine": "local",
        }

    async def check_local_available(self) -> bool:
        """检查本地模型是否可用（带缓存）。"""
        import time
        now = time.time()
        if self.local_check_time and (now - self.local_check_time) < self.local_check_cache:
            return self.local_available

        try:
            client = get_async_client()
            resp = await client.get("http://127.0.0.1:11434/api/tags", timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                self.local_available = len(models) > 0
                self.local_check_time = now
                return self.local_available
        except Exception as e:
            logger.debug(f"本地模型不可用: {e}")

        self.local_available = False
        self.local_check_time = now
        return False

    async def route(
        self,
        question: str,
        context: Optional[List[Dict]] = None,
        force_engine: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        智能路由：根据问题类型选择最优AI引擎。

        参数：
        - question: 用户问题
        - context: 对话上下文
        - force_engine: 强制使用指定引擎（local/api/rag）

        返回：
        {
            "engine": "local" | "api" | "rag",
            "classification": {...},
            "fallback_chain": ["api", "local"],
            "need_rag": bool,
            "reason": str,
        }
        """
        # 1. 分类问题 + 识别科目（科目决定选哪个本地模型）
        classification = self.classify_question(question)
        subject = self.detect_subject(question)
        classification["subject"] = subject

        # 2. 强制引擎
        if force_engine:
            return {
                "engine": force_engine,
                "classification": classification,
                "subject": subject,
                "fallback_chain": ["api", "local"] if force_engine != "api" else ["api"],
                "need_rag": force_engine == "rag",
                "reason": f"强制使用{force_engine}引擎",
            }

        # 3. 敏感内容处理
        if classification["type"] == "sensitive":
            return {
                "engine": "api",
                "classification": classification,
                "subject": subject,
                "fallback_chain": ["api"],
                "need_rag": False,
                "reason": "敏感内容，使用在线API（由API安全策略处理）",
            }

        # 4. 知识库相关问题 → RAG + API
        if classification["type"] == "knowledge":
            return {
                "engine": "rag",
                "classification": classification,
                "subject": subject,
                "fallback_chain": ["api", "local"],
                "need_rag": True,
                "reason": "知识库相关问题，使用RAG检索+在线API",
            }

        # 5. 复杂问题 → 在线API
        if classification["type"] == "complex":
            return {
                "engine": "api",
                "classification": classification,
                "subject": subject,
                "fallback_chain": ["api", "local"],
                "need_rag": False,
                "reason": "复杂问题，使用在线大模型API",
            }

        # 6. 简单问题 → 本地模型（如果可用），否则API
        local_available = await self.check_local_available()
        if local_available:
            return {
                "engine": "local",
                "classification": classification,
                "subject": subject,
                "fallback_chain": ["api"],
                "need_rag": False,
                "reason": "简单问题，使用本地模型快速响应（省钱+低延迟）",
            }
        else:
            return {
                "engine": "api",
                "classification": classification,
                "subject": subject,
                "fallback_chain": ["api"],
                "need_rag": False,
                "reason": "简单问题，但本地模型不可用，使用在线API",
            }

    async def chat_with_router(
        self,
        question: str,
        ai_service,
        context: Optional[List[Dict]] = None,
        force_engine: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        使用智能路由进行对话（带失败回退）。

        返回：
        {
            "content": str,
            "engine_used": str,
            "classification": dict,
            "fallback_used": bool,
            "latency_ms": int,
        }
        """
        import time
        start_time = time.time()

        # 1. 路由决策
        route_result = await self.route(question, context, force_engine)
        engine = route_result["engine"]
        fallback_chain = route_result["fallback_chain"]

        # 2. 尝试主引擎，失败则回退
        last_error = None
        for current_engine in [engine] + [e for e in fallback_chain if e != engine]:
            try:
                logger.info(f"AI路由: 使用{current_engine}引擎回答问题: {question[:50]}...")

                if current_engine == "local":
                    # 本地模型（Ollama）—— 模型按科目自动选
                    # 修复 AI-P0-1：此处误用了未定义变量 route（NameError 被外层 except 吞掉，
                    # 导致本地引擎 100% 静默降级到云端）。路由结果在上方赋值为 route_result。
                    result = await self._chat_local(question, context, subject=route_result.get("subject"))
                elif current_engine == "rag":
                    # RAG + 在线API
                    result = await self._chat_rag(question, ai_service, context)
                else:
                    # 在线API
                    result = await self._chat_api(question, ai_service, context)

                latency_ms = int((time.time() - start_time) * 1000)
                return {
                    "content": result.get("content", ""),
                    "engine_used": current_engine,
                    "classification": route_result["classification"],
                    "fallback_used": current_engine != engine,
                    "latency_ms": latency_ms,
                    "reason": route_result["reason"],
                    "reasoning_steps": result.get("reasoning_steps", []),
                    "retrieved_chunks": result.get("retrieved_chunks", []),
                    "cache_hit": result.get("cache_hit", False),
                    "from_cache": result.get("from_cache", False),
                    "reranker_backend": result.get("reranker_backend", "none"),
                }

            except Exception as e:
                last_error = e
                logger.warning(f"{current_engine}引擎失败，尝试回退: {e}")
                continue

        # 3. 所有引擎都失败
        latency_ms = int((time.time() - start_time) * 1000)
        return {
            "content": f"抱歉，所有AI引擎都暂时不可用。错误: {last_error}",
            "engine_used": "none",
            "classification": route_result["classification"],
            "fallback_used": True,
            "latency_ms": latency_ms,
            "error": str(last_error),
        }

    async def _pick_local_model(self, subject: Optional[str] = None) -> str:
        """按科目选本地模型（走 model_registry，不再硬编码）。

        关键点：**优先用"已安装且跑得动"的模型**，哪怕它不是该科的理想模型。
        只装了 qwen3:4b 时，数电题也应该用它本地作答，
        而不是因为"理想模型 deepseek-r1:7b 没装"就退回云端。
        """
        import os

        default = os.getenv("OLLAMA_MODEL", "qwen3:8b")
        try:
            from services import model_registry as mr

            # 已安装模型清单
            installed: set[str] = set()
            try:
                client = get_async_client()
                host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
                resp = await client.get(f"{host}/api/tags", timeout=5.0)
                if resp.status_code == 200:
                    installed = {m.get("name", "") for m in resp.json().get("models", [])}
                    installed |= {n.split(":")[0] for n in list(installed)}
            except Exception:
                pass

            if not installed:
                return default

            task = mr.route_for_subject(subject) if subject else "general"
            best = mr.pick_best_available(task, subject=subject, installed=installed)
            if best and best.get("ollama_name"):
                logger.info(
                    f"本地模型选型: {best['name']}（{best.get('relevance')}，科目={subject or '未识别'}）"
                )
                return best["ollama_name"]
        except Exception as e:
            logger.debug(f"本地模型选型失败，用默认值: {e}")
        return default

    async def _chat_local(
        self,
        question: str,
        context: Optional[List[Dict]] = None,
        subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        """使用本地Ollama模型对话（模型按科目自动选）。

        ⚠️ 两个实测要点（2026-10）：
        1. **不要传 `think:false`** —— 对 qwen3 系列会把推理过程倒进 content。
           不加该参数才是干净答案。这里也不做清洗兜底。
        2. **超时要给够** —— Qwen3 是思考模型，实测单问 60-320 秒，
           原来的 120 秒经常不够。
        """
        import os

        from services.llm_output import extract_answer

        messages = []
        if context:
            messages.extend(context[-5:])  # 只保留最近5条上下文
        messages.append({"role": "user", "content": question})

        model = await self._pick_local_model(subject)
        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        client = get_async_client()
        resp = await client.post(
            f"{host}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": "10m",
            },
            timeout=360.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            answer = extract_answer(data.get("message", {}) or {})
            if not answer:
                raise Exception(
                    f"本地模型 {model} 只返回了思考过程，未给出正文（可换更小的模型或走云端）"
                )
            return {"content": answer, "model": model}
        raise Exception(f"本地模型 {model} 返回错误: {resp.status_code}")

    async def _chat_api(self, question: str, ai_service, context: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """使用在线API对话。"""
        messages = []
        if context:
            messages.extend(context[-5:])
        messages.append({"role": "user", "content": question})

        result = await ai_service.chat(messages)
        return {"content": result.get("content", "")}

    # ------------------------------------------------------------------ #
    # V11 模块4：Agentic 轻量状态机辅助（自研，接线三个冻结模块）
    # ------------------------------------------------------------------ #
    _CIRCUIT_SUBJECT_HINTS = ("电路", "模拟电子")
    _CIRCUIT_KEYWORDS = (
        "基尔霍夫", "kcl", "kvl", "节点电压", "网孔电流", "戴维南", "诺顿",
        "叠加定理", "一阶电路", "二阶电路", "正弦稳态", "相量", "三相电路",
        "二端口", "耦合电感", "复频域", "谐振", "功率因数", "动态电路",
        "换路", "时间常数", "静态工作点", "分压偏置", "共射", "共集", "共基",
        "运算放大", "整流", "滤波电路",
    )
    _CALC_KEYWORDS = (
        "计算", "求解", "试求", "试计算", "求导", "积分", "微分", "极限",
        "解方程", "等于", "多少", "值为", "推导", "证明",
    )
    _CONCEPT_KEYWORDS = (
        "什么是", "什么叫", "定义", "概念", "区别", "联系", "原理", "为什么",
        "简述", "解释", "名词解释",
    )

    @classmethod
    def _classify_solve_type(
        cls, question: str, classification: Dict[str, Any], subject: Optional[str]
    ) -> str:
        """在现有 classify_question / detect_subject 之上识别解题路径：

        ``circuit`` 电路题 / ``calc`` 计算题 / ``concept`` 概念题 / ``reference`` 资料题。
        任何异常都回退到 ``reference``（RAG 引用优先）。
        """
        try:
            q = (question or "").lower()
            if subject and any(s in subject for s in cls._CIRCUIT_SUBJECT_HINTS):
                return "circuit"
            if any(kw in q for kw in cls._CIRCUIT_KEYWORDS):
                return "circuit"
            if classification.get("type") == "knowledge":
                return "reference"
            has_digit = bool(re.search(r"\d", question or ""))
            if has_digit and any(kw in q for kw in cls._CALC_KEYWORDS):
                return "calc"
            if any(kw in q for kw in cls._CONCEPT_KEYWORDS):
                return "concept"
            return "reference"
        except Exception:
            return "reference"

    @staticmethod
    def _solve_system_prompt(solve_type: str) -> str:
        """按题型给分步求解的 system prompt 模板。"""
        templates = {
            "circuit": (
                "你是电路分析助教。按电路规范分步求解：\n"
                "1) 判断电路类型（直流/正弦稳态/动态/放大），选用 KVL/KCL/节点电压法/"
                "网孔法/戴维南-诺顿等效/叠加定理/相量法/复频域拉氏变换/静态工作点分析；\n"
                "2) 写清元件参数与参考方向，列方程；\n"
                "3) 每步给出中间结果，最后给数值答案并标注单位（Ω/A/V/W 等）；\n"
                "4) 缺电路图或参数时明确指出缺失条件，不要编造。"
            ),
            "calc": (
                "你是理工科计算助教。分步计算：\n"
                "1) 写出所用公式与代入数值；\n"
                "2) 每步保留单位并做单位换算；\n"
                "3) 最后给数值结论，做量纲/数量级合理性检查；\n"
                "4) 条件不足时说明，不要硬编数字。"
            ),
            "concept": (
                "你是课程助教。回答概念题：\n"
                "1) 先给严格定义；\n"
                "2) 再举一个简明例子；\n"
                "3) 最后指出常见易错点/易混淆概念；\n"
                "4) 条理清晰，不要堆砌。"
            ),
            "reference": (
                "你是答疑助教。优先依据参考资料回答：\n"
                "1) 引用资料处标注 [资料i]；\n"
                "2) 资料不足时明确说'参考资料未直接覆盖'，通识补充需标注；\n"
                "3) 不要编造资料中没有的事实。"
            ),
        }
        return templates.get(solve_type, templates["reference"])

    @staticmethod
    def _dedupe_key(item: Dict[str, Any]) -> str:
        did = item.get("doc_id")
        cid = item.get("chunk_id")
        if did is not None or cid is not None:
            return f"doc={did}|chunk={cid}"
        return (item.get("content") or item.get("text") or "")[:160]

    @classmethod
    def _rrf_fuse(
        cls, ranked_lists: List[List[Dict[str, Any]]], k: int = 60
    ) -> List[Dict[str, Any]]:
        """RRF 融合多路检索：score = Σ 1/(k+rank)，按融合分排序并去重。"""
        scores: Dict[str, float] = {}
        items: Dict[str, Dict[str, Any]] = {}
        for lst in ranked_lists:
            for rank, item in enumerate(lst or []):
                if not isinstance(item, dict):
                    continue
                key = cls._dedupe_key(item)
                items.setdefault(key, item)
                scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        ordered = sorted(items.keys(), key=lambda x: -scores.get(x, 0.0))
        out: List[Dict[str, Any]] = []
        for key in ordered:
            it = dict(items[key])
            it["_rrf_score"] = round(scores.get(key, 0.0), 6)
            out.append(it)
        return out

    @classmethod
    def _merge_dedup(
        cls, base: List[Dict[str, Any]], extra: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        seen = {cls._dedupe_key(b) for b in base}
        merged = list(base)
        for it in extra or []:
            key = cls._dedupe_key(it)
            if key not in seen:
                seen.add(key)
                merged.append(it)
        return merged

    @staticmethod
    def _self_check_ok(content: str, solve_type: str) -> bool:
        """答案合理性自检：非空、有结论、长度阈值；计算题粗查数字。"""
        if not content:
            return False
        text = content.strip()
        if len(text) < 20:
            return False
        if not any(k in text for k in (
            "因此", "所以", "答案", "结论", "故", "综上", "=", "＝", "为", "：",
        )):
            return False
        if solve_type == "calc" and not re.search(r"\d", text):
            return False
        return True

    @staticmethod
    def _extract_image_path(context: Optional[List[Dict[str, Any]]]) -> Optional[str]:
        """从上下文消息里找图片路径。当前 ChatRequest 无 image 字段，恒为 None。"""
        if not context:
            return None
        for m in context:
            c = (m or {}).get("content") or ""
            mimg = re.search(r"([A-Za-z]:[\\/][^\s]+\.(?:png|jpg|jpeg|webp))", c)
            if mimg:
                return mimg.group(1)
        return None

    async def _retrieve_one(
        self, query: str, ai_service, subject: Optional[str]
    ) -> List[Dict[str, Any]]:
        """单路检索：异步 hybrid 优先，失败回退同步 FTS，再失败返回 []。"""
        if not query or not str(query).strip():
            return []
        try:
            hits = await ai_service.search_knowledge_base_hybrid(query, limit=6, subject=subject)
            return hits or []
        except Exception as e:
            logger.debug("[RAG] hybrid 检索失败，回退同步: %s", e)
        try:
            return ai_service.search_knowledge_base(query, limit=6, subject=subject) or []
        except Exception as e:
            logger.warning("[RAG] 同步检索也失败，按无上下文继续: %s", e)
            return []

    async def _chat_rag(
        self,
        question: str,
        ai_service,
        context: Optional[List[Dict]] = None,
        **_legacy: Any,
    ) -> Dict[str, Any]:
        """V11 模块4：Agentic 轻量状态机（自研，不装 RAGFlow）。

        接线三个冻结模块（只 import 调用，不改其实现）：
          - ``services.answer_cache``        缓存优先 / 生成后写回（失败静默）；
          - ``services.retrieval_enhance``  rewrite_query → 多路检索 → HyDE → RRF → rerank；
          - ``services.circuit_analysis``   电路图辅助（当前 chat 入口无图片通道，就绪不触发）。

        返回保持 ``content`` / ``retrieved_chunks`` 兼容，新增 ``agentic_steps``(List[str])
        与 ``cache_hit``(bool)。所有新环节失败静默降级，主链绝不中断。
        兼容旧调用方透传的 ``pipeline``/``semantic_cache``/``max_retrieval_rounds``（已忽略）。
        """
        agentic_steps: List[str] = []
        reasoning_steps: List[Dict[str, Any]] = []

        def _step(name: str, **detail: Any) -> None:
            agentic_steps.append(name)
            reasoning_steps.append({"step": name, **detail})

        # -------------------------------------------------------------- #
        # 步骤1：题目分类（失败→默认资料路径）
        # -------------------------------------------------------------- #
        try:
            classification = self.classify_question(question)
        except Exception as e:
            logger.warning("[RAG] classify_question 异常，默认资料路径: %s", e)
            classification = {
                "type": "knowledge", "confidence": 0.5, "reason": "分类异常",
                "need_rag": True, "preferred_engine": "rag",
            }
        try:
            subject = self.detect_subject(question)
        except Exception as e:
            logger.warning("[RAG] detect_subject 异常: %s", e)
            subject = None
        solve_type = self._classify_solve_type(question, classification, subject)
        _step(f"分类:{solve_type}", subject=subject, qtype=classification.get("type"))

        # -------------------------------------------------------------- #
        # 步骤2：缓存优先（answer_cache；读失败按未命中，绝不抛出）
        # -------------------------------------------------------------- #
        try:
            from services import answer_cache as _ac
            hit = _ac.get_cached(question, subject=subject)
        except Exception as e:
            logger.debug("[RAG] answer_cache.get_cached 失败，按未命中: %s", e)
            hit = None
        if hit and hit.get("answer"):
            _step("cache_hit", source=hit.get("source"))
            return {
                "content": hit.get("answer", ""),
                "retrieved_chunks": [],
                "agentic_steps": agentic_steps,
                "reasoning_steps": reasoning_steps,
                "cache_hit": True,
                "from_cache": True,
                "source": "cache",
            }
        _step("cache_miss")

        # -------------------------------------------------------------- #
        # 步骤3：检索增强链 rewrite → 多路检索 → HyDE → RRF → rerank
        # -------------------------------------------------------------- #
        try:
            from services import retrieval_enhance as _re
        except Exception as e:
            logger.warning("[RAG] retrieval_enhance 不可用，走裸检索: %s", e)
            _re = None  # type: ignore

        # -------------------------------------------------------------- #
        # Self-RAG 按复杂度裁剪：简单概念题("什么是/定义/简述/解释")只做
        # "单次检索 + bge rerank"，跳过多查询改写与 HyDE——这两步在 CPU 上各要
        # 一次 LLM 往返，是 60s 504 的主因。即使命中电路/计算关键词，只要问句是
        # 概念定义式(如"什么是 KVL")也按简单题裁剪。
        # -------------------------------------------------------------- #
        is_simple = (solve_type == "concept") or any(
            kw in (question or "").lower() for kw in self._CONCEPT_KEYWORDS
        )
        if is_simple:
            queries = [question]
            _step("裁剪:简单概念题(单次检索,跳过改写/HyDE)")
        elif _re is not None:
            try:
                queries = await _re.rewrite_query(question, subject=subject)
            except Exception as e:
                logger.warning("[RAG] rewrite_query 异常，用原查询: %s", e)
                queries = [question]
        else:
            queries = [question]
        queries = [q for q in (queries or [question]) if q and str(q).strip()] or [question]
        _step(f"改写:{len(queries)}个查询", queries=queries)

        ranked_lists: List[List[Dict[str, Any]]] = []
        for q in queries:
            hits = await self._retrieve_one(q, ai_service, subject)
            if hits:
                ranked_lists.append(hits)

        # HyDE 可选第二轮（失败返回 None，跳过）；简单题直接跳过
        hyde_used = False
        if _re is not None and not is_simple:
            try:
                hyde_doc = await _re.hyde_document(question, subject=subject)
            except Exception as e:
                logger.debug("[RAG] hyde_document 异常: %s", e)
                hyde_doc = None
            if hyde_doc:
                hyde_hits = await self._retrieve_one(hyde_doc, ai_service, subject)
                if hyde_hits:
                    ranked_lists.append(hyde_hits)
                    hyde_used = True
                    _step("hyde:并入1轮检索")

        candidates = self._rrf_fuse(ranked_lists) if ranked_lists else []
        before_rerank = len(candidates)
        if _re is not None and candidates:
            try:
                final_chunks = await _re.rerank(candidates, question, top_k=5)
            except Exception as e:
                logger.warning("[RAG] rerank 异常，原序截断: %s", e)
                final_chunks = candidates[:5]
        else:
            final_chunks = candidates[:5]
        _step(f"rerank:{before_rerank}→{len(final_chunks)}", hyde_used=hyde_used)

        # -------------------------------------------------------------- #
        # 步骤4：retrieval_gate observe 打点（不改门控行为，异常跳过）
        # -------------------------------------------------------------- #
        try:
            from services import retrieval_gate as _gate
            gate = _gate.evaluate_gate(
                final_chunks, question,
                is_complex=_gate.is_complex_query(question),
            )
            logger.info(
                "[retrieval_gate] query=%r decision=%s would_abstain=%s metrics=%s",
                question[:30], gate.get("decision"), gate.get("would_abstain"),
                gate.get("metrics"),
            )
            _step(f"gate:{gate.get('decision')}",
                  would_abstain=gate.get("would_abstain"))
        except Exception as e:
            logger.warning("[RAG] retrieval_gate 判定失败，跳过打点: %s", e)

        # -------------------------------------------------------------- #
        # 步骤5：电路题——图片通道核查
        #  ChatRequest.messages 仅含 role/content(str)，无 image 字段 →
        #  电路图辅助已就绪但当前 chat 入口无图片通道，不强行接假数据。
        # -------------------------------------------------------------- #
        if solve_type == "circuit":
            image_path = self._extract_image_path(context)
            if image_path:
                try:
                    from services import circuit_analysis as _ca
                    circ = await _ca.analyze_circuit_image(image_path, question)
                    _step(f"电路图辅助:{circ.get('status')}",
                          circuit_type=circ.get("circuit_type"))
                    if circ.get("description"):
                        final_chunks = final_chunks + [{
                            "source": "电路识图",
                            "title": circ.get("circuit_type") or "电路图",
                            "content": circ["description"],
                        }]
                except Exception as e:
                    logger.warning("[RAG] 电路图辅助异常: %s", e)
                    _step("电路图辅助:异常已降级")
            else:
                _step("电路图辅助:已就绪,当前chat入口无图片通道(ChatRequest无image字段),未触发")

        # -------------------------------------------------------------- #
        # 步骤6：分步求解（按题型 system prompt + RAG 上下文）
        # -------------------------------------------------------------- #
        async def _generate(chunks: List[Dict[str, Any]]) -> str:
            ctx_text = "\n\n".join(
                f"[资料{i+1}｜{c.get('source', 'chunk')}｜{c.get('title', '')}]\n"
                f"{c.get('content') or c.get('text', '')}"
                for i, c in enumerate(chunks)
            )
            user_prompt = (
                f"{ctx_text or '（未检索到资料）'}\n\n"
                f"用户问题：{question}\n\n"
                "要求：按系统提示的解题规范作答，引用资料处标注 [资料i]，不要编造。"
            )
            messages = [{"role": "system", "content": self._solve_system_prompt(solve_type)}]
            if context:
                messages.extend(context[-3:])
            messages.append({"role": "user", "content": user_prompt})
            try:
                res = await ai_service.chat(messages)
                return (res or {}).get("content", "") or ""
            except Exception as e:
                logger.warning("[RAG] ai_service.chat 生成失败: %s", e)
                return ""

        content = await _generate(final_chunks)

        # -------------------------------------------------------------- #
        # 步骤7：自检验证——不过则补充检索恰好一次后重新生成
        # -------------------------------------------------------------- #
        if self._self_check_ok(content, solve_type):
            _step("自检通过")
        else:
            _step("自检未通过:补充检索1次")
            sup_query = queries[0] if len(queries) > 1 else question
            sup_hits = await self._retrieve_one(sup_query, ai_service, subject)
            if sup_hits:
                final_chunks = self._merge_dedup(final_chunks, sup_hits)
            content2 = await _generate(final_chunks)
            if self._self_check_ok(content2, solve_type):
                content = content2
                _step("自检通过(补充检索后)")
            else:
                if len(content2) > len(content):
                    content = content2
                _step("自检仍未通过:返回当前最佳")

        # -------------------------------------------------------------- #
        # 步骤8：写缓存（失败静默）
        # -------------------------------------------------------------- #
        if content:
            try:
                from services import answer_cache as _ac
                _ac.set_cached(question, content, subject=subject)
            except Exception as e:
                logger.debug("[RAG] answer_cache.set_cached 失败: %s", e)

        return {
            "content": content,
            "retrieved_chunks": final_chunks,
            "agentic_steps": agentic_steps,
            "reasoning_steps": reasoning_steps,
            "cache_hit": False,
            "from_cache": False,
        }


# 单例
_router_instance = None

def get_ai_router(db: Session) -> AIRouter:
    """获取AI路由网关单例。"""
    global _router_instance
    if _router_instance is None:
        _router_instance = AIRouter(db)
    return _router_instance
