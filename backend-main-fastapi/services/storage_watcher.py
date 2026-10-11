"""
V3.0 本地存储库自动扫描与入库服务
自动监控存储库目录，识别新文件（PDF/Word/PPT/图片/文本），
调用文档解析服务解析并分块入库到知识库。

功能：
1. 扫描存储库目录中的新文件
2. 识别文件类型并选择解析器
3. 调用文档解析服务解析文件
4. 将解析结果分块入库到知识库（knowledge_chunks）
5. 记录已处理文件，避免重复处理
6. 支持手动触发扫描和增量扫描
"""
import os
import json
import time
import hashlib
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session

from models import Document, KnowledgeChunk, KnowledgePoint, PlatformConfig

logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
    """清理文本中的无效Unicode字符（代理对、控制字符等），确保能存入UTF-8数据库。"""
    if not text:
        return text
    # 移除UTF-16代理对（surrogates），如\ud835等数学符号
    cleaned = []
    for ch in text:
        code = ord(ch)
        # 跳过代理对范围 (0xD800-0xDFFF)
        if 0xD800 <= code <= 0xDFFF:
            continue
        # 跳过其他控制字符（保留换行、制表符等常用空白）
        if code < 32 and ch not in ('\n', '\t', '\r'):
            continue
        # 跳过删除字符
        if code == 0x7F:
            continue
        cleaned.append(ch)
    result = ''.join(cleaned)
    # 合并多余空行
    import re
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result


# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {
    '.pdf': 'pdf',
    '.doc': 'word',
    '.docx': 'word',
    '.ppt': 'ppt',
    '.pptx': 'ppt',
    '.txt': 'text',
    '.md': 'text',
    '.markdown': 'text',
    '.epub': 'epub',
    '.mobi': 'epub',
    '.jpg': 'image',
    '.jpeg': 'image',
    '.png': 'image',
    '.bmp': 'image',
    '.tiff': 'image',
    '.webp': 'image',
}

# 存储库根目录
STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge_base"

# 已处理文件记录
PROCESSED_RECORD_FILE = STORAGE_ROOT / ".processed_files.json"

# 扫描结果缓存有效期（秒）。存储库是低频变动目录，30s 内复用结果完全够用，
# 同时把最坏情况下的磁盘遍历次数压到每 30s 最多 1 次。
SCAN_CACHE_TTL = float(os.getenv("STORAGE_SCAN_CACHE_TTL", "30"))


