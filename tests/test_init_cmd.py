"""FREQ init_cmd tests — _run_with_input, _ssh_with_pass, _load_device_credentials.

Tests the stdin-piping helpers for IOS switch config and the per-device
credential loading from TOML files.
"""
import os
import sys
import stat
import tempfile
import types
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
        """Timeout produces rc=124 and error in stderr."""
        rc, out, err = _run_with_input(["sleep", "10"], "x", timeout=1)
        self.assertEqual(rc, 124)
        self.assertTrue(len(err) > 0)

    def test_invalid_command_returns_error(self):
        """Non-existent command returns non-zero rc."""
        rc, out, err = _run_with_input(["__nonexistent_binary_xyz__"], "x")
        # rc=1 (Python OSError) or rc=127 (shell "command not found" when
        # wrapped in GNU timeout by _run_bounded).
        self.assertNotEqual(rc, 0)

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
        # R-PVEFREQ-RUN3-IDRAC-HANG-20260415M: sshpass is now wrapped
        # in GNU timeout for hard process-level kill. Command shape is:
        # timeout -s KILL <N> sshpass -f <tmpfile> <ssh_cmd...>
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "timeout")
        self.assertEqual(cmd[1], "-s")
        self.assertEqual(cmd[2], "KILL")
        # cmd[3] is the timeout value (string)
        self.assertEqual(cmd[4], "sshpass")
        self.assertEqual(cmd[5], "-f")
        # cmd[6] is the tempfile path, then original SSH args follow
        self.assertEqual(cmd[7:], ["ssh", "user@host", "uptime"])

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
            # cmd[6] is the tempfile path (after timeout -s KILL <N> sshpass -f)
            if len(cmd) > 6 and os.path.isfile(cmd[6]):
                mode = os.stat(cmd[6]).st_mode
                created_files.append((cmd[6], mode))
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
            # cmd[6] is the tempfile path (after timeout -s KILL <N> sshpass -f)
            if len(cmd) > 6 and os.path.isfile(cmd[6]):
                with open(cmd[6]) as f:
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
            if len(cmd) > 6:
                tempfile_paths.append(cmd[6])
            raise RuntimeError("simulated failure")

        mock_run.side_effect = capture_run
        with self.assertRaises(RuntimeError):
            _ssh_with_pass("secret", ["ssh", "user@host", "test"])
        self.assertEqual(len(tempfile_paths), 1)
        self.assertFalse(os.path.exists(tempfile_paths[0]))

    @patch("freq.modules.init_cmd._run")
    def test_timeout_passed_through(self, mock_run):
        """Custom timeout is forwarded to _run with +10s buffer for GNU timeout."""
        mock_run.return_value = (0, "", "")
        _ssh_with_pass("secret", ["ssh", "host", "cmd"], timeout=60)
        call_kwargs = mock_run.call_args[1]
        # Python-side timeout is caller_timeout + 10 (GNU timeout fires
        # at caller_timeout; Python fallback fires 10s later as belt-and-suspenders)
        self.assertEqual(call_kwargs.get("timeout"), 70)
        # GNU timeout value in the command is the original caller timeout
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[3], "60")


class TestIdracParsing(unittest.TestCase):
    """Test helpers for live iDRAC RACADM output."""

    def test_parse_idrac_username_output_handles_real_racadm_format(self):
        from freq.modules.init_cmd import _parse_idrac_username_output

        output = "[Key=iDRAC.Embedded.1#Users.8]\nUserName=\n"
        self.assertEqual(_parse_idrac_username_output(output), "")

        output = "[Key=iDRAC.Embedded.1#Users.8]\nUserName=freq-admin\n"
        self.assertEqual(_parse_idrac_username_output(output), "freq-admin")

    def test_parse_idrac_slots_treats_null_as_empty(self):
        from freq.modules.init_cmd import _parse_idrac_slots

        slot_dump = "\n".join([
            "SLOT3=root",
            "SLOT4=(NULL)",
            "SLOT5=",
            "SLOT6=freq-admin",
        ])
        target_slot, existing_slot = _parse_idrac_slots(slot_dump, "freq-admin")
        self.assertEqual(target_slot, 4)
        self.assertEqual(existing_slot, 6)

    def test_query_idrac_slots_prefers_higher_automation_slots_first(self):
        from freq.modules.init_cmd import _query_idrac_slots

        seen = []

        def fake_ssh(cmd, extra_opts=None, timeout=None):
            seen.append(cmd)
            slot = int(cmd.split(".")[2])
            if slot == 8:
                return 0, "[Key=iDRAC.Embedded.1#Users.8]\nUserName=\n", ""
            return 0, f"[Key=iDRAC.Embedded.1#Users.{slot}]\nUserName=occupied\n", ""

        target_slot, existing_slot = _query_idrac_slots(fake_ssh, [], "freq-admin")
        self.assertEqual(target_slot, 8)
        self.assertIsNone(existing_slot)
        self.assertEqual(seen[0], "racadm get iDRAC.Users.8.UserName")


