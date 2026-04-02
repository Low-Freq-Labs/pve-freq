"""Tests for Phase 4 — The Eyes: Observability + Security (WS10-11).

Covers: Module imports, CLI registration, metrics parsing, monitor CRUD,
        FIM hash parsing, vuln scan structure.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import dataclass
from unittest.mock import MagicMock
from io import StringIO
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class MockHost:
    ip: str
    label: str
    htype: str
    groups: str = ""


class MockConfig:
    def __init__(self, tmpdir=None):
        self.conf_dir = tmpdir or tempfile.mkdtemp()
        self.hosts = [MockHost("10.0.0.1", "test", "linux")]
        self.ssh_key_path = "/tmp/test"
        self.ssh_connect_timeout = 5


# --- Metrics ---

class TestMetricsParser(unittest.TestCase):
    def test_parse_metrics(self):
        from freq.modules.metrics import _parse_metrics
        text = "CPU:45\nMEM:1024/4096\nDISK:23%\nLOAD:0.5 0.3 0.1\nUP:12345.67"
        result = _parse_metrics(text)
        self.assertEqual(result["cpu"], 45)
        self.assertEqual(result["memory"], "1024/4096")
        self.assertEqual(result["disk"], "23%")

    def test_parse_empty(self):
        from freq.modules.metrics import _parse_metrics
        self.assertEqual(_parse_metrics(""), {})


class TestMetricsStorage(unittest.TestCase):
    def test_save_and_load(self):
        from freq.modules.metrics import _save_snapshot, _load_snapshots
        cfg = MockConfig(tempfile.mkdtemp())
        _save_snapshot(cfg, "test", {"cpu": 50, "timestamp": "2026-04-01"})
        snaps = _load_snapshots(cfg, "test")
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["cpu"], 50)


# --- Monitors ---

class TestMonitorCRUD(unittest.TestCase):
    def setUp(self):
        self.cfg = MockConfig(tempfile.mkdtemp())

    def test_add_monitor(self):
        from freq.modules.synthetic_monitors import cmd_monitor_add, _load_checks
        args = MagicMock()
        args.name = "prod-web"
        args.type = "http"
        args.target = "https://example.com"
        args.interval = "5m"
        buf = StringIO()
        with redirect_stdout(buf):
            rc = cmd_monitor_add(self.cfg, None, args)
        self.assertEqual(rc, 0)
        checks = _load_checks(self.cfg)
        self.assertEqual(len(checks["checks"]), 1)

    def test_remove_monitor(self):
        from freq.modules.synthetic_monitors import cmd_monitor_add, cmd_monitor_remove, _load_checks
        args = MagicMock()
        args.name = "test"
        args.type = "http"
        args.target = "https://test.com"
        args.interval = "5m"
        buf = StringIO()
        with redirect_stdout(buf):
            cmd_monitor_add(self.cfg, None, args)
        args2 = MagicMock()
        args2.name = "test"
        with redirect_stdout(buf):
            rc = cmd_monitor_remove(self.cfg, None, args2)
        self.assertEqual(rc, 0)
        self.assertEqual(len(_load_checks(self.cfg)["checks"]), 0)

    def test_duplicate_fails(self):
        from freq.modules.synthetic_monitors import cmd_monitor_add
        args = MagicMock()
        args.name = "dup"
        args.type = "http"
        args.target = "https://dup.com"
        args.interval = "5m"
        buf = StringIO()
        with redirect_stdout(buf):
            cmd_monitor_add(self.cfg, None, args)
            rc = cmd_monitor_add(self.cfg, None, args)
        self.assertEqual(rc, 1)


# --- FIM ---

class TestFIMHashParser(unittest.TestCase):
    def test_parse_hashes(self):
        from freq.modules.fim import _parse_hashes
        text = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  /etc/passwd\na7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a  /etc/shadow"
        result = _parse_hashes(text)
        self.assertEqual(len(result), 2)
        self.assertIn("/etc/passwd", result)
        self.assertIn("/etc/shadow", result)

    def test_parse_empty(self):
        from freq.modules.fim import _parse_hashes
        self.assertEqual(_parse_hashes(""), {})


# --- Module Imports ---

class TestPhase4Imports(unittest.TestCase):
    def test_metrics(self):
        from freq.modules.metrics import cmd_metrics_collect, cmd_metrics_show, cmd_metrics_top
        self.assertTrue(callable(cmd_metrics_collect))

    def test_monitors(self):
        from freq.modules.synthetic_monitors import cmd_monitor_list, cmd_monitor_add, cmd_monitor_run, cmd_monitor_remove
        self.assertTrue(callable(cmd_monitor_list))

    def test_vuln(self):
        from freq.modules.vuln import cmd_vuln_scan, cmd_vuln_results
        self.assertTrue(callable(cmd_vuln_scan))

    def test_fim(self):
        from freq.modules.fim import cmd_fim_baseline, cmd_fim_check, cmd_fim_status
        self.assertTrue(callable(cmd_fim_baseline))


# --- CLI Registration ---

class TestPhase4CLI(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _parse(self, args_str):
        return self.parser.parse_args(args_str.split())

    def test_metrics_collect(self):
        args = self._parse("observe metrics collect")
        self.assertTrue(hasattr(args, "func"))

    def test_metrics_show(self):
        args = self._parse("observe metrics show")
        self.assertTrue(hasattr(args, "func"))

    def test_metrics_top(self):
        args = self._parse("observe metrics top")
        self.assertTrue(hasattr(args, "func"))

    def test_monitor_list(self):
        args = self._parse("observe monitor list")
        self.assertTrue(hasattr(args, "func"))

    def test_monitor_run(self):
        args = self._parse("observe monitor run")
        self.assertTrue(hasattr(args, "func"))

    def test_vuln_scan(self):
        args = self._parse("secure vuln scan")
        self.assertTrue(hasattr(args, "func"))

    def test_vuln_results(self):
        args = self._parse("secure vuln results")
        self.assertTrue(hasattr(args, "func"))

    def test_fim_baseline(self):
        args = self._parse("secure fim baseline")
        self.assertTrue(hasattr(args, "func"))

    def test_fim_check(self):
        args = self._parse("secure fim check")
        self.assertTrue(hasattr(args, "func"))

    def test_fim_status(self):
        args = self._parse("secure fim status")
        self.assertTrue(hasattr(args, "func"))


if __name__ == "__main__":
    unittest.main()
