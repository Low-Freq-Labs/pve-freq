"""CI guardrail: detect public-facing drift before it ships.

These tests catch cases where code changes without corresponding
public doc/metadata updates. Designed to run in CI so drift is
caught at PR time, not months later by a confused user.

Covers:
- New endpoints added without API-REFERENCE.md entry
- LOC count drifting beyond badge tolerance
- OpenAPI spec method labels drifting from handler truth
- CSS/JS version hash desync in app.html
"""
import glob
import inspect
import io
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


# ══════════════════════════════════════════════════════════════════════════
# Guard 1: New POST endpoints must be documented in API-REFERENCE.md
# ══════════════════════════════════════════════════════════════════════════

class TestNewPostEndpointsDocumented(unittest.TestCase):
    """POST endpoints must be documented in API-REFERENCE.md."""

    def test_all_post_handlers_in_api_reference(self):
        """Every handler with require_post() must appear in API-REFERENCE.md."""
        from freq.api import build_routes

        ref_path = os.path.join(REPO_ROOT, "docs", "API-REFERENCE.md")
        with open(ref_path) as f:
            ref_content = f.read()

        routes = build_routes()
        undocumented = []
        for path, handler_fn in routes.items():
            if not callable(handler_fn):
                continue
            try:
                src = inspect.getsource(handler_fn)
            except (TypeError, OSError):
                continue
            if "require_post(" not in src and "_require_post(" not in src:
                continue
            if path not in ref_content:
                undocumented.append(path)

        # Ratchet: current baseline is 54 undocumented POST endpoints.
        # This guard prevents the count from growing — new POST endpoints
        # must be documented. Reduce the threshold as docs are backfilled.
        UNDOCUMENTED_BASELINE = 54
        self.assertLessEqual(
            len(undocumented), UNDOCUMENTED_BASELINE,
            f"{len(undocumented)} POST endpoints missing (baseline: {UNDOCUMENTED_BASELINE}).\n"
            f"New POST endpoints must be added to docs/API-REFERENCE.md.\n"
            f"Undocumented:\n" + "\n".join(sorted(undocumented)[:20])
        )


# ══════════════════════════════════════════════════════════════════════════
# Guard 2: OpenAPI spec stays in sync with handler source
# ══════════════════════════════════════════════════════════════════════════

class TestOpenApiStaysInSync(unittest.TestCase):
    """OpenAPI spec must not drift from handler method enforcement."""

    def test_no_new_method_mismatches(self):
        """Zero POST handlers may be labeled GET in the OpenAPI spec."""
        from freq.modules.serve import FreqHandler
        from freq.api import build_routes

        # Generate spec
        h = FreqHandler.__new__(FreqHandler)
        h.path = "/api/openapi.json"
        h.command = "GET"
        h.wfile = io.BytesIO()
        h.rfile = io.BytesIO()
        h.requestline = "GET /api/openapi.json HTTP/1.1"
        h.client_address = ("127.0.0.1", 9999)
        h.request_version = "HTTP/1.1"
        h.headers = {}
        h._headers_buffer = []
        h._status = None
        h._resp_headers = []
        h.send_response = lambda code, msg=None: None
        h.send_header = lambda k, v: None
        h.end_headers = lambda: None
        h._serve_openapi_json()
        spec = json.loads(h.wfile.getvalue().decode())

        spec_methods = {}
        for path, methods in spec["paths"].items():
            spec_methods[path] = "POST" if "post" in methods else "GET"

        routes = build_routes()
        mismatches = []
        for path, handler_fn in routes.items():
            if not callable(handler_fn):
                continue
            try:
                src = inspect.getsource(handler_fn)
            except (TypeError, OSError):
                continue
            if "require_post(" not in src and "_require_post(" not in src:
                continue
            if spec_methods.get(path) != "POST":
                mismatches.append(path)

        self.assertEqual(
            len(mismatches), 0,
            f"POST handlers mislabeled as GET in OpenAPI spec:\n" +
            "\n".join(mismatches)
        )


