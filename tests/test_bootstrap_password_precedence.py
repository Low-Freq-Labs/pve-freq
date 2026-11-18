"""Tests for bootstrap password precedence — explicit password must not be overridden by key.

Bug: Headless init auto-detected bootstrap SSH key even when
--bootstrap-password-file was explicitly provided. This silently
switched from password-first auth to key auth, contaminating the
E2E password-first test path.

Root cause: Key auto-detection ran unconditionally when --bootstrap-key
was absent, regardless of whether --bootstrap-password-file was given.

Fix: Key auto-detection only runs when BOTH --bootstrap-key and
--bootstrap-password-file are absent. When a password is provided,
password-first is honored.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestPasswordFirstPrecedence(unittest.TestCase):
    """Explicit bootstrap password must prevent key auto-detection."""

    def test_key_autodetect_requires_no_password(self):
        """Key auto-detection must be guarded by 'not bootstrap_pass'."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("not bootstrap_key and not bootstrap_pass", src)

    def test_no_unconditional_key_autodetect(self):
        """Must NOT have 'if not bootstrap_key:' without password check."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        import re
        # The old pattern was: if not bootstrap_key:\n        for candidate in [
        # The new pattern must include: and not bootstrap_pass
        bad_pattern = re.search(
            r'if not bootstrap_key:\s+for candidate in \[',
            src
        )
        self.assertIsNone(bad_pattern,
                          "Key auto-detection must be guarded by 'not bootstrap_pass'")

    def test_banner_reports_password_when_no_key(self):
        """Banner must show 'via password' when no key is set."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("via password (sshpass)", src)


if __name__ == "__main__":
    unittest.main()
