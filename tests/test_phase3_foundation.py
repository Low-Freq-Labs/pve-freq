"""Tests for Phase 3 — The Foundation: Storage + DR.

Covers: Module imports, CLI registration, SLA target CRUD, runbook CRUD,
        storage target resolution.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import dataclass
from unittest.mock import MagicMock
from io import StringIO
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class MockHost:
    ip: str
    label: str
    htype: str
    groups: str = ""


class MockConfig:
    def __init__(self, tmpdir=None):
        self.conf_dir = tmpdir or tempfile.mkdtemp()
        self.hosts = [
            MockHost("10.25.255.25", "truenas", "truenas"),
            MockHost("10.25.255.26", "pve01", "pve"),
        ]
        self.truenas_ip = "10.25.255.25"
        self.pfsense_ip = ""
        self.switch_ip = ""
        self.ssh_key_path = "/tmp/test"
        self.ssh_rsa_key_path = ""
        self.ssh_connect_timeout = 5


# ---------------------------------------------------------------------------
# Storage Tests
# ---------------------------------------------------------------------------

class TestStorageImports(unittest.TestCase):
    def test_all_commands(self):
        from freq.modules.storage import (
            cmd_store_status, cmd_store_pools, cmd_store_datasets,
            cmd_store_snapshots, cmd_store_smart, cmd_store_shares,
            cmd_store_alerts,
        )
        self.assertTrue(callable(cmd_store_status))

    def test_resolve_target_default(self):
        from freq.modules.storage import _resolve_storage_target
        cfg = MockConfig()
        ip = _resolve_storage_target(None, cfg)
        self.assertEqual(ip, "10.25.255.25")

    def test_resolve_target_by_label(self):
        from freq.modules.storage import _resolve_storage_target
        cfg = MockConfig()
        ip = _resolve_storage_target("pve01", cfg)
        self.assertEqual(ip, "10.25.255.26")

    def test_resolve_target_by_ip(self):
        from freq.modules.storage import _resolve_storage_target
        cfg = MockConfig()
        ip = _resolve_storage_target("192.168.1.1", cfg)
        self.assertEqual(ip, "192.168.1.1")


# ---------------------------------------------------------------------------
# DR Tests
# ---------------------------------------------------------------------------

class TestDRSLATargets(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = MockConfig(self.tmpdir)

    def test_empty_load(self):
        from freq.modules.dr import _load_sla_targets
        data = _load_sla_targets(self.cfg)
        self.assertEqual(data["targets"], [])

    def test_save_and_load(self):
        from freq.modules.dr import _load_sla_targets, _save_sla_targets
        data = {"targets": [{"vmid": 100, "name": "test", "rpo_hours": 24, "rto_hours": 4}]}
        _save_sla_targets(self.cfg, data)
        reloaded = _load_sla_targets(self.cfg)
        self.assertEqual(len(reloaded["targets"]), 1)
        self.assertEqual(reloaded["targets"][0]["vmid"], 100)

    def test_cmd_sla_set(self):
        from freq.modules.dr import cmd_dr_sla_set
        args = MagicMock()
        args.vmid = "100"
        args.rpo = 12
        args.rto = 2
        args.name = "plex"
        args.tier = "critical"
        args.priority = 1

        buf = StringIO()
        with redirect_stdout(buf):
            rc = cmd_dr_sla_set(self.cfg, None, args)
        self.assertEqual(rc, 0)

        from freq.modules.dr import _load_sla_targets
        data = _load_sla_targets(self.cfg)
        self.assertEqual(len(data["targets"]), 1)
        self.assertEqual(data["targets"][0]["rpo_hours"], 12)

    def test_cmd_sla_set_update(self):
        from freq.modules.dr import cmd_dr_sla_set, _load_sla_targets
        args = MagicMock()
        args.vmid = "100"
        args.rpo = 24
        args.rto = 4
        args.name = "test"
        args.tier = "standard"
        args.priority = 50

        buf = StringIO()
        with redirect_stdout(buf):
            cmd_dr_sla_set(self.cfg, None, args)

        # Update
        args.rpo = 8
        with redirect_stdout(buf):
            cmd_dr_sla_set(self.cfg, None, args)

        data = _load_sla_targets(self.cfg)
        self.assertEqual(len(data["targets"]), 1)
        self.assertEqual(data["targets"][0]["rpo_hours"], 8)


class TestDRRunbooks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = MockConfig(self.tmpdir)

    def test_create_runbook(self):
        from freq.modules.dr import cmd_dr_runbook_create, _load_runbook
        args = MagicMock()
        args.name = "full-recovery"
        args.description = "Full site recovery"

        buf = StringIO()
        with redirect_stdout(buf):
            rc = cmd_dr_runbook_create(self.cfg, None, args)
        self.assertEqual(rc, 0)

        rb = _load_runbook(self.cfg, "full-recovery")
        self.assertIsNotNone(rb)
        self.assertEqual(len(rb["steps"]), 5)

    def test_create_duplicate_fails(self):
        from freq.modules.dr import cmd_dr_runbook_create, _save_runbook
        _save_runbook(self.cfg, "existing", {"name": "existing", "steps": []})

        args = MagicMock()
        args.name = "existing"
        args.description = ""

        buf = StringIO()
        with redirect_stdout(buf):
            rc = cmd_dr_runbook_create(self.cfg, None, args)
        self.assertEqual(rc, 1)

    def test_load_nonexistent(self):
        from freq.modules.dr import _load_runbook
        self.assertIsNone(_load_runbook(self.cfg, "nope"))

    def test_runbook_list_empty(self):
        from freq.modules.dr import cmd_dr_runbook_list
        args = MagicMock()
        buf = StringIO()
        with redirect_stdout(buf):
            rc = cmd_dr_runbook_list(self.cfg, None, args)
        self.assertEqual(rc, 0)


class TestDRStatusCommand(unittest.TestCase):
    def test_dr_status(self):
        from freq.modules.dr import cmd_dr_status
        cfg = MockConfig(tempfile.mkdtemp())
        args = MagicMock()
        buf = StringIO()
        with redirect_stdout(buf):
            rc = cmd_dr_status(cfg, None, args)
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# CLI Registration Tests
# ---------------------------------------------------------------------------

class TestPhase3CLIRegistration(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _parse(self, args_str):
        return self.parser.parse_args(args_str.split())

    # Storage
    def test_store_status(self):
        args = self._parse("store status")
        self.assertTrue(hasattr(args, "func"))

    def test_store_pools(self):
        args = self._parse("store pools")
        self.assertTrue(hasattr(args, "func"))

    def test_store_pools_target(self):
        args = self._parse("store pools pve01")
        self.assertEqual(args.target, "pve01")

    def test_store_datasets(self):
        args = self._parse("store datasets")
        self.assertTrue(hasattr(args, "func"))

    def test_store_snapshots(self):
        args = self._parse("store snapshots")
        self.assertTrue(hasattr(args, "func"))

    def test_store_smart(self):
        args = self._parse("store smart")
        self.assertTrue(hasattr(args, "func"))

    def test_store_shares(self):
        args = self._parse("store shares")
        self.assertTrue(hasattr(args, "func"))

    def test_store_alerts(self):
        args = self._parse("store alerts")
        self.assertTrue(hasattr(args, "func"))

    # DR
    def test_dr_status(self):
        args = self._parse("dr status")
        self.assertTrue(hasattr(args, "func"))

    def test_dr_verify(self):
        args = self._parse("dr verify")
        self.assertTrue(hasattr(args, "func"))

    def test_dr_sla_list(self):
        args = self._parse("dr sla list")
        self.assertTrue(hasattr(args, "func"))

    def test_dr_sla_set(self):
        args = self._parse("dr sla set 100 --rpo 12 --rto 2")
        self.assertEqual(args.vmid, "100")
        self.assertEqual(args.rpo, 12)
        self.assertEqual(args.rto, 2)

    def test_dr_runbook_list(self):
        args = self._parse("dr runbook list")
        self.assertTrue(hasattr(args, "func"))

    def test_dr_runbook_create(self):
        args = self._parse("dr runbook create full-recovery")
        self.assertEqual(args.name, "full-recovery")

    def test_dr_runbook_show(self):
        args = self._parse("dr runbook show full-recovery")
        self.assertEqual(args.name, "full-recovery")


if __name__ == "__main__":
    unittest.main()
