"""Regression tests for docs/API-REFERENCE.md truthfulness.

Proves: method labels in the API reference match actual handler behavior.
Catches: doc saying GET when handler requires POST (or vice versa).
"""
import inspect
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _parse_api_reference():
    """Parse method+endpoint pairs from API-REFERENCE.md tables."""
    ref_path = os.path.join(REPO_ROOT, "docs", "API-REFERENCE.md")
    with open(ref_path) as f:
        content = f.read()

    entries = {}
    for match in re.finditer(
        r"\|\s*(GET|POST|PUT|DELETE)\s*\|\s*`([^`]+)`\s*\|", content
    ):
        method = match.group(1)
        endpoint = match.group(2)
        entries[endpoint] = method
    return entries


def _get_handler_actual_method(handler_fn):
    """Determine if a handler actually requires POST by inspecting source."""
    try:
        src = inspect.getsource(handler_fn)
    except (TypeError, OSError):
        return None
    if "require_post(" in src or "_require_post(" in src:
        return "POST"
    if 'handler.command != "POST"' in src or "handler.command != 'POST'" in src:
        return "POST"
    doc = (handler_fn.__doc__ or "").strip().split("\n")[0].lower()
    if doc.startswith("post "):
        return "POST"
    if doc.startswith("get "):
        return "GET"
    return None  # Can't determine


class TestApiReferenceMethodTruth(unittest.TestCase):
    """API-REFERENCE.md method labels must match actual handler behavior."""

    def setUp(self):
        self.doc_entries = _parse_api_reference()
        from freq.api import build_routes
        self.api_routes = build_routes()
        from freq.modules.serve import FreqHandler
        self.serve_routes = dict(FreqHandler._ROUTES)

    def test_doc_post_endpoints_are_actually_post(self):
        """Endpoints labeled POST in docs must actually require POST."""
        mismatches = []
        for endpoint, doc_method in self.doc_entries.items():
            if doc_method != "POST":
                continue
            handler_fn = self.api_routes.get(endpoint)
            if handler_fn and callable(handler_fn):
                actual = _get_handler_actual_method(handler_fn)
                if actual == "GET":
                    mismatches.append(f"{endpoint}: doc=POST actual=GET")
        self.assertEqual(mismatches, [],
                         "Docs say POST but handler is actually GET:\n" +
                         "\n".join(mismatches))

    def test_doc_get_endpoints_are_not_post(self):
        """Endpoints labeled GET in docs must not require POST."""
        mismatches = []
        for endpoint, doc_method in self.doc_entries.items():
            if doc_method != "GET":
                continue
            handler_fn = self.api_routes.get(endpoint)
            if handler_fn and callable(handler_fn):
                actual = _get_handler_actual_method(handler_fn)
                if actual == "POST":
                    mismatches.append(f"{endpoint}: doc=GET actual=POST")
        self.assertEqual(mismatches, [],
                         "Docs say GET but handler requires POST:\n" +
                         "\n".join(mismatches))

    def test_critical_post_endpoints_documented_as_post(self):
        """Critical destructive endpoints must be documented as POST."""
        critical_post = [
            "/api/auth/login",
            "/api/auth/logout",
            "/api/vm/create",
            "/api/vm/destroy",
            "/api/vm/power",
            "/api/vault/set",
            "/api/vault/delete",
            "/api/containers/add",
            "/api/containers/delete",
            "/api/containers/edit",
            "/api/gwipe",
        ]
        for endpoint in critical_post:
            doc_method = self.doc_entries.get(endpoint)
            if doc_method is None:
                continue
            self.assertEqual(
                doc_method, "POST",
                f"{endpoint} must be documented as POST, found {doc_method}"
            )

    def test_critical_get_endpoints_documented_as_get(self):
        """Critical read-only endpoints must be documented as GET."""
        critical_get = [
            "/api/health",
            "/api/fleet/overview",
            "/api/info",
            "/api/config",
            "/api/update/check",
            "/api/setup/status",
        ]
        for endpoint in critical_get:
            doc_method = self.doc_entries.get(endpoint)
            if doc_method is None:
                continue
            self.assertEqual(
                doc_method, "GET",
                f"{endpoint} must be documented as GET, found {doc_method}"
            )

    def test_endpoint_count_header_accuracy(self):
        """Endpoint count in header must be within 10% of actual."""
        ref_path = os.path.join(REPO_ROOT, "docs", "API-REFERENCE.md")
        with open(ref_path) as f:
            header = f.readline() + f.readline() + f.readline()
        match = re.search(r"(\d+)\+?\s*REST API endpoints", header)
        self.assertIsNotNone(match, "Endpoint count not found in header")
        doc_count = int(match.group(1))

        from freq.modules.serve import FreqHandler
        routes = dict(FreqHandler._ROUTES)
        FreqHandler._load_v1_routes()
        if FreqHandler._V1_ROUTES:
            routes.update(FreqHandler._V1_ROUTES)
        actual_count = len(routes)

        lower = actual_count * 0.9
        upper = actual_count * 1.1
        self.assertTrue(
            lower <= doc_count <= upper,
            f"Doc says {doc_count} endpoints but actual is {actual_count}. "
            f"Must be within 10%."
        )


if __name__ == "__main__":
    unittest.main()
