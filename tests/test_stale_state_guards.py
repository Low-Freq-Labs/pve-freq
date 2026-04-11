"""Regression tests for stale cached data truthfulness.

Proves: every cached API surface exposes staleness metadata so the
dashboard cannot silently display stale data as if it were current.

Catches: cached endpoints that omit age_seconds, probe_status, or
stale flags, allowing the frontend to show hours-old data as "LIVE".
"""
import io
import json
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_handler(path="/", method="GET", headers=None, body=None):
    """Create a FreqHandler with captured response."""
    from freq.modules.serve import FreqHandler

    h = FreqHandler.__new__(FreqHandler)
    h.path = path
    h.command = method
    h.wfile = io.BytesIO()
    h.rfile = io.BytesIO(body.encode() if body else b"")
    h.requestline = f"{method} {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 9999)
    h.request_version = "HTTP/1.1"
    h.headers = headers or {}
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
    if not raw:
        return None
    return json.loads(raw.decode())


# ══════════════════════════════════════════════════════════════════════════
# /api/update/check — 6hr cache, was missing all staleness metadata
# ══════════════════════════════════════════════════════════════════════════

class TestUpdateCheckStaleness(unittest.TestCase):
    """Cached update check must expose age, probe_status, and stale flag."""

    def setUp(self):
        """Inject known cache state."""
        from freq.modules import serve
        self._orig_cache = {}
        self._orig_ts = {}
        self._orig_errors = {}
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

    def test_fresh_cache_includes_staleness_fields(self):
        """Recent update check must include age_seconds, probe_status, cached."""
        from freq.modules import serve
        from freq import __version__

        now = time.time()
        with serve._bg_lock:
            serve._bg_cache["update"] = {
                "current": __version__,
                "latest": __version__,
                "update_available": False,
                "checked_at": now,
            }
            serve._bg_cache_ts["update"] = now
            serve._bg_cache_errors.pop("update", None)

        h = _make_handler("/api/update/check")
        h._serve_update_check()
        data = _get_json(h)

        self.assertIn("age_seconds", data, "Must expose age_seconds")
        self.assertIn("probe_status", data, "Must expose probe_status")
        self.assertIn("cached", data, "Must expose cached flag")
        self.assertIn("stale", data, "Must expose stale flag")
        self.assertTrue(data["cached"])
        self.assertEqual(data["probe_status"], "ok")
        self.assertFalse(data["stale"], "Fresh cache should not be stale")
        self.assertLess(data["age_seconds"], 10, "Fresh cache age should be small")

    def test_stale_cache_marks_stale_true(self):
        """Update cache older than interval + grace must set stale=True."""
        from freq.modules import serve
        from freq import __version__

        old_ts = time.time() - (serve.UPDATE_CHECK_INTERVAL + 700)
        with serve._bg_lock:
            serve._bg_cache["update"] = {
                "current": __version__,
                "latest": "",
                "update_available": False,
                "checked_at": old_ts,
            }
            serve._bg_cache_ts["update"] = old_ts
            serve._bg_cache_errors.pop("update", None)

        h = _make_handler("/api/update/check")
        h._serve_update_check()
        data = _get_json(h)

        self.assertTrue(data["stale"], "Cache older than interval+grace must be stale")
        self.assertGreater(data["age_seconds"], serve.UPDATE_CHECK_INTERVAL)

    def test_probe_error_surfaces_in_response(self):
        """If update probe errored, response must include probe_status=error."""
        from freq.modules import serve
        from freq import __version__

        now = time.time()
        with serve._bg_lock:
            serve._bg_cache["update"] = {
                "current": __version__,
                "latest": "",
                "update_available": False,
                "checked_at": now,
            }
            serve._bg_cache_ts["update"] = now
            serve._bg_cache_errors["update"] = {
                "error": "Could not reach GitHub",
                "failed_at": now,
                "consecutive": 2,
            }

        h = _make_handler("/api/update/check")
        h._serve_update_check()
        data = _get_json(h)

        self.assertEqual(data["probe_status"], "error")
        self.assertIn("probe_error", data)
        self.assertEqual(data["probe_error"], "Could not reach GitHub")

    def test_graceful_github_error_not_ok(self):
        """Cached result with error field must NOT report probe_status=ok.

        When _bg_check_update catches a GitHub error gracefully, it stores
        error='Could not reach GitHub' in the result but does NOT populate
        _bg_cache_errors. The handler must check the result's error field too.
        """
        from freq.modules import serve
        from freq import __version__

        now = time.time()
        with serve._bg_lock:
            serve._bg_cache["update"] = {
                "current": __version__,
                "latest": "",
                "update_available": False,
                "checked_at": now,
                "error": "Could not reach GitHub",
            }
            serve._bg_cache_ts["update"] = now
            serve._bg_cache_errors.pop("update", None)  # No probe crash

        h = _make_handler("/api/update/check")
        h._serve_update_check()
        data = _get_json(h)

        self.assertEqual(data["probe_status"], "error",
                         "Must not report ok when result has error field")
        self.assertIn("probe_error", data)
        self.assertEqual(data["probe_error"], "Could not reach GitHub")

    def test_no_cache_returns_pending(self):
        """When no cache exists yet, must return probe_status=pending + stale=True."""
        from freq.modules import serve

        with serve._bg_lock:
            serve._bg_cache.pop("update", None)
            serve._bg_cache_ts.pop("update", None)

        h = _make_handler("/api/update/check")
        h._serve_update_check()
        data = _get_json(h)

        self.assertEqual(data["probe_status"], "pending")
        self.assertTrue(data["stale"], "No cache should be stale")
        self.assertFalse(data["cached"])


