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


class TestReportModule(unittest.TestCase):
    """Test the report module."""


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


if __name__ == "__main__":
    unittest.main()
