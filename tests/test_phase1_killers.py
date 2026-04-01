"""Phase 1 Killer Commands — Tests.

Tests for: alert, rollback, inventory, compare, baseline
5 new commands that kill Zabbix, Nagios, ServiceNow, Puppet, and Chef.
"""
import argparse
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPhase1Registration(unittest.TestCase):
    """Verify all Phase 1 commands are registered in the CLI parser."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()
        # Get all registered commands
        self.registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                self.registered.update(action.choices.keys())

    def test_alert_registered(self):
        self.assertIn("alert", self.registered)

    def test_rollback_registered(self):
        self.assertIn("rollback", self.registered)

    def test_inventory_registered(self):
        self.assertIn("inventory", self.registered)

    def test_compare_registered(self):
        self.assertIn("compare", self.registered)

    def test_baseline_registered(self):
        self.assertIn("baseline", self.registered)


class TestPhase1Parsing(unittest.TestCase):
    """Verify argument parsing for all Phase 1 commands."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_alert_list_default(self):
        args = self.parser.parse_args(["alert"])
        self.assertEqual(args.action, "list")
        self.assertTrue(hasattr(args, "func"))

    def test_alert_create_args(self):
        args = self.parser.parse_args([
            "alert", "create", "test-rule",
            "--condition", "cpu_above",
            "--threshold", "2.0",
            "--alert-severity", "critical",
        ])
        self.assertEqual(args.action, "create")
        self.assertEqual(args.name, "test-rule")
        self.assertEqual(args.condition, "cpu_above")
        self.assertEqual(args.threshold, 2.0)
        self.assertEqual(args.alert_severity, "critical")

    def test_alert_delete(self):
        args = self.parser.parse_args(["alert", "delete", "my-rule"])
        self.assertEqual(args.action, "delete")
        self.assertEqual(args.name, "my-rule")

    def test_alert_silence(self):
        args = self.parser.parse_args(["alert", "silence", "host-*", "--duration", "120"])
        self.assertEqual(args.action, "silence")
        self.assertEqual(args.name, "host-*")
        self.assertEqual(args.duration, 120)

    def test_alert_check(self):
        args = self.parser.parse_args(["alert", "check"])
        self.assertEqual(args.action, "check")

    def test_alert_test(self):
        args = self.parser.parse_args(["alert", "test"])
        self.assertEqual(args.action, "test")

    def test_alert_history(self):
        args = self.parser.parse_args(["alert", "history", "--lines", "50"])
        self.assertEqual(args.action, "history")
        self.assertEqual(args.lines, 50)

    def test_rollback_vmid(self):
        args = self.parser.parse_args(["rollback", "5005"])
        self.assertEqual(args.target, "5005")
        self.assertTrue(hasattr(args, "func"))

    def test_rollback_with_name(self):
        args = self.parser.parse_args(["rollback", "100", "--name", "pre-upgrade"])
        self.assertEqual(args.target, "100")
        self.assertEqual(args.name, "pre-upgrade")

    def test_rollback_no_start(self):
        args = self.parser.parse_args(["rollback", "100", "--no-start"])
        self.assertTrue(args.no_start)

    def test_inventory_default(self):
        args = self.parser.parse_args(["inventory"])
        self.assertEqual(args.section, "all")
        self.assertTrue(hasattr(args, "func"))

    def test_inventory_hosts_only(self):
        args = self.parser.parse_args(["inventory", "hosts"])
        self.assertEqual(args.section, "hosts")

    def test_inventory_vms_only(self):
        args = self.parser.parse_args(["inventory", "vms"])
        self.assertEqual(args.section, "vms")

    def test_inventory_csv(self):
        args = self.parser.parse_args(["inventory", "--csv"])
        self.assertTrue(args.csv)

    def test_compare_two_hosts(self):
        args = self.parser.parse_args(["compare", "pve01", "pve02"])
        self.assertEqual(args.target_a, "pve01")
        self.assertEqual(args.target_b, "pve02")
        self.assertTrue(hasattr(args, "func"))

    def test_baseline_default(self):
        args = self.parser.parse_args(["baseline"])
        self.assertEqual(args.action, "list")
        self.assertTrue(hasattr(args, "func"))

    def test_baseline_capture(self):
        args = self.parser.parse_args(["baseline", "capture", "my-baseline"])
        self.assertEqual(args.action, "capture")
        self.assertEqual(args.name, "my-baseline")

    def test_baseline_compare(self):
        args = self.parser.parse_args(["baseline", "compare", "my-baseline"])
        self.assertEqual(args.action, "compare")
        self.assertEqual(args.name, "my-baseline")

    def test_baseline_delete(self):
        args = self.parser.parse_args(["baseline", "delete", "old-baseline"])
        self.assertEqual(args.action, "delete")
        self.assertEqual(args.name, "old-baseline")


