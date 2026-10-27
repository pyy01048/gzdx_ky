#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
水印去除工具 - 统一入口
支持PDF和Word文档的水印去除
v2.0 - 改进PDF水印去除，避免破坏文档内容
"""

import argparse
import os
import sys

# 导入自定义模块
from pdf_watermark_remover import PDFWatermarkRemover, batch_process_pdf
from word_watermark_remover import WordWatermarkRemover, batch_process_word


def print_banner():
    """打印程序横幅"""
    banner = """
    ╔═══════════════════════════════════════════════════════════╗
    ║              文档水印去除工具 v2.0                        ║
    ║                                                           ║
    ║   支持格式: PDF (.pdf) | Word (.docx)                    ║
    ║   改进: 内容流编辑法，精确去水印不破坏内容                  ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    print(banner)


def process_single_file(input_path: str, output_path: str = None, method: str = "auto"):
    """
    处理单个文件
    
    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        method: 处理方法
    """
    if not os.path.exists(input_path):
        print(f"✗ 错误: 文件不存在: {input_path}")
        return False
    
    # 根据文件类型选择处理器
    file_ext = os.path.splitext(input_path)[1].lower()
    
    if file_ext == '.pdf':
        print(f"\n📄 处理PDF文件: {os.path.basename(input_path)}")
        print("-" * 60)
        
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
                remover.remove_image_watermark(output_path)
            elif method == "image_process":
                remover.remove_by_image_processing(output_path)
            elif method == "color":
                remover.remove_watermark_by_color(output_path)
            elif method == "opacity":
                remover.remove_watermark_by_opacity(output_path)
            elif method == "rebuild":
                # 页面重建法（终极方案）
                watermark_text = input("请输入水印文字（如'王道'，直接回车自动检测）: ").strip()
                remover.remove_watermark_by_rebuild(output_path, watermark_text if watermark_text else None)
            elif method == "precise":
                # 精确模式
                watermark_text = input("请输入水印文字（如'王道'，直接回车尝试自动检测）: ").strip()
                if watermark_text:
                    remover.remove_watermark_precise(output_path, watermark_text)
                else:
                    # 如果没有输入文本，尝试自动检测
                    remover.auto_detect_and_remove(output_path)
            elif method == "aggressive":
                watermark_text = input("请输入水印文字（可选，直接回车自动检测）: ").strip()
                remover.remove_watermark_aggressive(output_path, watermark_text if watermark_text else None)
            elif method == "preview":
                remover.preview_watermark_areas()
            else:
                print(f"✗ 未知方法: {method}")
                return False
            
            remover.close()
            return True
            
        except Exception as e:
            print(f"✗ 处理失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    elif file_ext == '.docx':
        print(f"\n📝 处理Word文件: {os.path.basename(input_path)}")
        print("-" * 60)
        
        try:
            remover = WordWatermarkRemover(input_path)
            remover.auto_remove_watermark(output_path)
            return True
            
        except Exception as e:
            print(f"✗ 处理失败: {str(e)}")
            return False
    
    else:
        print(f"✗ 不支持的文件格式: {file_ext}")
        print("支持的格式: .pdf, .docx")
        return False


def process_batch(input_dir: str, output_dir: str, file_type: str = "all"):
    """
    批量处理文件
    
    Args:
        input_dir: 输入目录
        output_dir: 输出目录
        file_type: 文件类型 (pdf/word/all)
    """
    if not os.path.exists(input_dir):
        print(f"✗ 错误: 目录不存在: {input_dir}")
        return
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"✓ 创建输出目录: {output_dir}")
    
    print(f"\n📁 批量处理模式")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print("-" * 60)
    
    # 处理PDF文件
    if file_type in ["pdf", "all"]:
        pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.pdf')]
        if pdf_files:
            print(f"\n发现 {len(pdf_files)} 个PDF文件")
            pdf_output_dir = os.path.join(output_dir, "pdf_output")
            batch_process_pdf(input_dir, pdf_output_dir, method="auto")
    
    # 处理Word文件
    if file_type in ["word", "all"]:
        word_files = [f for f in os.listdir(input_dir) 
                      if f.lower().endswith('.docx') and not f.startswith('~$')]
        if word_files:
            print(f"\n发现 {len(word_files)} 个Word文件")
            word_output_dir = os.path.join(output_dir, "word_output")
            batch_process_word(input_dir, word_output_dir)
    
    print("\n" + "=" * 60)
    print("✓ 批量处理完成")
    print("=" * 60)


