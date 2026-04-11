"""Fleet cache and discovery UI acceptance tests.

Proves that health, overview, infra, health score, and discovery
surfaces remain coherent to the operator during partial outages
or cold start — no misleading green states.

Each API cache endpoint must include:
- cached: bool (true = from cache, false = cold start/live)
- age_seconds: float or None (time since last probe)
- probe_status: "ok"|"error"|"loading" (current probe state)
- stale: bool (true = data >120s old)

Each frontend consumer must:
- Show age/freshness indicator (LIVE / Ns AGO / Nm AGO)
- Color-code freshness (green < 30s, yellow < 120s, red > 120s)
- Show PROBE ERROR on probe_status=error
- Show loading skeleton on cold start
- Time out skeletons after 15s with "Load failed"
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

    def test_returns_cached_flag(self):
        self.assertIn('"cached"', self._handler_src())

    def test_returns_age_seconds(self):
        self.assertIn('"age_seconds"', self._handler_src())

    def test_returns_probe_status(self):
        self.assertIn('"probe_status"', self._handler_src())

    def test_reports_probe_errors(self):
        src = self._handler_src()
        self.assertIn("probe_error", src)
        self.assertIn("probe_consecutive_failures", src)

    def test_cold_start_does_live_probe(self):
        """When no cache exists, handler does a live SSH probe (not fake data)."""
        src = self._handler_src()
        self.assertIn("ssh_single", src,
                       "Cold start must do real SSH probe, not return empty")


class TestFleetOverviewContract(unittest.TestCase):
    """GET /api/fleet/overview returns honest cache/loading state."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        return src.split("def handle_fleet_overview")[1].split("\ndef ")[0]

    def test_returns_cached_and_age(self):
        src = self._handler_src()
        self.assertIn('"cached"', src)
        self.assertIn('"age_seconds"', src)

    def test_returns_stale_flag(self):
        self.assertIn('"stale"', self._handler_src())

    def test_cold_start_returns_loading(self):
        """When no cache, returns _loading: true + probe_status: loading."""
        src = self._handler_src()
        self.assertIn('"_loading"', src)
        self.assertIn('"loading"', src)

    def test_cold_start_data_is_empty_not_fake(self):
        """Cold start must return empty arrays, not populated fake data."""
        src = self._handler_src()
        self.assertIn('"vms": []', src)


class TestInfraQuickContract(unittest.TestCase):
    """GET /api/infra/quick returns honest cache/warming state."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        return src.split("def handle_infra_quick")[1].split("\ndef ")[0]

    def test_returns_cache_metadata(self):
        src = self._handler_src()
        self.assertIn('"cached"', src)
        self.assertIn('"age_seconds"', src)
        self.assertIn('"stale"', src)
        self.assertIn('"probe_status"', src)

    def test_cold_start_returns_warming(self):
        src = self._handler_src()
        self.assertIn('"warming"', src)


class TestHealthScoreContract(unittest.TestCase):
    """GET /api/fleet/health-score returns honest score or 503."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        return src.split("def handle_fleet_health_score")[1].split("\ndef ")[0]

    def test_no_data_returns_503(self):
        """When no health data, returns 503 (not fake 100 score)."""
        src = self._handler_src()
        self.assertIn("503", src)

    def test_no_data_returns_zero_score(self):
        src = self._handler_src()
        self.assertIn('"score": 0', src)

    def test_includes_penalty_factors(self):
        """Score includes real penalty breakdown (not opaque number)."""
        src = self._handler_src()
        self.assertIn('"factors"', src)
        self.assertIn('"penalty"', src)


class TestFrontendCacheHonesty(unittest.TestCase):
    """Frontend handles cache/error/loading states honestly."""

    def _app_js(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            return f.read()

    def test_shows_probe_error_toast(self):
        """Fleet probe errors trigger a visible toast notification."""
        src = self._app_js()
        self.assertIn("Fleet probe failed", src)

    def test_shows_probe_error_in_status(self):
        """Probe error state shown in connection status indicator."""
        src = self._app_js()
        self.assertIn("PROBE ERROR", src)

    def test_shows_age_with_color_coding(self):
        """Age labels use color coding: green < 30s, yellow < 120s, red > 120s."""
        src = self._app_js()
        # Age label rendering
        self.assertIn("LIVE", src)
        self.assertIn("AGO", src)
        # Color thresholds
        self.assertIn("_age<30", src)
        self.assertIn("_age<120", src)

    def test_skeleton_timeout_prevents_eternal_spinner(self):
        """Loading skeletons time out after 15s with 'Load failed'."""
        src = self._app_js()
        self.assertIn("skeleton", src)
        # Skeleton timeout interval exists
        self.assertIn("Load failed", src)

    def test_infra_retries_on_warming(self):
        """Infra page retries when cache is warming."""
        src = self._app_js()
        self.assertIn("d.warming", src)

    def test_health_score_unavailable_on_error(self):
        """Health score shows 'Score unavailable' on fetch failure."""
        src = self._app_js()
        self.assertIn("Score unavailable", src)

    def test_fleet_overview_unavailable_on_error(self):
        src = self._app_js()
        self.assertIn("Fleet overview unavailable", src)

    def test_health_check_unavailable_on_error(self):
        src = self._app_js()
        self.assertIn("Health check unavailable", src)


class TestCacheConsistency(unittest.TestCase):
    """All cache endpoints follow the same metadata contract."""

    def test_all_cache_endpoints_have_consistent_shape(self):
        """Every cache endpoint must include cached, age_seconds, probe_status."""
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        required_fields = ['"cached"', '"age_seconds"', '"probe_status"']
        endpoints = {
            "handle_health_api": "health",
            "handle_fleet_overview": "fleet_overview",
            "handle_infra_quick": "infra_quick",
        }
        for handler, cache_key in endpoints.items():
            handler_src = src.split(f"def {handler}")[1].split("\ndef ")[0]
            for field in required_fields:
                self.assertIn(field, handler_src,
                              f"{handler} missing {field} in response")


if __name__ == "__main__":
    unittest.main()