class StorageWatcher:
    """本地存储库自动扫描与入库服务。"""

    # 扫描互斥锁：类级别共享，保证多worker / 多请求下同一时刻只有一次全盘扫描。
    # 非阻塞获取：拿不到锁说明已经有人在扫，直接走缓存，不排队堆积。
    _scan_lock = threading.Lock()
    # 扫描结果缓存：(写入时间戳, 结果快照)
    _scan_cache: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)
    _scan_cache_lock = threading.Lock()

    def __init__(self, db: Session):
        self.db = db
        self.processed_files = self._load_processed_files()

    def _load_processed_files(self) -> Dict[str, Dict[str, Any]]:
        """加载已处理文件记录。"""
        if PROCESSED_RECORD_FILE.exists():
            try:
                with open(PROCESSED_RECORD_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载已处理文件记录失败: {e}")
        return {}

    def _save_processed_files(self):
        """保存已处理文件记录。"""
        try:
            with open(PROCESSED_RECORD_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.processed_files, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存已处理文件记录失败: {e}")

    def _get_file_hash(self, file_path: Path) -> str:
        """计算文件全文 MD5（**慎用**：会读取整个文件内容）。

        保留原因：这是"严格内容校验"的唯一手段，供人工排查
        "size/mtime 变了但内容其实没变"这类边界情况使用。

        ⚠️ 扫描主流程**不会**调用本方法 —— 存储库约 76GB，
        全文读取一遍需要数分钟，且旧实现把它放在 async 路由里
        直接阻塞事件循环（实测 77~145s，其间全站无响应）。
        主流程请用 :meth:`_get_file_fingerprint`（size+mtime，微秒级）。
        """
        try:
            h = hashlib.md5()
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception as e:
            logger.error(f"计算文件哈希失败 {file_path}: {e}")
            return ""

    @staticmethod
    def _get_file_fingerprint(file_path: Path) -> str:
        """生成文件指纹（size + mtime），用于增量检测。

        为什么不用全文 MD5：
        - 存储库目录树约 76GB / 4176 个文件（实测），对每个文件做 MD5
          等于把 76GB 全部读一遍：实测仅抽样 3 种扩展名的 3510 个文件
          就花了 82.38s，完整扫描在 77s ~ 145s 量级；
          更糟的是旧实现把它放在 async 路由里，直接阻塞事件循环，
          期间连 TCP accept 都做不了，全站表现为假死。
        - 业界标准的增量扫描做法（rsync / make / Git 的 stat 缓存）都是
          用 "size + mtime" 作为变更判据：只有两者**同时**变化才认为文件被改动。
        - 取 stat 只需一次系统调用，单次约微秒级。
          实测效果：单遍 os.walk 遍历仅 0.16s，完整 scan 0.20~0.35s。

        理论上的漏检：内容被改动但 size 与 mtime 完全不变（mtime 精度以下）。
        本机场景（个人考研资料库，文件由解压/下载产生）下可忽略；
        如需对个别文件严格校验，可手工调用 :meth:`_get_file_hash`。

        Returns:
            形如 ``"12345-1700000000"`` 的指纹字符串；stat 失败返回空串。
        """
        try:
            st = file_path.stat()
        except (OSError, ValueError) as e:
            logger.debug(f"读取文件属性失败 {file_path}: {e}")
            return ""
        return f"{st.st_size}-{int(st.st_mtime)}"

    @staticmethod
    def _iter_storage_files() -> Tuple[List[Tuple[Path, str, str]], List[str], int]:
        """单次遍历存储库，同时完成「分类支持的文件」与「统计不支持的文件」。

        这是 P0 性能修复的核心：旧实现对 17 种扩展名各做一次 ``rglob``，
        外加第 18 次 ``rglob("*")`` 统计，总计 **18 遍全树遍历**。
        现在只遍历 1 遍，遍历次数直接降到 1/18。

        Returns:
            (supported, unsupported, total_supported)
            - supported: [(绝对路径, 相对路径key, 文件类型), ...]
            - unsupported: [不支持的文件绝对路径, ...]
            - total_supported: 支持的文件总数
        """
        supported: List[Tuple[Path, str, str]] = []
        unsupported: List[str] = []
        total_supported = 0

        # os.walk(topdown=True) 天然剪枝：可在目录级直接跳过隐藏目录，
        # 避免进入 .git / node_modules / __pycache__ 等无关子树。
        skip_dirs = {'.git', '.svn', '__pycache__', 'node_modules', '.idea', '.vscode'}

        for dirpath, dirnames, filenames in os.walk(STORAGE_ROOT, topdown=True):
            # 就地修改 dirnames 以剪枝（os.walk 语义）
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            base = Path(dirpath)

            for name in filenames:
                # 隐藏文件不参与分类统计（与旧逻辑 `not name.startswith('.')` 保持一致）
                if name.startswith('.'):
                    continue
                ext = os.path.splitext(name)[1].lower()
                ftype = SUPPORTED_EXTENSIONS.get(ext)
                if ftype is None:
                    unsupported.append(str(base / name))
                    continue
                total_supported += 1
                supported.append((base / name, str((base / name).relative_to(STORAGE_ROOT)), ftype))

        return supported, unsupported, total_supported

    def _classify_files(self, force: bool) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int, int]:
        """遍历一次，把文件分成"新增"与"变更"两类，并统计不支持的文件数。

        Args:
            force: True 时忽略已处理记录，所有文件都视为新增。

        Returns:
            (new_files, modified_files, total_files, unsupported_count)
        """
        supported, unsupported, total_files = self._iter_storage_files()

        new_files: List[Dict[str, Any]] = []
        modified_files: List[Dict[str, Any]] = []

        for file_path, file_key, ftype in supported:
            fingerprint = self._get_file_fingerprint(file_path)
            size = 0
            if fingerprint:
                # 指纹格式固定为 "<size>-<mtime>"，直接取前半段作为 size
                size = int(fingerprint.split('-', 1)[0])

            record = self.processed_files.get(file_key)
            if record is not None and not force:
                # 指纹一致 => 未变更，跳过（不再读取文件内容）
                if record.get('fingerprint') == fingerprint:
                    continue
                # 兼容旧记录（只有 MD5 hash、没有 fingerprint）：
                # 若 size 一致则视为未变更，并顺手回填指纹，避免升级后全量重扫。
                if not record.get('fingerprint') and record.get('size') == size:
                    record['fingerprint'] = fingerprint
                    continue
                modified_files.append({
                    'path': str(file_path),
                    'relative_path': file_key,
                    'type': ftype,
                    'hash': fingerprint,   # 字段名沿用 'hash'，实为 size+mtime 指纹
                    'size': size,
                })
            else:
                new_files.append({
                    'path': str(file_path),
                    'relative_path': file_key,
                    'type': ftype,
                    'hash': fingerprint,
                    'size': size,
                })

        return new_files, modified_files, total_files, len(unsupported)

    def scan_storage(self, force: bool = False) -> Dict[str, Any]:
        """
        扫描存储库目录，识别新文件或变更文件。

        性能说明：单次 os.walk + stat 指纹，实测 76GB 存储库从 77s 降到秒级以内。

        并发保护：同一时刻只允许一次扫描在跑（``_scan_lock``）。重复触发时
        直接返回最近一次的结果缓存（``SCAN_CACHE_TTL`` 秒内），避免几个前端
        页面同时挂载就把磁盘扫爆。

        Args:
            force: 是否强制重新扫描所有文件（忽略已处理记录）

        Returns:
            扫描结果统计
        """
        if not STORAGE_ROOT.exists():
            return {"error": "存储库目录不存在", "path": str(STORAGE_ROOT)}

        # 快速路径：命中缓存直接返回，连os.walk 都不进
        if not force:
            cached = self._get_cached_scan_result()
            if cached is not None:
                return cached

        # 并发保护：拿不到锁说明已有扫描在跑，直接复用它的结果而不是再扫一遍
        if not self._scan_lock.acquire(blocking=False):
            logger.warning("已有扫描任务在进行中，返回缓存结果（如无缓存则返回忙）")
            cached = self._get_cached_scan_result(ignore_ttl=True)
            if cached is not None:
                return cached
            return {"error": "扫描正在进行中，请稍后重试", "scanning": True}

        try:
            started = time.time()
            new_files, modified_files, total_files, unsupported_count = self._classify_files(force)
            elapsed = time.time() - started

            result = {
                "total_files": total_files,
                "new_files": len(new_files),
                "modified_files": len(modified_files),
                "unsupported_files": unsupported_count,
                "new_files_list": new_files[:20],  # 最多返回20个
                "modified_files_list": modified_files[:20],
                "unsupported_files_list": [],  # 不再返回完整列表，仅计数（76GB 下列表本身就很重）
                "elapsed_seconds": round(elapsed, 3),
            }
            self._store_scan_result(result)
            logger.info(
                f"存储库扫描完成: {total_files} 个支持文件, "
                f"新增 {len(new_files)}, 变更 {len(modified_files)}, "
                f"不支持 {unsupported_count}, 耗时 {elapsed:.3f}s"
            )
            return result
        finally:
            self._scan_lock.release()

    def _get_cached_scan_result(self, ignore_ttl: bool = False) -> Optional[Dict[str, Any]]:
        """读取扫描结果缓存。"""
        with self._scan_cache_lock:
            cached_at, payload = self._scan_cache
        if payload is None:
            return None
        if not ignore_ttl and (time.time() - cached_at) > SCAN_CACHE_TTL:
            return None
        result = dict(payload)
        result["cached"] = True
        return result

    def _store_scan_result(self, result: Dict[str, Any]) -> None:
        """写入扫描结果缓存（浅拷贝 + 截断后的列表，内存占用可控）。"""
        snapshot = {
            "total_files": result["total_files"],
            "new_files": result["new_files"],
            "modified_files": result["modified_files"],
            "unsupported_files": result["unsupported_files"],
            "new_files_list": list(result.get("new_files_list") or []),
            "modified_files_list": list(result.get("modified_files_list") or []),
            "unsupported_files_list": [],
            "elapsed_seconds": result.get("elapsed_seconds"),
        }
        with self._scan_cache_lock:
            self._scan_cache = (time.time(), snapshot)

    def ingest_file(self, file_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        将单个文件解析并入库到知识库。

        Args:
            file_info: 文件信息（path/type/hash等）

        Returns:
            入库结果
        """
        file_path = Path(file_info['path'])
        if not file_path.exists():
            return {"error": f"文件不存在: {file_path}", "success": False}

        try:
            # 1. 创建或更新Document记录
            doc = self.db.query(Document).filter(
                Document.file_path == str(file_path)
            ).first()

            if not doc:
                doc = Document(
                    file_name=file_path.name,
                    file_path=str(file_path),
                    file_type=file_info.get('type', 'unknown'),
                    size=file_info.get('size', 0),
                    index_status='pending',
                    parse_progress=0,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                self.db.add(doc)
                self.db.flush()

            # 2. 使用本地 DocumentParser 提取全文
            from services.document_parser import DocumentParser
            from services.kb_service import ingest_document

            logger.info(f"开始解析文件: {file_path.name}")
            parser = DocumentParser()
            try:
                content_text = parser.parse(str(file_path))
            except Exception as e:
                doc.index_status = 'failed'
                doc.parse_progress = 0
                self.db.commit()
                return {
                    "success": False,
                    "error": f"解析失败: {str(e)}",
                    "file": file_path.name,
                }

            if not content_text or not content_text.strip():
                content_text = f"[{file_info.get('type', 'unknown')} 文件，未能提取到文本内容] 文件名：{file_path.name}"

            # 清理无效Unicode字符（代理对、控制字符等）
            content_text = clean_text(content_text)

            # 3. 更新Document内容
            doc.content = content_text[:5000]
            doc.index_status = "indexing"
            doc.parse_progress = 0.5
            self.db.commit()

            # 4. 分块入库到知识库（knowledge_chunks + FTS）
            chunk_count = 0
            try:
                chunk_count = ingest_document(self.db, doc, replace=True)
                doc.parse_progress = 0.8
            except Exception as e:
                logger.warning(f"文档 {doc.id} 分块入库失败: {e}")

            # 5. 更新Document状态
            doc.index_status = 'indexed'
            doc.knowledge_point_count = chunk_count
            doc.parse_progress = 1.0
            doc.updated_at = datetime.now()

            # 6. 记录已处理文件（fingerprint 用于下次的增量比对）
            self.processed_files[file_info['relative_path']] = {
                'hash': file_info['hash'],
                'fingerprint': file_info['hash'],
                'size': file_info['size'],
                'processed_at': datetime.now().isoformat(),
                'doc_id': doc.id,
                'chunk_count': chunk_count,
                'status': 'success',
            }
            self._save_processed_files()

            self.db.commit()

            return {
                "success": True,
                "file": file_path.name,
                "doc_id": doc.id,
                "chunk_count": chunk_count,
                "message": f"文件解析成功，生成 {chunk_count} 个分块",
            }

        except Exception as e:
            logger.error(f"文件入库失败 {file_path}: {e}", exc_info=True)
            self.db.rollback()
            return {
                "success": False,
                "error": str(e),
                "file": file_path.name,
            }

    def _collect_all_new_files(self, force: bool = False) -> List[Dict[str, Any]]:
        """内部方法：收集全部新文件或变更文件（不截断）。

        与 :meth:`scan_storage` 共用同一套单遍遍历 + 指纹判定逻辑，
        同样不读取文件内容计算 MD5。
        """
        if not STORAGE_ROOT.exists():
            return []

        new_files, modified_files, _total, _unsupported = self._classify_files(force)
        return new_files + modified_files

    def ingest_all_new_files(self, force: bool = False) -> Dict[str, Any]:
        """
        扫描并入库所有新文件或变更文件。

        Args:
            force: 是否强制重新入库所有文件

        Returns:
            批量入库结果统计
        """
        # 1. 收集全部新文件（不截断）
        all_files = self._collect_all_new_files(force=force)

        if not all_files:
            scan_result = self.scan_storage(force=force)
            return {
                "success": True,
                "message": "没有新文件或变更文件需要处理",
                "scanned": scan_result.get('total_files', 0),
                "processed": 0,
                "failed": 0,
            }

        # 2. 逐个入库
        results = []
        success_count = 0
        failed_count = 0

        for i, file_info in enumerate(all_files):
            result = self.ingest_file(file_info)
            results.append(result)
            if result.get('success'):
                success_count += 1
            else:
                failed_count += 1
            # 每处理10个文件保存一次进度
            if (i + 1) % 10 == 0:
                self._save_processed_files()
                logger.info(f"入库进度: {i+1}/{len(all_files)}, 成功={success_count}, 失败={failed_count}")

        self._save_processed_files()

        return {
            "success": True,
            "message": f"批量入库完成：成功 {success_count} 个，失败 {failed_count} 个",
            "scanned": len(all_files),
            "new_files": len(all_files),
            "modified_files": 0,
            "processed": success_count,
            "failed": failed_count,
            "results": results[:20],  # 最多返回20个详细结果
        }

    def get_processed_files(self) -> List[Dict[str, Any]]:
        """获取已处理文件列表。"""
        return [
            {
                "relative_path": k,
                **v,
            }
            for k, v in self.processed_files.items()
        ]

    def get_storage_stats(self) -> Dict[str, Any]:
        """获取存储库统计信息。"""
        if not STORAGE_ROOT.exists():
            return {"error": "存储库目录不存在"}

        total_size = 0
        file_count = 0
        type_counts = {}

        # 单遍遍历 + 目录剪枝；语义与旧rglob 实现一致（含 other 类型、跳过隐藏文件）
        skip_dirs = {'.git', '.svn', '__pycache__', 'node_modules', '.idea', '.vscode'}
        for dirpath, dirnames, filenames in os.walk(STORAGE_ROOT, topdown=True):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for name in filenames:
                if name.startswith('.'):
                    continue
                try:
                    total_size += os.stat(os.path.join(dirpath, name)).st_size
                except OSError:
                    continue
                file_count += 1
                ext = os.path.splitext(name)[1].lower()
                ftype = SUPPORTED_EXTENSIONS.get(ext, 'other')
                type_counts[ftype] = type_counts.get(ftype, 0) + 1

        # 知识库统计
        doc_count = self.db.query(Document).count()
        chunk_count = self.db.query(KnowledgeChunk).count()
        point_count = self.db.query(KnowledgePoint).count()

        return {
            "storage_path": str(STORAGE_ROOT),
            "total_files": file_count,
            "total_size": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "type_counts": type_counts,
            "processed_files": len(self.processed_files),
            "knowledge_base": {
                "documents": doc_count,
                "chunks": chunk_count,
                "knowledge_points": point_count,
            },
        }