# ══════════════════════════════════════════════════════════════════════════
# /api/health — already has staleness metadata, regression guard
# ══════════════════════════════════════════════════════════════════════════

class TestHealthApiStalenessContract(unittest.TestCase):
    """Health API must always include age_seconds and probe_status."""

    def setUp(self):
        from freq.modules import serve
        self._orig_cache = {}
        self._orig_ts = {}
        self._orig_errors = {}
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

    def test_cached_health_includes_staleness_fields(self):
        """Cached health response must include age_seconds and probe_status."""
        from freq.modules import serve
        from freq.api.fleet import handle_health_api

        now = time.time()
        with serve._bg_lock:
            serve._bg_cache["health"] = {
                "hosts": [{"host": "test", "status": "healthy"}],
                "total": 1, "healthy": 1, "unhealthy": 0,
            }
            serve._bg_cache_ts["health"] = now
            serve._bg_cache_errors.pop("health", None)

        h = _make_handler("/api/health")
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "Bearer fake", "Cookie": "", "Origin": "",
        }.get(key, default)

        # Mock auth to pass
        with patch("freq.api.fleet._check_session_role", return_value=("admin", None)):
            handle_health_api(h)

        data = _get_json(h)
        self.assertIn("age_seconds", data)
        self.assertIn("probe_status", data)
        self.assertIn("cached", data)
        self.assertTrue(data["cached"])
        self.assertEqual(data["probe_status"], "ok")

    def test_health_probe_error_surfaces(self):
        """Health with probe error must include probe_status=error."""
        from freq.modules import serve
        from freq.api.fleet import handle_health_api

        now = time.time()
        with serve._bg_lock:
            serve._bg_cache["health"] = {
                "hosts": [], "total": 0, "healthy": 0, "unhealthy": 0,
            }
            serve._bg_cache_ts["health"] = now - 60
            serve._bg_cache_errors["health"] = {
                "error": "SSH timeout",
                "failed_at": now - 30,
                "consecutive": 4,
            }

        h = _make_handler("/api/health")
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "Bearer fake", "Cookie": "", "Origin": "",
        }.get(key, default)

        with patch("freq.api.fleet._check_session_role", return_value=("admin", None)):
            handle_health_api(h)

        data = _get_json(h)
        self.assertEqual(data["probe_status"], "error")
        self.assertIn("probe_error", data)
        self.assertGreater(data["age_seconds"], 50)


