#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF水印去除工具
支持多种去水印方式：
1. 内容流编辑法（推荐）- 直接编辑PDF内容流，精确移除水印标记
2. 覆盖法 - 用白色矩形覆盖水印区域
3. 文本删除法 - 删除特定文本水印
4. 图像处理法 - 像素级处理
"""

import fitz  # PyMuPDF
from PIL import Image
import io
import os
import re
from typing import List, Tuple, Optional
from collections import Counter


class PDFWatermarkRemover:
    """PDF水印去除器"""
    
    def __init__(self, input_path: str):
        self.input_path = input_path
        self.doc = fitz.open(input_path)
        self.watermark_patterns = [
            r'水印',
            r'watermark',
            r'样稿',
            r'draft',
            r'保密',
            r'confidential',
            r'内部资料',
            r'sample',
        ]
    
    def remove_watermark_by_content_stream(self, output_path: str):
        """
        通过编辑PDF内容流去除水印（推荐方法）
        
        此方法直接编辑PDF的内容流，移除标记为水印的Artifact块。
        这是最安全、最精确的方法，不会影响文档的其他内容。
        
        适用于：
        - 使用PDF标准水印标记的文档（/Artifact <</Subtype/Watermark>>）
        - WPS、Adobe等主流软件生成的水印
        
        Args:
            output_path: 输出文件路径
        """
        print("使用内容流编辑法去除水印...")
        removed_count = 0
        
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            page_removed = 0
            
            # 读取页面内容流
            contents = page.read_contents()
            if not contents:
                continue
            
            content_str = contents.decode('latin-1', errors='replace')
            
            # 方法1：移除 /Artifact <</Subtype/Watermark/...>>BDC ... EMC 块
            # 这是PDF标准的水印标记方式
            pattern = r'/Artifact\s*<<[^>]*?/Subtype\s*/Watermark[^>]*?>>BDC\s*.*?EMC'
            new_content, count = re.subn(pattern, '', content_str, flags=re.DOTALL)
            if count > 0:
                page_removed += count
                print(f"  第{page_num+1}页: 移除了 {count} 个Artifact水印块")
            
            # 方法2：移除带有 /Watermark 标记的 BDC...EMC 块（更宽泛的匹配）
            if page_removed == 0:
                pattern2 = r'BDC\s*q\s*[^Q]*?Watermark[^Q]*?Q\s*EMC'
                new_content2, count2 = re.subn(pattern2, '', new_content, flags=re.DOTALL)
                if count2 > 0:
                    new_content = new_content2
                    page_removed += count2
                    print(f"  第{page_num+1}页: 移除了 {count2} 个BDC水印块")
            
            if page_removed > 0:
                # 将修改后的内容写回
                new_contents_bytes = new_content.encode('latin-1')
                
                # 获取内容流的xref
                xref = page.get_contents()[0]
                
                # 更新内容流
                self.doc.update_stream(xref, new_contents_bytes)
                
                removed_count += page_removed
        
        # 清理水印相关的资源（可选，但更干净）
        self._clean_watermark_resources()
        
        self.doc.save(output_path, garbage=4, deflate=True)
        print(f"✓ 内容流编辑完成，共移除 {removed_count} 个水印块，保存至: {output_path}")
        return removed_count > 0
    
    def _clean_watermark_resources(self):
        """清理文档中的水印相关资源（OCG、XObject等）"""
        try:
            xref_len = self.doc.xref_length()
            for xref in range(1, xref_len):
                try:
                    obj_str = self.doc.xref_object(xref)
                    # 查找名为 "Watermark" 的 OCG（Optional Content Group）
                    if '/Type /OCG' in obj_str and '/Name (Watermark)' in obj_str:
                        print(f"  清理OCG水印资源 (xref={xref})")
                    # 查找 PieceInfo 中标记为 Watermark 的 Form XObject
                    if '/Private /Watermark' in obj_str and '/Subtype /Form' in obj_str:
                        print(f"  发现水印Form XObject (xref={xref})")
                except:
                    pass
        except Exception as e:
            print(f"  ⚠ 清理资源时出错: {e}")
    
    def remove_watermark_smart(self, output_path: str, watermark_text: str = None):
        """
        智能去水印（综合多种方法）
        
        先尝试内容流编辑法，如果没有检测到标准水印标记，
        则分析文本特征进行去除。
        
        Args:
            output_path: 输出文件路径
            watermark_text: 可选的水印文本关键词
        """
        print("开始智能去水印...")
        
        # 第一步：检测水印类型
        watermark_type = self._detect_watermark_type()
        print(f"检测到水印类型: {watermark_type}")
        
        if watermark_type == 'artifact':
            # 使用内容流编辑法（最安全）
            success = self.remove_watermark_by_content_stream(output_path)
            if success:
                return True
        
        if watermark_type == 'ocg' or watermark_type == 'artifact':
            # 也尝试通过OCG移除
            success = self.remove_watermark_by_ocg(output_path)
            if success:
                return True
        
        # 如果指定了水印文本，使用精确覆盖法
        if watermark_text:
            return self.remove_watermark_precise(output_path, watermark_text)
        
        # 尝试自动检测水印文本并使用安全方法移除
        detected_watermark = self._auto_detect_watermark_text()
        if detected_watermark:
            print(f"自动检测到水印文本: '{detected_watermark}'")
            return self.remove_watermark_by_text_safe(output_path, detected_watermark)
        
        # 最后的后备方案：颜色检测法
        print("使用颜色检测法作为后备方案...")
        return self.remove_watermark_by_color_safe(output_path)
    
    def _detect_watermark_type(self):
        """检测PDF中水印的类型"""
        # 检查内容流中是否有标准水印标记
        for page_num in range(min(2, len(self.doc))):
            page = self.doc[page_num]
            contents = page.read_contents()
            if contents:
                content_str = contents.decode('latin-1', errors='replace')
                if '/Watermark' in content_str or 'Watermark' in content_str:
                    return 'artifact'
        
        # 检查是否有OCG水印
        xref_len = self.doc.xref_length()
        for xref in range(1, xref_len):
            try:
                obj_str = self.doc.xref_object(xref)
                if '/Type /OCG' in obj_str and 'Watermark' in obj_str:
                    return 'ocg'
                if '/Private /Watermark' in obj_str:
                    return 'ocg'
            except:
                pass
        
        return 'unknown'
    
    def _auto_detect_watermark_text(self):
        """自动检测水印文本"""
        # 收集所有页面的文本及其出现频率
        all_texts = []
        
        for page_num in range(min(3, len(self.doc))):
            page = self.doc[page_num]
            text_dict = page.get_text("dict")
            
            for block in text_dict["blocks"]:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if not text or len(text) > 20:
                            continue
                        
                        color = span.get("color", 0)
                        r = (color >> 16) & 0xFF
                        g = (color >> 8) & 0xFF
                        b = color & 0xFF
                        size = span.get("size", 0)
                        
                        all_texts.append({
                            'text': text,
                            'color': (r, g, b),
                            'size': size,
                        })
        
        if not all_texts:
            return None
        
        # 统计文本出现频率
        text_counts = Counter([t['text'] for t in all_texts])
        
        # 水印特征：
        # 1. 在多个页面中出现多次
        # 2. 通常是短文本
        # 3. 可能是非黑色
        for text, count in text_counts.most_common(5):
            if count >= 3 and len(text) <= 10:
                # 检查这个文本是否匹配水印特征
                text_info = [t for t in all_texts if t['text'] == text]
                if text_info:
                    r, g, b = text_info[0]['color']
                    # 非纯黑色的重复短文本很可能是水印
                    if not (r == 0 and g == 0 and b == 0):
                        return text
                    # 即使是黑色，如果出现次数远超正常值也可能是水印
                    if count >= len(self.doc) * 5:
                        return text
        
        return None
    
    def remove_watermark_by_ocg(self, output_path: str):
        """
        通过OCG（Optional Content Group）去除水印
        
        很多PDF水印使用OCG来组织，可以通过移除OCG引用来去除水印。
        """
        print("尝试通过OCG去除水印...")
        
        removed = False
        xref_len = self.doc.xref_length()
        
        # 找到水印OCG的xref
        watermark_ocg_xref = None
        for xref in range(1, xref_len):
            try:
                obj_str = self.doc.xref_object(xref)
                if '/Type /OCG' in obj_str and 'Watermark' in obj_str:
                    watermark_ocg_xref = xref
                    print(f"  找到水印OCG (xref={xref})")
                    break
            except:
                pass
        
        if watermark_ocg_xref is None:
            print("  未找到水印OCG")
            return False
        
        # 使用内容流编辑法移除水印（因为已经确认有OCG）
        success = self.remove_watermark_by_content_stream(output_path)
        return success
    
    def remove_watermark_by_text_safe(self, output_path: str, watermark_text: str):
        """
        安全地移除文本水印（使用覆盖法而非redaction）
        
        与 apply_redactions() 不同，此方法使用白色矩形覆盖水印文本，
        不会破坏底层内容。
        
        Args:
            output_path: 输出文件路径
            watermark_text: 水印文本
        """
        print(f"使用安全覆盖法移除水印文本: '{watermark_text}'")
        
        covered_count = 0
        
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text_dict = page.get_text("dict")
            
            for block in text_dict["blocks"]:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if watermark_text in text:
                            bbox = fitz.Rect(span["bbox"])
                            # 使用Shape绘制白色矩形覆盖（不删除底层内容）
                            shape = page.new_shape()
                            shape.draw_rect(bbox)
                            shape.finish(color=(1, 1, 1), fill=(1, 1, 1))
                            shape.commit()
                            covered_count += 1
        
        self.doc.save(output_path, garbage=4, deflate=True)
        print(f"✓ 安全覆盖完成，共覆盖 {covered_count} 处水印，保存至: {output_path}")
        return covered_count > 0
    
    def remove_watermark_by_color_safe(self, output_path: str, watermark_color_range: Tuple[int, int] = (200, 240)):
        """
        通过颜色范围安全地去除水印
        使用覆盖法（不使用redaction），避免破坏底层内容
        
        Args:
            output_path: 输出文件路径
            watermark_color_range: 水印颜色范围 (min, max)
        """
        print(f"使用安全颜色检测法去除水印: 颜色范围{watermark_color_range}")
        
        covered_count = 0
        
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text_dict = page.get_text("dict")
            
            # 收集灰色文本
            gray_texts = []
            for block in text_dict["blocks"]:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if not text:
                            continue
                        
                        color = span.get("color", 0)
                        r = (color >> 16) & 0xFF
                        g = (color >> 8) & 0xFF
                        b = color & 0xFF
                        
                        is_gray = (abs(r - g) <= 10 and abs(g - b) <= 10 and abs(r - b) <= 10)
                        in_range = (watermark_color_range[0] <= r <= watermark_color_range[1])
                        
                        if is_gray and in_range:
                            gray_texts.append({
                                'text': text,
                                'bbox': fitz.Rect(span["bbox"]),
                                'length': len(text)
                            })
            
            # 分析文本特征
            text_counts = Counter([t['text'] for t in gray_texts])
            
            for text_info in gray_texts:
                text = text_info['text']
                count = text_counts[text]
                length = text_info['length']
                
                is_watermark = False
                if length <= 6 and count >= 2:
                    is_watermark = True
                elif any(kw in text.lower() for kw in ['水印', '样稿', 'draft', 'watermark']):
                    is_watermark = True
                
                if is_watermark:
                    shape = page.new_shape()
                    shape.draw_rect(text_info['bbox'])
                    shape.finish(color=(1, 1, 1), fill=(1, 1, 1))
                    shape.commit()
                    covered_count += 1
        
        self.doc.save(output_path, garbage=4, deflate=True)
        print(f"✓ 颜色检测完成，覆盖 {covered_count} 处，保存至: {output_path}")
        return covered_count > 0
    
    def remove_by_cover(self, output_path: str, watermark_rects: List[Tuple[float, float, float, float]] = None):
        """
        使用覆盖法去除水印
        
        Args:
            output_path: 输出文件路径
            watermark_rects: 水印区域列表 [(x0, y0, x1, y1), ...]
        """
        if watermark_rects is None:
            page = self.doc[0]
            width, height = page.rect.width, page.rect.height
            
            watermark_rects = [
                (0, 0, 300, 200),
                (width - 300, 0, width, 200),
                (width/2 - 150, height/2 - 100, width/2 + 150, height/2 + 100),
                (0, height - 200, 300, height),
                (width - 300, height - 200, width, height),
            ]
        
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            for rect in watermark_rects:
                shape = page.new_shape()
                shape.draw_rect(fitz.Rect(rect))
                shape.finish(color=(1, 1, 1), fill=(1, 1, 1))
                shape.commit()
        
        self.doc.save(output_path, garbage=4, deflate=True)
        print(f"✓ 覆盖法完成，保存至: {output_path}")
    
    def remove_text_watermark(self, output_path: str, keywords: List[str] = None):
        """
        删除文本水印（安全模式 - 使用覆盖法而非redaction）
        
        Args:
            output_path: 输出文件路径
            keywords: 水印关键词列表
        """
        if keywords is None:
            keywords = self.watermark_patterns
        
        removed_count = 0
        
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text_dict = page.get_text("dict")
            
            for block in text_dict["blocks"]:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"]
                        for keyword in keywords:
                            if keyword.lower() in text.lower():
                                bbox = fitz.Rect(span["bbox"])
                                # 使用覆盖法替代redaction
                                shape = page.new_shape()
                                shape.draw_rect(bbox)
                                shape.finish(color=(1, 1, 1), fill=(1, 1, 1))
                                shape.commit()
                                removed_count += 1
                                break
        
        self.doc.save(output_path, garbage=4, deflate=True)
        print(f"✓ 已覆盖 {removed_count} 处文本水印，保存至: {output_path}")
    
    def remove_watermark_precise(self, output_path: str, watermark_text: str = None):
        """
        精确去除水印（保守方案）
        只覆盖明确匹配的水印文本区域，保留所有其他内容
        
        Args:
            output_path: 输出文件路径
            watermark_text: 指定水印文本
        """
        if not watermark_text:
            print("错误：使用精确模式必须提供水印文本")
            return False
        
        print(f"使用精确模式去除水印，目标文本: '{watermark_text}'")
        
        # 先尝试内容流编辑法
        watermark_type = self._detect_watermark_type()
        if watermark_type in ('artifact', 'ocg'):
            print("检测到标准水印标记，优先使用内容流编辑法")
            return self.remove_watermark_by_content_stream(output_path)
        
        # 使用安全覆盖法
        return self.remove_watermark_by_text_safe(output_path, watermark_text)
    
    def remove_watermark_aggressive(self, output_path: str, watermark_text: str = None):
        """
        强力去除水印
        
        Args:
            output_path: 输出文件路径
            watermark_text: 指定水印文本
        """
        print("开始强力去水印...")
        
        # 第一步：尝试内容流编辑法
        watermark_type = self._detect_watermark_type()
        if watermark_type in ('artifact', 'ocg'):
            print("检测到标准水印标记，使用内容流编辑法")
            return self.remove_watermark_by_content_stream(output_path)
        
        # 第二步：如果指定了水印文本，使用安全覆盖法
        if watermark_text:
            return self.remove_watermark_by_text_safe(output_path, watermark_text)
        
        # 第三步：自动检测并移除
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text_dict = page.get_text("dict")
            
            text_info = []
            for block in text_dict["blocks"]:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if len(text) > 0 and len(text) <= 10:
                            color = span.get("color", 0)
                            r = (color >> 16) & 0xFF
                            g = (color >> 8) & 0xFF
                            b = color & 0xFF
                            
                            bbox = fitz.Rect(span["bbox"])
                            text_info.append({
                                'text': text,
                                'bbox': bbox,
                                'color': (r, g, b)
                            })
            
            text_counts = Counter([info['text'] for info in text_info])
            
            for info in text_info:
                if text_counts[info['text']] >= 3:
                    shape = page.new_shape()
                    shape.draw_rect(info['bbox'])
                    shape.finish(color=(1, 1, 1), fill=(1, 1, 1))
                    shape.commit()
                    print(f"✓ 覆盖疑似水印: {info['text']}")
        
        self.doc.save(output_path, garbage=4, deflate=True)
        print(f"✓ 强力去水印完成: {output_path}")
    
    def remove_image_watermark(self, output_path: str):
        """
        去除图片型水印
        """
        print("开始去除图片型水印...")
        removed_count = 0
        
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            image_list = page.get_images(full=True)
            
            for img_index, img in enumerate(image_list):
                xref = img[0]
                try:
                    base_image = self.doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    
                    from PIL import Image as PILImage
                    pil_img = PILImage.open(io.BytesIO(image_bytes))
                    width, height = pil_img.size
                    
                    if width < page.rect.width * 0.5 and height < page.rect.height * 0.5:
                        page.delete_image(xref)
                        removed_count += 1
                        print(f"✓ 第 {page_num + 1} 页: 删除小图片水印 ({width}x{height})")
                except Exception as e:
                    print(f"  ⚠ 处理图片失败: {e}")
        
        self.doc.save(output_path, garbage=4, deflate=True)
        print(f"✓ 图片型水印去除完成，共删除 {removed_count} 处，保存至: {output_path}")
    
    def remove_by_image_processing(self, output_path: str, threshold: int = 200):
        """
        使用图像处理去除水印（适用于图片型水印）
        
        Args:
            output_path: 输出文件路径
            threshold: 灰度阈值
        """
        print("使用图像处理法去除水印...")
        new_doc = fitz.open()
        
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            pixels = img.load()
            width, height = img.size
            
            for y in range(height):
                for x in range(width):
                    r, g, b = pixels[x, y]
                    if r > threshold and g > threshold and b > threshold:
                        if abs(r - g) < 20 and abs(g - b) < 20 and abs(r - b) < 20:
                            pixels[x, y] = (255, 255, 255)
            
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            
            new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(page.rect, stream=img_bytes.read())
        
        new_doc.save(output_path, garbage=4, deflate=True)
        new_doc.close()
        print(f"✓ 图像处理完成，保存至: {output_path}")
    
    def remove_watermark_by_color(self, output_path: str, watermark_color_range: Tuple[int, int] = (200, 240)):
        """
        通过颜色范围去除水印（安全版）
        """
        return self.remove_watermark_by_color_safe(output_path, watermark_color_range)
    
    def remove_watermark_by_opacity(self, output_path: str, min_opacity: float = 0.1, max_opacity: float = 0.5):
        """
        通过透明度检测去除水印（安全覆盖法）
        """
        print(f"使用透明度检测去除水印...")
        
        covered_count = 0
        
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text_dict = page.get_text("dict")
            
            for block in text_dict["blocks"]:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        color = span.get("color", 0)
                        r = (color >> 16) & 0xFF
                        g = (color >> 8) & 0xFF
                        b = color & 0xFF
                        
                        if (210 <= r <= 240 and 210 <= g <= 240 and 210 <= b <= 240 and
                            abs(r - g) <= 10 and abs(g - b) <= 10):
                            bbox = fitz.Rect(span["bbox"])
                            shape = page.new_shape()
                            shape.draw_rect(bbox)
                            shape.finish(color=(1, 1, 1), fill=(1, 1, 1))
                            shape.commit()
                            covered_count += 1
        
        self.doc.save(output_path, garbage=4, deflate=True)
        print(f"✓ 透明度检测完成，覆盖 {covered_count} 处，保存至: {output_path}")
    
    def remove_watermark_by_rebuild(self, output_path: str, watermark_text: str = None):
        """
        通过重建页面去除水印（终极方案）
        将PDF页面转为图片处理后重建
        """
        print("使用页面重建法去除水印...")
        
        try:
            from PIL import Image as PILImage, ImageDraw
            
            new_doc = fitz.open()
            
            for page_num in range(len(self.doc)):
                print(f"处理第 {page_num + 1}/{len(self.doc)} 页...")
                page = self.doc[page_num]
                page_rect = page.rect
                width, height = page_rect.width, page_rect.height
                
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
                img = PILImage.open(io.BytesIO(pix.tobytes("png")))
                draw = ImageDraw.Draw(img)
                
                if watermark_text:
                    text_dict = page.get_text("dict")
                    for block in text_dict["blocks"]:
                        if "lines" not in block:
                            continue
                        for line in block["lines"]:
                            for span in line["spans"]:
                                text = span["text"].strip()
                                if watermark_text in text:
                                    bbox = span["bbox"]
                                    x0, y0, x1, y1 = bbox
                                    x0, y0 = x0 * 3, y0 * 3
                                    x1, y1 = x1 * 3, y1 * 3
                                    x0, y0 = max(0, x0 - 10), max(0, y0 - 10)
                                    x1, y1 = min(img.width, x1 + 10), min(img.height, y1 + 10)
                                    draw.rectangle([x0, y0, x1, y1], fill=(255, 255, 255))
                                    print(f"  ✓ 覆盖水印: {text}")
                
                img_bytes = io.BytesIO()
                img.save(img_bytes, format='PNG', quality=95)
                img_bytes.seek(0)
                
                new_page = new_doc.new_page(width=width, height=height)
                new_page.insert_image(page_rect, stream=img_bytes.read())
            
            new_doc.save(output_path, garbage=4, deflate=True)
            new_doc.close()
            
            print(f"✓ 页面重建完成，保存至: {output_path}")
            return True
            
        except Exception as e:
            print(f"✗ 页面重建失败: {str(e)}")
            return False
    
    def auto_detect_and_remove(self, output_path: str):
        """
        自动检测并去除水印（改进版）
        优先使用安全的内容流编辑法，避免破坏文档内容
        """
        print("正在自动检测水印...")
        
        # 优先尝试内容流编辑法（最安全、最精确）
        watermark_type = self._detect_watermark_type()
        
        if watermark_type in ('artifact', 'ocg'):
            print(f"检测到标准水印标记 ({watermark_type})，使用内容流编辑法")
            success = self.remove_watermark_by_content_stream(output_path)
            if success:
                print(f"✓ 自动去水印完成: {output_path}")
                return
        
        # 尝试自动检测水印文本
        detected = self._auto_detect_watermark_text()
        if detected:
            print(f"检测到疑似水印文本: '{detected}'，使用安全覆盖法")
            self.remove_watermark_by_text_safe(output_path, detected)
            print(f"✓ 自动去水印完成: {output_path}")
            return
        
        # 最后尝试颜色检测法
        print("使用颜色检测法...")
        self.remove_watermark_by_color_safe(output_path)
        print(f"✓ 自动去水印完成: {output_path}")
    
    def preview_watermark_areas(self, output_preview: str = None):
        """预览水印区域"""
        page = self.doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        
        width, height = img.size
        areas = [
            (0, 0, 400, 200),
            (width - 400, 0, width, 200),
            (width/2 - 200, height/2 - 100, width/2 + 200, height/2 + 100),
            (0, height - 200, 400, height),
            (width - 400, height - 200, width, height),
        ]
        
        for i, area in enumerate(areas):
            draw.rectangle(area, outline="red", width=3)
            draw.text((area[0], area[1] - 20), f"Area {i+1}", fill="red")
        
        if output_preview:
            img.save(output_preview)
            print(f"✓ 预览图已保存: {output_preview}")
        else:
            preview_path = self.input_path.replace('.pdf', '_preview.png')
            img.save(preview_path)
            print(f"✓ 预览图已保存: {preview_path}")
        
        return areas
    
    def close(self):
        """关闭文档"""
        if self.doc:
            self.doc.close()


def batch_process_pdf(input_dir: str, output_dir: str, method: str = "auto"):
    """批量处理PDF文件"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.pdf')]
    print(f"发现 {len(pdf_files)} 个PDF文件")
    
    for i, filename in enumerate(pdf_files, 1):
        input_path = os.path.join(input_dir, filename)
        output_path = os.path.join(output_dir, f"no_watermark_{filename}")
        
        print(f"\n[{i}/{len(pdf_files)}] 处理: {filename}")
        
        try:
            remover = PDFWatermarkRemover(input_path)
            
            if method == "auto":
                remover.auto_detect_and_remove(output_path)
            elif method == "stream":
                remover.remove_watermark_by_content_stream(output_path)
            elif method == "smart":
                remover.remove_watermark_smart(output_path)
            elif method == "cover":
                remover.remove_by_cover(output_path)
            elif method == "text":
                remover.remove_text_watermark(output_path)
            elif method == "image":
                remover.remove_by_image_processing(output_path)
            
            remover.close()
            
        except Exception as e:
            print(f"✗ 处理失败: {filename}, 错误: {str(e)}")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python pdf_watermark_remover.py <输入PDF路径> [输出PDF路径] [方法]")
        print("方法: auto(默认), stream, smart, cover, text, image")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.pdf', '_no_watermark.pdf')
    method = sys.argv[3] if len(sys.argv) > 3 else "auto"
    
    if not os.path.exists(input_file):
        print(f"错误: 文件不存在: {input_file}")
        sys.exit(1)
    
    remover = PDFWatermarkRemover(input_file)
    
    if method == "auto":
        remover.auto_detect_and_remove(output_file)
    elif method == "stream":
        remover.remove_watermark_by_content_stream(output_file)
    elif method == "smart":
        remover.remove_watermark_smart(output_file)
    elif method == "cover":
        remover.remove_by_cover(output_file)
    elif method == "text":
        remover.remove_text_watermark(output_file)
    elif method == "image":
        remover.remove_by_image_processing(output_file)
    elif method == "preview":
        remover.preview_watermark_areas()
    else:
        print(f"未知方法: {method}")
    
    remover.close()
