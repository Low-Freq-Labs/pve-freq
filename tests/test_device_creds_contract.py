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
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

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
        with patch("freq.modules.init_cmd.fmt"):
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
        with patch("freq.modules.init_cmd.fmt"):
            result = self._load(cred_file)
        self.assertNotIn("switch", result)

    def test_no_password_no_password_file_skips(self):
        """No password and no password_file → device skipped."""
        cred_file = self._write("creds.toml", """
[idrac]
user = "root"
""")
        with patch("freq.modules.init_cmd.fmt"):
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
        with patch("freq.modules.init_cmd.fmt"):
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


class TestRuntimeDeviceCredentials(unittest.TestCase):
    """Runtime probes/actions must honor staged physical-device credentials."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-runtime-devcreds-")
        self.key_path = os.path.join(self.tmpdir, "fleet_key")
        with open(self.key_path, "w") as f:
            f.write("not-a-real-key\n")
        os.chmod(self.key_path, 0o600)
        self.creds_path = os.path.join(self.tmpdir, "device-credentials.toml")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _cfg(self):
        return SimpleNamespace(
            conf_dir=os.path.join(self.tmpdir, "conf"),
            install_dir=self.tmpdir,
            ssh_service_account="dc01-admin",
            ssh_key_path=os.path.join(self.tmpdir, "managed_key"),
        )

    def test_runtime_resolver_ignores_pfsense_bootstrap_user_and_key(self):
        from freq.core import device_credentials

        with open(self.creds_path, "w") as f:
            f.write(f"""
[pfsense]
username = "freq-ops"
ssh_key_file = "{self.key_path}"
""")
        old = device_credentials.DEVICE_CREDENTIAL_CANDIDATES
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (self.creds_path,)
        try:
            auth = device_credentials.resolve_device_ssh_auth(self._cfg(), "pfsense")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old

        self.assertEqual(auth["user"], "dc01-admin")
        self.assertEqual(auth["key_path"], "")
        self.assertEqual(auth["local_user"], "")
        self.assertEqual(auth["source"], "service-account")

    def test_runtime_resolver_does_not_infer_bootstrap_local_key_owner_for_pfsense(self):
        from freq.core import device_credentials

        key_path = "/home/freq-ops/.ssh/fleet_key"
        with open(self.creds_path, "w") as f:
            f.write(f"""
[pfsense]
username = "freq-ops"
ssh_key_file = "{key_path}"
""")
        old_candidates = device_credentials.DEVICE_CREDENTIAL_CANDIDATES
        old_isfile = device_credentials.os.path.isfile
        old_access = device_credentials.os.access
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (self.creds_path,)
        device_credentials.os.path.isfile = lambda path: path == self.creds_path
        device_credentials.os.access = lambda path, mode: path == self.creds_path
        try:
            auth = device_credentials.resolve_device_ssh_auth(self._cfg(), "pfsense")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old_candidates
            device_credentials.os.path.isfile = old_isfile
            device_credentials.os.access = old_access

        self.assertEqual(auth["user"], "dc01-admin")
        self.assertEqual(auth["key_path"], "")
        self.assertEqual(auth["local_user"], "")

    def test_staged_resolver_ignores_pfsense_bootstrap_key_when_service_cannot_stat_it(self):
        from freq.core import device_credentials

        key_path = "/home/freq-ops/.ssh/fleet_key"
        with open(self.creds_path, "w") as f:
            f.write(f"""
[pfsense]
username = "freq-ops"
ssh_key_file = "{key_path}"
""")
        old_candidates = device_credentials.DEVICE_CREDENTIAL_CANDIDATES
        old_isfile = device_credentials.os.path.isfile
        old_access = device_credentials.os.access
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (self.creds_path,)
        device_credentials.os.path.isfile = lambda path: path == self.creds_path
        device_credentials.os.access = lambda path, mode: path == self.creds_path
        try:
            auth = device_credentials.resolve_staged_device_ssh_auth(self._cfg(), "pfsense")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old_candidates
            device_credentials.os.path.isfile = old_isfile
            device_credentials.os.access = old_access

        self.assertEqual(auth["user"], "dc01-admin")
        self.assertEqual(auth["key_path"], "")
        self.assertEqual(auth["local_user"], "")
        self.assertEqual(auth["source"], "service-account")

    def test_staged_runtime_resolver_preserves_root_owned_password_file(self):
        from freq.core import device_credentials

        password_path = os.path.join(self.tmpdir, "truenas-password")
        with open(password_path, "w") as f:
            f.write("secret\n")
        os.chmod(password_path, 0)
        with open(self.creds_path, "w") as f:
            f.write(f"""
