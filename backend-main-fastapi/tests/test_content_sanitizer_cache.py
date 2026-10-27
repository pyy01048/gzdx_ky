"""``content_sanitizer`` 自学习词库缓存行为的单测（不连真实数据库）。

为什么值得单独测
----------------
`get_learned_patterns()` 在清洗时**每行调用一次**（一篇文档几千次）。
它一旦出错，症状非常隐蔽且昂贵：

* 旧实现把 `_LEARNED_LOADED = True` 放在 try **之前**，except 里静默吞掉异常
  → 启动那一刻数据库抖一下，**整个进程生命周期内学到的水印全部失效**，
  而且日志里一个字都没有。这正是项目血泪教训 #1 的翻版。
* 反过来如果每次都重试，一篇文档就会打几千次库。

这两个单测锁住的是两件事：**失败必须留痕**，以及**缓存必须真的生效**。
"""
from __future__ import annotations

import logging
import sys
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import services.content_sanitizer as cs  # noqa: E402


def _install_broken_db():
    """塞一个一碰就炸的假 database 模块进去（不碰真实连接）。"""
    fake = types.ModuleType("database")
    calls = {"n": 0}

    def SessionLocal():  # noqa: N802 - 对齐被替换对象的命名
        calls["n"] += 1
        raise RuntimeError("simulated DB down")

    fake.SessionLocal = SessionLocal
    real = sys.modules.get("database")
    sys.modules["database"] = fake
    return calls, real


def _restore_db(real):
    if real is None:
        sys.modules.pop("database", None)
    else:
        sys.modules["database"] = real


class TestLearnedCacheFailure(unittest.TestCase):
    def setUp(self):
        cs.invalidate_learned_cache()

    def tearDown(self):
        cs.invalidate_learned_cache()

    def test_failure_degrades_to_empty(self):
        calls, real = _install_broken_db()
        try:
            pats, frags = cs.get_learned_patterns()
        finally:
            _restore_db(real)
        self.assertEqual((pats, frags), ([], []))
        self.assertEqual(calls["n"], 1)

    def test_failure_emits_warning_not_silence(self):
        """核心：以前这里是完全静默的。"""
        calls, real = _install_broken_db()
        logger = logging.getLogger("services.content_sanitizer")
        with self.assertLogs(logger, level="WARNING") as ctx:
            try:
                cs.get_learned_patterns()
            finally:
                _restore_db(real)
        joined = "\n".join(ctx.output)
        self.assertIn("降级", joined)
        self.assertIn("simulated DB down", joined)

    def test_failure_is_not_permanently_cached(self):
        """降级后必须能恢复 —— TTL 到期就得重试，不能锁死到进程结束。"""
        calls, real = _install_broken_db()
        try:
            cs.get_learned_patterns()
            before = calls["n"]
            time.sleep(0.01)
            cs._LEARNED_TS = 0.0  # 模拟 TTL 过期
            cs.get_learned_patterns()
            self.assertEqual(calls["n"], before + 1, "TTL 过期后应重试")
        finally:
            _restore_db(real)

    def test_cache_hits_do_not_repeat_queries(self):
        """缓存命中时零查询 —— 一篇文档几千行不能打几千次库。"""
        calls, real = _install_broken_db()
        try:
            cs.get_learned_patterns()          # 首次：失败并记入降级状态
            n_after_first = calls["n"]
            for _ in range(1000):              # 后续：全部走缓存
                cs.get_learned_patterns()
            self.assertEqual(calls["n"], n_after_first)
        finally:
            _restore_db(real)

    def test_invalidate_forces_reload(self):
        calls, real = _install_broken_db()
        try:
            cs.get_learned_patterns()
            n = calls["n"]
            cs.invalidate_learned_cache()
            cs.get_learned_patterns()
            self.assertEqual(calls["n"], n + 1)
        finally:
            _restore_db(real)


class TestLearnedCacheSuccess(unittest.TestCase):
    def setUp(self):
        cs.invalidate_learned_cache()

    def tearDown(self):
        cs.invalidate_learned_cache()
        cs._LEARNED_PATTERNS, cs._LEARNED_FRAGMENTS = [], []

    def test_success_caches_phrases(self):
        real = sys.modules.get("database")
        fake = types.ModuleType("database")

        class _FakeDB:
            def execute(self, _sql):
                class _R:
                    def fetchall(self):
                        return [("内部资料",), ("请勿外传",), ("  ",)]
                return _R()

            def close(self):
                pass

        fake.SessionLocal = _FakeDB
        sys.modules["database"] = fake
        try:
            pats, frags = cs.get_learned_patterns()
        finally:
            if real is None:
                sys.modules.pop("database", None)
            else:
                sys.modules["database"] = real

        self.assertEqual(frags, ["内部资料", "请勿外传"], "空词组应被跳过")
        self.assertEqual(len(pats), 2)
        # 普通文本必须被转义后才能当正则用
        self.assertTrue(all(isinstance(p.pattern, str) for p in pats))


if __name__ == "__main__":
    unittest.main(verbosity=2)
