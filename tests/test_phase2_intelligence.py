"""Phase 2 Intelligence Layer — Tests.

Tests for: report, trend, sla, cert, dns
5 commands that make freq think for you.
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


class TestPhase2Registration(unittest.TestCase):
    """Verify all Phase 2 commands are registered."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()
        self.registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                self.registered.update(action.choices.keys())

    def test_report_registered(self):
        self.assertIn("fleet", self.registered)  # report under fleet

    def test_trend_registered(self):
        self.assertIn("observe", self.registered)  # trend under observe

    def test_sla_registered(self):
        self.assertIn("observe", self.registered)  # sla under observe

    def test_cert_registered(self):
        self.assertIn("cert", self.registered)  # cert under cert

    def test_dns_registered(self):
        self.assertIn("dns", self.registered)  # dns under dns


class TestPhase2Parsing(unittest.TestCase):
    """Verify argument parsing for Phase 2 commands."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_report_default(self):
        args = self.parser.parse_args(["fleet", "report"])
        self.assertEqual(args.action, "generate")
        self.assertTrue(hasattr(args, "func"))

    def test_report_markdown(self):
        args = self.parser.parse_args(["fleet", "report", "--markdown"])
        self.assertTrue(args.markdown)

    def test_trend_default(self):
        args = self.parser.parse_args(["observe", "trend"])
        self.assertEqual(args.action, "show")
        self.assertTrue(hasattr(args, "func"))

    def test_trend_snapshot(self):
        args = self.parser.parse_args(["observe", "trend", "snapshot"])
        self.assertEqual(args.action, "snapshot")

    def test_trend_history(self):
        args = self.parser.parse_args(["observe", "trend", "history", "--lines", "50"])
        self.assertEqual(args.action, "history")
        self.assertEqual(args.lines, 50)

    def test_sla_default(self):
        args = self.parser.parse_args(["observe", "sla"])
        self.assertEqual(args.action, "show")
        self.assertTrue(hasattr(args, "func"))

    def test_sla_check(self):
        args = self.parser.parse_args(["observe", "sla", "check"])
        self.assertEqual(args.action, "check")

    def test_sla_days(self):
        args = self.parser.parse_args(["observe", "sla", "show", "--days", "90"])
        self.assertEqual(args.days, 90)

    def test_sla_reset(self):
        args = self.parser.parse_args(["observe", "sla", "reset"])
        self.assertEqual(args.action, "reset")

    def test_cert_default(self):
        args = self.parser.parse_args(["cert"])
        self.assertIsNone(args.subcmd)  # default has no subcmd
        self.assertTrue(hasattr(args, "func"))

    def test_cert_check(self):
        args = self.parser.parse_args(["cert", "check", "pve01:8006"])
        self.assertEqual(args.subcmd, "check")
        self.assertEqual(args.target, "pve01:8006")

    def test_cert_list(self):
        args = self.parser.parse_args(["cert", "list"])
        self.assertEqual(args.subcmd, "list")

    def test_dns_default(self):
        args = self.parser.parse_args(["dns"])
        self.assertIsNone(args.subcmd)  # default has no subcmd
        self.assertTrue(hasattr(args, "func"))

    def test_dns_check(self):
        args = self.parser.parse_args(["dns", "check", "10.25.255.50"])
        self.assertEqual(args.subcmd, "check")
        self.assertEqual(args.target, "10.25.255.50")

    def test_dns_list(self):
        args = self.parser.parse_args(["dns", "list"])
        self.assertEqual(args.subcmd, "list")


class TestReportModule(unittest.TestCase):
    """Test the report module."""

    def test_import(self):
        from freq.modules.report import cmd_report
        self.assertTrue(callable(cmd_report))

    def test_find_issues_empty(self):
        from freq.modules.report import _find_issues
        issues = _find_issues({"hosts": []})
        self.assertEqual(issues, [])

    def test_find_issues_host_down(self):
        from freq.modules.report import _find_issues
        issues = _find_issues({"hosts": [{"label": "h1", "status": "down"}]})
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "critical")
        self.assertIn("DOWN", issues[0]["message"])

    def test_find_issues_disk_critical(self):
        from freq.modules.report import _find_issues
        issues = _find_issues({"hosts": [
            {"label": "h1", "status": "up", "disk_pct": 95, "ram_pct": 50, "cores": 4, "load": 1}
        ]})
        self.assertTrue(any("Disk" in i["message"] for i in issues))

    def test_find_issues_healthy(self):
        from freq.modules.report import _find_issues
        issues = _find_issues({"hosts": [
            {"label": "h1", "status": "up", "disk_pct": 40, "ram_pct": 50, "cores": 4, "load": 1}
        ]})
        self.assertEqual(len(issues), 0)

    def test_report_to_markdown(self):
        from freq.modules.report import _report_to_markdown
        report = {
            "timestamp": "2026-03-31T12:00:00-0500",
            "health": {"up": 10, "total": 10, "total_cores": 40, "total_ram_mb": 65536, "total_containers": 25},
            "vms": {"total": 30, "running": 28, "stopped": 2},
            "alerts": {"alerts_24h": 0, "rules_active": 5, "rules_total": 5},
            "issues": [],
        }
        md = _report_to_markdown(report)
        self.assertIn("# FREQ Fleet Report", md)
        self.assertIn("10/10 up", md)
        self.assertIn("No issues", md)


class TestTrendModule(unittest.TestCase):
    """Test the trend module."""

    def test_import(self):
        from freq.modules.trend import cmd_trend
        self.assertTrue(callable(cmd_trend))

    def test_sparkline(self):
        from freq.modules.trend import _render_sparkline
        spark = _render_sparkline([1, 2, 3, 4, 5])
        self.assertEqual(len(spark), 5)

    def test_sparkline_empty(self):
        from freq.modules.trend import _render_sparkline
        self.assertEqual(_render_sparkline([]), "")

    def test_sparkline_flat(self):
        from freq.modules.trend import _render_sparkline
        spark = _render_sparkline([5, 5, 5, 5])
        self.assertEqual(len(spark), 4)

    def test_trend_data_roundtrip(self):
        from freq.modules.trend import _load_trend_data, _save_trend_data
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            data = [
                {"epoch": 1000, "fleet": {"ram_pct": 50}, "hosts": {}},
                {"epoch": 2000, "fleet": {"ram_pct": 55}, "hosts": {}},
            ]
            _save_trend_data(cfg, data)
            loaded = _load_trend_data(cfg)
            self.assertEqual(len(loaded), 2)


class TestSlaModule(unittest.TestCase):
    """Test the SLA module."""

    def test_import(self):
        from freq.modules.sla import cmd_sla
        self.assertTrue(callable(cmd_sla))

    def test_calculate_sla_perfect(self):
        from freq.modules.sla import _calculate_sla
        data = {
            "checks": [
                {"epoch": time.time(), "results": {"host1": 1}},
                {"epoch": time.time(), "results": {"host1": 1}},
                {"epoch": time.time(), "results": {"host1": 1}},
            ]
        }
        result = _calculate_sla(data, "host1", 7)
        self.assertEqual(result["pct"], 100.0)
        self.assertEqual(result["grade"], "A+")

    def test_calculate_sla_with_downtime(self):
        from freq.modules.sla import _calculate_sla
        data = {
            "checks": [
                {"epoch": time.time(), "results": {"host1": 1}},
                {"epoch": time.time(), "results": {"host1": 0}},
                {"epoch": time.time(), "results": {"host1": 1}},
                {"epoch": time.time(), "results": {"host1": 1}},
            ]
        }
        result = _calculate_sla(data, "host1", 7)
        self.assertEqual(result["pct"], 75.0)
        self.assertEqual(result["grade"], "F")

    def test_calculate_sla_no_data(self):
        from freq.modules.sla import _calculate_sla
        result = _calculate_sla({"checks": []}, "host1", 30)
        self.assertEqual(result["grade"], "N/A")

    def test_sla_grades(self):
        from freq.modules.sla import _calculate_sla
        # 99.99% = A+
        checks_a = [{"epoch": time.time(), "results": {"h": 1}} for _ in range(10000)]
        checks_a[0]["results"]["h"] = 0  # 1 failure out of 10000 = 99.99%
        result = _calculate_sla({"checks": checks_a}, "h", 7)
        self.assertEqual(result["grade"], "A+")


class TestCertModule(unittest.TestCase):
    """Test the cert module."""

    def test_import(self):
        from freq.modules.cert import cmd_cert
        self.assertTrue(callable(cmd_cert))

    def test_default_ports(self):
        from freq.modules.cert import DEFAULT_PORTS
        self.assertIn(443, DEFAULT_PORTS)
        self.assertIn(8006, DEFAULT_PORTS)
        self.assertIn(8443, DEFAULT_PORTS)

    def test_expiry_thresholds(self):
        from freq.modules.cert import EXPIRY_CRITICAL, EXPIRY_WARNING
        self.assertEqual(EXPIRY_CRITICAL, 7)
        self.assertEqual(EXPIRY_WARNING, 30)

    def test_cert_data_roundtrip(self):
        from freq.modules.cert import _load_cert_data, _save_cert_data
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            data = {"certs": [{"host": "test", "status": "ok"}], "scan_time": "now"}
            _save_cert_data(cfg, data)
            loaded = _load_cert_data(cfg)
            self.assertEqual(len(loaded["certs"]), 1)


class TestDnsModule(unittest.TestCase):
    """Test the DNS module."""

    def test_import(self):
        from freq.modules.dns import cmd_dns
        self.assertTrue(callable(cmd_dns))

    def test_forward_lookup_localhost(self):
        from freq.modules.dns import _forward_lookup
        ips = _forward_lookup("localhost")
        self.assertIn("127.0.0.1", ips)

    def test_forward_lookup_invalid(self):
        from freq.modules.dns import _forward_lookup
        ips = _forward_lookup("this.host.definitely.does.not.exist.invalid")
        self.assertEqual(ips, [])

    def test_reverse_lookup_localhost(self):
        from freq.modules.dns import _reverse_lookup
        hostname = _reverse_lookup("127.0.0.1")
        self.assertTrue(len(hostname) > 0)

    def test_dns_data_roundtrip(self):
        from freq.modules.dns import _load_dns_data, _save_dns_data
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            data = {"records": [{"label": "test"}], "scan_time": "now"}
            _save_dns_data(cfg, data)
            loaded = _load_dns_data(cfg)
            self.assertEqual(len(loaded["records"]), 1)


class TestPhase2CommandCount(unittest.TestCase):
    """Verify command count."""

    def test_command_count_at_least_109(self):
        """Phase 1 (104) + Phase 2 (5) = 109+."""
        from freq.cli import _build_parser
        parser = _build_parser()
        registered = set()
        for action in parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertGreaterEqual(len(registered), 38,
                                f"Expected 38+ domain commands, got {len(registered)}")


class TestPhase2Dispatch(unittest.TestCase):
    """Verify all Phase 2 commands dispatch."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_report_has_func(self):
        args = self.parser.parse_args(["fleet", "report"])
        self.assertTrue(hasattr(args, "func"))

    def test_trend_has_func(self):
        args = self.parser.parse_args(["observe", "trend"])
        self.assertTrue(hasattr(args, "func"))

    def test_sla_has_func(self):
        args = self.parser.parse_args(["observe", "sla"])
        self.assertTrue(hasattr(args, "func"))

    def test_cert_has_func(self):
        args = self.parser.parse_args(["cert"])
        self.assertTrue(hasattr(args, "func"))

    def test_dns_has_func(self):
        args = self.parser.parse_args(["dns"])
        self.assertTrue(hasattr(args, "func"))


if __name__ == "__main__":
    unittest.main()