[truenas]
user = "dc01-admin"
password_file = "{password_path}"
""")
        old = device_credentials.DEVICE_CREDENTIAL_CANDIDATES
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (self.creds_path,)
        try:
            auth = device_credentials.resolve_staged_device_ssh_auth(self._cfg(), "truenas")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old
            os.chmod(password_path, 0o600)

        self.assertEqual(auth["user"], "dc01-admin")
        self.assertEqual(auth["password_file"], password_path)
        self.assertEqual(auth["key_path"], "")
        self.assertTrue(auth["sudo_password_file"])

    def test_truenas_staged_runtime_resolver_uses_service_account_when_truenas_is_api_only(self):
        from freq.core import device_credentials

        password_path = os.path.join(self.tmpdir, "dc01-admin-password")
        with open(password_path, "w") as f:
            f.write("secret\n")
        with open(self.creds_path, "w") as f:
            f.write(f"""
[truenas]
api_key_file = "/opt/pve-freq/data/secrets/truenas-prod.key"
url = "https://10.25.255.25/api/v2.0"

[service_account]
username = "dc01-admin"
password_file = "{password_path}"
""")
        old = device_credentials.DEVICE_CREDENTIAL_CANDIDATES
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (self.creds_path,)
        try:
            auth = device_credentials.resolve_staged_device_ssh_auth(self._cfg(), "truenas")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old

        self.assertEqual(auth["user"], "dc01-admin")
        self.assertEqual(auth["password_file"], password_path)
        self.assertEqual(auth["source"], "service-account")

    def test_truenas_staged_runtime_resolver_prefers_service_account_over_bootstrap_key(self):
        from freq.core import device_credentials

        password_path = os.path.join(self.tmpdir, "dc01-admin-password")
        with open(password_path, "w") as f:
            f.write("secret\n")
        with open(self.creds_path, "w") as f:
            f.write(f"""
[truenas]
host = "10.25.255.25"
username = "freq-ops"
ssh_key_file = "{self.key_path}"
api_key_file = "/opt/pve-freq/data/secrets/truenas-prod.key"

[service_account]
username = "dc01-admin"
password_file = "{password_path}"
""")
        old = device_credentials.DEVICE_CREDENTIAL_CANDIDATES
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (self.creds_path,)
        try:
            auth = device_credentials.resolve_staged_device_ssh_auth(self._cfg(), "truenas")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old

        self.assertEqual(auth["user"], "dc01-admin")
        self.assertEqual(auth["password_file"], password_path)
        self.assertEqual(auth["key_path"], "")

    def test_truenas_staged_runtime_resolver_prefers_service_account_key_when_present(self):
        from freq.core import device_credentials

        managed_key = os.path.join(self.tmpdir, "managed_key")
        with open(managed_key, "w") as f:
            f.write("not-a-real-key\n")
        os.chmod(managed_key, 0o600)
        password_path = os.path.join(self.tmpdir, "dc01-admin-password")
        with open(password_path, "w") as f:
            f.write("secret\n")
        with open(self.creds_path, "w") as f:
            f.write(f"""
[truenas]
host = "10.25.255.25"
username = "freq-ops"
ssh_key_file = "{self.key_path}"
api_key_file = "/opt/pve-freq/data/secrets/truenas-prod.key"

[service_account]
username = "dc01-admin"
password_file = "{password_path}"
""")
        cfg = self._cfg()
        cfg.ssh_key_path = managed_key
        old = device_credentials.DEVICE_CREDENTIAL_CANDIDATES
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (self.creds_path,)
        try:
            auth = device_credentials.resolve_staged_device_ssh_auth(cfg, "truenas")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old

        self.assertEqual(auth["user"], "dc01-admin")
        self.assertEqual(auth["key_path"], managed_key)
        self.assertEqual(auth["password_file"], "")

    def test_legacy_device_staged_runtime_resolver_uses_post_init_service_account_rsa(self):
        from freq.core import device_credentials

        password_path = os.path.join(self.tmpdir, "idrac-bootstrap-password")
        legacy_password_path = os.path.join(self.tmpdir, "legacy-device-pass")
        rsa_key_path = os.path.join(self.tmpdir, "freq_id_rsa")
        for path in (password_path, legacy_password_path, rsa_key_path):
            with open(path, "w") as f:
                f.write("secret\n")
            os.chmod(path, 0o600)
        with open(self.creds_path, "w") as f:
            f.write(f"""
