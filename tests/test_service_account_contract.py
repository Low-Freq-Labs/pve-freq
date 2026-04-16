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

    def test_serve_no_hardcoded_fallback(self):
        """serve.py must not use 'or \"freq-admin\"' fallbacks."""
        refs = self._count_hardcoded_fallbacks(FREQ_ROOT / "freq" / "modules" / "serve.py")
        self.assertEqual(refs, 0, f"serve.py has {refs} hardcoded freq-admin fallback(s)")

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
