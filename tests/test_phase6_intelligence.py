"""Phase 6 Intelligence Kills — Tests.

Tests for: logs, oncall, comply
"""
import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPhase6Registration(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()
        self.registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                self.registered.update(action.choices.keys())

    def test_logs_registered(self):
        """logs is under 'observe' domain."""
        self.assertIn("observe", self.registered)

    def test_oncall_registered(self):
        """oncall is under 'ops' domain."""
        self.assertIn("ops", self.registered)

    def test_comply_registered(self):
        """comply is under 'secure' domain."""
        self.assertIn("secure", self.registered)


class TestPhase6Parsing(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_logs_default(self):
        args = self.parser.parse_args(["observe", "logs"])
        self.assertEqual(args.action, "tail")
        self.assertTrue(hasattr(args, "func"))

    def test_logs_search(self):
        args = self.parser.parse_args(["observe", "logs", "search", "OOM", "--since", "2h"])
        self.assertEqual(args.action, "search")
        self.assertEqual(args.pattern, "OOM")
        self.assertEqual(args.since, "2h")

    def test_logs_stats(self):
        args = self.parser.parse_args(["observe", "logs", "stats"])
        self.assertEqual(args.action, "stats")

    def test_oncall_default(self):
        args = self.parser.parse_args(["ops", "oncall"])
        self.assertEqual(args.action, "whoami")
        self.assertTrue(hasattr(args, "func"))

    def test_oncall_schedule(self):
        args = self.parser.parse_args(["ops", "oncall", "schedule", "--users", "alice,bob"])
        self.assertEqual(args.action, "schedule")
        self.assertEqual(args.users, "alice,bob")

    def test_oncall_alert(self):
        args = self.parser.parse_args(["ops", "oncall", "alert", "--message", "Disk full",
                                       "--alert-severity", "critical"])
        self.assertEqual(args.action, "alert")
        self.assertEqual(args.message, "Disk full")
        self.assertEqual(args.alert_severity, "critical")

    def test_oncall_ack(self):
        args = self.parser.parse_args(["ops", "oncall", "ack", "INC-001"])
        self.assertEqual(args.action, "ack")
        self.assertEqual(args.name, "INC-001")

    def test_oncall_resolve(self):
        args = self.parser.parse_args(["ops", "oncall", "resolve", "INC-001", "--note", "Fixed it"])
        self.assertEqual(args.action, "resolve")
        self.assertEqual(args.note, "Fixed it")

    def test_comply_default(self):
        args = self.parser.parse_args(["secure", "comply"])
        self.assertEqual(args.action, "scan")
        self.assertTrue(hasattr(args, "func"))

    def test_comply_report(self):
        args = self.parser.parse_args(["secure", "comply", "report"])
        self.assertEqual(args.action, "report")

    def test_comply_exceptions(self):
        args = self.parser.parse_args(["secure", "comply", "exceptions"])
        self.assertEqual(args.action, "exceptions")


class TestLogsModule(unittest.TestCase):
    def test_import(self):
        from freq.modules.logs import cmd_logs
        self.assertTrue(callable(cmd_logs))


class TestOncallModule(unittest.TestCase):
    def test_import(self):
        from freq.modules.oncall import cmd_oncall
        self.assertTrue(callable(cmd_oncall))

    def test_get_current_oncall_single(self):
        from freq.modules.oncall import _get_current_oncall
        schedule = {"users": ["alice"], "rotation": "weekly", "start_date": ""}
        self.assertEqual(_get_current_oncall(schedule), "alice")

    def test_get_current_oncall_empty(self):
        from freq.modules.oncall import _get_current_oncall
        self.assertEqual(_get_current_oncall({"users": []}), "")

    def test_next_incident_id(self):
        from freq.modules.oncall import _next_incident_id
        self.assertEqual(_next_incident_id([]), "INC-001")
        self.assertEqual(_next_incident_id([{"id": "INC-005"}]), "INC-006")

    def test_schedule_roundtrip(self):
        from freq.modules.oncall import _load_schedule, _save_schedule
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            schedule = {"users": ["alice", "bob"], "rotation": "weekly"}
            _save_schedule(cfg, schedule)
            loaded = _load_schedule(cfg)
            self.assertEqual(loaded["users"], ["alice", "bob"])

    def test_incidents_roundtrip(self):
        from freq.modules.oncall import _load_incidents, _save_incidents
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            incidents = [{"id": "INC-001", "status": "open", "message": "test"}]
            _save_incidents(cfg, incidents)
            loaded = _load_incidents(cfg)
            self.assertEqual(len(loaded), 1)


class TestComplyModule(unittest.TestCase):
    def test_import(self):
        from freq.modules.comply import cmd_comply
        self.assertTrue(callable(cmd_comply))

    def test_cis_checks_exist(self):
        from freq.modules.comply import CIS_CHECKS
        self.assertGreaterEqual(len(CIS_CHECKS), 10)

    def test_cis_checks_have_required_fields(self):
        from freq.modules.comply import CIS_CHECKS
        for check in CIS_CHECKS:
            self.assertIn("id", check)
            self.assertIn("title", check)
            self.assertIn("command", check)
            self.assertIn("severity", check)

    def test_is_excepted(self):
        from freq.modules.comply import _is_excepted
        exceptions = [{"check_id": "1.1.1", "host": "dev-01", "reason": "dev box"}]
        self.assertTrue(_is_excepted(exceptions, "1.1.1", "dev-01"))
        self.assertFalse(_is_excepted(exceptions, "1.1.1", "prod-01"))
        self.assertFalse(_is_excepted(exceptions, "2.2.2", "dev-01"))

    def test_is_excepted_wildcard(self):
        from freq.modules.comply import _is_excepted
        exceptions = [{"check_id": "5.2.4", "host": "*", "reason": "global exception"}]
        self.assertTrue(_is_excepted(exceptions, "5.2.4", "any-host"))

    def test_results_roundtrip(self):
        from freq.modules.comply import _load_results, _save_results
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            results = {"scans": [{"timestamp": "now", "hosts": {}}], "last_scan": "now"}
            _save_results(cfg, results)
            loaded = _load_results(cfg)
            self.assertEqual(len(loaded["scans"]), 1)


class TestPhase6CommandCount(unittest.TestCase):
    def test_command_count_at_least_38(self):
        """Domain-based CLI: 38+ top-level domains (not 123+ flat commands)."""
        from freq.cli import _build_parser
        parser = _build_parser()
        registered = set()
        for action in parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertGreaterEqual(len(registered), 38,
                                f"Expected 38+, got {len(registered)}")


class TestPhase6Dispatch(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_logs_has_func(self):
        args = self.parser.parse_args(["observe", "logs"])
        self.assertTrue(hasattr(args, "func"))

    def test_oncall_has_func(self):
        args = self.parser.parse_args(["ops", "oncall"])
        self.assertTrue(hasattr(args, "func"))

    def test_comply_has_func(self):
        args = self.parser.parse_args(["secure", "comply"])
        self.assertTrue(hasattr(args, "func"))


if __name__ == "__main__":
    unittest.main()
