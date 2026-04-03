"""CLI integration tests — verify domain dispatch and all commands are wired correctly.

v3.0.0: Commands use `freq <domain> <action>` dispatch.
"""
import sys
import unittest
from pathlib import Path
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCLIDispatch(unittest.TestCase):
    """Test that all domains and commands are registered and dispatch correctly."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _get_registered(self):
        """Return set of all registered top-level commands/domains."""
        import argparse
        registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        return registered

    def test_parser_builds(self):
        """Parser builds without errors."""
        self.assertIsNotNone(self.parser)

    def test_all_domains_registered(self):
        """All expected domains are registered in the parser."""
        expected_domains = [
            # Top-level utilities
            "version", "help", "doctor", "menu", "demo",
            "init", "configure", "serve", "update", "learn",
            "docs", "distros", "notify", "agent", "specialist", "lab",
            # Domains
            "vm", "fleet", "host", "docker", "secure", "observe",
            "state", "auto", "ops", "hw", "store", "dr", "net",
            "fw", "cert", "dns", "proxy", "media", "user", "event", "vpn",
        ]
        registered = self._get_registered()
        for domain in expected_domains:
            self.assertIn(domain, registered, f"Domain '{domain}' not registered")

    def test_vm_subcommands(self):
        """VM domain has all expected subcommands."""
        args = self.parser.parse_args(["vm", "list"])
        self.assertEqual(args.domain, "vm")
        self.assertEqual(args.subcmd, "list")
        self.assertTrue(hasattr(args, "func"))

    def test_vm_create_args(self):
        args = self.parser.parse_args(["vm", "create", "--name", "test", "--cores", "4", "--ram", "2048"])
        self.assertEqual(args.name, "test")
        self.assertEqual(args.cores, 4)
        self.assertEqual(args.ram, 2048)

    def test_vm_power_preserves_action(self):
        """Power command's action arg is preserved (not overwritten by subcmd)."""
        args = self.parser.parse_args(["vm", "power", "start", "100"])
        self.assertEqual(args.subcmd, "power")
        self.assertEqual(args.action, "start")
        self.assertEqual(args.target, "100")

    def test_vm_snapshot_parses(self):
        args = self.parser.parse_args(["vm", "snapshot", "list", "100"])
        self.assertEqual(args.snap_action, "list")
        self.assertEqual(args.target, "100")

    def test_vm_nic_parses(self):
        args = self.parser.parse_args(["vm", "nic", "add", "100", "--ip", "10.0.0.5/24"])
        self.assertEqual(args.action, "add")
        self.assertEqual(args.target, "100")
        self.assertEqual(args.ip, "10.0.0.5/24")

    def test_fleet_status(self):
        args = self.parser.parse_args(["fleet", "status"])
        self.assertEqual(args.domain, "fleet")
        self.assertEqual(args.subcmd, "status")
        self.assertTrue(hasattr(args, "func"))

    def test_fleet_log_args(self):
        args = self.parser.parse_args(["fleet", "log", "myhost", "--lines", "50", "--unit", "sshd"])
        self.assertEqual(args.target, "myhost")
        self.assertEqual(args.lines, 50)
        self.assertEqual(args.unit, "sshd")

    def test_host_list(self):
        args = self.parser.parse_args(["host", "list"])
        self.assertEqual(args.domain, "host")
        self.assertEqual(args.subcmd, "list")
        self.assertTrue(hasattr(args, "func"))

    def test_host_discover_parses(self):
        args = self.parser.parse_args(["host", "discover", "192.168.1.0/24"])
        self.assertEqual(args.subcmd, "discover")
        self.assertEqual(args.subnet, "192.168.1.0/24")

    def test_docker_stack_parses(self):
        args = self.parser.parse_args(["docker", "stack", "update", "mystack"])
        self.assertEqual(args.domain, "docker")
        self.assertEqual(args.subcmd, "stack")
        self.assertEqual(args.action, "update")
        self.assertEqual(args.name, "mystack")

    def test_secure_vault_subcommands(self):
        for action in ["init", "set", "get", "delete", "list"]:
            args = self.parser.parse_args(["secure", "vault", action])
            self.assertEqual(args.action, action)

    def test_secure_audit_fix(self):
        args = self.parser.parse_args(["secure", "audit", "--fix"])
        self.assertTrue(args.fix)

    def test_observe_alert_check(self):
        args = self.parser.parse_args(["observe", "alert", "check"])
        self.assertEqual(args.domain, "observe")
        self.assertEqual(args.subcmd, "alert")
        self.assertEqual(args.action, "check")

    def test_state_check_policy(self):
        args = self.parser.parse_args(["state", "check", "ssh-hardening", "--hosts", "lab-pve1,lab-pve2"])
        self.assertEqual(args.policy, "ssh-hardening")
        self.assertEqual(args.hosts, "lab-pve1,lab-pve2")

    def test_auto_schedule_parses(self):
        args = self.parser.parse_args(["auto", "schedule", "create", "myjob", "--command", "freq fleet status"])
        self.assertEqual(args.action, "create")
        self.assertEqual(args.name, "myjob")

    def test_ops_risk_parses(self):
        args = self.parser.parse_args(["ops", "risk", "pfsense"])
        self.assertEqual(args.target, "pfsense")

    def test_fw_action(self):
        args = self.parser.parse_args(["fw", "status"])
        self.assertEqual(args.domain, "fw")
        self.assertEqual(args.subcmd, "status")

    def test_cert_parses(self):
        args = self.parser.parse_args(["cert", "scan"])
        self.assertEqual(args.subcmd, "scan")

    def test_dns_parses(self):
        args = self.parser.parse_args(["dns", "check", "myhost"])
        self.assertEqual(args.subcmd, "check")
        self.assertEqual(args.target, "myhost")

    def test_net_ip_parses(self):
        args = self.parser.parse_args(["net", "ip", "next", "--vlan", "mgmt"])
        self.assertEqual(args.action, "next")
        self.assertEqual(args.vlan, "mgmt")

    def test_user_create_parses(self):
        args = self.parser.parse_args(["user", "create", "testuser", "--role", "admin"])
        self.assertEqual(args.subcmd, "create")
        self.assertEqual(args.username, "testuser")
        self.assertEqual(args.role, "admin")

    def test_dr_backup_parses(self):
        args = self.parser.parse_args(["dr", "backup", "list"])
        self.assertEqual(args.action, "list")

    def test_store_nas_parses(self):
        args = self.parser.parse_args(["store", "nas", "status"])
        self.assertEqual(args.action, "status")

    def test_hw_idrac_parses(self):
        args = self.parser.parse_args(["hw", "idrac", "status"])
        self.assertEqual(args.action, "status")

    def test_version_has_func(self):
        args = self.parser.parse_args(["version"])
        self.assertTrue(hasattr(args, "func"))

    def test_help_has_func(self):
        args = self.parser.parse_args(["help"])
        self.assertTrue(hasattr(args, "func"))

    def test_agent_templates_parses(self):
        args = self.parser.parse_args(["agent", "templates"])
        self.assertEqual(args.action, "templates")

    def test_agent_create_parses(self):
        args = self.parser.parse_args(["agent", "create", "dev"])
        self.assertEqual(args.action, "create")
        self.assertEqual(args.name, "dev")

    def test_learn_parses(self):
        args = self.parser.parse_args(["learn", "nfs", "stale"])
        self.assertEqual(args.query, ["nfs", "stale"])

    def test_sweep_fix_flag(self):
        args = self.parser.parse_args(["secure", "sweep", "--fix"])
        self.assertTrue(args.fix)

    def test_patrol_interval(self):
        args = self.parser.parse_args(["auto", "patrol", "--interval", "60"])
        self.assertEqual(args.interval, 60)

    def test_global_flags(self):
        args = self.parser.parse_args(["--debug", "--yes", "version"])
        self.assertTrue(args.debug)
        self.assertTrue(args.yes)

    def test_notify_message(self):
        args = self.parser.parse_args(["notify", "test", "message"])
        self.assertEqual(args.message, ["test", "message"])

    def test_import_args(self):
        args = self.parser.parse_args(["vm", "import", "--image", "debian-13", "--name", "myvm"])
        self.assertEqual(args.image, "debian-13")
        self.assertEqual(args.name, "myvm")

    def test_media_parses(self):
        args = self.parser.parse_args(["media", "status"])
        self.assertEqual(args.action, "status")