[idrac]
username = "freq-ops"
password_file = "{password_path}"

[switch]
username = "freq-ops"
password_file = "{password_path}"
""")
        cfg = self._cfg()
        cfg.ssh_rsa_key_path = rsa_key_path
        cfg.legacy_password_file = legacy_password_path
        old = device_credentials.DEVICE_CREDENTIAL_CANDIDATES
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (self.creds_path,)
        try:
            for htype in ("idrac", "switch"):
                auth = device_credentials.resolve_staged_device_ssh_auth(cfg, htype)
                self.assertEqual(auth["user"], "dc01-admin")
                self.assertEqual(auth["key_path"], rsa_key_path)
                self.assertEqual(auth["password_file"], legacy_password_path)
                self.assertEqual(auth["source"], "service-account")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old

    def test_legacy_device_runtime_resolver_uses_post_init_service_account_rsa(self):
        from freq.core import device_credentials

        password_path = os.path.join(self.tmpdir, "switch-bootstrap-password")
        legacy_password_path = os.path.join(self.tmpdir, "legacy-device-pass")
        rsa_key_path = os.path.join(self.tmpdir, "freq_id_rsa")
        for path in (password_path, legacy_password_path, rsa_key_path):
            with open(path, "w") as f:
                f.write("secret\n")
            os.chmod(path, 0o600)
        with open(self.creds_path, "w") as f:
            f.write(f"""
