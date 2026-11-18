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


class TestWatchdogContainerRuntimeContract(unittest.TestCase):
    """Containerized serve must not depend on systemd to expose watchdog health."""

    def test_serve_starts_embedded_watchdog_for_container_runtime(self):
        src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("def _start_embedded_watchdog_if_needed", src)
        self.assertIn("_is_container_runtime()", src)
        self.assertIn("freq-embedded-watchdog", src)
        self.assertIn('os.path.join(cfg.data_dir, "watchdog")', src)
        self.assertIn("_start_embedded_watchdog_if_needed(cfg)", src)

    def test_watchdog_runtime_check_accepts_container_supervision(self):
        src = (FREQ_ROOT / "freq" / "modules" / "watchdog.py").read_text()
        self.assertIn("def _is_container_runtime", src)
        self.assertIn("freq_serve_runtime", src)
        self.assertIn("container runtime supervises freq serve", src)


if __name__ == "__main__":
    unittest.main()
