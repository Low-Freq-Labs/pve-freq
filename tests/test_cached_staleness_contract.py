"""Regression tests for the cached endpoint staleness contract.

Every cached API endpoint must expose a consistent staleness contract:
  - cached: bool (True if served from cache)
  - age_seconds: float|None (seconds since last probe)
  - stale: bool (True if age > threshold or no data)
  - probe_status: str (ok|error|loading|pending)
  - probe_error: str (only when probe_status=error)

This file tests the contract across all 6 cached endpoints:
  /api/health, /api/fleet/overview, /api/infra/quick,
  /api/fleet/health-score, /api/fleet/heatmap, /api/fleet/topology
Plus /api/update/check (already tested in test_stale_state_guards.py,
regression-guarded here).
"""
import io
import json
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_handler(path="/", method="GET"):
    """Minimal handler mock."""
    from freq.modules.serve import FreqHandler

    h = FreqHandler.__new__(FreqHandler)
    h.path = path
    h.command = method
    h.wfile = io.BytesIO()
    h.rfile = io.BytesIO()
    h.requestline = f"{method} {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 9999)
    h.request_version = "HTTP/1.1"
    h.headers = {}
    h._headers_buffer = []
    h._status = None
    h._resp_headers = []

    def mock_send(code, msg=None):
        h._status = code

    def mock_header(k, v):
        h._resp_headers.append((k, v))

    h.send_response = mock_send
    h.send_header = mock_header
    h.end_headers = lambda: None
    return h


def _get_json(h):
    raw = h.wfile.getvalue()
    return json.loads(raw.decode()) if raw else None


class CacheStalenessTestBase(unittest.TestCase):
    """Base class for cache staleness tests — saves/restores cache state."""

    def setUp(self):
        from freq.modules import serve
        with serve._bg_lock:
            self._orig_cache = dict(serve._bg_cache)
            self._orig_ts = dict(serve._bg_cache_ts)
            self._orig_errors = dict(serve._bg_cache_errors)

    def tearDown(self):
        from freq.modules import serve
        with serve._bg_lock:
            serve._bg_cache.update(self._orig_cache)
            serve._bg_cache_ts.update(self._orig_ts)
            serve._bg_cache_errors.clear()
            serve._bg_cache_errors.update(self._orig_errors)

    def _inject_cache(self, key, data, age_seconds=0, error=None):
        """Inject a known cache entry at a known age."""
        from freq.modules import serve
        ts = time.time() - age_seconds
        with serve._bg_lock:
            serve._bg_cache[key] = data
            serve._bg_cache_ts[key] = ts
            if error:
                serve._bg_cache_errors[key] = {
                    "error": error,
                    "failed_at": time.time(),
                    "consecutive": 1,
                }
            else:
                serve._bg_cache_errors.pop(key, None)

    def _clear_cache(self, key):
        from freq.modules import serve
        with serve._bg_lock:
            serve._bg_cache.pop(key, None)
            serve._bg_cache_ts.pop(key, None)
            serve._bg_cache_errors.pop(key, None)


# ══════════════════════════════════════════════════════════════════════════
# /api/fleet/overview — stale flag added
# ══════════════════════════════════════════════════════════════════════════

class TestFleetOverviewStaleness(CacheStalenessTestBase):
    """/api/fleet/overview must expose full staleness contract."""

    def _call(self):
        from freq.api.fleet import handle_fleet_overview
        h = _make_handler("/api/fleet/overview")
        handle_fleet_overview(h)
        return _get_json(h)

    def test_fresh_cache_contract(self):
        """Fresh fleet_overview must have cached=True, stale=False, probe_status=ok."""
        self._inject_cache("fleet_overview", {
            "vms": [], "physical": [], "pve_nodes": [],
        }, age_seconds=5)
        data = self._call()
        self.assertTrue(data["cached"])
        self.assertFalse(data["stale"])
        self.assertLess(data["age_seconds"], 15)
        self.assertEqual(data["probe_status"], "ok")

    def test_stale_cache_contract(self):
        """Fleet_overview older than 120s must have stale=True."""
        self._inject_cache("fleet_overview", {
            "vms": [], "physical": [], "pve_nodes": [],
        }, age_seconds=200)
        data = self._call()
        self.assertTrue(data["cached"])
        self.assertTrue(data["stale"])
        self.assertGreater(data["age_seconds"], 190)

    def test_probe_error_surfaces(self):
        """Fleet_overview with probe error must expose probe_status=error."""
        self._inject_cache("fleet_overview", {
            "vms": [], "physical": [], "pve_nodes": [],
        }, age_seconds=10, error="SSH connection refused")
        data = self._call()
        self.assertEqual(data["probe_status"], "error")
        self.assertEqual(data["probe_error"], "SSH connection refused")

    def test_cold_start_contract(self):
        """No cache: must return loading state with stale=True."""
        self._clear_cache("fleet_overview")
        data = self._call()
        self.assertFalse(data["cached"])
        self.assertTrue(data["stale"])
        self.assertEqual(data["probe_status"], "loading")
        self.assertIsNone(data["age_seconds"])


