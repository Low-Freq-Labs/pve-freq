"""FREQ init_cmd tests — _run_with_input, _ssh_with_pass, _load_device_credentials.

Tests the stdin-piping helpers for IOS switch config and the per-device
credential loading from TOML files.
"""
import os
import sys
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.modules.init_cmd import _run_with_input, _ssh_with_pass


# ═══════════════════════════════════════════════════════════════════
# _run_with_input() tests
# ═══════════════════════════════════════════════════════════════════

class TestRunWithInput(unittest.TestCase):
    """Test the stdin-piping subprocess helper."""

    def test_pipes_stdin_to_command(self):
        """Input text is piped via stdin and echoed back."""
        rc, out, err = _run_with_input(["cat"], "hello from stdin")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "hello from stdin")

    def test_multiline_input(self):
        """Multi-line input (IOS config style) is piped correctly."""
        config = "conf t\ninterface vlan 10\nip address 10.0.0.1 255.255.255.0\nend\n"
        rc, out, err = _run_with_input(["cat"], config)
        self.assertEqual(rc, 0)
        self.assertIn("conf t", out)
        self.assertIn("interface vlan 10", out)
        self.assertIn("end", out)

    def test_returns_nonzero_on_failure(self):
        """Non-zero return code propagated from subprocess."""
        rc, out, err = _run_with_input(["false"], "ignored")
        self.assertNotEqual(rc, 0)

    def test_returns_tuple_of_three(self):
        """Always returns (rc, stdout, stderr) tuple."""
        result = _run_with_input(["echo", "test"], "input")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def test_timeout_returns_error(self):
        """Timeout produces rc=1 and error in stderr."""
        rc, out, err = _run_with_input(["sleep", "10"], "x", timeout=1)
        self.assertEqual(rc, 1)
        self.assertTrue(len(err) > 0)

    def test_invalid_command_returns_error(self):
        """Non-existent command returns rc=1 with error message."""
        rc, out, err = _run_with_input(["__nonexistent_binary_xyz__"], "x")
        self.assertEqual(rc, 1)
        self.assertTrue(len(err) > 0)

    def test_empty_input(self):
        """Empty string input doesn't crash."""
        rc, out, err = _run_with_input(["cat"], "")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "")


# ═══════════════════════════════════════════════════════════════════
# _ssh_with_pass() tests
# ═══════════════════════════════════════════════════════════════════