class TestHeadlessFleetDeployTruth(unittest.TestCase):
    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.fmt")
    def test_truenas_probe_uses_resolved_device_credentials(self, mock_fmt, mock_run, mock_dispatch):
        from freq.modules.init_cmd import _headless_fleet_deploy

        cfg = types.SimpleNamespace(
            pve_nodes=[],
            pve_node_names=[],
            hosts=[types.SimpleNamespace(ip="10.0.0.25", label="nexus", htype="truenas")],
            ssh_service_account="freq-admin",
        )
        ctx = {"svc_name": "freq-admin", "svc_pass": "SvcPass2026!"}
        mock_run.return_value = (0, "OK", "")
        mock_dispatch.return_value = True

        _headless_fleet_deploy(
            cfg,
            ctx,
            bootstrap_key="/home/freq-ops/.ssh/fleet_key",
            bootstrap_user="freq-ops",
            bootstrap_pass="",
            device_creds={"truenas": {"user": "root", "password": "changeme1234"}},
            pve_only=False,
        )

        ssh_check = mock_run.call_args_list[0][0][0]
        self.assertIn("root@10.0.0.25", ssh_check)
        self.assertIn("sshpass", ssh_check)

        dispatch_args = mock_dispatch.call_args[0]
        self.assertEqual(dispatch_args[3], "changeme1234")
        self.assertEqual(dispatch_args[4], "")
        self.assertEqual(dispatch_args[5], "root")


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

    def test_missing_password_and_password_file_field(self):
        """Device section with no password or password_file — should skip."""
        toml_content = """
[switch]
user = "admin"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        try:
            result = self._load(cred_file)
            if "switch" in result:
                self.fail("Expected switch to be skipped when both password and password_file missing")
        except (KeyError, ValueError):
            pass  # Raising is acceptable

    def test_inline_password_honored(self):
        """Inline 'password' field should be used when no password_file."""
        toml_content = """
[switch]
user = "gigecolo"
password = "inline_secret"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        result = self._load(cred_file)
        self.assertIn("switch", result)
        self.assertEqual(result["switch"]["user"], "gigecolo")
        self.assertEqual(result["switch"]["password"], "inline_secret")

    def test_inline_password_all_device_types(self):
        """All device types honor inline password."""
        toml_content = """
[pfsense]
user = "root"
password = "pf_inline"

[switch]
user = "gigecolo"
password = "sw_inline"

[idrac]
user = "root"
password = "id_inline"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        result = self._load(cred_file)
        self.assertIn("pfsense", result)
        self.assertEqual(result["pfsense"]["password"], "pf_inline")
        self.assertIn("switch", result)
        self.assertEqual(result["switch"]["password"], "sw_inline")
        self.assertIn("idrac", result)
        self.assertEqual(result["idrac"]["password"], "id_inline")

    def test_password_file_takes_priority_over_inline(self):
        """password_file is preferred over inline password when both exist."""
        sw_pass = self._write_file("sw-pass", "file_secret")
        toml_content = f"""
[switch]
user = "admin"
password_file = "{sw_pass}"
password = "inline_secret"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        result = self._load(cred_file)
        self.assertIn("switch", result)
        self.assertEqual(result["switch"]["password"], "file_secret")

    def test_unreadable_password_file_falls_back_to_inline(self):
        """When password_file exists but is unreadable, fall back to inline password."""
        toml_content = """
[idrac]
user = "root"
password_file = "/nonexistent/idrac-pass"
password = "fallback_inline"
"""
        cred_file = self._write_file("creds.toml", toml_content)
        result = self._load(cred_file)
        self.assertIn("idrac", result)
        self.assertEqual(result["idrac"]["password"], "fallback_inline")

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


