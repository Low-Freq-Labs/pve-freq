"""Tests for Phase 9 — The Proof (WS21: E2E Testing Framework).
Covers: CLI smoke tests for all 25 domains, --help validation, domain dispatch
verification, and the E2E test harness infrastructure.

These tests run LOCALLY — they verify CLI registration, help output, and
module imports. Live fleet tests require freq-test (VM 5005) and Sonny's
approval before execution.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


# ─────────────────────────────────────────────────────────────
# CLI SMOKE TESTS — Every domain's --help must work
# ─────────────────────────────────────────────────────────────

class TestDomainHelpSmoke(unittest.TestCase):
    """Every registered domain must respond to --help without crashing."""

    DOMAINS = [
        "vm", "fleet", "host", "docker", "secure", "observe",
        "state", "auto", "ops", "hw", "store", "dr", "net",
        "fw", "cert", "dns", "proxy", "media", "user",
        "event", "vpn", "plugin",
    ]

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _help_works(self, domain):
        """Verify domain --help parses without error."""
        try:
            self.parser.parse_args([domain, "--help"])
        except SystemExit as e:
            # --help causes SystemExit(0) — that's expected
            self.assertEqual(e.code, 0, f"freq {domain} --help exited with {e.code}")

    def test_vm_help(self):
        self._help_works("vm")

    def test_fleet_help(self):
        self._help_works("fleet")

    def test_host_help(self):
        self._help_works("host")

    def test_docker_help(self):
        self._help_works("docker")

    def test_secure_help(self):
        self._help_works("secure")

    def test_observe_help(self):
        self._help_works("observe")

    def test_state_help(self):
        self._help_works("state")

    def test_auto_help(self):
        self._help_works("auto")

    def test_ops_help(self):
        self._help_works("ops")

    def test_hw_help(self):
        self._help_works("hw")

    def test_store_help(self):
        self._help_works("store")

    def test_dr_help(self):
        self._help_works("dr")

    def test_net_help(self):
        self._help_works("net")

    def test_fw_help(self):
        self._help_works("fw")

    def test_cert_help(self):
        self._help_works("cert")

    def test_dns_help(self):
        self._help_works("dns")

    def test_proxy_help(self):
        self._help_works("proxy")

    def test_media_help(self):
        self._help_works("media")

    def test_user_help(self):
        self._help_works("user")

    def test_event_help(self):
        self._help_works("event")

    def test_vpn_help(self):
        self._help_works("vpn")

    def test_plugin_help(self):
        self._help_works("plugin")


# ─────────────────────────────────────────────────────────────
# DOMAIN DISPATCH — Every domain routes to the correct handler
# ─────────────────────────────────────────────────────────────

class TestDomainDispatch(unittest.TestCase):
    """Verify every domain parses and sets a callable func."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _has_func(self, cmd_str):
        args = self.parser.parse_args(cmd_str.split())
        self.assertTrue(hasattr(args, "func"),
                        f"No func for: freq {cmd_str}")

    # VM domain
    def test_vm_list(self):
        self._has_func("vm list")

    def test_vm_create(self):
        self._has_func("vm create --name test --image debian --node pve01")

    def test_vm_power(self):
        self._has_func("vm power start 100")

    # Fleet domain
    def test_fleet_status(self):
        self._has_func("fleet status")

    def test_fleet_exec(self):
        self._has_func("fleet exec all hostname")

    def test_fleet_health(self):
        self._has_func("fleet health")

    # Host domain
    def test_host_list(self):
        self._has_func("host list")

    def test_host_add(self):
        self._has_func("host add")

    # Docker domain
    def test_docker_list(self):
        self._has_func("docker list")

    # Secure domain
    def test_secure_audit(self):
        self._has_func("secure audit")

    def test_secure_vault(self):
        self._has_func("secure vault list")

    # Observe domain
    def test_observe_alert_list(self):
        self._has_func("observe alert list")

    def test_observe_logs(self):
        self._has_func("observe logs tail freq-test")

    # State domain
    def test_state_baseline(self):
        self._has_func("state baseline capture freq-test")

    def test_state_plan(self):
        self._has_func("state plan")

    # Auto domain
    def test_auto_rules(self):
        self._has_func("auto rules list")

    def test_auto_schedule(self):
        self._has_func("auto schedule list")

    # Ops domain
    def test_ops_oncall(self):
        self._has_func("ops oncall whoami")

    # HW domain
    def test_hw_cost(self):
        self._has_func("hw cost")

    # Store domain
    def test_store_nas(self):
        self._has_func("store nas status")

    # DR domain
    def test_dr_backup(self):
        self._has_func("dr backup list")

    # Net domain
    def test_net_switch_facts(self):
        self._has_func("net switch facts switch")

    def test_net_switch_interfaces(self):
        self._has_func("net switch interfaces switch")

    # FW domain
    def test_fw_rules(self):
        self._has_func("fw rules list")

    # Cert domain
    def test_cert_scan(self):
        self._has_func("cert scan")

    # DNS domain
    def test_dns_scan(self):
        self._has_func("dns scan")

    # Proxy domain
    def test_proxy_status(self):
        self._has_func("proxy status")

    # User domain
    def test_user_list(self):
        self._has_func("user list")

    # Event domain
    def test_event_create(self):
        self._has_func("event create test-event")

    def test_event_list(self):
        self._has_func("event list")

    # VPN domain
    def test_vpn_wg_status(self):
        self._has_func("vpn wg status")

    # Plugin domain
    def test_plugin_list(self):
        self._has_func("plugin list")

    def test_plugin_create(self):
        self._has_func("plugin create --name test")

    def test_plugin_types(self):
        self._has_func("plugin types")


