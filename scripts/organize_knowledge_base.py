# -*- coding: utf-8 -*-
"""知识库自动化整理脚本。

功能：
1. 按学科分类文件到子文件夹（数学/英语/政治/数电/模电/专业课/其他）
2. 检测重复文件（同名 + MD5校验）
3. 统计各学科文件数量和大小
4. 生成整理报告

用法：python scripts/organize_knowledge_base.py [--dry-run] [--dedup]
"""
import os
import re
import shutil
import hashlib
from pathlib import Path
from collections import defaultdict
from typing import Optional

# 源目录和目标目录
SOURCE_DIR = Path(r"D:\平台\knowledge_base")
TARGET_DIR = SOURCE_DIR  # 原地整理，创建子文件夹

# 学科分类规则（关键词匹配，优先级从高到低）
SUBJECT_RULES = [
    # 数学相关
    {
        "name": "数学",
        "keywords": ["高数", "线代", "概统", "概率论", "数学一", "数学二", "数学三",
                     "张宇", "汤家凤", "李永乐", "武忠祥", "猕猴桃高分笔记"],
        "subfolders": {"高等数学": ["高数", "猕猴桃高分笔记-高数"],
                       "线性代数": ["线代", "猕猴桃高分笔记-线代"],
                       "概率统计": ["概统", "概率论", "猕猴桃高分笔记-概率论"]},
    },
    # 英语相关
    {
        "name": "英语",
        "keywords": ["英语", "考研英语", "词汇", "单词", "刘晓艳", "红宝书",
                     "长难句", "语法", "阅读", "完型", "翻译", "写作",
                     "cloze", "完形填空"],
        "subfolders": {"词汇": ["词汇", "单词", "刘晓艳", "红宝书"],
                       "语法长难句": ["长难句", "语法", "88句"],
                       "阅读": ["阅读"],
                       "真题": ["考研英语.*真题"]},
    },
    # 政治相关
    {
        "name": "政治",
        "keywords": ["政治", "肖秀荣", "徐涛", "腿姐", "马原", "毛概",
                     "思修", "史纲", "形势与政策"],
        "subfolders": {},
    },
    # 数字电子技术（数电）
    {
        "name": "数字电子技术",
        "keywords": ["数电", "数字电子", "数字部分", "阎石", "康华光.*数字",
                     "电子技术基础.*数字"],
        "subfolders": {"教材": ["教材", "第[0-9]+版[^学]"],
                       "辅导解答": ["辅导", "解答", "答案", "习题全解"],
                       "课件讲义": ["课件", "讲义", "教案", "复习提纲", "知识点总结", "章节总结"],
                       "真题试卷": ["真题", "试题", "试卷", "考试卷", "模拟", "题库", "章节题库"],
                       "笔记": ["笔记"]},
    },
    # 模拟电子技术（模电）
    {
        "name": "模拟电子技术",
        "keywords": ["模电", "模拟电子", "模拟部分", "康华光.*模拟",
                     "电子技术基础.*模拟"],
        "subfolders": {"教材": ["教材", "第[0-9]+版[^学]"],
                       "辅导解答": ["辅导", "解答", "答案", "习题全解"],
                       "课件讲义": ["课件", "讲义", "教案", "复习提纲", "知识点总结"],
                       "真题试卷": ["真题", "试题", "试卷", "考试卷", "模拟"],
                       "笔记": ["笔记"]},
    },
    # 电子技术基础（通用，不含数字/模拟关键词）
    {
        "name": "电子技术基础",
        "keywords": ["电子技术基础"],
        "subfolders": {"教材": ["虞文鹏", "霍亮生", "第[0-9]+版"],
                       "辅导解答": ["答案", "解析"],
                       "课件讲义": ["知识点", "考点", "总结归纳"],
                       "真题试卷": ["考试卷", "测试题"],
                       "笔记": []},
    },
    # 专业课 - 贵州大学834真题
    {
        "name": "专业课-贵大834",
        "keywords": ["贵大", "贵州大学", "834"],
        "subfolders": {"真题": ["真题"],
                       "答案": ["答案"]},
    },
    # 其他专业课（电子线路等）
    {
        "name": "专业课-其他",
        "keywords": ["电子线路", "考试大纲", "考点", "数据结构", "操作系统",
                     "计算机", "408", "通信", "信号", "自控", "自动控制",
                     "电路", "马原", "思修", "毛概", "史纲", "新思想",
                     "武忠祥", "张宇", "丁玉美", "严蔚敏", "同济"],
        "subfolders": {"数学辅导": ["武忠祥", "张宇", "同济.*高等数学", "同济.*线性代数"],
                       "计算机专业课": ["数据结构", "操作系统", "计算机", "408"],
                       "通信/信号": ["通信", "信号", "丁玉美"],
                       "自动控制": ["自控", "自动控制", "电路"],
                       "政治": ["马原", "思修", "毛概", "史纲", "新思想"]},
    },
]

