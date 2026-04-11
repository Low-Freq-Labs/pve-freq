"""Tests for setup state detection — must use resolved key path.

Bug: /api/setup/status reported ssh_key_exists=false and ssh_key_path
pointing to data/keys/freq_id_ed25519 (which doesn't exist) even though
the live resolved key was ~/.ssh/fleet_key (which works).

Root cause: _detect_ssh_key() didn't include fleet_key in search path
and didn't check readability. Fixed in earlier commits.

Contract:
- setup/status must use cfg.ssh_key_path (resolved by _detect_ssh_key)
- _detect_ssh_key resolves: ed25519 → fleet_key → rsa (first readable)
- ssh_key_exists reflects the RESOLVED key, not a hardcoded path
- ssh_key_readable checks os.access(R_OK)
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestSetupStatusUsesResolvedKey(unittest.TestCase):
    """Setup status handler must use cfg.ssh_key_path, not hardcoded path."""

    def test_serve_setup_uses_cfg_ssh_key_path(self):
        """_serve_setup_status must read from cfg.ssh_key_path."""
        path = FREQ_ROOT / "freq" / "modules" / "serve.py"
        with open(path) as f:
            content = f.read()
        # Find _serve_setup_status and verify it uses cfg.ssh_key_path
        self.assertIn("cfg.ssh_key_path", content)
        # Must NOT hardcode freq_id_ed25519 in setup status
        in_func = False
        for line in content.split("\n"):
            if "_serve_setup_status" in line and "def " in line:
                in_func = True
            if in_func:
                if "freq_id_ed25519" in line:
                    self.fail("_serve_setup_status hardcodes freq_id_ed25519")
                if line.strip().startswith("def ") and "_serve_setup_status" not in line:
                    break

    def test_setup_status_checks_readability(self):
        """Setup status must check key readability, not just existence."""
        path = FREQ_ROOT / "freq" / "modules" / "serve.py"
        with open(path) as f:
            content = f.read()
        self.assertIn("ssh_key_readable", content)
        self.assertIn("os.access(key_path, os.R_OK)", content)


class TestResolvedKeyIsLive(unittest.TestCase):
    """cfg.ssh_key_path must resolve to a live, readable key."""

    def test_resolved_key_exists(self):
        """The resolved SSH key must exist on disk."""
        from freq.core.config import load_config
        cfg = load_config()
        if cfg.ssh_key_path:
            self.assertTrue(os.path.isfile(cfg.ssh_key_path),
                            f"Resolved key must exist: {cfg.ssh_key_path}")

    def test_resolved_key_is_readable(self):
        """The resolved SSH key must be readable by current user."""
        from freq.core.config import load_config
        cfg = load_config()
        if cfg.ssh_key_path:
            self.assertTrue(os.access(cfg.ssh_key_path, os.R_OK),
                            f"Resolved key must be readable: {cfg.ssh_key_path}")

    def test_resolved_key_is_not_hardcoded_ed25519(self):
        """In this dev env, resolved key should be fleet_key (not freq_id_ed25519)."""
        from freq.core.config import load_config
        cfg = load_config()
        # freq_id_ed25519 doesn't exist in this checkout
        ed25519_path = os.path.join(cfg.key_dir, "freq_id_ed25519")
        if not os.path.isfile(ed25519_path):
            # If ed25519 doesn't exist, resolved key should NOT point to it
            self.assertNotEqual(cfg.ssh_key_path, ed25519_path,
                                "Resolved key must not point to non-existent ed25519")


if __name__ == "__main__":
    unittest.main()
