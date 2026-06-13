"""Tests for watchdog feature-gated contract.

Watchdog is now a core local truth-auditor, but it still has a feature flag so
operators can disable the dashboard proxy intentionally. Default installs
enable it and init installs freq-watchdog.service as an advisory service.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestWatchdogFeatureFlag(unittest.TestCase):
    """Config must have watchdog_enabled flag defaulting to True."""

    def test_default_enabled(self):
        """cfg.watchdog_enabled defaults to True."""
        from freq.core.config import FreqConfig
        cfg = FreqConfig()
        self.assertTrue(cfg.watchdog_enabled)

    def test_defaults_dict_has_flag(self):
        """_DEFAULTS must include watchdog_enabled = True."""
        from freq.core.config import _DEFAULTS
        self.assertIn("watchdog_enabled", _DEFAULTS)
        self.assertTrue(_DEFAULTS["watchdog_enabled"])

    def test_config_loads_flag_from_services(self):
        """load_config reads watchdog_enabled from [services] section."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        self.assertIn('services.get("watchdog_enabled"', src)


class TestProxyReturnsCleanStateWhenDisabled(unittest.TestCase):
    """Both proxy paths must return clean optional state when watchdog is not enabled."""

    def test_fleet_api_checks_enabled(self):
        """fleet.handle_watchdog_health must check watchdog_enabled."""
        src = (FREQ_ROOT / "freq" / "api" / "fleet.py").read_text()
        self.assertIn('watchdog_enabled', src)
        self.assertIn('"watchdog_installed": False', src)
        self.assertIn('"status": "not_installed"', src)

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
        self.assertIn('"watchdog_installed": False', body)
        self.assertIn('"status": "not_installed"', body)

    def test_disabled_state_returned_before_url_request(self):
        """Disabled-state check must happen before any URL request (no connect attempt)."""
        src = (FREQ_ROOT / "freq" / "api" / "fleet.py").read_text()
        # The 'if not ... watchdog_enabled' check must appear before urlopen
        enabled_pos = src.find('getattr(cfg, "watchdog_enabled"')
        urlopen_pos = src.find('urllib.request.urlopen')
        self.assertGreater(urlopen_pos, enabled_pos,
                           "watchdog_enabled check must happen before urlopen")


if __name__ == "__main__":
    unittest.main()
