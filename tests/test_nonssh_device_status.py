"""Tests for non-SSH device status contract — doctor/fleet-status honesty.

Bug: After a successful init that deployed freq-admin to bmc/switch,
freq doctor and freq fleet status marked them DOWN because:
1. Fleet status ran generic 'uptime' against all hosts (iDRAC/switch
   don't have uptime — only racadm/IOS commands work)
2. Even with device-appropriate commands, operator CLI couldn't read
   the service account's RSA key (700 dir perm) and fell back to the
   operator's personal key which isn't deployed

API /api/health runs as freq-admin and correctly showed the devices
healthy. CLI lied.

Fix:
1. Fleet status splits hosts by htype and runs device-appropriate
   verify commands (same dict as doctor).
2. When a legacy device fails with 'permission denied', mark it as
   'n/a (needs svc account)' instead of 'down'. This is operator-context
   mismatch, not a real outage.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestFleetStatusDeviceCommands(unittest.TestCase):
    """cmd_status must use device-appropriate verify commands."""

    def test_has_verify_cmds_dict(self):
        """cmd_status must define VERIFY_CMDS with per-htype commands."""
        src = (FREQ_ROOT / "freq" / "modules" / "fleet.py").read_text()
        self.assertIn("VERIFY_CMDS", src)
        self.assertIn('"idrac": "racadm getsysinfo', src)
        self.assertIn('"switch": "show version', src)

    def test_splits_hosts_by_command(self):
        """cmd_status must split by command and run separate batches."""
        src = (FREQ_ROOT / "freq" / "modules" / "fleet.py").read_text()
        self.assertIn("by_cmd = defaultdict(list)", src)

    def test_legacy_uses_rsa_key(self):
        """Legacy device batches must use cfg.ssh_rsa_key_path."""
        src = (FREQ_ROOT / "freq" / "modules" / "fleet.py").read_text()
        self.assertIn("cfg.ssh_rsa_key_path or cfg.ssh_key_path", src)


class TestOperatorAuthMismatchNotDown(unittest.TestCase):
    """Legacy device permission-denied must not count as DOWN."""

    def test_fleet_status_marks_na(self):
        """fleet cmd_status must distinguish n/a from down for legacy devices."""
        src = (FREQ_ROOT / "freq" / "modules" / "fleet.py").read_text()
        self.assertIn("operator_auth_issue", src)
        self.assertIn("needs svc account", src)
        self.assertIn("n/a", src)

    def test_doctor_marks_na(self):
        """doctor _test must return operator_auth flag for legacy auth failures."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("operator_auth", src)
        self.assertIn("need svc account", src)

    def test_doctor_excludes_na_from_total(self):
        """doctor must use total_checkable (total - na) for the reachable ratio."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("total_checkable", src)


if __name__ == "__main__":
    unittest.main()
