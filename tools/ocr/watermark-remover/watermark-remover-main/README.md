# 文档水印去除工具

一个Python脚本，用于去除PDF和Word文档中的水印。

## 功能特点

- **PDF水印去除**
  - 覆盖法：用白色矩形覆盖水印区域
  - 文本删除法：删除文本型水印
  - 图像处理法：处理图片型水印
  - 自动检测：智能识别并去除水印
  - 预览功能：查看水印位置

- **Word水印去除**
  - 页眉页脚水印
  - 文本框水印
  - 形状水印
  - 图片/艺术字水印
  - 文档设置水印

- **批量处理**：支持批量处理整个目录
- **交互模式**：友好的命令行交互界面

## 安装依赖

```bash
pip install -r requirements.txt
```

依赖包：
- PyMuPDF (fitz) - PDF处理
- python-docx - Word文档处理
- Pillow - 图像处理

## 使用方法

### 1. 交互模式（推荐新手使用）

```bash
python main.py
```

按提示选择操作即可。

### 2. 处理单个文件

**PDF文件：**
```bash
# 自动处理
python main.py -i input.pdf

# 指定输出文件
python main.py -i input.pdf -o output.pdf

# 指定处理方法
python main.py -i input.pdf -m cover
```

**Word文件：**
```bash
python main.py -i input.docx
python main.py -i input.docx -o output.docx
```

### 3. 批量处理

```bash
# 处理所有文件
python main.py -b ./input_dir ./output_dir

# 仅处理PDF
python main.py -b ./input_dir ./output_dir -t pdf

# 仅处理Word
python main.py -b ./input_dir ./output_dir -t word
```

## PDF处理方法说明

| 方法 | 说明 | 适用场景 |
|------|------|----------|
| `auto` | 自动检测并去除 | 通用，推荐 |
| `cover` | 覆盖法 | 固定位置的水印 |
| `text` | 文本删除法 | 文字型水印 |
| `image` | 图像处理法 | 图片型水印 |
| `preview` | 预览水印区域 | 查看水印位置 |

### 覆盖法详解

覆盖法会检测以下常见水印位置：
- 左上角
- 右上角
- 页面中心
- 左下角
- 右下角

你也可以自定义覆盖区域：
```python
from pdf_watermark_remover import PDFWatermarkRemover

remover = PDFWatermarkRemover("input.pdf")
# 自定义水印区域 [(x0, y0, x1, y1), ...]
watermark_rects = [
    (100, 100, 300, 200),  # 自定义区域1
    (400, 500, 600, 600),  # 自定义区域2
]
remover.remove_by_cover("output.pdf", watermark_rects)
```

## 文件结构

```
watermark_remover/
├── main.py                      # 主程序入口
├── pdf_watermark_remover.py     # PDF水印去除模块
├── word_watermark_remover.py    # Word水印去除模块
├── requirements.txt             # 依赖包列表
└── README.md                    # 使用说明
```

## 使用示例

### 示例1：快速去除单个PDF水印
```bash
python main.py -i "C:\Users\Documents\带水印.pdf" -o "C:\Users\Documents\无水印.pdf"
```

### 示例2：预览PDF水印位置
```bash
python main.py -i input.pdf -m preview
```
会生成一个预览图，标记出可能的水印区域。

### 示例3：批量处理Word文档
```bash
python main.py -b "./待处理文档" "./已处理文档" -t word
```

### 示例4：使用自定义关键词去除Word水印
```bash
python word_watermark_remover.py input.docx output.docx "机密,内部资料,样稿"
```

## 注意事项

1. **备份原文件**：处理前建议备份原始文件
2. **效果因文件而异**：不同文档的水印实现方式不同，效果可能有差异
3. **复杂水印**：某些复杂水印可能需要手动调整参数
4. **Word格式**：仅支持 .docx 格式，不支持 .doc 格式

## 常见问题

**Q: 处理后的PDF文件变大了？**
A: 这是正常现象，特别是使用图像处理法时。可以使用PDF压缩工具进一步处理。

**Q: 水印没有完全去除？**
A: 可以尝试不同的处理方法，或多次处理。某些水印可能需要手动指定位置。

**Q: 支持哪些类型的水印？**
A: 支持大多数常见水印类型，包括：
- 文字水印（"保密"、"样稿"等）
- 图片水印
- 半透明水印
- 页眉页脚水印

**Q: 如何确定水印位置？**
A: 使用预览功能：`python main.py -i input.pdf -m preview`

## 更新日志

### v1.0 (2024)
- 初始版本发布
- 支持PDF和Word水印去除
- 支持批量处理
- 支持多种处理方法

## 许可证

MIT License
