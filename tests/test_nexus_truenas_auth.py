"""Tests for nexus/TrueNAS auth model during Phase 8 deploy.

Bug: Clean-5005 init skipped nexus with generic "auth failed". The
device-creds.toml had no [truenas] section. Headless deploy fell
through to bootstrap credentials (freq-ops@bootstrap_pass), which
don't exist on TrueNAS (it uses root + its own password). The error
message didn't tell the operator what to do.

Fixes:
1. _read_entry accepts both 'user' and 'username' as key for account name
   (parser tolerance — E2E device-creds.toml uses 'username')
2. When TrueNAS deploy fails with auth failed, message includes hint
   to add [truenas] to --device-credentials
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestReadEntryUsernameAlias(unittest.TestCase):
    """_load_device_credentials must accept 'username' as alias for 'user'."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-nexus-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_username_alias_honored(self):
        """A TOML entry using 'username' must be parsed like 'user'."""
        from freq.modules.init_cmd import _load_device_credentials
        cred_file = self._write("creds.toml", """
[switch]
username = "gigecolo"
password = "switchpass"
""")
        result = _load_device_credentials(cred_file)
        self.assertIn("switch", result)
        self.assertEqual(result["switch"]["user"], "gigecolo")

    def test_user_still_works(self):
        """The canonical 'user' key still works."""
        from freq.modules.init_cmd import _load_device_credentials
        cred_file = self._write("creds.toml", """
[switch]
user = "admin"
password = "switchpass"
""")
        result = _load_device_credentials(cred_file)
        self.assertEqual(result["switch"]["user"], "admin")

    def test_user_beats_username_when_both_present(self):
        """If both 'user' and 'username' exist, 'user' wins."""
        from freq.modules.init_cmd import _load_device_credentials
        cred_file = self._write("creds.toml", """
[switch]
user = "preferred"
username = "legacy"
password = "pw"
""")
        result = _load_device_credentials(cred_file)
        self.assertEqual(result["switch"]["user"], "preferred")


class TestTruenasAuthFailedMessage(unittest.TestCase):
    """TrueNAS auth failures must include actionable device-credentials hint."""

    def test_source_has_truenas_hint(self):
        """Source code must have the TrueNAS-specific auth-failed hint."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("add [truenas] to --device-credentials", src)

    def test_hint_only_for_truenas(self):
        """Hint is conditional on htype == 'truenas'."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        import re
        # The hint must be inside an 'if htype == "truenas"' block
        match = re.search(
            r'if htype == "truenas"[^}]*?add \[truenas\]',
            src, re.DOTALL
        )
        self.assertIsNotNone(match)


if __name__ == "__main__":
    unittest.main()