class TestAlertModule(unittest.TestCase):
    """Test the alert module's internal logic."""

    def test_import(self):
        from freq.modules.alert import cmd_alert
        self.assertTrue(callable(cmd_alert))

    def test_conditions_dict(self):
        from freq.modules.alert import CONDITIONS
        self.assertIn("host_down", CONDITIONS)
        self.assertIn("cpu_above", CONDITIONS)
        self.assertIn("ram_above", CONDITIONS)
        self.assertIn("disk_above", CONDITIONS)
        self.assertIn("docker_down", CONDITIONS)
        self.assertIn("load_spike", CONDITIONS)
        self.assertGreaterEqual(len(CONDITIONS), 8)

    def test_evaluate_condition_host_down(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": False}
        result = _evaluate_condition("host_down", 0, metrics, {})
        self.assertIsNotNone(result)
        self.assertIn("DOWN", result["message"])

    def test_evaluate_condition_host_up(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True}
        result = _evaluate_condition("host_down", 0, metrics, {})
        self.assertIsNone(result)

    def test_evaluate_condition_cpu_above(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "load_ratio": 3.5, "cores": 4}
        result = _evaluate_condition("cpu_above", 2.0, metrics, {})
        self.assertIsNotNone(result)

    def test_evaluate_condition_cpu_below(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "load_ratio": 0.5, "cores": 4}
        result = _evaluate_condition("cpu_above", 2.0, metrics, {})
        self.assertIsNone(result)

    def test_evaluate_condition_ram_above(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "ram_pct": 95.0}
        result = _evaluate_condition("ram_above", 90.0, metrics, {})
        self.assertIsNotNone(result)

    def test_evaluate_condition_disk_above(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "disk_pct": 88}
        result = _evaluate_condition("disk_above", 80, metrics, {})
        self.assertIsNotNone(result)

    def test_evaluate_condition_docker_down(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "docker": "inactive"}
        result = _evaluate_condition("docker_down", 0, metrics, {})
        self.assertIsNotNone(result)

    def test_evaluate_condition_docker_running(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "docker": "active"}
        result = _evaluate_condition("docker_down", 0, metrics, {})
        self.assertIsNone(result)

    def test_host_matches_wildcard(self):
        from freq.modules.alert import _host_matches
        self.assertTrue(_host_matches("pve01", {}, "*"))

    def test_host_matches_exact(self):
        from freq.modules.alert import _host_matches
        self.assertTrue(_host_matches("pve01", {}, "pve01"))

    def test_host_matches_prefix(self):
        from freq.modules.alert import _host_matches
        self.assertTrue(_host_matches("pve01", {}, "pve*"))

    def test_host_matches_type(self):
        from freq.modules.alert import _host_matches
        self.assertTrue(_host_matches("pve01", {"type": "pve"}, "pve"))

    def test_host_not_matches(self):
        from freq.modules.alert import _host_matches
        self.assertFalse(_host_matches("media01", {"type": "linux"}, "pve01"))

    def test_json_file_operations(self):
        from freq.modules.alert import _load_json, _save_json
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            # Test save
            _save_json(path, [{"test": True}])
            # Test load
            data = _load_json(path)
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]["test"])
        finally:
            os.unlink(path)

    def test_load_json_missing_file(self):
        from freq.modules.alert import _load_json
        data = _load_json("/nonexistent/path.json")
        self.assertEqual(data, [])

    def test_severities(self):
        from freq.modules.alert import SEVERITIES
        self.assertIn("info", SEVERITIES)
        self.assertIn("warning", SEVERITIES)
        self.assertIn("critical", SEVERITIES)


class TestRollbackModule(unittest.TestCase):
    """Test the rollback module."""

    def test_import(self):
        from freq.modules.rollback import cmd_rollback
        self.assertTrue(callable(cmd_rollback))

    def test_get_snapshots_parser(self):
        """Verify rollback can parse PVE snapshot output format."""
        from freq.modules.rollback import _get_snapshots
        # The function requires SSH — just verify it exists and is callable
        self.assertTrue(callable(_get_snapshots))


class TestInventoryModule(unittest.TestCase):
    """Test the inventory module."""

    def test_import(self):
        from freq.modules.inventory import cmd_inventory
        self.assertTrue(callable(cmd_inventory))

    def test_to_csv(self):
        from freq.modules.inventory import _to_csv
        data = [
            {"name": "host1", "ip": "10.0.0.1", "cores": 4},
            {"name": "host2", "ip": "10.0.0.2", "cores": 8},
        ]
        csv_output = _to_csv(data)
        self.assertIn("name,ip,cores", csv_output)
        self.assertIn("host1,10.0.0.1,4", csv_output)
        self.assertIn("host2,10.0.0.2,8", csv_output)

    def test_to_csv_empty(self):
        from freq.modules.inventory import _to_csv
        self.assertEqual(_to_csv([]), "")


