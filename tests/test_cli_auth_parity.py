"""Tests for CLI auth parity — post-init CLI must use service account key.

Bug: After green init, freq init --check and freq fleet status failed
for legacy devices and self-host because _detect_ssh_key resolved to
the operator's personal key (~freq-ops/.ssh/id_ed25519) instead of the
service account's deployed key (~freq-admin/.ssh/id_ed25519).

Root cause: data/keys/ is 700 owned by freq-admin. When freq-ops runs
CLI commands, _detect_ssh_key can't read freq_id_ed25519 through the
700 dir and falls back to the current user's ~/.ssh/id_ed25519.
The operator's key is NOT deployed to fleet hosts — only freq-admin's is.

Fix: _detect_ssh_key now checks the service account's home dir keys
before the current user's home. Service account's key was synced there
by init Phase 4 and may be readable via group permissions.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestKeyDetectionPriority(unittest.TestCase):
    """_detect_ssh_key must prefer service account's key over operator's."""

    def test_service_account_key_in_candidates(self):
        """Service account home dir key must be in candidate list."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        self.assertIn("svc_home", src)
        self.assertIn('os.path.join(svc_home, ".ssh", "id_ed25519")', src)

    def test_service_account_before_current_user(self):
        """Service account key must be checked BEFORE current user's key."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        # svc_home key should appear before expanduser key in the candidates list
        svc_pos = src.find('os.path.join(svc_home, ".ssh", "id_ed25519")')
        user_pos = src.find('os.path.expanduser("~/.ssh/id_ed25519")')
        self.assertGreater(user_pos, svc_pos,
                           "Service account key must be before current user's key in priority")

    def test_rsa_key_also_checks_service_account(self):
        """_detect_rsa_key must also check service account home."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        self.assertIn('os.path.join(svc_home, ".ssh", "id_rsa")', src)


if __name__ == "__main__":
    unittest.main()