def interactive_mode():
    """交互模式"""
    print_banner()
    
    print("\n请选择操作模式:")
    print("  1. 处理单个文件")
    print("  2. 批量处理目录")
    print("  3. 退出")
    
    choice = input("\n请输入选项 (1-3): ").strip()
    
    if choice == "1":
        # 单个文件处理
        input_path = input("请输入文件路径: ").strip().strip('"')
        
        if not os.path.exists(input_path):
            print(f"✗ 文件不存在: {input_path}")
            return
        
        # 自动生成输出路径
        file_name, file_ext = os.path.splitext(input_path)
        default_output = f"{file_name}_no_watermark{file_ext}"
        
        output_path = input(f"请输入输出路径 (默认: {default_output}): ").strip().strip('"')
        if not output_path:
            output_path = default_output
        
        # PDF文件选择方法
        method = "auto"
        if input_path.lower().endswith('.pdf'):
            print("\n选择处理方法:")
            print("  1. 自动检测（推荐！智能选择最佳方法）")
            print("  2. 内容流编辑法（精确移除PDF水印标记）")
            print("  3. 智能综合法（多种方法组合）")
            print("  4. 精确模式（指定水印文字后精确移除）")
            print("  5. 覆盖法（适合固定位置水印）")
            print("  6. 文本覆盖法（覆盖关键词文本）")
            print("  7. 图片水印法（适合图片型水印）")
            print("  8. 颜色检测法（适合灰色半透明文字水印）")
            print("  9. 透明度检测法")
            print("  10. 强力去除（适合顽固水印）")
            print("  11. 图像处理法（像素级处理）")
            print("  12. 页面重建法（终极方案，可能丢失格式）")
            
            method_choice = input("请输入选项 (1-12, 推荐1): ").strip()
            method_map = {
                "1": "auto",
                "2": "stream",
                "3": "smart",
                "4": "precise",
                "5": "cover",
                "6": "text",
                "7": "image",
                "8": "color",
                "9": "opacity",
                "10": "aggressive",
                "11": "image_process",
                "12": "rebuild"
            }
            method = method_map.get(method_choice, "auto")
        
        process_single_file(input_path, output_path, method)
    
    elif choice == "2":
        # 批量处理
        input_dir = input("请输入输入目录路径: ").strip().strip('"')
        
        if not os.path.exists(input_dir):
            print(f"✗ 目录不存在: {input_dir}")
            return
        
        output_dir = input("请输入输出目录路径 (默认: ./output): ").strip().strip('"')
        if not output_dir:
            output_dir = "./output"
        
        print("\n选择文件类型:")
        print("  1. 所有文件")
        print("  2. 仅PDF")
        print("  3. 仅Word")
        
        type_choice = input("请输入选项 (1-3, 默认1): ").strip()
        type_map = {
            "1": "all",
            "2": "pdf",
            "3": "word"
        }
        file_type = type_map.get(type_choice, "all")
        
        process_batch(input_dir, output_dir, file_type)
    
    elif choice == "3":
        print("再见!")
        sys.exit(0)
    
    else:
        print("✗ 无效选项")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='文档水印去除工具 v2.0 - 支持PDF和Word',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 交互模式（推荐）
  python main.py
  
  # 处理单个文件（自动检测水印类型）
  python main.py -i input.pdf
  python main.py -i input.docx -o output.docx
  
  # PDF指定处理方法
  python main.py -i input.pdf -m stream   # 内容流编辑法（推荐）
  python main.py -i input.pdf -m smart    # 智能综合法
  python main.py -i input.pdf -m auto     # 自动检测
  
  # 批量处理
  python main.py -b ./input_dir ./output_dir
  python main.py -b ./input_dir ./output_dir -t pdf
  
PDF处理方法:
  auto          - 自动检测并去除（推荐，智能选择最佳方法）
  stream        - 内容流编辑法（直接编辑PDF内容流，最精确）
  smart         - 智能综合法（多种方法组合）
  precise       - 精确模式（指定水印文字后精确移除）
  cover         - 覆盖法（用白色矩形覆盖水印区域）
  text          - 文本覆盖法（覆盖匹配关键词的文本）
  image         - 图片水印法（删除PDF中的图片水印）
  image_process - 图像处理法（像素级处理）
  color         - 颜色检测法（适合灰色半透明文字水印）
  opacity       - 透明度检测法
  aggressive    - 强力去除（适合顽固水印）
  rebuild       - 页面重建法（终极方案，可能丢失格式）
  preview       - 预览水印区域
        """
    )
    
    parser.add_argument('-i', '--input', help='输入文件路径')
    parser.add_argument('-o', '--output', help='输出文件路径')
    parser.add_argument('-m', '--method', default='auto', 
                        choices=['auto', 'stream', 'smart', 'precise', 'cover', 'text', 
                                 'image', 'image_process', 'color', 'opacity', 
                                 'aggressive', 'rebuild', 'preview'],
                        help='PDF处理方法 (默认: auto)')
    parser.add_argument('-b', '--batch', nargs=2, metavar=('INPUT_DIR', 'OUTPUT_DIR'),
                        help='批量处理模式')
    parser.add_argument('-t', '--type', default='all', choices=['pdf', 'word', 'all'],
                        help='批量处理时的文件类型 (默认: all)')
    
    args = parser.parse_args()
    
    # 如果没有参数，进入交互模式
    if len(sys.argv) == 1:
        interactive_mode()
        return
    
    # 批量处理模式
    if args.batch:
        process_batch(args.batch[0], args.batch[1], args.type)
        return
    
    # 单个文件处理
    if args.input:
        output = args.output
        if not output:
            file_name, file_ext = os.path.splitext(args.input)
            output = f"{file_name}_no_watermark{file_ext}"
        process_single_file(args.input, output, args.method)
        return
    
    # 显示帮助
    parser.print_help()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n操作已取消")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ 发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
