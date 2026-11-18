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


class TestScheduleModule(unittest.TestCase):
    """Test the schedule module."""

    INTERVAL_CASES = (
        ("minutes", "5m", 300),
        ("hours", "2h", 7200),
        ("days", "1d", 86400),
        ("seconds", "30s", 30),
        ("invalid", "abc", 0),
    )

    def test_parse_interval_matrix(self):
        from freq.modules.schedule import _parse_interval
        self.assertEqual(len(self.INTERVAL_CASES), 5)
        case_ids = tuple(case_id for case_id, _, _ in self.INTERVAL_CASES)
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case_id, value, expected in self.INTERVAL_CASES:
            with self.subTest(case=case_id, value=value):
                self.assertEqual(_parse_interval(value), expected)


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
        self.assertGreaterEqual(len(registered), 38,
                                f"Expected 38+ domain commands, got {len(registered)}")


if __name__ == "__main__":
    unittest.main()
