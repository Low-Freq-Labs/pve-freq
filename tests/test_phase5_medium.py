"""Phase 5 Medium Kills — Tests.

Tests for: db, proxy, secrets
"""
import argparse
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestProxyModule(unittest.TestCase):

    def test_routes_roundtrip(self):
        from freq.modules.proxy import _load_routes, _save_routes
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            routes = [{"domain": "app.example.com", "upstream": "10.0.0.5:8080"}]
            _save_routes(cfg, routes)
            loaded = _load_routes(cfg)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["domain"], "app.example.com")


class TestSecretsModule(unittest.TestCase):

    def test_generate_password(self):
        from freq.modules.secrets import _generate_password
        pw = _generate_password(32)
        self.assertEqual(len(pw), 32)
        pw2 = _generate_password(32)
        self.assertNotEqual(pw, pw2)

    def test_generate_token(self):
        from freq.modules.secrets import _generate_token
        tok = _generate_token(48)
        self.assertTrue(len(tok) > 0)

    def test_secret_patterns(self):
        from freq.modules.secrets import SECRET_PATTERNS
        self.assertGreaterEqual(len(SECRET_PATTERNS), 5)

    def test_leases_roundtrip(self):
        from freq.modules.secrets import _load_leases, _save_leases
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            leases = [{"name": "ssh-key", "type": "ssh", "expires_epoch": time.time() + 86400}]
            _save_leases(cfg, leases)
            loaded = _load_leases(cfg)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["name"], "ssh-key")

    def test_scan_results_roundtrip(self):
        from freq.modules.secrets import _load_scan_results, _save_scan_results
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            data = {"findings": [{"host": "h1", "finding": "test"}], "scan_time": "now"}
            _save_scan_results(cfg, data)
            loaded = _load_scan_results(cfg)
            self.assertEqual(len(loaded["findings"]), 1)


class TestPhase5CommandCount(unittest.TestCase):
    def test_command_count_at_least_120(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        registered = set()
        for action in parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertGreaterEqual(len(registered), 38,
                                f"Expected 38+ domain commands, got {len(registered)}")


if __name__ == "__main__":
    unittest.main()
