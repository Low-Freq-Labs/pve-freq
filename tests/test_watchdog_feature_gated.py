"""Tests for watchdog feature-gated contract.

Bug: After clean init, /api/watchdog/health returned 503 'WATCHDOG daemon
not reachable at localhost:9900' even though no freq-watchdog.service was
ever installed. The 503 was misleading — it implied a transient daemon
failure when the daemon was never meant to exist.

Contract decision: Watchdog is an optional add-on. Default state is
'not installed'. The feature must be explicitly enabled via
watchdog_enabled=true in freq.toml [services].

Fix:
- cfg.watchdog_enabled defaults to False
- Both proxy paths check watchdog_enabled first; if False, return 501
  Not Implemented with truthful 'Watchdog is not installed' message
- If True but unreachable, still returns 503 (daemon was expected but down)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestWatchdogFeatureFlag(unittest.TestCase):
    """Config must have watchdog_enabled flag defaulting to False."""

    def test_default_disabled(self):
        """cfg.watchdog_enabled defaults to False."""
        from freq.core.config import FreqConfig
        cfg = FreqConfig()
        self.assertFalse(cfg.watchdog_enabled)

    def test_defaults_dict_has_flag(self):
        """_DEFAULTS must include watchdog_enabled = False."""
        from freq.core.config import _DEFAULTS
        self.assertIn("watchdog_enabled", _DEFAULTS)
        self.assertFalse(_DEFAULTS["watchdog_enabled"])

    def test_config_loads_flag_from_services(self):
        """load_config reads watchdog_enabled from [services] section."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        self.assertIn('services.get("watchdog_enabled"', src)


class TestProxyReturns501WhenDisabled(unittest.TestCase):
    """Both proxy paths must return 501 when watchdog is not enabled."""

    def test_fleet_api_checks_enabled(self):
        """fleet.handle_watchdog_health must check watchdog_enabled."""
        src = (FREQ_ROOT / "freq" / "api" / "fleet.py").read_text()
        self.assertIn('watchdog_enabled', src)
        self.assertIn('501', src)
        self.assertIn('Watchdog is not installed', src)

    def test_serve_proxy_checks_enabled(self):
        """serve._proxy_watchdog must check watchdog_enabled."""
        src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        import re
        # Find the _proxy_watchdog function and check for watchdog_enabled check
        match = re.search(
            r'def _proxy_watchdog.*?(?=def )',
            src, re.DOTALL
        )
        self.assertIsNotNone(match)
        body = match.group()
        self.assertIn("watchdog_enabled", body)
        self.assertIn("501", body)

    def test_501_returned_before_url_request(self):
        """501 check must happen before any URL request (no connect attempt)."""
        src = (FREQ_ROOT / "freq" / "api" / "fleet.py").read_text()
        # The 'if not ... watchdog_enabled' check must appear before urlopen
        enabled_pos = src.find('getattr(cfg, "watchdog_enabled"')
        urlopen_pos = src.find('urllib.request.urlopen')
        self.assertGreater(urlopen_pos, enabled_pos,
                           "watchdog_enabled check must happen before urlopen")


if __name__ == "__main__":
    unittest.main()
