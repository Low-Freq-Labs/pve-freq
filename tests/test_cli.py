"""CLI integration tests — verify all commands are wired and dispatch correctly."""
import sys
import unittest
from pathlib import Path
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCLIDispatch(unittest.TestCase):
    """Test that all commands are registered and dispatch without crashing."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_parser_builds(self):
        """Parser builds without errors."""
        self.assertIsNotNone(self.parser)

    def test_all_commands_registered(self):
        """All expected commands are registered in the parser."""
        expected = [
            # Core
            "version", "help", "doctor", "menu", "demo",
            # Fleet ops
            "status", "dashboard", "exec", "info", "diagnose", "ssh",
            "docker", "log", "keys", "hosts", "discover", "groups",
            "bootstrap", "onboard", "detail", "boundaries",
            # VM management
            "list", "create", "clone", "destroy", "resize", "snapshot",
            "migrate", "vm-overview", "vmconfig", "rescue", "power",
            "nic", "template", "rename", "add-disk", "tag", "pool",
            # Security & users
            "users", "new-user", "passwd", "roles", "promote", "demote",
            "install-user", "vault", "audit", "harden",
            # Infrastructure
            "pfsense", "truenas", "zfs", "switch", "idrac", "media",
            "ntp", "fleet-update", "comms",
            # Compliance
            "health", "watch", "check", "fix", "diff", "policies",
            # Setup
            "init", "configure", "distros",
            # Jarvis / smart commands
            "agent", "learn", "risk", "sweep", "patrol",
            # Utilities
            "notify", "backup", "journal", "provision",
            "import", "update", "serve",
            # Operations
            "sandbox", "file", "specialist", "lab",
            "deploy-agent", "agent-status", "gwipe",
        ]
        # Check parser's registered subcommands directly (avoids
        # required-arg issues with parse_args on commands like 'power')
        import argparse
        registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        for cmd in expected:
            self.assertIn(cmd, registered, f"Command '{cmd}' not registered")

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

    def test_risk_parses(self):
        args = self.parser.parse_args(["risk", "pfsense"])
        self.assertEqual(args.target, "pfsense")

    def test_sweep_fix_flag(self):
        args = self.parser.parse_args(["sweep", "--fix"])
        self.assertTrue(args.fix)

    def test_patrol_interval(self):
        args = self.parser.parse_args(["patrol", "--interval", "60"])
        self.assertEqual(args.interval, 60)

    def test_vault_subcommands(self):
        for action in ["init", "set", "get", "delete", "list"]:
            args = self.parser.parse_args(["vault", action])
            self.assertEqual(args.action, action)

    def test_create_vm_args(self):
        args = self.parser.parse_args(["create", "--name", "test", "--cores", "4", "--ram", "2048"])
        self.assertEqual(args.name, "test")
        self.assertEqual(args.cores, 4)
        self.assertEqual(args.ram, 2048)

    def test_backup_actions(self):
        for action in ["list", "create", "export"]:
            args = self.parser.parse_args(["backup", action])
            self.assertEqual(args.action, action)

    def test_global_flags(self):
        args = self.parser.parse_args(["--debug", "--yes", "version"])
        self.assertTrue(args.debug)
        self.assertTrue(args.yes)

    def test_notify_message(self):
        args = self.parser.parse_args(["notify", "test", "message"])
        self.assertEqual(args.message, ["test", "message"])

    def test_import_args(self):
        args = self.parser.parse_args(["import", "--image", "debian-13", "--name", "myvm"])
        self.assertEqual(args.image, "debian-13")
        self.assertEqual(args.name, "myvm")

    def test_log_args(self):
        args = self.parser.parse_args(["log", "myhost", "--lines", "50", "--unit", "sshd"])
        self.assertEqual(args.target, "myhost")
        self.assertEqual(args.lines, 50)
        self.assertEqual(args.unit, "sshd")

    def test_check_policy_args(self):
        args = self.parser.parse_args(["check", "ssh-hardening", "--hosts", "lab-pve1,lab-pve2"])
        self.assertEqual(args.policy, "ssh-hardening")
        self.assertEqual(args.hosts, "lab-pve1,lab-pve2")


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

    def test_help_shows_commands(self):
        result, output = self._run_cmd(["help"])
        self.assertEqual(result, 0)
        self.assertIn("freq status", output)
        self.assertIn("freq doctor", output)

    def test_policies_shows_list(self):
        result, output = self._run_cmd(["policies"])
        self.assertEqual(result, 0)
        self.assertIn("ssh-hardening", output)

    def test_learn_no_query_shows_stats(self):
        result, output = self._run_cmd(["learn"])
        self.assertEqual(result, 0)
        self.assertIn("lessons", output)

    def test_risk_all_shows_map(self):
        result, output = self._run_cmd(["risk", "all"])
        self.assertEqual(result, 0)
        self.assertIn("pfsense", output)
        self.assertIn("CRITICAL", output)

    def test_distros_shows_images(self):
        result, output = self._run_cmd(["distros"])
        self.assertEqual(result, 0)
        self.assertIn("cloud images", output)

    def test_roles_shows_hierarchy(self):
        result, output = self._run_cmd(["roles"])
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
        result, output = self._run_cmd(["provision"])
        self.assertEqual(result, 0)
        self.assertIn("debian-13", output)


if __name__ == "__main__":
    unittest.main()
