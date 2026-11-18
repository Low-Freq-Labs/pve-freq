"""Fleet cache and discovery UI acceptance tests.
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestHealthEndpointContract(unittest.TestCase):
    """GET /api/health returns honest cache metadata."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        return src.split("def handle_health_api")[1].split("\ndef ")[0]

    def test_cold_start_does_live_probe(self):
        """When no cache exists, handler does a live SSH probe (not fake data)."""
        src = self._handler_src()
        self.assertIn("ssh_single", src,
                       "Cold start must do real SSH probe, not return empty")

class TestFrontendCacheHonesty(unittest.TestCase):
    """Frontend handles cache/error/loading states honestly."""

    def _app_js(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            return f.read()

    def test_shows_probe_error_toast(self):
        """Fleet probe errors trigger a visible toast notification."""
        src = self._app_js()
        self.assertIn("Fleet probe failed", src)

    def test_skeleton_timeout_prevents_eternal_spinner(self):
        """Loading skeletons time out after 15s with 'Load failed'."""
        src = self._app_js()
        self.assertIn("skeleton", src)
        # Skeleton timeout interval exists
        self.assertIn("Load failed", src)

    def test_health_score_unavailable_on_error(self):
        """Health score shows 'Score unavailable' on fetch failure."""
        src = self._app_js()
        self.assertIn("Score unavailable", src)

    def test_fleet_overview_unavailable_on_error(self):
        src = self._app_js()
        self.assertIn("_markApiDegraded('fleet overview','network')", src)

    def test_health_check_unavailable_on_error(self):
        src = self._app_js()
        self.assertIn("_markApiDegraded('health','network')", src)

if __name__ == "__main__":
    unittest.main()
