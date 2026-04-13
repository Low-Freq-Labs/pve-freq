"""Collection state semantics contract tests.

Proves the dashboard shell speaks operator semantics, not transport
acronyms, for collection/freshness state. Netdata-style: "LIVE",
"CACHED", "PROBE FAILED", "CACHE WARMING", "STALE". Not "SSE", "POLL",
"PROBE ERROR", "WARMING".

These assertions target only operator-facing STATE LABELS — strings
actually written into DOM textContent or innerHTML. Internal comments
and developer identifiers (e.g. `startSSE` function names, `SSE Live
Updates` block comment) are exempt.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
        return f.read()


class TestNoTransportJargonInStateLabels(unittest.TestCase):
    """Operator-facing state labels must not leak SSE/POLL jargon."""

    def test_no_sse_text_content_assignment(self):
        """textContent or innerHTML must not be assigned the literal 'SSE'
        as an operator-facing label."""
        src = _js()
        self.assertNotIn("textContent='SSE'", src,
                          "textContent must not be set to 'SSE' — use 'LIVE'")
        self.assertNotIn('textContent="SSE"', src,
                          "textContent must not be set to \"SSE\" — use 'LIVE'")

    def test_no_poll_state_label(self):
        """textContent or innerHTML must not be assigned 'POLL' as a
        collection-state label. (POLL as an action button like 'POLL
        ALL' is distinct and still allowed — it's an action verb, not
        a state.)"""
        src = _js()
        self.assertNotIn("textContent='POLL'", src,
                          "textContent must not be set to 'POLL' — use 'CACHED'")
        self.assertNotIn('textContent="POLL"', src,
                          "textContent must not be set to \"POLL\" — use 'CACHED'")

    def test_no_probe_error_label(self):
        """'PROBE ERROR' is internal transport language. Operators say
        'PROBE FAILED' — it describes the observable outcome."""
        src = _js()
        # Find any string literal containing "PROBE ERROR"
        self.assertNotIn("'PROBE ERROR'", src,
                          "Operator label 'PROBE ERROR' must become 'PROBE FAILED'")
        self.assertNotIn('"PROBE ERROR"', src,
                          "Operator label 'PROBE ERROR' must become 'PROBE FAILED'")

    def test_no_bare_warming_label(self):
        """Bare 'WARMING' is ambiguous. Operators say 'CACHE WARMING' so
        the subject is clear."""
        src = _js()
        # Look for a ':"WARMING"' or :'WARMING' — a state label assignment
        self.assertFalse(
            bool(re.search(r"[=:]\s*['\"]WARMING['\"]", src)),
            "Bare 'WARMING' state label must become 'CACHE WARMING'"
        )


class TestOperatorFacingLabels(unittest.TestCase):
    """The replacement labels must actually exist in the source."""

    def test_live_label_present(self):
        """SSE-connected state must render as 'LIVE'."""
        src = _js()
        self.assertTrue(
            "'LIVE'" in src or '"LIVE"' in src,
            "Operator label 'LIVE' must be present for SSE-connected state"
        )

    def test_cached_label_present(self):
        """Polling state must render as 'CACHED'."""
        src = _js()
        self.assertTrue(
            "'CACHED'" in src or '"CACHED"' in src,
            "Operator label 'CACHED' must be present for polling state"
        )

    def test_probe_failed_label_present(self):
        """Error state must render as 'PROBE FAILED'."""
        src = _js()
        self.assertTrue(
            "'PROBE FAILED'" in src or '"PROBE FAILED"' in src,
            "Operator label 'PROBE FAILED' must be present for error state"
        )

    def test_cache_warming_label_present(self):
        """Warming state must render as 'CACHE WARMING'."""
        src = _js()
        self.assertTrue(
            "'CACHE WARMING'" in src or '"CACHE WARMING"' in src,
            "Operator label 'CACHE WARMING' must be present for warming state"
        )


class TestWarmingStateVisibleToOperator(unittest.TestCase):
    """When infra quick cache is warming, the operator must see the
    state — not just have the app silently retry."""

    def test_warming_surfaces_to_core_systems_age(self):
        """_enrichInfraCards d.warming branch must update the
        core-systems-age element so the operator sees 'CACHE WARMING'."""
        src = _js()
        # The _enrichInfraCards function's warming branch must set textContent
        # on the core-systems-age element (or equivalent operator-visible
        # state target) before the setTimeout retry
        fn = src.split("function _enrichInfraCards")[1].split("\nfunction ")[0]
        self.assertIn("warming", fn.lower(),
                       "_enrichInfraCards must handle warming state")
        # The warming branch must render something, not just retry silently
        warming_block = fn.split("d.warming")[1].split("setTimeout")[0]
        self.assertIn("CACHE WARMING", warming_block,
                       "warming branch must render 'CACHE WARMING' to operator")


if __name__ == "__main__":
    unittest.main()
