# 55-DeepTutor 借鉴与考研平台升级方案

> 参考：HKUDS/DeepTutor（17.8k+ stars）及同类 AI 教育开源项目深度调研。
> 目标：把顶级 AI 教育项目的设计哲学，映射为考研平台可落地的升级项。

---

## 一、核心结论：DeepTutor 最值得借鉴的三个设计哲学

调研发现，DeepTutor 的价值不在"多 Agent 角色"本身，而在三个经过验证的设计哲学：

1. **闭环个性化**：辅导中暴露的薄弱点 → 直接决定下一步生成什么题 → 学生做题表现 → 反过来更新后续讲解。论文报告个性化辅导质量 +10.8%，通用智能体推理 +29.4%。
2. **三层可审计记忆（DPM / Trace Forest）**：任何一条 AI 结论都可以一路追溯到原始证据（L1 原始轨迹 → L2 摘要事实 → L3 综合画像），用户可直接编辑纠正。
3. **结构分离验证**：生成器与验证器不共享推理链（防自我确认错误），计算题用沙箱代码独立验证。

这三个点与考研平台现有「错题本 + 艾宾浩斯 + RAG 答疑 + 模考」结合，优先级最高。

---

## 二、可落地升级项（按优先级）

### P0（高优先级，直接补短板）

#### 1. 三层可审计记忆（借鉴 DeepTutor DPM/Trace Forest）
- **借鉴**：L1 原始轨迹（只追加 jsonl）→ L2 摘要事实（带 L1 引用）→ L3 跨场景综合结论；每条 AI 判断可溯源。
- **落地**：
  - 新增 `memory_traces`（用户每次答疑/做题/看资料的原始事件）
  - `memory_facts`（LLM 定期蒸馏出的摘要，带 trace_id 外键）
  - `memory_synthesis`（综合画像）
  - 前端加「记忆图谱」面板：展示"AI 认为你薄弱的知识点" ← 依据哪些题/对话
- **价值**：解决考研用户最核心的信任问题——「AI 为什么说我这块薄弱」可追溯可纠错。

#### 2. 智能批改增强：结构分离验证器（借鉴 DeepTutor Critic/Validator + MLA 简真）
- **借鉴**：生成器与验证器**不共享推理链**；计算题跑沙箱代码；多维度评分卡（事实准确性/逻辑连贯性/格式规范性/数据完整性）。
- **落地**：
  - 主观题/简答题批改时，用第二个独立 prompt（甚至不同模型）验证第一遍评分
  - 数学计算题：提取表达式用 Python 沙箱（受限 `exec`）验证
  - 评分维度结构化返回前端展示（当前 P0-2 已做基础版 grade-subjective，可在此之上增强）

#### 3. 闭环个性化推题（借鉴 DeepTutor 闭环 + Mastery Path 精熟门控）
- **借鉴**：辅导中暴露的薄弱点直接决定下一步生成什么题；知识点不达标无法进入下一阶段。
- **落地**：
  - 错题本/答疑中识别薄弱知识点 → 触发「针对该知识点的专项练习」
  - 从题库按知识点+难度过滤或 LLM 生成变式题
  - 连续答对 N 题才标记掌握 → 更新学习路径

### P1（中优先级，增强体验）

#### 4. 知识图谱化学习路径（借鉴 DeepTutor SKG 双索引 + adaptive-knowledge-graph）
- **借鉴**：知识图谱 G（前置/关联关系）+ 向量索引 B，RRF 融合检索；检索前用图中邻近概念扩展查询。
- **落地**：
  - 现有知识点树已有 parent_id 层级 → 补充 `prerequisite_for`（前置）和 `related_to`（关联）关系边
  - RAG 检索时先用图谱扩展查询词
  - 生成「学习路径推荐」（下一步该学哪个知识点）

#### 5. 间隔复习升级：艾宾浩斯固定间隔 → SM-2/FSRS
- **借鉴**：SM-2 质量分 0-5 动态调间隔；FSRS 基于 DSR 模型的个性化调度，有 `py-fsrs`/`ts-fsrs` 现成库。
- **落地**：后端接入 `py-fsrs`，把现有固定节奏升级为按用户回忆质量动态调间隔；前端保留现有节奏编辑器作为手动覆盖（刚完成的艾宾浩斯自定义节奏正好兼容）。

