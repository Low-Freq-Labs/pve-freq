"""Tests for HTTP monitoring and Docker fleet features."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMonitorDataclass(unittest.TestCase):
    """Test Monitor type."""

    def test_monitor_defaults(self):
        from freq.core.types import Monitor
        m = Monitor(name="test", url="http://example.com")
        self.assertEqual(m.interval, 60)
        self.assertEqual(m.timeout, 10)
        self.assertEqual(m.expected_status, 200)
        self.assertEqual(m.method, "GET")
        self.assertTrue(m.notify)

    def test_monitor_custom(self):
        from freq.core.types import Monitor
        m = Monitor(
            name="api",
            url="http://example.com/api",
            interval=30,
            timeout=5,
            expected_status=204,
            method="HEAD",
            keyword="ok",
            notify=False,
        )
        self.assertEqual(m.interval, 30)
        self.assertEqual(m.expected_status, 204)
        self.assertFalse(m.notify)


class TestMonitorConfigLoading(unittest.TestCase):
    """Test loading [[monitor]] from TOML data."""

    def test_load_monitors(self):
        from freq.core.config import _load_monitors
        data = {
            "monitor": [
                {"name": "dash", "url": "http://10.0.0.1:8888/healthz"},
                {"name": "api", "url": "http://10.0.0.1:8888/readyz", "interval": 30},
            ]
        }
        monitors = _load_monitors(data)
        self.assertEqual(len(monitors), 2)
        self.assertEqual(monitors[0].name, "dash")
        self.assertEqual(monitors[1].interval, 30)

    def test_load_monitors_empty(self):
        from freq.core.config import _load_monitors
        monitors = _load_monitors({})
        self.assertEqual(monitors, [])

    def test_load_monitors_missing_url_skipped(self):
        from freq.core.config import _load_monitors
        data = {"monitor": [{"name": "broken"}, {"name": "ok", "url": "http://x"}]}
        monitors = _load_monitors(data)
        self.assertEqual(len(monitors), 1)
        self.assertEqual(monitors[0].name, "ok")


class TestHTTPChecks(unittest.TestCase):
    """Test HTTP endpoint checking."""

    def test_check_returns_results(self):
        from freq.jarvis.patrol import check_http_monitors
        from freq.core.types import Monitor
        # Use a URL that won't resolve — tests error handling
        monitors = [Monitor(name="bad", url="http://192.0.2.1:1/nope", timeout=1)]
        results = check_http_monitors(monitors)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertTrue(results[0]["error"])

    def test_check_empty_list(self):
        from freq.jarvis.patrol import check_http_monitors
        results = check_http_monitors([])
        self.assertEqual(results, [])


class TestServeRoutes(unittest.TestCase):
    """Test monitoring routes are present in the complete registry."""

    def test_monitor_routes_exist(self):
        from freq.modules.serve import FreqHandler
        all_routes = FreqHandler._load_routes()
        self.assertIn("/api/monitors", all_routes)
        self.assertIn("/api/monitors/check", all_routes)
        self.assertIn("/api/docker-fleet", all_routes)


if __name__ == "__main__":
    unittest.main()
