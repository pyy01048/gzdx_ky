# 智能入库管线落地报告（对照参考方案 × 项目实际）

- 生成时间：2026-10-12
- 代码：`backend-main-fastapi/services/smart_ingest.py`（新增）+ `scripts/smart_ingest.py`（CLI）
- 目标：大学教材 / 考研讲义 / 真题 / 课件 / 扫描件 PDF / 截图照片的高精度识别 → 分类 → 入库

---

## 一、核心判断：项目缺的不是模型，是「编排」

对照参考方案逐条核对项目现状后，结论是：

> 参考方案里的关键技术组件，**项目大部分已经有了**，但它们各自孤立、
> **没有一条管线把它们串起来**，导致入库时只走了最弱的 `DocumentParser` 纯文本抽取。

| 参考方案要求的组件 | 项目现状 | 位置 |
|---|---|---|
| 文字 OCR（PaddleOCR 主力 + 兜底） | ✅ 已有三层路由 | `services/ocr_router.py`（local-gpu / paddleocr / rapidocr / chineseocr-lite） |
| 版面检测分区 | ✅ 已有（按 blocks 坐标切题） | `services/ocr_layout.py` |
| 公式识别 → LaTeX | ✅ 已有（VLM + 编译校验） | `services/formula_service.py` |
| 电路图/原理图 VLM 解析 | ✅ 已有 | `services/circuit_analysis.py`（qwen2.5vl:7b） |
| 词法+语义混合检索 | ✅ 已有（FTS + 向量 + RRF） | `services/search_service.py` |
| 向量化（BGE） | ✅ 已有（BAAI/bge-small-zh-v1.5） | `services/embedding_service.py` |
| 学科分类 | ✅ 已有（规则+置信度） | `services/kb_service.classify_subject` |
| **图像预处理**（纠偏/去噪/去黑边） | ❌ **缺失** | — |
| **管线编排**（分流识别） | ❌ **缺失** | 本报告新增 |
| **结构化抽取**（教材/章节/知识点标签） | ❌ **缺失**（只存裸正文） | 本报告新增 |
| **入库前校验**（乱码比例/向量去重/白名单） | ❌ **缺失**（脏数据直接入库） | 本报告新增 |
| 重排序 Reranker | 🟡 部分（仅 AI 答疑链路有） | `services/retrieval_enhance.py` |

因此本轮的工作重点是**补齐编排层与校验层**，而不是重复造模型。

---

## 二、本轮已实现（可运行）

管线：
```
图像预处理 → 分流识别 → 文本清洗 → 结构化抽取 → 入库校验 → 入库
```

### 1. 图像预处理（新增，项目原缺失）
`preprocess_image()`：
- **去黑边**：Otsu 二值化 + 内容包围盒裁剪（扫描仪黑边）
- **去噪**：中值滤波
- **纠偏**：横向膨胀连行 → minAreaRect 估计倾角 → 旋转（限 ±20°，避免竖排文本转歪）
- **轻量放大**：短边 < 1000px 放大到 1600px（提升小字 OCR 命中率）

> ⚠️ 开发中发现并修复的真实 bug：`cv2.imread/imwrite` 在 Windows 上
> **无法读取含中文的路径**，而本项目知识库路径几乎全是中文 →
> 预处理此前被静默跳过。已改为 `imdecode/fromfile` + `imencode/tofile`。

### 2. 分流识别（编排）
- **图片**：预处理 → `ocr_router.recognize_file` 拿文字块 → 有公式迹象才调
  `formula_service`（避免无谓开销）→ 可选 VLM 图块描述
- **PDF**：优先文本层；`< 30 字`判定为扫描件 → **逐页渲染 200DPI → 走图片分流识别**
  （按页切片，避免大 PDF 内存溢出）
- **VLM 图块描述**：默认关闭（慢），`SMART_INGEST_VLM=1` 开启；
  prompt 使用参考方案的严格 JSON 模板 + `禁止编造 / 不确定填 null`

### 3. 文本清洗
去图片引用 `![alt](path)`（保留有信息的 alt 如 `CLK`）、零宽字符、控制字符、
纯噪声行、**页码**、**水印**（扫描全能王/CamScanner/仅供学习/盗版必究 等可配置）