# ══════════════════════════════════════════════════════════════════════════
# Guard 3: LOC badge cannot drift beyond 10%
# ══════════════════════════════════════════════════════════════════════════

class TestLocBadgeDrift(unittest.TestCase):
    """LOC badge must track actual line count within 10%."""

    def test_badge_within_tolerance(self):
        readme = os.path.join(REPO_ROOT, "README.md")
        with open(readme) as f:
            content = f.read()
        match = re.search(r"lines_of_code-(\d+)K", content)
        self.assertIsNotNone(match)
        badge_kloc = int(match.group(1))

        total = 0
        for path in glob.glob(os.path.join(REPO_ROOT, "freq", "**", "*.py"),
                              recursive=True):
            with open(path) as f:
                total += sum(1 for _ in f)
        actual_kloc = total // 1000

        drift_pct = abs(badge_kloc - actual_kloc) / max(actual_kloc, 1) * 100
        self.assertLess(
            drift_pct, 10,
            f"LOC badge ({badge_kloc}K) drifted {drift_pct:.1f}% from actual "
            f"({actual_kloc}K). Update the badge in README.md."
        )


# ══════════════════════════════════════════════════════════════════════════
# Guard 4: Asset version hashes stay in sync
# ══════════════════════════════════════════════════════════════════════════

class TestAssetVersionSync(unittest.TestCase):
    """JS and CSS version hashes in app.html must match."""

    def test_versions_match(self):
        html_path = os.path.join(REPO_ROOT, "freq", "data", "web", "app.html")
        with open(html_path) as f:
            content = f.read()

        js_match = re.search(r'app\.js\?v=([^"\']+)', content)
        css_match = re.search(r'app\.css\?v=([^"\']+)', content)

        self.assertIsNotNone(js_match, "app.js must have version hash")
        self.assertIsNotNone(css_match, "app.css must have version hash")
        self.assertEqual(js_match.group(1), css_match.group(1),
                         "JS and CSS version hashes must match")


# ══════════════════════════════════════════════════════════════════════════
# Guard 5: Endpoint count claims stay accurate
# ══════════════════════════════════════════════════════════════════════════

class TestEndpointCountSync(unittest.TestCase):
    """Endpoint count claims in docs must track actual count."""

    def _actual_count(self):
        from freq.modules.serve import FreqHandler
        routes = dict(FreqHandler._ROUTES)
        FreqHandler._load_v1_routes()
        if FreqHandler._V1_ROUTES:
            routes.update(FreqHandler._V1_ROUTES)
        return len(routes)

    def test_readme_count_within_tolerance(self):
        """README '300+ Commands' claim must hold."""
        actual = self._actual_count()
        self.assertGreater(actual, 300,
                           f"README claims 300+ but only {actual} endpoints")

    def test_api_reference_count_within_tolerance(self):
        """API-REFERENCE.md count must be within 10% of actual."""
        ref_path = os.path.join(REPO_ROOT, "docs", "API-REFERENCE.md")
        with open(ref_path) as f:
            header = f.read(200)
        match = re.search(r"(\d+)\+?\s*REST API endpoints", header)
        if not match:
            return  # No count claim to check
        doc_count = int(match.group(1))
        actual = self._actual_count()
        drift_pct = abs(doc_count - actual) / max(actual, 1) * 100
        self.assertLess(drift_pct, 10,
                        f"API-REFERENCE says {doc_count} but actual is {actual}. "
                        f"Drift: {drift_pct:.1f}%")


# ══════════════════════════════════════════════════════════════════════════
# Guard 6: pyproject.toml dependencies stay empty
# ══════════════════════════════════════════════════════════════════════════

class TestZeroDepsGuard(unittest.TestCase):
    """Zero-dependencies claim must hold — pyproject must have empty deps."""

    def test_dependencies_empty(self):
        toml_path = os.path.join(REPO_ROOT, "pyproject.toml")
        with open(toml_path) as f:
            content = f.read()
        self.assertIn("dependencies = []", content,
                       "pyproject.toml dependencies must stay empty "
                       "(zero-dependencies claim)")


if __name__ == "__main__":
    unittest.main()
