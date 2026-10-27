#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Word水印去除工具
支持去除以下类型的水印：
1. 页眉页脚中的水印
2. 文本框水印
3. 图片水印
4. 艺术字水印
"""

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import os
import re
from typing import List


class WordWatermarkRemover:
    """Word水印去除器"""
    
    def __init__(self, input_path: str):
        self.input_path = input_path
        self.doc = Document(input_path)
        self.watermark_keywords = [
            '水印', 'watermark', '样稿', 'draft', '保密',
            'confidential', '内部资料', 'sample', '请勿外传'
        ]
    
    def remove_header_footer_watermark(self):
        """
        去除页眉页脚中的水印
        """
        removed_count = 0
        
        # 遍历所有节（section）
        for section in self.doc.sections:
            # 处理页眉
            header = section.header
            for paragraph in header.paragraphs:
                if self._is_watermark_paragraph(paragraph):
                    self._clear_paragraph(paragraph)
                    removed_count += 1
            
            # 处理页眉中的表格
            for table in header.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            if self._is_watermark_paragraph(paragraph):
                                self._clear_paragraph(paragraph)
                                removed_count += 1
            
            # 处理页脚
            footer = section.footer
            for paragraph in footer.paragraphs:
                if self._is_watermark_paragraph(paragraph):
                    self._clear_paragraph(paragraph)
                    removed_count += 1
            
            # 处理页脚中的表格
            for table in footer.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            if self._is_watermark_paragraph(paragraph):
                                self._clear_paragraph(paragraph)
                                removed_count += 1
        
        print(f"✓ 已清理 {removed_count} 处页眉页脚水印")
        return removed_count
    
    def remove_textbox_watermark(self):
        """
        去除文本框水印
        """
        removed_count = 0
        
        # 遍历文档中的所有段落
        for paragraph in self.doc.paragraphs:
            # 检查段落是否包含水印文本
            if self._is_watermark_paragraph(paragraph):
                self._clear_paragraph(paragraph)
                removed_count += 1
        
        # 遍历所有表格
        for table in self.doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        if self._is_watermark_paragraph(paragraph):
                            self._clear_paragraph(paragraph)
                            removed_count += 1
        
        print(f"✓ 已清理 {removed_count} 处文本水印")
        return removed_count
    
    def remove_shape_watermark(self):
        """
        去除形状水印（通过XML操作）
        """
        removed_count = 0
        
        # 遍历所有节
        for section in self.doc.sections:
            # 获取节的XML元素
            sectPr = section._sectPr
            
            # 查找并删除水印形状
            for shape in sectPr.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pict'):
                # 检查形状是否包含水印
                shape_xml = str(shape)
                if any(keyword in shape_xml.lower() for keyword in self.watermark_keywords):
                    shape.getparent().remove(shape)
                    removed_count += 1
        
        # 遍历文档主体
        body = self.doc.element.body
        for shape in body.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pict'):
            shape_xml = str(shape)
            if any(keyword in shape_xml.lower() for keyword in self.watermark_keywords):
                shape.getparent().remove(shape)
                removed_count += 1
        
        print(f"✓ 已清理 {removed_count} 处形状水印")
        return removed_count
    
    def remove_drawing_watermark(self):
        """
        去除绘图水印（图片、艺术字等）
        """
        removed_count = 0
        
        # 遍历文档中的所有段落
        for paragraph in self.doc.paragraphs:
            # 获取段落的XML
            p_xml = paragraph._p
            
            # 查找绘图元素
            for drawing in p_xml.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing'):
                drawing_xml = str(drawing)
                # 检查是否包含水印关键词
                if any(keyword in drawing_xml.lower() for keyword in self.watermark_keywords):
                    drawing.getparent().remove(drawing)
                    removed_count += 1
                # 检查是否是半透明（常见水印特征）
                elif 'alpha' in drawing_xml.lower() or 'opacity' in drawing_xml.lower():
                    drawing.getparent().remove(drawing)
                    removed_count += 1
        
        print(f"✓ 已清理 {removed_count} 处绘图水印")
        return removed_count
    
    def remove_watermark_via_settings(self):
        """
        通过文档设置去除水印（适用于通过Word功能添加的水印）
        """
        removed_count = 0
        
        try:
            # 访问文档的XML设置
            doc_settings = self.doc.settings._element
            
            # 查找并删除水印设置
            for watermark in doc_settings.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}watermark'):
                watermark.getparent().remove(watermark)
                print("✓ 已删除文档设置中的水印")
                removed_count += 1
            
        except Exception as e:
            print(f"⚠ 通过设置去除水印失败: {str(e)}")
        
        # 遍历所有节，查找并删除节属性中的水印
        try:
            for section in self.doc.sections:
                sectPr = section._sectPr
                
                # 查找水印相关的XML元素
                # Word水印通常存储在 sectPr 下的 headerReference 或直接在 sectPr 中
                
                # 方法1：查找并删除所有可能的header/footer中的水印形状
                for header_ref in sectPr.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}headerReference'):
                    # 获取header ID
                    header_id = header_ref.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                    if header_id:
                        # 尝试从文档中删除对应的header
                        try:
                            # 遍历文档的所有部分查找header
                            for rel in self.doc.part.rels.values():
                                if rel.reltype == 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/header':
                                    if rel.rId == header_id:
                                        # 获取header部分
                                        header_part = rel.target_part
                                        # 删除header中的所有内容
                                        header_element = header_part._element
                                        for child in list(header_element):
                                            header_element.remove(child)
                                        removed_count += 1
                                        print(f"✓ 已清理header中的水印")
                        except Exception as e:
                            print(f"⚠ 清理header失败: {str(e)}")
                
                # 方法2：直接删除sectPr中的所有形状和绘图元素（可能包含水印）
                for pict in sectPr.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pict'):
                    pict.getparent().remove(pict)
                    removed_count += 1
                    print("✓ 已删除sectPr中的形状")
                
                for drawing in sectPr.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing'):
                    drawing.getparent().remove(drawing)
                    removed_count += 1
                    print("✓ 已删除sectPr中的绘图")
                    
        except Exception as e:
            print(f"⚠ 处理节属性时出错: {str(e)}")
        
        return removed_count
    
    def _is_watermark_paragraph(self, paragraph) -> bool:
        """
        判断段落是否为水印
        """
        text = paragraph.text.strip()
        
        if not text:
            return False
        
        # 检查是否包含水印关键词
        for keyword in self.watermark_keywords:
            if keyword.lower() in text.lower():
                return True
        
        # 检查文本格式（水印通常有特定格式）
        for run in paragraph.runs:
            # 检查字体大小（水印通常较大）
            if run.font.size and run.font.size > Pt(40):
                # 检查颜色（水印通常为灰色）
                if run.font.color and run.font.color.rgb:
                    color = run.font.color.rgb
                    # 灰色系颜色判断
                    if color[0] == color[1] == color[2] and color[0] > 150:
                        return True
            
            # 检查透明度（如果支持）
            if hasattr(run, '_element'):
                rPr = run._element.find(qn('w:rPr'))
                if rPr is not None:
                    # 检查是否有透明度设置
                    for elem in rPr:
                        if 'alpha' in elem.tag.lower():
                            return True
        
        return False
    
    def _clear_paragraph(self, paragraph):
        """
        清空段落内容
        """
        for run in paragraph.runs:
            run.text = ""
    
    def remove_word_builtin_watermark(self):
        """
        去除Word内置水印（通过Word菜单插入的水印）
        这种水印通常存储在header中，使用VML或DrawingML格式
        """
        removed_count = 0
        
        try:
            # Word内置水印通常在每个节的header中
            for section in self.doc.sections:
                header = section.header
                
                # 遍历header中的所有段落
                for paragraph in header.paragraphs:
                    p = paragraph._p
                    
                    # 查找并删除所有r元素（run）
                    for r in p.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r'):
                        # 检查是否包含图片或绘图
                        has_drawing = r.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing') is not None
                        has_pict = r.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pict') is not None
                        
                        if has_drawing or has_pict:
                            r.getparent().remove(r)
                            removed_count += 1
                            print("✓ 已删除header中的水印元素")
                
                # 同时检查header的XML，删除所有drawing和pict元素
                header_element = header._header_part._element
                for drawing in header_element.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing'):
                    drawing.getparent().remove(drawing)
                    removed_count += 1
                    print("✓ 已删除header中的drawing元素")
                
                for pict in header_element.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pict'):
                    pict.getparent().remove(pict)
                    removed_count += 1
                    print("✓ 已删除header中的pict元素")
                    
        except Exception as e:
            print(f"⚠ 去除Word内置水印失败: {str(e)}")
        
        return removed_count
    
    def remove_all_shapes_in_headers(self):
        """
        删除所有header中的形状和文本框（激进方法）
        """
        removed_count = 0
        
        try:
            for section in self.doc.sections:
                header = section.header
                header_element = header._header_part._element
                
                # 删除所有可能的形状容器
                for container in header_element.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r'):
                    # 检查是否包含任何图形元素
                    container_xml = str(container)
                    if 'drawing' in container_xml or 'pict' in container_xml or 'shape' in container_xml:
                        container.getparent().remove(container)
                        removed_count += 1
                        
        except Exception as e:
            print(f"⚠ 删除header形状失败: {str(e)}")
        
        if removed_count > 0:
            print(f"✓ 已删除 {removed_count} 个header中的形状")
        
        return removed_count
    
    def auto_remove_watermark(self, output_path: str = None):
        """
        自动去除所有类型的水印
        """
        if output_path is None:
            output_path = self.input_path.replace('.docx', '_no_watermark.docx')
        
        print(f"开始处理: {self.input_path}")
        print("-" * 50)
        
        # 方法1：通过文档设置去除
        self.remove_watermark_via_settings()
        
        # 方法2：去除Word内置水印（在header中）
        self.remove_word_builtin_watermark()
        
        # 方法3：删除header中的所有形状（激进方法）
        self.remove_all_shapes_in_headers()
        
        # 方法4：去除页眉页脚水印
        self.remove_header_footer_watermark()
        
        # 方法5：去除文本框水印
        self.remove_textbox_watermark()
        
        # 方法6：去除形状水印
        self.remove_shape_watermark()
        
        # 方法7：去除绘图水印
        self.remove_drawing_watermark()
        
        # 保存文档
        self.doc.save(output_path)
        print("-" * 50)
        print(f"✓ 处理完成，已保存: {output_path}")
        
        return output_path
    
    def remove_by_custom_keywords(self, keywords: List[str], output_path: str = None):
        """
        根据自定义关键词去除水印
        
        Args:
            keywords: 自定义关键词列表
            output_path: 输出文件路径
        """
        if output_path is None:
            output_path = self.input_path.replace('.docx', '_no_watermark.docx')
        
        self.watermark_keywords = keywords
        
        print(f"使用自定义关键词: {keywords}")
        
        # 遍历所有段落并删除包含关键词的内容
        for paragraph in self.doc.paragraphs:
            if self._is_watermark_paragraph(paragraph):
                self._clear_paragraph(paragraph)
        
        # 遍历所有表格
        for table in self.doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        if self._is_watermark_paragraph(paragraph):
                            self._clear_paragraph(paragraph)
        
        # 保存文档
        self.doc.save(output_path)
        print(f"✓ 已保存: {output_path}")


def batch_process_word(input_dir: str, output_dir: str):
    """
    批量处理Word文件
    
    Args:
        input_dir: 输入目录
        output_dir: 输出目录
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    word_files = [f for f in os.listdir(input_dir) 
                  if f.lower().endswith('.docx') and not f.startswith('~$')]
    
    print(f"发现 {len(word_files)} 个Word文件")
    
    for i, filename in enumerate(word_files, 1):
        input_path = os.path.join(input_dir, filename)
        output_path = os.path.join(output_dir, f"no_watermark_{filename}")
        
        print(f"\n[{i}/{len(word_files)}] 处理: {filename}")
        
        try:
            remover = WordWatermarkRemover(input_path)
            remover.auto_remove_watermark(output_path)
        except Exception as e:
            print(f"✗ 处理失败: {filename}, 错误: {str(e)}")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python word_watermark_remover.py <输入Word路径> [输出Word路径] [关键词1,关键词2,...]")
        print("示例:")
        print("  python word_watermark_remover.py input.docx")
        print("  python word_watermark_remover.py input.docx output.docx")
        print("  python word_watermark_remover.py input.docx output.docx 机密,内部资料")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not os.path.exists(input_file):
        print(f"错误: 文件不存在: {input_file}")
        sys.exit(1)
    
    remover = WordWatermarkRemover(input_file)
    
    if len(sys.argv) > 3:
        # 使用自定义关键词
        keywords = sys.argv[3].split(',')
        remover.remove_by_custom_keywords(keywords, output_file)
    else:
        # 自动去除
        remover.auto_remove_watermark(output_file)