class TestPfSenseUninstall(unittest.TestCase):
    """pfSense uninstall must distinguish full removal from key-only fallback."""

    @patch("freq.modules.init_cmd._uninstall_auth_ssh")
    def test_remove_pfsense_uses_admin_auth_for_full_removal(self, mock_auth_ssh):
        from freq.modules.init_cmd import _remove_pfsense

        ssh = MagicMock(side_effect=[
            (0, "OK\n", ""),
            (0, "ACCOUNT_REMOVED\n", ""),
        ])
        mock_auth_ssh.return_value = ssh

        ok, reason = _remove_pfsense(
            "10.0.0.1",
            "svc-test",
            "/tmp/freq_id_ed25519",
            admin_auth={"user": "admin", "password": "secret", "key_path": ""},
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        mock_auth_ssh.assert_called_once_with(
            "10.0.0.1", "admin", auth_key="", auth_pass="secret"
        )

    @patch("freq.modules.init_cmd._uninstall_ssh")
    def test_remove_pfsense_without_admin_auth_is_key_only(self, mock_uninstall_ssh):
        from freq.modules.init_cmd import _remove_pfsense

        ssh = MagicMock(side_effect=[
            (0, "OK\n", ""),
            (0, "KEY_REMOVED\n", ""),
        ])
        mock_uninstall_ssh.return_value = ssh

        ok, reason = _remove_pfsense("10.0.0.1", "svc-test", "/tmp/freq_id_ed25519")

        self.assertTrue(ok)
        self.assertEqual(reason, "key_only")


class TestUninstallSSH(unittest.TestCase):
    """Uninstall SSH helper must honor per-call extra SSH options."""

    @patch("freq.modules.init_cmd._run")
    def test_uninstall_ssh_accepts_call_time_extra_opts(self, mock_run):
        from freq.modules.init_cmd import _uninstall_ssh

        mock_run.return_value = (0, "OK\n", "")
        ssh = _uninstall_ssh("10.0.0.10", "svc-test", "/tmp/freq_id_rsa")
        ssh("echo OK", extra_opts=["-o", "KexAlgorithms=+diffie-hellman-group1-sha1"])

        cmd = mock_run.call_args.args[0]
        self.assertIn("-i", cmd)
        self.assertIn("/tmp/freq_id_rsa", cmd)
        self.assertIn("svc-test@10.0.0.10", cmd)
        self.assertIn("KexAlgorithms=+diffie-hellman-group1-sha1", cmd)


class TestUninstallLocalCleanup(unittest.TestCase):
    """Local uninstall must stop the dashboard service before userdel."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-uninstall-local-")
        self.key_dir = os.path.join(self.tmpdir, "keys")
        self.conf_dir = os.path.join(self.tmpdir, "conf")
        os.makedirs(self.key_dir, exist_ok=True)
        os.makedirs(self.conf_dir, exist_ok=True)
        self.vault_file = os.path.join(self.tmpdir, "vault.enc")
        self.ed_key = os.path.join(self.key_dir, "freq_id_ed25519")
        self.rsa_key = os.path.join(self.key_dir, "freq_id_rsa")
        for path in [
            self.ed_key,
            f"{self.ed_key}.pub",
            self.rsa_key,
            f"{self.rsa_key}.pub",
            self.vault_file,
            os.path.join(self.conf_dir, "roles.conf"),
            os.path.join(self.conf_dir, ".initialized"),
        ]:
            with open(path, "w") as f:
                f.write("x")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("freq.modules.init_cmd.logger")
    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.os.unlink")
    @patch("freq.modules.init_cmd.os.path.isfile")
    def test_uninstall_stops_service_before_userdel(self, mock_isfile, mock_unlink, mock_run, _mock_fmt, _mock_logger):
        from freq.modules.init_cmd import _uninstall_execute

        calls = []

        def fake_isfile(path):
            if path == "/etc/sudoers.d/freq-freq-admin":
                return False
            return os.path.exists(path)

        def fake_run(cmd, *args, **kwargs):
            calls.append(cmd)
            if cmd[:3] == ["systemctl", "is-enabled", "freq-serve"]:
                return (0, "enabled\n", "")
            if cmd[:3] == ["systemctl", "is-active", "freq-serve"]:
                return (0, "active\n", "")
            if cmd[:3] == ["systemctl", "disable", "--now"]:
                return (0, "", "")
            if cmd[:2] == ["id", "freq-admin"]:
                return (0, "uid=123\n", "")
            if cmd[:2] == ["pkill", "-u"] or cmd[:3] == ["pkill", "-9", "-u"]:
                return (0, "", "")
            if cmd[:2] == ["userdel", "-r"]:
                return (0, "", "")
            if cmd[:3] == ["getent", "group", "freq-admin"]:
                return (1, "", "")
            return (1, "", "")

        mock_run.side_effect = fake_run
        mock_isfile.side_effect = fake_isfile

        cfg = MagicMock()
        cfg.key_dir = self.key_dir
        cfg.vault_file = self.vault_file
        cfg.conf_dir = self.conf_dir

        rc = _uninstall_execute(cfg, "freq-admin", self.ed_key, self.rsa_key, [])

        self.assertEqual(rc, 0)
        disable_idx = next(i for i, cmd in enumerate(calls) if cmd[:3] == ["systemctl", "disable", "--now"])
        userdel_idx = next(i for i, cmd in enumerate(calls) if cmd[:2] == ["userdel", "-r"])
        self.assertLess(disable_idx, userdel_idx, "freq-serve must be stopped before userdel")


# ═══════════════════════════════════════════════════════════════════
# _update_toml_value() tests
# ═══════════════════════════════════════════════════════════════════

class TestUpdateTomlValue(unittest.TestCase):
    """Test the TOML content updater used by _phase_configure."""

    def _update(self, content, key, value):
        from freq.modules.init_cmd import _update_toml_value
        return _update_toml_value(content, key, value)

    def test_updates_string_value(self):
        """Simple string key gets updated."""
        content = 'gateway = "10.0.0.1"\n'
        result = self._update(content, "gateway", "192.168.1.1")
        self.assertIn('gateway = "192.168.1.1"', result)
        self.assertNotIn("10.0.0.1", result)

    def test_updates_list_value(self):
        """List value is formatted as TOML array."""
        content = 'nodes = ["old1"]\n'
        result = self._update(content, "nodes", ["10.0.0.1", "10.0.0.2"])
        self.assertIn('nodes = ["10.0.0.1", "10.0.0.2"]', result)

    def test_updates_bool_value(self):
        """Boolean value is formatted as TOML true/false."""
        content = 'debug = false\n'
        result = self._update(content, "debug", True)
        self.assertIn("debug = true", result)

    def test_uncomments_commented_key(self):
        """Commented-out key is uncommented and set."""
        content = '# nodes = []\n'
        result = self._update(content, "nodes", ["1.2.3.4"])
        self.assertIn('nodes = ["1.2.3.4"]', result)
        self.assertNotIn("#", result.split("\n")[0])

    def test_preserves_inline_comment(self):
        """Inline comment after value is preserved."""
        content = 'mode = "root"  # SSH as root directly\n'
        result = self._update(content, "mode", "sudo")
        self.assertIn('mode = "sudo"', result)
        self.assertIn("# SSH as root directly", result)

    def test_no_match_inserts_key(self):
        """Missing keys are inserted so init can populate minimal configs."""
        content = 'something_else = "value"\n'
        result = self._update(content, "nonexistent", "test")
        self.assertIn(content, result)
        self.assertIn('nonexistent = "test"', result)


# ═══════════════════════════════════════════════════════════════════
# _phase_configure() tests
# ═══════════════════════════════════════════════════════════════════

class TestPhaseConfigure(unittest.TestCase):
    """Test Phase 2: interactive cluster configuration."""

    def setUp(self):
        """Create temp directory with a minimal freq.toml."""
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-configure-")
        self.toml_path = os.path.join(self.tmpdir, "freq.toml")
        self.base_toml = (
            "[freq]\n"
            'version = "2.0.0"\n'
            "\n"
            "[ssh]\n"
            'mode = "sudo"\n'
            "\n"
            "[pve]\n"
            "# nodes = []\n"
            "# node_names = []\n"
            "\n"
            "[vm.defaults]\n"
            '# gateway = ""\n'
            '# nameserver = "1.1.1.1"\n'
            "\n"
            "[infrastructure]\n"
            '# cluster_name = ""\n'
        )
        with open(self.toml_path, "w") as f:
            f.write(self.base_toml)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cfg(self, **overrides):
        """Build a mock cfg object with defaults for _phase_configure."""
        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.pve_nodes = overrides.get("pve_nodes", [])
        cfg.pve_node_names = overrides.get("pve_node_names", [])
        cfg.vm_gateway = overrides.get("vm_gateway", "")
        cfg.vm_nameserver = overrides.get("vm_nameserver", "")
        cfg.cluster_name = overrides.get("cluster_name", "")
        cfg.ssh_mode = overrides.get("ssh_mode", "sudo")
        cfg.pve_storage = overrides.get("pve_storage", {})
        return cfg

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_phase_configure_writes_pve_nodes(self, mock_fmt, mock_input, mock_lc):
        """PVE node IPs and names are written to freq.toml via interactive prompt."""
        cfg = self._make_cfg()
        # _input calls in order: node IPs, node names, storage×3, gateway, nameserver, cluster, ssh mode
        mock_input.side_effect = [
            "10.0.0.1 10.0.0.2 10.0.0.3",  # PVE node IPs
            "pve01 pve02 pve03",             # Node names
            "local-lvm",                      # Storage pve01
            "local-lvm",                      # Storage pve02
            "local-lvm",                      # Storage pve03
            "10.0.0.1",                       # Gateway
            "1.1.1.1",                        # Nameserver
            "testlab",                        # Cluster name
            "sudo",                           # SSH mode
        ]
        mock_lc.return_value = cfg  # Reload returns same cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertIn("10.0.0.1", content)
        self.assertIn("10.0.0.2", content)
        self.assertIn("10.0.0.3", content)
        self.assertIn("pve01", content)
        self.assertIn("pve02", content)
        self.assertIn("pve03", content)

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_phase_configure_writes_gateway(self, mock_fmt, mock_input, mock_lc):
        """Gateway and nameserver are written to freq.toml via interactive prompt."""
        cfg = self._make_cfg()
        mock_input.side_effect = [
            "10.0.0.1",       # PVE node IPs (single node)
            "pve01",           # Node name
            "local-lvm",       # Storage
            "192.168.1.1",     # Gateway
            "8.8.8.8",         # Nameserver
            "homelab",         # Cluster name
            "sudo",            # SSH mode
        ]
        mock_lc.return_value = cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertIn('gateway = "192.168.1.1"', content)

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_phase_configure_cli_pve_nodes(self, mock_fmt, mock_input, mock_lc):
        """--pve-nodes CLI arg writes nodes to freq.toml without interactive prompt."""
        cfg = self._make_cfg()
        args = MagicMock()
        args.pve_nodes = "10.0.0.1 10.0.0.2"
        args.pve_node_names = "pve01 pve02"
        args.gateway = None
        args.nameserver = None
        args.hosts_file = None
        args.yes = False

        # Only interactive prompts that remain: gateway, nameserver, cluster, ssh mode
        mock_input.side_effect = [
            "10.0.0.1",   # Gateway
            "1.1.1.1",    # Nameserver (default)
            "",            # Cluster name (skip)
            "sudo",        # SSH mode
        ]
        mock_lc.return_value = cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg, args)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertIn("10.0.0.1", content)
        self.assertIn("10.0.0.2", content)
        self.assertIn("pve01", content)
        self.assertIn("pve02", content)
        # Verify cfg was updated
        self.assertEqual(cfg.pve_nodes, ["10.0.0.1", "10.0.0.2"])

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_phase_configure_cli_gateway(self, mock_fmt, mock_input, mock_lc):
        """--gateway CLI arg writes gateway without interactive prompt."""
        cfg = self._make_cfg()
        args = MagicMock()
        args.pve_nodes = "10.0.0.1"
        args.pve_node_names = "pve01"
        args.gateway = "192.168.1.1"
        args.nameserver = "8.8.4.4"
        args.hosts_file = None
        args.yes = False

        # Only cluster name and SSH mode remain interactive
        mock_input.side_effect = [
            "mylab",   # Cluster name
            "sudo",    # SSH mode
        ]
        mock_lc.return_value = cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg, args)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertIn('gateway = "192.168.1.1"', content)
        self.assertIn('nameserver = "8.8.4.4"', content)
        self.assertEqual(cfg.vm_gateway, "192.168.1.1")
        self.assertEqual(cfg.vm_nameserver, "8.8.4.4")

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_phase_configure_rejects_invalid_cli_pve_nodes(self, mock_fmt, mock_input, mock_lc):
        cfg = self._make_cfg()
        args = MagicMock()
        args.pve_nodes = "10.0.0.1 bad-ip"
        args.pve_node_names = "pve01 pve02"
        args.gateway = None
        args.nameserver = None
        args.hosts_file = None
        args.yes = False

        mock_input.side_effect = [
            "10.0.0.1",
            "1.1.1.1",
            "",
            "sudo",
        ]
        mock_lc.return_value = cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg, args)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertNotIn("bad-ip", content)
        self.assertEqual(cfg.pve_nodes, [])
        mock_fmt.step_fail.assert_any_call("Invalid PVE node IP(s) from CLI: bad-ip")

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_phase_configure_rejects_invalid_cli_gateway(self, mock_fmt, mock_input, mock_lc):
        cfg = self._make_cfg()
        args = MagicMock()
        args.pve_nodes = "10.0.0.1"
        args.pve_node_names = "pve01"
        args.gateway = "not-an-ip"
        args.nameserver = "8.8.4.4"
        args.hosts_file = None
        args.yes = False

        mock_input.side_effect = [
            "mylab",
            "sudo",
        ]
        mock_lc.return_value = cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg, args)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertNotIn('gateway = "not-an-ip"', content)
        self.assertEqual(cfg.vm_gateway, "")
        mock_fmt.step_fail.assert_any_call("Invalid gateway IP from CLI: not-an-ip")

    @patch("freq.modules.init_cmd._confirm")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_phase_configure_skips_if_populated(self, mock_fmt, mock_input, mock_confirm):
        """Already-configured values are shown but not re-prompted (unless user opts in)."""
        cfg = self._make_cfg(
            pve_nodes=["10.0.0.1"],
            pve_node_names=["pve01"],
            vm_gateway="10.0.0.1",
            vm_nameserver="8.8.8.8",
            cluster_name="homelab",
            ssh_mode="sudo",
        )
        # User declines to reconfigure nodes
        mock_confirm.return_value = False
        # Only nameserver and SSH mode prompts will fire (they always prompt)
        # Nameserver: already set and != 1.1.1.1, so skipped
        # SSH mode: prompted but same as current
        mock_input.side_effect = [
            "sudo",  # SSH mode — same as current
        ]

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg)

        # freq.toml should be unchanged (no write happened)
        with open(self.toml_path) as f:
            content = f.read()

        self.assertEqual(content, self.base_toml)


# ═══════════════════════════════════════════════════════════════════
# Bootstrap key tests — _phase_pve_deploy + _phase_fleet_deploy
# ═══════════════════════════════════════════════════════════════════

class TestBootstrapKey(unittest.TestCase):
    """Test that --bootstrap-key skips interactive prompts in deploy phases."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-bootstrap-")
        # Create a fake SSH key file
        self.key_path = os.path.join(self.tmpdir, "id_ed25519")
        with open(self.key_path, "w") as f:
            f.write("fake-ssh-key-for-testing")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_args(self, bootstrap_key=None, bootstrap_user=None):
        args = MagicMock()
        args.bootstrap_key = bootstrap_key
        args.bootstrap_user = bootstrap_user
        return args

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_pve_deploy_uses_bootstrap_key(self, mock_fmt, mock_input, mock_dispatch):
        """When bootstrap_key is set, PVE deploy skips interactive auth prompts."""
        cfg = MagicMock()
        cfg.pve_nodes = ["10.0.0.1"]
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}
        args = self._make_args(bootstrap_key=self.key_path, bootstrap_user="root")

        mock_dispatch.return_value = True

        from freq.modules.init_cmd import _phase_pve_deploy
        _phase_pve_deploy(cfg, ctx, args)

        # _input should NOT have been called for auth method selection
        # (bootstrap mode skips the A/B choice prompt)
        for call in mock_input.call_args_list:
            prompt = call[0][0] if call[0] else ""
            self.assertNotIn("Deploy as user", prompt,
                             "Bootstrap mode should skip interactive user prompt")
            self.assertNotIn("Choice", prompt,
                             "Bootstrap mode should skip A/B auth choice")

        # Verify dispatch was called with the bootstrap key
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0]
        # call_args: (ip, htype, ctx, auth_pass, auth_key, pve_user)
        self.assertEqual(call_args[4], self.key_path)  # auth_key = bootstrap key path
        self.assertEqual(call_args[5], "root")          # pve_user = bootstrap_user

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_fleet_deploy_uses_bootstrap_key(self, mock_fmt, mock_input, mock_dispatch):
        """When bootstrap_key is set, fleet deploy skips interactive auth prompts for linux hosts."""
        from freq.core.config import Host
        cfg = MagicMock()
        host = MagicMock(ip="10.0.0.10", label="testhost", htype="linux")
        host.category = "server"
        cfg.hosts = [host]
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}
        args = self._make_args(bootstrap_key=self.key_path, bootstrap_user="root")

        mock_dispatch.return_value = True

        from freq.modules.init_cmd import _phase_fleet_deploy
        _phase_fleet_deploy(cfg, ctx, args)

        # _input should NOT have been called for auth method selection
        for call in mock_input.call_args_list:
            prompt = call[0][0] if call[0] else ""
            self.assertNotIn("Password", prompt,
                             "Bootstrap mode should skip password prompt")

        # Verify dispatch was called with the bootstrap key
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0]
        self.assertEqual(call_args[4], self.key_path)  # auth_key = bootstrap key path
        self.assertEqual(call_args[5], "root")          # auth_user = bootstrap_user


