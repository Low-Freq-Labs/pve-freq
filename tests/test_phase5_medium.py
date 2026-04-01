"""Phase 5 Medium Kills — Tests.

Tests for: db, proxy, secrets
"""
import argparse
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPhase5Registration(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()
        self.registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                self.registered.update(action.choices.keys())

    def test_db_registered(self):
        self.assertIn("db", self.registered)

    def test_proxy_registered(self):
        self.assertIn("proxy", self.registered)

    def test_secrets_registered(self):
        self.assertIn("secrets", self.registered)


class TestPhase5Parsing(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_db_default(self):
        args = self.parser.parse_args(["db"])
        self.assertEqual(args.action, "status")
        self.assertTrue(hasattr(args, "func"))

    def test_db_size(self):
        args = self.parser.parse_args(["db", "size"])
        self.assertEqual(args.action, "size")

    def test_proxy_default(self):
        args = self.parser.parse_args(["proxy"])
        self.assertEqual(args.action, "status")
        self.assertTrue(hasattr(args, "func"))

    def test_proxy_add(self):
        args = self.parser.parse_args(["proxy", "add", "--domain", "app.example.com",
                                       "--upstream", "10.0.0.5:8080"])
        self.assertEqual(args.action, "add")
        self.assertEqual(args.domain, "app.example.com")
        self.assertEqual(args.upstream, "10.0.0.5:8080")

    def test_proxy_certs(self):
        args = self.parser.parse_args(["proxy", "certs"])
        self.assertEqual(args.action, "certs")

    def test_secrets_default(self):
        args = self.parser.parse_args(["secrets"])
        self.assertEqual(args.action, "list")
        self.assertTrue(hasattr(args, "func"))

    def test_secrets_scan(self):
        args = self.parser.parse_args(["secrets", "scan"])
        self.assertEqual(args.action, "scan")

    def test_secrets_generate(self):
        args = self.parser.parse_args(["secrets", "generate", "--secret-type", "token",
                                       "--length", "48"])
        self.assertEqual(args.action, "generate")
        self.assertEqual(args.secret_type, "token")
        self.assertEqual(args.length, 48)

    def test_secrets_lease(self):
        args = self.parser.parse_args(["secrets", "lease", "my-key", "--expires", "90d"])
        self.assertEqual(args.action, "lease")
        self.assertEqual(args.name, "my-key")
        self.assertEqual(args.expires, "90d")


class TestDbModule(unittest.TestCase):
    def test_import(self):
        from freq.modules.db import cmd_db
        self.assertTrue(callable(cmd_db))


class TestProxyModule(unittest.TestCase):
    def test_import(self):
        from freq.modules.proxy import cmd_proxy
        self.assertTrue(callable(cmd_proxy))

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
    def test_import(self):
        from freq.modules.secrets import cmd_secrets
        self.assertTrue(callable(cmd_secrets))

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
        self.assertGreaterEqual(len(registered), 120,
                                f"Expected 120+, got {len(registered)}")


class TestPhase5Dispatch(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_db_has_func(self):
        args = self.parser.parse_args(["db"])
        self.assertTrue(hasattr(args, "func"))

    def test_proxy_has_func(self):
        args = self.parser.parse_args(["proxy"])
        self.assertTrue(hasattr(args, "func"))

    def test_secrets_has_func(self):
        args = self.parser.parse_args(["secrets"])
        self.assertTrue(hasattr(args, "func"))


if __name__ == "__main__":
    unittest.main()