class TestCLIOutput(unittest.TestCase):
    """Test that commands produce expected output patterns."""

    def _run_cmd(self, argv):
        """Run a freq command and capture output."""
        from freq.cli import main
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            result = main(argv)
        except SystemExit as e:
            result = e.code or 0
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        return result, output

    def test_version_shows_branding(self):
        result, output = self._run_cmd(["version"])
        self.assertEqual(result, 0)
        self.assertIn("F R E Q", output)

    def test_help_shows_domains(self):
        result, output = self._run_cmd(["help"])
        self.assertEqual(result, 0)
        self.assertIn("freq vm", output)
        self.assertIn("freq fleet", output)
        self.assertIn("freq secure", output)
        self.assertIn("freq doctor", output)

    def test_policies_shows_list(self):
        result, output = self._run_cmd(["state", "policies"])
        self.assertEqual(result, 0)
        self.assertIn("ssh-hardening", output)

    def test_learn_no_query_shows_stats(self):
        result, output = self._run_cmd(["learn"])
        self.assertEqual(result, 0)
        self.assertIn("lessons", output)

    def test_risk_all_shows_map(self):
        result, output = self._run_cmd(["ops", "risk", "all"])
        self.assertEqual(result, 0)
        # Risk map may output ANSI codes — check for "Risk Map" in raw text
        has_risk = "Risk Map" in output or "risk" in output.lower() or "No risk map" in output
        self.assertTrue(has_risk, f"Expected risk output, got: {output[:200]}")

    def test_distros_shows_images(self):
        result, output = self._run_cmd(["distros"])
        self.assertEqual(result, 0)
        self.assertIn("cloud images", output)

    def test_roles_shows_hierarchy(self):
        result, output = self._run_cmd(["user", "roles"])
        self.assertEqual(result, 0)
        self.assertIn("viewer", output)
        self.assertIn("admin", output)

    def test_agent_templates(self):
        result, output = self._run_cmd(["agent", "templates"])
        self.assertEqual(result, 0)
        self.assertIn("infra-manager", output)
        self.assertIn("security-ops", output)

    def test_configure_shows_settings(self):
        result, output = self._run_cmd(["configure"])
        self.assertEqual(result, 0)
        self.assertIn("Version", output)

    def test_notify_no_webhook(self):
        result, output = self._run_cmd(["notify"])
        self.assertEqual(result, 0)
        self.assertIn("not configured", output)

    def test_provision_shows_images(self):
        result, output = self._run_cmd(["vm", "provision"])
        self.assertEqual(result, 0)
        self.assertIn("debian-13", output)


if __name__ == "__main__":
    unittest.main()
