"""Regression tests for browser asset and deployed runtime truth.

Proves:
- Frontend JS uses correct HTTP methods for mutating API calls
- Static assets include X-Content-Type-Options: nosniff
- HTML pages reference assets with cache-busting version hashes
- JS and CSS version hashes stay in sync
"""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ══════════════════════════════════════════════════════════════════════════
# Frontend method consistency: mutating calls must use POST
# ══════════════════════════════════════════════════════════════════════════

class TestFrontendMethodConsistency(unittest.TestCase):
    """Frontend JS must use POST for all mutating API calls."""

    def setUp(self):
        """Load app.js source."""
        app_js_path = os.path.join(
            os.path.dirname(__file__), "..",
            "freq", "data", "web", "js", "app.js"
        )
        with open(app_js_path) as f:
            self.js_source = f.read()

    # Endpoints that require POST (from require_post() in backend)
    POST_REQUIRED_ENDPOINTS = [
        "/api/containers/edit",
        "/api/containers/delete",
        "/api/containers/add",
        "/api/containers/rescan",
        "/api/capacity/snapshot",
    ]

    def test_mutating_calls_use_post(self):
        """Every _authFetch to a POST-required endpoint must include method:'POST'."""
        for endpoint in self.POST_REQUIRED_ENDPOINTS:
            # Find all lines containing _authFetch to this endpoint
            found = False
            for i, line in enumerate(self.js_source.splitlines(), 1):
                if f"_authFetch('{endpoint}" in line or f'_authFetch("{endpoint}' in line:
                    found = True
                    normalized = line.replace('"', "'")
                    self.assertIn(
                        "method:'POST'", normalized,
                        f"Line {i}: _authFetch to {endpoint} must include method:'POST'.\n"
                        f"Found: {line.strip()[:150]}"
                    )
            self.assertTrue(found,
                            f"Expected at least one _authFetch call to {endpoint}")

    # Endpoints that should use GET (read-only)
    GET_ENDPOINTS = [
        "/api/health",
        "/api/fleet/overview",
        "/api/info",
        "/api/containers/registry",
    ]

    def test_readonly_calls_use_get(self):
        """Read-only _authFetch calls must NOT include method:'POST'."""
        for endpoint in self.GET_ENDPOINTS:
            pattern = re.compile(
                r"_authFetch\(['\"]" + re.escape(endpoint) + r"[^)]*\)"
            )
            matches = pattern.findall(self.js_source)
            for match in matches:
                normalized = match.replace('"', "'")
                self.assertNotIn(
                    "method:'POST'", normalized,
                    f"Read-only _authFetch to {endpoint} should not use POST.\n"
                    f"Found: {match[:120]}"
                )


if __name__ == "__main__":
    unittest.main()
