"""Tests for runtime auth path — init-check must use resolved key, not hardcoded.

Bug: _scan_fleet() and _phase_verify() hardcoded key_dir/freq_id_ed25519
as the SSH key path. In repo-backed installs where freq_id_ed25519
doesn't exist but cfg.ssh_key_path resolves to ~/.ssh/fleet_key, these
functions reported "key not found" even though fleet auth was live.

Fix: use cfg.ssh_key_path (the resolved key) for fleet verification.
The key_dir check remains for init-generated key existence reporting.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestScanFleetUsesResolvedKey(unittest.TestCase):
    """_scan_fleet must use cfg.ssh_key_path, not hardcoded key_dir path."""

    def test_scan_fleet_uses_cfg_ssh_key_path(self):
        """_scan_fleet source must reference cfg.ssh_key_path."""
        path = FREQ_ROOT / "freq" / "modules" / "init_cmd.py"
        with open(path) as f:
            content = f.read()
        # Find _scan_fleet function and check it uses cfg.ssh_key_path
        in_func = False
        found_resolved = False
        for line in content.split("\n"):
            if "def _scan_fleet" in line:
                in_func = True
            if in_func:
                if "cfg.ssh_key_path" in line and "key_file" in line:
                    found_resolved = True
                    break
                if line.strip().startswith("def ") and "def _scan_fleet" not in line:
                    break
        self.assertTrue(found_resolved,
                        "_scan_fleet must use cfg.ssh_key_path for key_file")

    def test_scan_fleet_not_hardcoded_key_dir(self):
        """_scan_fleet must NOT hardcode key_dir/freq_id_ed25519."""
        path = FREQ_ROOT / "freq" / "modules" / "init_cmd.py"
        with open(path) as f:
            content = f.read()
        in_func = False
        for line in content.split("\n"):
            if "def _scan_fleet" in line:
                in_func = True
            if in_func:
                if 'os.path.join(cfg.key_dir, "freq_id_ed25519")' in line and "key_file" in line:
                    self.fail("_scan_fleet still hardcodes key_dir/freq_id_ed25519")
                if line.strip().startswith("def ") and "def _scan_fleet" not in line:
                    break


class TestVerifyHostChecksReadability(unittest.TestCase):
    """_verify_host must check key readability, not just existence."""

    def test_verify_host_checks_access(self):
        """_verify_host must use os.access for key check."""
        path = FREQ_ROOT / "freq" / "modules" / "init_cmd.py"
        with open(path) as f:
            content = f.read()
        self.assertIn("os.access(key, os.R_OK)", content,
                       "_verify_host must check key readability")


class TestConfigResolvesKey(unittest.TestCase):
    """Config loader must resolve to a readable key."""

    def test_ssh_key_path_is_readable(self):
        """cfg.ssh_key_path must point to a readable file (or be empty)."""
        import os
        from freq.core.config import load_config
        cfg = load_config()
        if cfg.ssh_key_path:
            self.assertTrue(os.path.isfile(cfg.ssh_key_path),
                            f"ssh_key_path must exist: {cfg.ssh_key_path}")
            self.assertTrue(os.access(cfg.ssh_key_path, os.R_OK),
                            f"ssh_key_path must be readable: {cfg.ssh_key_path}")


if __name__ == "__main__":
    unittest.main()
