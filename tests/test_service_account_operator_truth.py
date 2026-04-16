"""Service account operator truth tests.

Proves:
1. Operator-visible CLI help does not hardcode freq-admin
2. Dashboard key push text says "service account" not "freq-admin"
3. Runtime config uses the configured account from freq.toml
4. Code default is freq-admin (documented) when config does not override it
"""

import os
import re
import tomllib
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCLIHelpServiceAccount(unittest.TestCase):
    """CLI help text must not hardcode freq-admin."""

    def test_init_fix_help_says_service_account(self):
        with open(os.path.join(REPO_ROOT, "freq/cli.py")) as f:
            src = f.read()
        match = re.search(r'--fix.*?help="([^"]+)"', src)
        self.assertIsNotNone(match)
        self.assertNotIn("freq-admin", match.group(1),
                          "--fix help must say 'service account' not 'freq-admin'")


class TestDashboardServiceAccount(unittest.TestCase):
    """Dashboard UI must not hardcode freq-admin in operator text."""

    def test_key_push_says_service_account(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        # Find the key push confirmation dialog
        push_idx = src.index("Push freq SSH key")
        push_block = src[push_idx:push_idx + 300]
        self.assertNotIn("freq-admin", push_block,
                          "Key push dialog must say 'service account' not 'freq-admin'")
        self.assertIn("service account", push_block.lower())


class TestRuntimeConfigTruth(unittest.TestCase):
    """Runtime must use configured account, code default is separate."""

    def test_code_default_is_freq_admin(self):
        """Code default is freq-admin — this is the fallback, not the configured value."""
        from freq.core.config import _DEFAULTS
        self.assertEqual(_DEFAULTS["ssh_service_account"], "freq-admin")

    def test_configured_account_matches_local_config(self):
        """Runtime config must match the local freq.toml service_account value when set."""
        from freq.core.config import load_config
        cfg_path = os.path.join(REPO_ROOT, "conf", "freq.toml")
        cfg = load_config()
        with open(cfg_path, "rb") as f:
            data = tomllib.load(f)
        expected = data.get("ssh", {}).get("service_account", "freq-admin")
        self.assertEqual(cfg.ssh_service_account, expected)

    def test_configured_value_is_nonempty(self):
        """Configured runtime service account must not be empty."""
        from freq.core.config import load_config
        cfg = load_config()
        self.assertTrue(cfg.ssh_service_account)


if __name__ == "__main__":
    unittest.main()