class TestSSHWithPass(unittest.TestCase):
    """Test the sshpass-based SSH runner with tempfile password handling."""

    @patch("freq.modules.init_cmd._run")
    def test_calls_run_without_input_text(self, mock_run):
        """Without input_text, delegates to _run (no stdin)."""
        mock_run.return_value = (0, "ok", "")
        rc, out, err = _ssh_with_pass("secret", ["ssh", "user@host", "uptime"])
        self.assertEqual(rc, 0)
        mock_run.assert_called_once()
        # Verify sshpass -f is prepended
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "sshpass")
        self.assertEqual(cmd[1], "-f")
        # Tempfile path is cmd[2], then original SSH args follow
        self.assertEqual(cmd[3:], ["ssh", "user@host", "uptime"])

    @patch("freq.modules.init_cmd._run_with_input")
    def test_calls_run_with_input_when_input_text_provided(self, mock_run_input):
        """With input_text, delegates to _run_with_input (stdin piped)."""
        mock_run_input.return_value = (0, "configured", "")
        rc, out, err = _ssh_with_pass(
            "secret", ["ssh", "user@switch", ""], input_text="conf t\nend\n"
        )
        self.assertEqual(rc, 0)
        mock_run_input.assert_called_once()
        # Verify input_text passed through
        call_args = mock_run_input.call_args
        self.assertEqual(call_args[0][1], "conf t\nend\n")

    @patch("freq.modules.init_cmd._run")
    def test_password_file_created_with_correct_permissions(self, mock_run):
        """Tempfile is created with 0o600 permissions."""
        created_files = []

        def capture_run(cmd, **kwargs):
            # cmd[2] is the tempfile path
            if len(cmd) > 2 and os.path.isfile(cmd[2]):
                mode = os.stat(cmd[2]).st_mode
                created_files.append((cmd[2], mode))
            return (0, "", "")

        mock_run.side_effect = capture_run
        _ssh_with_pass("mypassword", ["ssh", "user@host", "test"])
        self.assertEqual(len(created_files), 1)
        path, mode = created_files[0]
        self.assertEqual(stat.S_IMODE(mode), 0o600)

    @patch("freq.modules.init_cmd._run")
    def test_password_file_contains_password(self, mock_run):
        """Tempfile contains the exact password string."""
        contents = []

        def capture_run(cmd, **kwargs):
            if len(cmd) > 2 and os.path.isfile(cmd[2]):
                with open(cmd[2]) as f:
                    contents.append(f.read())
            return (0, "", "")

        mock_run.side_effect = capture_run
        _ssh_with_pass("hunter2", ["ssh", "user@host", "test"])
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0], "hunter2")

    @patch("freq.modules.init_cmd._run")
    def test_password_file_cleaned_up_after_success(self, mock_run):
        """Tempfile is deleted after successful execution."""
        tempfile_paths = []

        def capture_run(cmd, **kwargs):
            if len(cmd) > 2:
                tempfile_paths.append(cmd[2])
            return (0, "", "")

        mock_run.side_effect = capture_run
        _ssh_with_pass("secret", ["ssh", "user@host", "test"])
        self.assertEqual(len(tempfile_paths), 1)
        self.assertFalse(os.path.exists(tempfile_paths[0]))

    @patch("freq.modules.init_cmd._run")
    def test_password_file_cleaned_up_on_exception(self, mock_run):
        """Tempfile is deleted even when _run raises."""
        tempfile_paths = []

        def capture_run(cmd, **kwargs):
            if len(cmd) > 2:
                tempfile_paths.append(cmd[2])
            raise RuntimeError("simulated failure")

        mock_run.side_effect = capture_run
        with self.assertRaises(RuntimeError):
            _ssh_with_pass("secret", ["ssh", "user@host", "test"])
        self.assertEqual(len(tempfile_paths), 1)
        self.assertFalse(os.path.exists(tempfile_paths[0]))

    @patch("freq.modules.init_cmd._run")
    def test_timeout_passed_through(self, mock_run):
        """Custom timeout is forwarded to _run."""
        mock_run.return_value = (0, "", "")
        _ssh_with_pass("secret", ["ssh", "host", "cmd"], timeout=60)
        call_kwargs = mock_run.call_args[1]
        self.assertEqual(call_kwargs.get("timeout"), 60)


# ═══════════════════════════════════════════════════════════════════
# _load_device_credentials() tests
# ═══════════════════════════════════════════════════════════════════

class TestLoadDeviceCredentials(unittest.TestCase):
    """Test per-device TOML credential loading.

    Function under test: _load_device_credentials(cred_file) -> dict
    Expected return: {"device_type": {"user": "...", "password": "actual_pass"}, ...}
    """

    def setUp(self):
        """Create temp directory for test TOML + password files."""
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-creds-")

    def tearDown(self):
        """Clean up temp files."""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def _load(self, cred_file):
        """Import and call _load_device_credentials."""
        from freq.modules.init_cmd import _load_device_credentials
        return _load_device_credentials(cred_file)

    def test_valid_full_config(self):
        """All three device types with valid password files."""
        pf_pass = self._write_file("pf-pass", "pfsense_secret")
        sw_pass = self._write_file("sw-pass", "switch_secret")
        id_pass = self._write_file("id-pass", "idrac_secret")

        toml_content = f"""
[pfsense]
user = "root"
password_file = "{pf_pass}"

[switch]
user = "gigecolo"
password_file = "{sw_pass}"

[idrac]
user = "root"
password_file = "{id_pass}"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        result = self._load(cred_file)

        self.assertIn("pfsense", result)
        self.assertEqual(result["pfsense"]["user"], "root")
        self.assertEqual(result["pfsense"]["password"], "pfsense_secret")

        self.assertIn("switch", result)
        self.assertEqual(result["switch"]["user"], "gigecolo")
        self.assertEqual(result["switch"]["password"], "switch_secret")

        self.assertIn("idrac", result)
        self.assertEqual(result["idrac"]["user"], "root")
        self.assertEqual(result["idrac"]["password"], "idrac_secret")

    def test_partial_config_only_pfsense(self):
        """Only one device type defined — others absent from result."""
        pf_pass = self._write_file("pf-pass", "mypass")
        toml_content = f"""
