"""Tests for dashboard TLS config activation via restart.

Bug: Phase 9 starts the dashboard service early (for healthy init
reporting), then Phase 9l generates TLS cert and updates freq.toml
with tls_cert/tls_key paths. But the already-running dashboard loaded
config before those paths were set — it's serving plain HTTP with
stale config in memory. Post-init probes get 'SSL record layer' on
HTTPS and plain HTTP succeeds, contradicting the 'TLS configured'
status messaging.

Fix: When Phase 9l writes new TLS paths to freq.toml, restart the
dashboard service so the new config takes effect. This closes the
gap between 'init says TLS is configured' and 'dashboard actually
speaks TLS on the advertised port'.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestPhase9lRestartsDashboard(unittest.TestCase):
    """Phase 9l must restart freq-dashboard after TLS config write."""

    def test_tracks_tls_config_changed(self):
        """Phase 9l must set a tls_config_changed flag when writing new paths."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("tls_config_changed = True", src)

    def test_restart_on_config_change(self):
        """If tls_config_changed is True, restart freq-dashboard."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        idx = src.find('if tls_config_changed:')
        self.assertNotEqual(idx, -1)
        block = src[idx:idx + 1000]
        self.assertIn('"systemctl", "restart", "freq-dashboard"', block)

    def test_checks_service_is_active_before_restart(self):
        """Must check is-active before restart to avoid stalling on dead service."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        idx = src.find('tls_config_changed:')
        self.assertNotEqual(idx, -1)
        block = src[idx:idx + 1000]
        self.assertIn('"systemctl", "is-active", "freq-dashboard"', block)


if __name__ == "__main__":
    unittest.main()