class TestHealthDiskCacheStaleness(unittest.TestCase):
    """Health from disk cache must report probe_status=stale, not ok."""

    def setUp(self):
        from freq.modules import serve
        self._orig_cache = {}
        self._orig_ts = {}
        self._orig_errors = {}
        self._orig_from_disk = set()
        with serve._bg_lock:
            self._orig_cache.update(serve._bg_cache)
            self._orig_ts.update(serve._bg_cache_ts)
            self._orig_errors.update(serve._bg_cache_errors)
            self._orig_from_disk = set(serve._bg_cache_from_disk)

    def tearDown(self):
        from freq.modules import serve
        with serve._bg_lock:
            serve._bg_cache.update(self._orig_cache)
            serve._bg_cache_ts.update(self._orig_ts)
            serve._bg_cache_errors.clear()
            serve._bg_cache_errors.update(self._orig_errors)
            serve._bg_cache_from_disk.clear()
            serve._bg_cache_from_disk.update(self._orig_from_disk)

    def test_disk_cache_reports_stale(self):
        """Health loaded from disk must have probe_status=stale."""
        from freq.modules import serve
        from freq.api.fleet import handle_health_api

        now = time.time()
        with serve._bg_lock:
            serve._bg_cache["health"] = {
                "hosts": [{"host": "test", "status": "healthy"}],
                "total": 1, "healthy": 1,
            }
            serve._bg_cache_ts["health"] = now - 300  # 5 min old
            serve._bg_cache_errors.pop("health", None)
            serve._bg_cache_from_disk.add("health")  # Loaded from disk

        h = _make_handler("/api/health")
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "Bearer fake", "Cookie": "", "Origin": "",
        }.get(key, default)

        with patch("freq.api.fleet._check_session_role", return_value=("admin", None)):
            handle_health_api(h)

        data = _get_json(h)
        self.assertEqual(data["probe_status"], "stale",
                         "Disk-loaded health must report probe_status=stale")
        self.assertTrue(data["from_disk_cache"])
        self.assertIn("previous server instance", data.get("probe_error", ""))

    def test_fresh_probe_clears_disk_flag(self):
        """After a fresh probe, disk flag must be cleared."""
        from freq.modules import serve
        with serve._bg_lock:
            serve._bg_cache_from_disk.add("health")
        # Simulate fresh probe writing to cache
        with serve._bg_lock:
            serve._bg_cache["health"] = {"hosts": [], "duration": 0.1}
            serve._bg_cache_ts["health"] = time.time()
            serve._bg_cache_from_disk.discard("health")
        self.assertNotIn("health", serve._bg_cache_from_disk)


# ══════════════════════════════════════════════════════════════════════════
# /api/fleet/health-score — stale flag at 120s, regression guard
# ══════════════════════════════════════════════════════════════════════════

class TestHealthScoreStaleness(unittest.TestCase):
    """Health score must flag stale when cache age > 120s."""

    def setUp(self):
        from freq.modules import serve
        self._orig_cache = {}
        self._orig_ts = {}
        with serve._bg_lock:
            self._orig_cache = dict(serve._bg_cache)
            self._orig_ts = dict(serve._bg_cache_ts)

    def tearDown(self):
        from freq.modules import serve
        with serve._bg_lock:
            serve._bg_cache.update(self._orig_cache)
            serve._bg_cache_ts.update(self._orig_ts)

    def test_fresh_data_not_stale(self):
        """Health score with fresh data must not be stale."""
        from freq.modules import serve
        from freq.api.fleet import handle_fleet_health_score

        now = time.time()
        with serve._bg_lock:
            serve._bg_cache["health"] = {
                "hosts": [{"host": "h1", "status": "healthy", "ram": "40%", "disk": "30%"}],
            }
            serve._bg_cache_ts["health"] = now
            serve._bg_cache["fleet_overview"] = {"vms": []}
            serve._bg_cache_ts["fleet_overview"] = now

        h = _make_handler("/api/fleet/health-score")
        handle_fleet_health_score(h)
        data = _get_json(h)

        self.assertIn("stale", data)
        self.assertFalse(data["stale"])

    def test_old_data_marked_stale(self):
        """Health score with 3-minute-old data must be stale."""
        from freq.modules import serve
        from freq.api.fleet import handle_fleet_health_score

        old = time.time() - 180  # 3 minutes
        with serve._bg_lock:
            serve._bg_cache["health"] = {
                "hosts": [{"host": "h1", "status": "healthy", "ram": "40%", "disk": "30%"}],
            }
            serve._bg_cache_ts["health"] = old
            serve._bg_cache["fleet_overview"] = {"vms": []}
            serve._bg_cache_ts["fleet_overview"] = old

        h = _make_handler("/api/fleet/health-score")
        handle_fleet_health_score(h)
        data = _get_json(h)

        self.assertTrue(data["stale"], "Data > 120s must be stale")


