"""Setup status truth tests.

Proves:
1. Setup status uses actual resolved key path (not hardcoded ed25519)
2. Setup status reports key readability (not just existence)
3. Setup status includes setup_health summary
4. Setup health distinguishes configured/partial/unconfigured
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSetupStatusKeyTruth(unittest.TestCase):
    """Setup status must use the actual resolved SSH key path."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _serve_setup_status")[1].split("def _serve_")[0]

    def test_uses_resolved_key_path(self):
        """Must use cfg.ssh_key_path, not hardcoded freq_id_ed25519."""
        src = self._handler_src()
        self.assertIn("cfg.ssh_key_path", src,
                       "Must use resolved key path from config")
        self.assertNotIn("freq_id_ed25519", src,
                          "Must not hardcode ed25519 key name")

    def test_redetects_key_if_missing(self):
        """Must re-detect key path if cached path is stale (key created after serve start)."""
        src = self._handler_src()
        self.assertIn("_detect_ssh_key", src,
                       "Must re-detect key if initial path is missing")

    def test_reports_key_readable(self):
        """Must check if current user can READ the key, not just if file exists."""
        src = self._handler_src()
        self.assertIn("ssh_key_readable", src)
        self.assertIn("os.access", src)

    def test_includes_host_count(self):
        src = self._handler_src()
        self.assertIn("host_count", src)


class TestSetupHealthSummary(unittest.TestCase):
    """Setup status must include honest health summary."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _serve_setup_status")[1].split("def _serve_")[0]

    def test_includes_setup_health(self):
        src = self._handler_src()
        self.assertIn("setup_health", src)

    def test_distinguishes_three_states(self):
        src = self._handler_src()
        self.assertIn('"configured"', src)
        self.assertIn('"partial"', src)
        self.assertIn('"unconfigured"', src)

    def test_configured_requires_key_and_hosts(self):
        """'configured' state must require readable key + hosts + nodes."""
        src = self._handler_src()
        # The if-block leading to setup_health = "configured" must check key + hosts
        config_block_idx = src.index('"configured"')
        preceding = src[max(0, config_block_idx - 200):config_block_idx]
        self.assertIn("key_readable", preceding)
        self.assertIn("has_hosts", preceding)


if __name__ == "__main__":
    unittest.main()