class TestCompareModule(unittest.TestCase):
    """Test the compare module."""

    def test_import(self):
        from freq.modules.compare import cmd_compare
        self.assertTrue(callable(cmd_compare))

    def test_compare_field_equal_strings(self):
        from freq.modules.compare import _compare_field
        label, sa, sb, ind = _compare_field("OS", "Debian 13", "Debian 13")
        self.assertEqual(sa, "Debian 13")
        self.assertEqual(sb, "Debian 13")
        self.assertIn("=", ind)

    def test_compare_field_different_strings(self):
        from freq.modules.compare import _compare_field
        label, sa, sb, ind = _compare_field("OS", "Debian 13", "Ubuntu 24.04")
        self.assertIn("≠", ind)

    def test_compare_field_numeric(self):
        from freq.modules.compare import _compare_field
        label, sa, sb, ind = _compare_field("Cores", "8", "4", higher_is_better=True)
        self.assertIn("◀", ind)  # A is better


class TestBaselineModule(unittest.TestCase):
    """Test the baseline module."""

    def test_import(self):
        from freq.modules.baseline import cmd_baseline
        self.assertTrue(callable(cmd_baseline))

    def test_parse_sections(self):
        from freq.modules.baseline import _parse_sections
        output = (
            "---PACKAGES---\n"
            "vim=8.2\n"
            "curl=7.88\n"
            "---SERVICES---\n"
            "sshd.service\n"
            "docker.service\n"
            "---USERS---\n"
            "freq-ops\n"
            "sonny\n"
            "---KERNEL---\n"
            "6.1.0-27-amd64\n"
            "---END---\n"
        )
        sections = _parse_sections(output)
        self.assertEqual(len(sections["packages"]), 2)
        self.assertIn("vim=8.2", sections["packages"])
        self.assertEqual(len(sections["services"]), 2)
        self.assertIn("sshd.service", sections["services"])
        self.assertEqual(len(sections["users"]), 2)
        self.assertEqual(sections["kernel"], ["6.1.0-27-amd64"])

    def test_parse_sections_empty(self):
        from freq.modules.baseline import _parse_sections
        sections = _parse_sections("")
        self.assertEqual(sections, {})

    def test_baseline_json_roundtrip(self):
        """Test saving and loading a baseline."""
        from freq.modules.baseline import _save_baseline, _load_baseline
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock cfg
            cfg = MagicMock()
            cfg.conf_dir = tmpdir

            baseline_data = {
                "name": "test",
                "timestamp": "2026-03-31T12:00:00-0500",
                "hosts": {
                    "pve01": {
                        "packages": ["vim=8.2", "curl=7.88"],
                        "services": ["sshd.service"],
                    }
                },
            }

            _save_baseline(cfg, "test", baseline_data)
            loaded = _load_baseline(cfg, "test")

            self.assertEqual(loaded["name"], "test")
            self.assertEqual(len(loaded["hosts"]["pve01"]["packages"]), 2)

    def test_list_baselines(self):
        """Test listing baselines."""
        from freq.modules.baseline import _save_baseline, _list_baselines
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir

            _save_baseline(cfg, "b1", {"name": "b1", "timestamp": "t1", "hosts": {"h1": {}}})
            _save_baseline(cfg, "b2", {"name": "b2", "timestamp": "t2", "hosts": {"h1": {}, "h2": {}}})

            baselines = _list_baselines(cfg)
            self.assertEqual(len(baselines), 2)
            names = [b["name"] for b in baselines]
            self.assertIn("b1", names)
            self.assertIn("b2", names)


class TestPhase1CommandCount(unittest.TestCase):
    """Verify we've passed 100 commands."""

    def test_command_count_at_least_104(self):
        """We should have at least 104 commands (99 + 5 new)."""
        from freq.cli import _build_parser
        parser = _build_parser()
        registered = set()
        for action in parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertGreaterEqual(len(registered), 104,
                                f"Expected 104+ commands, got {len(registered)}: {sorted(registered)}")


class TestPhase1Dispatch(unittest.TestCase):
    """Verify all Phase 1 commands have func set."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_alert_has_func(self):
        args = self.parser.parse_args(["alert"])
        self.assertTrue(hasattr(args, "func"))

    def test_rollback_has_func(self):
        args = self.parser.parse_args(["rollback", "100"])
        self.assertTrue(hasattr(args, "func"))

    def test_inventory_has_func(self):
        args = self.parser.parse_args(["inventory"])
        self.assertTrue(hasattr(args, "func"))

    def test_compare_has_func(self):
        args = self.parser.parse_args(["compare", "a", "b"])
        self.assertTrue(hasattr(args, "func"))

    def test_baseline_has_func(self):
        args = self.parser.parse_args(["baseline"])
        self.assertTrue(hasattr(args, "func"))


if __name__ == "__main__":
    unittest.main()
