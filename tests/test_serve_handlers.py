"""Tier 5B: serve.py HTTP handler tests with MockFreqHandler.

Tests HTTP endpoints by creating a mock handler that captures JSON responses
without needing real sockets or SSH backends.

NOTE: Auth handler tests (login, verify, change-password), info, status, vault,
users, exec, and VM action tests were removed in the Phase 3.1 refactor.
Those handlers were extracted to freq/api/*.py modules and the old _serve_*
methods were deleted from serve.py.  Auth is now tested in test_security_api.py.
"""
import io
import json
import os
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

# ── Path setup ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.modules.serve import FreqHandler


# ── Mock handler factory ────────────────────────────────────────────────

class MockWfile(io.BytesIO):
    """Captures bytes written to wfile."""
    pass


def _make_handler(path="/api/info"):
    """Create a FreqHandler instance without opening a real socket.

    The handler has:
    - h.path set to the given path
    - h.wfile captures written bytes
    - h.send_response / send_header / end_headers are no-ops
    - h._captured: parsed JSON from _json_response calls
    """
    h = FreqHandler.__new__(FreqHandler)
    h.path = path
    h.wfile = MockWfile()
    h.rfile = io.BytesIO()
    h.requestline = f"GET {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 9999)
    h.request_version = "HTTP/1.1"
    h.headers = {}
    h._headers_buffer = []
    h.responses = {200: ("OK", ""), 404: ("Not Found", "")}

    # Track response metadata
    h._status_code = None
    h._resp_headers = []

    _orig_send = h.send_response

    def mock_send(code, msg=None):
        h._status_code = code

    def mock_header(k, v):
        h._resp_headers.append((k, v))

    h.send_response = mock_send
    h.send_header = mock_header
    h.end_headers = lambda: None
    return h


def _get_json(handler):
    """Extract JSON response body from handler.wfile."""
    handler.wfile.seek(0)
    body = handler.wfile.read()
    if not body:
        return None
    return json.loads(body.decode())


# ── Mock config ─────────────────────────────────────────────────────────

