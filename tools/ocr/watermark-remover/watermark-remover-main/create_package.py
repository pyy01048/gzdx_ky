#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建分发包"""

import os
import shutil

print('\n' + '=' * 60)
print('创建分发包')
print('=' * 60 + '\n')

dist_package_dir = '发布包'
if os.path.exists(dist_package_dir):
    shutil.rmtree(dist_package_dir)
os.makedirs(dist_package_dir)

exe_name = '文档水印去除工具.exe'
if os.path.exists(f'dist/{exe_name}'):
    shutil.copy(f'dist/{exe_name}', dist_package_dir)
    print(f'✓ 复制: {exe_name}')

if os.path.exists('README.md'):
    shutil.copy('README.md', dist_package_dir)
    print('✓ 复制: README.md')

usage_file = os.path.join(dist_package_dir, '使用说明.txt')
with open(usage_file, 'w', encoding='utf-8') as f:
    f.write("""文档水印去除工具 - 使用说明
=====================================

【快速开始】
1. 双击运行"文档水印去除工具.exe"
2. 选择操作模式（单个文件或批量处理）
3. 按提示选择要处理的PDF或Word文件
4. 等待处理完成

【支持的格式】
  - PDF (.pdf)
  - Word (.docx)

【PDF处理方法】
  1. 自动检测（推荐）- 智能识别并去除水印
  2. 覆盖法 - 用白色矩形覆盖水印区域
  3. 文本删除法 - 删除文本型水印
  4. 图像处理法 - 处理图片型水印
  5. 预览 - 查看水印位置

【使用示例】

方法1：交互模式（推荐）
  直接双击运行exe文件，按提示操作

方法2：命令行模式
  文档水印去除工具.exe -i input.pdf
  文档水印去除工具.exe -i input.docx -o output.docx
  文档水印去除工具.exe -b ./input_dir ./output_dir

方法3：拖放文件
  将PDF或Word文件拖放到exe文件上

【注意事项】
1. 处理前建议备份原始文件
2. 处理后的文件会添加"_no_watermark"后缀
3. 某些复杂水印可能需要多次处理或手动调整
4. 仅支持.docx格式，不支持.doc格式

【技术支持】
如有问题，请查看README.md文件
""")
print('✓ 创建: 使用说明.txt')

example_dir = os.path.join(dist_package_dir, '示例文件')
os.makedirs(example_dir, exist_ok=True)

with open(os.path.join(example_dir, '将文件放到这里.txt'), 'w', encoding='utf-8') as f:
    f.write('将要去除水印的文件放到此目录，然后运行程序选择批量处理模式\n')

print(f'\n✓ 分发包已创建: {os.path.abspath(dist_package_dir)}')
print('\n' + '=' * 60)
print('打包流程完成!')
print('=' * 60)
