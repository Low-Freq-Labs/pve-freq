"""Tests for fleet status using dashboard cache as authoritative source.

Bug: After the K and D fixes, switch showed n/a in fleet status while
/api/health reported it healthy. The n/a was technically truthful
('operator can't directly verify'), but still contradicted the
backend health surface.

Fix: Fleet status now reads the dashboard's cached health data from
data/cache/health.json. When a legacy device hits operator_auth_issue
but the cache says healthy (and is fresh, <120s old), show as UP with
'via dashboard: <metric>' detail. Falls back to n/a when cache is
missing, stale, or the device isn't present in the cache.

Also: _save_disk_cache now writes cache files with chmod 644 so
operator CLI commands (running as a non-service-account user) can
read them. Cache content is host health metrics — no secrets.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestCacheFilesReadableByOperator(unittest.TestCase):
    """_save_disk_cache must chmod cache files to 644."""

    def test_save_cache_chmods_644(self):
        """_save_disk_cache source must call os.chmod(tmp, 0o644)."""
        src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        # Find the _save_disk_cache function
        idx = src.find("def _save_disk_cache")
        self.assertNotEqual(idx, -1)
        block = src[idx:idx + 1500]
        self.assertIn("os.chmod(tmp, 0o644)", block)


class TestDashboardCacheReader(unittest.TestCase):
    """_load_dashboard_health_cache must parse health.json correctly."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-cache-")
        os.makedirs(os.path.join(self.tmpdir, "cache"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cfg(self):
        class FakeCfg:
            pass
        cfg = FakeCfg()
        cfg.data_dir = self.tmpdir
        return cfg

    def _write_cache(self, data, ts=None):
        cache_path = os.path.join(self.tmpdir, "cache", "health.json")
        with open(cache_path, "w") as f:
            json.dump({"data": data, "ts": ts or time.time()}, f)
        return cache_path

    def test_fresh_cache_returns_hosts(self):
        """Fresh health.json returns dict keyed by IP."""
        from freq.modules.fleet import _load_dashboard_health_cache
        self._write_cache({"hosts": [
            {"label": "switch", "ip": "10.25.255.5", "status": "healthy", "load": "0.05"},
            {"label": "bmc-10", "ip": "10.25.255.10", "status": "healthy", "load": "0.02"},
        ]})
        result = _load_dashboard_health_cache(self._make_cfg())
        self.assertEqual(len(result), 2)
        self.assertIn("10.25.255.5", result)
        self.assertEqual(result["10.25.255.5"]["status"], "healthy")

    def test_stale_cache_returns_empty(self):
        """Cache older than 120s is considered stale."""
        from freq.modules.fleet import _load_dashboard_health_cache
        self._write_cache({"hosts": [{"ip": "1.1.1.1", "status": "healthy"}]}, ts=time.time() - 300)
        result = _load_dashboard_health_cache(self._make_cfg())
        self.assertEqual(result, {})

    def test_missing_cache_returns_empty(self):
        """No cache file returns empty dict (not exception)."""
        from freq.modules.fleet import _load_dashboard_health_cache
        result = _load_dashboard_health_cache(self._make_cfg())
        self.assertEqual(result, {})


class TestFleetStatusMergesCache(unittest.TestCase):
    """cmd_status must load dashboard cache and use it for legacy devices."""

    def test_loads_dashboard_cache(self):
        """cmd_status must call _load_dashboard_health_cache."""
        src = (FREQ_ROOT / "freq" / "modules" / "fleet.py").read_text()
        self.assertIn("_load_dashboard_health_cache(cfg)", src)

    def test_uses_cache_for_legacy_hosts(self):
        """When legacy device has auth issue + cache says healthy → show UP."""
        src = (FREQ_ROOT / "freq" / "modules" / "fleet.py").read_text()
        self.assertIn("cached.get(\"status\") == \"healthy\"", src)
        self.assertIn("via dashboard", src)


if __name__ == "__main__":
    unittest.main()
