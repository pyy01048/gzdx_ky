# 刷题数据冷启动报告（2026-10-19 凌晨）

## 结果
- **quiz_questions：0 → 386 题**（可刷 386），指纹重复率 0.00%
- 按 subject：数学 211 / 模拟电子技术 111 / 电路 34 / 数字电子技术 30
- answer_source=source_extract、answer_confidence=0.85 → **题库确定性答案优先（find_bank_answer）即刻有数据可用**

## 质量门（全部通过）
- 结构完整性：题干/四选项/答案逐题自检
- 抽取率 ≥5%/≥5 题、答案错配率 ≤1%（原 SQLite 版阈值原样保留）
- 内容指纹去重（题干+选项全同不重入）；insert-only、单文档事务
- apply 前自动 JSONL 备份现存行

## 抽取来源（圣才配套题库 e-book 文本层）
- 文本层格式与抽取器原假设不同（标签内联/题号题干同行），脚本内 normalize_exam_text() 归一化 + SECTION_RE 词表补齐（分析计算题/计算分析题/解答题）后通过

## 宁缺勿滥决策
- **同济《高等数学》下册配套题库未导入**：文本层公式字符丢失（「若级数条件收敛，则___依次为幂级数的」），结构完整但语义残缺，导入会污染题库
- 已入库的 211 道数学题部分同样存在公式缺字（读题干可辨上下文的保留）；后续可按 `source_label` 一键 is_junk 过滤

## 复现
```
cd backend-main-fastapi
.venv/Scripts/python.exe scripts/import_exam_questions_pg.py            # dry-run
.venv/Scripts/python.exe scripts/import_exam_questions_pg.py --apply    # 入库
```

## 待办
- [ ] 386 题同步到服务器（随数据同步轮）
- [ ] 知识点挂接（kp 挂 quiz_questions，走 link_kp_chapters 同款唯一命中规则）
- [ ] 对标 gitgraduate 的 P0：原卷题号回填、真题地图（见 docs/quiz-benchmark-gitgraduate.md）