# ═══════════════════════════════════════════════════════════════════
# Device credentials in interactive fleet deploy
# ═══════════════════════════════════════════════════════════════════

class TestDeviceCredsInteractive(unittest.TestCase):
    """Test --device-credentials in interactive _phase_fleet_deploy."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-devcreds-")
        self.key_path = os.path.join(self.tmpdir, "id_ed25519")
        with open(self.key_path, "w") as f:
            f.write("fake-key")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_args(self, device_credentials=None, bootstrap_key=None, bootstrap_user=None, hosts_file=None):
        args = MagicMock()
        args.device_credentials = device_credentials
        args.bootstrap_key = bootstrap_key
        args.bootstrap_user = bootstrap_user
        args.hosts_file = hosts_file
        return args

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._load_device_credentials")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_fleet_deploy_uses_device_creds_for_pfsense(self, mock_fmt, mock_input, mock_load_dc, mock_dispatch):
        """pfSense host uses credentials from --device-credentials, skipping interactive prompt."""
        cfg = MagicMock()
        host = MagicMock(ip="10.0.0.1", label="fw01", htype="pfsense")
        host.category = "firewall"
        cfg.hosts = [host]

        mock_load_dc.return_value = {
            "pfsense": {"user": "admin", "password": "fw-secret"},
        }
        mock_dispatch.return_value = True

        args = self._make_args(device_credentials="/fake/creds.toml")
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        from freq.modules.init_cmd import _phase_fleet_deploy
        _phase_fleet_deploy(cfg, ctx, args)

        # Dispatch called with password from device creds, not interactive
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0]
        self.assertEqual(call_args[0], "10.0.0.1")       # ip
        self.assertEqual(call_args[1], "pfsense")         # htype
        self.assertEqual(call_args[3], "fw-secret")       # auth_pass from device creds
        self.assertEqual(call_args[4], "")                 # auth_key empty (password mode)
        self.assertEqual(call_args[5], "admin")            # auth_user from device creds

        # No interactive auth prompts for pfSense
        for call in mock_input.call_args_list:
            prompt = call[0][0] if call[0] else ""
            self.assertNotIn("pfSense", prompt)
            self.assertNotIn("Choice", prompt)

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._load_device_credentials")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_fleet_deploy_uses_device_creds_per_htype(self, mock_fmt, mock_input, mock_load_dc, mock_dispatch):
        """iDRAC and switch get different credentials from device_creds dict."""
        cfg = MagicMock()
        idrac_host = MagicMock(ip="10.0.0.2", label="idrac01", htype="idrac")
        idrac_host.category = "bmc"
        switch_host = MagicMock(ip="10.0.0.3", label="sw01", htype="switch")
        switch_host.category = "switch"
        cfg.hosts = [idrac_host, switch_host]

        mock_load_dc.return_value = {
            "idrac": {"user": "root", "password": "idrac-pass"},
            "switch": {"user": "gigecolo", "password": "switch-pass"},
        }
        mock_dispatch.return_value = True

        args = self._make_args(device_credentials="/fake/creds.toml")
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        from freq.modules.init_cmd import _phase_fleet_deploy
        _phase_fleet_deploy(cfg, ctx, args)

        # Both dispatched with their own creds
        self.assertEqual(mock_dispatch.call_count, 2)
        calls = mock_dispatch.call_args_list

        # iDRAC call
        idrac_call = [c for c in calls if c[0][1] == "idrac"][0]
        self.assertEqual(idrac_call[0][3], "idrac-pass")   # password
        self.assertEqual(idrac_call[0][5], "root")          # user

        # Switch call
        switch_call = [c for c in calls if c[0][1] == "switch"][0]
        self.assertEqual(switch_call[0][3], "switch-pass")  # password
        self.assertEqual(switch_call[0][5], "gigecolo")      # user

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._load_device_credentials")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_fleet_deploy_device_creds_over_bootstrap(self, mock_fmt, mock_input, mock_load_dc, mock_dispatch):
        """--device-credentials takes priority over --bootstrap-key for devices."""
        cfg = MagicMock()
        host = MagicMock(ip="10.0.0.1", label="fw01", htype="pfsense")
        host.category = "firewall"
        cfg.hosts = [host]

        mock_load_dc.return_value = {
            "pfsense": {"user": "admin", "password": "creds-password"},
        }
        mock_dispatch.return_value = True

        # Both device creds AND bootstrap key provided
        args = self._make_args(
            device_credentials="/fake/creds.toml",
            bootstrap_key=self.key_path,
            bootstrap_user="root",
        )
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        from freq.modules.init_cmd import _phase_fleet_deploy
        _phase_fleet_deploy(cfg, ctx, args)

        # Device creds win — password auth used, not bootstrap key
        call_args = mock_dispatch.call_args[0]
        self.assertEqual(call_args[3], "creds-password")  # password from device creds
        self.assertEqual(call_args[4], "")                 # NOT the bootstrap key
        self.assertEqual(call_args[5], "admin")            # user from device creds

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._load_device_credentials")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_fleet_deploy_mixed_creds(self, mock_fmt, mock_input, mock_load_dc, mock_dispatch):
        """Devices with creds use them; devices without fall back to bootstrap key."""
        cfg = MagicMock()
        idrac_host = MagicMock(ip="10.0.0.2", label="idrac01", htype="idrac")
        idrac_host.category = "bmc"
        switch_host = MagicMock(ip="10.0.0.3", label="sw01", htype="switch")
        switch_host.category = "switch"
        cfg.hosts = [idrac_host, switch_host]

        # Only iDRAC has device creds — switch does not
        mock_load_dc.return_value = {
            "idrac": {"user": "root", "password": "idrac-pass"},
        }
        mock_dispatch.return_value = True

        args = self._make_args(
            device_credentials="/fake/creds.toml",
            bootstrap_key=self.key_path,
            bootstrap_user="root",
        )
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        from freq.modules.init_cmd import _phase_fleet_deploy
        _phase_fleet_deploy(cfg, ctx, args)

        self.assertEqual(mock_dispatch.call_count, 2)
        calls = mock_dispatch.call_args_list

        # iDRAC: uses device creds (password)
        idrac_call = [c for c in calls if c[0][1] == "idrac"][0]
        self.assertEqual(idrac_call[0][3], "idrac-pass")  # password from creds
        self.assertEqual(idrac_call[0][4], "")              # no key

        # Switch: falls back to bootstrap key
        switch_call = [c for c in calls if c[0][1] == "switch"][0]
        self.assertEqual(switch_call[0][3], "")              # no password
        self.assertEqual(switch_call[0][4], self.key_path)   # bootstrap key
        self.assertEqual(switch_call[0][5], "root")          # bootstrap user


# ═══════════════════════════════════════════════════════════════════
# --hosts-file import tests
# ═══════════════════════════════════════════════════════════════════

class TestHostsFileImport(unittest.TestCase):
    """Test that --hosts-file imports fleet hosts into cfg before deployment."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-hostsfile-")
        # Create a hosts.conf with test entries
        self.hosts_file = os.path.join(self.tmpdir, "hosts.conf")
        with open(self.hosts_file, "w") as f:
            f.write("10.0.0.10  testhost  linux\n")
            f.write("10.0.0.11  docker01  docker\n")
        # Create the target hosts_file location cfg will point to
        self.cfg_hosts_file = os.path.join(self.tmpdir, "hosts-target.conf")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("freq.modules.init_cmd.getpass")
    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_hosts_file_imports_hosts(self, mock_fmt, mock_input, mock_dispatch, mock_getpass):
        """--hosts-file copies hosts.conf and loads hosts into cfg."""
        cfg = MagicMock()
        cfg.hosts = []  # Empty — no hosts registered yet
        cfg.hosts_file = self.cfg_hosts_file

        args = MagicMock()
        args.hosts_file = self.hosts_file
        args.bootstrap_key = None
        args.bootstrap_user = None

        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        # Mock load_hosts to return parsed host objects
        host1 = MagicMock(ip="10.0.0.10", label="testhost", htype="linux")
        host1.category = "server"
        host2 = MagicMock(ip="10.0.0.11", label="docker01", htype="docker")
        host2.category = "server"

        mock_getpass.getpass.return_value = "testpass"
        mock_dispatch.return_value = True

        with patch("freq.core.config.load_hosts", return_value=[host1, host2]):
            # Auth prompts: deploy user, auth choice, then getpass handles password
            mock_input.side_effect = [
                "root",    # Deploy as user
                "A",       # Auth choice (password)
            ]

            from freq.modules.init_cmd import _phase_fleet_deploy
            try:
                _phase_fleet_deploy(cfg, ctx, args)
            except StopIteration:
                pass  # Input exhaustion is fine — we're testing the import

        # Verify hosts.conf was copied to cfg's hosts_file location
        self.assertTrue(os.path.isfile(self.cfg_hosts_file))
        with open(self.cfg_hosts_file) as f:
            content = f.read()
        self.assertIn("testhost", content)
        self.assertIn("docker01", content)

    @patch("freq.modules.init_cmd.getpass")
    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_hosts_file_skips_if_hosts_already_registered(self, mock_fmt, mock_input, mock_dispatch, mock_getpass):
        """--hosts-file does NOT overwrite if cfg.hosts is already populated."""
        cfg = MagicMock()
        cfg.hosts = [MagicMock(ip="10.0.0.99", label="existing", htype="linux")]
        cfg.hosts_file = self.cfg_hosts_file

        args = MagicMock()
        args.hosts_file = self.hosts_file
        args.bootstrap_key = None
        args.bootstrap_user = None

        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        mock_getpass.getpass.return_value = "testpass"
        mock_dispatch.return_value = True
        mock_input.side_effect = [
            "root",  # Deploy as user
            "A",     # Auth choice
        ]

        from freq.modules.init_cmd import _phase_fleet_deploy
        try:
            _phase_fleet_deploy(cfg, ctx, args)
        except StopIteration:
            pass

        # hosts-target.conf should NOT have been created (import skipped)
        self.assertFalse(os.path.isfile(self.cfg_hosts_file))


