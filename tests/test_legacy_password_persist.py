"""Tests for legacy password file persistence — must use svc_pass not device_pass.

Bug: Phase 8 deploy persisted the DEVICE auth password (what init used to
connect to the switch via --device-credentials) to /home/freq-admin/.ssh/switch-pass.
But after deploy, the switch has freq-admin configured with ctx['svc_pass']
as the password, NOT the device auth password. Phase 12 sshpass fallback
tried the wrong password → 'sshpass exit 5 wrong password' → switch marked
as verification failure → init reports NOT initialized.

Fix: Both headless and interactive deploy paths now persist ctx['svc_pass']
as the legacy password. That's the password that actually works for
freq-admin on the device after deploy.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestLegacyPasswordUsesSvcPass(unittest.TestCase):
    """_persist_legacy_password_file must be called with svc_pass."""

    def test_headless_uses_svc_pass(self):
        """_headless_fleet_deploy persists svc_pass, not device_creds password."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Find the headless Persist block
        idx = src.find("Persist the SERVICE ACCOUNT password")
        self.assertNotEqual(idx, -1, "Must have 'SERVICE ACCOUNT password' comment")
        block = src[idx:idx + 1500]
        self.assertIn("svc_pass_value", block)
        self.assertIn('ctx.get("svc_pass"', block)

    def test_interactive_uses_svc_pass(self):
        """_phase_fleet_deploy also persists svc_pass, not legacy_passwords set."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Should have svc_pass_value used in both paths
        count = src.count('svc_pass_value = ctx.get("svc_pass"')
        self.assertGreaterEqual(count, 2,
                                "Both deploy paths must use svc_pass_value for persist")

    def test_not_using_device_creds_password(self):
        """Persist block must NOT use device_creds[...]['password']."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # The old pattern was: device_passwords = {device_creds[t['htype']]['password'] ...}
        # used in a _persist_legacy_password_file call
        import re
        bad = re.search(
            r"_persist_legacy_password_file\s*\(\s*cfg\s*,\s*[^,]+\s*,\s*next\(iter\(device_passwords\)\)",
            src
        )
        self.assertIsNone(bad,
                          "_persist_legacy_password_file must not use device_passwords set")

    def test_not_using_legacy_passwords_set(self):
        """Interactive path must not use the legacy_passwords set for persist."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        import re
        bad = re.search(
            r"_persist_legacy_password_file\s*\(\s*cfg\s*,\s*ctx\[\"svc_name\"\]\s*,\s*next\(iter\(legacy_passwords\)\)",
            src
        )
        self.assertIsNone(bad,
                          "_persist_legacy_password_file must not use legacy_passwords set")


if __name__ == "__main__":
    unittest.main()
