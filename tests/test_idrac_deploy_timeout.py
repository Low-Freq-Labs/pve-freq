"""Tests for iDRAC deploy timeout — bounded device deploy prevents hangs.

Bug: Phase 8 iDRAC deploy could hang indefinitely. After "Connected to
iDRAC", the slot query loop (14 iterations × 10s timeout each = 140s max)
had no overall timeout. If the iDRAC was slow to respond, init would stall.

Root cause: Individual racadm commands had per-command timeouts, but the
overall _deploy_idrac function had no total time bound. A slow iDRAC
could keep init hanging for minutes.

Fix: Added DEVICE_DEPLOY_TIMEOUT (120s) as overall time bound for
_deploy_idrac and _deploy_switch. Timeout is checked between phases
(after connect, after slot query, before user setup, before key deploy).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestDeviceDeployTimeoutConstant(unittest.TestCase):
    """DEVICE_DEPLOY_TIMEOUT must exist and be reasonable."""

    def test_constant_exists(self):
        """DEVICE_DEPLOY_TIMEOUT must be defined."""
        from freq.modules.init_cmd import DEVICE_DEPLOY_TIMEOUT
        self.assertIsInstance(DEVICE_DEPLOY_TIMEOUT, (int, float))

    def test_constant_reasonable(self):
        """DEVICE_DEPLOY_TIMEOUT must be between 30s and 300s."""
        from freq.modules.init_cmd import DEVICE_DEPLOY_TIMEOUT
        self.assertGreaterEqual(DEVICE_DEPLOY_TIMEOUT, 30)
        self.assertLessEqual(DEVICE_DEPLOY_TIMEOUT, 300)


class TestIdracDeployHasTimeout(unittest.TestCase):
    """_deploy_idrac must have overall timeout checks."""

    def test_deploy_idrac_has_timeout_tracking(self):
        """_deploy_idrac must track elapsed time."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Must use time.monotonic() to track deploy start
        self.assertIn("deploy_start = time.monotonic()", src)

    def test_deploy_idrac_checks_timeout(self):
        """_deploy_idrac must check timeout between phases."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("_check_timeout", src)
        self.assertIn("DEVICE_DEPLOY_TIMEOUT", src)

    def test_timeout_before_slot_query(self):
        """Timeout must be checked before the slot query loop."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn('_check_timeout("slot_query")', src)

    def test_timeout_before_user_setup(self):
        """Timeout must be checked before each user setup command."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn('_check_timeout("user_setup")', src)


class TestSwitchDeployHasTimeout(unittest.TestCase):
    """_deploy_switch must also have overall timeout tracking."""

    def test_deploy_switch_has_timeout_tracking(self):
        """_deploy_switch must track elapsed time."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Check that _deploy_switch also has deploy_start
        import re
        switch_fn = re.search(r'def _deploy_switch\(.*?\n(?=def |\Z)', src, re.DOTALL)
        self.assertIsNotNone(switch_fn)
        self.assertIn("deploy_start", switch_fn.group())


if __name__ == "__main__":
    unittest.main()
