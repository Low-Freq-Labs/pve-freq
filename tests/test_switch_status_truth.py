"""Tests for switch status truth after device-aware CLI fix.

Bug (follow-up to K): After the K fix, fleet status and doctor correctly
marked iDRAC devices as n/a (needs svc account), but switch could still
show DOWN in some races because the detection check missed stderr
variations. Also, _check_legacy_passwords still produced false warnings
for the service account legacy-device password file because os.path.isdir(parent)
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
        from types import SimpleNamespace

        from freq.core.types import CmdResult
        from freq.services.fleet_status import classify_fleet_results

        host = SimpleNamespace(label="switch", ip="10.25.255.5", htype="switch")
        result = CmdResult(
            returncode=255,
            stdout="",
            stderr="publickey authentication failed",
            duration=0.1,
        )
        entry = classify_fleet_results([(host, result)], {}, probed_at=100.0)[0]

        self.assertEqual(entry["state"], "auth_failed")
        self.assertTrue(entry["operator_auth_issue"])

    def test_doctor_matches_publickey(self):
        """Doctor _test must include publickey in operator_auth detection."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("publickey", src)
        self.assertIn("operator_auth", src)


if __name__ == "__main__":
    unittest.main()
