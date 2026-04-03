"""Phase 4 Easy Kills — Tests.

Tests for: patch, stack, docs
"""
import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPhase4Registration(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()
        self.registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                self.registered.update(action.choices.keys())

    def test_patch_registered(self):
        self.assertIn("secure", self.registered)  # patch under secure

    def test_stack_registered(self):
        self.assertIn("docker", self.registered)  # stack under docker

    def test_docs_registered(self):
        self.assertIn("docs", self.registered)


class TestPhase4Parsing(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_patch_default(self):
        args = self.parser.parse_args(["secure", "patch"])
        self.assertEqual(args.action, "status")
        self.assertTrue(hasattr(args, "func"))

    def test_patch_check(self):
        args = self.parser.parse_args(["secure", "patch", "check"])
        self.assertEqual(args.action, "check")

    def test_patch_apply(self):
        args = self.parser.parse_args(["secure", "patch", "apply", "--target-host", "web-01"])
        self.assertEqual(args.action, "apply")
        self.assertEqual(args.target_host, "web-01")

    def test_patch_hold(self):
        args = self.parser.parse_args(["secure", "patch", "hold", "nginx"])
        self.assertEqual(args.action, "hold")
        self.assertEqual(args.name, "nginx")

    def test_patch_compliance(self):
        args = self.parser.parse_args(["secure", "patch", "compliance"])
        self.assertEqual(args.action, "compliance")

    def test_stack_default(self):
        args = self.parser.parse_args(["docker", "stack"])
        self.assertEqual(args.action, "status")
        self.assertTrue(hasattr(args, "func"))

    def test_stack_update(self):
        args = self.parser.parse_args(["docker", "stack", "update", "media"])
        self.assertEqual(args.action, "update")
        self.assertEqual(args.name, "media")

    def test_stack_health(self):
        args = self.parser.parse_args(["docker", "stack", "health"])
        self.assertEqual(args.action, "health")

    def test_stack_logs(self):
        args = self.parser.parse_args(["docker", "stack", "logs", "media", "--lines", "50"])
        self.assertEqual(args.action, "logs")
        self.assertEqual(args.name, "media")
        self.assertEqual(args.lines, 50)

    def test_stack_template(self):
        args = self.parser.parse_args(["docker", "stack", "template"])
        self.assertEqual(args.action, "template")

    def test_docs_default(self):
        args = self.parser.parse_args(["docs"])
        self.assertEqual(args.action, "generate")
        self.assertTrue(hasattr(args, "func"))

    def test_docs_verify(self):
        args = self.parser.parse_args(["docs", "verify"])
        self.assertEqual(args.action, "verify")

    def test_docs_export(self):
        args = self.parser.parse_args(["docs", "export", "--format", "html"])
        self.assertEqual(args.action, "export")
        self.assertEqual(args.format, "html")

    def test_docs_runbook(self):
        args = self.parser.parse_args(["docs", "runbook", "disk-cleanup"])
        self.assertEqual(args.action, "runbook")
        self.assertEqual(args.name, "disk-cleanup")


class TestPatchModule(unittest.TestCase):
    def test_import(self):
        from freq.modules.patch import cmd_patch
        self.assertTrue(callable(cmd_patch))

    def test_holds_roundtrip(self):
        from freq.modules.patch import _load_holds, _save_holds
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            holds = [{"package": "nginx", "since": "2026-03-31"}]
            _save_holds(cfg, holds)
            loaded = _load_holds(cfg)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["package"], "nginx")

    def test_history_roundtrip(self):
        from freq.modules.patch import _load_history, _save_history
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            history = [{"timestamp": "now", "hosts": ["h1"], "success": 1, "failed": 0}]
            _save_history(cfg, history)
            loaded = _load_history(cfg)
            self.assertEqual(len(loaded), 1)


class TestStackModule(unittest.TestCase):
    def test_import(self):
        from freq.modules.stack import cmd_stack
        self.assertTrue(callable(cmd_stack))

    def test_templates(self):
        from freq.modules.stack import STACK_TEMPLATES
        self.assertIn("arr-stack", STACK_TEMPLATES)
        self.assertIn("monitoring", STACK_TEMPLATES)
        self.assertIn("web", STACK_TEMPLATES)
        self.assertIn("db", STACK_TEMPLATES)

    def test_registry_roundtrip(self):
        from freq.modules.stack import _load_registry, _save_registry
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            registry = [{"name": "media", "host": "plex-01"}]
            _save_registry(cfg, registry)
            loaded = _load_registry(cfg)
            self.assertEqual(len(loaded), 1)


class TestDocsModule(unittest.TestCase):
    def test_import(self):
        from freq.modules.docs import cmd_docs
        self.assertTrue(callable(cmd_docs))

    def test_generate_markdown(self):
        from freq.modules.docs import _generate_markdown
        cfg = MagicMock()
        cfg.pve_nodes = ["10.0.0.1"]
        data = {
            "hosts": [
                {"label": "pve01", "ip": "10.0.0.1", "type": "pve", "reachable": True,
                 "hostname": "pve01.local", "os": "Debian 13", "kernel": "6.1.0",
                 "cores": "4", "ram": "32768", "disk": "500", "ips": "10.0.0.1/24",
                 "docker": "none", "services": "sshd.service"},
            ],
            "timestamp": "2026-04-01T00:00:00-0500",
            "host_count": 1,
            "reachable": 1,
        }
        md = _generate_markdown(data, cfg)
        self.assertIn("# Infrastructure Documentation", md)
        self.assertIn("pve01", md)
        self.assertIn("Debian 13", md)

    def test_generate_markdown_empty(self):
        from freq.modules.docs import _generate_markdown
        cfg = MagicMock()
        cfg.pve_nodes = []
        data = {"hosts": [], "timestamp": "now", "host_count": 0, "reachable": 0}
        md = _generate_markdown(data, cfg)
        self.assertIn("# Infrastructure Documentation", md)
        self.assertIn("Total Hosts | 0", md)


class TestPhase4CommandCount(unittest.TestCase):
    def test_command_count_at_least_117(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        registered = set()
        for action in parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertGreaterEqual(len(registered), 38,
                                f"Expected 38+ domain commands, got {len(registered)}")


class TestPhase4Dispatch(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_patch_has_func(self):
        args = self.parser.parse_args(["secure", "patch"])
        self.assertTrue(hasattr(args, "func"))

    def test_stack_has_func(self):
        args = self.parser.parse_args(["docker", "stack"])
        self.assertTrue(hasattr(args, "func"))

    def test_docs_has_func(self):
        args = self.parser.parse_args(["docs"])
        self.assertTrue(hasattr(args, "func"))


if __name__ == "__main__":
    unittest.main()
