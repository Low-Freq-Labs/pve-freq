"""Tests for watchdog proxy contract — consistent status codes across paths.

Bug: /api/watchdog/health (fleet.py) returned 503 for unreachable watchdog,
but /api/comms/* and /api/watch/* (serve.py) returned 502 for the same
condition. Both now return 503 (Service Unavailable).

Watchdog proxy contract:
- URLError (daemon unreachable) → 503 with watchdog_down=True
- General Exception (proxy error) → 502 with error message
- Both paths use the same JSON response shape
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestWatchdogStatusCodes(unittest.TestCase):
    """Both watchdog proxy paths must use the same status codes."""

    def _find_watchdog_unreachable_status(self, filepath):
        """Find the HTTP status code used for URLError in watchdog proxy."""
        import re
        with open(filepath) as f:
            content = f.read()
        # Find URLError blocks and extract status from nearby watchdog_down response
        blocks = re.split(r'except urllib\.error\.URLError', content)
        for block in blocks[1:]:  # Skip text before first URLError
            # Look in the first ~200 chars after the except for the status code
            snippet = block[:300]
            if "watchdog_down" in snippet:
                m = re.search(r',\s*(\d{3})\s*\)', snippet)
                if m:
                    return int(m.group(1))
        return None

    def test_fleet_api_returns_503_on_unreachable(self):
        """fleet.py handle_watchdog_health must return 503 for URLError."""
        status = self._find_watchdog_unreachable_status(
            FREQ_ROOT / "freq" / "api" / "fleet.py"
        )
        self.assertEqual(status, 503,
                         "fleet.py watchdog URLError must return 503 (Service Unavailable)")

    def test_serve_proxy_returns_503_on_unreachable(self):
        """serve.py _proxy_watchdog must return 503 for URLError."""
        status = self._find_watchdog_unreachable_status(
            FREQ_ROOT / "freq" / "modules" / "serve.py"
        )
        self.assertEqual(status, 503,
                         "serve.py watchdog URLError must return 503 (Service Unavailable)")

    def test_both_paths_agree(self):
        """Both watchdog proxy paths must use the same status for URLError."""
        fleet_status = self._find_watchdog_unreachable_status(
            FREQ_ROOT / "freq" / "api" / "fleet.py"
        )
        serve_status = self._find_watchdog_unreachable_status(
            FREQ_ROOT / "freq" / "modules" / "serve.py"
        )
        self.assertEqual(fleet_status, serve_status,
                         f"Status code mismatch: fleet.py={fleet_status}, serve.py={serve_status}")


class TestWatchdogResponseShape(unittest.TestCase):
    """Both paths must include watchdog_down=True in the error response."""

    def _has_watchdog_down_flag(self, filepath):
        """Check if URLError handler includes watchdog_down in response."""
        with open(filepath) as f:
            content = f.read()
        # Find the URLError block and check for watchdog_down
        import re
        pattern = r'except urllib\.error\.URLError.*?(?=except|$)'
        matches = re.findall(pattern, content, re.DOTALL)
        return any("watchdog_down" in m for m in matches)

    def test_fleet_api_includes_watchdog_down(self):
        self.assertTrue(self._has_watchdog_down_flag(
            FREQ_ROOT / "freq" / "api" / "fleet.py"
        ))

    def test_serve_proxy_includes_watchdog_down(self):
        self.assertTrue(self._has_watchdog_down_flag(
            FREQ_ROOT / "freq" / "modules" / "serve.py"
        ))


if __name__ == "__main__":
    unittest.main()
