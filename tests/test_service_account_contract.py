"""Tests for service account identity contract.

Contract:
- Default template: freq-admin (in _DEFAULTS, example configs)
- Live identity: cfg.ssh_service_account (user-configured service account)
- Runtime code must use cfg.ssh_service_account, never hardcode freq-admin
- Example configs document the default, not the live value
- Doctor, init --check, fleet SSH all use the configured account

Bug: Multiple code paths had hardcoded "freq-admin" fallbacks instead of
using cfg.ssh_service_account, causing mismatches when the user configured
a different service account.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestServiceAccountDefault(unittest.TestCase):
    """The default service account must be defined in one place."""

    def test_default_is_freq_admin(self):
        """_DEFAULTS must define ssh_service_account as freq-admin."""
        from freq.core.config import _DEFAULTS
        self.assertEqual(_DEFAULTS["ssh_service_account"], "freq-admin")

    def test_config_reads_from_toml(self):
        """load_config must read service_account from freq.toml."""
        from freq.core.config import load_config
        cfg = load_config()
        self.assertTrue(cfg.ssh_service_account, "service account must not be empty")


class TestNoHardcodedFreqAdmin(unittest.TestCase):
    """Runtime code must not hardcode freq-admin as fallback."""

    def _count_hardcoded_fallbacks(self, filepath):
        """Count lines with hardcoded 'freq-admin' that aren't defaults/examples/comments."""
        count = 0
        with open(filepath) as f:
            for i, line in enumerate(f, 1):
                stripped = line.strip()
                # Skip pure comments (# ...) and docstring lines
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                # Skip the _DEFAULTS definition (that's the canonical default)
                if "_DEFAULTS" in line or "default" in line.lower():
                    continue
                # Skip example/template references
                if "example" in line.lower() or "template" in line.lower():
                    continue
                # Skip log examples
                if "logger" in line.lower() and "freq-admin" in line:
                    continue
                # Check for hardcoded freq-admin in actual code
                if '"freq-admin"' in line and ("or " in line or "get(" in line):
                    count += 1
        return count

    def test_terminal_runtime_identity_fails_closed(self):
        """F3-4: terminal auth uses the validated configured identity."""
        from freq.api.terminal import _terminal_ssh_auth
        from freq.core.config import validated_runtime_service_account

        cfg = SimpleNamespace(
            ssh_service_account="portable-svc",
            ssh_key_path="",
            ssh_rsa_key_path="",
            legacy_password_file="",
        )
        self.assertEqual(validated_runtime_service_account(cfg), "portable-svc")
        self.assertEqual(_terminal_ssh_auth(cfg, "linux")["user"], "portable-svc")
        cfg.ssh_service_account = ""
        with self.assertRaisesRegex(ValueError, "ssh.service_account"):
            validated_runtime_service_account(cfg)
        with self.assertRaisesRegex(ValueError, "ssh.service_account"):
            _terminal_ssh_auth(cfg, "linux")

        source = (FREQ_ROOT / "freq/api/terminal.py").read_text()
        self.assertNotIn('or "freq-admin"', source)
        self.assertIn("validated_runtime_service_account", source)

    def test_device_credentials_runtime_identity_fails_closed(self):
        """F3-4: managed device auth cannot invent a service username."""
        from freq.core.device_credentials import _service_account_ssh_auth

        cfg = SimpleNamespace(
            ssh_service_account="",
            ssh_key_path="",
            ssh_rsa_key_path="",
            legacy_password_file="",
        )
        with self.assertRaisesRegex(ValueError, "ssh.service_account"):
            _service_account_ssh_auth(cfg, "linux", {})

        source = (FREQ_ROOT / "freq/core/device_credentials.py").read_text()
        self.assertNotIn('or "freq-admin"', source)
        self.assertIn("validated_runtime_service_account", source)

    def test_doctor_runtime_identity_fails_closed_without_healing(self):
        """F3-4: doctor reports invalid live identity instead of substituting."""
        import inspect
        from freq.core import doctor

        for function in (
            doctor._check_pve_nodes,
            doctor._check_pve_token_local,
            doctor._check_pve_token_drift,
        ):
            with self.subTest(doctor_consumer=function.__name__):
                source = inspect.getsource(function)
                self.assertIn("validated_runtime_service_account", source)
                self.assertNotIn('"freq-admin"', source)

    def test_init_runtime_identity_fails_closed_without_fallback(self):
        """F3-4: init runtime operations share the config-layer resolver."""
        source = (FREQ_ROOT / "freq/modules/init_cmd.py").read_text()
        self.assertIn("validated_runtime_service_account", source)
        self.assertNotIn('or "freq-admin"', source)
        self.assertNotIn('else "freq-admin"', source)

    def test_ssh_module_uses_config(self):
        """ssh.py must use cfg.ssh_service_account, not hardcoded freq-admin."""
        with open(FREQ_ROOT / "freq" / "core" / "ssh.py") as f:
            content = f.read()
        self.assertIn("cfg.ssh_service_account", content,
                       "SSH module must reference configured account")


class TestExampleConfigsDocumentDefault(unittest.TestCase):
    """Example configs must document the default service account."""

    def test_freq_toml_example_shows_default(self):
        """freq.toml.example must show freq-admin as the default."""
        with open(FREQ_ROOT / "freq" / "data" / "conf-templates" / "freq.toml.example") as f:
            content = f.read()
        self.assertIn("freq-admin", content,
                       "Example config must show the default service account")


if __name__ == "__main__":
    unittest.main()