# 未匹配文件的默认分类
DEFAULT_SUBJECT = "未分类"


def classify_file(filename: str) -> tuple[str, Optional[str]]:
    """根据文件名判断学科和子文件夹。

    Returns:
        (subject_name, subfolder_name or None)
    """
    fname_lower = filename.lower()

    for rule in SUBJECT_RULES:
        # 检查是否匹配该学科的关键词
        matched = False
        for kw in rule["keywords"]:
            if re.search(kw, fname_lower):
                matched = True
                break

        if not matched:
            continue

        subject = rule["name"]

        # 尝试匹配子文件夹
        if rule.get("subfolders"):
            for subfolder, patterns in rule["subfolders"].items():
                for pattern in patterns:
                    if re.search(pattern, fname_lower):
                        return subject, subfolder

        # 没有匹配到子文件夹，返回学科名
        return subject, None

    return DEFAULT_SUBJECT, None


def compute_md5(filepath: Path, chunk_size: int = 8192) -> str:
    """计算文件MD5哈希值（用于去重）"""
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def find_duplicates(files: list[Path]) -> dict[str, list[Path]]:
    """查找重复文件（相同MD5）"""
    md5_map = defaultdict(list)
    for f in files:
        try:
            md5 = compute_md5(f)
            md5_map[md5].append(f)
        except (OSError, PermissionError) as e:
            print(f"  ⚠️ 无法读取 {f.name}: {e}")

    # 只保留有重复的
    return {md5: paths for md5, paths in md5_map.items() if len(paths) > 1}


