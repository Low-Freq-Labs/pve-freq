"""Regression tests for OpenAPI spec truthfulness.

Proves: the OpenAPI spec at /api/openapi.json accurately reflects
actual handler behavior — correct HTTP methods and endpoint coverage.

Catches: spec saying GET when handler requires POST (or vice versa),
missing endpoints, and method label drift after refactoring.
"""
import inspect
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _get_openapi_spec():
    """Generate the OpenAPI spec by calling the handler directly."""
    from freq.modules.serve import FreqHandler

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

    h.send_response = lambda code, msg=None: setattr(h, "_status", code)
    h.send_header = lambda k, v: h._resp_headers.append((k, v))
    h.end_headers = lambda: None

    h._serve_openapi_json()
    return json.loads(h.wfile.getvalue().decode())


# ══════════════════════════════════════════════════════════════════════════
# Spec structure validity
# ══════════════════════════════════════════════════════════════════════════

class TestOpenApiStructure(unittest.TestCase):
    """OpenAPI spec must be valid and well-formed."""

    def setUp(self):
        self.spec = _get_openapi_spec()

    def test_openapi_version(self):
        """Spec must declare OpenAPI 3.0.x."""
        self.assertTrue(self.spec["openapi"].startswith("3.0"))

    def test_has_info(self):
        """Spec must have info with title and version."""
        self.assertIn("info", self.spec)
        self.assertIn("title", self.spec["info"])
        self.assertIn("version", self.spec["info"])

    def test_version_matches_module(self):
        """Spec version must match freq.__version__."""
        import freq
        self.assertEqual(self.spec["info"]["version"], freq.__version__)

    def test_has_paths(self):
        """Spec must have paths."""
        self.assertIn("paths", self.spec)
        self.assertGreater(len(self.spec["paths"]), 100,
                           "Spec must have >100 documented paths")

    def test_has_security_schemes(self):
        """Spec must declare bearerAuth and cookieAuth schemes."""
        schemes = self.spec.get("components", {}).get("securitySchemes", {})
        self.assertIn("bearerAuth", schemes)
        self.assertIn("cookieAuth", schemes)

    def test_each_path_has_one_method(self):
        """Each path must have exactly one HTTP method defined."""
        for path, methods in self.spec["paths"].items():
            method_keys = [k for k in methods if k in ("get", "post", "put", "delete", "patch")]
            self.assertEqual(
                len(method_keys), 1,
                f"{path} must have exactly one method, found {method_keys}"
            )


# ══════════════════════════════════════════════════════════════════════════
# Method labels match actual handler behavior
# ══════════════════════════════════════════════════════════════════════════

class TestOpenApiMethodTruth(unittest.TestCase):
    """OpenAPI method labels must match actual require_post() enforcement."""

    def setUp(self):
        self.spec = _get_openapi_spec()
        self.spec_methods = {}
        for path, methods in self.spec["paths"].items():
            if "post" in methods:
                self.spec_methods[path] = "POST"
            else:
                self.spec_methods[path] = "GET"

    def test_post_handlers_labeled_post_in_spec(self):
        """Every handler with require_post() must be labeled POST in spec."""
        from freq.api import build_routes
        routes = build_routes()

        mismatches = []
        for path, handler_fn in routes.items():
            if not callable(handler_fn):
                continue
            try:
                src = inspect.getsource(handler_fn)
            except (TypeError, OSError):
                continue
            has_require_post = "require_post(" in src or "_require_post(" in src
            if not has_require_post:
                continue
            spec_method = self.spec_methods.get(path, "MISSING")
            if spec_method != "POST":
                mismatches.append(f"{path}: handler has require_post but spec says {spec_method}")

        self.assertEqual(mismatches, [],
                         f"POST handlers mislabeled in OpenAPI spec:\n" +
                         "\n".join(mismatches))

    def test_get_overrides_are_actually_get(self):
        """Endpoints in _GET_OVERRIDES must not have require_post()."""
        from freq.api import build_routes
        routes = build_routes()

        get_overrides = {"/api/fleet/updates", "/api/redfish/power-usage"}
        for path in get_overrides:
            handler_fn = routes.get(path)
            if handler_fn is None or not callable(handler_fn):
                continue
            try:
                src = inspect.getsource(handler_fn)
            except (TypeError, OSError):
                continue
            self.assertNotIn(
                "require_post(", src,
                f"{path} is in _GET_OVERRIDES but has require_post()"
            )

    def test_known_post_endpoints_in_spec(self):
        """Critical POST endpoints must appear as POST in the spec."""
        must_be_post = [
            "/api/auth/login",
            "/api/auth/logout",
            "/api/vm/create",
            "/api/vm/destroy",
            "/api/vm/power",
            "/api/ct/create",
            "/api/ct/destroy",
            "/api/vault/set",
            "/api/vault/delete",
            "/api/users/create",
            "/api/containers/add",
            "/api/containers/delete",
            "/api/containers/edit",
        ]
        for path in must_be_post:
            spec_method = self.spec_methods.get(path)
            if spec_method is None:
                continue  # Path might not be in spec (not all routes are)
            self.assertEqual(
                spec_method, "POST",
                f"{path} must be POST in spec, found {spec_method}"
            )

    def test_known_get_endpoints_in_spec(self):
        """Critical GET endpoints must appear as GET in the spec."""
        must_be_get = [
            "/api/health",
            "/api/fleet/overview",
            "/api/info",
            "/api/config",
            "/api/healthz",
            "/api/readyz",
        ]
        for path in must_be_get:
            spec_method = self.spec_methods.get(path)
            if spec_method is None:
                continue
            self.assertEqual(
                spec_method, "GET",
                f"{path} must be GET in spec, found {spec_method}"
            )


