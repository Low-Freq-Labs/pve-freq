"""Regression tests for browser asset and deployed runtime truth.

Proves:
- Frontend JS uses correct HTTP methods for mutating API calls
- Static assets include X-Content-Type-Options: nosniff
- HTML pages reference assets with cache-busting version hashes
- JS and CSS version hashes stay in sync
"""
import io
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


# ══════════════════════════════════════════════════════════════════════════
# Static asset security headers
# ══════════════════════════════════════════════════════════════════════════

class TestStaticAssetHeaders(unittest.TestCase):
    """Static assets must include X-Content-Type-Options: nosniff."""

    def test_serve_static_sends_nosniff(self):
        """_serve_static must include X-Content-Type-Options: nosniff."""
        from freq.modules.serve import FreqHandler

        h = FreqHandler.__new__(FreqHandler)
        h.path = "/static/js/app.js"
        h.command = "GET"
        h.wfile = io.BytesIO()
        h.rfile = io.BytesIO()
        h.requestline = "GET /static/js/app.js HTTP/1.1"
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

        h._serve_static("/static/js/app.js")

        self.assertEqual(h._status, 200)
        headers_dict = {k.lower(): v for k, v in h._resp_headers}
        self.assertIn("x-content-type-options", headers_dict,
                       "Static assets must include X-Content-Type-Options")
        self.assertEqual(headers_dict["x-content-type-options"], "nosniff")

    def test_serve_static_correct_mime_js(self):
        """JS files must be served as application/javascript."""
        from freq.modules.serve import FreqHandler

        h = FreqHandler.__new__(FreqHandler)
        h.path = "/static/js/app.js"
        h.command = "GET"
        h.wfile = io.BytesIO()
        h.rfile = io.BytesIO()
        h.requestline = "GET /static/js/app.js HTTP/1.1"
        h.client_address = ("127.0.0.1", 9999)
        h.request_version = "HTTP/1.1"
        h.headers = {}
        h._headers_buffer = []
        h._status = None
        h._resp_headers = []

        h.send_response = lambda code, msg=None: setattr(h, '_status', code)
        h.send_header = lambda k, v: h._resp_headers.append((k, v))
        h.end_headers = lambda: None

        h._serve_static("/static/js/app.js")

        headers_dict = {k.lower(): v for k, v in h._resp_headers}
        self.assertIn("application/javascript", headers_dict.get("content-type", ""))


# ══════════════════════════════════════════════════════════════════════════
# Asset version hashes: JS and CSS must both have cache-busting versions
# ══════════════════════════════════════════════════════════════════════════

class TestAssetVersionHashes(unittest.TestCase):
    """HTML must reference JS and CSS with matching version hashes."""

    def setUp(self):
        """Load app.html source."""
        html_path = os.path.join(
            os.path.dirname(__file__), "..",
            "freq", "data", "web", "app.html"
        )
        with open(html_path) as f:
            self.html_source = f.read()

    def test_js_has_version_hash(self):
        """app.js script tag must include ?v= version parameter."""
        match = re.search(r'src="/static/js/app\.js(\?v=[^"]+)"', self.html_source)
        self.assertIsNotNone(match,
                             "app.js must have ?v= cache-busting version")

    def test_css_has_version_hash(self):
        """app.css link tag must include ?v= version parameter."""
        match = re.search(r'href="/static/css/app\.css(\?v=[^"]+)"', self.html_source)
        self.assertIsNotNone(match,
                             "app.css must have ?v= cache-busting version")

    def test_js_and_css_versions_match(self):
        """JS and CSS version hashes must be identical."""
        js_match = re.search(r'src="/static/js/app\.js\?v=([^"]+)"', self.html_source)
        css_match = re.search(r'href="/static/css/app\.css\?v=([^"]+)"', self.html_source)
        self.assertIsNotNone(js_match, "JS version not found")
        self.assertIsNotNone(css_match, "CSS version not found")
        self.assertEqual(
            js_match.group(1), css_match.group(1),
            f"JS version ({js_match.group(1)}) must match CSS version ({css_match.group(1)})"
        )


if __name__ == "__main__":
    unittest.main()
