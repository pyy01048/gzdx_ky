# -*- coding: utf-8 -*-
"""院校公告采集栈（爬取 → 抽取 → 分类 → 去重 → 入库）。

分层
----
- :mod:`services.crawl.urls`       URL 规范化、内容哈希、SimHash 指纹
- :mod:`services.crawl.classifier` 公告类型规则分类（规则优先，LLM 兜底接口预留）
- :mod:`services.crawl.fetcher`    带 robots / 限速 / 重试 / 编码兜底的单域串行抓取
- :mod:`services.crawl.extractor`  正文抽取（trafilatura → readability → 内置兜底）
- :mod:`services.crawl.queue`      任务状态机（pending/running/done/failed/dead）
- :mod:`services.crawl.runner`     把上面几段串成一次采集批次

持久化（``crawl_jobs`` / ``crawl_pages`` / ``crawl_dead_letters``）由别的同事在
``models.py`` 里定义，本包**不重复定义**这些模型：:mod:`services.crawl.queue`
只依赖一个可替换的 store 接口，PostgreSQL 适配层落地前用内存 / SQLite store 顶上。

导入约定：本包被导入时**不**拉起 trafilatura / readability 等重依赖，
只有真正调用 :func:`services.crawl.extractor.extract` 时才按需 import。
"""

from __future__ import annotations

__all__ = [
    "canonicalize_url",
    "content_hash",
    "simhash64",
    "hamming_distance",
    "classify_notice",
    "NOTICE_TYPES",
    "PoliteFetcher",
    "FetchResult",
    "extract",
    "Extracted",
    "CrawlQueue",
]

_LAZY = {
    "canonicalize_url": "services.crawl.urls",
    "content_hash": "services.crawl.urls",
    "simhash64": "services.crawl.urls",
    "hamming_distance": "services.crawl.urls",
    "classify_notice": "services.crawl.classifier",
    "NOTICE_TYPES": "services.crawl.classifier",
    "PoliteFetcher": "services.crawl.fetcher",
    "FetchResult": "services.crawl.fetcher",
    "extract": "services.crawl.extractor",
    "Extracted": "services.crawl.extractor",
    "CrawlQueue": "services.crawl.queue",
}


def __getattr__(name: str):  # pragma: no cover - 惰性导入的薄封装
    mod_name = _LAZY.get(name)
    if not mod_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(mod_name), name)


def __dir__():  # pragma: no cover
    return sorted(set(list(globals()) + list(_LAZY)))
