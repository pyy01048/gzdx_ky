"""``scripts/startup_manager.py`` 纯逻辑单测。

为什么全都要能离线跑
--------------------
启动管家是**唯一一个在你最需要它的时候一定是坏的组件**：数据库挂了、
环境脏了、依赖缺了。如果它的测试自己也要连库，那就永远验证不到
"库挂了还能把库救回来"这条路径。所以判定逻辑全部做成纯函数 + 临时文件，
零数据库依赖。
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import startup_manager as sm  # noqa: E402


class TestParsePidFile(unittest.TestCase):
    def _write(self, tmp_path: Path, text: str | None) -> str:
        p = tmp_path / "postmaster.pid"
        if text is None:
            return str(p)
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_reads_first_line_pid(self):
        p = self._write(Path(__file__).parent, "40668\nD:/pgsql/data\n5432\n")
        try:
            self.assertEqual(sm.parse_pid_file(p), 40668)
        finally:
            os.unlink(p)

    def test_missing_file_returns_none(self):
        self.assertIsNone(sm.parse_pid_file("does/not/exist/postmaster.pid"))

    def test_empty_file_returns_none(self):
        p = Path(__file__).parent / "_tmp_empty.pid"
        p.write_text("", encoding="utf-8")
        try:
            self.assertIsNone(sm.parse_pid_file(p))
        finally:
            os.unlink(p)

    def test_garbage_first_line_returns_none(self):
        p = Path(__file__).parent / "_tmp_garbage.pid"
        p.write_text("not-a-number\n123\n", encoding="utf-8")
        try:
            self.assertIsNone(sm.parse_pid_file(p))
        finally:
            os.unlink(p)


class TestPidAlive(unittest.TestCase):
    def test_invalid_pid_is_dead(self):
        for pid in (None, 0, -1):
            self.assertFalse(sm.pid_alive(pid))

    def test_current_process_is_alive(self):
        self.assertTrue(sm.pid_alive(os.getpid()))


class TestStalePidFile(unittest.TestCase):
    """崩溃残留 pid 是 .bat 时代最常踩的坑，必须锁死。"""

    def test_no_file_is_not_stale(self):
        self.assertFalse(sm.is_stale_pid_file("no/such/file.pid"))

    def test_dead_pid_is_stale_and_removable(self):
        p = Path(__file__).parent / "_tmp_dead.pid"
        # 用一个几乎不可能存在的 PID
        p.write_text("999999\n", encoding="utf-8")
        try:
            if sm.pid_alive(999999):  # pragma: no cover - 极端巧合
                self.skipTest("PID 999999 居然活着，无法构造陈旧场景")
            self.assertTrue(sm.is_stale_pid_file(p))
            self.assertTrue(sm.remove_stale_pid(p))
            self.assertFalse(p.exists())
        finally:
            if p.exists():
                os.unlink(p)

    def test_live_pid_is_never_touched(self):
        """活着的服务绝不能被误删 pid 文件 —— 那是数据损坏级别的失误。"""
        p = Path(__file__).parent / "_tmp_live.pid"
        p.write_text(f"{os.getpid()}\n", encoding="utf-8")
        try:
            self.assertFalse(sm.is_stale_pid_file(p))
            self.assertFalse(sm.remove_stale_pid(p))
            self.assertTrue(p.exists(), "活进程的 pid 文件被删了！")
        finally:
            if p.exists():
                os.unlink(p)


class TestParseEnvKv(unittest.TestCase):
    def test_basic_and_comments(self):
        text = "# comment\nPG_HOST=127.0.0.1\n\nPG_PORT=5432\nexport PG_DB=kk\n"
        got = sm.parse_env_kv(text)
        self.assertEqual(got["PG_HOST"], "127.0.0.1")
        self.assertEqual(got["PG_PORT"], "5432")
        self.assertEqual(got["PG_DB"], "kk")
        self.assertNotIn("comment", got)

    def test_quotes_stripped(self):
        got = sm.parse_env_kv('PG_PASSWORD="abc"\nPG_USER=\'u\'')
        self.assertEqual(got["PG_PASSWORD"], "abc")
        self.assertEqual(got["PG_USER"], "u")

    def test_empty_input(self):
        self.assertEqual(sm.parse_env_kv(""), {})


class TestPickPython(unittest.TestCase):
    def test_prefers_existing_path(self):
        got = sm.pick_python(["nope/python.exe", sys.executable])
        self.assertEqual(got, sys.executable)

    def test_none_when_all_missing(self):
        self.assertIsNone(sm.pick_python(["x:\\no\\python.exe"]))

    def test_bare_python_alias_resolves_to_current(self):
        self.assertEqual(sm.pick_python(["python"]), sys.executable)


class TestReport(unittest.TestCase):
    def test_ok_only_when_all_steps_pass(self):
        r = sm.Report()
        r.add("a", True)
        self.assertTrue(r.ok)
        r.add("b", False)
        self.assertFalse(r.ok)
        payload = json.loads(json.dumps(r.to_dict()))
        self.assertEqual(len(payload["steps"]), 2)


class TestPortOpen(unittest.TestCase):
    def test_closed_port_is_false(self):
        # 选一个几乎肯定没人监听的高端口
        self.assertFalse(sm.port_open("127.0.0.1", 59999, timeout=0.3))


if __name__ == "__main__":
    unittest.main(verbosity=2)
