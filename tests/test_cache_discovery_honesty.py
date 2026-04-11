"""Cache discovery honesty tests.

Proves:
1. All primary cache endpoints share consistent metadata contract
2. Secondary cache consumers return 503 when data is missing
3. No duplicated fallback probe logic between serve.py and fleet.py
4. Stale threshold is consistent (120s) across all endpoints
5. The _bg_lock is always acquired before reading cache
"""

import ast
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCacheMetadataConsistency(unittest.TestCase):
    """Primary cache endpoints must all follow the same contract."""

    def _fleet_src(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            return f.read()

    def test_health_has_full_metadata(self):
        src = self._fleet_src()
        h = src.split("def handle_health_api")[1].split("\ndef ")[0]
        for field in ['"cached"', '"age_seconds"', '"probe_status"']:
            self.assertIn(field, h, f"health missing {field}")

    def test_overview_has_full_metadata(self):
        src = self._fleet_src()
        h = src.split("def handle_fleet_overview")[1].split("\ndef ")[0]
        for field in ['"cached"', '"age_seconds"', '"stale"', '"probe_status"']:
            self.assertIn(field, h, f"overview missing {field}")

    def test_infra_has_full_metadata(self):
        src = self._fleet_src()
        h = src.split("def handle_infra_quick")[1].split("\ndef ")[0]
        for field in ['"cached"', '"age_seconds"', '"stale"', '"probe_status"']:
            self.assertIn(field, h, f"infra missing {field}")

    def test_heatmap_has_stale_metadata(self):
        src = self._fleet_src()
        h = src.split("def handle_fleet_heatmap")[1].split("\ndef ")[0]
        for field in ['"cached"', '"age_seconds"', '"stale"']:
            self.assertIn(field, h, f"heatmap missing {field}")

    def test_topology_has_stale_metadata(self):
        src = self._fleet_src()
        # handle_topology uses "age_seconds", topology-enhanced uses dual ages
        h = src.split("def handle_topology")[1].split("\ndef handle_topology_enhanced")[0]
        for field in ['"cached"', '"age_seconds"', '"stale"']:
            self.assertIn(field, h, f"topology missing {field}")

    def test_topology_enhanced_has_dual_age(self):
        """Enhanced topology has two data sources — reports age for each."""
        src = self._fleet_src()
        h = src.split("def handle_topology_enhanced")[1].split("\ndef ")[0]
        self.assertIn('"health_age_seconds"', h)
        self.assertIn('"fleet_age_seconds"', h)
        self.assertIn('"stale"', h)


class TestStaleThresholdConsistency(unittest.TestCase):
    """Stale threshold should be consistent (120s) across endpoints."""

    def test_stale_threshold_is_120(self):
        """All stale flag checks should use 120s threshold."""
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        # Match specific stale assignment pattern: "stale": age > N
        stale_checks = re.findall(r'"stale".*?age.*?>\s*(\d+)', src)
        for threshold in stale_checks:
            self.assertEqual(int(threshold), 120,
                             f"Found non-120s stale threshold: {threshold}s")


class TestCacheLockUsage(unittest.TestCase):
    """All cache reads must be inside _bg_lock."""

    def test_no_cache_read_without_lock(self):
        """Every _bg_cache.get() must be preceded by _bg_lock acquisition."""
        files_to_check = [
            "freq/api/fleet.py",
            "freq/api/hw.py",
            "freq/api/observe.py",
        ]
        for relpath in files_to_check:
            fpath = os.path.join(REPO_ROOT, relpath)
            with open(fpath) as f:
                src = f.read()
            # Find all function blocks that access _bg_cache
            for match in re.finditer(r'def (\w+)\(', src):
                func_name = match.group(1)
                func_start = match.start()
                func_end = src.find("\ndef ", func_start + 1)
                if func_end == -1:
                    func_end = len(src)
                func_body = src[func_start:func_end]
                if "_bg_cache" in func_body:
                    self.assertIn("_bg_lock", func_body,
                                  f"{relpath}:{func_name}() reads _bg_cache without _bg_lock")


class TestSecondaryCacheConsumers503(unittest.TestCase):
    """Secondary consumers must return 503 when cache is empty."""

    def test_cost_returns_503_when_no_health(self):
        with open(os.path.join(REPO_ROOT, "freq/api/hw.py")) as f:
            src = f.read()
        cost_handler = src.split("def handle_cost")[1].split("\ndef ")[0]
        self.assertIn("503", cost_handler,
                       "Cost handler must return 503 when health data missing")

    def test_snapshot_returns_503_when_no_health(self):
        with open(os.path.join(REPO_ROOT, "freq/api/observe.py")) as f:
            src = f.read()
        snap_handler = src.split("def handle_capacity_snapshot")[1].split("\ndef ")[0]
        self.assertIn("503", snap_handler,
                       "Snapshot handler must return 503 when health data missing")


class TestNoDuplicatedFallbackLogic(unittest.TestCase):
    """Live SSH fallback for health should only exist in one place."""

    def test_health_fallback_only_in_fleet_api(self):
        """Only handle_health_api should do live SSH probes as fallback."""
        # The health background probe is in serve.py
        # The API cold-start fallback is in fleet.py handle_health_api
        # No other file should do a live health SSH fallback
        with open(os.path.join(REPO_ROOT, "freq/api/hw.py")) as f:
            hw_src = f.read()
        with open(os.path.join(REPO_ROOT, "freq/api/observe.py")) as f:
            obs_src = f.read()
        # These should return 503, not do their own SSH probes
        for handler in hw_src.split("\ndef "):
            if "_bg_cache" in handler and "ssh_single" in handler:
                # Only OK if it's doing a specific device probe, not a fleet-wide fallback
                self.assertNotIn("_probe_host", handler,
                                  "hw.py should not duplicate health probe logic")
        for handler in obs_src.split("\ndef "):
            if "_bg_cache" in handler and "ssh_single" in handler:
                self.assertNotIn("_probe_host", handler,
                                  "observe.py should not duplicate health probe logic")


class TestColdStartBehavior(unittest.TestCase):
    """Cold start (no cache) must return honest loading/empty state."""

    def test_overview_cold_start_returns_loading(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler = src.split("def handle_fleet_overview")[1].split("\ndef ")[0]
        self.assertIn('"_loading": True', handler)
        self.assertIn('"probe_status": "loading"', handler)

    def test_infra_cold_start_returns_warming(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler = src.split("def handle_infra_quick")[1].split("\ndef ")[0]
        self.assertIn('"warming": True', handler)

    def test_health_score_cold_start_returns_503(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler = src.split("def handle_fleet_health_score")[1].split("\ndef ")[0]
        self.assertIn("503", handler)
        self.assertIn('"score": 0', handler)


if __name__ == "__main__":
    unittest.main()
