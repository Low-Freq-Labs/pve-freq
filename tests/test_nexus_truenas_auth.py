"""Tests for nexus/TrueNAS auth model during Phase 8 deploy.

TrueNAS has two distinct auth phases:
1. init reaches TrueNAS with an SSH-capable bootstrap identity, commonly
   ``freq-ops`` plus the fleet key staged in ``[truenas]``.
2. runtime must use the service account created by init, not the bootstrap
   identity and not an API-key-only TrueNAS stanza.

The contract bug this guards against: API-key-only ``[truenas]`` entries
used to let init drift into misleading fallback paths. Core TrueNAS must
either carry SSH bootstrap material or fail with an actionable message.
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
    """TrueNAS auth failures must include actionable SSH-bootstrap hints."""

    def test_source_has_truenas_hint(self):
        """Source code must have the TrueNAS-specific auth-failed hint."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("Core TrueNAS has API credentials only", src)
        self.assertIn("ssh_key_file under [truenas]", src)
        self.assertNotIn("with root user", src)

    def test_hint_only_for_truenas(self):
        """Hint is conditional on htype == 'truenas'."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        import re
        # The hint must be inside an 'if htype == "truenas"' block
        match = re.search(
            r'if htype == "truenas"[^}]*?Core TrueNAS has API credentials only',
            src, re.DOTALL
        )
        self.assertIsNotNone(match)


class TestTruenasDeployerTemplateTruth(unittest.TestCase):
    """TrueNAS deployer must interpolate the real service-account name."""

    def test_no_literal_percent_placeholder_in_failure_message(self):
        src = (FREQ_ROOT / "freq" / "deployers" / "nas" / "truenas.py").read_text()
        self.assertNotIn("Failed to create account '%(svc_name)s'", src)
        self.assertIn("Failed to create account '{svc_name}'", src)

    def test_shell_template_uses_percent_style_placeholders_consistently(self):
        src = (FREQ_ROOT / "freq" / "deployers" / "nas" / "truenas.py").read_text()
        self.assertNotIn('svc_home="/home/{svc_name}"', src)
        self.assertNotIn("echo '{svc_name} ALL=(ALL) NOPASSWD: ALL'", src)
        scale_verify = src.split("test \"$(midclt call user.query", 1)[1].split("elif [ \"$VARIANT\" = \"core\" ]", 1)[0]
        self.assertNotIn("{svc_name}", scale_verify)
        self.assertIn("%(svc_name)s", scale_verify)

    def test_remove_script_has_no_literal_percent_placeholders(self):
        src = (FREQ_ROOT / "freq" / "deployers" / "nas" / "truenas.py").read_text()
        remove_section = src.split("def remove(", 1)[1]
        self.assertNotIn("%(svc_name)s", remove_section)


class TestTruenasRemove(unittest.TestCase):
    """TrueNAS uninstall script should interpolate safely and report success."""

    def test_remove_uses_env_based_script(self):
        from unittest.mock import patch
        from freq.deployers.nas import truenas

        with patch("freq.core.ssh.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "REMOVE_OK\n"
            mock_run.return_value.stderr = ""

            ok, reason = truenas.remove("10.0.0.8", "svc-test", "/tmp/freq_id_ed25519")

        self.assertTrue(ok)
        self.assertEqual(reason, "Account removed")
        command = mock_run.call_args.kwargs["command"]
        self.assertIn("export FREQ_USER=svc-test", command)
        self.assertIn("midclt", command)
        self.assertNotIn("%(svc_name)s", command)


if __name__ == "__main__":
    unittest.main()
