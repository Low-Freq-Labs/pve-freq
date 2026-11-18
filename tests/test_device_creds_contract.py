"""Device credential loading, staging, and runtime contract tests."""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix  # noqa: E402, I001

FREQ_ROOT = Path(__file__).parent.parent


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

    def _case_runtime_resolver_ignores_pfsense_bootstrap_user_and_key(self):
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

    def _case_runtime_resolver_does_not_infer_bootstrap_local_key_owner_for_pfsense(self):
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

    def _case_staged_resolver_ignores_pfsense_bootstrap_key_when_service_cannot_stat_it(self):
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

    def _case_staged_runtime_resolver_preserves_root_owned_password_file(self):
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
        old_access = device_credentials.os.access
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (self.creds_path,)
        device_credentials.os.access = lambda path, mode: (
            False if path == password_path else old_access(path, mode)
        )
        try:
            auth = device_credentials.resolve_staged_device_ssh_auth(self._cfg(), "truenas")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old
            device_credentials.os.access = old_access
            os.chmod(password_path, 0o600)

        self.assertEqual(auth["user"], "dc01-admin")
        self.assertEqual(auth["password_file"], password_path)
        self.assertEqual(auth["key_path"], "")
        self.assertTrue(auth["sudo_password_file"])

    def _case_truenas_staged_runtime_resolver_uses_service_account_when_truenas_is_api_only(self):
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

    def _case_truenas_staged_runtime_resolver_prefers_service_account_over_bootstrap_key(self):
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

    def _case_truenas_staged_runtime_resolver_prefers_service_account_key_when_present(self):
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

    def _case_legacy_device_staged_runtime_resolver_uses_post_init_service_account_rsa(self):
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

    def _case_legacy_device_runtime_resolver_uses_post_init_service_account_rsa(self):
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

    def _case_runtime_resolver_falls_back_to_managed_account(self):
        from freq.core import device_credentials

        old = device_credentials.DEVICE_CREDENTIAL_CANDIDATES
        device_credentials.DEVICE_CREDENTIAL_CANDIDATES = (os.path.join(self.tmpdir, "missing.toml"),)
        try:
            auth = device_credentials.resolve_device_ssh_auth(self._cfg(), "linux")
        finally:
            device_credentials.DEVICE_CREDENTIAL_CANDIDATES = old

        self.assertEqual(auth["user"], "dc01-admin")
        self.assertEqual(auth["source"], "config")

    def _case_pfsense_api_and_status_paths_use_runtime_resolver(self):
        fw_src = (FREQ_ROOT / "freq" / "api" / "fw.py").read_text()
        serve_src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        command_src = (FREQ_ROOT / "freq" / "services" / "device_command.py").read_text()
        ssh_src = (FREQ_ROOT / "freq" / "core" / "ssh.py").read_text()
        doctor_src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        terminal_src = (FREQ_ROOT / "freq" / "api" / "terminal.py").read_text()

        self.assertIn("resolve_staged_device_ssh_auth(cfg, \"pfsense\")", fw_src)
        self.assertIn("user=auth[\"user\"]", fw_src)
        self.assertIn("key_path=auth[\"key_path\"]", fw_src)
        self.assertIn("local_user=auth.get(\"local_user\")", fw_src)
        self.assertIn(
            "resolve_auth=lambda cfg, device_type: resolve_staged_device_ssh_auth(cfg, device_type)",
            serve_src,
        )
        self.assertIn('auth = runtime.resolve_auth(cfg, "pfsense")', command_src)
        self.assertIn('user=auth["user"]', command_src)
        self.assertIn('key_path=auth["key_path"]', command_src)
        self.assertIn('local_user=auth.get("local_user")', command_src)
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


RUNTIME_DEVICE_CREDENTIAL_CASES = (
    "_case_runtime_resolver_ignores_pfsense_bootstrap_user_and_key",
    "_case_runtime_resolver_does_not_infer_bootstrap_local_key_owner_for_pfsense",
    "_case_staged_resolver_ignores_pfsense_bootstrap_key_when_service_cannot_stat_it",
    "_case_staged_runtime_resolver_preserves_root_owned_password_file",
    "_case_truenas_staged_runtime_resolver_uses_service_account_when_truenas_is_api_only",
    "_case_truenas_staged_runtime_resolver_prefers_service_account_over_bootstrap_key",
    "_case_truenas_staged_runtime_resolver_prefers_service_account_key_when_present",
    "_case_legacy_device_staged_runtime_resolver_uses_post_init_service_account_rsa",
    "_case_legacy_device_runtime_resolver_uses_post_init_service_account_rsa",
    "_case_runtime_resolver_falls_back_to_managed_account",
    "_case_pfsense_api_and_status_paths_use_runtime_resolver",
)


class TestRuntimeDeviceCredentialsMatrix(unittest.TestCase):
    def test_runtime_device_credentials_matrix(self):
        run_case_matrix(self, TestRuntimeDeviceCredentials, RUNTIME_DEVICE_CREDENTIAL_CASES)


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