[switch]
username = "freq-ops"
password_file = "{password_path}"
""")
        cfg = self._cfg()
        cfg.ssh_rsa_key_path = rsa_key_path
        cfg.legacy_password_file = legacy_password_path
        old = device_credentials.DEVICE_CREDENTIAL_CANDIDATES
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (self.creds_path,)
        try:
            auth = device_credentials.resolve_device_ssh_auth(cfg, "switch")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old

        self.assertEqual(auth["user"], "dc01-admin")
        self.assertEqual(auth["key_path"], rsa_key_path)
        self.assertEqual(auth["password_file"], legacy_password_path)
        self.assertEqual(auth["source"], "service-account")

    def test_runtime_resolver_falls_back_to_managed_account(self):
        from freq.core import device_credentials

        old = device_credentials.DEVICE_CREDENTIAL_CANDIDATES
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (os.path.join(self.tmpdir, "missing.toml"),)
        try:
            auth = device_credentials.resolve_device_ssh_auth(self._cfg(), "linux")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old

        self.assertEqual(auth["user"], "dc01-admin")
        self.assertEqual(auth["source"], "config")

    def test_pfsense_api_and_status_paths_use_runtime_resolver(self):
        fw_src = (FREQ_ROOT / "freq" / "api" / "fw.py").read_text()
        serve_src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        ssh_src = (FREQ_ROOT / "freq" / "core" / "ssh.py").read_text()
        doctor_src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        terminal_src = (FREQ_ROOT / "freq" / "api" / "terminal.py").read_text()

        self.assertIn("resolve_staged_device_ssh_auth(cfg, \"pfsense\")", fw_src)
        self.assertIn("user=auth[\"user\"]", fw_src)
        self.assertIn("key_path=auth[\"key_path\"]", fw_src)
        self.assertIn("local_user=auth.get(\"local_user\")", fw_src)
        self.assertIn("resolve_staged_device_ssh_auth(cfg, \"pfsense\")", serve_src)
        self.assertIn("user=pf_auth[\"user\"]", serve_src)
        self.assertIn("key_path=pf_auth[\"key_path\"]", serve_src)
        self.assertIn("local_user=pf_auth.get(\"local_user\")", serve_src)
        self.assertIn("[\"sudo\", \"-n\", \"-u\", local_user]", ssh_src)
        self.assertIn("resolve_staged_device_ssh_auth(cfg, h.htype)", doctor_src)
        self.assertIn('if h.htype in ("pfsense", "idrac", "switch", "truenas")', doctor_src)
        self.assertIn('sudo_password_file = auth.get("sudo_password_file", False)', doctor_src)
        self.assertIn("password_file=password_file", doctor_src)
        self.assertIn("sudo_password_file=sudo_password_file", doctor_src)
        self.assertIn("local_user=local_user", doctor_src)
        self.assertNotIn("resolve_device_ssh_auth(cfg, h.htype)", doctor_src)
        self.assertIn("def _terminal_ssh_auth", terminal_src)
        self.assertIn("_build_ssh_cmd(", terminal_src)
        self.assertIn("password_file=password_file", terminal_src)
        self.assertIn("sudo_password_file=sudo_password_file", terminal_src)
        self.assertIn("extra_opts=[\"-tt\"]", terminal_src)
        self.assertNotIn("sshpass_prefix", terminal_src)


class TestInitStagesServiceAccountCredentials(unittest.TestCase):
    """Init must write runtime service-account metadata, not rely on manual staging."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-init-stage-creds-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_service_account_metadata_preserves_existing_truenas_section(self):
        from freq.modules.init_cmd import _persist_service_account_credentials_metadata

        cred_dir = os.path.join(self.tmpdir, "credentials")
        os.makedirs(cred_dir)
        creds_path = os.path.join(cred_dir, "device-credentials.toml")
        with open(creds_path, "w") as f:
            f.write("""
[truenas]
host = "10.25.255.25"
username = "freq-ops"
ssh_key_file = "/home/freq-ops/.ssh/fleet_key"
api_key_file = "/opt/pve-freq/data/secrets/truenas-prod.key"
""")
        managed_key = os.path.join(self.tmpdir, "managed_key")
        rsa_key = os.path.join(self.tmpdir, "managed_rsa")
        cfg = SimpleNamespace(credentials_dir=cred_dir, ssh_key_path=managed_key, ssh_rsa_key_path=rsa_key)

        with patch("freq.modules.init_cmd._chown", return_value=True), \
             patch("freq.modules.init_cmd.fmt"):
            _persist_service_account_credentials_metadata(cfg, "dc01-admin", "SvcPass2026!")

        text = Path(creds_path).read_text()
        self.assertIn("[truenas]", text)
        self.assertIn('username = "freq-ops"', text)
        self.assertIn('api_key_file = "/opt/pve-freq/data/secrets/truenas-prod.key"', text)
        self.assertIn("[service_account]", text)
        self.assertIn('username = "dc01-admin"', text)
        self.assertIn(f'password_file = "{cred_dir}/dc01-admin-password"', text)
        self.assertEqual(Path(cred_dir, "dc01-admin-password").read_text(), "SvcPass2026!")

    def test_runtime_device_metadata_preserves_physical_device_auth(self):
        from freq.modules.init_cmd import _persist_runtime_device_credentials_metadata

        cred_dir = os.path.join(self.tmpdir, "credentials")
        managed_key = os.path.join(self.tmpdir, "managed_key")
        rsa_key = os.path.join(self.tmpdir, "managed_rsa")
        cfg = SimpleNamespace(credentials_dir=cred_dir, ssh_key_path=managed_key, ssh_rsa_key_path=rsa_key)
        device_creds = {
            "pfsense": {
                "user": "freq-ops",
                "host": "10.25.255.1",
                "key_path": "/home/freq-ops/.ssh/fleet_key",
            },
            "switch": {
                "user": "freq-ops",
                "host": "10.25.255.5",
                "password": "switch-secret",
            },
        }

        with patch("freq.modules.init_cmd._chown", return_value=True), \
             patch("freq.modules.init_cmd.fmt"):
            _persist_runtime_device_credentials_metadata(cfg, device_creds, "dc01-admin")

        creds_path = Path(cred_dir, "device-credentials.toml")
        text = creds_path.read_text()
        self.assertIn("[pfsense]", text)
        self.assertIn('username = "dc01-admin"', text)
        self.assertIn('host = "10.25.255.1"', text)
        self.assertIn(f'ssh_key_file = "{managed_key}"', text)
        self.assertIn("[switch]", text)
        self.assertIn(f'ssh_key_file = "{rsa_key}"', text)
        self.assertIn(f'password_file = "{cred_dir}/switch-password"', text)
        self.assertEqual(Path(cred_dir, "switch-password").read_text(), "switch-secret")
        self.assertNotIn("switch-secret", text)


if __name__ == "__main__":
    unittest.main()