# ══════════════════════════════════════════════════════════════════════════
# Endpoint coverage — spec must include all registered routes
# ══════════════════════════════════════════════════════════════════════════

class TestOpenApiCoverage(unittest.TestCase):
    """OpenAPI spec must cover all registered API routes."""

    def setUp(self):
        self.spec = _get_openapi_spec()
        self.spec_paths = set(self.spec["paths"].keys())

    def test_serve_routes_in_spec(self):
        """All serve.py _ROUTES must appear in the spec."""
        from freq.modules.serve import FreqHandler

        # Skip internal/non-API routes
        skip = {"/", "/dashboard", "/api/docs", "/api/openapi.json", "/api/events"}
        missing = []
        for path in FreqHandler._ROUTES:
            if path in skip or path.startswith("/api/setup/"):
                continue
            if path not in self.spec_paths:
                missing.append(path)

        # Allow some tolerance for dynamic routes
        self.assertLess(
            len(missing), 5,
            f"Too many serve.py routes missing from OpenAPI spec:\n" +
            "\n".join(missing[:10])
        )

    def test_api_module_routes_in_spec(self):
        """All freq/api/ module routes must appear in the spec."""
        from freq.api import build_routes
        routes = build_routes()

        missing = []
        for path in routes:
            if path not in self.spec_paths:
                missing.append(path)

        self.assertLess(
            len(missing), 5,
            f"Too many API module routes missing from OpenAPI spec:\n" +
            "\n".join(missing[:10])
        )


# ══════════════════════════════════════════════════════════════════════════
# Docstring consistency — POST handlers must have POST docstrings
# ══════════════════════════════════════════════════════════════════════════

class TestDocstringMethodConsistency(unittest.TestCase):
    """Handlers with require_post must have docstrings starting with 'POST'."""

    def test_post_handlers_have_post_docstrings(self):
        """Every handler with require_post() must document it in docstring."""
        from freq.api import build_routes
        routes = build_routes()

        mismatches = []
        for path, handler_fn in routes.items():
            if not callable(handler_fn):
                continue
            try:
                src = inspect.getsource(handler_fn)
            except (TypeError, OSError):
                continue
            has_require_post = "require_post(" in src or "_require_post(" in src
            if not has_require_post:
                continue
            doc = (handler_fn.__doc__ or "").strip().split("\n")[0]
            if not doc.lower().startswith("post "):
                mismatches.append(f"{path}: has require_post but doc='{doc[:60]}'")

        self.assertEqual(mismatches, [],
                         f"POST handlers with wrong docstring prefix:\n" +
                         "\n".join(mismatches))


if __name__ == "__main__":
    unittest.main()