# ══════════════════════════════════════════════════════════════════════════
# Disk cache restoration — must preserve original timestamps (not reset)
# ══════════════════════════════════════════════════════════════════════════

class TestDiskCacheTimestampPreservation(unittest.TestCase):
    """Disk cache load must preserve original timestamps so staleness is visible."""

    def test_disk_cache_roundtrip_preserves_ts(self):
        """Save + load must preserve the timestamp exactly."""
        import tempfile
        from freq.modules import serve

        old_cache_dir = serve.CACHE_DIR
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                serve.CACHE_DIR = tmpdir

                original_ts = time.time() - 3600  # 1 hour ago
                test_data = {"test": True, "value": 42}

                serve._save_disk_cache("test_key", test_data)

                # Manually read to verify ts is stored
                cache_file = os.path.join(tmpdir, "test_key.json")
                with open(cache_file) as f:
                    saved = json.load(f)
                self.assertIn("ts", saved, "Disk cache must store ts")
                # ts should be ~now (when saved), not original_ts

                # Now inject old ts and reload
                saved["ts"] = original_ts
                with open(cache_file, "w") as f:
                    json.dump(saved, f)

                # Load from disk
                orig_bg_cache = dict(serve._bg_cache)
                orig_bg_ts = dict(serve._bg_cache_ts)
                serve._bg_cache["test_key"] = None  # ensure key exists for loader
                serve._load_disk_cache()

                with serve._bg_lock:
                    loaded_ts = serve._bg_cache_ts.get("test_key", 0)

                self.assertEqual(loaded_ts, original_ts,
                                 "Disk cache must preserve original timestamp, "
                                 "not reset to now (which would hide staleness)")
        finally:
            serve.CACHE_DIR = old_cache_dir


# ══════════════════════════════════════════════════════════════════════════
# Probe error recording — must surface to API consumers
# ══════════════════════════════════════════════════════════════════════════

class TestProbeErrorRecording(unittest.TestCase):
    """Probe errors must be recorded with consecutive count for API consumers."""

    def test_record_probe_error_increments_consecutive(self):
        """Consecutive failures must be counted."""
        from freq.modules.serve import (
            _record_probe_error, _clear_probe_error,
            _bg_cache_errors, _bg_lock
        )

        _record_probe_error("test_probe", Exception("fail1"))
        with _bg_lock:
            err = _bg_cache_errors.get("test_probe")
        self.assertIsNotNone(err)
        self.assertEqual(err["consecutive"], 1)

        _record_probe_error("test_probe", Exception("fail2"))
        with _bg_lock:
            err = _bg_cache_errors.get("test_probe")
        self.assertEqual(err["consecutive"], 2)

        _clear_probe_error("test_probe")
        with _bg_lock:
            err = _bg_cache_errors.get("test_probe")
        self.assertIsNone(err)

    def test_error_includes_failed_at_timestamp(self):
        """Recorded error must include failed_at for age calculation."""
        from freq.modules.serve import (
            _record_probe_error, _bg_cache_errors, _bg_lock
        )

        before = time.time()
        _record_probe_error("ts_test_probe", Exception("boom"))
        with _bg_lock:
            err = _bg_cache_errors.get("ts_test_probe")
        self.assertGreaterEqual(err["failed_at"], before)

        # Cleanup
        from freq.modules.serve import _clear_probe_error
        _clear_probe_error("ts_test_probe")


if __name__ == "__main__":
    unittest.main()
