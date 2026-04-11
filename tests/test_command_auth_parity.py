"""Tests for command auth parity — CLI commands must use configured service account.

Bug: fleet.py and vm.py used module-level PLATFORM_SSH dict (computed at
import time with cfg=None → user=freq-admin). When the configured service
account was freq-ops, commands still SSH'd as freq-admin → permission denied.

Root cause: PLATFORM_SSH is a module-level dict frozen at import:
  PLATFORM_SSH = {htype: get_platform_ssh(htype) for htype in _PLATFORM_SSH_BASE}
Without cfg, get_platform_ssh falls back to _DEFAULTS["ssh_service_account"]
which is "freq-admin". Callers that use PLATFORM_SSH.get() always get freq-admin.

Fix: Replace PLATFORM_SSH.get(htype) with get_platform_ssh(htype, cfg) in
fleet.py and vm.py so the configured account is used at runtime.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestFleetUsesConfiguredAccount(unittest.TestCase):
    """fleet.py must use get_platform_ssh(htype, cfg), not PLATFORM_SSH."""

    def test_fleet_no_stale_platform_ssh(self):
        """fleet.py must not use PLATFORM_SSH for user resolution."""
        with open(FREQ_ROOT / "freq" / "modules" / "fleet.py") as f:
            content = f.read()
        # PLATFORM_SSH may still be imported for extra_opts — check it's not used for user
        lines_with_platform_ssh = []
        for i, line in enumerate(content.split("\n"), 1):
            if "PLATFORM_SSH.get(" in line and "extra_opts" not in line:
                lines_with_platform_ssh.append(i)
        self.assertEqual(lines_with_platform_ssh, [],
                         f"fleet.py still uses PLATFORM_SSH.get() for user at lines: {lines_with_platform_ssh}")

    def test_fleet_uses_get_platform_ssh(self):
        """fleet.py must import and use get_platform_ssh with cfg."""
        with open(FREQ_ROOT / "freq" / "modules" / "fleet.py") as f:
            content = f.read()
        self.assertIn("get_platform_ssh", content)


class TestVmUsesConfiguredAccount(unittest.TestCase):
    """vm.py must use get_platform_ssh(htype, cfg), not PLATFORM_SSH."""

    def test_vm_no_stale_platform_ssh(self):
        """vm.py must not use PLATFORM_SSH for user resolution."""
        with open(FREQ_ROOT / "freq" / "modules" / "vm.py") as f:
            content = f.read()
        lines_with_platform_ssh = []
        for i, line in enumerate(content.split("\n"), 1):
            if "PLATFORM_SSH.get(" in line and "extra_opts" not in line:
                lines_with_platform_ssh.append(i)
        self.assertEqual(lines_with_platform_ssh, [],
                         f"vm.py still uses PLATFORM_SSH.get() for user at lines: {lines_with_platform_ssh}")

    def test_vm_uses_get_platform_ssh(self):
        """vm.py must import and use get_platform_ssh with cfg."""
        with open(FREQ_ROOT / "freq" / "modules" / "vm.py") as f:
            content = f.read()
        self.assertIn("get_platform_ssh", content)


class TestGetPlatformSshRespectsCfg(unittest.TestCase):
    """get_platform_ssh(htype, cfg) must use cfg.ssh_service_account."""

    def test_with_cfg_uses_configured_account(self):
        """When cfg is provided, user must be cfg.ssh_service_account."""
        from freq.core.ssh import get_platform_ssh
        from freq.core.config import load_config
        cfg = load_config()
        platform = get_platform_ssh("linux", cfg)
        self.assertEqual(platform["user"], cfg.ssh_service_account)

    def test_without_cfg_uses_default(self):
        """When cfg is None, user must be the code default."""
        from freq.core.ssh import get_platform_ssh
        from freq.core.config import _DEFAULTS
        platform = get_platform_ssh("linux")
        self.assertEqual(platform["user"], _DEFAULTS["ssh_service_account"])

    def test_module_level_platform_ssh_uses_default(self):
        """Module-level PLATFORM_SSH must use code default (no cfg)."""
        from freq.core.ssh import PLATFORM_SSH
        from freq.core.config import _DEFAULTS
        self.assertEqual(PLATFORM_SSH["linux"]["user"], _DEFAULTS["ssh_service_account"])


if __name__ == "__main__":
    unittest.main()