class TestPhaseDiscoverScopedHosts(unittest.TestCase):
    """Discovery must not pollute a curated --hosts-file run."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-discover-scope-")
        self.hosts_file = os.path.join(self.tmpdir, "hosts.toml")
        with open(self.hosts_file, "w") as f:
            f.write('[[host]]\n')
            f.write('ip = "10.25.255.25"\n')
            f.write('label = "truenas"\n')
            f.write('type = "truenas"\n')
            f.write('groups = "infrastructure"\n')
        self.cfg_hosts_file = os.path.join(self.tmpdir, "hosts-target.toml")
        self.freq_toml = os.path.join(self.tmpdir, "freq.toml")
        self.boundaries = os.path.join(self.tmpdir, "fleet-boundaries.toml")
        with open(self.freq_toml, "w") as f:
            f.write("[freq]\nversion = \"test\"\n\n[ssh]\nlegacy_password_file = \"\"\n\n[infrastructure]\n")
        with open(self.boundaries, "w") as f:
            f.write("")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.core.config.append_host_toml")
    def test_hosts_file_prevents_headless_auto_registration(self, mock_append, mock_run, mock_fmt):
        from freq.modules.init_cmd import _phase_fleet_discover

        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.hosts_file = self.cfg_hosts_file
        cfg.hosts = []
        cfg.pve_nodes = ["10.25.255.26"]
        cfg.pve_node_names = ["pve01"]
        cfg.vlans = []
        cfg.vm_gateway = ""
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})

        ctx = {"key_path": "/tmp/fake", "svc_name": "freq-admin"}
        args = MagicMock(headless=True, hosts_file=self.hosts_file)

        vm_list = '[{"vmid":5001,"name":"truenas-lab","status":"running","type":"qemu","node":"pve01"}]'
        agent_ips = '{"result":[{"name":"eth0","ip-addresses":[{"ip-address-type":"ipv4","ip-address":"192.168.255.25"}]}]}'

        def run_side_effect(cmd, timeout=30):
            cmd_str = " ".join(cmd)
            if "/cluster/resources --type vm" in cmd_str:
                return 0, vm_list, ""
            if "qm agent 5001 network-get-interfaces" in cmd_str:
                return 0, agent_ips, ""
            return 1, "", "not mocked"

        mock_run.side_effect = run_side_effect

        _phase_fleet_discover(cfg, ctx, args)

        mock_append.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# Config reload fix — load_config() instead of FreqConfig()
# ═══════════════════════════════════════════════════════════════════

class TestConfigReload(unittest.TestCase):
    """Test that _phase_configure reloads config via load_config() after writing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-reload-")
        self.toml_path = os.path.join(self.tmpdir, "freq.toml")
        with open(self.toml_path, "w") as f:
            f.write(
                "[freq]\n"
                'version = "2.0.0"\n'
                "\n"
                "[ssh]\n"
                'mode = "sudo"\n'
                "\n"
                "[pve]\n"
                "# nodes = []\n"
                "\n"
                "[vm.defaults]\n"
                '# gateway = ""\n'
                '# nameserver = "1.1.1.1"\n'
                "\n"
                "[infrastructure]\n"
                '# cluster_name = ""\n'
            )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_reload_uses_load_config(self, mock_fmt, mock_input, mock_lc):
        """After writing freq.toml, reload calls load_config(install_dir)."""
        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.install_dir = "/opt/freq"
        cfg.pve_nodes = []
        cfg.pve_node_names = []
        cfg.vm_gateway = ""
        cfg.vm_nameserver = ""
        cfg.cluster_name = ""
        cfg.ssh_mode = "sudo"
        cfg.pve_storage = {}

        mock_input.side_effect = [
            "10.0.0.1",   # PVE node IP
            "pve01",       # Node name
            "local-lvm",   # Storage
            "10.0.0.1",   # Gateway
            "1.1.1.1",    # Nameserver
            "test",        # Cluster name
            "sudo",        # SSH mode
        ]

        reloaded_cfg = MagicMock()
        reloaded_cfg.pve_nodes = ["10.0.0.1"]
        reloaded_cfg.pve_node_names = ["pve01"]
        reloaded_cfg.vm_gateway = "10.0.0.1"
        reloaded_cfg.vm_nameserver = "1.1.1.1"
        reloaded_cfg.cluster_name = "test"
        reloaded_cfg.ssh_mode = "sudo"
        reloaded_cfg.pve_storage = {}
        mock_lc.return_value = reloaded_cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg)

        # Verify load_config was called (not FreqConfig constructor)
        mock_lc.assert_called_once_with(cfg.install_dir)


if __name__ == "__main__":
    unittest.main()