### 4. 结构化抽取（对应参考方案的标签体系）
输出：`subject / major / book_name / author / edition / chapter / section / content_type`
- 教材名：`《》` 提取（文件名优先，其次正文首部）
- 章/节：`第X章`、`第X节` 正则
- 内容类型：考研真题 / 课后习题 / 例题 / 讲义课件 / 教材正文
- 学科 + 专业方向：复用 `kb_service` + 新增 3 级映射表 `MAJOR_DIRECTION`

实例（实测）：
```
输入： 《模拟电子技术基础》康华光 第五版 课后习题详解.pdf
输出： subject=模拟电子技术  major=电子信息（模拟电路方向）
      book_name=模拟电子技术基础  edition=第五版
      chapter=第3章 多级放大电路  content_type=课后习题
```

### 5. 入库前校验（脏数据拦截，项目原缺失）
- **长度**：正文 < 30 字 → 拒收
- **乱码比例**：替换符占比 > 10% → 拒收（实测能拦住 55.6% 乱码的样本）
- **中文占比**：< 2% 且无长英文 → 标 `need_review`（可能是纯公式/图表或识别失败）
- **向量去重**：BGE 向量余弦比对 `knowledge_chunks_vec`
  - ≥ 0.97 → 判重复拒收；0.90~0.97 → 标 `need_review`

> 实测去重有效：批量跑「专业课/834贵大真题」90 篇，
> 拦下 8 篇与库内已有文档相似度 **0.985~1.000** 的重复件
> （如「贵大2023年834真题」与「贵大2023年834真题(1)」）。

### 6. 并行与断点
- `--workers N` 多线程（每 worker 独立 DB session；SQLite 写入自动串行化）
- OCR 预扫结果落盘缓存（`_kb_ocr_cache.json`），重启不重扫
- OCR / 非 OCR 双通道分离：文本层文件秒级入库，扫描件走 OCR 通道

---

## 三、实测数据

| 项目 | 数值 |
|---|---|
| 知识库磁盘文档类文件 | 4101 |
| 其中**从未入库** | 3314 |
| 文本层文件（快速通道） | 2003 |
| 需 OCR 文件（OCR 通道） | 1303 |
| 并行实测速度（4 workers） | 90 篇 / <110s |

---

## 四、与参考方案的差异（未做 / 需算力）

| 参考方案建议 | 本项目选择 | 原因 |
|---|---|---|
| Pix2Tex 专用公式模型 | 复用已有 `formula_service`（VLM 通道） | 已有实现且带 LaTeX 编译校验，无需重复引入 |
| InternVL2-4B/8B 图块解析 | 用已有 `qwen2.5vl:7b` | 本地已装，避免再下载大模型 |
| 轻量 BERT 分类 + LLM 分类**双路投票** | 暂用规则分类 + 置信度 | 双路投票需先有训练集；待分类样本积累后再上 |
| BGE-M3 / BGE-Reranker | 现有 bge-small-zh + FTS/向量/RRF 混合 | 答疑链路已有 rerank；入库链路暂不需要 |
| FAISS / Milvus | 已有 sqlite-vec | 规模（2.8 万块）够用，免额外运维 |

**待补（下一步优先级）**
1. 教材**白名单**（书名+作者+章节）——需要先把知识库跑一遍统计出教材清单
2. 分类**双路投票** + 人工复核回流（需先积累标注样本）
3. 知识点标签自动抽取接知识地图（当前知识点靠 `document_analyzer` 单独抽取）
4. Reranker 下沉到入库检索链路（可选）

---

## 五、使用方式

```bash
cd D:\平台\backend-main-fastapi

# 单文件预演（不入库，看识别+分类+校验结果）
python scripts/smart_ingest.py --file "<路径>"

# 单文件入库
python scripts/smart_ingest.py --file "<路径>" --apply

# 批量：只处理有文本层的（快）
python scripts/smart_ingest.py --scan-dir "D:\平台\knowledge_base" --skip-ocr --skip-ingested --apply --workers 6

# 批量：只处理扫描件/图片（OCR 通道，慢）
python scripts/smart_ingest.py --scan-dir "D:\平台\knowledge_base" --only-ocr --skip-ingested --apply --workers 6

# 开启 VLM 图块描述（最慢，精度最高）
python scripts/smart_ingest.py --file "<路径>" --vlm --apply
```

保留旧链路 `scripts/ingest_kb_bulk.py`（快速批量）与 `services/kb_ingest.py`（单文件），
两者行为未改动。