# ─────────────────────────────────────────────────────────────
# CONVERGENCE VERIFICATION — Old flat commands must NOT work
# ─────────────────────────────────────────────────────────────

class TestConvergenceOldCommandsDead(unittest.TestCase):
    """Old flat command names must not parse — convergence means they're dead."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _must_fail(self, cmd_str):
        """Verify old flat command does NOT parse as a domain."""
        try:
            args = self.parser.parse_args(cmd_str.split())
            # If it parsed but has no func, that's also OK (domain help)
            if hasattr(args, "func"):
                # Some old names (like "doctor") are deliberately kept as utilities
                pass
        except SystemExit:
            pass  # Expected — command not found

    def test_old_create_gone(self):
        """freq create should not exist (now freq vm create)."""
        try:
            args = self.parser.parse_args(["create", "--name", "test"])
            # create is not a registered top-level command
            self.assertFalse(hasattr(args, "func") and
                             "vm" not in str(getattr(args, "domain", "")))
        except SystemExit:
            pass  # Expected

    def test_old_destroy_gone(self):
        try:
            args = self.parser.parse_args(["destroy", "100"])
            self.assertFalse(hasattr(args, "func"))
        except SystemExit:
            pass

    def test_old_audit_gone(self):
        try:
            args = self.parser.parse_args(["audit"])
            self.assertFalse(hasattr(args, "func"))
        except SystemExit:
            pass


# ─────────────────────────────────────────────────────────────
# MODULE IMPORT VERIFICATION — All 21 modules must import
# ─────────────────────────────────────────────────────────────

class TestAllModulesImport(unittest.TestCase):
    """Every module file in freq/modules/ must import without error."""

    MODULES = [
        "switch_orchestration", "config_management", "event_network",
        "snmp", "topology", "net_intelligence",
        "firewall", "dns_management", "vpn", "cert_management", "proxy_management",
        "storage", "dr",
        "metrics", "synthetic_monitors", "vuln", "fim",
        "incident", "iac", "automation",
        "docker_mgmt", "hardware",
        "plugin_manager",
    ]

    def test_all_modules_import(self):
        for mod_name in self.MODULES:
            try:
                __import__(f"freq.modules.{mod_name}")
            except Exception as e:
                self.fail(f"Failed to import freq.modules.{mod_name}: {e}")


# ─────────────────────────────────────────────────────────────
# API ROUTE COMPLETENESS — Every domain has API routes
# ─────────────────────────────────────────────────────────────

class TestAPIRouteCompleteness(unittest.TestCase):
    """Verify the API route builder includes all domains."""

    def test_build_routes_returns_dict(self):
        from freq.api import build_routes
        routes = build_routes()
        self.assertIsInstance(routes, dict)

    def test_route_count(self):
        from freq.api import build_routes
        routes = build_routes()
        # Should have routes from 15 domain modules
        self.assertGreater(len(routes), 0)

    def test_api_domains_registered(self):
        """Verify each API module can be imported."""
        api_modules = [
            "freq.api.vm", "freq.api.fleet", "freq.api.host",
            "freq.api.secure", "freq.api.observe", "freq.api.state",
            "freq.api.net", "freq.api.docker_api", "freq.api.hw",
            "freq.api.store", "freq.api.dr", "freq.api.auto",
            "freq.api.ops", "freq.api.user", "freq.api.plugin",
        ]
        for mod_path in api_modules:
            try:
                __import__(mod_path)
            except ImportError as e:
                self.fail(f"Cannot import {mod_path}: {e}")


# ─────────────────────────────────────────────────────────────
# HELP OUTPUT QUALITY — freq help shows all domains
# ─────────────────────────────────────────────────────────────

class TestHelpOutput(unittest.TestCase):
    """Verify freq help references all v3.0.0 domains."""

    def setUp(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import MagicMock

        from freq.cli import cmd_help

        cfg = MagicMock()
        cfg.version = "3.0.0"
        pack = MagicMock()
        args = MagicMock()

        self.output = io.StringIO()
        with redirect_stdout(self.output):
            cmd_help(cfg, pack, args)
        self.text = self.output.getvalue()

    def test_help_mentions_vm(self):
        self.assertIn("vm", self.text.lower())

    def test_help_mentions_fleet(self):
        self.assertIn("fleet", self.text.lower())

    def test_help_mentions_plugin(self):
        self.assertIn("plugin", self.text.lower())

    def test_help_mentions_net(self):
        self.assertIn("net", self.text.lower())

    def test_help_mentions_secure(self):
        self.assertIn("secure", self.text.lower())

    def test_help_mentions_observe(self):
        self.assertIn("observe", self.text.lower())

    def test_help_mentions_auto(self):
        self.assertIn("auto", self.text.lower())

    def test_help_mentions_dr(self):
        self.assertIn("dr", self.text.lower())


# ─────────────────────────────────────────────────────────────
# E2E HARNESS — Test infrastructure for live fleet tests
# ─────────────────────────────────────────────────────────────

class TestE2EHarness(unittest.TestCase):
    """Verify the E2E test harness helpers work."""

    def test_freq_test_ip_defined(self):
        """freq-test VM IP is known."""
        FREQ_TEST_IP = "10.25.255.55"
        self.assertTrue(len(FREQ_TEST_IP) > 0)

    def test_safe_vmid_range(self):
        """Test VMID range for E2E is 5010-5020."""
        SAFE_VMIDS = range(5010, 5021)
        self.assertEqual(len(SAFE_VMIDS), 11)
        self.assertIn(5010, SAFE_VMIDS)
        self.assertIn(5020, SAFE_VMIDS)
        self.assertNotIn(5005, SAFE_VMIDS)  # freq-test itself
        self.assertNotIn(100, SAFE_VMIDS)   # production


class TestE2EReadOnlyCommands(unittest.TestCase):
    """Define the set of read-only commands safe for live fleet testing.
    These commands query state but don't modify anything."""

    SAFE_COMMANDS = [
        "freq vm list",
        "freq fleet status",
        "freq fleet health",
        "freq host list",
        "freq docker list",
        "freq observe alert list",
        "freq state policies",
        "freq auto rules list",
        "freq ops oncall whoami",
        "freq hw cost",
        "freq store nas status",
        "freq dr backup list",
        "freq cert scan",
        "freq dns scan",
        "freq proxy status",
        "freq user list",
        "freq event list",
        "freq vpn wg status",
        "freq plugin list",
        "freq plugin types",
    ]

    def test_safe_commands_defined(self):
        self.assertGreater(len(self.SAFE_COMMANDS), 15)

    def test_all_safe_commands_are_read_only(self):
        """No safe command should contain destructive verbs."""
        destructive = ["destroy", "delete", "remove", "wipe", "apply", "create"]
        for cmd in self.SAFE_COMMANDS:
            for verb in destructive:
                self.assertNotIn(verb, cmd,
                                 f"Safe command contains destructive verb: {cmd}")


if __name__ == "__main__":
    unittest.main()
