"""Tests for Phase 5 — The Brain (WS12, 15-16).
Covers: Incident CRUD, change CRUD, state export/drift, reactor CRUD, CLI registration.
"""
import json, os, sys, tempfile, unittest
from pathlib import Path
from dataclasses import dataclass
from unittest.mock import MagicMock
from io import StringIO
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).parent.parent))

@dataclass
class MockHost:
    ip: str; label: str; htype: str; groups: str = ""

class MockConfig:
    def __init__(self, tmpdir=None):
        self.conf_dir = tmpdir or tempfile.mkdtemp()
        self.hosts = [MockHost("10.0.0.1", "test", "linux")]
        self.ssh_key_path = "/tmp/test"
        self.ssh_connect_timeout = 5

class TestIncidentCRUD(unittest.TestCase):
    def setUp(self):
        self.cfg = MockConfig(tempfile.mkdtemp())
    def test_create(self):
        from freq.modules.incident import cmd_incident_create
        args = MagicMock(); args.title = "Server down"; args.severity = "critical"
        buf = StringIO()
        with redirect_stdout(buf): rc = cmd_incident_create(self.cfg, None, args)
        self.assertEqual(rc, 0)
        self.assertIn("INC-1", buf.getvalue())
    def test_list_empty(self):
        from freq.modules.incident import cmd_incident_list
        args = MagicMock()
        buf = StringIO()
        with redirect_stdout(buf): rc = cmd_incident_list(self.cfg, None, args)
        self.assertEqual(rc, 0)

class TestChangeCRUD(unittest.TestCase):
    def setUp(self):
        self.cfg = MockConfig(tempfile.mkdtemp())
    def test_create(self):
        from freq.modules.incident import cmd_change_create
        args = MagicMock(); args.title = "Update firewall rules"; args.risk = "medium"
        buf = StringIO()
        with redirect_stdout(buf): rc = cmd_change_create(self.cfg, None, args)
        self.assertEqual(rc, 0)
        self.assertIn("CHG-1", buf.getvalue())

class TestIaCState(unittest.TestCase):
    def setUp(self):
        self.cfg = MockConfig(tempfile.mkdtemp())
    def test_export(self):
        from freq.modules.iac import cmd_state_export
        args = MagicMock()
        buf = StringIO()
        with redirect_stdout(buf): rc = cmd_state_export(self.cfg, None, args)
        self.assertEqual(rc, 0)
    def test_drift_no_snapshot(self):
        from freq.modules.iac import cmd_state_drift
        args = MagicMock()
        buf = StringIO()
        with redirect_stdout(buf): rc = cmd_state_drift(self.cfg, None, args)
        self.assertEqual(rc, 1)  # No snapshot yet
    def test_export_then_drift(self):
        from freq.modules.iac import cmd_state_export, cmd_state_drift
        args = MagicMock()
        buf = StringIO()
        with redirect_stdout(buf):
            cmd_state_export(self.cfg, None, args)
            rc = cmd_state_drift(self.cfg, None, args)
        self.assertEqual(rc, 0)

class TestReactorCRUD(unittest.TestCase):
    def setUp(self):
        self.cfg = MockConfig(tempfile.mkdtemp())
    def test_add(self):
        from freq.modules.automation import cmd_react_add
        args = MagicMock(); args.name = "auto-restart"; args.trigger = "host_down"; args.action = "freq fleet ping"
        args.cooldown = 300
        buf = StringIO()
        with redirect_stdout(buf): rc = cmd_react_add(self.cfg, None, args)
        self.assertEqual(rc, 0)
    def test_list_empty(self):
        from freq.modules.automation import cmd_react_list
        args = MagicMock()
        buf = StringIO()
        with redirect_stdout(buf): rc = cmd_react_list(self.cfg, None, args)
        self.assertEqual(rc, 0)

class TestPhase5Imports(unittest.TestCase):
    def test_incident(self):
        from freq.modules.incident import cmd_incident_create, cmd_incident_list, cmd_incident_update, cmd_change_create, cmd_change_list
        self.assertTrue(callable(cmd_incident_create))
    def test_iac(self):
        from freq.modules.iac import cmd_state_export, cmd_state_drift, cmd_state_history
        self.assertTrue(callable(cmd_state_export))
    def test_automation(self):
        from freq.modules.automation import cmd_react_list, cmd_react_add, cmd_workflow_list, cmd_workflow_create, cmd_job_list
        self.assertTrue(callable(cmd_react_list))

class TestPhase5CLI(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()
    def _parse(self, args_str):
        return self.parser.parse_args(args_str.split())
    def test_incident_list(self):
        self.assertTrue(hasattr(self._parse("ops incident list"), "func"))
    def test_incident_create(self):
        args = self._parse("ops incident create test-incident")
        self.assertEqual(args.title, "test-incident")
    def test_change_list(self):
        self.assertTrue(hasattr(self._parse("ops change list"), "func"))
    def test_state_export(self):
        self.assertTrue(hasattr(self._parse("state export"), "func"))
    def test_state_drift(self):
        self.assertTrue(hasattr(self._parse("state drift"), "func"))
    def test_state_history(self):
        self.assertTrue(hasattr(self._parse("state history"), "func"))
    def test_react_list(self):
        self.assertTrue(hasattr(self._parse("auto react list"), "func"))
    def test_workflow_list(self):
        self.assertTrue(hasattr(self._parse("auto workflow list"), "func"))
    def test_job_list(self):
        self.assertTrue(hasattr(self._parse("auto job"), "func"))

if __name__ == "__main__":
    unittest.main()
