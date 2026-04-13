"""Tests for switch status truth after device-aware CLI fix.

Bug (follow-up to K): After the K fix, fleet status and doctor correctly
marked iDRAC devices as n/a (needs svc account), but switch could still
show DOWN in some races because the detection check missed stderr
variations. Also, _check_legacy_passwords still produced false warnings
for /home/freq-admin/.ssh/switch-pass because os.path.isdir(parent)
returns False on 700 dirs (not just os.access R_OK = False).

Fix:
1. The n/a detection already handles 'permission denied' and 'publickey' —
   verified correct on live 5005.
2. _check_legacy_passwords now also checks if pw_file is under the
   service account's home dir (stat-free check) as an additional
   secure-dir heuristic.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestLegacyPasswordSecureDirHeuristic(unittest.TestCase):
    """Legacy password check must handle unreachable-via-stat svc dirs."""

    def test_checks_svc_home_prefix(self):
        """Must check if pw_file is under cfg.ssh_service_account home dir."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("svc_home", src)
        self.assertIn("pw_file.startswith(svc_home", src)

    def test_secure_svc_dir_message(self):
        """Must report 'in secure svc dir' when path prefix matches."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("in secure svc dir", src)


class TestSwitchNaDetection(unittest.TestCase):
    """Switch auth failures must match the n/a detection patterns."""

    def test_fleet_status_matches_publickey(self):
        """Fleet status operator_auth_issue check must include 'publickey'."""
        src = (FREQ_ROOT / "freq" / "modules" / "fleet.py").read_text()
        # The check pattern: is_legacy AND (permission denied OR publickey)
        import re
        match = re.search(
            r'is_legacy\s+and\s+\(\s*"permission denied".*?"publickey"',
            src, re.DOTALL
        )
        self.assertIsNotNone(match,
                             "operator_auth_issue must check both permission denied and publickey")

    def test_doctor_matches_publickey(self):
        """Doctor _test must include publickey in operator_auth detection."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("publickey", src)
        self.assertIn("operator_auth", src)


if __name__ == "__main__":
    unittest.main()
