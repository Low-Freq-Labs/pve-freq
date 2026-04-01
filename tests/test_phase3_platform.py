"""Phase 3 Platform Play — Tests.

Tests for: schedule, backup-policy, webhook, migrate-plan, migrate-vmware
5 commands that turn freq from a tool into infrastructure.
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


class TestPhase3Registration(unittest.TestCase):
    """Verify all Phase 3 commands are registered."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()
        self.registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                self.registered.update(action.choices.keys())

    def test_schedule_registered(self):
        self.assertIn("schedule", self.registered)

    def test_backup_policy_registered(self):
        self.assertIn("backup-policy", self.registered)

    def test_webhook_registered(self):
        self.assertIn("webhook", self.registered)

    def test_migrate_plan_registered(self):
        self.assertIn("migrate-plan", self.registered)

    def test_migrate_vmware_registered(self):
        self.assertIn("migrate-vmware", self.registered)


class TestPhase3Parsing(unittest.TestCase):
    """Verify argument parsing for Phase 3 commands."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_schedule_default(self):
        args = self.parser.parse_args(["schedule"])
        self.assertEqual(args.action, "list")
        self.assertTrue(hasattr(args, "func"))

    def test_schedule_create(self):
        args = self.parser.parse_args([
            "schedule", "create", "my-job",
            "--command", "freq trend snapshot",
            "--interval", "2h",
        ])
        self.assertEqual(args.action, "create")
        self.assertEqual(args.name, "my-job")
        self.assertEqual(args.command, "freq trend snapshot")
        self.assertEqual(args.interval, "2h")

    def test_schedule_templates(self):
        args = self.parser.parse_args(["schedule", "templates"])
        self.assertEqual(args.action, "templates")

    def test_backup_policy_default(self):
        args = self.parser.parse_args(["backup-policy"])
        self.assertEqual(args.action, "list")
        self.assertTrue(hasattr(args, "func"))

    def test_backup_policy_create(self):
        args = self.parser.parse_args([
            "backup-policy", "create", "prod-daily",
            "--target", "prod", "--retention", "14",
        ])
        self.assertEqual(args.action, "create")
        self.assertEqual(args.name, "prod-daily")
        self.assertEqual(args.target, "prod")
        self.assertEqual(args.retention, 14)

    def test_backup_policy_apply(self):
        args = self.parser.parse_args(["backup-policy", "apply"])
        self.assertEqual(args.action, "apply")

    def test_webhook_default(self):
        args = self.parser.parse_args(["webhook"])
        self.assertEqual(args.action, "list")
        self.assertTrue(hasattr(args, "func"))

    def test_webhook_create(self):
        args = self.parser.parse_args([
            "webhook", "create", "deploy-hook",
            "--command", "freq gitops sync",
        ])
        self.assertEqual(args.action, "create")
        self.assertEqual(args.name, "deploy-hook")
        self.assertEqual(args.command, "freq gitops sync")

    def test_webhook_test(self):
        args = self.parser.parse_args(["webhook", "test", "my-hook"])
        self.assertEqual(args.action, "test")
        self.assertEqual(args.name, "my-hook")

    def test_migrate_plan_default(self):
        args = self.parser.parse_args(["migrate-plan"])
        self.assertEqual(args.action, "show")
        self.assertTrue(hasattr(args, "func"))

    def test_migrate_vmware_default(self):
        args = self.parser.parse_args(["migrate-vmware"])
        self.assertEqual(args.action, "scan")
        self.assertTrue(hasattr(args, "func"))

    def test_migrate_vmware_import(self):
        args = self.parser.parse_args([
            "migrate-vmware", "import", "/tmp/vm.ova",
            "--vmid", "200", "--node", "pve01",
        ])
        self.assertEqual(args.action, "import")
        self.assertEqual(args.target, "/tmp/vm.ova")
        self.assertEqual(args.vmid, 200)
        self.assertEqual(args.node, "pve01")

    def test_migrate_vmware_status(self):
        args = self.parser.parse_args(["migrate-vmware", "status"])
        self.assertEqual(args.action, "status")


class TestScheduleModule(unittest.TestCase):
    """Test the schedule module."""

    def test_import(self):
        from freq.modules.schedule import cmd_schedule
        self.assertTrue(callable(cmd_schedule))

    def test_parse_interval_minutes(self):
        from freq.modules.schedule import _parse_interval
        self.assertEqual(_parse_interval("5m"), 300)

    def test_parse_interval_hours(self):
        from freq.modules.schedule import _parse_interval
        self.assertEqual(_parse_interval("2h"), 7200)

    def test_parse_interval_days(self):
        from freq.modules.schedule import _parse_interval
        self.assertEqual(_parse_interval("1d"), 86400)

    def test_parse_interval_seconds(self):
        from freq.modules.schedule import _parse_interval
        self.assertEqual(_parse_interval("30s"), 30)

    def test_parse_interval_invalid(self):
        from freq.modules.schedule import _parse_interval
        self.assertEqual(_parse_interval("abc"), 0)

    def test_job_templates(self):
        from freq.modules.schedule import JOB_TEMPLATES
        self.assertIn("trend-snapshot", JOB_TEMPLATES)
        self.assertIn("sla-check", JOB_TEMPLATES)
        self.assertIn("alert-check", JOB_TEMPLATES)
        self.assertGreaterEqual(len(JOB_TEMPLATES), 4)

    def test_jobs_roundtrip(self):
        from freq.modules.schedule import _load_jobs, _save_jobs
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            jobs = [{"name": "test", "command": "echo hi", "interval": "5m"}]
            _save_jobs(cfg, jobs)
            loaded = _load_jobs(cfg)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["name"], "test")


class TestBackupPolicyModule(unittest.TestCase):
    """Test the backup-policy module."""

    def test_import(self):
        from freq.modules.backup_policy import cmd_backup_policy
        self.assertTrue(callable(cmd_backup_policy))

    def test_policies_roundtrip(self):
        from freq.modules.backup_policy import _load_policies, _save_policies
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            policies = [{"name": "prod", "target": "prod", "retention": 7}]
            _save_policies(cfg, policies)
            loaded = _load_policies(cfg)
            self.assertEqual(len(loaded), 1)

    def test_state_roundtrip(self):
        from freq.modules.backup_policy import _load_state, _save_state
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            state = {"last_run": "now", "snapshots_created": 5, "snapshots_pruned": 2}
            _save_state(cfg, state)
            loaded = _load_state(cfg)
            self.assertEqual(loaded["snapshots_created"], 5)


class TestWebhookModule(unittest.TestCase):
    """Test the webhook module."""

    def test_import(self):
        from freq.modules.webhook import cmd_webhook
        self.assertTrue(callable(cmd_webhook))

    def test_generate_token(self):
        from freq.modules.webhook import _generate_token
        token = _generate_token()
        self.assertEqual(len(token), 32)
        # Should be different each time
        token2 = _generate_token()
        self.assertNotEqual(token, token2)

    def test_verify_signature_no_secret(self):
        from freq.modules.webhook import _verify_signature
        self.assertTrue(_verify_signature(b"test", "", ""))

    def test_hooks_roundtrip(self):
        from freq.modules.webhook import _load_hooks, _save_hooks
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            hooks = [{"name": "deploy", "command": "echo deploy", "token": "abc123"}]
            _save_hooks(cfg, hooks)
            loaded = _load_hooks(cfg)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["name"], "deploy")

    def test_handle_webhook_unknown(self):
        from freq.modules.webhook import handle_webhook_request
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            result = handle_webhook_request(cfg, "nonexistent", "token")
            self.assertEqual(result["status"], 404)


class TestMigratePlanModule(unittest.TestCase):
    """Test the migrate-plan module."""

    def test_import(self):
        from freq.modules.migrate_plan import cmd_migrate_plan
        self.assertTrue(callable(cmd_migrate_plan))

    def test_generate_recommendations_balanced(self):
        from freq.modules.migrate_plan import _generate_recommendations
        nodes = [
            {"node": "pve01", "mem_pct": 50, "maxmem": 64*1024*1024*1024},
            {"node": "pve02", "mem_pct": 52, "maxmem": 64*1024*1024*1024},
        ]
        vms = [{"vmid": 100, "name": "test", "node": "pve01", "mem_mb": 2048, "mem_bytes": 2*1024*1024*1024}]
        recs = _generate_recommendations(nodes, vms)
        # Balanced fleet — no recommendations
        self.assertEqual(len(recs), 0)

    def test_generate_recommendations_imbalanced(self):
        from freq.modules.migrate_plan import _generate_recommendations
        nodes = [
            {"node": "pve01", "mem_pct": 92, "maxmem": 64*1024*1024*1024},
            {"node": "pve02", "mem_pct": 30, "maxmem": 64*1024*1024*1024},
        ]
        vms = [
            {"vmid": 100, "name": "heavy", "node": "pve01", "mem_mb": 4096,
             "mem_bytes": 4*1024*1024*1024},
        ]
        recs = _generate_recommendations(nodes, vms)
        self.assertGreater(len(recs), 0)
        self.assertEqual(recs[0]["to_node"], "pve02")


class TestMigrateVmwareModule(unittest.TestCase):
    """Test the migrate-vmware module."""

    def test_import(self):
        from freq.modules.migrate_vmware import cmd_migrate_vmware
        self.assertTrue(callable(cmd_migrate_vmware))

    def test_disk_formats(self):
        from freq.modules.migrate_vmware import DISK_FORMATS
        self.assertIn("vmdk", DISK_FORMATS)
        self.assertIn("ova", DISK_FORMATS)
        self.assertIn("ovf", DISK_FORMATS)
        self.assertIn("qcow2", DISK_FORMATS)

    def test_state_roundtrip(self):
        from freq.modules.migrate_vmware import _load_state, _save_state
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            state = {"scans": [{"dir": "/tmp"}], "imports": []}
            _save_state(cfg, state)
            loaded = _load_state(cfg)
            self.assertEqual(len(loaded["scans"]), 1)


class TestPhase3CommandCount(unittest.TestCase):
    """Verify command count."""

    def test_command_count_at_least_114(self):
        """Phase 2 (109) + Phase 3 (5) = 114+."""
        from freq.cli import _build_parser
        parser = _build_parser()
        registered = set()
        for action in parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertGreaterEqual(len(registered), 114,
                                f"Expected 114+ commands, got {len(registered)}")


class TestPhase3Dispatch(unittest.TestCase):
    """Verify all Phase 3 commands dispatch."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_schedule_has_func(self):
        args = self.parser.parse_args(["schedule"])
        self.assertTrue(hasattr(args, "func"))

    def test_backup_policy_has_func(self):
        args = self.parser.parse_args(["backup-policy"])
        self.assertTrue(hasattr(args, "func"))

    def test_webhook_has_func(self):
        args = self.parser.parse_args(["webhook"])
        self.assertTrue(hasattr(args, "func"))

    def test_migrate_plan_has_func(self):
        args = self.parser.parse_args(["migrate-plan"])
        self.assertTrue(hasattr(args, "func"))

    def test_migrate_vmware_has_func(self):
        args = self.parser.parse_args(["migrate-vmware"])
        self.assertTrue(hasattr(args, "func"))


if __name__ == "__main__":
    unittest.main()