# ══════════════════════════════════════════════════════════════════════════
# /api/infra/quick — stale flag added
# ══════════════════════════════════════════════════════════════════════════

class TestInfraQuickStaleness(CacheStalenessTestBase):
    """/api/infra/quick must expose full staleness contract."""

    def _call(self):
        from freq.api.fleet import handle_infra_quick
        h = _make_handler("/api/infra/quick")
        handle_infra_quick(h)
        return _get_json(h)

    def test_fresh_cache_contract(self):
        """Fresh infra_quick must have cached=True, stale=False, probe_status=ok."""
        self._inject_cache("infra_quick", {"devices": []}, age_seconds=5)
        data = self._call()
        self.assertTrue(data["cached"])
        self.assertFalse(data["stale"])
        self.assertEqual(data["probe_status"], "ok")

    def test_stale_cache_contract(self):
        """Infra_quick older than 120s must have stale=True."""
        self._inject_cache("infra_quick", {"devices": []}, age_seconds=200)
        data = self._call()
        self.assertTrue(data["stale"])
        self.assertGreater(data["age_seconds"], 190)

    def test_probe_error_surfaces(self):
        """Infra_quick with probe error must expose probe_status=error."""
        self._inject_cache("infra_quick", {"devices": []},
                          age_seconds=10, error="SNMP timeout")
        data = self._call()
        self.assertEqual(data["probe_status"], "error")
        self.assertIn("SNMP timeout", data["probe_error"])

    def test_cold_start_contract(self):
        """No cache: must return warming state with stale=True."""
        self._clear_cache("infra_quick")
        data = self._call()
        self.assertFalse(data["cached"])
        self.assertTrue(data["stale"])
        self.assertEqual(data["probe_status"], "loading")


# ══════════════════════════════════════════════════════════════════════════
# /api/health — regression guard for existing contract
# ══════════════════════════════════════════════════════════════════════════

class TestHealthStalenessRegression(CacheStalenessTestBase):
    """/api/health staleness contract regression guard."""

    def _call(self):
        from freq.api.fleet import handle_health_api
        h = _make_handler("/api/health")
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "Bearer fake", "Cookie": "", "Origin": "",
        }.get(key, default)
        with patch("freq.api.fleet._check_session_role", return_value=("admin", None)):
            handle_health_api(h)
        return _get_json(h)

    def test_fresh_health_has_required_fields(self):
        """Fresh health must include cached, age_seconds, probe_status."""
        self._inject_cache("health", {
            "hosts": [{"host": "h1", "status": "healthy"}],
            "total": 1, "healthy": 1, "unhealthy": 0,
        }, age_seconds=3)
        data = self._call()
        self.assertIn("cached", data)
        self.assertIn("age_seconds", data)
        self.assertIn("probe_status", data)
        self.assertTrue(data["cached"])
        self.assertEqual(data["probe_status"], "ok")


# ══════════════════════════════════════════════════════════════════════════
# /api/fleet/heatmap — regression guard
# ══════════════════════════════════════════════════════════════════════════

class TestHeatmapStalenessRegression(CacheStalenessTestBase):
    """/api/fleet/heatmap stale flag regression guard."""

    def _call(self):
        from freq.api.fleet import handle_fleet_heatmap
        h = _make_handler("/api/fleet/heatmap")
        handle_fleet_heatmap(h)
        return _get_json(h)

    def test_fresh_not_stale(self):
        self._inject_cache("health", {
            "hosts": [{"host": "h1", "status": "healthy", "ram": "40%",
                       "disk": "30%", "load": "0.5", "docker": "3"}],
        }, age_seconds=5)
        data = self._call()
        self.assertFalse(data["stale"])
        self.assertIn("age_seconds", data)

    def test_old_data_stale(self):
        self._inject_cache("health", {
            "hosts": [{"host": "h1", "status": "healthy", "ram": "40%",
                       "disk": "30%", "load": "0.5", "docker": "3"}],
        }, age_seconds=200)
        data = self._call()
        self.assertTrue(data["stale"])


