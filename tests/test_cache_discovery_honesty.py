"""Cache discovery honesty tests.
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCacheMetadataConsistency(unittest.TestCase):
    """Primary cache endpoints must all follow the same contract."""

    def _fleet_src(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            return f.read()

    def test_topology_enhanced_has_dual_age(self):
        """Enhanced topology has two data sources — reports age for each."""
        src = self._fleet_src()
        h = src.split("def handle_topology_enhanced")[1].split("\ndef ")[0]
        self.assertIn('"health_age_seconds"', h)
        self.assertIn('"fleet_age_seconds"', h)
        self.assertIn('"stale"', h)

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

if __name__ == "__main__":
    unittest.main()
