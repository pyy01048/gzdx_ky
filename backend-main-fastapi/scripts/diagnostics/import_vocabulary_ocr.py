"""
《词汇闪过》PDF OCR 单词导入脚本
- 使用 PyMuPDF 提取 PDF 页面为图片
- 使用 RapidOCR 识别文字
- 解析单词并分类导入到数据库
- 支持断点续传
"""
import os
import re
import json
import time
import sys
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import Word, WordDeck

# PDF 目录
PDF_DIR = r"D:\文档\考研\27考研《词汇闪过》"

# 进度文件
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), "data", "ocr_import_progress.json")

# 词库映射
DECK_MAPPING = {
    "完型词汇": "完型词汇",
    "阅读词汇": "阅读词汇",
    "翻译词汇": "翻译词汇",
    "写作词汇": "写作词汇",
    "固定搭配": "固定搭配",
    "数词僻义": "熟词僻义",
    "熟词僻义": "熟词僻义",
    "高频词精缩本": "核心词精缩本",
    "高频词替换": "高频词替换",
}


def load_progress():
    """加载处理进度"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"files": {}, "total_words": 0}


def save_progress(progress):
    """保存处理进度"""
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def get_or_create_deck(db, deck_name):
    """获取或创建词库"""
    deck = db.query(WordDeck).filter(WordDeck.name == deck_name).first()
    if not deck:
        deck = WordDeck(name=deck_name, description=f"《词汇闪过》{deck_name}")
        db.add(deck)
        db.commit()
        db.refresh(deck)
    return deck


def parse_words_from_text(text):
    """从OCR文本中解析单词"""
    words = []
    lines = text.split("\n")

    # 单词模式：英文单词 + 可选音标 + 词性 + 中文释义
    # 例如：abandon /əˈbændən/ v. 放弃，抛弃
    word_pattern = re.compile(
        r'^([a-zA-Z][a-zA-Z\-\s]{1,30})\s*'  # 单词
        r'(/[^/]+/)?\s*'  # 音标（可选）
        r'([a-z]+\.)?\s*'  # 词性（可选）
        r'(.+)$'  # 释义
    )

    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # 尝试匹配单词行
        match = word_pattern.match(line)
        if match:
            word = match.group(1).strip()
            phonetic = match.group(2) or ""
            pos = match.group(3) or ""
            meaning = match.group(4).strip() if match.group(4) else ""

            # 验证单词是否合理
            if len(word) >= 2 and len(word) <= 30 and meaning:
                words.append({
                    "word": word.lower(),
                    "phonetic": phonetic.strip("/ "),
                    "pos": pos.strip("."),
                    "meaning": meaning,
                })

    return words


def ocr_pdf_pages(pdf_path, start_page=0, max_pages=None):
    """OCR识别PDF页面，返回提取的文本"""
    import pymupdf
    from rapidocr_onnxruntime import RapidOCR

    ocr = RapidOCR()
    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)

    if max_pages:
        end_page = min(start_page + max_pages, total_pages)
    else:
        end_page = total_pages

    all_text = ""
    for page_num in range(start_page, end_page):
        try:
            page = doc[page_num]
            # 渲染页面为图片（提高分辨率以提升OCR准确率）
            mat = pymupdf.Matrix(2, 2)  # 2倍缩放
            pix = page.get_pixmap(matrix=mat)

            # 转换为numpy数组
            import numpy as np
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)

            # OCR识别
            result, _ = ocr(img)
            if result:
                page_text = "\n".join([line[1] for line in result])
                all_text += page_text + "\n"

            if (page_num - start_page + 1) % 5 == 0:
                print(f"  已处理 {page_num - start_page + 1}/{end_page - start_page} 页")

        except Exception as e:
            print(f"  第{page_num}页处理失败: {e}")
            continue

    doc.close()
    return all_text


def import_words_to_db(db, words, deck_id):
    """导入单词到数据库，跳过已存在的单词"""
    imported = 0
    skipped = 0

    for w in words:
        # 检查单词是否已存在
        existing = db.query(Word).filter(
            Word.word == w["word"],
            Word.deck_id == deck_id
        ).first()

        if existing:
            skipped += 1
            continue

        # 创建新单词
        new_word = Word(
            word=w["word"],
            phonetic=w.get("phonetic", ""),
            pos=w.get("pos", ""),
            meaning=w["meaning"],
            deck_id=deck_id,
            status="new",
            ease_factor=2.5,
            interval=0,
            reps=0,
            lapses=0,
            due_date=datetime.now().date(),
        )
        db.add(new_word)
        imported += 1

        # 每100个提交一次
        if imported % 100 == 0:
            db.commit()
            print(f"  已导入 {imported} 个单词")

    db.commit()
    return imported, skipped


def process_pdf(pdf_path, deck_name, db, progress):
    """处理单个PDF文件"""
    filename = os.path.basename(pdf_path)
    print(f"\n{'='*60}")
    print(f"处理文件: {filename}")
    print(f"词库: {deck_name}")
    print(f"{'='*60}")

    # 检查是否已处理完成
    if progress["files"].get(filename, {}).get("completed"):
        print(f"  文件已处理完成，跳过")
        return 0

    # 获取或创建词库
    deck = get_or_create_deck(db, deck_name)

    # 获取已处理页数
    processed_pages = progress["files"].get(filename, {}).get("pages", 0)

    try:
        # OCR识别（每次处理10页，分批处理）
        batch_size = 10
        import pymupdf
        doc = pymupdf.open(pdf_path)
        total_pages = len(doc)
        doc.close()

        total_imported = 0
        total_skipped = 0

        for start_page in range(processed_pages, total_pages, batch_size):
            print(f"\n处理第 {start_page+1}-{min(start_page+batch_size, total_pages)} 页...")

            # OCR识别
            text = ocr_pdf_pages(pdf_path, start_page, batch_size)

            # 解析单词
            words = parse_words_from_text(text)
            print(f"  解析到 {len(words)} 个单词")

            # 导入数据库
            if words:
                imported, skipped = import_words_to_db(db, words, deck.id)
                total_imported += imported
                total_skipped += skipped
                print(f"  导入 {imported} 个，跳过 {skipped} 个")

            # 更新进度
            progress["files"][filename] = {
                "pages": min(start_page + batch_size, total_pages),
                "total_pages": total_pages,
                "imported": total_imported,
                "skipped": total_skipped,
                "completed": start_page + batch_size >= total_pages,
            }
            progress["total_words"] += total_imported
            save_progress(progress)

        print(f"\n文件处理完成: 共导入 {total_imported} 个单词，跳过 {total_skipped} 个")
        return total_imported

    except Exception as e:
        print(f"文件处理失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def main():
    """主函数"""
    print("="*60)
    print("《词汇闪过》PDF OCR 单词导入工具")
    print("="*60)

    # 加载进度
    progress = load_progress()
    print(f"已导入单词总数: {progress.get('total_words', 0)}")

    # 获取数据库会话
    db = SessionLocal()

    try:
        # 遍历PDF目录
        pdf_files = [f for f in os.listdir(PDF_DIR) if f.endswith(".pdf")]
        print(f"\n找到 {len(pdf_files)} 个PDF文件")

        total_imported = 0

        for filename in sorted(pdf_files):
            pdf_path = os.path.join(PDF_DIR, filename)

            # 匹配词库
            deck_name = None
            for keyword, deck in DECK_MAPPING.items():
                if keyword in filename:
                    deck_name = deck
                    break

            if not deck_name:
                print(f"\n跳过文件（未匹配词库）: {filename}")
                continue

            # 处理PDF
            imported = process_pdf(pdf_path, deck_name, db, progress)
            total_imported += imported

        print(f"\n{'='*60}")
        print(f"全部处理完成!")
        print(f"本次导入: {total_imported} 个单词")
        print(f"累计导入: {progress.get('total_words', 0)} 个单词")
        print(f"{'='*60}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
