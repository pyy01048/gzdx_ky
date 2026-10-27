"""Pydantic V2 迁移脚本：将 class Config 转换为 model_config = ConfigDict(...)"""

import re
from pathlib import Path

def migrate_pydantic_v2(file_path):
    """将文件中的 Pydantic V1 Config 类转换为 V2 ConfigDict"""
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    new_lines = []
    i = 0
    converted_count = 0
    
    while i < len(lines):
        line = lines[i]
        
        # 检测 class Config:
        if re.match(r'^\s+class Config:\s*$', line):
            indent = re.match(r'(\s+)', line).group(1)
            
            # 收集Config块内的所有行
            config_body = []
            j = i + 1
            while j < len(lines) and (lines[j].startswith(indent + '    ') or lines[j].strip() == ''):
                if lines[j].strip():  # 跳过空行
                    config_body.append(lines[j])
                j += 1
            
            # 解析配置项
            config_dict_items = []
            for config_line in config_body:
                match = re.match(r'\s+(\w+)\s*=\s*(.+)', config_line)
                if match:
                    key, value = match.groups()
                    # 转换常见配置
                    if key == 'orm_mode':
                        key = 'from_attributes'
                    elif key == 'allow_population_by_field_name':
                        key = 'populate_by_name'
                    config_dict_items.append(f'{key}={value.strip()}')
            
            # 生成 model_config 行
            if config_dict_items:
                config_str = ', '.join(config_dict_items)
                new_lines.append(f'{indent}model_config = ConfigDict({config_str})\n')
                converted_count += 1
            
            # 跳过原来的Config块
            i = j
        else:
            new_lines.append(line)
            i += 1
    
    # 添加 ConfigDict 导入
    content = ''.join(new_lines)
    if converted_count > 0:
        if 'from pydantic import BaseModel, Field' in content:
            content = content.replace(
                'from pydantic import BaseModel, Field',
                'from pydantic import BaseModel, ConfigDict, Field'
            )
        elif 'from pydantic import BaseModel' in content:
            content = content.replace(
                'from pydantic import BaseModel',
                'from pydantic import BaseModel, ConfigDict'
            )
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return converted_count

if __name__ == '__main__':
    files = ['schemas.py', 'routers/words.py']
    
    for file_path in files:
        path = Path(file_path)
        if path.exists():
            count = migrate_pydantic_v2(path)
            print(f'{file_path}: 转换了 {count} 个 Config 类')
        else:
            print(f'{file_path}: 文件不存在')
