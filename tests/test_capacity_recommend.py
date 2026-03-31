"""Tests for capacity recommendation engine."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestRecommendMigrations(unittest.TestCase):
    """Test migration recommendations based on projections."""

    def test_no_projections_returns_empty(self):
        from freq.jarvis.capacity import recommend_migrations
        self.assertEqual(recommend_migrations({}), [])

    def test_critical_at_threshold(self):
        from freq.jarvis.capacity import recommend_migrations
        projections = {
            "pve01": {
                "ram": {"current": 85, "trend": 0.5, "trend_direction": "rising", "days_to_80pct": -1},
            },
            "pve02": {
                "ram": {"current": 30, "trend": 0.1, "trend_direction": "stable", "days_to_80pct": -1},
            },
        }
        recs = recommend_migrations(projections)
        self.assertTrue(len(recs) >= 1)
        critical = [r for r in recs if r["urgency"] == "critical"]
        self.assertTrue(len(critical) >= 1)
        self.assertEqual(critical[0]["source"], "pve01")

    def test_warning_approaching(self):
        from freq.jarvis.capacity import recommend_migrations
        projections = {
            "host-a": {
                "disk": {"current": 65, "trend": 1.0, "trend_direction": "rising", "days_to_80pct": 15},
            },
        }
        recs = recommend_migrations(projections)
        warnings = [r for r in recs if r["urgency"] == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("15 days", warnings[0]["reason"])

    def test_migrate_suggests_target(self):
        from freq.jarvis.capacity import recommend_migrations
        projections = {
            "busy-host": {
                "ram": {"current": 90, "trend": 1.0, "trend_direction": "rising", "days_to_80pct": -1},
            },
            "idle-host": {
                "ram": {"current": 25, "trend": -0.1, "trend_direction": "falling", "days_to_80pct": -1},
            },
        }
        recs = recommend_migrations(projections)
        migrate_recs = [r for r in recs if r["type"] == "migrate"]
        self.assertTrue(len(migrate_recs) >= 1)
        self.assertEqual(migrate_recs[0]["target"], "idle-host")

    def test_no_target_becomes_alert(self):
        from freq.jarvis.capacity import recommend_migrations
        projections = {
            "only-host": {
                "ram": {"current": 85, "trend": 0.5, "trend_direction": "rising", "days_to_80pct": -1},
            },
        }
        recs = recommend_migrations(projections)
        self.assertTrue(len(recs) >= 1)
        self.assertEqual(recs[0]["type"], "alert")

    def test_stable_hosts_no_recommendations(self):
        from freq.jarvis.capacity import recommend_migrations
        projections = {
            "stable-1": {
                "ram": {"current": 50, "trend": 0.0, "trend_direction": "stable", "days_to_80pct": -1},
            },
            "stable-2": {
                "disk": {"current": 40, "trend": 0.0, "trend_direction": "stable", "days_to_80pct": -1},
            },
        }
        recs = recommend_migrations(projections)
        # Should have no critical/warning recs
        urgent = [r for r in recs if r["urgency"] in ("critical", "warning")]
        self.assertEqual(len(urgent), 0)

    def test_optimization_for_idle_host(self):
        from freq.jarvis.capacity import recommend_migrations
        from freq.jarvis.cost import HostCost
        projections = {
            "wasteful": {
                "ram": {"current": 10, "trend": 0.0, "trend_direction": "stable", "days_to_80pct": -1},
            },
        }
        costs = [HostCost(label="wasteful", watts=200, cost_month=15.00)]
        recs = recommend_migrations(projections, costs)
        optimize_recs = [r for r in recs if r["type"] == "optimize"]
        self.assertTrue(len(optimize_recs) >= 1)
        self.assertIn("consolidation", optimize_recs[0]["reason"])

    def test_sorted_by_urgency(self):
        from freq.jarvis.capacity import recommend_migrations
        projections = {
            "info-host": {
                "ram": {"current": 60, "trend": 0.3, "trend_direction": "rising", "days_to_80pct": 60},
            },
            "crit-host": {
                "ram": {"current": 95, "trend": 1.0, "trend_direction": "rising", "days_to_80pct": -1},
            },
            "warn-host": {
                "ram": {"current": 70, "trend": 0.8, "trend_direction": "rising", "days_to_80pct": 20},
            },
        }
        recs = recommend_migrations(projections)
        if len(recs) >= 2:
            urgencies = [r["urgency"] for r in recs]
            # Critical should come before warning, warning before info
            crit_idx = next((i for i, u in enumerate(urgencies) if u == "critical"), 999)
            warn_idx = next((i for i, u in enumerate(urgencies) if u == "warning"), 999)
            info_idx = next((i for i, u in enumerate(urgencies) if u == "info"), 999)
            self.assertLessEqual(crit_idx, warn_idx)
            self.assertLessEqual(warn_idx, info_idx)

    def test_with_cost_data_adds_savings(self):
        from freq.jarvis.capacity import recommend_migrations
        from freq.jarvis.cost import HostCost
        projections = {
            "busy": {
                "ram": {"current": 90, "trend": 1.0, "trend_direction": "rising", "days_to_80pct": -1},
            },
            "idle": {
                "ram": {"current": 20, "trend": 0.0, "trend_direction": "stable", "days_to_80pct": -1},
            },
        }
        costs = [
            HostCost(label="busy", watts=300, watts_source="estimate", cost_month=30.00),
            HostCost(label="idle", watts=100, watts_source="estimate", cost_month=10.00),
        ]
        recs = recommend_migrations(projections, costs)
        migrate_recs = [r for r in recs if r["type"] == "migrate"]
        self.assertTrue(len(migrate_recs) >= 1)
        # Should have savings estimate
        self.assertGreater(migrate_recs[0]["savings_month"], 0)


class TestCapacityAPI(unittest.TestCase):
    """Test capacity API route exists."""

    def test_recommend_route_exists(self):
        from freq.modules.serve import FreqHandler
        self.assertIn("/api/capacity/recommend", FreqHandler._ROUTES)


if __name__ == "__main__":
    unittest.main()