#### 6. 多 Agent 答疑协作（借鉴 DeepTutor consult_subagent + MLA 12 Agent 流水线）
- **借鉴**：复杂问题拆解 → 不同 Agent 分工（路径规划/资源检索/质量审核/补救讲解），LangGraph 状态机编排。
- **落地**（轻量版）：考研答疑拆为——
  1. RAG 检索 Agent（查知识库）
  2. 解题 Agent（分步讲解）
  3. 审核 Agent（检查引用和正确性）
  4. 补救 Agent（用户仍不懂 → 换模态重讲：文字→图示→例题）
- **成本可控**：同模型多 prompt 角色，而非多模型。

### P2（低成本，见效快）

#### 7. 学习轨迹可视化（借鉴 DeepTutor Memory Graph + MLA 雷达图）
- 仪表盘加「学习热力图」（每天做题/时长）+「知识星系图」（D3 力导向，节点大小=学习时长，颜色=掌握度）+「遗忘曲线可视化」。

#### 8. 学情周报/月报（借鉴 OpenMentor 学情报告 + 智学领航预警中心）
- 每周日自动生成结构化学情报告（本周做题量、正确率趋势、薄弱知识点 TOP3、下周建议），SSE 流式生成，存档可回看下载。

#### 9. 苏格拉底式对话模式（借鉴 Claw-STU 模态轮换 + Pathwise）
- AI 答疑加「引导模式」开关：默认不直接给答案，先反问拆解问题；用户连续答错才降级为直接讲解；记录哪种模式对用户有效。

#### 10. 安全与合规（借鉴 OpenMentor + Claw-STU）
- 关键词黑名单、每日消息上限、紧急熔断、谄媚语剥离（避免 AI 无脑鼓励）。

---

## 三、参考项目清单

| 项目 | 链接 | 值得深挖点 |
|---|---|---|
| HKUDS/DeepTutor | https://github.com/HKUDS/DeepTutor | 三层记忆源码、Mastery Path、Quiz 生成、RAG 多引擎 |
| HKUDS 组织 | https://github.com/HKUDS | LightRAG 等 RAG 顶级项目 |
| THU-MAIC/OpenMAIC | https://github.com/THU-MAIC/OpenMAIC | LangGraph 多智能体课堂编排、两阶段课程生成 |
| buBailai/OpenMentor | https://github.com/buBailai/OpenMentor | 轻量化部署、审计大屏、学情报告 |
| sbkriz/Claw-STU | https://github.com/sbkriz/Claw-STU | ZPD 校准、模态轮换、夜间固化、主动调度 |
| Faye-bit/MLA_CnSoftBei | https://github.com/Faye-bit/MLA_CnSoftBei | 12 Agent LangGraph 编排、三级质量审查、艾宾浩斯 |
| Glory0707/zhixuelinghang | https://github.com/Glory0707/zhixuelinghang | 三端闭环、预警中心、审计日志 |
| open-spaced-repetition | https://github.com/open-spaced-repetition | FSRS 算法全家桶 |
| MysterionRise/adaptive-knowledge-graph | https://github.com/MysterionRise/adaptive-knowledge-graph | KG 增强 RAG + BKT 自适应测验 |

---

## 四、与当前 P0 修复的关系

| 当前 P0 修复 | DeepTutor 借鉴增强 |
|---|---|
| P0-2 主观题批改（grade-subjective） | → 升级为「结构分离验证器」：二次独立验证 + 沙箱验算 + 多维评分卡 |
| P0-3 模考考后报告 | → 衔接「闭环个性化推题」：报告薄弱点直接触发专项练习 |
| 艾宾浩斯自定义节奏（已完成） | → 升级为 SM-2/FSRS 动态间隔（保留手动覆盖） |
| RAG 答疑（已有） | → 升级为「多 Agent 答疑协作 + 三层可审计记忆」 |

---

## 五、建议实施顺序

1. **先做 P2-7 学习热力图 + P2-8 学情周报**（成本低、见效快，增强用户感知）
2. **再升级 P0-2 批改为结构分离验证**（直接提升已做的 AI 批改质量）
3. **落地 P0-1 三层可审计记忆**（表结构 + 答疑埋点 + 记忆图谱面板）
4. **落地 P0-3 闭环个性化推题**（薄弱点 → 专项练习）
5. **间隔复习升级 FSRS**（在艾宾浩斯自定义节奏基础上）
6. **多 Agent 答疑**（轻量版）与**知识图谱关系边**（P1-4/P1-6）