[pfsense]
user = "admin"
password_file = "{pf_pass}"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        result = self._load(cred_file)

        self.assertIn("pfsense", result)
        self.assertEqual(result["pfsense"]["user"], "admin")
        self.assertNotIn("switch", result)
        self.assertNotIn("idrac", result)

    def test_missing_cred_file_returns_empty(self):
        """Non-existent TOML file returns empty dict (graceful fallback)."""
        result = self._load("/nonexistent/path/creds.toml")
        self.assertEqual(result, {})

    def test_missing_password_file_inside_toml(self):
        """Password file path in TOML doesn't exist on disk — should error or skip."""
        toml_content = """
[switch]
user = "gigecolo"
password_file = "/nonexistent/switch-pass"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        # Should either raise or return empty/skip the device
        try:
            result = self._load(cred_file)
            # If it doesn't raise, the device should be absent or have no password
            if "switch" in result:
                self.fail("Expected switch to be skipped or raise when password_file missing")
        except (FileNotFoundError, OSError, ValueError):
            pass  # Acceptable — raising is fine for missing password_file

    def test_password_file_trailing_whitespace_stripped(self):
        """Password files often have trailing newlines — should be stripped."""
        pf_pass = self._write_file("pf-pass", "clean_pass\n")
        toml_content = f"""
[pfsense]
user = "root"
password_file = "{pf_pass}"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        result = self._load(cred_file)
        self.assertEqual(result["pfsense"]["password"], "clean_pass")

    def test_empty_toml_returns_empty_dict(self):
        """Empty TOML file returns empty dict (no devices configured)."""
        cred_file = self._write_file("creds.toml", "")
        result = self._load(cred_file)
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), 0)

    def test_device_type_not_in_file_absent_from_result(self):
        """Querying a device type not in the TOML — not present in result."""
        sw_pass = self._write_file("sw-pass", "secret")
        toml_content = f"""
[switch]
user = "admin"
password_file = "{sw_pass}"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        result = self._load(cred_file)
        self.assertNotIn("pfsense", result)
        self.assertNotIn("idrac", result)
        self.assertIn("switch", result)

    def test_missing_user_field(self):
        """Device section without 'user' field — should handle gracefully."""
        sw_pass = self._write_file("sw-pass", "secret")
        toml_content = f"""
[switch]
password_file = "{sw_pass}"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        # Should either use a default user, skip the device, or raise
        try:
            result = self._load(cred_file)
            if "switch" in result:
                # If it's included, user should have some value (default or empty)
                self.assertIn("user", result["switch"])
        except (KeyError, ValueError):
            pass  # Raising is acceptable for missing required field

    def test_missing_password_file_field(self):
        """Device section without 'password_file' field — should handle gracefully."""
        toml_content = """
[switch]
user = "admin"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        try:
            result = self._load(cred_file)
            if "switch" in result:
                self.fail("Expected switch to be skipped when password_file field missing")
        except (KeyError, ValueError):
            pass  # Raising is acceptable

    def test_returns_dict_type(self):
        """Return type is always a dict."""
        cred_file = self._write_file("creds.toml", "")
        result = self._load(cred_file)
        self.assertIsInstance(result, dict)

    def test_unknown_sections_ignored(self):
        """Non-device sections in TOML don't cause errors."""
        sw_pass = self._write_file("sw-pass", "secret")
        toml_content = f"""
[metadata]
version = "1.0"

[switch]
user = "admin"
password_file = "{sw_pass}"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        result = self._load(cred_file)
        self.assertIn("switch", result)
        # metadata section should not appear as a device credential
        if "metadata" in result:
            # If it appears, it shouldn't have user/password fields that would cause issues
            pass  # Not a hard requirement — depends on implementation


if __name__ == "__main__":
    unittest.main()