def organize_knowledge_base(dry_run: bool = False, dedup: bool = False) -> dict:
    """执行知识库整理。

    Args:
        dry_run: True时只预览不实际移动文件
        dedup: True时检测并标记重复文件

    Returns:
        整理统计报告
    """
    print("=" * 70)
    print("📚 知识库自动化整理工具")
    print("=" * 70)
    print(f"源目录: {SOURCE_DIR}")
    print(f"模式: {'预览模式（不移动文件）' if dry_run else '实际整理'}")
    print()

    # 获取所有文件（递归扫描，但跳过已整理的学科子目录）
    SKIP_DIRS = {"数字电子技术", "模拟电子技术", "数学", "英语", "政治", 
                 "专业课-贵大834", "专业课-其他", "电子技术基础", "未分类"}
    
    all_files = []
    for f in SOURCE_DIR.rglob("*"):
        if not f.is_file():
            continue
        # 跳过已在目标学科目录中的文件
        rel = f.relative_to(SOURCE_DIR)
        if rel.parts[0] in SKIP_DIRS:
            continue
        all_files.append(f)
    
    print(f"发现 {len(all_files)} 个待整理文件\n")

    # 分类统计
    stats = defaultdict(lambda: {"count": 0, "size": 0, "files": [], "subfolders": defaultdict(list)})
    uncategorized = []

    for filepath in sorted(all_files):
        subject, subfolder = classify_file(filepath.name)
        size_mb = filepath.stat().st_size / (1024 * 1024)

        stats[subject]["count"] += 1
        stats[subject]["size"] += filepath.stat().st_size
        stats[subject]["files"].append(filepath.name)

        if subfolder:
            stats[subject]["subfolders"][subfolder].append(filepath.name)
        else:
            uncategorized.append((filepath.name, subject))

    # 打印分类结果
    print("📊 学科分类统计:")
    print("-" * 70)
    total_count = 0
    total_size = 0

    for subject in sorted(stats.keys()):
        data = stats[subject]
        size_mb = data["size"] / (1024 * 1024)
        total_count += data["count"]
        total_size += data["size"]

        print(f"\n📘 {subject}: {data['count']} 个文件 ({size_mb:.1f} MB)")

        # 显示子文件夹分布
        if data["subfolders"]:
            for subfolder, files in sorted(data["subfolders"].items()):
                print(f"   └─ 📂 {subfolder}: {len(files)} 个文件")
                for fname in files[:5]:  # 最多显示5个
                    print(f"      • {fname}")
                if len(files) > 5:
                    print(f"      ... 还有 {len(files) - 5} 个文件")

    # 显示未匹配到子文件夹的文件
    if uncategorized:
        print(f"\n️  未匹配到子文件夹的文件 ({len(uncategorized)} 个):")
        for fname, subject in uncategorized[:10]:
            print(f"   • [{subject}] {fname}")
        if len(uncategorized) > 10:
            print(f"   ... 还有 {len(uncategorized) - 10} 个文件")

    # 去重检测
    if dedup and not dry_run:
        print("\n 检测重复文件...")
        duplicates = find_duplicates(all_files)
        if duplicates:
            print(f"   发现 {len(duplicates)} 组重复文件:")
            for md5, paths in list(duplicates.items())[:5]:
                print(f"   • MD5={md5[:8]}... ({len(paths)} 个副本):")
                for p in paths:
                    size_mb = p.stat().st_size / (1024 * 1024)
                    print(f"     - {p.name} ({size_mb:.1f} MB)")
            if len(duplicates) > 5:
                print(f"   ... 还有 {len(duplicates) - 5} 组重复")
        else:
            print("   ✅ 未发现重复文件")

    # 实际移动文件
    if not dry_run:
        print("\n🚀 开始移动文件...")
        moved_count = 0
        error_count = 0

        for filepath in all_files:
            subject, subfolder = classify_file(filepath.name)

            # 构建目标路径
            target_subdir = TARGET_DIR / subject
            if subfolder:
                target_subdir = target_subdir / subfolder

            # 创建目标目录
            target_subdir.mkdir(parents=True, exist_ok=True)

            # 移动文件
            target_path = target_subdir / filepath.name
            try:
                if target_path.exists():
                    # 如果目标已存在，添加序号避免覆盖
                    base, ext = target_path.stem, target_path.suffix
                    counter = 1
                    while target_path.exists():
                        target_path = target_subdir / f"{base}_{counter}{ext}"
                        counter += 1

                shutil.move(str(filepath), str(target_path))
                moved_count += 1
            except Exception as e:
                print(f"   ❌ 移动失败 {filepath.name}: {e}")
                error_count += 1

        print(f"\n✅ 完成! 成功移动 {moved_count} 个文件, {error_count} 个失败")

    # 生成报告
    report = {
        "total_files": len(all_files),
        "total_size_mb": total_size / (1024 * 1024),
        "subjects": {
            subject: {
                "count": data["count"],
                "size_mb": data["size"] / (1024 * 1024),
                "subfolders": {k: len(v) for k, v in data["subfolders"].items()},
            }
            for subject, data in stats.items()
        },
        "uncategorized_count": len(uncategorized),
    }

    print("\n" + "=" * 70)
    print("📋 整理报告:")
    print(f"   总文件数: {report['total_files']}")
    print(f"   总大小: {report['total_size_mb']:.1f} MB ({report['total_size_mb']/1024:.2f} GB)")
    print(f"   学科分类: {len(report['subjects'])} 个")
    print(f"   未分类文件: {report['uncategorized_count']} 个")
    print("=" * 70)

    return report


if __name__ == "__main__":
    import sys

    dry_run = "--dry-run" in sys.argv
    dedup = "--dedup" in sys.argv
    auto_yes = "--yes" in sys.argv or "-y" in sys.argv

    # 先以预览模式运行
    print(">>> 预览模式（不会移动任何文件）\n")
    organize_knowledge_base(dry_run=True, dedup=True)

    if not dry_run:
        print("\n" + "=" * 70)
        if auto_yes:
            response = "yes"
            print("\n自动确认执行实际整理...\n")
        else:
            response = input("\n确认执行实际整理？(yes/no): ").strip().lower()

        if response in ("yes", "y", "是"):
            print("\n>>> 实际整理模式\n")
            organize_knowledge_base(dry_run=False, dedup=True)
        else:
            print("已取消操作。如需执行，请重新运行脚本并输入 yes。")
