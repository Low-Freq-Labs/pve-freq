"""Tests for device credentials contract — --device-credentials TOML loading.

Bug: _load_device_credentials only supported password_file (path to file
containing password). When the TOML had inline password values or when
password_file paths didn't exist, credentials silently failed to load.
This caused _headless_fleet_deploy to skip idrac/switch with
"No device credentials for X — skipping" even though --device-credentials
was explicitly provided.

Root cause: _read_entry() only checked entry.get("password_file", "").
If password_file was missing or unreadable and no inline password was
available, the credential was silently dropped from the result dict.

Fix: _read_entry() now supports both password_file (priority) and inline
password. When password_file is unreadable but inline password exists,
it falls back to inline with a warning.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestReadEntrySupportsInlinePassword(unittest.TestCase):
    """_read_entry must accept inline password, not just password_file."""

    def test_source_supports_inline_password(self):
        """_read_entry must read entry.get('password', '') for inline fallback."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # The _read_entry function must reference both password_file and password
        self.assertIn("password_file", src)
        # Must have inline password support — entry.get("password"
        self.assertIn('entry.get("password"', src)


class TestLoadDeviceCredsInlineContract(unittest.TestCase):
    """_load_device_credentials must honor inline password values."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-devcreds-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def _load(self, cred_file):
        from freq.modules.init_cmd import _load_device_credentials
        return _load_device_credentials(cred_file)

    def test_inline_password_loads_for_all_device_types(self):
        """All device types (pfsense, switch, idrac) honor inline password."""
        cred_file = self._write("creds.toml", """
[pfsense]
user = "root"
password = "pf_secret"

[switch]
user = "gigecolo"
password = "sw_secret"

[idrac]
user = "root"
password = "id_secret"
""")
        result = self._load(cred_file)
        for htype in ("pfsense", "switch", "idrac"):
            self.assertIn(htype, result, f"{htype} must be in result with inline password")
            self.assertIn("password", result[htype])
            self.assertTrue(len(result[htype]["password"]) > 0)

    def test_password_file_beats_inline(self):
        """password_file takes priority when both are present."""
        pw_file = self._write("sw-pass", "from_file")
        cred_file = self._write("creds.toml", f"""
[switch]
user = "admin"
password_file = "{pw_file}"
password = "from_inline"
""")
        result = self._load(cred_file)
        self.assertEqual(result["switch"]["password"], "from_file")

    def test_unreadable_password_file_with_inline_fallback(self):
        """Unreadable password_file falls back to inline password."""
        cred_file = self._write("creds.toml", """
[idrac]
user = "root"
password_file = "/nonexistent/idrac-pass"
password = "fallback_pw"
""")
        result = self._load(cred_file)
        self.assertIn("idrac", result)
        self.assertEqual(result["idrac"]["password"], "fallback_pw")

    def test_unreadable_password_file_no_inline_skips(self):
        """Unreadable password_file with no inline password → device skipped."""
        cred_file = self._write("creds.toml", """
[switch]
user = "admin"
password_file = "/nonexistent/switch-pass"
""")
        result = self._load(cred_file)
        self.assertNotIn("switch", result)

    def test_no_password_no_password_file_skips(self):
        """No password and no password_file → device skipped."""
        cred_file = self._write("creds.toml", """
[idrac]
user = "root"
""")
        result = self._load(cred_file)
        self.assertNotIn("idrac", result)

    def test_category_vendor_format_with_inline(self):
        """category:vendor section names work with inline password."""
        cred_file = self._write("creds.toml", """
[bmc:idrac]
user = "root"
password = "bmc_secret"

[switch:cisco]
user = "gigecolo"
password = "cisco_secret"
""")
        result = self._load(cred_file)
        self.assertIn("idrac", result)
        self.assertEqual(result["idrac"]["password"], "bmc_secret")
        self.assertIn("switch", result)
        self.assertEqual(result["switch"]["password"], "cisco_secret")


class TestHeadlessFleetDeployUsesDeviceCreds(unittest.TestCase):
    """_headless_fleet_deploy must pass device_creds to host dispatch."""

    def test_headless_passes_device_creds_to_deploy(self):
        """Phase 8 headless fleet deploy must use loaded device_creds dict."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Headless must call _load_device_credentials and pass result to _headless_fleet_deploy
        self.assertIn("_load_device_credentials(device_credentials_file)", src)
        self.assertIn("device_creds=device_creds", src)

    def test_headless_fleet_deploy_checks_device_creds_dict(self):
        """_headless_fleet_deploy must check htype in device_creds for dispatch."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("htype in device_creds", src)


if __name__ == "__main__":
    unittest.main()