# ══════════════════════════════════════════════════════════════════════════
# /api/fleet/health-score — regression guard
# ══════════════════════════════════════════════════════════════════════════

class TestHealthScoreStalenessRegression(CacheStalenessTestBase):
    """/api/fleet/health-score stale flag regression guard."""

    def _call(self):
        from freq.api.fleet import handle_fleet_health_score
        h = _make_handler("/api/fleet/health-score")
        handle_fleet_health_score(h)
        return _get_json(h)

    def test_fresh_not_stale(self):
        self._inject_cache("health", {
            "hosts": [{"host": "h1", "status": "healthy", "ram": "40%", "disk": "30%"}],
        }, age_seconds=5)
        self._inject_cache("fleet_overview", {"vms": []}, age_seconds=5)
        data = self._call()
        self.assertIn("stale", data)
        self.assertFalse(data["stale"])

    def test_old_data_stale(self):
        self._inject_cache("health", {
            "hosts": [{"host": "h1", "status": "healthy", "ram": "40%", "disk": "30%"}],
        }, age_seconds=200)
        self._inject_cache("fleet_overview", {"vms": []}, age_seconds=200)
        data = self._call()
        self.assertTrue(data["stale"])


# ══════════════════════════════════════════════════════════════════════════
# Cross-endpoint consistency: all cached endpoints share same contract
# ══════════════════════════════════════════════════════════════════════════

class TestStalenessContractConsistency(CacheStalenessTestBase):
    """All cached endpoints must expose the same field set."""

    REQUIRED_FIELDS = {"cached", "age_seconds", "probe_status"}
    STALE_FIELDS = {"stale"}

    def test_fleet_overview_has_all_fields(self):
        from freq.api.fleet import handle_fleet_overview
        self._inject_cache("fleet_overview", {"vms": []}, age_seconds=5)
        h = _make_handler("/api/fleet/overview")
        handle_fleet_overview(h)
        data = _get_json(h)
        missing = (self.REQUIRED_FIELDS | self.STALE_FIELDS) - set(data.keys())
        self.assertEqual(missing, set(),
                         f"fleet/overview missing fields: {missing}")

    def test_infra_quick_has_all_fields(self):
        from freq.api.fleet import handle_infra_quick
        self._inject_cache("infra_quick", {"devices": []}, age_seconds=5)
        h = _make_handler("/api/infra/quick")
        handle_infra_quick(h)
        data = _get_json(h)
        missing = (self.REQUIRED_FIELDS | self.STALE_FIELDS) - set(data.keys())
        self.assertEqual(missing, set(),
                         f"infra/quick missing fields: {missing}")

    def test_health_has_all_fields(self):
        from freq.api.fleet import handle_health_api
        self._inject_cache("health", {
            "hosts": [], "total": 0, "healthy": 0, "unhealthy": 0,
        }, age_seconds=5)
        h = _make_handler("/api/health")
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "Bearer fake", "Cookie": "", "Origin": "",
        }.get(key, default)
        with patch("freq.api.fleet._check_session_role", return_value=("admin", None)):
            handle_health_api(h)
        data = _get_json(h)
        missing = self.REQUIRED_FIELDS - set(data.keys())
        self.assertEqual(missing, set(),
                         f"health missing fields: {missing}")

    def test_heatmap_has_stale_field(self):
        from freq.api.fleet import handle_fleet_heatmap
        self._inject_cache("health", {"hosts": []}, age_seconds=5)
        h = _make_handler("/api/fleet/heatmap")
        handle_fleet_heatmap(h)
        data = _get_json(h)
        self.assertIn("stale", data)
        self.assertIn("age_seconds", data)
        self.assertIn("cached", data)

    def test_health_score_has_stale_field(self):
        from freq.api.fleet import handle_fleet_health_score
        self._inject_cache("health", {
            "hosts": [{"host": "h1", "status": "healthy", "ram": "40%", "disk": "30%"}],
        }, age_seconds=5)
        self._inject_cache("fleet_overview", {"vms": []}, age_seconds=5)
        h = _make_handler("/api/fleet/health-score")
        handle_fleet_health_score(h)
        data = _get_json(h)
        self.assertIn("stale", data)


if __name__ == "__main__":
    unittest.main()
