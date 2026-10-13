# -*- coding: utf-8 -*-
"""
知识库扫描规则（单一事实来源）。

被 ingest_kb_bulk.py 与 smart_ingest.py 共用，避免两处逻辑漂移。

两条关键规则（都来自实测踩坑）：
1. **排除词里绝不能有"打印"**。《2010-2024英语一真题一键打印版》53MB、
   《高数刷题本（打印版）》都是宝贵真题/题本，只是文件名带"打印"二字。
   按"打印"过滤会误杀 200MB 级资产。
2. **`_trash` 隔离区必须跳过**。cleanup_lowvalue.py 把已判定的低价值文件
   移入 knowledge_base/_trash/<日期>/，若扫描时不过滤，垃圾会被重新入库。

命名相同但内容差异极大的情况按内容判定，不按文件名：
  「艾宾浩斯抗遗忘打卡」→ 实测含 862/141/475 个真实英文词，保留
  「词汇闪过抗遗忘时间规划打卡表」→ 实测 0 个词汇，纯广告页，删
故统一按 EXCLUDE_KEEP 放行，再由入库时的 validate_for_ingest 按内容把关。
"""
import os

# 缓存区 / 隔离区：绝不扫描
SKIP_DIRS = {"documents", "chunks", "meta", "inbox", ".git", "_trash"}

# 硬保护：文件名带排除词但本体是高价值资产，绝不能排除
EXCLUDE_KEEP = (
    "红宝书", "艾宾浩斯抗遗忘打卡", "抗遗忘", "词汇闪过",
)

# 低价值排除词（精确垃圾词）
EXCLUDE_KW = (
    "答题卡", "答题纸", "答题版", "机读卡", "填涂卡",
    "签到表", "进度表", "计划表", "倒计时",
    "课程表", "课表",
    "打印店", "彩印", "在线打印",
    "封面及目录", "封面.ppt",
    "二维码", "扫码", "客服", "加微信", "公众号",
)

DOC_EXT = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".md", ".txt",
           ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def skip_file(name: str) -> bool:
    """返回 True 表示该文件应被排除。"""
    if any(k in name for k in EXCLUDE_KEEP):
        return False
    return any(k in name for k in EXCLUDE_KW)


def walk_files(root: str, allowed_ext=None):
    """遍历知识库，产出待入库文件路径（已应用排除与目录跳过规则）。"""
    exts = allowed_ext if allowed_ext is not None else DOC_EXT
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if os.path.splitext(f)[1].lower() not in exts:
                continue
            if skip_file(f):
                continue
            yield os.path.join(dirpath, f)
