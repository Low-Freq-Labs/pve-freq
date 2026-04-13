"""Status copy DC01 tone contract tests.

Proves the dashboard shell does not leak comfort/theater language on
load, snapshot, watchdog, or status-card surfaces. DC01 operators
want a factual count, not a pat on the back. "Fleet is balanced",
"No stale snapshots" with a checkmark emoji, and "Quick Start
dashboard loaded" all read like hosted-SaaS onboarding, not an ops
console reporting evidence.
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
        return f.read()


class TestNoFleetIsBalancedComfort(unittest.TestCase):
    """'Fleet is balanced' is a feel-good phrase, not evidence."""

    def test_no_fleet_is_balanced_phrase(self):
        src = _js()
        self.assertNotIn("Fleet is balanced", src,
                          "Must not use 'Fleet is balanced' comfort copy")

    def test_no_no_optimization_recommendations_sentence(self):
        src = _js()
        self.assertNotIn("No optimization recommendations.", src,
                          "Must not use softened 'No optimization recommendations.' sentence")

    def test_migration_empty_state_is_factual(self):
        """The migration empty state must report a factual count plus
        the threshold context, not a pat-on-the-back."""
        src = _js()
        # Must contain the factual alternative
        self.assertIn("migration candidates at current mem thresholds", src,
                       "Migration empty state must be a factual count + threshold")

    def test_capacity_empty_state_is_factual(self):
        """Capacity recommendations empty state must be a factual count."""
        src = _js()
        self.assertIn("recommendations at current thresholds", src,
                       "Capacity empty state must report '0 recommendations at current thresholds'")


class TestNoStaleSnapshotComfort(unittest.TestCase):
    """Snapshot empty state must not use checkmark emoji or pat-on-the-back."""

    def test_no_checkmark_emoji_in_snapshot_empty(self):
        """The ✅ checkmark (\\u2705) must not appear next to snapshot empty state."""
        src = _js()
        self.assertNotIn("\\u2705 No stale snapshots", src,
                          "Must not decorate snapshot empty state with ✅")
        self.assertNotIn("\u2705 No stale snapshots", src,
                          "Must not decorate snapshot empty state with ✅ glyph")

    def test_snapshot_empty_state_is_factual(self):
        """Empty state must report factual count with threshold window."""
        src = _js()
        self.assertIn("0 snapshots older than 30d", src,
                       "Snapshot empty state must be a factual count with threshold")


class TestQuickStartToastNeutral(unittest.TestCase):
    """'Quick Start dashboard loaded' is SaaS onboarding chatter."""

    def test_no_dashboard_loaded_toast(self):
        src = _js()
        self.assertNotIn("Quick Start dashboard loaded", src,
                          "Must not use 'Quick Start dashboard loaded' comfort toast")

    def test_quick_start_toast_reports_count(self):
        """quickStartHome toast must report the actual widget count."""
        src = _js()
        fn = src.split("function quickStartHome")[1].split("function ")[0]
        self.assertIn("widgets loaded", fn,
                       "Quick start toast must report widget count, not generic 'dashboard loaded'")


class TestStatusCopyNotColoredGreen(unittest.TestCase):
    """Green-theater: status copy reporting absence must NOT use the
    green success color. Green means evidence of an UP state, not
    'we couldn't find anything and we're happy about it'."""

    def test_migration_empty_not_green(self):
        src = _js()
        # Find the migration empty branch content
        idx = src.find("migration candidates at current mem thresholds")
        self.assertGreater(idx, 0)
        # Walk back ~160 chars to the opening div style and confirm no --green
        snippet = src[max(0, idx - 200): idx]
        self.assertNotIn("var(--green)", snippet,
                          "Migration empty-state div must not use --green color")

    def test_capacity_empty_not_green(self):
        src = _js()
        idx = src.find("recommendations at current thresholds")
        self.assertGreater(idx, 0)
        snippet = src[max(0, idx - 200): idx]
        self.assertNotIn("var(--green)", snippet,
                          "Capacity empty-state div must not use --green color")

    def test_snapshot_empty_not_green(self):
        src = _js()
        idx = src.find("0 snapshots older than 30d")
        self.assertGreater(idx, 0)
        snippet = src[max(0, idx - 200): idx]
        self.assertNotIn("var(--green)", snippet,
                          "Snapshot empty-state div must not use --green color")


if __name__ == "__main__":
    unittest.main()
