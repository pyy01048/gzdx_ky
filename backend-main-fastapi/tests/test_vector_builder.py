# -*- coding: utf-8 -*-
"""向量灌库核心（services/vector_builder.py）单元测试。

背景：这段逻辑原先只在 pipeline/build_vectors.py（CLI）里，
而 /api/ai/build-embeddings 端点维护了另一套写 `knowledge_chunks_vec`
（PG 下不存在的表）+ `INSERT OR REPLACE`（PG 语法错误）的实现 ——
**用户在界面上点"重建向量"必定失败**。抽到 service 后两条路同源。

本文件用**假连接**测纯逻辑，不依赖数据库/模型（保持秒级反馈）：
  - 文本清洗与归一化的数值行为
  - pgvector 字面量格式
  - 过短文本跳过
  - 写库失败必须 rollback（PG 事务 aborted 的连锁坑）
"""
from __future__ import annotations

import numpy as np
import pytest

from services.vector_builder import (
    DIM,
    argmin_normalize,
    build_pg_vectors,
    clean_text,
    vec_literal,
)


# --------------------------------------------------------------------------- #
# 纯函数
# --------------------------------------------------------------------------- #
class TestCleanText:
    def test_压缩空白并去控制字符(self):
        assert clean_text("  逻辑\t代数\n\n基本  运算  ") == "逻辑 代数 基本 运算"

    def test_NUL_替换为空格(self):
        assert "\x00" not in clean_text("a\x00b")

    def test_超长截断到_MAX_CHARS(self):
        out = clean_text("字" * 1000)
        assert len(out) == 400

    def test_空输入返回空串(self):
        assert clean_text("") == ""
        assert clean_text(None) == ""


class TestArgMinNormalize:
    def test_一维减最小值(self):
        v = argmin_normalize(np.array([3.0, 1.0, 5.0], dtype=np.float32))
        assert v.min() == pytest.approx(0.0)
        assert v.max() == pytest.approx(4.0)

    def test_全零向量不炸(self):
        v = argmin_normalize(np.zeros(4, dtype=np.float32))
        assert np.allclose(v, 0)

    def test_二维按行归一(self):
        m = np.array([[1.0, 3.0], [5.0, 2.0]], dtype=np.float32)
        out = argmin_normalize(m)
        # 按**行**减最小值：行0 min=1 → [0,2]；行1 min=2 → [3,0]
        assert list(out[:, 0]) == pytest.approx([0.0, 3.0])
        assert list(out[:, 1]) == pytest.approx([2.0, 0.0])

    def test_输出保持_float32(self):
        v = argmin_normalize(np.array([1.0, 2.0]))
        assert v.dtype == np.float32


class TestVecLiteral:
    def test_格式为方括号逗号分隔(self):
        s = vec_literal(np.array([0.5, -1.0], dtype=np.float32))
        assert s.startswith("[") and s.endswith("]")
        assert "," in s

    def test_维度正确(self):
        s = vec_literal(np.zeros(DIM, dtype=np.float32))
        assert len(s.strip("[]").split(",")) == DIM


# --------------------------------------------------------------------------- #
# 假连接：只记录调用，不连库
# --------------------------------------------------------------------------- #
class _FakeCursor:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.owner.executed.append((sql, params))
        return self

    def executemany(self, sql, payload):
        if self.owner.fail_upsert:
            raise RuntimeError("simulated write failure")
        self.owner.upserts.append((sql, list(payload)))
        return self

    def fetchall(self):
        return self.owner.pending


class _FakeConn:
    def __init__(self, pending, fail_upsert=False):
        self.pending = pending
        self.fail_upsert = fail_upsert
        self.executed = []
        self.upserts = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _embed(texts):
    """假 embedding：按文本长度造可区分的向量，不加载模型。"""
    return [np.full(DIM, float(len(t) % 7) + 1.0, dtype=np.float32) for t in texts]


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
class TestBuildPgVectors:
    def test_空待处理直接返回(self):
        conn = _FakeConn(pending=[])
        res = build_pg_vectors(conn, _embed)
        assert res["total"] == 0
        assert res["inserted"] == 0
        assert conn.upserts == []

    def test_正常批次写入并提交(self):
        conn = _FakeConn(pending=[
            (1, 10, 100, "逻辑代数的基本运算"),
            (2, 10, 100, "卡诺图化简的依据"),
        ])
        res = build_pg_vectors(conn, _embed, batch=10)
        assert res["inserted"] == 2
        assert res["failed"] == 0
        assert conn.commits == 1
        sql, payload = conn.upserts[0]
        # 双写：embedding(bytea) 与 embedding_f32(vector) 必须都在
        assert "embedding" in sql and "embedding_f32" in sql
        assert "ON CONFLICT (chunk_id) DO UPDATE" in sql

    def test_过短文本被跳过且不写库(self):
        conn = _FakeConn(pending=[
            (1, 10, 100, "abc"),          # 3 字符 < 5 → 跳过
            (2, 10, 100, "有效文本内容"),
        ])
        res = build_pg_vectors(conn, _embed, batch=10)
        assert res["skipped"] == 1
        assert res["inserted"] == 1

    def test_写库失败必须_rollback(self):
        """PG 里失败会把事务打成 aborted —— 不 rollback 后续批次全废。"""
        conn = _FakeConn(pending=[(1, 10, 100, "有效文本内容")], fail_upsert=True)
        res = build_pg_vectors(conn, _embed, batch=10)
        assert res["failed"] == 1
        assert res["inserted"] == 0
        assert conn.rollbacks == 1, "写库失败后必须 rollback，否则事务 aborted"

    def test_推理异常不中断整批(self):
        def boom(texts):
            raise RuntimeError("model down")

        conn = _FakeConn(pending=[(1, 10, 100, "有效文本内容")])
        res = build_pg_vectors(conn, boom, batch=10)
        assert res["failed"] == 1
        assert res["inserted"] == 0

    def test_向量数量不匹配计为失败(self):
        def half(texts):
            return [np.zeros(DIM, dtype=np.float32)]  # 少返回

        # 注意：文本必须 >=5 字符，否则会先被"过短跳过"规则吃掉，
        # 走不到"数量不匹配"这条分支（实测踩过）
        conn = _FakeConn(pending=[
            (1, 10, 100, "第一段有效文本"),
            (2, 10, 100, "第二段有效文本"),
        ])
        res = build_pg_vectors(conn, half, batch=10)
        assert res["failed"] == 2
        assert res["inserted"] == 0

    def test_进度回调被调用(self):
        seen = []
        conn = _FakeConn(pending=[(1, 10, 100, "有效文本内容")])
        build_pg_vectors(conn, _embed, batch=10,
                         on_progress=lambda d, t: seen.append((d, t)))
        assert seen and seen[-1][1] == 1