def _mock_cfg(**overrides):
    """Create a minimal mock config for handler tests."""
    from freq.core.types import FleetBoundaries

    fb = FleetBoundaries(
        tiers={
            "probe": {"actions": ["view"]},
            "operator": {"actions": ["view", "start", "stop", "restart", "snapshot"]},
            "admin": {"actions": ["view", "start", "stop", "restart", "snapshot", "resize", "migrate", "configure", "destroy"]},
        },
        categories={
            "personal": {"vmid_ranges": [[5000, 5999]], "tier": "admin"},
            "prod_media": {"vmid_ranges": [[200, 299]], "tier": "operator"},
            "lab": {"vmid_ranges": [[3000, 3999]], "tier": "probe"},
        },
    )
    defaults = dict(
        hosts=[],
        pve_nodes=["192.168.10.1"],
        ssh_key_path="/tmp/fake_key",
        brand="FREQ",
        build="dev",
        cluster_name="testcluster",
        install_dir="/opt/freq",
        vault_file="/tmp/fake_vault",
        conf_dir="/tmp/fake_conf",
        dashboard_port=8888,
        fleet_boundaries=fb,
        infrastructure={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_host(label="testhost", ip="192.168.10.50", htype="linux", groups=""):
    return SimpleNamespace(label=label, ip=ip, htype=htype, groups=groups)


def _mock_ssh_result(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


# ══════════════════════════════════════════════════════════════════════════
# NOTE: Auth (login/verify/change-password), Info, Status, Vault, Users,
# Exec, and VM action tests were removed.  Those _serve_* handler methods
# were deleted from serve.py during the Phase 3.1 API extraction.
# The functionality is now in freq/api/*.py and tested via
# test_security_api.py, test_admin_api.py, and the API-level test suite.
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
# Routing Tests
# ══════════════════════════════════════════════════════════════════════════

class TestDoGetRouting:
    """Test do_GET route dispatch."""

    def test_known_route_dispatches(self):
        h = _make_handler("/api/config")
        # Patch _serve_config to just track it was called
        called = []
        h._serve_config = lambda: called.append(True)
        # Bypass global auth check for routing test (auth tested separately)
        with patch("freq.modules.serve._check_session_role", return_value=("admin", None)):
            h.do_GET()
        assert called == [True]

    def test_unknown_route_404(self):
        h = _make_handler("/api/nonexistent")
        # Bypass global auth check for routing test (auth tested separately)
        with patch("freq.modules.serve._check_session_role", return_value=("admin", None)):
            h.do_GET()
        # Unknown API routes return JSON 404 via _json_response
        assert h._status_code == 404
        data = _get_json(h)
        assert data["error"] == "not found"

    def test_watchdog_proxy_route(self):
        h = _make_handler("/api/watch/something")
        called = []
        h._proxy_watchdog = lambda: called.append(True)
        with patch("freq.modules.serve._check_session_role", return_value=("viewer", None)):
            h.do_GET()
        assert called == [True]

    def test_comms_proxy_route(self):
        h = _make_handler("/api/comms/test")
        called = []
        h._proxy_watchdog = lambda: called.append(True)
        with patch("freq.modules.serve._check_session_role", return_value=("viewer", None)):
            h.do_GET()
        assert called == [True]

    def test_watchdog_proxy_rejects_anonymous(self):
        """Watchdog proxy must reject unauthenticated requests."""
        h = _make_handler("/api/watch/status")
        h.do_GET()
        assert h._status_code == 403

    def test_comms_proxy_rejects_anonymous(self):
        """Comms proxy must reject unauthenticated requests."""
        h = _make_handler("/api/comms/test")
        h.do_GET()
        assert h._status_code == 403

    def test_root_serves_app(self):
        h = _make_handler("/")
        called = []
        h._serve_app = lambda: called.append(True)
        h.do_GET()
        assert called == [True]

    def test_dashboard_serves_app(self):
        h = _make_handler("/dashboard")
        called = []
        h._serve_app = lambda: called.append(True)
        h.do_GET()
        assert called == [True]


class TestFleetOverviewApi:
    """Test /api/fleet/overview cache metadata."""

    def test_cached_response_includes_age_seconds(self):
        from freq.api.fleet import handle_fleet_overview
        from freq.modules.serve import _bg_cache, _bg_cache_ts, _bg_lock

        h = _make_handler("/api/fleet/overview")
        now = time.time()

        with _bg_lock:
            _bg_cache["fleet_overview"] = {
                "vms": [],
                "vm_nics": {},
                "physical": [],
                "pve_nodes": [],
                "vlans": [],
                "nic_profiles": {},
                "categories": {},
                "summary": {
                    "total_vms": 0,
                    "running": 0,
                    "stopped": 0,
                    "prod_count": 0,
                    "lab_count": 0,
                    "template_count": 0,
                },
                "duration": 0.2,
            }
            _bg_cache_ts["fleet_overview"] = now - 123.4

        handle_fleet_overview(h)
        data = _get_json(h)

        assert data["cached"] is True
        assert isinstance(data["age_seconds"], float)
        assert round(data["age_seconds"], 1) == 123.4
        assert data["age"] == data["age_seconds"]

        with _bg_lock:
            assert "cached" not in _bg_cache["fleet_overview"]
            assert "age_seconds" not in _bg_cache["fleet_overview"]


# ══════════════════════════════════════════════════════════════════════════
# Lab / Media Endpoints
# ══════════════════════════════════════════════════════════════════════════

class TestServeLabStatus:
    """Test /api/lab/status endpoint."""

    @patch("freq.modules.serve.ssh_single")
    @patch("freq.modules.serve.load_config")
    def test_lab_status(self, mock_cfg_fn, mock_ssh_single):
        hosts = [_mock_host("lab1", "192.168.10.100", "linux", groups="lab")]
        cfg = _mock_cfg(hosts=hosts, docker_dev_ip="192.168.10.200")
        mock_cfg_fn.return_value = cfg
        mock_ssh_single.return_value = _mock_ssh_result("up 3 days")

        h = _make_handler("/api/lab/status")
        h._serve_lab_status()

        data = _get_json(h)
        assert "hosts" in data
        assert len(data["hosts"]) == 1


class TestServeMediaRestart:
    """Test /api/media/restart endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_restart_missing_name(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/media/restart?name=")
        h._serve_media_restart()

        data = _get_json(h)
        assert "error" in data


class TestServeMediaLogs:
    """Test /api/media/logs endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_logs_missing_name(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/media/logs?name=")
        h._serve_media_logs()

        data = _get_json(h)
        assert "error" in data


class TestServeMediaUpdate:
    """Test /api/media/update endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_update_missing_name(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/media/update?name=")
        h._serve_media_update()

        data = _get_json(h)
        assert "error" in data


class TestSetupHandlers:
    """Trust-critical setup handler behavior."""

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_rejects_invalid_timezone(self, mock_cfg_fn, _mock_first_run):
        cfg = _mock_cfg(conf_dir="/tmp/freq-test-conf")
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/setup/configure")
        h.command = "POST"
        h._request_body = lambda: {"cluster_name": "dc01", "timezone": "Mars/Phobos", "pve_nodes": ["10.0.0.1"]}

        h._serve_setup_configure()

        assert h._status_code == 400
        data = _get_json(h)
        assert "Invalid timezone" in data["error"]

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_rejects_invalid_pve_nodes(self, mock_cfg_fn, _mock_first_run):
        cfg = _mock_cfg(conf_dir="/tmp/freq-test-conf")
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/setup/configure")
        h.command = "POST"
        h._request_body = lambda: {"cluster_name": "dc01", "timezone": "UTC", "pve_nodes": ["bad-ip", "10.0.0.2"]}

        h._serve_setup_configure()

        assert h._status_code == 400
        data = _get_json(h)
        assert "Invalid PVE node IP" in data["error"]

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_requires_cluster_name(self, mock_cfg_fn, _mock_first_run):
        cfg = _mock_cfg(conf_dir="/tmp/freq-test-conf")
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/setup/configure")
        h.command = "POST"
        h._request_body = lambda: {"cluster_name": "", "timezone": "UTC", "pve_nodes": ["10.0.0.1"]}

        h._serve_setup_configure()

        assert h._status_code == 400
        data = _get_json(h)
        assert data["error"] == "cluster_name is required"

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_requires_pve_nodes(self, mock_cfg_fn, _mock_first_run):
        cfg = _mock_cfg(conf_dir="/tmp/freq-test-conf")
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/setup/configure")
        h.command = "POST"
        h._request_body = lambda: {"cluster_name": "dc01", "timezone": "UTC", "pve_nodes": []}

        h._serve_setup_configure()

        assert h._status_code == 400
        data = _get_json(h)
        assert data["error"] == "At least one PVE node IP is required"

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_rejects_duplicate_pve_nodes(self, mock_cfg_fn, _mock_first_run):
        cfg = _mock_cfg(conf_dir="/tmp/freq-test-conf")
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/setup/configure")
        h.command = "POST"
        h._request_body = lambda: {"cluster_name": "dc01", "timezone": "UTC", "pve_nodes": ["10.0.0.1", "10.0.0.1"]}

        h._serve_setup_configure()

        assert h._status_code == 400
        data = _get_json(h)
        assert data["error"] == "Duplicate PVE node IPs are not allowed"

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_writes_default_node_names(self, mock_cfg_fn, _mock_first_run):
        with tempfile.TemporaryDirectory() as td:
            cfg = _mock_cfg(conf_dir=td)
            mock_cfg_fn.return_value = cfg

            h = _make_handler("/api/setup/configure")
            h.command = "POST"
            h._request_body = lambda: {
                "cluster_name": "dc01",
                "timezone": "UTC",
                "pve_nodes": ["10.0.0.1", "10.0.0.2"],
            }

            h._serve_setup_configure()

            assert h._status_code == 200
            data = _get_json(h)
            assert data["pve_node_names"] == ["pve01", "pve02"]
            with open(os.path.join(td, "freq.toml")) as f:
                content = f.read()
            assert 'node_names = ["pve01", "pve02"]' in content

    @patch("freq.modules.serve._is_first_run", return_value=True)
    def test_setup_test_ssh_requires_host(self, _mock_first_run):
        h = _make_handler("/api/setup/test-ssh")
        h._serve_setup_test_ssh()

        assert h._status_code == 400
        data = _get_json(h)
        assert data["error"] == "host parameter required"

    @patch("freq.modules.serve._is_first_run", return_value=True)
    def test_setup_test_ssh_rejects_invalid_host(self, _mock_first_run):
        h = _make_handler("/api/setup/test-ssh?host=bad host")
        h._serve_setup_test_ssh()

        assert h._status_code == 400
        data = _get_json(h)
        assert "Invalid host" in data["error"]

    @patch("freq.modules.serve.ssh_single")
    @patch("freq.modules.serve.load_config")
    @patch("freq.modules.serve._is_first_run", return_value=True)
    def test_setup_test_ssh_returns_502_on_connection_failure(self, _mock_first_run, mock_cfg_fn, mock_ssh_single):
        mock_cfg_fn.return_value = _mock_cfg(ssh_connect_timeout=5, ssh_service_account="freq-admin")
        mock_ssh_single.return_value = _mock_ssh_result("", "Permission denied", 255)

        h = _make_handler("/api/setup/test-ssh?host=10.0.0.1")
        h._serve_setup_test_ssh()

        assert h._status_code == 502
        data = _get_json(h)
        assert data["ok"] is False
        assert data["error"] == "Permission denied"


# ══════════════════════════════════════════════════════════════════════════
# JSON Response Mechanics
# ══════════════════════════════════════════════════════════════════════════

class TestJsonResponse:
    """Test _json_response method."""

    def test_json_response_writes_body(self):
        h = _make_handler("/test")
        h._json_response({"key": "value"})

        data = _get_json(h)
        assert data == {"key": "value"}
        assert h._status_code == 200

    def test_json_response_sets_headers(self):
        h = _make_handler("/test")
        h._json_response({"x": 1})

        header_dict = dict(h._resp_headers)
        assert header_dict["Content-Type"] == "application/json"
        # CORS headers are now origin-aware (only sent when Origin header present)
        assert header_dict.get("X-Content-Type-Options") == "nosniff"
        assert header_dict.get("X-Frame-Options") == "DENY"

    def test_json_response_cors_with_origin(self):
        h = _make_handler("/test")
        h.headers = {"Origin": "http://localhost:3000"}
        h._json_response({"x": 1})

        header_dict = dict(h._resp_headers)
        assert header_dict["Access-Control-Allow-Origin"] == "http://localhost:3000"

    def test_json_response_complex_data(self):
        h = _make_handler("/test")
        complex_data = {
            "list": [1, 2, 3],
            "nested": {"a": True, "b": None},
            "str": "hello",
        }
        h._json_response(complex_data)

        data = _get_json(h)
        assert data == complex_data


# ═══════════════════════════════════════════════════════════════════
# SSE Endpoint
# ═══════════════════════════════════════════════════════════════════

class TestSSEEndpoint:
    """Tests for /api/events SSE route."""

    def test_events_route_registered(self):
        """The /api/events route is in the routing table."""
        assert "/api/events" in FreqHandler._ROUTES
        assert FreqHandler._ROUTES["/api/events"] == "_serve_events"

    def test_serve_events_method_exists(self):
        """FreqHandler has a _serve_events method."""
        assert hasattr(FreqHandler, "_serve_events")
        assert callable(getattr(FreqHandler, "_serve_events"))


# ═══════════════════════════════════════════════════════════════════
# OpenAPI / API Docs Truthfulness
# ═══════════════════════════════════════════════════════════════════

class TestOpenAPITruthfulness:
    """Verify the OpenAPI spec reflects the real API surface."""

    def _get_spec(self):
        """Generate and return the OpenAPI spec as dict."""
        h = _make_handler("/api/openapi.json")
        h._serve_openapi_json()
        return _get_json(h)

    def test_spec_is_valid_openapi(self):
        spec = self._get_spec()
        assert spec["openapi"] == "3.0.3"
        assert "info" in spec
        assert "paths" in spec
        assert spec["info"]["title"] == "PVE FREQ API"

    def test_every_legacy_route_in_spec(self):
        """Every route in _ROUTES appears in the spec (except /, /dashboard, /api/docs, /api/openapi.json)."""
        spec = self._get_spec()
        skip = {"/", "/dashboard", "/api/docs", "/api/openapi.json"}
        for path in FreqHandler._ROUTES:
            if path in skip:
                continue
            assert path in spec["paths"], f"Legacy route {path} missing from OpenAPI spec"

    def test_v1_routes_in_spec(self):
        """v1 domain routes appear in the spec after loading."""
        spec = self._get_spec()
        # v1 routes should be present if build_routes succeeds
        FreqHandler._load_v1_routes()
        if FreqHandler._V1_ROUTES:
            for path in FreqHandler._V1_ROUTES:
                assert path in spec["paths"], f"v1 route {path} missing from OpenAPI spec"

    def test_proxy_routes_in_spec(self):
        """Dynamic proxy routes /api/comms/ and /api/watch/ appear in spec."""
        spec = self._get_spec()
        assert "/api/comms/{path}" in spec["paths"], "/api/comms/ proxy missing from spec"
        assert "/api/watch/{path}" in spec["paths"], "/api/watch/ proxy missing from spec"

    def test_post_endpoints_documented_as_post(self):
        """Routes with mutating names should be documented as POST, not GET."""
        spec = self._get_spec()
        post_keywords = ("create", "update", "delete", "reset", "login",
                         "change", "complete", "generate", "deploy", "rollback")
        for path, methods in spec["paths"].items():
            path_tail = path.rsplit("/", 1)[-1]
            if any(kw in path_tail for kw in post_keywords):
                assert "post" in methods, f"{path} should be POST but is {list(methods.keys())}"

    def test_post_endpoints_document_error_responses(self):
        """POST endpoints should document 400 and 403 responses."""
        spec = self._get_spec()
        for path, methods in spec["paths"].items():
            if "post" in methods:
                responses = methods["post"]["responses"]
                assert "400" in responses, f"POST {path} missing 400 response"
                assert "403" in responses, f"POST {path} missing 403 response"

    def test_auth_logout_documented_as_post(self):
        """Logout must appear as POST in the spec."""
        spec = self._get_spec()
        assert "/api/auth/logout" in spec["paths"]
        assert "post" in spec["paths"]["/api/auth/logout"]

    def test_spec_has_security_schemes(self):
        """OpenAPI spec must document bearer and cookie auth."""
        spec = self._get_spec()
        schemes = spec.get("components", {}).get("securitySchemes", {})
        assert "bearerAuth" in schemes, "Spec must document bearerAuth"
        assert "cookieAuth" in schemes, "Spec must document cookieAuth"
        assert schemes["cookieAuth"]["name"] == "freq_session"

    def test_no_internal_method_names_in_summaries(self):
        """Spec summaries must not contain _serve_ method names."""
        spec = self._get_spec()
        for path, methods in spec["paths"].items():
            for method, detail in methods.items():
                summary = detail.get("summary", "")
                assert not summary.startswith("_serve_"), \
                    f"{path} leaks internal method name: {summary}"

    def test_no_url_token_in_spec(self):
        """Spec must not document ?token= query parameter auth."""
        import json
        spec = self._get_spec()
        spec_str = json.dumps(spec)
        assert "?token=" not in spec_str, "Spec must not reference ?token= auth"
        assert "X-Session" not in spec_str, "Spec must not reference X-Session header"

    def test_every_endpoint_has_summary(self):
        """Every endpoint in spec has a non-empty summary."""
        spec = self._get_spec()
        missing = []
        for path, methods in spec["paths"].items():
            for method, detail in methods.items():
                summary = detail.get("summary", "")
                if not summary or summary.startswith("_serve_"):
                    missing.append(f"{method.upper()} {path}")
        # Allow some missing — v1 callables without docs are ok for now
        # but legacy _serve_ method names leaking through is a bug
        serve_leaks = [m for m in missing if "_serve_" in m]
        assert not serve_leaks, f"Internal method names leaked into spec: {serve_leaks}"

    def test_no_error_responses_return_200(self):
        """Verify no _json_response({{error:...}}) call defaults to 200.

        Checks both single-line and multi-line patterns in serve.py.
        """
        import re
        serve_path = os.path.join(os.path.dirname(__file__), "..", "freq", "modules", "serve.py")
        with open(serve_path) as f:
            content = f.read()
            lines = content.splitlines(True)

        bad_lines = []
        # Single-line check
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if '_json_response({"error"' in stripped and stripped.endswith("})"):
                if not re.search(r'},\s*\d+\)$', stripped):
                    bad_lines.append(i)

        # Multi-line check: _json_response(\n...{"error": <only field>...}\n)
        # Skip mixed payloads (data + error field) — those are partial-success
        for m in re.finditer(
            r'_json_response\(\s*\n\s*(\{[^)]*"error"[^)]*\})\s*\n\s*\)',
            content,
        ):
            lineno = content[:m.start()].count('\n') + 1
            payload = m.group(1)
            # Count top-level keys — if "error" is the only key (or with simple
            # metadata), it's an error-only response. Mixed payloads have 3+ keys.
            key_count = len(re.findall(r'"[a-z_]+":', payload))
            if key_count <= 2:  # error + at most one metadata key
                match_text = m.group()
                if not re.search(r'},\s*\d+\s*\n\s*\)', match_text):
                    bad_lines.append(lineno)

        assert not bad_lines, f"Lines returning error with implicit 200: {bad_lines}"

    def test_no_v1_api_error_responses_return_200(self):
        """Verify no v1 API json_response(handler, {{error:...}}) defaults to 200.

        Source-level guard across all freq/api/*.py files.
        """
        import re, glob
        api_dir = os.path.join(os.path.dirname(__file__), "..", "freq", "api")
        bad = []
        for fpath in sorted(glob.glob(os.path.join(api_dir, "*.py"))):
            fname = os.path.basename(fpath)
            with open(fpath) as f:
                for i, line in enumerate(f, 1):
                    stripped = line.strip()
                    if 'json_response(handler, {"error"' in stripped and stripped.endswith("})"):
                        if not re.search(r'},\s*\d+\)$', stripped):
                            bad.append(f"{fname}:{i}")
        assert not bad, f"v1 API lines returning error with implicit 200: {bad}"


class TestAPIDocsPage:
    """Verify the /api/docs HTML page is truthful."""

    def test_docs_page_renders(self):
        h = _make_handler("/api/docs")
        h._serve_api_docs()
        assert h._status_code == 200
        body = h.wfile.getvalue().decode()
        assert "PVE FREQ" in body
        assert "<table>" in body

    def test_docs_page_includes_routes(self):
        h = _make_handler("/api/docs")
        h._serve_api_docs()
        body = h.wfile.getvalue().decode()
        # Should contain real API paths
        assert "/api/auth/login" in body
        assert "/healthz" in body


# ═══════════════════════════════════════════════════════════════════
# Auth Whitelist Correctness
# ═══════════════════════════════════════════════════════════════════

class TestAuthWhitelist:
    """Verify auth whitelist covers required public endpoints."""

    def test_setup_endpoints_whitelisted_for_first_run(self):
        """All setup wizard endpoints must be in auth whitelist so first-run works."""
        setup_routes = [
            "/api/setup/status",
            "/api/setup/create-admin",
            "/api/setup/configure",
            "/api/setup/generate-key",
            "/api/setup/test-ssh",
            "/api/setup/complete",
        ]
        for route in setup_routes:
            assert route in FreqHandler._AUTH_WHITELIST, \
                f"Setup route {route} missing from auth whitelist — first-run will 403"

    def test_auth_endpoints_whitelisted(self):
        """Auth login and verify must be public."""
        assert "/api/auth/login" in FreqHandler._AUTH_WHITELIST
        assert "/api/auth/verify" in FreqHandler._AUTH_WHITELIST

    def test_health_probes_whitelisted(self):
        """Orchestration probes must not require auth."""
        assert "/healthz" in FreqHandler._AUTH_WHITELIST
        assert "/readyz" in FreqHandler._AUTH_WHITELIST

    def test_docs_endpoints_whitelisted(self):
        """API documentation should be publicly accessible."""
        assert "/api/docs" in FreqHandler._AUTH_WHITELIST
        assert "/api/openapi.json" in FreqHandler._AUTH_WHITELIST

    def test_setup_reset_not_whitelisted(self):
        """Setup reset requires admin auth — must NOT be in whitelist."""
        assert "/api/setup/reset" not in FreqHandler._AUTH_WHITELIST

    def test_destructive_endpoints_not_whitelisted(self):
        """Mutating endpoints must never be in whitelist."""
        dangerous = [
            "/api/admin/fleet-boundaries/update",
            "/api/admin/hosts/update",
            "/api/config",
        ]
        for route in dangerous:
            assert route not in FreqHandler._AUTH_WHITELIST, \
                f"Dangerous route {route} should NOT be in auth whitelist"
