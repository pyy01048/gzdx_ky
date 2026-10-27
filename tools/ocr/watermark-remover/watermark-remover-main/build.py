#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包脚本 - 将文档水印去除工具打包成可执行文件
使用PyInstaller打包
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def check_pyinstaller():
    """检查是否安装了PyInstaller"""
    try:
        import PyInstaller
        return True
    except ImportError:
        return False


def install_pyinstaller():
    """安装PyInstaller"""
    print("正在安装PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    print("✓ PyInstaller安装完成")


def clean_build_dirs():
    """清理构建目录"""
    dirs_to_clean = ['build', 'dist']
    for d in dirs_to_clean:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"✓ 清理目录: {d}")
    
    for spec_file in Path('.').glob('*.spec'):
        spec_file.unlink()
        print(f"✓ 清理文件: {spec_file}")


def build_executable():
    """打包可执行文件"""
    print("\n" + "=" * 60)
    print("开始打包 - 文档水印去除工具 v2.0")
    print("=" * 60 + "\n")
    
    # PyInstaller命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        '--name=文档水印去除工具',
        '--onefile',
        '--console',
        '--clean',
        '--noconfirm',
        
        # 排除不必要的模块
        '--exclude-module=PyQt5',
        '--exclude-module=PyQt6',
        '--exclude-module=PySide2',
        '--exclude-module=PySide6',
        '--exclude-module=matplotlib',
        '--exclude-module=numpy',
        '--exclude-module=pandas',
        '--exclude-module=scipy',
        '--exclude-module=tkinter',
        
        # 隐藏导入
        '--hidden-import=PyMuPDF',
        '--hidden-import=fitz',
        '--hidden-import=fitz.fitz',
        '--hidden-import=docx',
        '--hidden-import=docx.shared',
        '--hidden-import=docx.enum.text',
        '--hidden-import=docx.oxml.ns',
        '--hidden-import=docx.oxml',
        '--hidden-import=PIL',
        '--hidden-import=PIL.Image',
        '--hidden-import=PIL.ImageDraw',
        '--hidden-import=pdf_watermark_remover',
        '--hidden-import=word_watermark_remover',
        '--hidden-import=collections',
        '--hidden-import=re',
        
        'main.py'
    ]
    
    print("执行命令:")
    print(" ".join(cmd))
    print()
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if result.returncode == 0:
            print("\n" + "=" * 60)
            print("✓ 打包成功!")
            print("=" * 60)
            exe_path = os.path.abspath('dist/文档水印去除工具.exe')
            print(f"\n可执行文件位置: {exe_path}")
            return True
        else:
            print("\n✗ 打包失败!")
            print("\n错误输出:")
            print(result.stderr[-3000:] if len(result.stderr) > 3000 else result.stderr)
            return False
        
    except Exception as e:
        print(f"\n✗ 打包失败: {str(e)}")
        return False


def create_distribution_package():
    """创建分发包"""
    print("\n" + "=" * 60)
    print("创建分发包")
    print("=" * 60 + "\n")
    
    dist_package_dir = '发布包'
    
    # 确保发布包目录存在
    os.makedirs(dist_package_dir, exist_ok=True)
    
    # 复制可执行文件
    exe_name = '文档水印去除工具.exe'
    if os.path.exists(f'dist/{exe_name}'):
        shutil.copy(f'dist/{exe_name}', dist_package_dir)
        print(f"✓ 复制: {exe_name}")
    else:
        print(f"✗ 未找到: dist/{exe_name}")
        return
    
    # 复制说明文档
    if os.path.exists('README.md'):
        shutil.copy('README.md', dist_package_dir)
        print("✓ 复制: README.md")
    
    # 创建使用说明
    usage_file = os.path.join(dist_package_dir, '使用说明.txt')
    with open(usage_file, 'w', encoding='utf-8') as f:
        f.write("""文档水印去除工具 v2.0 - 使用说明
=====================================

【更新内容 v2.0】
- 新增"内容流编辑法"，直接编辑PDF内容流精确移除水印
- 自动检测水印类型，智能选择最佳去除方法
- 修复了去水印时可能误删文档内容的问题
- 不再使用redaction方式，改用安全的覆盖法

【快速开始】
1. 双击运行"文档水印去除工具.exe"
2. 选择操作模式（单个文件或批量处理）
3. 按提示选择要处理的PDF或Word文件
4. 选择"自动检测"方法（推荐）
5. 等待处理完成

【支持的格式】
  - PDF (.pdf)
  - Word (.docx)

【PDF处理方法】
  1. 自动检测（推荐！） - 智能识别水印类型并选择最佳方法
  2. 内容流编辑法 - 直接编辑PDF内容流，最精确
  3. 智能综合法 - 多种方法组合
  4. 精确模式 - 指定水印文字后精确移除
  5. 覆盖法 - 用白色矩形覆盖水印区域
  6. 文本覆盖法 - 覆盖关键词文本
  7. 图片水印法 - 适合图片型水印
  8. 颜色检测法 - 适合灰色半透明文字水印
  9. 透明度检测法
  10. 强力去除 - 适合顽固水印
  11. 图像处理法 - 像素级处理
  12. 页面重建法 - 终极方案，可能丢失格式

【使用示例】

方法1：交互模式（推荐）
  直接双击运行exe文件，按提示操作

方法2：命令行模式
  文档水印去除工具.exe -i input.pdf
  文档水印去除工具.exe -i input.pdf -m stream
  文档水印去除工具.exe -i input.docx -o output.docx
  文档水印去除工具.exe -b ./input_dir ./output_dir

方法3：拖放文件
  将PDF或Word文件拖放到exe文件上

【注意事项】
1. 处理前建议备份原始文件
2. 处理后的文件会添加"_no_watermark"后缀
3. 推荐使用"自动检测"方法，程序会智能选择最佳策略
4. 仅支持.docx格式，不支持.doc格式
""")
    print("✓ 创建: 使用说明.txt")
    
    # 确保示例目录存在
    example_dir = os.path.join(dist_package_dir, '示例文件')
    os.makedirs(example_dir, exist_ok=True)
    
    # 创建说明文件
    with open(os.path.join(example_dir, '将文件放到这里.txt'), 'w', encoding='utf-8') as f:
        f.write("将要去除水印的文件放到此目录，然后运行程序选择批量处理模式\n")
    
    print(f"\n✓ 分发包已创建: {os.path.abspath(dist_package_dir)}")


def main():
    """主函数"""
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║             打包工具 - 文档水印去除工具 v2.0               ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    # 检查PyInstaller
    if not check_pyinstaller():
        print("PyInstaller未安装，正在安装...")
        install_pyinstaller()
    
    # 清理旧的构建
    print("\n清理旧的构建文件...")
    clean_build_dirs()
    
    # 打包
    if build_executable():
        create_distribution_package()
        
        print("\n" + "=" * 60)
        print("✓ 打包流程完成!")
        print("=" * 60)
    else:
        print("\n✗ 打包失败，请检查错误信息")


if __name__ == '__main__':
    main()
