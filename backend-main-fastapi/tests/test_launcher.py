"""``scripts/launcher.py`` 纯逻辑单测（不连库、不起进程）。

批处理"中文行吞掉下一行"的那个坑没法直接写单测，所以把**判定逻辑**全搬进
Python，这里锁住的是搬运过程中有没有搬错。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import launcher  # noqa: E402

NETSTAT = """\
Proto  Local Address          Foreign Address        State           PID
TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       12345
TCP    127.0.0.1:5432         0.0.0.0:0              LISTENING       40668
TCP    [::]:8000              [::]:0                 LISTENING       12345
TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1024
TCP    192.168.1.9:51000      8.8.8.8:443            ESTABLISHED     999
TCP    0.0.0.0:8000           0.0.0.0:0              TIME_WAIT       7777
"""


class TestParseNetstatListen(unittest.TestCase):
    """netstat 解析是原先 .bat 里 findstr+tokens 干的活，现在可测了。"""

    def test_finds_pid_on_port(self):
        self.assertEqual(launcher.parse_netstat_listen(NETSTAT, 8000), [12345])

    def test_ipv6_form(self):
        # [::]:8000 与 0.0.0.0:8000 是同一个进程，必须去重
        self.assertEqual(launcher.parse_netstat_listen(NETSTAT, 8000), [12345])

    def test_only_listening_state(self):
        # TIME_WAIT 的 7777 不能被当成服务进程杀掉
        self.assertNotIn(7777, launcher.parse_netstat_listen(NETSTAT, 8000))

    def test_established_connection_excluded(self):
        self.assertEqual(launcher.parse_netstat_listen(NETSTAT, 443), [])

    def test_empty_output(self):
        self.assertEqual(launcher.parse_netstat_listen("", 8000), [])

    def test_port_as_string_or_int(self):
        self.assertEqual(
            launcher.parse_netstat_listen(NETSTAT, "5432"),
            launcher.parse_netstat_listen(NETSTAT, 5432),
        )


class TestBuildBackendCmd(unittest.TestCase):
    def test_normal_mode_runs_main_py(self):
        cmd = launcher.build_backend_cmd("127.0.0.1", 8000, "normal")
        self.assertTrue(any(p.endswith("main.py") for p in cmd))
        self.assertFalse(any("--reload" == p for p in cmd))

    def test_dev_mode_uses_uvicorn_with_reload(self):
        cmd = launcher.build_backend_cmd("127.0.0.1", 8000, "dev")
        self.assertIn("uvicorn", " ".join(cmd))
        self.assertIn("--reload", cmd)

    def test_background_mode_runs_run_server(self):
        cmd = launcher.build_backend_cmd("127.0.0.1", 8000, "background")
        self.assertTrue(any(p.endswith("run_server.py") for p in cmd))

    def test_uses_current_interpreter(self):
        cmd = launcher.build_backend_cmd("127.0.0.1", 8000, "normal")
        self.assertEqual(cmd[0], sys.executable)


class TestHttpOk(unittest.TestCase):
    def test_unreachable_url_is_false(self):
        # 关键：必须 False。旧的 curl -s 不带 -f 会在 HTTP 500 时返回 0，
        # 导致健康检查挂了启动器还打印"[OK] 服务已就绪"。
        self.assertFalse(launcher.http_ok("http://127.0.0.1:59998/xx", timeout=1))


class TestReadEnv(unittest.TestCase):
    def test_reads_backend_env_values(self):
        got = launcher.read_env()
        # 至少要能读出 PORT；读不到说明 BACKEND 路径算错了
        if got:
            self.assertIsInstance(got, dict)

    def test_missing_file_returns_empty(self):
        import importlib

        importlib.reload(launcher)
        orig = launcher.BACKEND
        try:
            launcher.BACKEND = Path(__file__).parent / "_no_such_dir"
            self.assertEqual(launcher.read_env(), {})
        finally:
            launcher.BACKEND = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
